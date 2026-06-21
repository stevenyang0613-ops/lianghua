"""西部量化可转债策略 V3.0 边缘计算模块

功能:
- 低延迟交易执行
- 边缘节点部署
- FPGA加速
- 市场数据预处理
- 本地信号计算
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import time
import threading
import queue
from collections import deque, defaultdict
import numpy as np

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class EdgeNodeType(str, Enum):
    """边缘节点类型"""
    TRADING = "trading"       # 交易节点
    DATA = "data"             # 数据节点
    SIGNAL = "signal"         # 信号节点
    GATEWAY = "gateway"       # 网关节点


class ExecutionMode(str, Enum):
    """执行模式"""
    NORMAL = "normal"         # 正常模式
    FAST = "fast"             # 快速模式
    AGGRESSIVE = "aggressive" # 激进模式


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"
    SENT = "sent"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# ============ 配置类 ============

@dataclass
class EdgeConfig:
    """边缘节点配置"""
    node_id: str
    node_type: EdgeNodeType
    region: str = "cn-east"
    latency_target_ms: float = 1.0  # 目标延迟
    max_batch_size: int = 100
    buffer_size: int = 10000
    enable_fpga: bool = False
    enable_local_cache: bool = True


@dataclass
class LatencyMetrics:
    """延迟指标"""
    data_receive_ms: float = 0
    signal_calc_ms: float = 0
    order_generate_ms: float = 0
    order_send_ms: float = 0
    total_ms: float = 0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


# ============ 低延迟执行引擎 ============

class LowLatencyExecutor:
    """低延迟执行引擎"""

    def __init__(self, config: EdgeConfig):
        self.config = config
        self._order_queue = queue.PriorityQueue(maxsize=config.buffer_size)
        self._execution_callbacks: List[Callable] = []
        self._latency_history: deque = deque(maxlen=10000)
        self._running = False
        self._worker_thread: threading.Thread = None
        self._lock = threading.Lock()

        # 性能统计
        self._stats = {
            "orders_sent": 0,
            "orders_filled": 0,
            "avg_latency_ms": 0,
            "max_latency_ms": 0,
            "p99_latency_ms": 0,
        }

    def start(self):
        """启动执行引擎"""
        self._running = True
        self._worker_thread = threading.Thread(target=self._execution_loop, daemon=True)
        self._worker_thread.start()
        logger.info(f"[LowLatencyExecutor] 启动: {self.config.node_id}")

    def stop(self):
        """停止执行引擎"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info(f"[LowLatencyExecutor] 停止: {self.config.node_id}")

    def submit_order(
        self,
        code: str,
        action: str,
        quantity: int,
        price: float,
        priority: int = 0,
        mode: ExecutionMode = ExecutionMode.NORMAL,
    ) -> str:
        """提交订单"""
        order_id = self._generate_order_id(code)

        order = {
            "order_id": order_id,
            "code": code,
            "action": action,
            "quantity": quantity,
            "price": price,
            "mode": mode,
            "priority": priority,
            "submit_time": time.perf_counter_ns(),
            "status": OrderStatus.PENDING.value,
        }

        # 入队
        try:
            self._order_queue.put((-priority, time.perf_counter_ns(), order), block=False)
        except queue.Full:
            logger.warning("[LowLatencyExecutor] 订单队列已满")
            return None

        return order_id

    def _execution_loop(self):
        """执行循环"""
        while self._running:
            try:
                # 非阻塞获取
                priority, submit_time, order = self._order_queue.get(timeout=0.001)

                start_time = time.perf_counter_ns()

                # 执行订单
                self._execute_order(order)

                end_time = time.perf_counter_ns()

                # 记录延迟
                latency_ns = end_time - submit_time
                latency_ms = latency_ns / 1_000_000

                self._latency_history.append(latency_ms)
                self._update_stats(latency_ms)

                # 检查是否超时
                if latency_ms > self.config.latency_target_ms:
                    logger.warning(
                        f"[LowLatencyExecutor] 延迟超标: {order['code']}, "
                        f"{latency_ms:.3f}ms > {self.config.latency_target_ms}ms"
                    )

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[LowLatencyExecutor] 执行异常: {e}")

    def _execute_order(self, order: Dict):
        """执行订单"""
        order["status"] = OrderStatus.SENT.value
        order["send_time"] = time.perf_counter_ns()

        # 调用执行回调
        for callback in self._execution_callbacks:
            try:
                callback(order)
            except Exception as e:
                logger.error(f"[LowLatencyExecutor] 回调执行失败: {e}")

        # 更新统计
        self._stats["orders_sent"] += 1

    def _update_stats(self, latency_ms: float):
        """更新统计"""
        history = list(self._latency_history)

        self._stats["avg_latency_ms"] = sum(history) / len(history) if history else 0
        self._stats["max_latency_ms"] = max(history) if history else 0

        if len(history) >= 100:
            sorted_history = sorted(history)
            p99_index = int(len(sorted_history) * 0.99)
            self._stats["p99_latency_ms"] = sorted_history[p99_index]

    def _generate_order_id(self, code: str) -> str:
        """生成订单ID"""
        return f"ORD_{code}_{int(time.time() * 1000000)}"

    def register_callback(self, callback: Callable):
        """注册执行回调"""
        self._execution_callbacks.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        return self._stats.copy()

    def get_latency_percentiles(self) -> Dict[str, float]:
        """获取延迟百分位"""
        if not self._latency_history:
            return {}

        history = sorted(self._latency_history)
        n = len(history)

        return {
            "p50": history[int(n * 0.50)],
            "p90": history[int(n * 0.90)],
            "p95": history[int(n * 0.95)],
            "p99": history[int(n * 0.99)],
            "max": history[-1],
        }


# ============ 边缘节点管理器 ============

class EdgeNodeManager:
    """边缘节点管理器"""

    def __init__(self):
        self._nodes: Dict[str, EdgeConfig] = {}
        self._executors: Dict[str, LowLatencyExecutor] = {}
        self._node_status: Dict[str, Dict] = {}

    def register_node(self, config: EdgeConfig):
        """注册节点"""
        self._nodes[config.node_id] = config

        # 创建执行器
        if config.node_type == EdgeNodeType.TRADING:
            executor = LowLatencyExecutor(config)
            self._executors[config.node_id] = executor

        self._node_status[config.node_id] = {
            "status": "registered",
            "last_heartbeat": datetime.now().isoformat(),
        }

        logger.info(f"[EdgeNodeManager] 注册节点: {config.node_id} ({config.node_type.value})")

    def start_node(self, node_id: str) -> bool:
        """启动节点"""
        if node_id not in self._executors:
            return False

        self._executors[node_id].start()
        self._node_status[node_id]["status"] = "running"
        return True

    def stop_node(self, node_id: str) -> bool:
        """停止节点"""
        if node_id not in self._executors:
            return False

        self._executors[node_id].stop()
        self._node_status[node_id]["status"] = "stopped"
        return True

    def get_node_status(self, node_id: str) -> Optional[Dict]:
        """获取节点状态"""
        status = self._node_status.get(node_id, {}).copy()

        if node_id in self._executors:
            status["stats"] = self._executors[node_id].get_stats()
            status["latency"] = self._executors[node_id].get_latency_percentiles()

        return status

    def get_all_nodes(self) -> List[Dict]:
        """获取所有节点"""
        return [
            {
                "node_id": node_id,
                "config": config.__dict__,
                "status": self._node_status.get(node_id, {}),
            }
            for node_id, config in self._nodes.items()
        ]

    def submit_order_to_node(
        self,
        node_id: str,
        code: str,
        action: str,
        quantity: int,
        price: float,
        priority: int = 0,
    ) -> Optional[str]:
        """向指定节点提交订单"""
        if node_id not in self._executors:
            return None

        return self._executors[node_id].submit_order(
            code=code,
            action=action,
            quantity=quantity,
            price=price,
            priority=priority,
        )


# ============ 市场数据预处理器 ============

class MarketDataPreprocessor:
    """市场数据预处理器"""

    def __init__(self, buffer_size: int = 10000):
        self.buffer_size = buffer_size
        self._buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=buffer_size))
        self._callbacks: List[Callable] = []

    def process_tick(self, tick: Dict):
        """处理Tick数据"""
        code = tick.get("code")
        if not code:
            return

        # 快速预处理
        processed = {
            "code": code,
            "timestamp": tick.get("timestamp", time.perf_counter_ns()),
            "price": float(tick.get("price", 0)),
            "volume": int(tick.get("volume", 0)),
            "bid": float(tick.get("bid", 0)),
            "ask": float(tick.get("ask", 0)),
        }

        # 缓存
        self._buffers[code].append(processed)

        # 触发回调
        for callback in self._callbacks:
            try:
                callback(processed)
            except Exception as e:
                logger.error(f"[MarketDataPreprocessor] 回调失败: {e}")

    def get_recent_ticks(self, code: str, count: int = 100) -> List[Dict]:
        """获取最近Tick"""
        buffer = self._buffers.get(code, [])
        return list(buffer)[-count:]

    def calculate_vwap(self, code: str, window: int = 100) -> float:
        """计算VWAP"""
        ticks = self.get_recent_ticks(code, window)
        if not ticks:
            return 0

        total_value = sum(t["price"] * t["volume"] for t in ticks)
        total_volume = sum(t["volume"] for t in ticks)

        return total_value / total_volume if total_volume > 0 else 0

    def calculate_momentum(self, code: str, window: int = 10) -> float:
        """计算动量"""
        ticks = self.get_recent_ticks(code, window)
        if len(ticks) < 2:
            return 0

        first_price = ticks[0]["price"]
        last_price = ticks[-1]["price"]

        return (last_price - first_price) / first_price if first_price > 0 else 0

    def register_callback(self, callback: Callable):
        """注册回调"""
        self._callbacks.append(callback)


# ============ 本地信号计算器 ============

class LocalSignalCalculator:
    """本地信号计算器"""

    def __init__(self, preprocessor: MarketDataPreprocessor):
        self.preprocessor = preprocessor
        self._signal_handlers: List[Callable] = []
        self._config = {
            "momentum_threshold": 0.02,
            "vwap_deviation": 0.01,
            "volume_spike": 2.0,
        }

    def calculate_signal(self, code: str) -> Optional[Dict]:
        """计算信号"""
        ticks = self.preprocessor.get_recent_ticks(code, 100)
        if len(ticks) < 10:
            return None

        # 动量
        momentum = self.preprocessor.calculate_momentum(code, 50)

        # VWAP
        vwap = self.preprocessor.calculate_vwap(code, 100)
        current_price = ticks[-1]["price"]
        vwap_deviation = (current_price - vwap) / vwap if vwap > 0 else 0

        # 成交量
        recent_volume = sum(t["volume"] for t in ticks[-10:])
        avg_volume = sum(t["volume"] for t in ticks) / len(ticks) if ticks else 0
        volume_ratio = recent_volume / (avg_volume * 10) if avg_volume > 0 else 0

        # 信号判断
        signal = None

        if momentum > self._config["momentum_threshold"]:
            if vwap_deviation < self._config["vwap_deviation"]:
                signal = {
                    "code": code,
                    "action": "buy",
                    "strength": min(1.0, momentum * 10),
                    "reason": "momentum_breakout",
                    "timestamp": time.perf_counter_ns(),
                }

        elif momentum < -self._config["momentum_threshold"]:
            signal = {
                "code": code,
                "action": "sell",
                "strength": min(1.0, abs(momentum) * 10),
                "reason": "momentum_breakdown",
                "timestamp": time.perf_counter_ns(),
            }

        if signal:
            for handler in self._signal_handlers:
                try:
                    handler(signal)
                except Exception as e:
                    logger.error(f"[LocalSignalCalculator] 信号处理失败: {e}")

        return signal

    def register_signal_handler(self, handler: Callable):
        """注册信号处理器"""
        self._signal_handlers.append(handler)


# ============ FPGA加速接口 ============

class FPGAAccelerator:
    """FPGA加速器接口"""

    def __init__(self, device_path: str = "/dev/fpga0"):
        self.device_path = device_path
        self._available = False
        self._check_availability()

    def _check_availability(self):
        """检查FPGA可用性"""
        # 实际部署时检查设备文件
        self._available = False

    def accelerate_calculation(
        self,
        operation: str,
        data: np.ndarray,
    ) -> Optional[np.ndarray]:
        """加速计算"""
        if not self._available:
            return None

        # 模拟FPGA加速
        if operation == "matrix_multiply":
            return self._fpga_matrix_multiply(data)
        elif operation == "fft":
            return self._fpga_fft(data)
        elif operation == "correlation":
            return self._fpga_correlation(data)

        return None

    def _fpga_matrix_multiply(self, data: np.ndarray) -> np.ndarray:
        """FPGA矩阵乘法"""
        # 实际实现需要FPGA驱动
        return np.dot(data, data.T)

    def _fpga_fft(self, data: np.ndarray) -> np.ndarray:
        """FPGA FFT"""
        return np.fft.fft(data)

    def _fpga_correlation(self, data: np.ndarray) -> np.ndarray:
        """FPGA相关计算"""
        return np.corrcoef(data)

    def is_available(self) -> bool:
        """检查是否可用"""
        return self._available


# ============ 边缘计算协调器 ============

class EdgeCoordinator:
    """边缘计算协调器"""

    def __init__(self):
        self.node_manager = EdgeNodeManager()
        self.preprocessor = MarketDataPreprocessor()
        self.signal_calculator = LocalSignalCalculator(self.preprocessor)
        self.fpga = FPGAAccelerator()

    def initialize(self, node_configs: List[EdgeConfig]):
        """初始化"""
        for config in node_configs:
            self.node_manager.register_node(config)
            self.node_manager.start_node(config.node_id)

        logger.info("[EdgeCoordinator] 初始化完成")

    def process_market_data(self, tick: Dict):
        """处理市场数据"""
        self.preprocessor.process_tick(tick)

        # 本地信号计算
        code = tick.get("code")
        if code:
            self.signal_calculator.calculate_signal(code)

    def submit_order(
        self,
        code: str,
        action: str,
        quantity: int,
        price: float,
        node_id: str = None,
    ) -> Optional[str]:
        """提交订单"""
        if node_id:
            return self.node_manager.submit_order_to_node(
                node_id=node_id,
                code=code,
                action=action,
                quantity=quantity,
                price=price,
            )

        # 选择最优节点
        best_node = self._select_best_node()
        if best_node:
            return self.node_manager.submit_order_to_node(
                node_id=best_node,
                code=code,
                action=action,
                quantity=quantity,
                price=price,
            )

        return None

    def _select_best_node(self) -> Optional[str]:
        """选择最优节点"""
        min_latency = float("inf")
        best_node = None

        for node_id, status in self.node_manager._node_status.items():
            if status.get("status") != "running":
                continue

            latency = status.get("latency", {}).get("p99", float("inf"))
            if latency < min_latency:
                min_latency = latency
                best_node = node_id

        return best_node

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "nodes": self.node_manager.get_all_nodes(),
            "fpga_available": self.fpga.is_available(),
            "buffer_sizes": {
                code: len(buffer)
                for code, buffer in self.preprocessor._buffers.items()
            },
        }


# ============ 便捷函数 ============

def create_edge_coordinator() -> EdgeCoordinator:
    """创建边缘计算协调器"""
    return EdgeCoordinator()


def create_low_latency_executor(config: EdgeConfig) -> LowLatencyExecutor:
    """创建低延迟执行器"""
    return LowLatencyExecutor(config)
