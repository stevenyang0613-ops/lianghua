import logging
from typing import Optional

from app.models.trade import (
    Order, OrderSide, OrderStatus, OrderType,
    Position, Account, TradeRecord
)
from app.adapters.broker_sim import SimBroker
from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


class TradeEngine:
    def __init__(self, broker: Optional[SimBroker] = None):
        self._broker = broker or SimBroker()

    @property
    def broker(self) -> SimBroker:
        return self._broker

    @property
    def account(self) -> Account:
        return self._broker.account

    @property
    def positions(self) -> list[Position]:
        return self._broker.positions

    @property
    def orders(self) -> list[Order]:
        return self._broker.orders

    def buy(self, code: str, name: str, price: float, volume: int,
            order_type: OrderType = OrderType.MARKET) -> Order:
        if not code:
            raise ValueError("code must be non-empty")
        if price <= 0:
            raise ValueError("price must be greater than 0")
        if volume <= 0:
            raise ValueError("volume must be greater than 0")
        return self._broker.place_order(
            code=code, name=name,
            side=OrderSide.BUY,
            price=price, volume=volume,
            order_type=order_type
        )

    def sell(self, code: str, name: str, price: float, volume: int,
             order_type: OrderType = OrderType.MARKET) -> Order:
        if not code:
            raise ValueError("code must be non-empty")
        if price <= 0:
            raise ValueError("price must be greater than 0")
        if volume <= 0:
            raise ValueError("volume must be greater than 0")
        return self._broker.place_order(
            code=code, name=name,
            side=OrderSide.SELL,
            price=price, volume=volume,
            order_type=order_type
        )

    def update_prices(self, quotes: list[ConvertibleQuote]) -> None:
        self._broker.update_prices(quotes)

    def cancel_order(self, order_id: str) -> bool:
        result = self._broker.cancel_order(order_id)
        if not result:
            logger.warning(f"cancel_order failed: order_id={order_id} not found or already filled")
        return result

    def reset(self):
        logger.info("TradeEngine reset called")
        self._broker.reset()
