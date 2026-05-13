from datetime import datetime
from typing import Optional, Callable, Awaitable

from app.adapters.akshare import AKShareAdapter
from app.models.convertible import ConvertibleQuote


class MarketEngine:
    """行情引擎 - 负责数据采集和缓存"""

    def __init__(self, adapter: Optional[AKShareAdapter] = None):
        self.adapter = adapter or AKShareAdapter()
        self._quotes: dict[str, ConvertibleQuote] = {}
        self._last_update: Optional[datetime] = None
        self._running = False
        self._all_subscribers: set[Callable[[list[ConvertibleQuote]], Awaitable[None]]] = set()

    async def refresh(self) -> list[ConvertibleQuote]:
        """刷新全市场行情"""
        bonds = await self.adapter.fetch_all_quotes()
        for bond in bonds:
            self._quotes[bond.code] = bond
        self._last_update = datetime.now()
        return bonds

    async def get_all_quotes(self) -> list[ConvertibleQuote]:
        if not self._quotes:
            await self.refresh()
        return list(self._quotes.values())

    async def get_quote(self, code: str) -> Optional[ConvertibleQuote]:
        return self._quotes.get(code)

    def subscribe_all(self, callback: Callable[[list[ConvertibleQuote]], Awaitable[None]]) -> None:
        self._all_subscribers.add(callback)

    def unsubscribe_all(self, callback: Callable[[list[ConvertibleQuote]], Awaitable[None]]) -> None:
        self._all_subscribers.discard(callback)

    def stop(self):
        self._running = False
