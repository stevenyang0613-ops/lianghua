"""西部量化可转债策略 V3.0 券商交易接口

支持券商:
- 华泰证券 (基于华泰API)
- 国信证券
- 东方财富
- 模拟交易

功能:
- 下单买入/卖出
- 撤单
- 查询持仓
- 查询资金
- 查询委托
- 查询成交
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Optional, Callable, Any, Tuple
from abc import ABC, abstractmethod
from enum import Enum
import logging
import json
import threading
import time

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"       # 待提交
    SUBMITTED = "submitted"   # 已提交
    PARTIAL = "partial"       # 部分成交
    FILLED = "filled"         # 全部成交
    CANCELLED = "cancelled"   # 已撤单
    REJECTED = "rejected"     # 已拒绝


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"         # 市价单
    LIMIT = "limit"           # 限价单
    LIMIT_MAKER = "limit_maker"  # 只做限价单


class OrderSide(str, Enum):
    """买卖方向"""
    BUY = "buy"
    SELL = "sell"


# ============ 数据类型 ============

@dataclass
class Order:
    """订单"""
    order_id: str
    cb_code: str
    cb_name: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = None
    updated_at: datetime = None
    message: str = ""

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "cb_code": self.cb_code,
            "cb_name": self.cb_name,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "commission": self.commission,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "message": self.message,
        }


@dataclass
class Position:
    """持仓"""
    cb_code: str
    cb_name: str
    quantity: int
    available: int           # 可用数量
    cost_price: float        # 成本价
    current_price: float     # 当前价
    market_value: float      # 市值
    profit: float            # 盈亏
    profit_pct: float        # 盈亏比例

    def to_dict(self) -> dict:
        return {
            "cb_code": self.cb_code,
            "cb_name": self.cb_name,
            "quantity": self.quantity,
            "available": self.available,
            "cost_price": self.cost_price,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "profit": self.profit,
            "profit_pct": self.profit_pct,
        }


@dataclass
class Account:
    """账户信息"""
    total_asset: float       # 总资产
    cash: float              # 可用资金
    frozen: float            # 冻结资金
    market_value: float      # 持仓市值
    profit: float            # 总盈亏
    profit_pct: float        # 收益率

    def to_dict(self) -> dict:
        return {
            "total_asset": self.total_asset,
            "cash": self.cash,
            "frozen": self.frozen,
            "market_value": self.market_value,
            "profit": self.profit,
            "profit_pct": self.profit_pct,
        }


@dataclass
class Trade:
    """成交记录"""
    trade_id: str
    order_id: str
    cb_code: str
    cb_name: str
    side: OrderSide
    quantity: int
    price: float
    amount: float
    commission: float
    traded_at: datetime

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "cb_code": self.cb_code,
            "cb_name": self.cb_name,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "amount": self.amount,
            "commission": self.commission,
            "traded_at": self.traded_at.isoformat(),
        }


# ============ 券商接口抽象 ============

class BrokerInterface(ABC):
    """券商接口抽象类"""

    @abstractmethod
    def connect(self) -> bool:
        """连接券商"""
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """断开连接"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass

    @abstractmethod
    def get_broker_name(self) -> str:
        """获取券商名称"""
        pass

    @abstractmethod
    def buy(self, code: str, name: str, quantity: int, price: float, order_type: OrderType = OrderType.LIMIT) -> Optional[Order]:
        """买入

        Args:
            code: 转债代码
            name: 转债名称
            quantity: 数量(张)
            price: 价格
            order_type: 订单类型

        Returns:
            订单对象
        """
        pass

    @abstractmethod
    def sell(self, code: str, name: str, quantity: int, price: float, order_type: OrderType = OrderType.LIMIT) -> Optional[Order]:
        """卖出"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        pass

    @abstractmethod
    def query_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        pass

    @abstractmethod
    def query_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """查询委托列表"""
        pass

    @abstractmethod
    def query_positions(self) -> List[Position]:
        """查询持仓"""
        pass

    @abstractmethod
    def query_account(self) -> Account:
        """查询账户"""
        pass

    @abstractmethod
    def query_trades(self, order_id: Optional[str] = None) -> List[Trade]:
        """查询成交记录"""
        pass


# ============ 模拟券商 ============

class SimulatedBroker(BrokerInterface):
    """模拟券商 - 用于回测和测试"""

    def __init__(self, initial_capital: float = 1000000.0):
        """初始化模拟券商

        Args:
            initial_capital: 初始资金(元)
        """
        self.initial_capital = initial_capital
        self._cash = initial_capital
        self._frozen = 0.0
        self._positions: Dict[str, Dict] = {}
        self._orders: Dict[str, Order] = {}
        self._trades: List[Trade] = []
        self._connected = False
        self._lock = threading.Lock()
        self._order_counter = 0
        self._trade_counter = 0

    def connect(self) -> bool:
        """连接"""
        self._connected = True
        logger.info("[SimulatedBroker] 连接成功")
        return True

    def disconnect(self) -> bool:
        """断开连接"""
        self._connected = False
        logger.info("[SimulatedBroker] 已断开连接")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def get_broker_name(self) -> str:
        return "simulated"

    def buy(self, code: str, name: str, quantity: int, price: float, order_type: OrderType = OrderType.LIMIT) -> Optional[Order]:
        """买入"""
        with self._lock:
            if not self._connected:
                logger.warning("[SimulatedBroker] 未连接")
                return None

            # 计算所需资金
            amount = price * quantity
            commission = self._calc_commission(amount, "buy")
            required = amount + commission

            if self._cash < required:
                logger.warning(f"[SimulatedBroker] 资金不足: 需要{required:.2f}, 可用{self._cash:.2f}")
                return None

            # 冻结资金
            self._cash -= required
            self._frozen += required

            # 创建订单
            order = self._create_order(code, name, OrderSide.BUY, quantity, price, order_type)
            self._orders[order.order_id] = order

            logger.info(f"[SimulatedBroker] 买入委托: {code} {quantity}张 @ {price:.2f}")
            return order

    def sell(self, code: str, name: str, quantity: int, price: float, order_type: OrderType = OrderType.LIMIT) -> Optional[Order]:
        """卖出"""
        with self._lock:
            if not self._connected:
                logger.warning(f"[SimulatedBroker] 未连接，无法卖出: {code}")
                return None

            # 检查持仓
            pos = self._positions.get(code)
            if not pos or pos['available'] < quantity:
                logger.warning(f"[SimulatedBroker] 持仓不足: {code}")
                return None

            # 冻结持仓
            pos['available'] -= quantity

            # 创建订单
            order = self._create_order(code, name, OrderSide.SELL, quantity, price, order_type)
            self._orders[order.order_id] = order

            logger.info(f"[SimulatedBroker] 卖出委托: {code} {quantity}张 @ {price:.2f}")
            return order

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                return False

            if order.status not in [OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL]:
                return False

            # 撤销订单
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now()

            # 释放冻结资金或持仓
            if order.side == OrderSide.BUY:
                amount = order.price * order.quantity
                commission = self._calc_commission(amount, "buy")
                self._frozen -= (amount + commission)
                self._cash += (amount + commission)
            else:
                pos = self._positions.get(order.cb_code)
                if pos:
                    pos['available'] = pos.get('available', 0) + (order.quantity - order.filled_quantity)
                else:
                    logger.warning(f"[SimulatedBroker] 撤单时持仓不存在: {order.cb_code}")

            logger.info(f"[SimulatedBroker] 撤单成功: {order_id}")
            return True

    def query_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        return self._orders.get(order_id)

    def query_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """查询委托列表"""
        orders = list(self._orders.values())
        if status:
            orders = [o for o in orders if o.status == status]
        return orders

    def query_positions(self) -> List[Position]:
        """查询持仓"""
        positions = []
        for code, pos in self._positions.items():
            if pos.get('quantity', 0) > 0:
                quantity = pos.get('quantity', 0)
                available = pos.get('available', 0)
                cost_price = pos.get('cost_price', 0)
                current_price = pos.get('current_price', cost_price)
                positions.append(Position(
                    cb_code=code,
                    cb_name=pos.get('name', code),
                    quantity=quantity,
                    available=available,
                    cost_price=cost_price,
                    current_price=current_price,
                    market_value=quantity * current_price,
                    profit=(current_price - cost_price) * quantity if cost_price > 0 else 0,
                    profit_pct=(current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0,
                ))
        return positions

    def query_account(self) -> Account:
        """查询账户"""
        market_value = sum(p['quantity'] * p.get('current_price', p['cost_price']) for p in self._positions.values())
        total = self._cash + self._frozen + market_value
        profit = total - self.initial_capital

        return Account(
            total_asset=total,
            cash=self._cash,
            frozen=self._frozen,
            market_value=market_value,
            profit=profit,
            profit_pct=profit / self.initial_capital * 100 if self.initial_capital > 0 else 0,
        )

    def query_trades(self, order_id: Optional[str] = None) -> List[Trade]:
        """查询成交记录"""
        if order_id:
            return [t for t in self._trades if t.order_id == order_id]
        return self._trades

    def simulate_fill(self, order_id: str, fill_price: Optional[float] = None) -> bool:
        """模拟成交

        Args:
            order_id: 订单ID
            fill_price: 成交价格（None则使用委托价）

        Returns:
            是否成交成功
        """
        with self._lock:
            order = self._orders.get(order_id)
            if not order or order.status not in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                return False

            price = fill_price or order.price
            amount = price * order.quantity
            commission = self._calc_commission(amount, "buy" if order.side == OrderSide.BUY else "sell")

            # 更新订单状态
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.filled_price = price
            order.commission = commission
            order.updated_at = datetime.now()

            # 更新资金和持仓
            if order.side == OrderSide.BUY:
                # 释放冻结，扣除实际金额
                frozen_amount = order.price * order.quantity
                frozen_commission = self._calc_commission(frozen_amount, "buy")
                self._frozen -= (frozen_amount + frozen_commission)

                # 退款差价
                if price < order.price:
                    self._cash += (order.price - price) * order.quantity
                elif price > order.price:
                    self._cash -= (price - order.price) * order.quantity

                # 更新持仓
                if order.cb_code not in self._positions:
                    self._positions[order.cb_code] = {
                        'name': order.cb_name,
                        'quantity': 0,
                        'available': 0,
                        'cost_price': 0,
                        'current_price': price,
                    }

                pos = self._positions[order.cb_code]
                total_cost = pos['cost_price'] * pos['quantity'] + amount
                pos['quantity'] += order.quantity
                pos['available'] += order.quantity
                pos['cost_price'] = total_cost / pos['quantity']
                pos['current_price'] = price

            else:  # SELL
                # 更新持仓
                pos = self._positions.get(order.cb_code)
                if pos:
                    pos['quantity'] -= order.quantity
                    pos['current_price'] = price

                # 增加资金
                self._cash += amount - commission

            # 记录成交
            self._trade_counter += 1
            trade = Trade(
                trade_id=f"T{self._trade_counter:08d}",
                order_id=order.order_id,
                cb_code=order.cb_code,
                cb_name=order.cb_name,
                side=order.side,
                quantity=order.quantity,
                price=price,
                amount=amount,
                commission=commission,
                traded_at=datetime.now(),
            )
            self._trades.append(trade)

            logger.info(f"[SimulatedBroker] 成交: {order.cb_code} {order.side.value} {order.quantity}张 @ {price:.2f}")
            return True

    def update_prices(self, prices: Dict[str, float]):
        """更新持仓价格

        Args:
            prices: {代码: 价格}
        """
        with self._lock:
            for code, price in prices.items():
                if code in self._positions:
                    self._positions[code]['current_price'] = price

    def _create_order(self, code: str, name: str, side: OrderSide, quantity: int, price: float, order_type: OrderType) -> Order:
        """创建订单"""
        self._order_counter += 1
        return Order(
            order_id=f"O{self._order_counter:08d}",
            cb_code=code,
            cb_name=name,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.SUBMITTED,
        )

    def _calc_commission(self, amount: float, side: str) -> float:
        """计算佣金"""
        if amount <= 0:
            return 0.0
        # 佣金万1，最低5元
        commission = max(amount * 0.0001, 5.0)
        # 印花税（卖出）
        if side == "sell":
            commission += amount * 0.001
        return commission


# ============ 华泰证券接口 ============

class HuataiBroker(BrokerInterface):
    """华泰证券接口

    需要安装华泰API: pip install htapi
    """

    def __init__(self, account: str = "", password: str = "", client_id: str = ""):
        """初始化

        Args:
            account: 账号
            password: 密码
            client_id: 客户端ID
        """
        self.account = account
        self.password = password
        self.client_id = client_id
        self._api = None
        self._connected = False

    def connect(self) -> bool:
        """连接华泰"""
        try:
            from htapi import HTApi
            self._api = HTApi(self.account, self.password, self.client_id)
            self._connected = True
            logger.info("[HuataiBroker] 连接成功")
            return True
        except ImportError:
            logger.warning("[HuataiBroker] htapi未安装")
            return False
        except Exception as e:
            logger.error(f"[HuataiBroker] 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """断开连接"""
        self._connected = False
        self._api = None
        return True

    def is_connected(self) -> bool:
        return self._connected

    def get_broker_name(self) -> str:
        return "huatai"

    def buy(self, code: str, name: str, quantity: int, price: float, order_type: OrderType = OrderType.LIMIT) -> Optional[Order]:
        """买入"""
        if not self._connected:
            return None
        try:
            result = self._api.order(code, "buy", quantity, price)
            order_id = result.get('order_id') if isinstance(result, dict) else None
            if not order_id:
                logger.error(f"[HuataiBroker] 买入失败: API返回无效结果")
                return None
            return Order(
                order_id=order_id,
                cb_code=code,
                cb_name=name,
                side=OrderSide.BUY,
                order_type=order_type,
                quantity=quantity,
                price=price,
                status=OrderStatus.SUBMITTED,
            )
        except Exception as e:
            logger.error(f"[HuataiBroker] 买入失败: {e}")
            return None

    def sell(self, code: str, name: str, quantity: int, price: float, order_type: OrderType = OrderType.LIMIT) -> Optional[Order]:
        """卖出"""
        if not self._connected:
            return None
        try:
            result = self._api.order(code, "sell", quantity, price)
            order_id = result.get('order_id') if isinstance(result, dict) else None
            if not order_id:
                logger.error(f"[HuataiBroker] 卖出失败: API返回无效结果")
                return None
            return Order(
                order_id=order_id,
                cb_code=code,
                cb_name=name,
                side=OrderSide.SELL,
                order_type=order_type,
                quantity=quantity,
                price=price,
                status=OrderStatus.SUBMITTED,
            )
        except Exception as e:
            logger.error(f"[HuataiBroker] 卖出失败: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        if not self._connected:
            return False
        try:
            self._api.cancel_order(order_id)
            return True
        except Exception as e:
            logger.warning("[Broker] cancel_order failed: %s", e)
            return False

    def query_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        if not self._connected:
            return None
        try:
            result = self._api.query_order(order_id)
            return Order(
                order_id=result['order_id'],
                cb_code=result['code'],
                cb_name=result.get('name', ''),
                side=OrderSide.BUY if result['side'] == 'buy' else OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=result['quantity'],
                price=result['price'],
                status=self._map_status(result['status']),
                filled_quantity=result.get('filled_quantity', 0),
                filled_price=result.get('filled_price', 0),
            )
        except Exception as e:
            logger.warning("[Broker] query_order failed: %s", e)
            return None

    def query_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """查询委托列表"""
        return []

    def query_positions(self) -> List[Position]:
        """查询持仓"""
        if not self._connected:
            return []
        try:
            result = self._api.query_positions()
            return [
                Position(
                    cb_code=p['code'],
                    cb_name=p.get('name', ''),
                    quantity=p['quantity'],
                    available=p.get('available', p['quantity']),
                    cost_price=p['cost_price'],
                    current_price=p.get('current_price', p['cost_price']),
                    market_value=p['quantity'] * p.get('current_price', p['cost_price']),
                    profit=p.get('profit', 0),
                    profit_pct=p.get('profit_pct', 0),
                )
                for p in result
            ]
        except Exception as e:
            logger.warning("[Broker] query_positions failed: %s", e)
            return []

    def query_account(self) -> Account:
        """查询账户"""
        if not self._connected:
            return Account(0, 0, 0, 0, 0, 0)
        try:
            result = self._api.query_account()
            return Account(
                total_asset=result.get('total_asset', 0),
                cash=result.get('cash', 0),
                frozen=result.get('frozen', 0),
                market_value=result.get('market_value', 0),
                profit=result.get('profit', 0),
                profit_pct=result.get('profit_pct', 0),
            )
        except Exception as e:
            logger.warning("[Broker] query_account failed: %s", e)
            return Account(0, 0, 0, 0, 0, 0)

    def query_trades(self, order_id: Optional[str] = None) -> List[Trade]:
        """查询成交记录"""
        return []

    def _map_status(self, status: str) -> OrderStatus:
        """映射订单状态"""
        mapping = {
            'pending': OrderStatus.PENDING,
            'submitted': OrderStatus.SUBMITTED,
            'partial': OrderStatus.PARTIAL,
            'filled': OrderStatus.FILLED,
            'cancelled': OrderStatus.CANCELLED,
            'rejected': OrderStatus.REJECTED,
        }
        return mapping.get(status, OrderStatus.PENDING)


# ============ 券商管理器 ============

class BrokerManager:
    """券商管理器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._brokers: Dict[str, BrokerInterface] = {}
        self._default_broker: str = "simulated"

        # 注册模拟券商
        self.register_broker("simulated", SimulatedBroker())

    def register_broker(self, name: str, broker: BrokerInterface) -> None:
        """注册券商"""
        self._brokers[name] = broker
        logger.info(f"[BrokerManager] 注册券商: {name}")

    def set_default_broker(self, name: str) -> bool:
        """设置默认券商"""
        if name in self._brokers:
            self._default_broker = name
            return True
        return False

    def get_broker(self, name: Optional[str] = None) -> Optional[BrokerInterface]:
        """获取券商"""
        broker_name = name or self._default_broker
        return self._brokers.get(broker_name)

    def list_brokers(self) -> List[str]:
        """列出所有券商"""
        return list(self._brokers.keys())


def get_broker_manager() -> BrokerManager:
    """获取券商管理器单例"""
    return BrokerManager()


# ============ 风控熔断机制 ============

@dataclass
class CircuitBreakerConfig:
    """熔断配置"""
    max_daily_loss_pct: float = 0.05        # 单日最大亏损比例
    max_order_amount: float = 500000        # 单笔最大金额
    max_daily_trades: int = 50              # 每日最大交易次数
    max_position_count: int = 30            # 最大持仓数
    max_single_position_pct: float = 0.10   # 单一持仓上限比例
    cooldown_minutes: int = 30              # 熔断后冷却时间


@dataclass
class CircuitBreakerStatus:
    """熔断状态"""
    is_triggered: bool = False
    trigger_reason: str = ""
    trigger_time: Optional[datetime] = None
    daily_pnl: float = 0.0
    daily_trades: int = 0

    def to_dict(self) -> dict:
        return {
            "is_triggered": self.is_triggered,
            "trigger_reason": self.trigger_reason,
            "trigger_time": self.trigger_time.isoformat() if self.trigger_time else None,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
        }


class RiskCircuitBreaker:
    """风控熔断器"""

    def __init__(self, config: CircuitBreakerConfig = None):
        """初始化

        Args:
            config: 熔断配置
        """
        self.config = config or CircuitBreakerConfig()
        self._status = CircuitBreakerStatus()
        self._initial_value = 0.0
        self._last_reset = datetime.now()

    def check_before_order(
        self,
        order: Order,
        account: Account,
        positions: List[Position],
    ) -> Tuple[bool, str]:
        """下单前检查

        Args:
            order: 订单
            account: 账户信息
            positions: 持仓列表

        Returns:
            (是否允许, 原因)
        """
        # 检查熔断状态
        if self._status.is_triggered:
            if self._check_cooldown():
                self._reset_circuit_breaker()
            else:
                return False, f"熔断中: {self._status.trigger_reason}"

        # 检查单笔金额
        order_amount = order.price * order.quantity
        if order_amount > self.config.max_order_amount:
            return False, f"单笔金额{order_amount:.0f}超过限制{self.config.max_order_amount}"

        # 检查交易次数
        if self._status.daily_trades >= self.config.max_daily_trades:
            return False, f"今日交易次数已达上限{self.config.max_daily_trades}"

        # 检查持仓数（仅买入）
        if order.side == OrderSide.BUY:
            current_count = len([p for p in positions if p.quantity > 0])
            if order.cb_code not in [p.cb_code for p in positions]:
                if current_count >= self.config.max_position_count:
                    return False, f"持仓数已达上限{self.config.max_position_count}"

        # 检查单一持仓比例（仅买入）
        if order.side == OrderSide.BUY:
            total_value = account.total_asset
            if total_value > 0:
                position_value = order_amount
                existing = next((p for p in positions if p.cb_code == order.cb_code), None)
                if existing:
                    position_value += existing.market_value

                if position_value / total_value > self.config.max_single_position_pct:
                    return False, f"单一持仓比例超过{self.config.max_single_position_pct*100:.0f}%"

        return True, "OK"

    def update_after_trade(
        self,
        account: Account,
        trade_result: Optional[Dict] = None,
    ):
        """交易后更新状态

        Args:
            account: 账户信息
            trade_result: 交易结果
        """
        # 检查日期变化，重置计数器
        now = datetime.now()
        if now.date() != self._last_reset.date():
            self._reset_daily_counter(account)

        # 更新交易次数
        self._status.daily_trades += 1

        # 计算当日盈亏
        if self._initial_value > 0:
            self._status.daily_pnl = (account.total_asset - self._initial_value) / self._initial_value

        # 检查亏损熔断
        if self._status.daily_pnl <= -self.config.max_daily_loss_pct:
            self._trigger_circuit_breaker(
                f"单日亏损{abs(self._status.daily_pnl)*100:.2f}%超过限制{self.config.max_daily_loss_pct*100:.0f}%"
            )

    def _trigger_circuit_breaker(self, reason: str):
        """触发熔断"""
        self._status.is_triggered = True
        self._status.trigger_reason = reason
        self._status.trigger_time = datetime.now()
        logger.warning(f"[CircuitBreaker] 熔断触发: {reason}")

    def _check_cooldown(self) -> bool:
        """检查冷却时间"""
        if not self._status.trigger_time:
            return True

        elapsed = (datetime.now() - self._status.trigger_time).total_seconds() / 60
        return elapsed >= self.config.cooldown_minutes

    def _reset_circuit_breaker(self):
        """重置熔断"""
        logger.info("[CircuitBreaker] 熔断重置")
        self._status.is_triggered = False
        self._status.trigger_reason = ""
        self._status.trigger_time = None

    def _reset_daily_counter(self, account: Account):
        """重置每日计数器"""
        self._status.daily_trades = 0
        self._status.daily_pnl = 0.0
        self._initial_value = account.total_asset
        self._last_reset = datetime.now()

    def get_status(self) -> CircuitBreakerStatus:
        """获取熔断状态"""
        return self._status

    def force_reset(self):
        """强制重置"""
        self._status = CircuitBreakerStatus()
        logger.info("[CircuitBreaker] 强制重置")


class AutoHedgeExecutor:
    """自动对冲执行器"""

    def __init__(
        self,
        broker: BrokerInterface,
        circuit_breaker: RiskCircuitBreaker,
        hedge_threshold: float = 0.08,  # 回撤阈值
    ):
        """初始化

        Args:
            broker: 券商接口
            circuit_breaker: 熔断器
            hedge_threshold: 对冲触发阈值
        """
        self.broker = broker
        self.circuit_breaker = circuit_breaker
        self.hedge_threshold = hedge_threshold
        self._peak_value = 0.0
        self._hedged = False

    def check_and_hedge(self, account: Account, positions: List[Position]) -> bool:
        """检查并执行对冲

        Args:
            account: 账户信息
            positions: 持仓列表

        Returns:
            是否执行了对冲
        """
        # 更新峰值
        if account.total_asset > self._peak_value:
            self._peak_value = account.total_asset

        # 计算回撤
        if self._peak_value > 0:
            drawdown = (self._peak_value - account.total_asset) / self._peak_value

            # 触发对冲
            if drawdown >= self.hedge_threshold and not self._hedged:
                self._execute_hedge(positions)
                return True

        return False

    def _execute_hedge(self, positions: List[Position]):
        """执行对冲（减仓）"""
        logger.warning(f"[AutoHedge] 触发自动对冲，减仓50%")

        for pos in positions:
            if pos.quantity > 0:
                sell_qty = pos.quantity // 2
                if sell_qty > 0:
                    # 创建卖出订单
                    self.broker.sell(
                        code=pos.cb_code,
                        name=pos.cb_name,
                        quantity=sell_qty,
                        price=pos.current_price,
                    )

        self._hedged = True

    def reset_hedge(self):
        """重置对冲状态"""
        self._hedged = False


class SmartOrderRouter:
    """智能订单路由"""

    def __init__(self, broker: BrokerInterface):
        """初始化

        Args:
            broker: 券商接口
        """
        self.broker = broker

    def route_order(
        self,
        code: str,
        name: str,
        side: OrderSide,
        quantity: int,
        target_price: float,
        liquidity_score: float = 1.0,
    ) -> List[Order]:
        """智能路由订单

        Args:
            code: 转债代码
            name: 转债名称
            side: 买卖方向
            quantity: 总数量
            target_price: 目标价格
            liquidity_score: 流动性得分

        Returns:
            订单列表
        """
        orders = []

        # 根据流动性决定拆单策略
        if liquidity_score > 0.8:
            # 高流动性：直接下单
            order = self._place_order(code, name, side, quantity, target_price)
            if order:
                orders.append(order)
        elif liquidity_score > 0.5:
            # 中流动性：拆成2笔
            half = quantity // 2
            for qty in [half, quantity - half]:
                if qty > 0:
                    order = self._place_order(code, name, side, qty, target_price)
                    if order:
                        orders.append(order)
        else:
            # 低流动性：拆成多笔小单
            chunk_size = max(100, quantity // 5)
            remaining = quantity
            while remaining > 0:
                qty = min(chunk_size, remaining)
                order = self._place_order(code, name, side, qty, target_price)
                if order:
                    orders.append(order)
                remaining -= qty

        return orders

    def _place_order(
        self,
        code: str,
        name: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> Optional[Order]:
        """下单"""
        if side == OrderSide.BUY:
            return self.broker.buy(code, name, quantity, price)
        else:
            return self.broker.sell(code, name, quantity, price)


class TradingSystem:
    """完整交易系统"""

    def __init__(
        self,
        broker: BrokerInterface,
        circuit_breaker_config: CircuitBreakerConfig = None,
    ):
        """初始化

        Args:
            broker: 券商接口
            circuit_breaker_config: 熔断配置
        """
        self.broker = broker
        self.circuit_breaker = RiskCircuitBreaker(circuit_breaker_config)
        self.auto_hedge = AutoHedgeExecutor(broker, self.circuit_breaker)
        self.smart_router = SmartOrderRouter(broker)

        self._connected = False

    def connect(self) -> bool:
        """连接"""
        self._connected = self.broker.connect()
        return self._connected

    def place_order(
        self,
        code: str,
        name: str,
        side: OrderSide,
        quantity: int,
        price: float,
        liquidity_score: float = 1.0,
    ) -> List[Order]:
        """下单（带风控检查）

        Args:
            code: 转债代码
            name: 转债名称
            side: 买卖方向
            quantity: 数量
            price: 价格
            liquidity_score: 流动性得分

        Returns:
            订单列表
        """
        if not self._connected:
            logger.warning("[TradingSystem] 未连接券商")
            return []

        # 获取账户和持仓
        account = self.broker.query_account()
        positions = self.broker.query_positions()

        # 创建临时订单用于检查
        temp_order = Order(
            order_id="temp",
            cb_code=code,
            cb_name=name,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price,
        )

        # 风控检查
        allowed, reason = self.circuit_breaker.check_before_order(temp_order, account, positions)
        if not allowed:
            logger.warning(f"[TradingSystem] 订单被拒绝: {reason}")
            return []

        # 智能路由
        orders = self.smart_router.route_order(code, name, side, quantity, price, liquidity_score)

        # 更新风控状态（仅当订单成功提交后）
        if orders:
            self.circuit_breaker.update_after_trade(account)

        # 检查自动对冲
        account = self.broker.query_account()
        positions = self.broker.query_positions()
        self.auto_hedge.check_and_hedge(account, positions)

        return orders

    def cancel_all_orders(self) -> int:
        """撤销所有委托

        Returns:
            撤销数量
        """
        orders = self.broker.query_orders(status=OrderStatus.SUBMITTED)
        count = 0
        for order in orders:
            if self.broker.cancel_order(order.order_id):
                count += 1
        return count

    def get_status(self) -> Dict:
        """获取系统状态"""
        account = self.broker.query_account() if self._connected else Account(0, 0, 0, 0, 0, 0)
        positions = self.broker.query_positions() if self._connected else []

        return {
            "connected": self._connected,
            "account": account.to_dict(),
            "positions": [p.to_dict() for p in positions],
            "circuit_breaker": self.circuit_breaker.get_status().to_dict(),
        }
