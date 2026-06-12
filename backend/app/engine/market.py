import asyncio
import logging
from datetime import datetime, date
from typing import Optional, Callable, Awaitable

from app.adapters.akshare import AKShareAdapter
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

    async def start(self) -> None:
        """启动定时刷新"""
        if self._running:
            return
        self._running = True
        await self.refresh()
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
            bonds = await self.adapter.fetch_all_quotes()
            if not bonds and self._storage:
                bonds = self._load_from_storage()
            for bond in bonds:
                self._quotes[bond.code] = bond
            self._last_update = datetime.now()

        await self._notify_subscribers(bonds)

        # 数据增强（异步非阻塞）
        try:
            from app.engine.data_enrich import enrich_quotes
            asyncio.create_task(enrich_quotes(bonds))
        except Exception:
            pass

        # 自动缓存行情数据到DuckDB（每日首次写入，避免高频写入压力）
        if bonds and self._storage:
            today = str(date.today())
            try:
                if today != self._last_cache_date:
                    self._last_cache_date = today
                    self._storage.save_quotes_batch(bonds)
                    self._storage.save_daily_snapshot(bonds)
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
                    bonds.append(ConvertibleQuote(
                        code=code,
                        name=name,
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
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

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
        strategy = SonggangSevenDimensionStrategy()
        strategy.on_init(df)

        # 优先使用向量化计算
        if hasattr(strategy, 'calc_vectorized'):
            scores, _ = strategy.calc_vectorized(df)
        else:
            scores = []
            for _, row in df.iterrows():
                veto = strategy._check_veto(row)
                if not veto.passed:
                    continue
                score_dict = strategy._calc_total_score(row, df)
                score_dict['code'] = row['code']
                score_dict['name'] = row.get('name', '')
                score_dict['price'] = row['price']
                score_dict['premium_ratio'] = row['premium_ratio']
                score_dict['dual_low'] = row['dual_low']
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
        """获取所有行情（无数据时自动刷新，最多重试2次）"""
        if not self._quotes:
            for attempt in range(2):
                try:
                    await asyncio.wait_for(self.refresh(), timeout=90)
                    break
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"[MarketEngine] Refresh attempt {attempt + 1} failed: {e}")
        return list(self._quotes.values())

    async def get_quote(self, code: str) -> Optional[ConvertibleQuote]:
        """获取单只可转债行情"""
        async with self._lock:
            return self._quotes.get(code)

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
