import asyncio
import json
import logging
from datetime import datetime, date
from typing import Optional, Callable, Awaitable

import pandas as pd

from app.adapters.akshare import AKShareAdapter
from app.engine.storage import DataStorage
from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


def _parse_iso_date(value) -> Optional[date]:
    """容错解析 date/datetime/str → date;空值/无效值返回 None"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s or s in ("nan", "NaT", "None"):
            return None
        try:
            return datetime.strptime(s[:10].replace("/", "-"), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


class MarketEngine:
    """行情引擎 - 负责数据采集、缓存和定时刷新"""

    def __init__(self, adapter: Optional[AKShareAdapter] = None, refresh_interval: int = 5, storage: Optional['DataStorage'] = None):
        self.adapter = adapter or AKShareAdapter()
        self._quotes: dict[str, ConvertibleQuote] = {}
        self._last_update: Optional[datetime] = None
        self._running = False
        self._refresh_interval = refresh_interval
        try:
            from app.config import settings
            self._trading_interval = settings.trading_refresh_interval
            self._off_hours_interval = settings.off_hours_refresh_interval
        except Exception:
            self._trading_interval = 10
            self._off_hours_interval = 60
        self._refresh_task: Optional[asyncio.Task] = None
        self._subscribers: set[Callable[[list[ConvertibleQuote]], Awaitable[None]]] = set()
        self._lock = asyncio.Lock()
        self._storage = storage
        self._last_snapshot_date: Optional[str] = None
        self._last_cache_date: Optional[str] = None
        self._last_periodic_save: Optional[float] = 0  # timestamp of last periodic save
        self._PERIODIC_SAVE_INTERVAL = 300  # 5 minutes

    async def start(self) -> None:
        """启动定时刷新

        注意：此方法不会立即调用 refresh() 以避免 AKShare C扩展 segfault 杀死进程。
        首次数据加载在 refresh_loop 的第一次 tick 中完成，且优先使用 DuckDB 缓存。
        """
        if self._running:
            return
        self._running = True
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        """停止定时刷新"""
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        self._subscribers.clear()

    async def _refresh_loop(self) -> None:
        """定时刷新循环"""
        while self._running:
            interval = self.get_refresh_interval()
            await asyncio.sleep(interval)
            try:
                await self.refresh()
            except Exception as e:
                logger.error(f"[MarketEngine] Refresh error: {e}")

    async def refresh(self) -> list[ConvertibleQuote]:
        """刷新全市场行情并通知订阅者"""
        async with self._lock:
            # 优先从缓存加载，避免AKShare API调用造成OOM
            bonds = []
            if self._storage:
                bonds = self._load_from_storage()
            if not bonds:
                try:
                    bonds = await self.adapter.fetch_all_quotes()
                except Exception as e:
                    logger.error(f"[MarketEngine] fetch_all_quotes failed: {e}")
            if not bonds:
                bonds = []

            try:
                from app.engine.data_enrich import set_bond_stock_codes
                stock_codes = list({b.stock_code for b in bonds if getattr(b, 'stock_code', None)})
                set_bond_stock_codes(stock_codes)
            except Exception:
                pass

            # 数据增强：填充 industry/pe/pb/roe/gpm 等字段（等待完成，确保数据一致）
            try:
                from app.engine.data_enrich import enrich_quotes
                bonds = await enrich_quotes(bonds)
            except Exception as e:
                logger.error(f"[MarketEngine] enrich_quotes failed: {e}", exc_info=True)

            # 如果 volatility 缓存为空，从 DuckDB 历史价格计算
            try:
                from app.engine.data_enrich import _vol_map, _save_cache, _VOL_CACHE, _set_global_map
                if not _vol_map and self._storage:
                    from app.engine.historical import HistoricalDataLoader
                    loader = HistoricalDataLoader(self._storage)
                    count = await asyncio.to_thread(loader._compute_iv_from_prices)
                    if count > 0:
                        # Reload the vol map after computation
                        from app.engine.data_enrich import _load_vol_cache
                        _load_vol_cache()
                        logger.info(f"[MarketEngine] Computed IV from stock prices: {count} stocks")
            except Exception as e:
                logger.debug(f"[MarketEngine] IV from stock prices failed: {e}")

            for bond in bonds:
                self._quotes[bond.code] = bond
            self._last_update = datetime.now()

        await self._notify_subscribers(bonds)

        # 自动缓存行情数据到DuckDB（每日首次写入，避免高频写入压力）
        if bonds and self._storage:
            today = str(date.today())
            try:
                if today != self._last_cache_date:
                    self._last_cache_date = today
                    self._storage.save_quotes_batch(bonds)
                    self._storage.save_daily_snapshot(bonds)
                    self._last_periodic_save = asyncio.get_event_loop().time()
                else:
                    # Periodic save every 5 minutes to capture enrichment updates
                    now = asyncio.get_event_loop().time()
                    if now - self._last_periodic_save >= self._PERIODIC_SAVE_INTERVAL:
                        self._storage.save_quotes_batch(bonds)
                        self._last_periodic_save = now
                        logger.debug(f"[MarketEngine] Periodic save: {len(bonds)} bonds")
            except Exception as e:
                logger.warning(f"[MarketEngine] Cache to storage failed: {e}")

            # 每日首次成功刷新时自动保存七维评分快照（线程池计算，不阻塞事件循环）
            if today != self._last_snapshot_date:
                self._last_snapshot_date = today
                asyncio.create_task(self._auto_save_seven_dim_snapshot_async(bonds))

        return bonds

    @staticmethod
    def _is_delisted_or_exchangeable(code: str, name: str) -> bool:
        """判断是否为退市转债或可交换债，应从行情中排除"""
        from app.engine.filters import is_delisted_or_exchangeable
        return is_delisted_or_exchangeable(code, name)

    def _load_from_storage(self) -> list[ConvertibleQuote]:
        """从 DuckDB 历史数据加载兜底数据（过滤price=0等无效数据）"""
        try:
            rows = self._storage.get_latest_quotes()
            bonds = []
            skipped_zero_price = 0
            skipped_stopped = 0
            now = date.today()
            for r in rows:
                try:
                    code = r.get("code", "")
                    name = r.get("name", "")
                    if self._is_delisted_or_exchangeable(code, name):
                        continue
                    price = float(r.get("price", 0))
                    if price <= 0:
                        skipped_zero_price += 1
                        continue
                    # 过滤已停止交易的转债（最后交易日或到期日已过）
                    last_trade = _parse_iso_date(r.get("last_trade_date"))
                    maturity = _parse_iso_date(r.get("maturity_date"))
                    if last_trade and last_trade < now:
                        skipped_stopped += 1
                        continue
                    if maturity and maturity < now:
                        skipped_stopped += 1
                        continue
                    # Bug 10 fix: DuckDB JSON column returns parsed Python objects (list/dict),
                    # NOT strings. json.loads() on an already-parsed list raises TypeError.
                    _concepts_raw = r.get("concepts")
                    if _concepts_raw is None:
                        concepts_val = None
                    elif isinstance(_concepts_raw, (list, dict)):
                        concepts_val = _concepts_raw  # already parsed
                    elif isinstance(_concepts_raw, str) and _concepts_raw.strip():
                        concepts_val = json.loads(_concepts_raw)
                    else:
                        concepts_val = None
                    bonds.append(ConvertibleQuote(
                        code=code,
                        name=name,
                        stock_code=str(r.get("stock_code", "")),
                        price=price,
                        change_pct=float(r.get("change_pct", 0)),
                        stock_price=float(r.get("stock_price", 0)),
                        stock_change_pct=float(r.get("stock_change_pct", 0)),
                        conversion_price=float(r.get("conversion_price", 0)),
                        conversion_value=float(r.get("conversion_value", 0)),
                        premium_ratio=float(r.get("premium_ratio", 0)),
                        dual_low=float(r.get("dual_low", 0)),
                        ytm=float(r.get("ytm", 0)),
                        volume=float(r.get("volume", 0)),
                        remaining_years=float(r.get("remaining_years", 0)),
                        forced_call_days=int(r.get("forced_call_days", 0)),
                        is_called=bool(r.get("is_called") or False),
                        call_status=str(r.get("call_status", "") or ""),
                        last_trade_date=last_trade,
                        maturity_date=maturity,
                        redemption_price=float(r.get("redemption_price", 0) or 0.0),
                        industry=r.get("industry"),
                        rating=r.get("rating"),
                        roe=r.get("roe"),
                        gpm=r.get("gpm"),
                        cagr=r.get("cagr"),
                        debt_ratio=r.get("debt_ratio"),
                        current_ratio=r.get("current_ratio"),
                        pe=r.get("pe"),
                        pb=r.get("pb"),
                        iv=r.get("iv"),
                        iv_source=r.get("iv_source"),
                        bond_value=r.get("bond_value"),
                        buyback_amount=r.get("buyback_amount"),
                        mgmt_buy_price=r.get("mgmt_buy_price"),
                        outstanding_scale=r.get("outstanding_scale"),
                        turnover_rate=r.get("turnover_rate"),
                        net_capital_flow=r.get("net_capital_flow"),
                        net_capital_flow_pct=r.get("net_capital_flow_pct"),
                        net_super_flow=r.get("net_super_flow"),
                        net_big_flow=r.get("net_big_flow"),
                        pledge_ratio=r.get("pledge_ratio"),
                        momentum_5d=r.get("momentum_5d"),
                        momentum_10d=r.get("momentum_10d"),
                        momentum_20d=r.get("momentum_20d"),
                        momentum_60d=r.get("momentum_60d"),
                        event_score=r.get("event_score"),
                        event_detail=r.get("event_detail"),
                        stock_name=str(r.get("stock_name") or ""),
                        concepts=concepts_val,
                        # 14 new columns (added 2026-06-21)
                        hv=r.get("hv"),
                        rating_score=r.get("rating_score"),
                        pure_bond_premium_ratio=r.get("pure_bond_premium_ratio"),
                        north_net=r.get("north_net"),
                        margin_balance=r.get("margin_balance"),
                        lhb_count=r.get("lhb_count"),
                        block_trade_amount=r.get("block_trade_amount"),
                        holder_num_change=r.get("holder_num_change"),
                        eps_forecast=r.get("eps_forecast"),
                        eps=r.get("eps"),
                        bps=r.get("bps"),
                        revenue_yoy=r.get("revenue_yoy"),
                        profit_yoy=r.get("profit_yoy"),
                        restricted_release_amount=r.get("restricted_release_amount"),
                    ))
                except (ValueError, TypeError, KeyError):
                    continue
            if bonds:
                logger.info(f"[MarketEngine] Loaded {len(bonds)} bonds from storage fallback (skipped {skipped_zero_price} with price=0, {skipped_stopped} stopped trading)")
            return bonds
        except Exception as e:
            logger.error(f"[MarketEngine] Storage fallback failed: {e}")
            return []

    @staticmethod
    def _compute_seven_dim_snapshot(bonds: list[ConvertibleQuote], storage) -> int:
        """同步计算七维评分快照（在线程池中执行，向量化），返回评分数量"""
        import pandas as pd
        from app.strategies.xibu_seven_dimension import XibuSevenDimensionStrategy

        rows = [{
            "code": b.code, "name": b.name, "price": b.price,
            "premium_ratio": b.premium_ratio, "volume": b.volume or 0,
            "dual_low": b.dual_low, "change_pct": b.change_pct or 0,
            "ytm": b.ytm or 0, "remaining_years": b.remaining_years or 0,
            "conversion_value": b.conversion_value or 0,
            "stock_price": b.stock_price or 0, "stock_change_pct": b.stock_change_pct or 0,
            "forced_call_days": b.forced_call_days or 0,
            "date": date.today(),
        } for b in bonds]

        df = pd.DataFrame(rows)
        strategy = XibuSevenDimensionStrategy()
        strategy.on_init(df)

        # 检测市场环境并传入向量化计算
        from app.strategies.xibu_seven_dimension import _detect_market_env
        market_env, _ = _detect_market_env(df, pd.Timestamp.now(), None, None)

        # 优先使用向量化计算
        if hasattr(strategy, 'calc_vectorized'):
            scores, _ = strategy.calc_vectorized(df, market_env)
        else:
            scores = []
            for _, row in df.iterrows():
                veto = strategy._check_veto(row)
                # 即使未通过审查也保存基础评分数据（维度数据为0）
                if hasattr(strategy, '_calc_total_score'):
                    try:
                        score_dict = strategy._calc_total_score(row, df)
                    except Exception:
                        score_dict = {}
                else:
                    score_dict = {}
                score_dict['code'] = row['code']
                score_dict['name'] = row.get('name', '')
                score_dict['price'] = row['price']
                score_dict['premium_ratio'] = row['premium_ratio']
                score_dict['dual_low'] = row['dual_low']
                score_dict['stock_score'] = score_dict.get('stock_score', 0)
                score_dict['bond_score'] = score_dict.get('bond_score', 0)
                score_dict['total'] = score_dict.get('total', 0)
                scores.append(score_dict)

        if scores:
            storage.save_seven_dim_snapshot(scores)
        return len(scores)

    async def _auto_save_seven_dim_snapshot_async(self, bonds: list[ConvertibleQuote]) -> None:
        """自动保存七维评分快照（线程池计算，不阻塞事件循环）"""
        try:
            count = await asyncio.to_thread(self._compute_seven_dim_snapshot, bonds, self._storage)
            if count > 0:
                logger.info(f"[MarketEngine] Auto-saved seven-dim snapshot: {count} bonds")
        except Exception as e:
            logger.warning(f"[MarketEngine] Auto seven-dim snapshot failed: {e}")

    async def _notify_subscribers(self, bonds: list[ConvertibleQuote]) -> None:
        """通知所有订阅者，移除失败的订阅者"""
        dead = []
        for callback in list(self._subscribers):
            try:
                await callback(bonds)
            except Exception as e:
                logger.exception(f"[MarketEngine] Subscriber notification error")
                dead.append(callback)
        for cb in dead:
            self._subscribers.discard(cb)
            logger.info(f"[MarketEngine] Removed dead subscriber, {len(self._subscribers)} remaining")

    async def get_all_quotes(self) -> list[ConvertibleQuote]:
        """获取所有行情（无数据时尝试 DuckDB 兜底，不调用 AKShare 以避免 segfault）"""
        if not self._quotes:
            # 仅尝试 DuckDB 兜底，不调用 AKShare 以避免 C 扩展 segfault
            if self._storage:
                try:
                    rows = self._storage.get_latest_quotes()
                    if rows:
                        # 复用 _load_from_storage 的逻辑
                        from app.models.convertible import ConvertibleQuote
                        bonds = []
                        from app.engine.filters import is_delisted_or_exchangeable
                        for r in rows:
                            try:
                                price = float(r.get("price", 0) or 0)
                                code = str(r.get("code", ""))
                                name = str(r.get("name", ""))
                                if not code or not name:
                                    continue
                                stock_code = str(r.get("stock_code", ""))
                                change_pct = float(r.get("change_pct", 0) or 0)
                                stock_price = float(r.get("stock_price", 0) or 0)
                                stock_change_pct = float(r.get("stock_change_pct", 0) or 0)
                                conversion_price = float(r.get("conversion_price", 0) or 0)
                                conversion_value = float(r.get("conversion_value", 0) or 0)
                                premium_ratio = float(r.get("premium_ratio", 0) or 0)
                                dual_low = float(r.get("dual_low", 0) or 0)
                                volume = float(r.get("volume", 0) or 0)
                                ytm = float(r.get("ytm", 0) or 0)
                                remaining_years = float(r.get("remaining_years", 0) or 0)
                                forced_call_days = int(r.get("forced_call_days", 0) or 0)
                                is_called = bool(r.get("is_called", False))
                                call_status = str(r.get("call_status", ""))
                                last_trade_date = r.get("last_trade_date")
                                maturity_date = r.get("maturity_date")
                                redemption_price = float(r.get("redemption_price", 0.0) or 0.0)
                                rating = r.get("rating")
                                if price <= 0:
                                    continue
                                bonds.append(ConvertibleQuote(
                                    code=code, name=name, stock_code=stock_code,
                                    price=price, change_pct=change_pct, stock_price=stock_price,
                                    stock_change_pct=stock_change_pct, conversion_price=conversion_price,
                                    conversion_value=conversion_value, premium_ratio=premium_ratio,
                                    dual_low=dual_low, volume=volume, ytm=ytm,
                                    remaining_years=remaining_years, forced_call_days=forced_call_days,
                                    is_called=is_called, call_status=call_status,
                                    last_trade_date=last_trade_date, maturity_date=maturity_date,
                                    redemption_price=redemption_price, rating=rating,
                                    turnover_rate=r.get("turnover_rate"),
                                    net_capital_flow=r.get("net_capital_flow"),
                                    net_capital_flow_pct=r.get("net_capital_flow_pct"),
                                ))
                            except (ValueError, TypeError, KeyError):
                                continue
                        if bonds:
                            self._quotes = {b.code: b for b in bonds}
                            logger.info(f"[MarketEngine] get_all_quotes loaded {len(bonds)} bonds from storage fallback")
                            # Enrich immediately so caller sees pe/pb/industry/roe/gpm/iv/etc.
                            try:
                                from app.engine.data_enrich import enrich_quotes
                                enriched = await enrich_quotes(bonds)
                                if enriched:
                                    self._quotes = {b.code: b for b in enriched}
                                    logger.info(f"[MarketEngine] get_all_quotes enriched {len(enriched)} bonds")
                            except Exception as enr_e:
                                logger.warning(f"[MarketEngine] get_all_quotes enrich failed: {enr_e}")
                except Exception as e:
                    logger.debug(f"[MarketEngine] get_all_quotes storage fallback failed: {e}")

        # Always enrich before returning to avoid stale data (AGENTS.md audit fix)
        if self._quotes:
            try:
                from app.engine.data_enrich import enrich_quotes
                bonds = list(self._quotes.values())
                enriched = await enrich_quotes(bonds)
                if enriched:
                    self._quotes = {b.code: b for b in enriched}
            except Exception as e:
                logger.warning(f"[MarketEngine] get_all_quotes enrich failed: {e}")

        # 深拷贝避免外部修改污染内部状态
        import copy
        return copy.deepcopy(list(self._quotes.values()))

    async def get_quote(self, code: str) -> Optional[ConvertibleQuote]:
        """获取单只可转债行情 — 返回深拷贝避免外部修改污染内部状态"""
        import copy
        async with self._lock:
            quote = self._quotes.get(code)
            return copy.deepcopy(quote) if quote is not None else None

    def get_refresh_interval(self) -> int:
        """根据当前时段返回刷新间隔：交易时段10秒，非交易时段60秒"""
        now = datetime.now()
        weekday = now.weekday()
        if weekday >= 5:
            return self._off_hours_interval
        hour, minute = now.hour, now.minute
        if (9, 30) <= (hour, minute) < (15, 0):
            return self._trading_interval
        return self._off_hours_interval

    def subscribe(self, callback: Callable[[list[ConvertibleQuote]], Awaitable[None]]) -> None:
        """订阅行情更新"""
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable[[list[ConvertibleQuote]], Awaitable[None]]) -> None:
        """取消订阅"""
        self._subscribers.discard(callback)

    @property
    def last_update(self) -> Optional[datetime]:
        return self._last_update

    @property
    def is_running(self) -> bool:
        return self._running
