import asyncio
from datetime import datetime
from typing import Optional, Callable, Awaitable
import logging
import pandas as pd

from app.models.convertible import ConvertibleQuote
from app.strategies import get_strategy, list_strategies
from app.engine.storage import DataStorage

logger = logging.getLogger(__name__)


class TradeSignal:
    """交易信号"""

    def __init__(self, strategy: str, code: str, name: str,
                 action: str, price: float, reason: str,
                 confidence: float = 0.0):
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

    def __init__(self):
        self._signals: list[TradeSignal] = []
        self._active_strategies: list[str] = ["dual_low"]
        self._subscribers: set[Callable[[list[TradeSignal]], Awaitable[None]]] = set()
        self._storage: Optional[DataStorage] = None

    def set_storage(self, storage: DataStorage) -> None:
        self._storage = storage

    @property
    def active_strategies(self) -> list[str]:
        return list(self._active_strategies)

    def set_active_strategies(self, strategies: list[str]):
        self._active_strategies = strategies

    async def process_quotes(self, bonds: list[ConvertibleQuote]) -> list[TradeSignal]:
        """处理行情数据，生成交易信号"""
        signals: list[TradeSignal] = []

        # Build a simple DataFrame from current quotes
        rows = []
        for b in bonds:
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

        for strat_id in self._active_strategies:
            try:
                strategy_cls = get_strategy(strat_id)
                strategy = strategy_cls()
                strategy.on_init(df)
                result = strategy.on_data(df, 0)
                if result:
                    for sig in result:
                        bond = next((b for b in bonds if b.code == sig["code"]), None)
                        confidence = self._calc_confidence(strat_id, bond, sig)
                        signals.append(TradeSignal(
                            strategy=strat_id,
                            code=sig["code"],
                            name=bond.name if bond else sig.get("code", ""),
                            action=sig["action"],
                            price=sig["price"],
                            reason=sig.get("reason", ""),
                            confidence=confidence,
                        ))
            except Exception as e:
                logger.warning(f"[Signal] Strategy {strat_id} failed: {e}")

        if signals:
            self._signals = signals
            # Save to DuckDB history
            if self._storage:
                self._storage.save_signals_batch([s.to_dict() for s in signals])
            await self._notify(signals)

        return signals

    def _calc_confidence(self, strategy: str, bond: Optional[ConvertibleQuote],
                         signal: dict) -> float:
        """计算信号置信度 (0~1)"""
        if not bond:
            return 0.5

        score = 0.5

        if strategy == "dual_low":
            # Lower dual_low = higher confidence
            if bond.dual_low < 130:
                score += 0.3
            elif bond.dual_low < 150:
                score += 0.15
            # Low premium boosts confidence
            if bond.premium_ratio < 10:
                score += 0.2
            elif bond.premium_ratio < 20:
                score += 0.1
        elif strategy == "low_premium":
            if bond.premium_ratio < 5:
                score += 0.3
            elif bond.premium_ratio < 10:
                score += 0.15
        elif strategy == "momentum":
            if bond.change_pct and bond.change_pct > 2:
                score += 0.2
                if bond.volume and bond.volume > 1e8:
                    score += 0.1

        return min(score, 1.0)

    @property
    def current_signals(self) -> list[dict]:
        return [s.to_dict() for s in self._signals if not s.executed]

    def mark_executed(self, code: str, strategy: str) -> None:
        for s in self._signals:
            if s.code == code and s.strategy == strategy and not s.executed:
                s.executed = True

    def subscribe(self, callback: Callable[[list[TradeSignal]], Awaitable[None]]) -> None:
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable[[list[TradeSignal]], Awaitable[None]]) -> None:
        self._subscribers.discard(callback)

    async def _notify(self, signals: list[TradeSignal]) -> None:
        for cb in list(self._subscribers):
            try:
                await cb(signals)
            except Exception as e:
                logger.warning(f"[Signal] Subscriber error: {e}")
