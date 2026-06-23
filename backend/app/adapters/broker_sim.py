import uuid
import threading
from datetime import datetime
from typing import Optional

from app.models.trade import (
    Order, OrderSide, OrderStatus, OrderType,
    Position, Account
)
from app.models.convertible import ConvertibleQuote


class SimBroker:
    def __init__(self, initial_cash: float = 100000.0, commission_pct: float = 0.0003):
        self.initial_cash = initial_cash
        self.commission_pct = commission_pct
        self._account = Account(cash=initial_cash, total_asset=initial_cash)
        self._positions: dict[str, Position] = {}
        self._orders: list[Order] = []
        self._trade_records: list = []
        self._lock = threading.Lock()

    @property
    def account(self) -> Account:
        return self._account

    @property
    def positions(self) -> list[Position]:
        return list(self._positions.values())

    @property
    def orders(self) -> list[Order]:
        return list(self._orders)

    def place_order(self, code: str, name: str, side: OrderSide,
                    price: float, volume: int, order_type: OrderType = OrderType.MARKET) -> Order:
        with self._lock:
            return self._place_order_impl(code, name, side, price, volume, order_type)

    def _place_order_impl(self, code: str, name: str, side: OrderSide,
                    price: float, volume: int, order_type: OrderType) -> Order:
        order = Order(
            id=uuid.uuid4().hex[:12],
            code=code, name=name,
            side=side, type=order_type,
            price=price, volume=volume,
        )

        if side == OrderSide.BUY:
            amount = price * volume
            commission = amount * self.commission_pct
            total_cost = amount + commission

            if self._account.cash < total_cost:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "资金不足"
                self._orders.append(order)
                return order

            self._account.cash -= total_cost

            if code in self._positions:
                pos = self._positions[code]
                total_cost_existing = pos.cost_price * pos.volume
                total_volume = pos.volume + volume
                if total_volume > 0:
                    pos.cost_price = round((total_cost_existing + amount) / total_volume, 4)
                pos.volume = total_volume
                pos.available_volume = total_volume
            else:
                self._positions[code] = Position(
                    code=code, name=name,
                    volume=volume, available_volume=volume,
                    cost_price=price, current_price=price,
                    market_value=amount,
                )

        elif side == OrderSide.SELL:
            if code not in self._positions or self._positions[code].volume < volume:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "持仓不足"
                self._orders.append(order)
                return order

            pos = self._positions[code]
            amount = price * volume
            commission = amount * self.commission_pct

            pos.volume -= volume
            pos.available_volume -= volume

            self._account.cash += amount - commission

            if pos.volume <= 0:
                del self._positions[code]

        order.status = OrderStatus.FILLED
        order.filled_volume = volume
        order.updated_at = datetime.now()
        self._orders.append(order)

        self._account.market_value = sum(
            p.current_price * p.volume for p in self._positions.values()
        )
        # 当前模拟器对所有订单立即成交，所以冻结资金 = 0。
        # 真实场景下应累加所有未成交委托占用的资金。
        self._account.frozen = 0.0
        self._account.total_asset = self._account.cash + self._account.market_value
        self._account.total_profit = self._account.total_asset - self.initial_cash
        self._account.updated_at = datetime.now()

        return order

    def update_prices(self, quotes: list[ConvertibleQuote]) -> None:
        quote_map = {q.code: q for q in quotes}
        for pos in self._positions.values():
            q = quote_map.get(pos.code)
            if q:
                pos.current_price = q.price
                pos.market_value = q.price * pos.volume
                if pos.cost_price and pos.cost_price > 0:
                    pos.profit_pct = round((q.price - pos.cost_price) / pos.cost_price * 100, 2)
                else:
                    pos.profit_pct = 0.0
                pos.profit_amount = round((q.price - pos.cost_price) * pos.volume, 2)

        self._account.market_value = sum(p.market_value for p in self._positions.values())
        self._account.total_asset = self._account.cash + self._account.market_value
        self._account.total_profit = self._account.total_asset - self.initial_cash

    def cancel_order(self, order_id: str) -> bool:
        for order in self._orders:
            if order.id == order_id and order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now()
                return True
        return False

    def reset(self):
        self._account = Account(cash=self.initial_cash, total_asset=self.initial_cash)
        self._positions.clear()
        self._orders.clear()
        self._trade_records.clear()
