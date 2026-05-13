import asyncio
from datetime import datetime
from typing import Optional, Callable, Awaitable

from app.adapters.akshare import AKShareAdapter
from app.models.convertible import ConvertibleQuote


class MarketEngine:
    """行情引擎 - 负责数据采集、缓存和定时刷新"""

    def __init__(self, adapter: Optional[AKShareAdapter] = None, refresh_interval: int = 5):
        self.adapter = adapter or AKShareAdapter()
        self._quotes: dict[str, ConvertibleQuote] = {}
        self._last_update: Optional[datetime] = None
        self._running = False
        self._refresh_interval = refresh_interval
        self._refresh_task: Optional[asyncio.Task] = None
        self._subscribers: set[Callable[[list[ConvertibleQuote]], Awaitable[None]]] = set()
        self._lock = asyncio.Lock()

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
            await asyncio.sleep(self._refresh_interval)
            try:
                await self.refresh()
            except Exception as e:
                print(f"[MarketEngine] Refresh error: {e}")

    async def refresh(self) -> list[ConvertibleQuote]:
        """刷新全市场行情并通知订阅者"""
        async with self._lock:
            bonds = await self.adapter.fetch_all_quotes()
            for bond in bonds:
                self._quotes[bond.code] = bond
            self._last_update = datetime.now()

        await self._notify_subscribers(bonds)
        return bonds

    async def _notify_subscribers(self, bonds: list[ConvertibleQuote]) -> None:
        """通知所有订阅者"""
        for callback in list(self._subscribers):
            try:
                await callback(bonds)
            except Exception as e:
                print(f"[MarketEngine] Subscriber callback error: {e}")

    async def get_all_quotes(self) -> list[ConvertibleQuote]:
        """获取所有行情（无数据时自动刷新）"""
        if not self._quotes:
            await self.refresh()
        return list(self._quotes.values())

    async def get_quote(self, code: str) -> Optional[ConvertibleQuote]:
        """获取单只可转债行情"""
        return self._quotes.get(code)

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
