"""毫秒级订单执行引擎"""
import asyncio
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import deque
import threading
import queue
import logging
logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    ICEBERG = "iceberg"
    TWAP = "twap"
    VWAP = "vwap"


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    """订单"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    avg_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    parent_id: Optional[str] = None
    child_orders: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    # 性能指标
    submission_latency_us: int = 0  # 微秒
    execution_latency_us: int = 0
    ack_latency_us: int = 0


@dataclass
class ExecutionReport:
    """执行报告"""
    report_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float
    execution_time: datetime
    latency_us: int


class OrderExecutor:
    """订单执行器"""
    
    def __init__(
        self,
        max_orders_per_second: int = 100,
        order_queue_size: int = 10000,
        latency_target_ms: float = 1.0
    ):
        self.max_orders_per_second = max_orders_per_second
        self.latency_target_ms = latency_target_ms
        
        # 订单队列
        self.order_queue = queue.PriorityQueue(maxsize=order_queue_size)
        
        # 订单管理
        self.orders: Dict[str, Order] = {}
        self.pending_orders: Dict[str, Order] = {}
        
        # 执行回调
        self.on_fill_callbacks: List[Callable] = []
        self.on_status_callbacks: List[Callable] = []
        
        # 性能统计
        self.stats = {
            'total_orders': 0,
            'filled_orders': 0,
            'cancelled_orders': 0,
            'total_volume': 0.0,
            'avg_latency_us': 0.0,
            'p99_latency_us': 0.0,
        }
        
        self.latency_history = deque(maxlen=10000)
        
        # 执行线程
        self._running = False
        self._executor_thread = None
    
    def start(self):
        """启动执行器"""
        self._running = True
        self._executor_thread = threading.Thread(target=self._execution_loop, daemon=True)
        self._executor_thread.start()
    
    def stop(self):
        """停止执行器"""
        self._running = False
        if self._executor_thread:
            self._executor_thread.join(timeout=5)
    
    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float = None,
        priority: int = 0
    ) -> Order:
        """提交订单"""
        start_time = time.perf_counter_ns()
        
        order_id = self._generate_order_id()
        
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.PENDING
        )
        
        # 记录订单
        self.orders[order_id] = order
        self.pending_orders[order_id] = order
        
        # 加入执行队列
        self.order_queue.put((priority, time.time_ns(), order))
        
        # 记录延迟
        submission_time = time.perf_counter_ns()
        order.submission_latency_us = (submission_time - start_time) // 1000
        
        self.stats['total_orders'] += 1
        
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        if order_id not in self.orders:
            return False
        
        order = self.orders[order_id]
        
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
            return False
        
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now()
        
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
        
        self.stats['cancelled_orders'] += 1
        
        # 触发回调
        self._notify_status_change(order)
        
        return True
    
    def modify_order(
        self,
        order_id: str,
        new_quantity: float = None,
        new_price: float = None
    ) -> bool:
        """修改订单"""
        if order_id not in self.orders:
            return False
        
        order = self.orders[order_id]
        
        if order.status != OrderStatus.PENDING:
            return False
        
        if new_quantity is not None:
            order.quantity = new_quantity
        if new_price is not None:
            order.price = new_price
        
        order.updated_at = datetime.now()
        
        return True
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """获取订单"""
        return self.orders.get(order_id)
    
    def get_open_orders(self, symbol: str = None) -> List[Order]:
        """获取未完成订单"""
        open_orders = [
            order for order in self.pending_orders.values()
            if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED]
        ]
        
        if symbol:
            open_orders = [o for o in open_orders if o.symbol == symbol]
        
        return open_orders
    
    def _execution_loop(self):
        """执行循环"""
        rate_limiter = 0
        last_second = time.time()
        
        while self._running:
            try:
                # 速率限制
                current_time = time.time()
                if current_time - last_second >= 1.0:
                    rate_limiter = 0
                    last_second = current_time
                
                if rate_limiter >= self.max_orders_per_second:
                    time.sleep(0.001)
                    continue
                
                # 获取订单
                try:
                    priority, timestamp, order = self.order_queue.get(timeout=0.001)
                except queue.Empty:
                    continue
                
                # 执行订单
                self._execute_order(order)
                rate_limiter += 1
                
            except Exception as e:
                pass
    
    def _execute_order(self, order: Order):
        """执行订单"""
        start_time = time.perf_counter_ns()
        
        # 模拟订单执行
        order.status = OrderStatus.SUBMITTED
        order.updated_at = datetime.now()
        
        # 模拟市场成交
        # 实际实现会连接交易接口
        filled_quantity = order.quantity
        filled_price = order.price if order.price else self._get_market_price(order.symbol)
        
        if filled_quantity > 0:
            order.filled_quantity = filled_quantity
            order.filled_price = filled_price * filled_quantity
            order.avg_price = filled_price
            order.status = OrderStatus.FILLED
            
            # 计算延迟
            end_time = time.perf_counter_ns()
            execution_latency = (end_time - start_time) // 1000
            order.execution_latency_us = execution_latency
            
            # 记录延迟
            self.latency_history.append(execution_latency)
            
            # 更新统计
            self.stats['filled_orders'] += 1
            self.stats['total_volume'] += filled_quantity * filled_price
            
            # 从待执行队列移除
            if order.order_id in self.pending_orders:
                del self.pending_orders[order.order_id]
            
            # 生成执行报告
            report = ExecutionReport(
                report_id=f"rpt_{order.order_id}",
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=filled_quantity,
                price=filled_price,
                commission=filled_quantity * filled_price * 0.0001,
                execution_time=datetime.now(),
                latency_us=execution_latency
            )
            
            # 触发回调
            self._notify_fill(report)
        
        self._notify_status_change(order)
    
    def _get_market_price(self, symbol: str) -> float:
        """获取市场价格"""
        # 模拟价格
        return 100.0
    
    def _generate_order_id(self) -> str:
        """生成订单ID"""
        return f"ord_{int(time.time() * 1000000)}"
    
    def _notify_fill(self, report: ExecutionReport):
        """通知成交"""
        for callback in self.on_fill_callbacks:
            try:
                callback(report)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
    
    def _notify_status_change(self, order: Order):
        """通知状态变更"""
        for callback in self.on_status_callbacks:
            try:
                callback(order)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
    
    def add_fill_callback(self, callback: Callable):
        """添加成交回调"""
        self.on_fill_callbacks.append(callback)
    
    def add_status_callback(self, callback: Callable):
        """添加状态回调"""
        self.on_status_callbacks.append(callback)
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        if self.latency_history:
            sorted_latencies = sorted(self.latency_history)
            self.stats['avg_latency_us'] = sum(self.latency_history) / len(self.latency_history)
            self.stats['p99_latency_us'] = sorted_latencies[int(len(sorted_latencies) * 0.99)]
        
        return self.stats.copy()
    
    async def submit_order_async(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float = None
    ) -> Order:
        """异步提交订单"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.submit_order(symbol, side, order_type, quantity, price)
        )


class BatchOrderExecutor:
    """批量订单执行器"""
    
    def __init__(self, executor: OrderExecutor):
        self.executor = executor
        self.batch_size = 100
        self.batch_timeout_ms = 10
    
    def submit_batch(
        self,
        orders: List[Dict]
    ) -> List[Order]:
        """批量提交订单"""
        submitted = []
        
        for order_data in orders:
            order = self.executor.submit_order(
                symbol=order_data['symbol'],
                side=OrderSide(order_data['side']),
                order_type=OrderType(order_data.get('type', 'market')),
                quantity=order_data['quantity'],
                price=order_data.get('price')
            )
            submitted.append(order)
        
        return submitted
    
    def submit_with_priority(
        self,
        orders: List[Dict],
        priority_fn: Callable
    ) -> List[Order]:
        """按优先级批量提交"""
        # 排序
        sorted_orders = sorted(orders, key=priority_fn, reverse=True)
        
        return self.submit_batch(sorted_orders)
