"""松岗量化可转债策略 V3.0 执行模块

模拟交易执行:
- 信号处理
- 订单生成
- 成交模拟
- 持仓更新
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Optional
import logging

from app.sg_strategy.core.types import (
    TradeSignal, Position, Portfolio, TransactionCost, SignalType
)
from app.sg_strategy.core.cost import TransactionCostModel, CostController
from app.sg_strategy.config.settings import params

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """订单"""
    order_id: str
    cb_code: str
    cb_name: str
    action: str  # buy/sell
    quantity: int
    price_limit: Optional[float]
    signal_type: SignalType
    reason: str
    status: str = "pending"  # pending/filled/cancelled
    filled_price: float = 0.0
    filled_quantity: int = 0
    created_at: datetime = None
    filled_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class ExecutionResult:
    """执行结果"""
    order: Order
    success: bool
    message: str
    cost: TransactionCost
    position_after: Optional[Position] = None

    def to_dict(self) -> dict:
        return {
            "order_id": self.order.order_id,
            "cb_code": self.order.cb_code,
            "success": self.success,
            "message": self.message,
            "filled_price": self.order.filled_price,
            "filled_quantity": self.order.filled_quantity,
            "cost": self.cost.to_dict(),
        }


class ExecutionEngine:
    """执行引擎"""

    def __init__(self, aum: float = 10000.0):
        """初始化

        Args:
            aum: 资产规模(万元)
        """
        self.aum = aum
        self.cost_model = TransactionCostModel(aum)
        self.cost_controller = CostController(aum)

        self._pending_orders: List[Order] = []
        self._filled_orders: List[Order] = []
        self._daily_trades: Dict[date, List[Order]] = {}

    def create_order(
        self,
        signal: TradeSignal,
        daily_amount: float = 1000.0,
    ) -> Order:
        """创建订单

        Args:
            signal: 交易信号
            daily_amount: 标的日均成交额(万元)

        Returns:
            Order: 订单
        """
        import uuid

        order = Order(
            order_id=str(uuid.uuid4())[:8],
            cb_code=signal.cb_code,
            cb_name=signal.cb_name,
            action=signal.action.value,
            quantity=signal.quantity,
            price_limit=signal.price,
            signal_type=signal.signal_type,
            reason=signal.reason,
        )

        self._pending_orders.append(order)
        return order

    def execute_order(
        self,
        order: Order,
        portfolio: Portfolio,
        market_price: float,
        daily_amount: float = 1000.0,
    ) -> ExecutionResult:
        """执行订单

        Args:
            order: 订单
            portfolio: 组合
            market_price: 市场价格
            daily_amount: 日均成交额(万元)

        Returns:
            ExecutionResult: 执行结果
        """
        # 使用限价或市价
        fill_price = order.price_limit or market_price
        fill_quantity = order.quantity

        # 计算成本
        cost = self.cost_model.calculate_cost(
            fill_price, fill_quantity, daily_amount, order.action
        )

        position_after = None

        if order.action == "buy":
            # 检查资金
            # 注意: fill_price是元/张，fill_quantity是张数，所以金额是元
            # portfolio.cash是万元，需要转换
            required_yuan = fill_price * fill_quantity + cost.total  # 元
            required_wan = required_yuan / 10000  # 转换为万元

            if portfolio.cash < required_wan:
                return ExecutionResult(
                    order=order,
                    success=False,
                    message=f"资金不足(需要{required_wan:.2f}万, 可用{portfolio.cash:.2f}万)",
                    cost=cost,
                )

            # 执行买入 (现金单位是万元)
            portfolio.cash -= required_wan

            if order.cb_code in portfolio.positions:
                # 加仓
                pos = portfolio.positions[order.cb_code]
                total_qty = pos.quantity + fill_quantity
                total_cost = pos.cost_basis + fill_price * fill_quantity
                pos.avg_cost = total_cost / total_qty
                pos.quantity = total_qty
                pos.cost_basis = total_cost
            else:
                # 新建仓位
                pos = Position(
                    cb_code=order.cb_code,
                    cb_name=order.cb_name,
                    quantity=fill_quantity,
                    avg_cost=fill_price,
                    current_price=fill_price,
                    market_value=fill_price * fill_quantity,
                    cost_basis=fill_price * fill_quantity,
                    buy_date=order.created_at.date() if order.created_at else date.today(),
                    buy_price=fill_price,
                )
                portfolio.positions[order.cb_code] = pos

                # 记录买入日期
                self.cost_controller.record_buy(order.cb_code, order.created_at.date() if order.created_at else date.today())

            position_after = pos

        elif order.action == "sell":
            # 检查持仓
            if order.cb_code not in portfolio.positions:
                return ExecutionResult(
                    order=order,
                    success=False,
                    message="无此持仓",
                    cost=cost,
                )

            pos = portfolio.positions[order.cb_code]

            if pos.quantity < fill_quantity:
                fill_quantity = pos.quantity  # 只能卖出持有的

            # 执行卖出
            proceeds_yuan = fill_price * fill_quantity - cost.total  # 元
            proceeds_wan = proceeds_yuan / 10000  # 转换为万元
            portfolio.cash += proceeds_wan

            if fill_quantity >= pos.quantity:
                # 清仓
                del portfolio.positions[order.cb_code]
                self.cost_controller.record_sell(order.cb_code)
            else:
                # 减仓
                pos.quantity -= fill_quantity
                pos.cost_basis = pos.avg_cost * pos.quantity
                position_after = pos

        # 更新订单状态
        order.status = "filled"
        order.filled_price = fill_price
        order.filled_quantity = fill_quantity
        order.filled_at = datetime.now()

        self._filled_orders.append(order)

        # 记录当日交易
        trade_date = order.created_at.date() if order.created_at else date.today()
        if trade_date not in self._daily_trades:
            self._daily_trades[trade_date] = []
        self._daily_trades[trade_date].append(order)

        # 记录交易成本
        self.cost_model.record_trade(
            trade_date,
            order.cb_code,
            order.action,
            fill_price,
            fill_quantity,
            daily_amount,
        )

        logger.info(
            f"[Execution] {order.action.upper()} {order.cb_code} "
            f"{fill_quantity}张 @ {fill_price:.3f}, 成本: {cost.total:.2f}"
        )

        return ExecutionResult(
            order=order,
            success=True,
            message="执行成功",
            cost=cost,
            position_after=position_after,
        )

    def process_signals(
        self,
        signals: List[TradeSignal],
        portfolio: Portfolio,
        prices: Dict[str, float],
        daily_amounts: Dict[str, float],
    ) -> List[ExecutionResult]:
        """批量处理信号

        Args:
            signals: 信号列表
            portfolio: 组合
            prices: 价格字典
            daily_amounts: 日均成交额字典

        Returns:
            执行结果列表
        """
        results = []

        # 按紧急程度排序
        sorted_signals = sorted(signals, key=lambda s: -s.urgency)

        for signal in sorted_signals:
            price = prices.get(signal.cb_code, signal.price)
            daily_amount = daily_amounts.get(signal.cb_code, 1000.0)

            # 创建并执行订单
            order = self.create_order(signal, daily_amount)
            result = self.execute_order(order, portfolio, price, daily_amount)
            results.append(result)

        return results

    def get_pending_orders(self) -> List[Order]:
        """获取待执行订单"""
        return [o for o in self._pending_orders if o.status == "pending"]

    def get_daily_trades(self, trade_date: date) -> List[Order]:
        """获取当日交易"""
        return self._daily_trades.get(trade_date, [])

    def cancel_order(self, order_id: str) -> bool:
        """取消订单

        Args:
            order_id: 订单ID

        Returns:
            是否成功
        """
        for order in self._pending_orders:
            if order.order_id == order_id and order.status == "pending":
                order.status = "cancelled"
                return True
        return False
