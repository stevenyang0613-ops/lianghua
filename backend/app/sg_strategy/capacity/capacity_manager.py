"""松岗量化可转债策略 V3.0 策略容量管理模块

功能:
- 容量评估模型
- 规模限制预警
- 容量扩展策略
- 容量衰减监控
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple, Callable
from enum import Enum
import logging
import math
import numpy as np
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class CapacityStatus(str, Enum):
    """容量状态"""
    AVAILABLE = "available"       # 容量充足
    MODERATE = "moderate"         # 容量适中
    CONSTRAINED = "constrained"   # 容量受限
    EXHAUSTED = "exhausted"       # 容量耗尽


class WarningLevel(str, Enum):
    """预警级别"""
    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"
    CRITICAL = "critical"


class CapacityFactor(str, Enum):
    """容量因子"""
    LIQUIDITY = "liquidity"       # 流动性
    MARKET_IMPACT = "impact"      # 市场冲击
    CONCENTRATION = "concentration"  # 集中度
    VOLATILITY = "volatility"     # 波动率
    CORRELATION = "correlation"   # 相关性


# ============ 数据模型 ============

@dataclass
class CapacityMetrics:
    """容量指标"""
    total_aum: float              # 总管理规模
    investable_capacity: float    # 可投资容量
    used_capacity: float          # 已用容量
    available_capacity: float     # 可用容量
    capacity_utilization: float   # 容量利用率
    effective_capacity: float     # 有效容量

    def to_dict(self) -> dict:
        return {
            "total_aum": round(self.total_aum, 2),
            "investable_capacity": round(self.investable_capacity, 2),
            "used_capacity": round(self.used_capacity, 2),
            "available_capacity": round(self.available_capacity, 2),
            "capacity_utilization": round(self.capacity_utilization, 4),
            "effective_capacity": round(self.effective_capacity, 2),
        }


@dataclass
class CapacityConstraint:
    """容量约束"""
    constraint_id: str
    factor: CapacityFactor
    description: str
    current_value: float
    limit_value: float
    utilization: float
    status: CapacityStatus
    warning_level: WarningLevel

    def to_dict(self) -> dict:
        return {
            "constraint_id": self.constraint_id,
            "factor": self.factor.value,
            "description": self.description,
            "current_value": round(self.current_value, 4),
            "limit_value": round(self.limit_value, 4),
            "utilization": round(self.utilization, 4),
            "status": self.status.value,
            "warning_level": self.warning_level.value,
        }


@dataclass
class CapacityWarning:
    """容量预警"""
    warning_id: str
    level: WarningLevel
    factor: CapacityFactor
    message: str
    current_value: float
    threshold: float
    timestamp: datetime
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "warning_id": self.warning_id,
            "level": self.level.value,
            "factor": self.factor.value,
            "message": self.message,
            "current_value": round(self.current_value, 4),
            "threshold": round(self.threshold, 4),
            "timestamp": self.timestamp.isoformat(),
            "recommendations": self.recommendations,
        }


@dataclass
class CapacityReport:
    """容量报告"""
    report_id: str
    timestamp: datetime
    metrics: CapacityMetrics
    constraints: List[CapacityConstraint]
    warnings: List[CapacityWarning]
    status: CapacityStatus
    recommendations: List[str]

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp.isoformat(),
            "metrics": self.metrics.to_dict(),
            "constraints": [c.to_dict() for c in self.constraints],
            "warnings": [w.to_dict() for w in self.warnings],
            "status": self.status.value,
            "recommendations": self.recommendations,
        }


# ============ 容量评估模型 ============

class CapacityEstimator:
    """容量评估模型"""

    def __init__(self):
        # 容量参数
        self._params = {
            "max_participation_rate": 0.1,    # 最大参与率
            "max_impact_bps": 10,             # 最大冲击成本(bps)
            "max_concentration": 0.15,        # 最大集中度
            "min_liquidity_days": 5,          # 最小流动性天数
        }

        # 历史数据
        self._adv_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=60))
        self._volume_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=252))

    def estimate_capacity(
        self,
        code: str,
        adv: float,           # 平均日成交量
        price: float,
        volatility: float,
        market_cap: float = None,
    ) -> float:
        """估算单个标的容量"""
        # 基于流动性的容量
        liquidity_capacity = adv * self._params["max_participation_rate"] * self._params["min_liquidity_days"] * price

        # 基于冲击成本的容量
        # 使用简化的冲击模型
        max_impact_value = self._params["max_impact_bps"] / 10000

        # 假设冲击成本 = participation * volatility * coefficient
        # 反推可交易量
        impact_capacity = adv * price * max_impact_value / (volatility * 0.5) if volatility > 0 else liquidity_capacity

        # 基于市值的容量 (如果有)
        if market_cap:
            market_cap_capacity = market_cap * 0.01  # 不超过市值1%
        else:
            market_cap_capacity = float('inf')

        # 取最小值
        capacity = min(liquidity_capacity, impact_capacity, market_cap_capacity)

        return capacity

    def estimate_portfolio_capacity(
        self,
        positions: Dict[str, Dict],  # code -> {adv, price, volatility, ...}
        total_aum: float,
    ) -> CapacityMetrics:
        """估算组合容量"""
        total_capacity = 0

        for code, data in positions.items():
            capacity = self.estimate_capacity(
                code=code,
                adv=data.get("adv", 0),
                price=data.get("price", 0),
                volatility=data.get("volatility", 0.02),
                market_cap=data.get("market_cap"),
            )
            total_capacity += capacity

        # 有效容量 (考虑分散化)
        n_positions = len(positions)
        diversification_factor = min(1.0, math.sqrt(n_positions) / 10)

        effective_capacity = total_capacity * diversification_factor

        # 已用容量
        used_capacity = sum(
            data.get("market_value", 0)
            for data in positions.values()
        )

        available_capacity = max(0, effective_capacity - used_capacity)
        utilization = used_capacity / effective_capacity if effective_capacity > 0 else 0

        return CapacityMetrics(
            total_aum=total_aum,
            investable_capacity=total_capacity,
            used_capacity=used_capacity,
            available_capacity=available_capacity,
            capacity_utilization=utilization,
            effective_capacity=effective_capacity,
        )


# ============ 约束监控器 ============

class ConstraintMonitor:
    """约束监控器"""

    def __init__(self):
        self._constraints: Dict[str, CapacityConstraint] = {}
        self._thresholds = {
            CapacityFactor.LIQUIDITY: {"warning": 0.6, "danger": 0.8, "critical": 0.95},
            CapacityFactor.MARKET_IMPACT: {"warning": 5, "danger": 10, "critical": 20},
            CapacityFactor.CONCENTRATION: {"warning": 0.1, "danger": 0.15, "critical": 0.2},
            CapacityFactor.VOLATILITY: {"warning": 0.02, "danger": 0.03, "critical": 0.05},
        }

    def add_constraint(self, constraint: CapacityConstraint):
        """添加约束"""
        self._constraints[constraint.constraint_id] = constraint

    def check_liquidity_constraint(
        self,
        position_value: float,
        adv: float,
        price: float,
        code: str,
    ) -> CapacityConstraint:
        """检查流动性约束"""
        # 参与率
        daily_volume = adv * price
        participation = position_value / daily_volume if daily_volume > 0 else 0

        limit = self._params["max_participation_rate"] if hasattr(self, '_params') else 0.1
        utilization = participation / limit if limit > 0 else 0

        # 确定状态
        status, warning = self._determine_status(CapacityFactor.LIQUIDITY, utilization)

        constraint = CapacityConstraint(
            constraint_id=f"liquidity_{code}",
            factor=CapacityFactor.LIQUIDITY,
            description=f"{code}流动性约束",
            current_value=participation,
            limit_value=limit,
            utilization=utilization,
            status=status,
            warning_level=warning,
        )

        self._constraints[constraint.constraint_id] = constraint

        return constraint

    def check_impact_constraint(
        self,
        position_value: float,
        adv: float,
        price: float,
        volatility: float,
        code: str,
    ) -> CapacityConstraint:
        """检查冲击成本约束"""
        # 估算冲击成本
        participation = position_value / (adv * price) if adv * price > 0 else 0
        estimated_impact_bps = participation * volatility * 10000 * 10  # 简化模型

        limit = 10  # bps
        utilization = estimated_impact_bps / limit

        status, warning = self._determine_status(CapacityFactor.MARKET_IMPACT, utilization)

        constraint = CapacityConstraint(
            constraint_id=f"impact_{code}",
            factor=CapacityFactor.MARKET_IMPACT,
            description=f"{code}冲击成本约束",
            current_value=estimated_impact_bps,
            limit_value=limit,
            utilization=utilization,
            status=status,
            warning_level=warning,
        )

        self._constraints[constraint.constraint_id] = constraint

        return constraint

    def check_concentration_constraint(
        self,
        position_value: float,
        total_value: float,
        code: str,
    ) -> CapacityConstraint:
        """检查集中度约束"""
        concentration = position_value / total_value if total_value > 0 else 0
        limit = 0.15  # 15%
        utilization = concentration / limit

        status, warning = self._determine_status(CapacityFactor.CONCENTRATION, utilization)

        constraint = CapacityConstraint(
            constraint_id=f"concentration_{code}",
            factor=CapacityFactor.CONCENTRATION,
            description=f"{code}集中度约束",
            current_value=concentration,
            limit_value=limit,
            utilization=utilization,
            status=status,
            warning_level=warning,
        )

        self._constraints[constraint.constraint_id] = constraint

        return constraint

    def _determine_status(self, factor: CapacityFactor, utilization: float) -> Tuple[CapacityStatus, WarningLevel]:
        """确定状态"""
        thresholds = self._thresholds.get(factor, {})

        warning_threshold = thresholds.get("warning", 0.7)
        danger_threshold = thresholds.get("danger", 0.85)
        critical_threshold = thresholds.get("critical", 0.95)

        if utilization >= critical_threshold:
            return CapacityStatus.EXHAUSTED, WarningLevel.CRITICAL
        elif utilization >= danger_threshold:
            return CapacityStatus.CONSTRAINED, WarningLevel.DANGER
        elif utilization >= warning_threshold:
            return CapacityStatus.MODERATE, WarningLevel.WARNING
        else:
            return CapacityStatus.AVAILABLE, WarningLevel.INFO

    def get_all_constraints(self) -> List[CapacityConstraint]:
        """获取所有约束"""
        return list(self._constraints.values())

    def get_violations(self) -> List[CapacityConstraint]:
        """获取违规约束"""
        return [c for c in self._constraints.values() if c.status in [CapacityStatus.CONSTRAINED, CapacityStatus.EXHAUSTED]]


# ============ 预警管理器 ============

class CapacityWarningManager:
    """容量预警管理器"""

    def __init__(self):
        self._warnings: List[CapacityWarning] = []
        self._alert_handlers: List[Callable] = []
        self._warning_history: deque = deque(maxlen=1000)

    def generate_warning(
        self,
        constraint: CapacityConstraint,
    ) -> Optional[CapacityWarning]:
        """生成预警"""
        if constraint.warning_level == WarningLevel.INFO:
            return None

        warning_id = f"warn_{int(datetime.now().timestamp() * 1000)}"

        # 生成建议
        recommendations = self._generate_recommendations(constraint)

        warning = CapacityWarning(
            warning_id=warning_id,
            level=constraint.warning_level,
            factor=constraint.factor,
            message=f"{constraint.description}: 利用率{constraint.utilization:.1%}",
            current_value=constraint.current_value,
            threshold=constraint.limit_value,
            timestamp=datetime.now(),
            recommendations=recommendations,
        )

        self._warnings.append(warning)
        self._warning_history.append(warning)

        # 触发处理器
        for handler in self._alert_handlers:
            try:
                handler(warning)
            except Exception as e:
                logger.error(f"[CapacityWarningManager] 处理器执行失败: {e}")

        return warning

    def _generate_recommendations(self, constraint: CapacityConstraint) -> List[str]:
        """生成建议"""
        recommendations = []

        if constraint.factor == CapacityFactor.LIQUIDITY:
            recommendations.extend([
                "降低持仓规模以减少流动性风险",
                "分批执行交易以降低冲击",
                "寻找替代标的分散流动性需求",
            ])

        elif constraint.factor == CapacityFactor.MARKET_IMPACT:
            recommendations.extend([
                "使用TWAP/VWAP算法执行",
                "延长交易时间窗口",
                "考虑使用暗池或大宗交易",
            ])

        elif constraint.factor == CapacityFactor.CONCENTRATION:
            recommendations.extend([
                "分散投资降低集中度",
                "设置单标的权重上限",
                "定期再平衡组合",
            ])

        elif constraint.factor == CapacityFactor.VOLATILITY:
            recommendations.extend([
                "增加对冲保护",
                "降低仓位规模",
                "等待波动率下降",
            ])

        return recommendations

    def get_active_warnings(self) -> List[CapacityWarning]:
        """获取活跃预警"""
        # 最近24小时的预警
        cutoff = datetime.now() - timedelta(hours=24)
        return [w for w in self._warnings if w.timestamp > cutoff]

    def register_handler(self, handler: Callable):
        """注册处理器"""
        self._alert_handlers.append(handler)


# ============ 容量衰减监控器 ============

class CapacityDecayMonitor:
    """容量衰减监控器"""

    def __init__(self):
        self._capacity_history: deque = deque(maxlen=252)
        self._decay_rate: float = 0

    def record_capacity(self, capacity: float, timestamp: datetime = None):
        """记录容量"""
        self._capacity_history.append({
            "capacity": capacity,
            "timestamp": timestamp or datetime.now(),
        })

    def calculate_decay_rate(self, window: int = 30) -> float:
        """计算衰减率"""
        if len(self._capacity_history) < window:
            return 0

        recent = list(self._capacity_history)[-window:]
        capacities = [r["capacity"] for r in recent]

        # 线性回归计算衰减率
        x = np.arange(len(capacities))
        y = np.array(capacities)

        slope = np.polyfit(x, y, 1)[0]
        mean_capacity = np.mean(y)

        # 标准化衰减率
        decay_rate = -slope / mean_capacity if mean_capacity > 0 else 0

        self._decay_rate = decay_rate

        return decay_rate

    def predict_future_capacity(self, days: int = 30) -> float:
        """预测未来容量"""
        if len(self._capacity_history) < 10:
            return 0

        current_capacity = self._capacity_history[-1]["capacity"]

        # 简单线性预测
        future_capacity = current_capacity * (1 - self._decay_rate * days)

        return max(0, future_capacity)

    def get_decay_trend(self) -> str:
        """获取衰减趋势"""
        if self._decay_rate < 0.001:
            return "stable"
        elif self._decay_rate < 0.01:
            return "slow_decay"
        elif self._decay_rate < 0.03:
            return "moderate_decay"
        else:
            return "rapid_decay"


# ============ 容量管理服务 ============

class CapacityManagementService:
    """容量管理服务"""

    def __init__(self, total_aum: float = 100000000):
        self.total_aum = total_aum
        self.estimator = CapacityEstimator()
        self.monitor = ConstraintMonitor()
        self.warning_manager = CapacityWarningManager()
        self.decay_monitor = CapacityDecayMonitor()

        self._positions: Dict[str, Dict] = {}

    def update_position(self, code: str, position_data: Dict):
        """更新持仓"""
        self._positions[code] = position_data

    def assess_capacity(self) -> CapacityReport:
        """评估容量"""
        # 计算容量指标
        metrics = self.estimator.estimate_portfolio_capacity(
            self._positions, self.total_aum
        )

        # 检查约束
        constraints = []
        warnings = []

        total_value = sum(p.get("market_value", 0) for p in self._positions.values())

        for code, data in self._positions.items():
            # 流动性约束
            liquidity_constraint = self.monitor.check_liquidity_constraint(
                position_value=data.get("market_value", 0),
                adv=data.get("adv", 0),
                price=data.get("price", 0),
                code=code,
            )
            constraints.append(liquidity_constraint)

            # 冲击成本约束
            impact_constraint = self.monitor.check_impact_constraint(
                position_value=data.get("market_value", 0),
                adv=data.get("adv", 0),
                price=data.get("price", 0),
                volatility=data.get("volatility", 0.02),
                code=code,
            )
            constraints.append(impact_constraint)

            # 集中度约束
            concentration_constraint = self.monitor.check_concentration_constraint(
                position_value=data.get("market_value", 0),
                total_value=total_value,
                code=code,
            )
            constraints.append(concentration_constraint)

            # 生成预警
            for constraint in [liquidity_constraint, impact_constraint, concentration_constraint]:
                warning = self.warning_manager.generate_warning(constraint)
                if warning:
                    warnings.append(warning)

        # 记录容量历史
        self.decay_monitor.record_capacity(metrics.effective_capacity)

        # 确定整体状态
        status = self._determine_overall_status(constraints)

        # 生成建议
        recommendations = self._generate_recommendations(metrics, constraints)

        report = CapacityReport(
            report_id=f"capacity_{int(datetime.now().timestamp() * 1000)}",
            timestamp=datetime.now(),
            metrics=metrics,
            constraints=constraints,
            warnings=warnings,
            status=status,
            recommendations=recommendations,
        )

        return report

    def _determine_overall_status(self, constraints: List[CapacityConstraint]) -> CapacityStatus:
        """确定整体状态"""
        if any(c.status == CapacityStatus.EXHAUSTED for c in constraints):
            return CapacityStatus.EXHAUSTED
        elif any(c.status == CapacityStatus.CONSTRAINED for c in constraints):
            return CapacityStatus.CONSTRAINED
        elif any(c.status == CapacityStatus.MODERATE for c in constraints):
            return CapacityStatus.MODERATE
        else:
            return CapacityStatus.AVAILABLE

    def _generate_recommendations(self, metrics: CapacityMetrics, constraints: List[CapacityConstraint]) -> List[str]:
        """生成建议"""
        recommendations = []

        if metrics.capacity_utilization > 0.8:
            recommendations.append("容量利用率较高, 建议控制新仓位规模")

        if metrics.available_capacity < metrics.total_aum * 0.1:
            recommendations.append("可用容量不足, 考虑增加流动性或降低规模")

        # 按约束类型统计
        factor_counts = defaultdict(int)
        for c in constraints:
            if c.status in [CapacityStatus.CONSTRAINED, CapacityStatus.EXHAUSTED]:
                factor_counts[c.factor] += 1

        for factor, count in factor_counts.items():
            if factor == CapacityFactor.LIQUIDITY:
                recommendations.append(f"{count}个标的存在流动性约束")
            elif factor == CapacityFactor.MARKET_IMPACT:
                recommendations.append(f"{count}个标的冲击成本较高")
            elif factor == CapacityFactor.CONCENTRATION:
                recommendations.append(f"{count}个标的集中度过高")

        return recommendations

    def can_add_position(
        self,
        code: str,
        value: float,
    ) -> Tuple[bool, str]:
        """判断是否可以新增仓位"""
        metrics = self.estimator.estimate_portfolio_capacity(
            self._positions, self.total_aum
        )

        # 检查可用容量
        if value > metrics.available_capacity:
            return False, f"容量不足: 需要{value:.0f}, 可用{metrics.available_capacity:.0f}"

        # 检查新增后的集中度
        total_value = sum(p.get("market_value", 0) for p in self._positions.values()) + value
        new_concentration = value / total_value if total_value > 0 else 0

        if new_concentration > 0.15:
            return False, f"集中度过高: {new_concentration:.1%}"

        return True, "容量充足"

    def get_capacity_status(self) -> Dict:
        """获取容量状态"""
        report = self.assess_capacity()

        return {
            "status": report.status.value,
            "utilization": round(report.metrics.capacity_utilization, 4),
            "available": round(report.metrics.available_capacity, 2),
            "warnings": len(report.warnings),
            "decay_rate": round(self.decay_monitor.calculate_decay_rate(), 6),
            "decay_trend": self.decay_monitor.get_decay_trend(),
        }


# ============ 便捷函数 ============

def create_capacity_service(aum: float = 100000000) -> CapacityManagementService:
    """创建容量管理服务"""
    return CapacityManagementService(aum)


def estimate_capacity(
    adv: float,
    price: float,
    volatility: float,
) -> float:
    """估算容量"""
    estimator = CapacityEstimator()
    return estimator.estimate_capacity("default", adv, price, volatility)
