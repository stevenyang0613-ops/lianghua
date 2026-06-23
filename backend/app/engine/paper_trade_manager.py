"""
模拟盘管理器 — 每个策略拥有独立的 TradeEngine 账户，
自动接收行情、运行策略、执行信号。

架构:
  MarketEngine.subscribe(paper_trade_manager.on_quotes)
  → on_quotes(bonds) → 每个 running 账户 → strategy.on_data() → 自动买卖
"""

import asyncio
import json
import time as time_mod
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from app.engine.filters import is_tradeable_bond
from app.engine.storage import DataStorage
from app.engine.trade import TradeEngine
from app.models.convertible import ConvertibleQuote
from app.models.trade import OrderStatus, OrderSide
from app.strategies import get_strategy, Strategy
from app.adapters.broker_sim import SimBroker

import logging

logger = logging.getLogger(__name__)


# ── 数据类 ──────────────────────────────────────────────

@dataclass
class PaperAccount:
    """单个策略的模拟盘账户"""
    id: str
    strategy_id: str
    strategy_name: str
    trade_engine: TradeEngine
    strategy: Optional[Strategy] = None
    is_running: bool = False
    initial_cash: float = 100_000_000.0
    created_at: datetime = field(default_factory=datetime.now)
    params: dict = field(default_factory=dict)

    # 去重: {(code, action): (timestamp, price)}
    _recent_signals: dict = field(default_factory=dict)
    _dedup_window_seconds: int = 300
    _dedup_price_threshold: float = 0.02

    # 权益快照节流: 上次快照时间
    _last_equity_ts: float = 0.0
    _equity_snapshot_interval: float = 300.0  # 5 分钟

    # 交易日计数: 用于策略 idx 参数
    _trade_day_count: int = 0
    _last_trade_date: str = ""
    _needs_init: bool = False  # 延迟初始化标记

    # 模拟日期序列: 与策略 _dates 对齐，确保 idx 始终有效
    _sim_dates: list[str] = field(default_factory=list)
    _sim_idx: int = 0  # 策略运行索引（初始化为历史数据最后一个索引）

    def to_dict(self) -> dict:
        acc = self.trade_engine.account
        # 获取策略参数定义
        strategy_cls = None
        try:
            from app.strategies import STRATEGY_REGISTRY
            strategy_cls = STRATEGY_REGISTRY.get(self.strategy_id)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
            pass
        param_defs = []
        if strategy_cls and hasattr(strategy_cls, 'params'):
            for p in strategy_cls.params:
                param_defs.append({
                    "name": p.name,
                    "label": p.label,
                    "type": p.type,
                    "default": p.default,
                    "min_val": p.min_val,
                    "max_val": p.max_val,
                    "options": p.options,
                    "description": p.description,
                })
        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "is_running": self.is_running,
            "initial_cash": self.initial_cash,
            "params": self.params,
            "param_defs": param_defs,
            "created_at": self.created_at.isoformat(),
            "total_asset": acc.total_asset,
            "cash": acc.cash,
            "market_value": acc.market_value,
            "total_profit": acc.total_profit,
            "total_profit_pct": round(
                (acc.total_asset - self.initial_cash) / self.initial_cash * 100, 2
            ) if self.initial_cash > 0 else 0.0,
            # 调仓倒计时信息
            "trade_day_count": self._trade_day_count,
            "rebalance_days": self.params.get("rebalance_days", 7) if isinstance(self.params, dict) else 7,
            # 关键: 返回真实的距离下一次调仓的 idx 差值
            "next_rebalance_idx": self._sim_idx + (self.params.get("rebalance_days", 7) - self._sim_idx % self.params.get("rebalance_days", 7)) % self.params.get("rebalance_days", 7) if isinstance(self.params, dict) and self.params.get("rebalance_days", 7) > 0 else self._sim_idx,


# ── 核心管理器 ──────────────────────────────────────────

class PaperTradeManager:
    """管理多个独立模拟盘账户"""

    # 支持的三个核心策略
    CORE_STRATEGIES = {
        "xuanji_twelve": "璇玑十二因子",
        "xibu_seven": "西部七维",
        "fusion": "融合策略",
    }

    # 最优参数（基于策略设计逻辑 + 回测经验）
    OPTIMAL_PARAMS = {
        "xibu_seven": {
            "hold_count": 60, "buffer_size": 8, "buffer_days": 5,
            "min_credit_score": 55, "max_premium": 100, "min_remaining_months": 6,
            "aum_level": "small", "market_env": "neutral",
            "rebalance_days": 5, "min_hold_days": 3,
            "momentum_filter": True, "position_sizing": "score_weighted",
        },
        "xuanji_twelve": {
            "hold_count": 25, "rebalance_days": 7, "market_state": "auto",
            "max_premium": 50, "min_price": 90, "max_price": 150,
            "delta_hedge_pct": 15, "vol_adjust": 0.80,
            "stop_loss_pct": -8.0, "trailing_stop_pct": -3.0,
            "portfolio_stop_loss": -15.0, "icir_lookback": 60,
            "buffer_size": 3, "buffer_days": 3,
            "min_credit_score": 60, "min_liquidity": 500,
        },
        "fusion": {
            "hold_count": 25, "rebalance_days": 7,
            "xuanji_hold_count": 50, "xibu_hold_count": 40,
            "buffer_size": 3, "buffer_days": 3, "min_credit_score": 55,
            "max_premium": 60, "min_price": 90, "max_price": 150,
            "trailing_stop_pct": -3.0, "portfolio_stop_loss": -15.0,
        },
    }

    @classmethod
    def get_optimal_params(cls, strategy_id):
        return dict(cls.OPTIMAL_PARAMS.get(strategy_id, {}))

    def __init__(
        self,
        storage: DataStorage,
        market_engine: Optional[object] = None,
    ):
        self._accounts: dict[str, PaperAccount] = {}
        self._storage = storage
        self._market_engine = market_engine

    # ── 账户 CRUD ────────────────────────────────────

    def create_account(
        self,
        strategy_id: str,
        initial_cash: float = 100_000_000.0,
        params: Optional[dict] = None,
    ) -> PaperAccount:
        """创建模拟盘账户"""
        from app.strategies import STRATEGY_REGISTRY
        if strategy_id not in STRATEGY_REGISTRY:
            raise ValueError(f"Unknown strategy: {strategy_id}. Available: {list(STRATEGY_REGISTRY.keys())}")

        strategy_cls = STRATEGY_REGISTRY[strategy_id]
        strategy_name = getattr(strategy_cls, 'name', strategy_id)
        account_id = uuid.uuid4().hex[:12]
        params = params or {}

        broker = SimBroker(initial_cash=initial_cash)
        trade_engine = TradeEngine(broker=broker)

        account = PaperAccount(
            id=account_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            trade_engine=trade_engine,
            initial_cash=initial_cash,
            params=params,
            created_at=datetime.now(),
        )

        self._accounts[account_id] = account

        # 持久化
        self._save_account(account)

        logger.info(
            f"[PaperTrade] Created account {account_id} "
            f"for {strategy_name} ({strategy_id}), cash={initial_cash}"
        )
        return account

    def delete_account(self, account_id: str) -> None:
        """删除模拟盘账户"""
        account = self._accounts.pop(account_id, None)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        if account.is_running:
            account.is_running = False
        if account.strategy:
            account.strategy.on_destroy()
        # 从 DB 删除
        try:
            with self._storage._write() as conn:
                conn.execute("DELETE FROM paper_accounts WHERE id = ?", (account_id,))
                conn.execute("DELETE FROM paper_equity WHERE account_id = ?", (account_id,))
        except Exception as e:
            logger.warning(f"[PaperTrade] Failed to delete account {account_id} from DB: {e}")
        logger.info(f"[PaperTrade] Deleted account {account_id}")

    def get_account(self, account_id: str) -> dict:
        """获取账户摘要"""
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        return account.to_dict()

    def list_accounts(self) -> list[dict]:
        """列出所有账户"""
        return [acc.to_dict() for acc in self._accounts.values()]

    # ── 启动/停止 ────────────────────────────────────

    def start_account(self, account_id: str) -> None:
        """启动模拟盘 — 策略初始化，开始接收行情"""
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        if account.is_running:
            return  # 已在运行

        # 创建策略实例
        strategy_cls = get_strategy(account.strategy_id)
        account.strategy = strategy_cls(**account.params)

        # ── 关键: 调用 on_init(df) 初始化策略 ──
        # 从 MarketEngine 获取当前行情构建初始 DataFrame
        init_df = self._build_init_df()
        if init_df is not None and len(init_df) > 0:
            try:
                account.strategy.on_init(init_df)
                # 初始化模拟索引为历史数据的最后一个索引，使 idx 始终指向 "今天"
                account._sim_idx = max(0, len(getattr(account.strategy, '_dates', [])) - 1)
                # 关键修复: 确保 _sim_idx 对齐调仓日，否则启动后可能需等待多个交易日才调仓
                # 对齐到前一个调仓日，这样 _process_account 中首次 +=1 后正好落在调仓日
                if hasattr(account.strategy, 'get_param'):
                    rebalance_days = account.strategy.get_param('rebalance_days')
                    if rebalance_days and rebalance_days > 0:
                        orig_idx = account._sim_idx
                        aligned = (account._sim_idx // rebalance_days) * rebalance_days
                        account._sim_idx = aligned - 1 if aligned > 0 else 0
                        if account._sim_idx != orig_idx:
                            logger.info(
                                f"[PaperTrade] Aligned sim_idx {orig_idx} -> {account._sim_idx} "
                                f"(aligned={aligned}, rebalance_days={rebalance_days})"
                            )
                account._sim_dates = [str(d) for d in getattr(account.strategy, '_dates', [])]
                logger.info(
                    f"[PaperTrade] Initialized strategy for account {account_id} "
                    f"with {len(init_df)} bonds, sim_idx={account._sim_idx}"
                )
            except Exception as e:
                logger.warning(
                    f"[PaperTrade] on_init failed for account {account_id}: {e}"
                )
        else:
            logger.warning(
                f"[PaperTrade] No market data for on_init, account {account_id} "
                "will initialize on first quote tick"
            )
            account._needs_init = True
            account._sim_idx = 0
            account._sim_dates = []

        account.is_running = True

        # 持久化状态
        self._update_account_running(account_id, True)

        logger.info(f"[PaperTrade] Started account {account_id} ({account.strategy_name})")

    def stop_account(self, account_id: str) -> None:
        """停止模拟盘"""
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        account.is_running = False
        if account.strategy:
            account.strategy.on_destroy()
            account.strategy = None

        self._update_account_running(account_id, False)
        logger.info(f"[PaperTrade] Stopped account {account_id}")

    def reset_account(self, account_id: str) -> None:
        """重置账户到初始状态"""
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")

        was_running = account.is_running
        if was_running:
            account.is_running = False
            if account.strategy:
                account.strategy.on_destroy()
                account.strategy = None

        account.trade_engine.reset()
        account._recent_signals.clear()
        account._trade_day_count = 0
        account._last_trade_date = ""
        account._needs_init = False
        account._sim_dates = []
        account._sim_idx = 0

        if was_running:
            # 重新初始化策略
            strategy_cls = get_strategy(account.strategy_id)
            account.strategy = strategy_cls(**account.params)
            # 初始化策略数据
            init_df = self._build_init_df()
            if init_df is not None and len(init_df) > 0:
                try:
                    account.strategy.on_init(init_df)
                    account._sim_idx = max(0, len(getattr(account.strategy, '_dates', [])) - 1)
                    # 关键修复: 重置后也要对齐到前一个调仓日
                    if hasattr(account.strategy, 'get_param'):
                        rebalance_days = account.strategy.get_param('rebalance_days')
                        if rebalance_days and rebalance_days > 0:
                            aligned = (account._sim_idx // rebalance_days) * rebalance_days
                            account._sim_idx = aligned - 1 if aligned > 0 else 0
                    account._sim_dates = [str(d) for d in getattr(account.strategy, '_dates', [])]
                except Exception as e:
                    logger.warning(f"[PaperTrade] on_init after reset failed for {account_id}: {e}")
            else:
                account._needs_init = True
                account._sim_idx = 0
                account._sim_dates = []
            account.is_running = True

        logger.info(f"[PaperTrade] Reset account {account_id}")

    # ── 参数更新 ──────────────────────────────────────

    def update_params(self, account_id: str, params: dict) -> None:
        """更新策略参数（需要重启策略才能生效）"""
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")

        account.params = params

        # 如果正在运行，重启策略
        if account.is_running and account.strategy:
            account.strategy.on_destroy()
            strategy_cls = get_strategy(account.strategy_id)
            account.strategy = strategy_cls(**params)
            # 重新初始化策略数据
            init_df = self._build_init_df()
            if init_df is not None and len(init_df) > 0:
                try:
                    account.strategy.on_init(init_df)
                    account._sim_idx = max(0, len(getattr(account.strategy, '_dates', [])) - 1)
                    # 关键修复: 参数更新后也要对齐到前一个调仓日
                    if hasattr(account.strategy, 'get_param'):
                        rebalance_days = account.strategy.get_param('rebalance_days')
                        if rebalance_days and rebalance_days > 0:
                            aligned = (account._sim_idx // rebalance_days) * rebalance_days
                            account._sim_idx = aligned - 1 if aligned > 0 else 0
                    account._sim_dates = [str(d) for d in getattr(account.strategy, '_dates', [])]
                except Exception as e:
                    logger.warning(f"[PaperTrade] on_init after param update failed for {account_id}: {e}")
            else:
                account._needs_init = True
                account._sim_idx = 0
                account._sim_dates = []

        # 持久化
        self._save_account(account)
        logger.info(f"[PaperTrade] Updated params for account {account_id}")

    def force_rebalance(self, account_id: str) -> dict:
        """强制策略立即调仓（无视调仓间隔天数限制）

        策略按调仓间隔（如 7 天）决定何时产生信号，新启动的账户往往
        还没到第一次调仓日就处于"空仓等待"状态。此方法临时将
        rebalance_days 设为 1（每天都是调仓日），触发策略生成信号并执行，
        之后恢复原始参数，不影响后续正常运行。

        Returns:
            {"status": "ok"/"no_signals", "signals": [...], "positions": [...]}
        """
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")

        # 未运行时先启动
        if not account.is_running:
            self.start_account(account_id)

        if account.strategy is None:
            raise RuntimeError("策略未初始化，请稍后再试")

        strategy = account.strategy
        today_str = str(datetime.now().date())

        # ── 获取最新行情（优先实时，回退历史快照） ──
        bonds = None
        df = pd.DataFrame()
        valid_bonds = []
        if self._market_engine is not None:
            bonds = getattr(self._market_engine, 'latest_quotes', None)
            if bonds is None:
                get_fn = getattr(self._market_engine, 'get_latest_quotes', None)
                if get_fn:
                    try:
                        bonds = get_fn()
                    except Exception:
                        pass
        if bonds:
            valid_bonds = [b for b in bonds if is_tradeable_bond(b)]
            rows = []
            for b in valid_bonds:
                row = b.to_strategy_dict()
                row["date"] = datetime.now().date()
                rows.append(row)
            df = pd.DataFrame(rows) if rows else pd.DataFrame()
            if not df.empty:
                account.trade_engine.update_prices(valid_bonds)

        # 无实时行情时，从数据库历史快照构建 DataFrame
        if df.empty:
            logger.info(f"[PaperTrade] force_rebalance: no live quotes, using storage fallback")
            init_df = self._build_init_df()
            if init_df is not None and len(init_df) > 0:
                # 取最新交易日的数据
                init_df = init_df.sort_values("date")
                last_date = init_df["date"].iloc[-1]
                df = init_df[init_df["date"] == last_date].copy()
                # 标准化列名（_build_init_df 用 close_price 作为 price 别名）
                if "close_price" in df.columns and "price" not in df.columns:
                    df = df.rename(columns={"close_price": "price"})
                if not df.empty:
                    logger.info(
                        f"[PaperTrade] force_rebalance: loaded {len(df)} bonds "
                        f"from storage date={last_date}"
                    )

        if df.empty:
            raise RuntimeError("无行情数据且无历史快照，请等待行情推送后再试")

        # ── 保存原始状态 ──
        original_idx = account._sim_idx
        original_dates = list(getattr(strategy, '_dates', []))
        original_strategy_rebalance = strategy._params.get('rebalance_days', 7)
        saved_states: dict = {}

        if hasattr(strategy, '_last_rebalance_idx'):
            saved_states['_last_rebalance_idx'] = strategy._last_rebalance_idx
        if hasattr(strategy, '_portfolio_stop_trigger_idx'):
            saved_states['_portfolio_stop_trigger_idx'] = strategy._portfolio_stop_trigger_idx

        # ── 确保今天在策略 _dates 和 _date_data_map 中 ──
        if today_str not in original_dates:
            strategy._dates = original_dates + [today_str]
        today_idx = len(strategy._dates) - 1

        if hasattr(strategy, '_date_data_map'):
            if today_str not in strategy._date_data_map:
                strategy._date_data_map[today_str] = df

        # ── 临时设置：rebalance_days=1 → 每次都是调仓日 ──
        strategy._params['rebalance_days'] = 1
        if hasattr(strategy, '_last_rebalance_idx'):
            strategy._last_rebalance_idx = -999  # (idx - (-999)) >= 1 永远成立
        if hasattr(strategy, '_portfolio_stop_trigger_idx'):
            strategy._portfolio_stop_trigger_idx = -1  # 清除止损触发

        account._sim_idx = today_idx

        try:
            result = strategy.on_data(df, today_idx)

            if not result:
                return {"status": "no_signals", "message": "策略在当前行情下未产生买入信号", "signals": []}

            # ── 构建信号（去重逻辑同 _process_account） ──
            now = time_mod.time()
            signals_to_execute = []
            for sig in result:
                code = sig.get("code", "")
                action = sig.get("action", "")
                price = sig.get("price")
                if price is None or (isinstance(price, (int, float)) and price <= 0):
                    continue
                # 去重
                dedup_key = (code, action)
                prev = account._recent_signals.get(dedup_key)
                if prev:
                    prev_ts, prev_price = prev
                    price_close = abs(price - prev_price) / max(prev_price, 0.01) < account._dedup_price_threshold
                    if now - prev_ts < account._dedup_window_seconds and price_close:
                        continue
                account._recent_signals[dedup_key] = (now, price)
                bond = next((b for b in valid_bonds if b.code == code), None)
                if not bond:
                    continue
                signals_to_execute.append({
                    "code": code, "name": bond.name, "action": action,
                    "price": price, "reason": sig.get("reason", ""),
                    "confidence": sig.get("confidence", 0.0),
                })

            if not signals_to_execute:
                return {"status": "no_signals", "message": "去重后无有效信号", "signals": []}

            self._execute_signals(account, signals_to_execute)
            self._save_account(account)
            self._save_signals(account, signals_to_execute)
            self._maybe_save_equity(account, now)

            pos_list = []
            for p in account.trade_engine.positions:
                pos_list.append({
                    "code": p.code, "name": p.name,
                    "volume": p.volume,
                    "cost_price": round(p.cost_price, 3) if p.cost_price else 0,
                    "market_value": round(p.market_value, 2) if p.market_value else 0,
                })

            return {
                "status": "ok",
                "signals": signals_to_execute,
                "positions": pos_list,
            }
        finally:
            # ── 恢复原始状态 ──
            account._sim_idx = original_idx
            strategy._params['rebalance_days'] = original_strategy_rebalance
            strategy._dates = original_dates
            if hasattr(strategy, '_date_data_map') and today_str in strategy._date_data_map:
                try:
                    del strategy._date_data_map[today_str]
                except Exception:
                    pass
            for key, value in saved_states.items():
                setattr(strategy, key, value)

    # ── 数据查询 ──────────────────────────────────────

    def get_positions(self, account_id: str) -> list[dict]:
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        positions = account.trade_engine.positions
        return [
            {
                "code": p.code,
                "name": p.name,
                "volume": p.volume,
                "available_volume": p.available_volume,
                "cost_price": p.cost_price,
                "current_price": p.current_price,
                "market_value": round(p.market_value, 2),
                "profit_pct": p.profit_pct,
                "profit_amount": p.profit_amount,
            }
            for p in positions
        ]

    def get_orders(self, account_id: str) -> list[dict]:
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        orders = sorted(account.trade_engine.orders, key=lambda o: o.created_at, reverse=True)
        return [
            {
                "id": o.id,
                "code": o.code,
                "name": o.name,
                "side": o.side.value if isinstance(o.side, OrderSide) else o.side,
                "type": o.type.value,
                "price": o.price,
                "volume": o.volume,
                "filled_volume": o.filled_volume,
                "status": o.status.value if isinstance(o.status, OrderStatus) else o.status,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "updated_at": o.updated_at.isoformat() if o.updated_at else None,
                "reject_reason": o.reject_reason or "",
            }
            for o in orders
        ]

    def get_equity_curve(self, account_id: str, days: int = 30) -> list[dict]:
        """从 DB 查询权益曲线"""
        try:
            # DuckDB: 用 date_add + 参数化避免字符串拼接
            cutoff = datetime.now() - timedelta(days=days)
            cursor = self._storage.conn.execute("""
                SELECT ts, total_asset, cash, market_value, total_profit, total_profit_pct
                FROM paper_equity
                WHERE account_id = ?
                  AND ts >= ?
                ORDER BY ts ASC
            """, (account_id, cutoff))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception:
            # fallback: 从当前账户直接返回一个点
            account = self._accounts.get(account_id)
            if account is None:
                return []
            acc = account.trade_engine.account
            return [{
                "ts": datetime.now().isoformat(),
                "total_asset": acc.total_asset,
                "cash": acc.cash,
                "market_value": acc.market_value,
                "total_profit": acc.total_profit,
                "total_profit_pct": round(
                    (acc.total_asset - account.initial_cash) / account.initial_cash * 100, 2
                ) if account.initial_cash > 0 else 0.0,
            }]

    def get_signals(self, account_id: str, limit: int = 50) -> list[dict]:
        """获取信号历史（从 signal_history 按 strategy 过滤）"""
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        # 用 strategy_id 作为 filter
        try:
            cursor = self._storage.conn.execute("""
                SELECT * FROM signal_history
                WHERE strategy = ?
                ORDER BY ts DESC
                LIMIT ?
            """, (f"paper_{account.strategy_id}", limit))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception:
            return []

    # ── 行情回调（核心逻辑）──────────────────────────

    def _build_init_df(self) -> Optional[pd.DataFrame]:
        """从 daily_snapshots / quotes_history 加载60天历史数据 + MarketEngine 实时行情构建策略初始化 DataFrame。
        
        策略 on_init 需要历史数据计算动量(5/10/20/60日位移)和HV，
        仅用当天快照会导致这些因子全部为 NaN。
        
        优先从 daily_snapshots 读取（snapshot_date 已索引，无全表扫描），
        回退到 quotes_history 的 DISTINCT CAST(timestamp AS DATE)。
        """
        all_rows = []
        
        # ── 1. 从 daily_snapshots 加载历史数据（snapshot_date 已索引） ──
        if self._storage:
            try:
                # 优先使用 daily_snapshots（snapshot_date 有索引，查询 O(logN)）
                date_cursor = self._storage.conn.execute("""
                    SELECT DISTINCT snapshot_date
                    FROM daily_snapshots
                    WHERE snapshot_date >= CURRENT_DATE - INTERVAL '180 days'
                    ORDER BY snapshot_date DESC
                    LIMIT 60
                """)
                trading_dates = [str(row[0]) for row in date_cursor.fetchall()]
                
                if trading_dates:
                    placeholders = ",".join("?" for _ in trading_dates)
                    cursor = self._storage.conn.execute(f"""
                        SELECT code, name, close_price AS price, premium_ratio, volume, dual_low,
                               ytm, remaining_years, change_pct, stock_price, stock_change_pct,
                               conversion_value, snapshot_date AS date,
                               momentum_5d, momentum_10d, momentum_20d, momentum_60d,
                               hv, rating_score, pure_bond_premium_ratio, bond_value,
                               industry, pe, pb, roe, gpm, call_status, is_called, forced_call_days,
                               cagr, debt_ratio, buyback_amount, mgmt_buy_price, event_score,
                               conversion_price, sentiment_score
                        FROM daily_snapshots
                        WHERE snapshot_date IN ({placeholders})
                        ORDER BY snapshot_date ASC
                    """, trading_dates)
                    columns = [desc[0] for desc in cursor.description]
                    hist_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    all_rows.extend(hist_rows)
                    logger.info(
                        f"[PaperTrade] _build_init_df: loaded {len(hist_rows)} rows "
                        f"from {len(trading_dates)} trading days (daily_snapshots)"
                    )

                    # ── 数据天数不足时从 quotes_history 补充早期数据 ──
                    # 动量5d至少需5个交易日，60d需60个交易日
                    # 若 daily_snapshots 天数不足，从 quotes_history 补充更早的日期
                    # 使用 < earliest_date 范围过滤，避免 NOT IN 子查询全表扫描
                    MIN_TRADING_DAYS = 60  # 需要60天才能算 momentum_60d
                    if len(trading_dates) < MIN_TRADING_DAYS and trading_dates:
                        try:
                            supplement_needed = MIN_TRADING_DAYS - len(trading_dates)
                            # trading_dates 来自 ORDER BY snapshot_date DESC，[-1] 是最早日期
                            earliest_date = trading_dates[-1]
                            if not earliest_date:
                                logger.debug("[PaperTrade] _build_init_df: earliest_date is empty, skip supplement")
                            else:
                                # 收集 daily_snapshots 中已有的 code 集合，补充时只加载这些 code
                                existing_codes = list({r["code"] for r in all_rows if "code" in r and r["code"]})
                                supp_cursor = self._storage.conn.execute("""
                                    SELECT DISTINCT CAST(timestamp AS DATE) AS td
                                    FROM quotes_history
                                    WHERE CAST(timestamp AS DATE) < ?
                                    ORDER BY td DESC
                                    LIMIT ?
                                """, (earliest_date, supplement_needed))
                                supp_dates = [str(row[0]) for row in supp_cursor.fetchall()]
                                if supp_dates and existing_codes:
                                    # 使用 DuckDB 临时表代替 IN (?) 分批，减少参数绑定开销
                                    # 用唯一表名避免并发场景冲突
                                    conn = self._storage.conn
                                    tmp_table = f"_supp_codes_{uuid.uuid4().hex[:8]}"
                                    # 防御性校验：确保表名只含字母数字和下划线
                                    if not tmp_table.replace("_", "").isalnum():
                                        logger.warning("[PaperTrade] Invalid temp table name, skipping supplement")
                                        tmp_table = None
                                    all_supp_rows: list[dict] = []
                                    if tmp_table:
                                        try:
                                            conn.execute(f"CREATE TEMP TABLE {tmp_table}(code VARCHAR)")
                                            # 分批插入（每批 500）
                                            for bs in range(0, len(existing_codes), 500):
                                                batch = existing_codes[bs:bs + 500]
                                                conn.executemany(
                                                    f"INSERT INTO {tmp_table} VALUES (?)",
                                                    [(c,) for c in batch]
                                                )
                                            supp_date_ph = ",".join("?" for _ in supp_dates)
                                            supp_cur = conn.execute(f"""
                                                SELECT q.code, q.name, q.price, q.premium_ratio, q.volume, q.dual_low,
                                                       q.ytm, q.remaining_years, q.change_pct, q.stock_price, q.stock_change_pct,
                                                       q.conversion_value, q.momentum_5d, q.momentum_10d,
                                                       q.momentum_20d, q.momentum_60d, q.timestamp,
                                                       q.hv, q.rating_score, q.pure_bond_premium_ratio, q.bond_value,
                                                       q.industry, q.pe, q.pb, q.roe, q.gpm, q.call_status, q.is_called, q.forced_call_days,
                                                       q.cagr, q.debt_ratio, q.buyback_amount, q.mgmt_buy_price, q.event_score,
                                                       q.conversion_price, q.sentiment_score
                                                FROM quotes_history q
                                                INNER JOIN {tmp_table} s ON q.code = s.code
                                                WHERE CAST(q.timestamp AS DATE) IN ({supp_date_ph})
                                                ORDER BY q.timestamp ASC
                                            """, supp_dates)
                                            supp_columns = [desc[0] for desc in supp_cur.description]
                                            all_supp_rows = [dict(zip(supp_columns, row)) for row in supp_cur.fetchall()]
                                        finally:
                                            conn.execute(f"DROP TABLE IF EXISTS {tmp_table}")
                                    if all_supp_rows:
                                        all_rows.extend(all_supp_rows)
                                        logger.info(
                                            f"[PaperTrade] _build_init_df: supplemented {len(all_supp_rows)} rows "
                                            f"from {len(supp_dates)} earlier trading days, {len(existing_codes)} codes "
                                            f"(quotes_history + temp table, before {earliest_date})"
                                        )
                        except Exception as supp_e:
                            logger.debug(f"[PaperTrade] _build_init_df supplement from quotes_history failed: {supp_e}")
                # 回退: daily_snapshots 无数据，从 quotes_history 加载
                else:
                    date_cursor = self._storage.conn.execute("""
                        SELECT DISTINCT CAST(timestamp AS DATE) AS td
                        FROM quotes_history
                        WHERE timestamp >= CURRENT_TIMESTAMP - INTERVAL '180 days'
                        ORDER BY td DESC
                        LIMIT 60
                    """)
                    trading_dates = [str(row[0]) for row in date_cursor.fetchall()]
                    
                    if trading_dates:
                        placeholders = ",".join("?" for _ in trading_dates)
                        cursor = self._storage.conn.execute(f"""
                            SELECT code, name, price, premium_ratio, volume, dual_low,
                                   ytm, remaining_years, change_pct, stock_price, stock_change_pct,
                                   conversion_value, momentum_5d, momentum_10d,
                                   momentum_20d, momentum_60d, timestamp,
                                   hv, rating_score, pure_bond_premium_ratio, bond_value,
                                   industry, pe, pb, roe, gpm, call_status, is_called, forced_call_days,
                                   cagr, debt_ratio, buyback_amount, mgmt_buy_price, event_score,
                                   conversion_price, sentiment_score
                            FROM quotes_history
                            WHERE CAST(timestamp AS DATE) IN ({placeholders})
                            ORDER BY timestamp ASC
                        """, trading_dates)
                        columns = [desc[0] for desc in cursor.description]
                        hist_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                        all_rows.extend(hist_rows)
                        logger.info(
                            f"[PaperTrade] _build_init_df: loaded {len(hist_rows)} rows "
                            f"from {len(trading_dates)} trading days (quotes_history fallback)"
                        )
            except Exception as e:
                logger.debug(f"[PaperTrade] _build_init_df history load failed: {e}")
        
        # ── 2. 从 MarketEngine 获取实时行情作为最新一天 ──
        if self._market_engine is not None:
            try:
                bonds = getattr(self._market_engine, 'latest_quotes', None)
                if bonds is None:
                    get_fn = getattr(self._market_engine, 'get_latest_quotes', None)
                    if get_fn:
                        bonds = get_fn()
                if bonds:
                    for b in bonds:
                        if not is_tradeable_bond(b):
                            continue
                        row = b.to_strategy_dict()
                        row["date"] = datetime.now().date()
                        row["timestamp"] = datetime.now()
                        all_rows.append(row)
            except Exception as e:
                logger.debug(f"[PaperTrade] _build_init_df live quotes failed: {e}")
        
        if not all_rows:
            return None
        
        df = pd.DataFrame(all_rows)
        # 关键修复: 统一 date 列类型为 datetime.date，避免 str 和 datetime.date 混用导致 on_init 中 sorted() 失败
        if "date" in df.columns:
            try:
                df["date"] = pd.to_datetime(df["date"], errors='coerce').dt.date
            except Exception as e:
                logger.warning(f"[PaperTrade] _build_init_df date conversion failed: {e}")
        # 确保日期列存在
        if "date" not in df.columns:
            df["date"] = df.get("timestamp", datetime.now()).apply(
                lambda x: str(x)[:10] if x else datetime.now().date()
            )
        
        # ── 去重：daily_snapshots + quotes_history 补充可能产生 code+date 重复 ──
        # 性能说明：duplicated() 为 O(N log N) 排序操作，对于 < 10 万行可接受。
        # 若数据量增长显著，可改用 set 跟踪已见 code+date 对来去重。
        # 快速路径：> 10000 行时跳过价格不一致检测（仅做去重），避免性能瓶颈
        if "code" in df.columns and "date" in df.columns:
            before = len(df)
            if "price" in df.columns and len(df) <= 10000:
                # 小数据集：先检查是否有重复行，有则检查价格不一致
                has_dups = df.duplicated(subset=["code", "date"], keep=False)
                if has_dups.any():
                    dup_rows = df[has_dups]
                    inconsistent = dup_rows.groupby(["code", "date"])["price"].nunique()
                    inconsistent_count = (inconsistent > 1).sum()
                    if inconsistent_count > 0:
                        logger.info(
                            f"[PaperTrade] _build_init_df: {inconsistent_count} code+date pairs "
                            f"have price mismatch (daily_snapshots vs quotes_history)"
                        )
            df = df.drop_duplicates(subset=["code", "date"], keep="first")
            if len(df) < before:
                logger.info(
                    f"[PaperTrade] _build_init_df: removed {before - len(df)} duplicate rows "
                    f"(code+date)"
                )
        
        # ── 补充动量因子（若 daily_snapshots 的 momentum 列全为 NULL） ──
        for col, window in [("momentum_5d", 5), ("momentum_10d", 10),
                            ("momentum_20d", 20), ("momentum_60d", 60)]:
            if col not in df.columns:
                df[col] = None
            # 仅在列全为 NaN/None 时才从价格序列计算
            if df[col].isna().all() and "code" in df.columns and "price" in df.columns:
                try:
                    df = df.sort_values(["code", "date"])
                    df[col] = df.groupby("code")["price"].pct_change(periods=window) * 100
                except Exception:
                    logger.debug(f"[PaperTrade] Momentum {col} calculation failed (insufficient data), keeping NaN")
        
        return df

    async def on_quotes(self, bonds: list[ConvertibleQuote]) -> None:
        """MarketEngine 行情回调 — 运行所有活跃账户的策略"""
        running_accounts = [a for a in self._accounts.values() if a.is_running and a.strategy]
        if not running_accounts:
            return

        # 过滤可交易债券
        valid_bonds = [b for b in bonds if is_tradeable_bond(b)]

        # 周末/非交易日: 仍更新持仓价格，但跳过策略运行避免重复信号
        is_weekend = datetime.now().weekday() >= 5  # 5=Sat, 6=Sun
        if is_weekend:
            for account in running_accounts:
                try:
                    account.trade_engine.update_prices(valid_bonds)
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
                    pass
            return

        # 构建 DataFrame（一次构建，多账户共用）
        rows = []
        for b in valid_bonds:
            row = b.to_strategy_dict()
            row["date"] = datetime.now().date()
            rows.append(row)

        if not rows:
            return

        df = pd.DataFrame(rows)

        now = time_mod.monotonic()
        today = str(datetime.now().date())

        # 并行处理各账户
        tasks = []
        for account in running_accounts:
            tasks.append(self._process_account(account, df, valid_bonds, now, today))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_account(
        self,
        account: PaperAccount,
        df: pd.DataFrame,
        bonds: list[ConvertibleQuote],
        now: float,
        today: str,
    ) -> None:
        """处理单个账户的策略运行和自动执行"""
        from datetime import date
        today_date = date.fromisoformat(today)
        try:
            # 更新交易日计数（跳过周末，A股不交易）
            if today != account._last_trade_date:
                weekday = datetime.now().weekday()  # 0=Mon, 6=Sun
                if weekday < 5:  # 周一到周五才算交易日
                    account._trade_day_count += 1
                    # 动态扩展策略的日期序列，确保 idx 始终有效
                    if account.strategy is not None:
                        try:
                            strategy_dates = list(getattr(account.strategy, '_dates', []))
                            # 关键修复: 统一比较时使用 date 类型，避免 str 和 datetime.date 混用导致匹配失败
                            if not any(
                                (isinstance(d, date) and d == today_date) or (str(d) == today)
                                for d in strategy_dates
                            ):
                                account._sim_idx += 1
                                strategy_dates.append(today_date)
                                account.strategy._dates = strategy_dates
                                # 同步更新 _date_data_map
                                if hasattr(account.strategy, '_date_data_map'):
                                    dmap = dict(account.strategy._date_data_map)
                                    dmap[today_date] = df
                                    account.strategy._date_data_map = dmap
                                # 同步更新 _data（限制保留最近90天防止无限增长）
                                if hasattr(account.strategy, '_data') and not df.empty:
                                    combined = pd.concat([account.strategy._data, df], ignore_index=True)
                                    if 'date' in combined.columns:
                                        unique_dates = combined['date'].unique()
                                        if len(unique_dates) > 90:
                                            cutoff = sorted(unique_dates)[-90]
                                            combined = combined[combined['date'] >= cutoff]
                                    account.strategy._data = combined
                        except Exception as e:
                            logger.debug(
                                f"[PaperTrade] Strategy date extension failed for {account.id}: {e}"
                            )
                account._last_trade_date = today
                # 同步 _sim_dates 确保与 _sim_idx 一致，并立即持久化防止进程崩溃后回退
                if account.strategy is not None:
                    account._sim_dates = [str(d) for d in getattr(account.strategy, '_dates', [])]
                self._save_account(account)

            # 更新持仓价格
            account.trade_engine.update_prices(bonds)

            # 策略初始化（延迟初始化: start_account 时无行情数据的情况）
            if account.strategy is None:
                logger.debug(f"[PaperTrade] Account {account.id} strategy is None, skipping")
                return

            if getattr(account, '_needs_init', False) and account.strategy is not None:
                try:
                    account.strategy.on_init(df)
                    account._sim_idx = max(0, len(getattr(account.strategy, '_dates', [])) - 1)
                    # 关键修复: 延迟初始化后也要对齐到前一个调仓日
                    if hasattr(account.strategy, 'get_param'):
                        rebalance_days = account.strategy.get_param('rebalance_days')
                        if rebalance_days and rebalance_days > 0:
                            aligned = (account._sim_idx // rebalance_days) * rebalance_days
                            account._sim_idx = aligned - 1 if aligned > 0 else 0
                    account._sim_dates = [str(d) for d in getattr(account.strategy, '_dates', [])]
                    account._needs_init = False
                    logger.info(
                        f"[PaperTrade] Delayed on_init for account {account.id} "
                        f"with {len(df)} bonds, sim_idx={account._sim_idx}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[PaperTrade] Delayed on_init failed for account {account.id}: {e}"
                    )
                    account._needs_init = False

            # 使用 _sim_idx 运行策略，确保与策略 _dates 对齐
            idx = account._sim_idx
            if account.strategy and hasattr(account.strategy, '_dates'):
                max_idx = max(0, len(account.strategy._dates) - 1)
                if idx > max_idx:
                    logger.warning(
                        f"[PaperTrade] idx {idx} exceeds strategy _dates length "
                        f"{len(account.strategy._dates)} for account {account.id}, clamping to {max_idx}"
                    )
                    idx = max_idx

            # 记录策略运行前的关键状态
            rebalance_days = account.strategy.get_param('rebalance_days') if hasattr(account.strategy, 'get_param') else None
            logger.info(
                f"[PaperTrade] Running strategy {account.strategy_name} for account {account.id}, "
                f"idx={idx}, rebalance_days={rebalance_days}, _dates_len={len(getattr(account.strategy, '_dates', []))}"
            )

            # 运行策略（30 秒超时防止阻塞）
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(account.strategy.on_data, df, idx),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[PaperTrade] Strategy on_data timeout for account {account.id} "
                    f"({account.strategy_name}), skipping this tick"
                )
                self._maybe_save_equity(account, now)
                return
            except Exception as e:
                logger.exception(f"[PaperTrade] Strategy on_data error for account {account.id}: {e}")
                self._maybe_save_equity(account, now)
                return

            if not result:
                logger.info(f"[PaperTrade] Strategy {account.strategy_name} returned no signals for account {account.id} (idx={idx})")
                # 即使无信号也记录权益快照
                self._maybe_save_equity(account, now)
                return

            logger.info(f"[PaperTrade] Strategy {account.strategy_name} returned {len(result)} raw signals for account {account.id}")

            # 处理信号
            signals_to_execute = []
            for sig in result:
                code = sig.get("code", "")
                action = sig.get("action", "")
                price = sig.get("price")
                if price is None or (isinstance(price, (int, float)) and price <= 0):
                    continue

                # 去重
                dedup_key = (code, action)
                prev = account._recent_signals.get(dedup_key)
                if prev:
                    prev_ts, prev_price = prev
                    price_close = abs(price - prev_price) / max(prev_price, 0.01) < account._dedup_price_threshold
                    if now - prev_ts < account._dedup_window_seconds and price_close:
                        continue
                account._recent_signals[dedup_key] = (now, price)

                # 查找债券信息
                bond = next((b for b in bonds if b.code == code), None)
                if not bond:
                    continue

                signals_to_execute.append({
                    "code": code,
                    "name": bond.name,
                    "action": action,
                    "price": price,
                    "reason": sig.get("reason", ""),
                    "confidence": sig.get("confidence", 0.0),
                })

            # 清理过期去重记录
            expired = [
                k for k, (ts, _) in account._recent_signals.items()
                if now - ts > account._dedup_window_seconds
            ]
            for k in expired:
                del account._recent_signals[k]

            if not signals_to_execute:
                self._maybe_save_equity(account, now)
                return

            # 自动执行: 先卖后买
            self._execute_signals(account, signals_to_execute)

            # 持久化持仓变化
            self._save_account(account)

            # 保存信号到 DB
            self._save_signals(account, signals_to_execute)

            # 记录权益快照
            self._maybe_save_equity(account, now)

        except Exception as e:
            logger.warning(f"[PaperTrade] Account {account.id} ({account.strategy_name}) error: {e}")

    # 最低配额: 每个买入信号至少分配总资产的此比例
    _min_alloc_pct: float = 0.02  # 2%
    # 最低置信度: 低于此值的买入信号将被跳过，避免 confidence=0 的信号浪费资金
    _min_confidence: float = 0.1

    def _execute_signals(self, account: PaperAccount, signals: list[dict]) -> None:
        """自动执行信号: 先卖后买，每个买入信号至少分配总资产的 _min_alloc_pct"""
        if not signals:
            return
        trade_engine = account.trade_engine

        # 1. 先卖
        for sig in signals:
            if sig["action"] != "sell":
                continue
            try:
                pos = next((p for p in trade_engine.positions if p.code == sig["code"]), None)
                if pos is None:
                    logger.debug(
                        f"[PaperTrade] Sell signal for {sig['code']} but no position held, skipping"
                    )
                    continue
                volume = pos.volume
                order = trade_engine.sell(
                    code=sig["code"], name=sig["name"],
                    price=sig["price"], volume=volume,
                )
                if order.status == OrderStatus.FILLED:
                    logger.info(
                        f"[PaperTrade] {account.strategy_name} SELL {sig['code']} "
                        f"vol={volume} @ {sig['price']}"
                    )
            except Exception as e:
                logger.warning(f"[PaperTrade] Sell failed {sig['code']}: {e}")

        # 2. 再买（按 confidence 降序排列，总量感知分配）
        # 先过滤低置信度信号，避免 confidence=0 的信号浪费资金
        # 支持策略级 min_confidence 配置（从 account.params 读取），否则用全局默认
        # 修复: 策略使用 'score' 而非 'confidence'，fallback 到 score 避免所有信号被过滤
        _min_conf_val = account.params.get("min_confidence", self._min_confidence) if isinstance(account.params, dict) else self._min_confidence
        try:
            min_conf = self._min_confidence if _min_conf_val is None else float(_min_conf_val)
        except (ValueError, TypeError):
            min_conf = self._min_confidence
        all_buy_signals = [s for s in signals if s["action"] == "buy"]
        # 如果策略未设置 confidence/score（均为 0），视为有效信号（置信度=1.0）
        buy_signals = sorted(
            [s for s in all_buy_signals if s.get("confidence", s.get("score", 0.0)) > 0 or
             (s.get("confidence", 0) == 0 and s.get("score", 0) == 0) or
             s.get("confidence", s.get("score", 0.0)) >= min_conf],
            key=lambda s: s.get("confidence", s.get("score", 0.0)) or 1.0,
            reverse=True,
        )
        skipped = len(all_buy_signals) - len(buy_signals)
        if skipped > 0:
            logger.info(
                f"[PaperTrade] {account.strategy_name}: skipped {skipped} buy signals "
                f"below min_confidence={min_conf}"
            )
        if not buy_signals:
            if skipped > 0:
                logger.info(
                    f"[PaperTrade] {account.strategy_name}: all buy signals filtered "
                    f"by min_confidence={min_conf}, sell-only day"
                )
            return

        total_asset = trade_engine.account.total_asset
        min_alloc = total_asset * self._min_alloc_pct  # 最低配额（2%总资产）
        available_cash = trade_engine.account.cash / 1.001  # 预留0.1%佣金空间

        # -- 总量感知: 先算每个信号的目标分配额 --
        n = len(buy_signals)
        total_min = min_alloc * n
        targets = []
        if total_min <= available_cash:
            # 资金充裕：每个信号至少 min_alloc + 剩余按 confidence 加权
            surplus = available_cash - total_min
            conf_sum = sum(s.get("confidence", s.get("score", 0.5)) for s in buy_signals) or 1.0
            for sig in buy_signals:
                extra = surplus * (sig.get("confidence", sig.get("score", 0.5)) / conf_sum)
                targets.append(min_alloc + extra)
        else:
            # 资金紧张：按 confidence 加权分配全部可用资金
            conf_sum = sum(s.get("confidence", s.get("score", 0.5)) for s in buy_signals) or 1.0
            for sig in buy_signals:
                targets.append(available_cash * (sig.get("confidence", sig.get("score", 0.5)) / conf_sum))

        # 按目标分配额执行买入
        for sig, target in zip(buy_signals, targets):
            try:
                volume = max(10, int(target / sig["price"] / 10) * 10)  # 按10张取整，最小10张
                if volume <= 0 or sig["price"] <= 0:
                    continue
                order = trade_engine.buy(
                    code=sig["code"], name=sig["name"],
                    price=sig["price"], volume=volume,
                )
                # 如果因资金不足被拒绝，尝试减少到10张（最小单位）
                if order.status == OrderStatus.REJECTED and volume > 10:
                    min_cost = sig["price"] * 10 * 1.001  # 10张 + 佣金
                    if trade_engine.account.cash >= min_cost:
                        order = trade_engine.buy(
                            code=sig["code"], name=sig["name"],
                            price=sig["price"], volume=10,
                        )
                if order.status == OrderStatus.FILLED:
                    logger.info(
                        f"[PaperTrade] {account.strategy_name} BUY {sig['code']} "
                        f"vol={volume} @ {sig['price']}"
                    )
                elif order.status == OrderStatus.REJECTED:
                    logger.debug(
                        f"[PaperTrade] BUY rejected {sig['code']}: {order.reject_reason}"
                    )
            except Exception as e:
                logger.warning(f"[PaperTrade] Buy failed {sig['code']}: {e}")

    def _save_signals(self, account: PaperAccount, signals: list[dict]) -> None:
        """保存信号到 signal_history"""
        if not self._storage:
            return
        try:
            import uuid as _uuid
            self._storage.save_signals_batch([
                {
                    "id": _uuid.uuid4().hex[:12],
                    "strategy": f"paper_{account.strategy_id}",
                    "code": s["code"],
                    "name": s["name"],
                    "action": s["action"],
                    "price": s["price"],
                    "reason": s.get("reason", ""),
                    "confidence": s.get("confidence", 0.0),
                    "executed": True,
                    "ts": datetime.now(),
                }
                for s in signals
            ])
        except Exception as e:
            logger.warning(f"[PaperTrade] Failed to save signals: {e}")

    _equity_cleanup_ts: float = 0.0  # 上次清理时间
    _equity_cleanup_interval: float = 86400.0  # 24小时清理一次

    def _maybe_save_equity(self, account: PaperAccount, now: float) -> None:
        """节流记录权益快照（每5分钟一次）"""
        if now - account._last_equity_ts < account._equity_snapshot_interval:
            return
        account._last_equity_ts = now

        acc = account.trade_engine.account
        profit_pct = round(
            (acc.total_asset - account.initial_cash) / account.initial_cash * 100, 2
        ) if account.initial_cash > 0 else 0.0

        try:
            with self._storage._write() as conn:
                conn.execute("""
                    INSERT INTO paper_equity
                    (account_id, ts, total_asset, cash, market_value, total_profit, total_profit_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    account.id,
                    datetime.now(),
                    acc.total_asset,
                    acc.cash,
                    acc.market_value,
                    acc.total_profit,
                    profit_pct,
                ))

                # 定期清理超过365天的旧快照（分批删除避免锁表）
                if now - self._equity_cleanup_ts > self._equity_cleanup_interval:
                    self._equity_cleanup_ts = now
                    cutoff = datetime.now() - timedelta(days=365)
                    # DuckDB 不支持 DELETE ... LIMIT，用子查询 + 计数分批删除
                    batch_size = 1000
                    total_deleted = 0
                    while True:
                        row = conn.execute(
                            "SELECT COUNT(*) FROM paper_equity WHERE ts < ?",
                            (cutoff,),
                        ).fetchone()
                        if row is None or len(row) == 0:
                            break
                        old_count = row[0]
                        if old_count == 0:
                            break
                        conn.execute(
                            "DELETE FROM paper_equity WHERE rowid IN ("
                            "  SELECT rowid FROM paper_equity WHERE ts < ? LIMIT ?"
                            ")",
                            (cutoff, batch_size),
                        )
                        row2 = conn.execute(
                            "SELECT COUNT(*) FROM paper_equity WHERE ts < ?",
                            (cutoff,),
                        ).fetchone()
                        if row2 is None or len(row2) == 0:
                            break
                        deleted = old_count - row2[0]
                        total_deleted += deleted
                        if deleted < batch_size:
                            break
                    if total_deleted > 0:
                        logger.info(
                            f"[PaperTrade] Cleaned up {total_deleted} old equity snapshots "
                            f"(older than 365 days)"
                        )
        except Exception as e:
            logger.debug(f"[PaperTrade] Failed to save equity snapshot: {e}")

    # ── 持久化 ────────────────────────────────────────

    def _save_account(self, account: PaperAccount) -> None:
        """保存账户到 DB（含持仓状态）"""
        if not self._storage:
            return
        try:
            # 序列化持仓状态
            positions_data = []
            for p in account.trade_engine.positions:
                positions_data.append({
                    "code": p.code,
                    "name": p.name,
                    "volume": p.volume,
                    "available_volume": p.available_volume,
                    "cost_price": p.cost_price,
                    "current_price": p.current_price,
                })

            with self._storage._write() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO paper_accounts
                    (id, strategy_id, strategy_name, initial_cash, is_running, params_json,
                     cash_balance, positions_json, created_at, updated_at,
                     sim_dates, last_trade_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    account.id,
                    account.strategy_id,
                    account.strategy_name,
                    account.initial_cash,
                    account.is_running,
                    json.dumps(account.params),
                    account.trade_engine.account.cash,
                    json.dumps(positions_data),
                    account.created_at,
                    datetime.now(),
                    json.dumps(account._sim_dates),
                    account._last_trade_date,
                ))
        except Exception as e:
            logger.warning(f"[PaperTrade] Failed to save account {account.id}: {e}")

    def _update_account_running(self, account_id: str, running: bool) -> None:
        """更新账户运行状态"""
        if not self._storage:
            return
        try:
            with self._storage._write() as conn:
                conn.execute("""
                    UPDATE paper_accounts SET is_running = ?, updated_at = ?
                    WHERE id = ?
                """, (running, datetime.now(), account_id))
        except Exception as e:
            logger.warning(f"[PaperTrade] Failed to update running state: {e}")

    def load_accounts(self) -> None:
        """从 DB 恢复账户（含持仓状态）"""
        if not self._storage:
            return
        try:
            cursor = self._storage.conn.execute("""
                SELECT * FROM paper_accounts
            """)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            for row in rows:
                row_dict = dict(zip(columns, row))
                account_id = row_dict['id']
                strategy_id = row_dict['strategy_id']
                strategy_name = row_dict['strategy_name']
                initial_cash = row_dict['initial_cash']
                is_running = row_dict['is_running']
                params_json = row_dict.get('params_json', '{}')
                created_at = row_dict.get('created_at')
                cash_balance = row_dict.get('cash_balance')
                positions_json = row_dict.get('positions_json', '[]')
                sim_dates = row_dict.get('sim_dates', '[]')
                last_trade_date = row_dict.get('last_trade_date', '')
                params = {}
                if params_json:
                    try:
                        params = json.loads(params_json)
                    except (json.JSONDecodeError, TypeError):
                        pass

                broker = SimBroker(initial_cash=initial_cash)
                trade_engine = TradeEngine(broker=broker)

                # ── 恢复持仓状态 ──
                if cash_balance and cash_balance > 0:
                    broker.account.cash = cash_balance
                if positions_json:
                    try:
                        positions_data = json.loads(positions_json)
                        from app.models.trade import Position
                        for pd_item in positions_data:
                            pos = Position(
                                code=pd_item["code"],
                                name=pd_item.get("name", ""),
                                volume=pd_item["volume"],
                                available_volume=pd_item.get("available_volume", pd_item["volume"]),
                                cost_price=pd_item["cost_price"],
                                current_price=pd_item.get("current_price", pd_item["cost_price"]),
                                market_value=pd_item.get("current_price", pd_item["cost_price"]) * pd_item["volume"],
                            )
                            broker._positions[pd_item["code"]] = pos
                        # 重新计算账户市值
                        broker.account.market_value = sum(
                            p.current_price * p.volume for p in broker._positions.values()
                        )
                        broker.account.total_asset = broker.account.cash + broker.account.market_value
                        broker.account.total_profit = broker.account.total_asset - initial_cash
                    except Exception as e:
                        logger.warning(f"[PaperTrade] Failed to restore positions for {account_id}: {e}")

                # 恢复 sim_dates
                sim_dates_list = []
                if sim_dates:
                    try:
                        sim_dates_list = json.loads(sim_dates)
                    except (json.JSONDecodeError, TypeError):
                        pass

                account = PaperAccount(
                    id=account_id,
                    strategy_id=strategy_id,
                    strategy_name=strategy_name,
                    trade_engine=trade_engine,
                    initial_cash=initial_cash,
                    params=params,
                    created_at=created_at or datetime.now(),
                    _sim_dates=sim_dates_list,
                    _last_trade_date=last_trade_date,
                    _sim_idx=max(0, len(sim_dates_list) - 1) if sim_dates_list else 0,
                )

                self._accounts[account_id] = account

                # 如果之前是运行状态，重新启动
                if is_running:
                    try:
                        self.start_account(account_id)
                    except Exception as e:
                        logger.warning(
                            f"[PaperTrade] Failed to restart account {account_id}: {e}"
                        )

            logger.info(f"[PaperTrade] Loaded {len(rows)} accounts from DB")

            # ── 恢复后立即刷新持仓价格（避免旧价显示跳变） ──
            self._refresh_position_prices()

        except Exception as e:
            logger.warning(f"[PaperTrade] Failed to load accounts: {e}")

    # 连续刷新失败计数器
    # NOTE: 当前 _refresh_position_prices 仅在单线程/主事件循环中调用，
    # 所以 int 计数器无需锁保护。若将来改为并发刷新（多线程/协程并发调用），
    # 需改用 threading.Lock 或 asyncio.Lock 保护 _refresh_fail_count 的读写。
    _refresh_fail_count: int = 0
    _refresh_fail_threshold: int = 5  # 连续失败N次后触发警告
    _refresh_call_count: int = 0  # 累计调用次数
    _refresh_grace_calls: int = 10  # 启动宽限期：前N次调用不计入失败
    _refresh_total_fails: int = 0  # 全局累计失败次数（即使宽限期内也计入）
    _refresh_total_fail_threshold: int = 30  # 全局失败超此值强制触发警告
    _refresh_consecutive_success: int = 0  # 连续成功次数，达到5次才重置 total_fails

    def _tick_refresh_call_count(self) -> None:
        """递增刷新调用计数（用于宽限期判断）"""
        self._refresh_call_count += 1

    def _is_in_grace_period(self) -> bool:
        """判断是否在启动宽限期内（前N次调用不计入连续失败）"""
        return self._refresh_call_count <= self._refresh_grace_calls

    def _record_refresh_failure(self, reason: str = "") -> None:
        """记录一次刷新失败，更新全局和连续失败计数，按阈值触发日志警告"""
        self._refresh_total_fails += 1
        self._refresh_consecutive_success = 0
        in_grace = self._is_in_grace_period()
        if self._refresh_total_fails >= self._refresh_total_fail_threshold:
            logger.warning(
                f"[PaperTrade] Position price refresh total failures reached "
                f"{self._refresh_total_fails}" + (f": {reason}" if reason else "")
                + " — prices may be stale"
            )
        elif not in_grace:
            self._refresh_fail_count += 1
            if self._refresh_fail_count >= self._refresh_fail_threshold:
                logger.warning(
                    f"[PaperTrade] Position price refresh failed {self._refresh_fail_count} "
                    f"consecutive times" + (f": {reason}" if reason else "")
                    + " — prices may be stale"
                )
            else:
                logger.debug(f"[PaperTrade] Position price refresh failed: {reason}")
        else:
            logger.debug(f"[PaperTrade] Position price refresh failed (startup grace): {reason}")

    def _record_refresh_success(self) -> None:
        """记录一次刷新成功，重置连续失败计数，连续成功5次后重置全局失败计数
        
        注意：成功时不调用 _tick_refresh_call_count()，而是直接重置 _refresh_call_count = 0。
        这样下次失败时 _refresh_call_count 从 1 开始重新计数，宽限期重新生效。
        这是有意设计：确保每次恢复后的前 N 次失败都享有宽限期保护。
        """
        self._refresh_fail_count = 0
        self._refresh_call_count = 0
        self._refresh_consecutive_success += 1
        if self._refresh_consecutive_success >= 5:
            self._refresh_total_fails = 0
            self._refresh_consecutive_success = 0

    def _refresh_position_prices(self) -> None:
        """从 MarketEngine 获取最新行情刷新所有账户持仓价格"""
        if self._market_engine is None:
            return
        try:
            bonds = getattr(self._market_engine, 'latest_quotes', None)
            if bonds is None:
                get_fn = getattr(self._market_engine, 'get_latest_quotes', None)
                if get_fn:
                    bonds = get_fn()
            if not bonds:
                self._tick_refresh_call_count()
                self._record_refresh_failure("no quotes available")
                return
            valid_bonds = [b for b in bonds if is_tradeable_bond(b)]
            if not valid_bonds:
                # 有行情但无可交易债券（非交易时间等），不计为失败
                return
            updated = 0
            for account in self._accounts.values():
                has_positions = len(account.trade_engine.positions) > 0
                if has_positions:
                    account.trade_engine.update_prices(valid_bonds)
                    updated += 1
            if updated > 0:
                logger.info(f"[PaperTrade] Refreshed position prices for {updated} accounts")
            self._record_refresh_success()
        except Exception as e:
            self._tick_refresh_call_count()
            self._record_refresh_failure(str(e))

    def ensure_default_accounts(self, auto_start: bool = True) -> list[PaperAccount]:
        """确保三个核心策略都有默认账户，返回新创建的账户列表

        Args:
            auto_start: 是否自动启动新创建的账户（默认True）
        """
        from app.strategies import STRATEGY_REGISTRY
        existing_strategies = {a.strategy_id for a in self._accounts.values()}
        new_accounts = []
        for strategy_id, strategy_name in self.CORE_STRATEGIES.items():
            if strategy_id in existing_strategies:
                continue
            if strategy_id not in STRATEGY_REGISTRY:
                logger.warning(
                    f"[PaperTrade] Skipping default account for {strategy_name} "
                    f"({strategy_id}): strategy not found in registry. "
                    f"Available: {list(STRATEGY_REGISTRY.keys())}"
                )
                continue
            optimal_params = self.get_optimal_params(strategy_id)
            account = self.create_account(strategy_id, initial_cash=100_000_000, params=optimal_params)
            new_accounts.append(account)
            logger.info(
                f"[PaperTrade] Auto-created {strategy_name} with optimal params "
                f"({len(optimal_params)} keys)"
            )
            if auto_start:
                try:
                    self.start_account(account.id)
                    logger.info(f"[PaperTrade] Auto-started {strategy_name} account {account.id}")
                except Exception as e:
                    logger.warning(f"[PaperTrade] Auto-start failed for {strategy_name}: {e}")
        return new_accounts
