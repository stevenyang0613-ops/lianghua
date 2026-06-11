import asyncio
import time as time_mod
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Callable, Awaitable
import logging
import pandas as pd

from app.models.convertible import ConvertibleQuote
from app.strategies import get_strategy, list_strategies, Strategy
from app.engine.storage import DataStorage
from app.engine.trade import TradeEngine
from app.engine.confidence import calc_confidence

logger = logging.getLogger(__name__)


@dataclass
class ExecutedPosition:
    """自动执行信号的持仓记录"""
    code: str
    name: str
    side: str  # 'buy' or 'sell'
    price: float
    volume: int
    ts: datetime

    def to_dict(self) -> dict:
        d = asdict(self)
        d['ts'] = self.ts.isoformat()
        return d


class TradeSignal:
    """交易信号"""

    def __init__(self, strategy: str, code: str, name: str,
                 action: str, price: float, reason: str,
                 confidence: float = 0.0):
        self.id = uuid.uuid4().hex[:12]
        self.strategy = strategy
        self.code = code
        self.name = name
        self.action = action  # 'buy' or 'sell'
        self.price = price
        self.reason = reason
        self.confidence = confidence
        self.ts = datetime.now()
        self.executed = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy": self.strategy,
            "code": self.code,
            "name": self.name,
            "action": self.action,
            "price": round(self.price, 3),
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
            "ts": self.ts.isoformat(),
            "executed": self.executed,
        }


class SignalEngine:
    """实时信号引擎 - 在每次行情更新时运行策略生成信号"""

    # 策略缓存TTL：6小时后自动重建，防止长期运行时数据漂移
    _CACHE_TTL_SECONDS = 6 * 3600

    def __init__(self):
        self._signals: list[TradeSignal] = []
        self._active_strategies: list[str] = ["dual_low"]
        self._subscribers: set[Callable[[list[TradeSignal]], Awaitable[None]]] = set()
        self._storage: Optional[DataStorage] = None
        self._trade_engine: Optional['TradeEngine'] = None
        self._auto_execute_threshold: float = 0.0
        self._executed_positions: list[ExecutedPosition] = []
        # 策略实例缓存: {strat_id: (Strategy, init_timestamp, params_sig)}
        self._strategy_cache: dict[str, tuple[Strategy, float, str]] = {}
        self._last_init_date: Optional[str] = None
        # 策略参数覆盖: {strat_id: {param_name: value}}
        self._strategy_params: dict[str, dict] = {}
        # 跨调用去重: {(code, strategy, action): (timestamp, price)}
        self._recent_signals: dict[tuple[str, str, str], tuple[float, float]] = {}
        self._dedup_window_seconds: int = 300
        self._dedup_price_threshold: float = 0.02

    def set_strategy_params(self, strat_id: str, params: dict) -> None:
        """设置策略参数覆盖。参数变更会自动使对应缓存失效。"""
        old_sig = self._params_signature(strat_id, self._strategy_params.get(strat_id, {}))
        self._strategy_params[strat_id] = params
        new_sig = self._params_signature(strat_id, params)
        if old_sig != new_sig:
            self.invalidate_cache(strat_id)

    def set_dedup_config(self, window_seconds: int | None = None, price_threshold: float | None = None) -> dict:
        """配置去重参数，返回当前配置"""
        if window_seconds is not None:
            self._dedup_window_seconds = max(0, window_seconds)
        if price_threshold is not None:
            self._dedup_price_threshold = max(0, min(1.0, price_threshold))
        # 持久化到存储
        if self._storage:
            self._storage.set_config("dedup_window_seconds", str(self._dedup_window_seconds))
            self._storage.set_config("dedup_price_threshold", str(self._dedup_price_threshold))
        return self.get_dedup_config()

    def get_dedup_config(self) -> dict:
        """获取当前去重配置"""
        return {"window_seconds": self._dedup_window_seconds, "price_threshold": self._dedup_price_threshold}

    @staticmethod
    def _params_signature(strat_id: str, params: dict) -> str:
        """生成参数签名字符串，用于检测参数变更"""
        if not params:
            return ""
        return f"{strat_id}:{sorted(params.items())}"

    def set_storage(self, storage: DataStorage) -> None:
        self._storage = storage
        self._load_executed_positions()
        # 恢复持久化的去重配置
        w = storage.get_config("dedup_window_seconds")
        if w is not None:
            try:
                self._dedup_window_seconds = max(0, int(w))
            except (ValueError, TypeError):
                pass
        t = storage.get_config("dedup_price_threshold")
        if t is not None:
            try:
                self._dedup_price_threshold = max(0, min(1.0, float(t)))
            except (ValueError, TypeError):
                pass
        # 恢复持久化的活跃策略
        saved_strategies = storage.get_config("active_strategies")
        if saved_strategies:
            try:
                import json
                strategies = json.loads(saved_strategies)
                if isinstance(strategies, list):
                    self._active_strategies = strategies
            except (json.JSONDecodeError, ValueError):
                pass

    @property
    def active_strategies(self) -> list[str]:
        return list(self._active_strategies)

    def set_active_strategies(self, strategies: list[str]):
        # 清除不再活跃的策略缓存
        removed = set(self._active_strategies) - set(strategies)
        for s in removed:
            entry = self._strategy_cache.pop(s, None)
            if entry:
                entry[0].on_destroy()
        # 清除刚被重新激活的策略的去重记录
        # 这样重新激活的策略的信号会立即显示,不会被旧的去重窗口抑制
        added = set(strategies) - set(self._active_strategies)
        if added:
            keys_to_remove = [k for k in self._recent_signals if k[1] in added]
            for k in keys_to_remove:
                del self._recent_signals[k]
        self._active_strategies = strategies
        # 持久化到存储
        if self._storage:
            import json
            self._storage.set_config("active_strategies", json.dumps(strategies))

    def invalidate_cache(self, strat_id: Optional[str] = None) -> None:
        """使策略缓存失效。strat_id=None时清除全部缓存。"""
        if strat_id is None:
            for entry in self._strategy_cache.values():
                entry[0].on_destroy()
            self._strategy_cache.clear()
        else:
            entry = self._strategy_cache.pop(strat_id, None)
            if entry:
                entry[0].on_destroy()

    def _process_strategies(
        self, df: pd.DataFrame, bonds: list[ConvertibleQuote]
    ) -> list[TradeSignal]:
        """同步执行所有活跃策略，返回信号列表（在线程池中运行以避免阻塞事件循环）"""
        signals: list[TradeSignal] = []
        today = str(datetime.now().date())
        date_changed = today != self._last_init_date
        now = time_mod.monotonic()

        for strat_id in self._active_strategies:
            try:
                current_sig = self._params_signature(strat_id, self._strategy_params.get(strat_id, {}))
                cached = self._strategy_cache.get(strat_id)
                if cached and not date_changed:
                    strategy, init_ts, cached_sig = cached
                    # TTL过期或参数签名变更则重建
                    if now - init_ts > self._CACHE_TTL_SECONDS or cached_sig != current_sig:
                        strategy.on_destroy()
                        cached = None
                else:
                    cached = None

                if cached:
                    strategy = cached[0]
                else:
                    strategy_cls = get_strategy(strat_id)
                    params = self._strategy_params.get(strat_id, {})
                    strategy = strategy_cls(**params)
                    strategy.on_init(df)
                    self._strategy_cache[strat_id] = (strategy, now, current_sig)

                result = strategy.on_data(df, 0)
                if result:
                    for sig in result:
                        bond = next(
                            (b for b in bonds if b.code == sig["code"]), None
                        )
                        confidence = calc_confidence(strat_id, bond, sig)
                        signals.append(
                            TradeSignal(
                                strategy=strat_id,
                                code=sig["code"],
                                name=bond.name if bond else sig.get("code", ""),
                                action=sig["action"],
                                price=sig["price"],
                                reason=sig.get("reason", ""),
                                confidence=confidence,
                            )
                        )
            except Exception as e:
                logger.warning(f"[Signal] Strategy {strat_id} failed: {e}")

        if date_changed:
            self._last_init_date = today

        return signals

    @staticmethod
    def _is_valid_for_signal(b: ConvertibleQuote) -> bool:
        """过滤不适合生成交易信号的债券

        包括:退市整理期、可交换债、价格异常、已公告强赎、
        强赎/到期最后交易日前 3 天(用户要求:即将赎回/退市前 3 天不能交易)。
        """
        from app.engine.filters import is_tradeable_bond
        return is_tradeable_bond(b)

    async def process_quotes(self, bonds: list[ConvertibleQuote]) -> list[TradeSignal]:
        """处理行情数据，生成交易信号"""
        signals: list[TradeSignal] = []

        # 过滤不适合交易的债券
        valid_bonds = [b for b in bonds if self._is_valid_for_signal(b)]

        # Build a simple DataFrame from current quotes
        rows = []
        for b in valid_bonds:
            rows.append({
                "code": b.code,
                "name": b.name,
                "price": b.price,
                "premium_ratio": b.premium_ratio,
                "volume": b.volume,
                "dual_low": b.dual_low,
                "date": datetime.now().date(),
            })

        if not rows:
            return signals

        df = pd.DataFrame(rows)

        # Run all strategies in a thread to avoid blocking the event loop
        signals = await asyncio.to_thread(self._process_strategies, df, bonds)

        if signals:
            # Deduplicate within this call: keep highest confidence per (code, strategy)
            seen: dict[tuple[str, str], TradeSignal] = {}
            for s in signals:
                key = (s.code, s.strategy)
                if key not in seen or s.confidence > seen[key].confidence:
                    seen[key] = s
            signals = list(seen.values())

            # Track which (code, strategy) the strategy wants to keep in the UI.
            # This is used to preserve existing signals that are still in the strategy output
            # even when the cross-call dedup suppresses their notification.
            strategy_keys = {(s.code, s.strategy) for s in signals}

            # Cross-call dedup: suppress signals already sent recently with same action & similar price
            now_ts = time_mod.monotonic()
            new_signals: list[TradeSignal] = []
            for s in signals:
                dedup_key = (s.code, s.strategy, s.action)
                prev = self._recent_signals.get(dedup_key)
                if prev:
                    prev_ts, prev_price = prev
                    price_close = abs(s.price - prev_price) / max(prev_price, 0.01) < self._dedup_price_threshold
                    if now_ts - prev_ts < self._dedup_window_seconds and price_close:
                        continue  # Skip notification, but keep the signal in self._signals
                self._recent_signals[dedup_key] = (now_ts, s.price)
                new_signals.append(s)

            # Clean up expired dedup entries
            expired = [k for k, (ts, _) in self._recent_signals.items() if now_ts - ts > self._dedup_window_seconds]
            for k in expired:
                del self._recent_signals[k]

            # Merge: preserve existing signals that the strategy still wants to keep
            # (and aren't executed) + add the new (non-deduped) signals.
            # This fixes the bug where repeated calls with the same data would clear
            # self._signals because all signals were deduped.
            # We exclude signals that are already in new_signals to avoid double-counting
            # the same (code, strategy) pair.
            new_keys = {(s.code, s.strategy) for s in new_signals}
            preserved = [
                s for s in self._signals
                if (s.code, s.strategy) in strategy_keys
                and (s.code, s.strategy) not in new_keys
                and not s.executed
            ]
            # Sort preserved by timestamp descending so newer ones come first
            preserved.sort(key=lambda s: s.ts, reverse=True)
            self._signals = new_signals + preserved

            # Only save/notify/auto-execute the truly new signals (not deduped)
            if new_signals:
                if self._storage:
                    self._storage.save_signals_batch([s.to_dict() for s in new_signals])
                self._auto_execute(new_signals)
                await self._notify(new_signals)

            # Return only the new (non-deduped) signals, matching the original
            # contract of process_quotes (returns signals that were newly
            # emitted to subscribers).
            return new_signals

        return signals

    @property
    def current_signals(self) -> list[dict]:
        return [s.to_dict() for s in self._signals if not s.executed]

    def mark_executed(self, code: str, strategy: str) -> None:
        for s in self._signals:
            if s.code == code and s.strategy == strategy and not s.executed:
                s.executed = True

    def set_trade_engine(self, engine: 'TradeEngine') -> None:
        self._trade_engine = engine

    def set_auto_execute_min_confidence(self, threshold: float) -> None:
        self._auto_execute_threshold = threshold

    def _auto_execute(self, signals: list[TradeSignal]) -> None:
        trade_engine = self._trade_engine
        if not trade_engine:
            return
        threshold = self._auto_execute_threshold
        if threshold <= 0:
            return

        batch_positions: list[dict] = []

        # 1. Process all sells first (freeing cash)
        for s in signals:
            if s.action == 'sell' and s.confidence >= threshold and not s.executed:
                try:
                    pos = next((p for p in trade_engine.positions if p.code == s.code), None)
                    volume = pos.volume if pos else 10
                    trade_engine.sell(code=s.code, name=s.name, price=s.price, volume=volume)
                    s.executed = True
                    self._executed_positions.append(ExecutedPosition(
                        code=s.code, name=s.name, side='sell',
                        price=s.price, volume=volume, ts=datetime.now(),
                    ))
                    batch_positions.append(self._executed_positions[-1].to_dict())
                    logger.info(f'[Signal] Auto-executed SELL {s.code} ({s.strategy}) at {s.price}')
                except Exception as e:
                    logger.warning(f'[Signal] Auto-execute sell failed {s.code}: {e}')

        # 2. Pre-compute buy candidates
        buy_candidates = [s for s in signals if s.action == 'buy' and s.confidence >= threshold and not s.executed]
        remaining = len(buy_candidates)

        # 3. Process buys with dynamic volume based on remaining count
        for s in buy_candidates:
            try:
                alloc = trade_engine.account.cash / max(remaining, 1)
                volume = max(1, int(alloc / s.price))
                trade_engine.buy(code=s.code, name=s.name, price=s.price, volume=volume)
                s.executed = True
                self._executed_positions.append(ExecutedPosition(
                    code=s.code, name=s.name, side='buy',
                    price=s.price, volume=volume, ts=datetime.now(),
                ))
                batch_positions.append(self._executed_positions[-1].to_dict())
                logger.info(f'[Signal] Auto-executed BUY {s.code} ({s.strategy}) at {s.price}')
            except Exception as e:
                logger.warning(f'[Signal] Auto-execute buy failed {s.code}: {e}')
            finally:
                remaining -= 1

        # 4. Batch save
        if self._storage and batch_positions:
            self._storage.save_executed_positions_batch(batch_positions)

    def cleanup_history(self, keep_days: int = 30) -> None:
        if self._storage:
            deleted = self._storage.cleanup_signal_history(keep_days)
            if deleted:
                logger.info(f'[Signal] Cleaned up {deleted} old signal records')
            deleted_ep = self._storage.cleanup_executed_positions(keep_days)
            if deleted_ep:
                logger.info(f'[Signal] Cleaned up {deleted_ep} old executed position records')

    def _load_executed_positions(self):
        if not self._storage:
            return
        saved = self._storage.get_executed_positions(limit=100)
        # Only load if current list is empty (fresh start)
        if not self._executed_positions:
            for s in reversed(saved):  # oldest first
                self._executed_positions.append(ExecutedPosition(
                    code=s.get('code', ''),
                    name=s.get('name', ''),
                    side=s.get('side', ''),
                    price=s.get('price', 0.0),
                    volume=s.get('volume', 0),
                    ts=s.get('ts', datetime.now()),
                ))

    @property
    def executed_positions(self) -> list[dict]:
        """返回已自动执行的持仓记录列表"""
        return [ep.to_dict() for ep in self._executed_positions]

    def clear_executed_positions(self) -> None:
        """清空已自动执行的持仓记录"""
        self._executed_positions.clear()

    def subscribe(self, callback: Callable[[list[TradeSignal]], Awaitable[None]]) -> None:
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable[[list[TradeSignal]], Awaitable[None]]) -> None:
        self._subscribers.discard(callback)

    async def _notify(self, signals: list[TradeSignal]) -> None:
        dead = []
        for cb in list(self._subscribers):
            try:
                await cb(signals)
            except Exception as e:
                logger.warning(f"[Signal] Subscriber error (removing): {e}")
                dead.append(cb)
        for cb in dead:
            self._subscribers.discard(cb)
