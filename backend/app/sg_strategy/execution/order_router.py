"""松岗量化可转债策略 V3.0 智能订单路由模块

功能:
- 多交易所智能路由
- 最优执行价格
- 拆单策略
- 订单状态跟踪
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import time
import threading
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class Exchange(str, Enum):
    """交易所"""
    SSE = "sse"           # 上交所
    SZSE = "szse"         # 深交所
    SHFE = "shfe"         # 上期所
    DCE = "dce"           # 大商所
    CZCE = "czce"         # 郑商所
    CFFEX = "cffex"       # 中金所


class OrderStatus(str, Enum):
    """订单状态"""
    NEW = "new"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    ICEBERG = "iceberg"


class RoutingStrategy(str, Enum):
    """路由策略"""
    BEST_PRICE = "best_price"     # 最优价格
    BEST_EXECUTION = "best_exec"  # 最优执行
    MIN_COST = "min_cost"         # 最小成本
    FASTEST = "fastest"           # 最快执行
    BALANCED = "balanced"         # 平衡


# ============ 数据模型 ============

@dataclass
class ExchangeInfo:
    """交易所信息"""
    exchange: Exchange
    name: str
    trading_hours: List[Tuple[str, str]]
    min_order_size: int
    max_order_size: int
    price_tick: float
    commission_rate: float
    latency_ms: float
    fill_rate: float
    available: bool = True

    def is_trading_time(self, dt: datetime = None) -> bool:
        """是否交易时间"""
        dt = dt or datetime.now()
        current_time = dt.strftime("%H:%M")

        for start, end in self.trading_hours:
            if start <= current_time <= end:
                return True

        return False


@dataclass
class Order:
    """订单"""
    order_id: str
    code: str
    exchange: Exchange
    side: str  # buy/sell
    order_type: OrderType
    quantity: int
    price: float
    status: OrderStatus
    filled_quantity: int = 0
    filled_price: float = 0
    avg_price: float = 0
    created_at: datetime = None
    updated_at: datetime = None
    parent_id: str = None
    child_orders: List[str] = field(default_factory=list)
    commission: float = 0
    slippage: float = 0

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def update_fill(self, filled_qty: int, filled_price: float):
        """更新成交"""
        self.filled_quantity += filled_qty
        self.avg_price = (
            (self.avg_price * (self.filled_quantity - filled_qty) + filled_price * filled_qty)
            / self.filled_quantity if self.filled_quantity > 0 else 0
        )
        self.updated_at = datetime.now()

        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        elif self.filled_quantity > 0:
            self.status = OrderStatus.PARTIAL

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "code": self.code,
            "exchange": self.exchange.value,
            "side": self.side,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "avg_price": round(self.avg_price, 4),
            "commission": round(self.commission, 4),
        }


@dataclass
class OrderSlice:
    """订单分片"""
    slice_id: str
    parent_id: str
    exchange: Exchange
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: int = 0
    filled_price: float = 0

    def to_dict(self) -> dict:
        return {
            "slice_id": self.slice_id,
            "parent_id": self.parent_id,
            "exchange": self.exchange.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
        }


@dataclass
class ExecutionPlan:
    """执行计划"""
    plan_id: str
    code: str
    side: str
    total_quantity: int
    target_price: float
    strategy: RoutingStrategy
    slices: List[OrderSlice] = field(default_factory=list)
    total_filled: int = 0
    avg_price: float = 0
    total_cost: float = 0
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def calculate_performance(self) -> Dict:
        """计算执行绩效"""
        return {
            "fill_rate": self.total_filled / self.total_quantity if self.total_quantity > 0 else 0,
            "avg_price": round(self.avg_price, 4),
            "slippage": round((self.avg_price - self.target_price) / self.target_price, 6) if self.target_price > 0 else 0,
            "slice_count": len(self.slices),
        }


# ============ 交易所路由器 ============

class ExchangeRouter:
    """交易所路由器"""

    def __init__(self):
        self._exchanges: Dict[Exchange, ExchangeInfo] = {}
        self._initialize_exchanges()

    def _initialize_exchanges(self):
        """初始化交易所"""
        default_exchanges = [
            ExchangeInfo(
                exchange=Exchange.SSE,
                name="上海证券交易所",
                trading_hours=[("09:30", "11:30"), ("13:00", "15:00")],
                min_order_size=100,
                max_order_size=1000000,
                price_tick=0.01,
                commission_rate=0.0003,
                latency_ms=10,
                fill_rate=0.95,
            ),
            ExchangeInfo(
                exchange=Exchange.SZSE,
                name="深圳证券交易所",
                trading_hours=[("09:30", "11:30"), ("13:00", "15:00")],
                min_order_size=100,
                max_order_size=1000000,
                price_tick=0.01,
                commission_rate=0.0003,
                latency_ms=12,
                fill_rate=0.94,
            ),
        ]

        for ex in default_exchanges:
            self._exchanges[ex.exchange] = ex

    def get_exchange(self, exchange: Exchange) -> Optional[ExchangeInfo]:
        """获取交易所信息"""
        return self._exchanges.get(exchange)

    def get_available_exchanges(self, code: str = None) -> List[ExchangeInfo]:
        """获取可用交易所"""
        exchanges = list(self._exchanges.values())

        # 按代码过滤
        if code:
            if code.startswith("6"):
                exchanges = [e for e in exchanges if e.exchange == Exchange.SSE]
            elif code.startswith("0") or code.startswith("3"):
                exchanges = [e for e in exchanges if e.exchange == Exchange.SZSE]

        # 按交易时间过滤
        exchanges = [e for e in exchanges if e.is_trading_time() and e.available]

        return exchanges

    def score_exchange(
        self,
        exchange: ExchangeInfo,
        quantity: int,
        price: float,
        strategy: RoutingStrategy,
    ) -> float:
        """交易所评分"""
        score = 100.0

        if strategy == RoutingStrategy.BEST_PRICE:
            # 价格优先
            pass
        elif strategy == RoutingStrategy.BEST_EXECUTION:
            # 综合评分
            score -= exchange.latency_ms * 0.5
            score += exchange.fill_rate * 20
        elif strategy == RoutingStrategy.MIN_COST:
            # 成本优先
            score -= exchange.commission_rate * 10000
        elif strategy == RoutingStrategy.FASTEST:
            # 速度优先
            score -= exchange.latency_ms
        else:
            # 平衡策略
            score -= exchange.latency_ms * 0.3
            score += exchange.fill_rate * 10
            score -= exchange.commission_rate * 5000

        # 规模适配
        if quantity > exchange.max_order_size:
            score -= 20

        return max(0, score)


# ============ 拆单策略器 ============

class OrderSplitter:
    """订单拆分器"""

    def __init__(self):
        self._split_configs = {
            "small": {"threshold": 1000, "slices": 1},
            "medium": {"threshold": 10000, "slices": 3},
            "large": {"threshold": 100000, "slices": 5},
            "huge": {"threshold": float('inf'), "slices": 10},
        }

    def split_order(
        self,
        quantity: int,
        price: float,
        exchange: ExchangeInfo,
        strategy: str = "auto",
    ) -> List[Tuple[int, float]]:
        """拆分订单"""
        # 确定拆分规模
        config = self._get_split_config(quantity)
        n_slices = config["slices"]

        if n_slices == 1:
            return [(quantity, price)]

        # 拆分
        slices = []
        remaining = quantity
        base_size = quantity // n_slices

        for i in range(n_slices):
            if i == n_slices - 1:
                slice_qty = remaining
            else:
                slice_qty = min(base_size, remaining)

            # 调整到最小下单单位
            slice_qty = (slice_qty // exchange.min_order_size) * exchange.min_order_size

            if slice_qty > 0:
                slices.append((slice_qty, price))
                remaining -= slice_qty

        return slices

    def _get_split_config(self, quantity: int) -> Dict:
        """获取拆分配置"""
        for name, config in self._split_configs.items():
            if quantity <= config["threshold"]:
                return config
        return self._split_configs["huge"]

    def calculate_optimal_slice_size(
        self,
        total_quantity: int,
        avg_daily_volume: float,
        max_participation: float = 0.1,
    ) -> int:
        """计算最优分片大小"""
        # 基于参与率
        max_per_slice = int(avg_daily_volume * max_participation)

        # 确保不超过总量
        optimal = min(max_per_slice, total_quantity)

        # 取整到100
        optimal = (optimal // 100) * 100

        return max(100, optimal)


# ============ 订单状态跟踪器 ============

class OrderTracker:
    """订单状态跟踪器"""

    def __init__(self):
        self._orders: Dict[str, Order] = {}
        self._execution_plans: Dict[str, ExecutionPlan] = {}
        self._order_history: deque = deque(maxlen=10000)
        self._lock = threading.Lock()

    def add_order(self, order: Order):
        """添加订单"""
        with self._lock:
            self._orders[order.order_id] = order

    def update_order(
        self,
        order_id: str,
        status: OrderStatus = None,
        filled_quantity: int = None,
        filled_price: float = None,
    ):
        """更新订单"""
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                return

            if status:
                order.status = status

            if filled_quantity is not None and filled_price is not None:
                order.update_fill(filled_quantity, filled_price)

            order.updated_at = datetime.now()

            # 记录历史
            if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
                self._order_history.append(order)

    def get_order(self, order_id: str) -> Optional[Order]:
        """获取订单"""
        return self._orders.get(order_id)

    def get_active_orders(self) -> List[Order]:
        """获取活跃订单"""
        return [
            o for o in self._orders.values()
            if o.status in [OrderStatus.NEW, OrderStatus.PARTIAL]
        ]

    def create_execution_plan(
        self,
        code: str,
        side: str,
        quantity: int,
        price: float,
        strategy: RoutingStrategy,
    ) -> ExecutionPlan:
        """创建执行计划"""
        plan_id = f"plan_{int(time.time() * 1000)}"

        plan = ExecutionPlan(
            plan_id=plan_id,
            code=code,
            side=side,
            total_quantity=quantity,
            target_price=price,
            strategy=strategy,
        )

        self._execution_plans[plan_id] = plan

        return plan

    def update_execution_plan(
        self,
        plan_id: str,
        slice_id: str,
        filled_quantity: int,
        filled_price: float,
    ):
        """更新执行计划"""
        plan = self._execution_plans.get(plan_id)
        if not plan:
            return

        # 更新分片
        for slice_obj in plan.slices:
            if slice_obj.slice_id == slice_id:
                slice_obj.filled_quantity = filled_quantity
                slice_obj.filled_price = filled_price
                slice_obj.status = OrderStatus.FILLED if filled_quantity >= slice_obj.quantity else OrderStatus.PARTIAL
                break

        # 更新总计
        plan.total_filled += filled_quantity
        total_cost = plan.total_filled * plan.avg_price + filled_quantity * filled_price
        plan.total_filled += filled_quantity
        plan.avg_price = total_cost / plan.total_filled if plan.total_filled > 0 else 0

    def get_execution_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        """获取执行计划"""
        return self._execution_plans.get(plan_id)


# ============ 智能订单路由服务 ============

class SmartOrderRouter:
    """智能订单路由服务"""

    def __init__(self):
        self.exchange_router = ExchangeRouter()
        self.order_splitter = OrderSplitter()
        self.order_tracker = OrderTracker()

        self._routing_handlers: List[callable] = []

    def route_order(
        self,
        code: str,
        side: str,
        quantity: int,
        price: float = 0,
        order_type: OrderType = OrderType.LIMIT,
        strategy: RoutingStrategy = RoutingStrategy.BALANCED,
    ) -> ExecutionPlan:
        """路由订单"""
        # 创建执行计划
        plan = self.order_tracker.create_execution_plan(
            code=code,
            side=side,
            quantity=quantity,
            price=price,
            strategy=strategy,
        )

        # 获取可用交易所
        available_exchanges = self.exchange_router.get_available_exchanges(code)

        if not available_exchanges:
            logger.warning(f"[SmartOrderRouter] 无可用交易所: {code}")
            return plan

        # 选择最优交易所
        best_exchange = self._select_best_exchange(
            available_exchanges, quantity, price, strategy
        )

        # 拆分订单
        slices = self.order_splitter.split_order(
            quantity=quantity,
            price=price,
            exchange=best_exchange,
        )

        # 创建分片订单
        for i, (slice_qty, slice_price) in enumerate(slices):
            slice_id = f"{plan.plan_id}_slice_{i}"

            slice_obj = OrderSlice(
                slice_id=slice_id,
                parent_id=plan.plan_id,
                exchange=best_exchange.exchange,
                quantity=slice_qty,
                price=slice_price,
            )

            plan.slices.append(slice_obj)

            # 创建订单
            order = Order(
                order_id=slice_id,
                code=code,
                exchange=best_exchange.exchange,
                side=side,
                order_type=order_type,
                quantity=slice_qty,
                price=slice_price,
                status=OrderStatus.NEW,
                parent_id=plan.plan_id,
            )

            self.order_tracker.add_order(order)

        # 触发处理器
        for handler in self._routing_handlers:
            try:
                handler(plan)
            except Exception as e:
                logger.error(f"[SmartOrderRouter] 处理器执行失败: {e}")

        logger.info(f"[SmartOrderRouter] 订单路由完成: {plan.plan_id}, {len(slices)}个分片")

        return plan

    def _select_best_exchange(
        self,
        exchanges: List[ExchangeInfo],
        quantity: int,
        price: float,
        strategy: RoutingStrategy,
    ) -> ExchangeInfo:
        """选择最优交易所"""
        scored = [
            (ex, self.exchange_router.score_exchange(ex, quantity, price, strategy))
            for ex in exchanges
        ]

        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[0][0] if scored else None

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        order = self.order_tracker.get_order(order_id)
        if not order:
            return False

        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
            return False

        self.order_tracker.update_order(order_id, status=OrderStatus.CANCELLED)
        logger.info(f"[SmartOrderRouter] 订单已取消: {order_id}")

        return True

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """获取订单状态"""
        order = self.order_tracker.get_order(order_id)
        return order.to_dict() if order else None

    def get_active_orders(self) -> List[Dict]:
        """获取活跃订单"""
        return [o.to_dict() for o in self.order_tracker.get_active_orders()]

    def register_handler(self, handler: callable):
        """注册处理器"""
        self._routing_handlers.append(handler)


# ============ 便捷函数 ============

def create_order_router() -> SmartOrderRouter:
    """创建订单路由器"""
    return SmartOrderRouter()


def route_order(
    code: str,
    side: str,
    quantity: int,
    price: float = 0,
) -> ExecutionPlan:
    """路由订单"""
    router = SmartOrderRouter()
    return router.route_order(code, side, quantity, price)
