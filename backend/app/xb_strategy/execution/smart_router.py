"""西部量化可转债策略 V3.0 智能交易路由模块

功能:
- 多券商智能拆单
- TWAP/VWAP执行算法
- 冲击成本最小化
- 暗池流动性探测
- 最优执行路径
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import math
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class ExecutionAlgorithm(str, Enum):
    """执行算法"""
    MARKET = "market"               # 市价单
    LIMIT = "limit"                 # 限价单
    TWAP = "twap"                   # 时间加权平均价
    VWAP = "vwap"                   # 成交量加权平均价
    POV = "pov"                     # 占比成交
    IS = "implementation_shortfall" # 实现缺口
    ADAPTIVE = "adaptive"           # 自适应


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    ICEBERG = "iceberg"


class BrokerType(str, Enum):
    """券商类型"""
    XTB = "xtb"
    HUABAO = "huabao"
    GUOXIN = "guoxin"
    ZHONGTAI = "zhongtai"
    HUATAI = "huatai"


class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ============ 配置类 ============

@dataclass
class BrokerConfig:
    """券商配置"""
    broker_id: str
    broker_type: BrokerType
    name: str
    api_url: str = ""
    account: str = ""
    password: str = ""
    commission_rate: float = 0.0003  # 佣金率
    min_commission: float = 5.0      # 最低佣金
    max_order_size: int = 100000     # 最大单笔数量
    max_daily_volume: int = 1000000  # 日最大交易量
    latency_ms: float = 50           # 平均延迟
    success_rate: float = 0.99       # 成功率
    enabled: bool = True


@dataclass
class ExecutionConfig:
    """执行配置"""
    algorithm: ExecutionAlgorithm = ExecutionAlgorithm.VWAP
    max_participation_rate: float = 0.1  # 最大参与率
    min_slice_size: int = 100         # 最小分片
    max_slice_interval: float = 30    # 最大分片间隔(秒)
    price_tolerance: float = 0.001    # 价格容忍度
    urgency: float = 0.5              # 紧急程度 [0, 1]
    enable_dark_pool: bool = True     # 启用暗池
    max_slippage: float = 0.005       # 最大滑点


@dataclass
class OrderSlice:
    """订单分片"""
    slice_id: str
    parent_id: str
    broker_id: str
    code: str
    side: OrderSide
    quantity: int
    price: float
    order_type: OrderType
    status: ExecutionStatus = ExecutionStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0
    created_at: datetime = None
    sent_at: datetime = None
    filled_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "slice_id": self.slice_id,
            "parent_id": self.parent_id,
            "broker_id": self.broker_id,
            "code": self.code,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "order_type": self.order_type.value,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
        }


@dataclass
class ExecutionPlan:
    """执行计划"""
    plan_id: str
    code: str
    side: OrderSide
    total_quantity: int
    target_price: float
    algorithm: ExecutionAlgorithm
    slices: List[OrderSlice] = field(default_factory=list)
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: datetime = None
    started_at: datetime = None
    completed_at: datetime = None
    filled_quantity: int = 0
    avg_price: float = 0
    total_cost: float = 0
    slippage: float = 0

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def calculate_metrics(self):
        """计算指标"""
        if self.filled_quantity > 0:
            self.avg_price = self.total_cost / self.filled_quantity
            self.slippage = (self.avg_price - self.target_price) / self.target_price
            if self.side == OrderSide.SELL:
                self.slippage = -self.slippage

    def to_dict(self) -> dict:
        self.calculate_metrics()
        return {
            "plan_id": self.plan_id,
            "code": self.code,
            "side": self.side.value,
            "total_quantity": self.total_quantity,
            "target_price": self.target_price,
            "algorithm": self.algorithm.value,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "avg_price": round(self.avg_price, 4),
            "slippage": round(self.slippage, 6),
            "slices": [s.to_dict() for s in self.slices],
        }


# ============ 冲击成本模型 ============

class ImpactModel:
    """冲击成本模型"""

    def __init__(self):
        # 历史冲击数据
        self._impact_history: Dict[str, List[Dict]] = defaultdict(list)

        # 模型参数 (可基于历史数据拟合)
        self._params = {
            "linear_coef": 0.1,      # 线性系数
            "sqrt_coef": 0.05,       # 平方根系数
            "temporal_decay": 0.95,  # 时间衰减
        }

    def estimate_impact(
        self,
        code: str,
        quantity: int,
        adv: float,  # 平均日成交量
        volatility: float,
    ) -> Dict[str, float]:
        """估算冲击成本"""
        if adv <= 0:
            return {"impact": 0, "confidence": 0}

        participation = quantity / adv

        # Almgren-Chriss模型简化版
        # 临时冲击
        temporary_impact = self._params["linear_coef"] * participation * volatility

        # 永久冲击
        permanent_impact = self._params["sqrt_coef"] * math.sqrt(participation) * volatility

        # 总冲击
        total_impact = temporary_impact + permanent_impact

        # 置信度 (基于历史数据量)
        confidence = min(1.0, len(self._impact_history[code]) / 100)

        return {
            "impact": total_impact,
            "temporary": temporary_impact,
            "permanent": permanent_impact,
            "participation": participation,
            "confidence": confidence,
        }

    def record_actual_impact(
        self,
        code: str,
        expected_price: float,
        actual_price: float,
        quantity: int,
        adv: float,
    ):
        """记录实际冲击"""
        impact = abs(actual_price - expected_price) / expected_price

        self._impact_history[code].append({
            "impact": impact,
            "participation": quantity / adv if adv > 0 else 0,
            "timestamp": datetime.now().isoformat(),
        })

    def optimize_slice_size(
        self,
        code: str,
        total_quantity: int,
        adv: float,
        volatility: float,
        max_impact: float = 0.01,
    ) -> int:
        """优化分片大小"""
        # 二分搜索最优分片大小
        low, high = 100, total_quantity
        optimal = total_quantity

        while low < high:
            mid = (low + high) // 2
            impact = self.estimate_impact(code, mid, adv, volatility)

            if impact["impact"] <= max_impact:
                optimal = mid
                low = mid + 1
            else:
                high = mid

        return optimal


# ============ 暗池探测器 ============

class DarkPoolScanner:
    """暗池流动性探测器"""

    def __init__(self):
        # 暗池配置
        self._dark_pools: Dict[str, Dict] = {
            "pool_1": {"name": "暗池A", "latency_ms": 10, "fill_rate": 0.3},
            "pool_2": {"name": "暗池B", "latency_ms": 15, "fill_rate": 0.25},
            "pool_3": {"name": "暗池C", "latency_ms": 20, "fill_rate": 0.2},
        }

        # 流动性缓存
        self._liquidity_cache: Dict[str, Dict] = {}

    def scan_liquidity(self, code: str, side: OrderSide, quantity: int) -> Dict[str, Any]:
        """扫描暗池流动性"""
        result = {
            "code": code,
            "side": side.value,
            "total_available": 0,
            "pools": [],
        }

        for pool_id, pool_config in self._dark_pools.items():
            # 模拟流动性探测
            available = self._probe_pool(pool_id, code, side)

            if available > 0:
                result["pools"].append({
                    "pool_id": pool_id,
                    "name": pool_config["name"],
                    "available": available,
                    "latency_ms": pool_config["latency_ms"],
                    "fill_rate": pool_config["fill_rate"],
                })
                result["total_available"] += available

        # 按可用量排序
        result["pools"].sort(key=lambda x: x["available"], reverse=True)

        return result

    def _probe_pool(self, pool_id: str, code: str, side: OrderSide) -> int:
        """探测单个暗池"""
        # 实际实现需要调用暗池API
        # 这里返回模拟值
        import random
        return random.randint(0, 10000)

    def route_to_dark_pool(
        self,
        pool_id: str,
        code: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> Optional[str]:
        """路由到暗池"""
        pool = self._dark_pools.get(pool_id)
        if not pool:
            return None

        # 创建暗池订单
        order_id = f"dark_{pool_id}_{int(time.time() * 1000)}"

        logger.info(f"[DarkPoolScanner] 路由暗池订单: {order_id}")

        return order_id


# ============ TWAP执行器 ============

class TWAPExecutor:
    """TWAP执行器"""

    def __init__(self, config: ExecutionConfig = None):
        self.config = config or ExecutionConfig(algorithm=ExecutionAlgorithm.TWAP)
        self._active_plans: Dict[str, ExecutionPlan] = {}
        self._lock = threading.Lock()

    def create_plan(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        target_price: float,
        duration_seconds: float,
    ) -> ExecutionPlan:
        """创建执行计划"""
        plan_id = f"twap_{int(time.time() * 1000)}"

        # 计算分片
        num_slices = max(1, int(duration_seconds / self.config.max_slice_interval))
        slice_quantity = quantity // num_slices
        remainder = quantity % num_slices

        slices = []
        for i in range(num_slices):
            qty = slice_quantity + (1 if i < remainder else 0)

            slice_obj = OrderSlice(
                slice_id=f"{plan_id}_slice_{i}",
                parent_id=plan_id,
                broker_id="",  # 待分配
                code=code,
                side=side,
                quantity=qty,
                price=target_price,
                order_type=OrderType.LIMIT,
            )
            slices.append(slice_obj)

        plan = ExecutionPlan(
            plan_id=plan_id,
            code=code,
            side=side,
            total_quantity=quantity,
            target_price=target_price,
            algorithm=ExecutionAlgorithm.TWAP,
            slices=slices,
        )

        with self._lock:
            self._active_plans[plan_id] = plan

        logger.info(f"[TWAPExecutor] 创建计划: {plan_id}, 分片数: {num_slices}")

        return plan

    def get_next_slice(self, plan_id: str) -> Optional[OrderSlice]:
        """获取下一个分片"""
        with self._lock:
            plan = self._active_plans.get(plan_id)
            if not plan:
                return None

            for slice_obj in plan.slices:
                if slice_obj.status == ExecutionStatus.PENDING:
                    return slice_obj

            return None

    def update_slice_status(
        self,
        slice_id: str,
        status: ExecutionStatus,
        filled_quantity: int = 0,
        filled_price: float = 0,
    ):
        """更新分片状态"""
        with self._lock:
            for plan in self._active_plans.values():
                for slice_obj in plan.slices:
                    if slice_obj.slice_id == slice_id:
                        slice_obj.status = status
                        slice_obj.filled_quantity = filled_quantity
                        slice_obj.filled_price = filled_price
                        slice_obj.filled_at = datetime.now()

                        if status == ExecutionStatus.COMPLETED:
                            plan.filled_quantity += filled_quantity
                            plan.total_cost += filled_quantity * filled_price

                        return

    def get_plan_status(self, plan_id: str) -> Optional[Dict]:
        """获取计划状态"""
        with self._lock:
            plan = self._active_plans.get(plan_id)
            if plan:
                return plan.to_dict()
            return None


# ============ VWAP执行器 ============

class VWAPExecutor:
    """VWAP执行器"""

    def __init__(self, config: ExecutionConfig = None):
        self.config = config or ExecutionConfig(algorithm=ExecutionAlgorithm.VWAP)
        self._active_plans: Dict[str, ExecutionPlan] = {}
        self._volume_profiles: Dict[str, List[float]] = {}  # 成交量曲线
        self._lock = threading.Lock()

    def set_volume_profile(self, code: str, profile: List[float]):
        """设置成交量曲线 (每小时成交占比)"""
        self._volume_profiles[code] = profile

    def create_plan(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        target_price: float,
        volume_profile: List[float] = None,
    ) -> ExecutionPlan:
        """创建执行计划"""
        plan_id = f"vwap_{int(time.time() * 1000)}"

        # 使用提供的或历史成交量曲线
        profile = volume_profile or self._volume_profiles.get(code, self._default_profile())

        # 根据成交量曲线分配数量
        slices = []
        remaining = quantity

        for i, pct in enumerate(profile):
            if remaining <= 0:
                break

            slice_qty = int(quantity * pct * self.config.max_participation_rate)
            slice_qty = min(slice_qty, remaining)

            if slice_qty < self.config.min_slice_size:
                continue

            slice_obj = OrderSlice(
                slice_id=f"{plan_id}_slice_{i}",
                parent_id=plan_id,
                broker_id="",
                code=code,
                side=side,
                quantity=slice_qty,
                price=target_price,
                order_type=OrderType.LIMIT,
            )
            slices.append(slice_obj)
            remaining -= slice_qty

        # 处理剩余
        if remaining > 0 and slices:
            slices[-1].quantity += remaining

        plan = ExecutionPlan(
            plan_id=plan_id,
            code=code,
            side=side,
            total_quantity=quantity,
            target_price=target_price,
            algorithm=ExecutionAlgorithm.VWAP,
            slices=slices,
        )

        with self._lock:
            self._active_plans[plan_id] = plan

        return plan

    def _default_profile(self) -> List[float]:
        """默认成交量曲线 (24小时)"""
        # 典型的日内成交分布
        return [
            0.05, 0.08, 0.12, 0.10,  # 9:30-10:30
            0.08, 0.06, 0.05, 0.04,  # 10:30-14:00
            0.06, 0.10, 0.15, 0.11,  # 14:00-15:00
        ]


# ============ 智能路由器 ============

class SmartRouter:
    """智能交易路由器"""

    def __init__(self):
        self.brokers: Dict[str, BrokerConfig] = {}
        self.impact_model = ImpactModel()
        self.dark_pool_scanner = DarkPoolScanner()
        self.twap_executor = TWAPExecutor()
        self.vwap_executor = VWAPExecutor()

        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4)

        # 统计
        self._stats = {
            "total_orders": 0,
            "total_volume": 0,
            "avg_slippage": 0,
            "dark_pool_rate": 0,
        }

    def register_broker(self, config: BrokerConfig):
        """注册券商"""
        self.brokers[config.broker_id] = config
        logger.info(f"[SmartRouter] 注册券商: {config.name}")

    def route_order(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        price: float,
        algorithm: ExecutionAlgorithm = ExecutionAlgorithm.VWAP,
        config: ExecutionConfig = None,
    ) -> ExecutionPlan:
        """路由订单"""
        config = config or ExecutionConfig(algorithm=algorithm)

        # 选择执行算法
        if algorithm == ExecutionAlgorithm.TWAP:
            plan = self.twap_executor.create_plan(
                code=code,
                side=side,
                quantity=quantity,
                target_price=price,
                duration_seconds=3600,  # 默认1小时
            )
        elif algorithm == ExecutionAlgorithm.VWAP:
            plan = self.vwap_executor.create_plan(
                code=code,
                side=side,
                quantity=quantity,
                target_price=price,
            )
        else:
            plan = self._create_market_order(code, side, quantity, price)

        # 分配券商
        self._assign_brokers(plan)

        # 检查暗池
        if config.enable_dark_pool:
            self._check_dark_pools(plan, config)

        self._stats["total_orders"] += 1
        self._stats["total_volume"] += quantity

        return plan

    def _create_market_order(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> ExecutionPlan:
        """创建市价单计划"""
        plan_id = f"market_{int(time.time() * 1000)}"

        slice_obj = OrderSlice(
            slice_id=f"{plan_id}_slice_0",
            parent_id=plan_id,
            broker_id="",
            code=code,
            side=side,
            quantity=quantity,
            price=price,
            order_type=OrderType.MARKET,
        )

        return ExecutionPlan(
            plan_id=plan_id,
            code=code,
            side=side,
            total_quantity=quantity,
            target_price=price,
            algorithm=ExecutionAlgorithm.MARKET,
            slices=[slice_obj],
        )

    def _assign_brokers(self, plan: ExecutionPlan):
        """分配券商"""
        available_brokers = [
            b for b in self.brokers.values()
            if b.enabled
        ]

        if not available_brokers:
            logger.warning("[SmartRouter] 无可用券商")
            return

        # 按评分排序
        scored_brokers = []
        for broker in available_brokers:
            score = self._score_broker(broker, plan)
            scored_brokers.append((broker, score))

        scored_brokers.sort(key=lambda x: x[1], reverse=True)

        # 分配
        for i, slice_obj in enumerate(plan.slices):
            broker = scored_brokers[i % len(scored_brokers)][0]
            slice_obj.broker_id = broker.broker_id

    def _score_broker(self, broker: BrokerConfig, plan: ExecutionPlan) -> float:
        """券商评分"""
        score = 0.0

        # 成功率
        score += broker.success_rate * 40

        # 延迟 (越低越好)
        score += max(0, 30 - broker.latency_ms / 10)

        # 佣金 (越低越好)
        score += max(0, 20 - broker.commission_rate * 10000)

        # 容量
        if broker.max_order_size >= plan.total_quantity:
            score += 10

        return score

    def _check_dark_pools(self, plan: ExecutionPlan, config: ExecutionConfig):
        """检查暗池"""
        for slice_obj in plan.slices:
            liquidity = self.dark_pool_scanner.scan_liquidity(
                code=slice_obj.code,
                side=slice_obj.side,
                quantity=slice_obj.quantity,
            )

            if liquidity["total_available"] >= slice_obj.quantity * 0.3:
                # 可以利用暗池
                best_pool = liquidity["pools"][0] if liquidity["pools"] else None
                if best_pool:
                    # 创建暗池订单
                    dark_order_id = self.dark_pool_scanner.route_to_dark_pool(
                        pool_id=best_pool["pool_id"],
                        code=slice_obj.code,
                        side=slice_obj.side,
                        quantity=min(slice_obj.quantity, int(best_pool["available"])),
                        price=slice_obj.price,
                    )

                    if dark_order_id:
                        slice_obj.data = {"dark_pool_order": dark_order_id}
                        logger.info(f"[SmartRouter] 暗池订单: {dark_order_id}")

    def estimate_execution_cost(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        price: float,
        adv: float,
        volatility: float,
    ) -> Dict[str, float]:
        """估算执行成本"""
        # 冲击成本
        impact = self.impact_model.estimate_impact(code, quantity, adv, volatility)

        # 佣金
        commission = quantity * price * 0.0003

        # 滑点 (预估)
        slippage = impact["impact"] * price * quantity

        return {
            "impact_cost": slippage,
            "commission": commission,
            "total_cost": slippage + commission,
            "impact_bps": impact["impact"] * 10000,
            "confidence": impact["confidence"],
        }

    def get_stats(self) -> Dict:
        """获取统计"""
        return self._stats.copy()


# ============ 便捷函数 ============

def create_smart_router() -> SmartRouter:
    """创建智能路由器"""
    return SmartRouter()


def route_order(
    code: str,
    side: str,
    quantity: int,
    price: float,
    algorithm: str = "vwap",
) -> ExecutionPlan:
    """路由订单"""
    router = SmartRouter()
    return router.route_order(
        code=code,
        side=OrderSide(side),
        quantity=quantity,
        price=price,
        algorithm=ExecutionAlgorithm(algorithm),
    )


def estimate_impact(
    code: str,
    quantity: int,
    adv: float,
    volatility: float,
) -> Dict[str, float]:
    """估算冲击成本"""
    model = ImpactModel()
    return model.estimate_impact(code, quantity, adv, volatility)
