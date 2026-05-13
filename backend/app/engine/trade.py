from typing import Optional

from app.models.trade import (
    Order, OrderSide, OrderStatus, OrderType,
    Position, Account, TradeRecord
)
from app.adapters.broker_sim import SimBroker
from app.models.convertible import ConvertibleQuote


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
        return self._broker.place_order(
            code=code, name=name,
            side=OrderSide.BUY,
            price=price, volume=volume,
            order_type=order_type
        )

    def sell(self, code: str, name: str, price: float, volume: int,
             order_type: OrderType = OrderType.MARKET) -> Order:
        return self._broker.place_order(
            code=code, name=name,
            side=OrderSide.SELL,
            price=price, volume=volume,
            order_type=order_type
        )

    def update_prices(self, quotes: list[ConvertibleQuote]) -> None:
        self._broker.update_prices(quotes)

    def cancel_order(self, order_id: str) -> bool:
        return self._broker.cancel_order(order_id)

    def reset(self):
        self._broker.reset()
