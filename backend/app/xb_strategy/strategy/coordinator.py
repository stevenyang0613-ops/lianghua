"""西部量化可转债策略 V3.0 多策略协同框架模块

功能:
- 策略信号融合
- 资金分配优化
- 冲突解决机制
- 策略绩效归因
- 动态权重调整
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple, Callable, Set
from enum import Enum
import logging
import numpy as np
import pandas as pd
from collections import deque, defaultdict
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class SignalType(str, Enum):
    """信号类型"""
    LONG = "long"             # 做多
    SHORT = "short"           # 做空
    NEUTRAL = "neutral"       # 中性
    CLOSE = "close"           # 平仓


class SignalStrength(str, Enum):
    """信号强度"""
    STRONG = "strong"         # 强
    MODERATE = "moderate"     # 中
    WEAK = "weak"             # 弱


class ConflictResolution(str, Enum):
    """冲突解决方式"""
    VOTE = "vote"             # 投票
    WEIGHTED = "weighted"     # 加权
    PRIORITY = "priority"     # 优先级
    CONSENSUS = "consensus"   # 共识
    META = "meta"             # 元策略


class AllocationMethod(str, Enum):
    """资金分配方法"""
    EQUAL = "equal"           # 等权重
    SHARPE = "sharpe"         # 夏普比例
    RISK_PARITY = "risk_parity"  # 风险平价
    MIN_VARIANCE = "min_variance"  # 最小方差
    KELLY = "kelly"           # 凯利公式
    ADAPTIVE = "adaptive"     # 自适应


class StrategyStatus(str, Enum):
    """策略状态"""
    ACTIVE = "active"         # 活跃
    PAUSED = "paused"         # 暂停
    STOPPED = "stopped"       # 停止
    ERROR = "error"           # 错误


# ============ 数据模型 ============

@dataclass
class Signal:
    """信号"""
    signal_id: str
    strategy_id: str
    code: str
    signal_type: SignalType
    strength: SignalStrength
    confidence: float  # 0-1
    price: float
    timestamp: datetime
    metadata: Dict = field(default_factory=dict)

    @property
    def score(self) -> float:
        """信号得分"""
        type_score = {
            SignalType.LONG: 1.0,
            SignalType.SHORT: -1.0,
            SignalType.NEUTRAL: 0.0,
            SignalType.CLOSE: 0.0,
        }

        strength_mult = {
            SignalStrength.STRONG: 1.0,
            SignalStrength.MODERATE: 0.6,
            SignalStrength.WEAK: 0.3,
        }

        return type_score[self.signal_type] * strength_mult[self.strength] * self.confidence

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "strategy_id": self.strategy_id,
            "code": self.code,
            "signal_type": self.signal_type.value,
            "strength": self.strength.value,
            "confidence": round(self.confidence, 4),
            "score": round(self.score, 4),
            "price": round(self.price, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class FusedSignal:
    """融合信号"""
    code: str
    final_score: float
    signal_type: SignalType
    contributing_strategies: List[str]
    signal_details: List[Signal]
    confidence: float
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "final_score": round(self.final_score, 4),
            "signal_type": self.signal_type.value,
            "contributing_strategies": self.contributing_strategies,
            "strategy_count": len(self.contributing_strategies),
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Strategy:
    """策略"""
    strategy_id: str
    name: str
    description: str
    status: StrategyStatus = StrategyStatus.ACTIVE
    weight: float = 1.0
    priority: int = 1

    # 绩效指标
    total_return: float = 0
    sharpe_ratio: float = 0
    max_drawdown: float = 0
    win_rate: float = 0
    total_trades: int = 0

    # 风险控制
    max_position: float = 0.1
    max_drawdown_limit: float = 0.1

    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "weight": round(self.weight, 4),
            "priority": self.priority,
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
        }


@dataclass
class StrategyAllocation:
    """策略资金分配"""
    strategy_id: str
    allocated_capital: float
    weight: float
    max_position: float
    current_positions: Dict[str, float] = field(default_factory=dict)
    current_exposure: float = 0

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "allocated_capital": round(self.allocated_capital, 2),
            "weight": round(self.weight, 4),
            "max_position": round(self.max_position, 4),
            "current_exposure": round(self.current_exposure, 4),
            "position_count": len(self.current_positions),
        }


@dataclass
class Conflict:
    """冲突"""
    conflict_id: str
    codes: List[str]
    strategies: List[str]
    signals: List[Signal]
    resolution: ConflictResolution
    resolved_signal: FusedSignal
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "conflict_id": self.conflict_id,
            "codes": self.codes,
            "strategies": self.strategies,
            "signal_count": len(self.signals),
            "resolution": self.resolution.value,
            "resolved_score": round(self.resolved_signal.final_score, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CoordinatorConfig:
    """协调器配置"""
    conflict_resolution: ConflictResolution = ConflictResolution.WEIGHTED
    allocation_method: AllocationMethod = AllocationMethod.ADAPTIVE
    min_signal_confidence: float = 0.3
    signal_fusion_threshold: float = 0.5
    max_strategy_count: int = 10
    rebalance_frequency: int = 1  # 天
    enable_auto_adjustment: bool = True


# ============ 信号融合器 ============

class SignalFusion:
    """信号融合器"""

    def __init__(self, config: CoordinatorConfig = None):
        self.config = config or CoordinatorConfig()
        self._signal_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

    def fuse_signals(
        self,
        signals: List[Signal],
        strategy_weights: Dict[str, float],
    ) -> FusedSignal:
        """融合信号"""
        if not signals:
            return None

        # 按代码分组
        by_code: Dict[str, List[Signal]] = defaultdict(list)
        for signal in signals:
            by_code[signal.code].append(signal)

        fused_signals = []

        for code, code_signals in by_code.items():
            # 过滤低置信度信号
            valid_signals = [
                s for s in code_signals
                if s.confidence >= self.config.min_signal_confidence
            ]

            if not valid_signals:
                continue

            # 计算加权得分
            weighted_sum = 0
            weight_total = 0
            strategies = []

            for signal in valid_signals:
                strategy_weight = strategy_weights.get(signal.strategy_id, 1.0)
                weight = strategy_weight * signal.confidence

                weighted_sum += signal.score * weight
                weight_total += weight

                if signal.strategy_id not in strategies:
                    strategies.append(signal.strategy_id)

            final_score = weighted_sum / weight_total if weight_total > 0 else 0

            # 确定信号类型
            if final_score >= self.config.signal_fusion_threshold:
                signal_type = SignalType.LONG
            elif final_score <= -self.config.signal_fusion_threshold:
                signal_type = SignalType.SHORT
            else:
                signal_type = SignalType.NEUTRAL

            # 计算融合置信度
            confidence = min(1.0, abs(final_score) * len(valid_signals) / len(strategies))

            fused = FusedSignal(
                code=code,
                final_score=final_score,
                signal_type=signal_type,
                contributing_strategies=strategies,
                signal_details=valid_signals,
                confidence=confidence,
                timestamp=datetime.now(),
            )

            fused_signals.append(fused)

            # 记录历史
            self._signal_history[code].append(fused)

        # 返回最强的信号
        if fused_signals:
            return max(fused_signals, key=lambda x: abs(x.final_score))

        return None

    def get_signal_history(
        self,
        code: str,
        limit: int = 10,
    ) -> List[FusedSignal]:
        """获取信号历史"""
        history = list(self._signal_history.get(code, []))
        return history[-limit:]


# ============ 冲突解决器 ============

class ConflictResolver:
    """冲突解决器"""

    def __init__(self, config: CoordinatorConfig = None):
        self.config = config or CoordinatorConfig()
        self._conflicts: List[Conflict] = []
        self._lock = threading.Lock()

    def detect_conflicts(
        self,
        signals: List[Signal],
    ) -> List[List[Signal]]:
        """检测冲突"""
        conflicts = []

        # 按代码分组
        by_code: Dict[str, List[Signal]] = defaultdict(list)
        for signal in signals:
            by_code[signal.code].append(signal)

        # 检测冲突
        for code, code_signals in by_code.items():
            if len(code_signals) < 2:
                continue

            # 检查方向冲突
            long_signals = [s for s in code_signals if s.signal_type == SignalType.LONG]
            short_signals = [s for s in code_signals if s.signal_type == SignalType.SHORT]

            if long_signals and short_signals:
                conflicts.append(code_signals)

        return conflicts

    def resolve_conflict(
        self,
        conflicting_signals: List[Signal],
        strategy_weights: Dict[str, float],
        strategy_priorities: Dict[str, int],
    ) -> Conflict:
        """解决冲突"""
        resolution = self.config.conflict_resolution

        if resolution == ConflictResolution.VOTE:
            resolved_signal = self._resolve_by_vote(conflicting_signals)
        elif resolution == ConflictResolution.WEIGHTED:
            resolved_signal = self._resolve_by_weight(conflicting_signals, strategy_weights)
        elif resolution == ConflictResolution.PRIORITY:
            resolved_signal = self._resolve_by_priority(conflicting_signals, strategy_priorities)
        elif resolution == ConflictResolution.CONSENSUS:
            resolved_signal = self._resolve_by_consensus(conflicting_signals)
        else:
            resolved_signal = self._resolve_by_meta(conflicting_signals, strategy_weights)

        # 创建冲突记录
        conflict = Conflict(
            conflict_id=f"conflict_{int(datetime.now().timestamp() * 1000)}",
            codes=list(set(s.code for s in conflicting_signals)),
            strategies=list(set(s.strategy_id for s in conflicting_signals)),
            signals=conflicting_signals,
            resolution=resolution,
            resolved_signal=resolved_signal,
            timestamp=datetime.now(),
        )

        with self._lock:
            self._conflicts.append(conflict)

        return conflict

    def _resolve_by_vote(self, signals: List[Signal]) -> FusedSignal:
        """投票解决"""
        votes = defaultdict(float)

        for signal in signals:
            votes[signal.signal_type] += signal.confidence

        winner = max(votes.keys(), key=lambda k: votes[k])

        avg_score = np.mean([s.score for s in signals])

        return FusedSignal(
            code=signals[0].code,
            final_score=avg_score,
            signal_type=winner,
            contributing_strategies=list(set(s.strategy_id for s in signals)),
            signal_details=signals,
            confidence=votes[winner] / len(signals),
            timestamp=datetime.now(),
        )

    def _resolve_by_weight(
        self,
        signals: List[Signal],
        weights: Dict[str, float],
    ) -> FusedSignal:
        """加权解决"""
        weighted_score = 0
        total_weight = 0

        for signal in signals:
            w = weights.get(signal.strategy_id, 1.0)
            weighted_score += signal.score * w
            total_weight += w

        final_score = weighted_score / total_weight if total_weight > 0 else 0

        if final_score > 0:
            signal_type = SignalType.LONG
        elif final_score < 0:
            signal_type = SignalType.SHORT
        else:
            signal_type = SignalType.NEUTRAL

        return FusedSignal(
            code=signals[0].code,
            final_score=final_score,
            signal_type=signal_type,
            contributing_strategies=list(set(s.strategy_id for s in signals)),
            signal_details=signals,
            confidence=min(1.0, abs(final_score)),
            timestamp=datetime.now(),
        )

    def _resolve_by_priority(
        self,
        signals: List[Signal],
        priorities: Dict[str, int],
    ) -> FusedSignal:
        """优先级解决"""
        # 按优先级排序
        sorted_signals = sorted(
            signals,
            key=lambda s: priorities.get(s.strategy_id, 1),
            reverse=True,
        )

        winner = sorted_signals[0]

        return FusedSignal(
            code=winner.code,
            final_score=winner.score,
            signal_type=winner.signal_type,
            contributing_strategies=[winner.strategy_id],
            signal_details=[winner],
            confidence=winner.confidence,
            timestamp=datetime.now(),
        )

    def _resolve_by_consensus(self, signals: List[Signal]) -> FusedSignal:
        """共识解决"""
        # 检查是否有共识
        types = set(s.signal_type for s in signals)

        if len(types) == 1 and SignalType.NEUTRAL not in types:
            # 完全共识
            avg_score = np.mean([s.score for s in signals])
            signal_type = list(types)[0]
            confidence = 0.9
        else:
            # 无共识，返回中性
            avg_score = 0
            signal_type = SignalType.NEUTRAL
            confidence = 0.3

        return FusedSignal(
            code=signals[0].code,
            final_score=avg_score,
            signal_type=signal_type,
            contributing_strategies=list(set(s.strategy_id for s in signals)),
            signal_details=signals,
            confidence=confidence,
            timestamp=datetime.now(),
        )

    def _resolve_by_meta(
        self,
        signals: List[Signal],
        weights: Dict[str, float],
    ) -> FusedSignal:
        """元策略解决"""
        # 综合多种方法
        vote_result = self._resolve_by_vote(signals)
        weight_result = self._resolve_by_weight(signals, weights)

        # 元策略综合
        final_score = (vote_result.final_score + weight_result.final_score) / 2

        if final_score > 0:
            signal_type = SignalType.LONG
        elif final_score < 0:
            signal_type = SignalType.SHORT
        else:
            signal_type = SignalType.NEUTRAL

        return FusedSignal(
            code=signals[0].code,
            final_score=final_score,
            signal_type=signal_type,
            contributing_strategies=list(set(s.strategy_id for s in signals)),
            signal_details=signals,
            confidence=(vote_result.confidence + weight_result.confidence) / 2,
            timestamp=datetime.now(),
        )

    def get_conflict_history(self, limit: int = 10) -> List[Conflict]:
        """获取冲突历史"""
        with self._lock:
            return self._conflicts[-limit:]


# ============ 资金分配器 ============

class CapitalAllocator:
    """资金分配器"""

    def __init__(self, config: CoordinatorConfig = None):
        self.config = config or CoordinatorConfig()
        self._allocations: Dict[str, StrategyAllocation] = {}

    def allocate(
        self,
        total_capital: float,
        strategies: List[Strategy],
        returns: Dict[str, List[float]] = None,
        method: AllocationMethod = None,
    ) -> Dict[str, StrategyAllocation]:
        """分配资金"""
        method = method or self.config.allocation_method

        if method == AllocationMethod.EQUAL:
            weights = self._equal_allocation(strategies)
        elif method == AllocationMethod.SHARPE:
            weights = self._sharpe_allocation(strategies)
        elif method == AllocationMethod.RISK_PARITY:
            weights = self._risk_parity_allocation(strategies, returns)
        elif method == AllocationMethod.MIN_VARIANCE:
            weights = self._min_variance_allocation(strategies, returns)
        elif method == AllocationMethod.KELLY:
            weights = self._kelly_allocation(strategies, returns)
        else:
            weights = self._adaptive_allocation(strategies, returns)

        # 创建分配
        allocations = {}
        for strategy in strategies:
            allocation = StrategyAllocation(
                strategy_id=strategy.strategy_id,
                allocated_capital=total_capital * weights[strategy.strategy_id],
                weight=weights[strategy.strategy_id],
                max_position=strategy.max_position,
            )
            allocations[strategy.strategy_id] = allocation
            self._allocations[strategy.strategy_id] = allocation

        return allocations

    def _equal_allocation(self, strategies: List[Strategy]) -> Dict[str, float]:
        """等权重分配"""
        n = len(strategies)
        return {s.strategy_id: 1.0 / n for s in strategies}

    def _sharpe_allocation(self, strategies: List[Strategy]) -> Dict[str, float]:
        """夏普比率分配"""
        sharpes = {s.strategy_id: max(0.01, s.sharpe_ratio) for s in strategies}
        total = sum(sharpes.values())

        return {sid: s / total for sid, s in sharpes.items()}

    def _risk_parity_allocation(
        self,
        strategies: List[Strategy],
        returns: Dict[str, List[float]],
    ) -> Dict[str, float]:
        """风险平价分配"""
        if not returns:
            return self._equal_allocation(strategies)

        # 计算波动率
        volatilities = {}
        for strategy in strategies:
            rets = returns.get(strategy.strategy_id, [])
            if rets:
                vol = np.std(rets)
                volatilities[strategy.strategy_id] = max(0.01, vol)
            else:
                volatilities[strategy.strategy_id] = 0.01

        # 反波动率权重
        inv_vols = {sid: 1.0 / v for sid, v in volatilities.items()}
        total = sum(inv_vols.values())

        return {sid: v / total for sid, v in inv_vols.items()}

    def _min_variance_allocation(
        self,
        strategies: List[Strategy],
        returns: Dict[str, List[float]],
    ) -> Dict[str, float]:
        """最小方差分配"""
        if not returns:
            return self._equal_allocation(strategies)

        # 简化处理：等权重
        return self._equal_allocation(strategies)

    def _kelly_allocation(
        self,
        strategies: List[Strategy],
        returns: Dict[str, List[float]],
    ) -> Dict[str, float]:
        """凯利公式分配"""
        if not returns:
            return self._equal_allocation(strategies)

        kelly_weights = {}

        for strategy in strategies:
            rets = returns.get(strategy.strategy_id, [])
            if len(rets) < 10:
                kelly_weights[strategy.strategy_id] = 0.1
                continue

            mean_ret = np.mean(rets)
            std_ret = np.std(rets)

            if std_ret > 0:
                kelly = mean_ret / (std_ret ** 2)
                kelly = max(0.01, min(0.25, kelly))  # 限制范围
            else:
                kelly = 0.1

            kelly_weights[strategy.strategy_id] = kelly

        total = sum(kelly_weights.values())
        return {sid: w / total for sid, w in kelly_weights.items()}

    def _adaptive_allocation(
        self,
        strategies: List[Strategy],
        returns: Dict[str, List[float]],
    ) -> Dict[str, float]:
        """自适应分配"""
        # 结合多种方法
        equal = self._equal_allocation(strategies)
        sharpe = self._sharpe_allocation(strategies)
        risk_parity = self._risk_parity_allocation(strategies, returns)

        # 加权组合
        weights = {}
        for strategy in strategies:
            sid = strategy.strategy_id
            weights[sid] = (
                equal[sid] * 0.2 +
                sharpe[sid] * 0.4 +
                risk_parity[sid] * 0.4
            )

        # 归一化
        total = sum(weights.values())
        return {sid: w / total for sid, w in weights.items()}

    def get_allocation(self, strategy_id: str) -> Optional[StrategyAllocation]:
        """获取分配"""
        return self._allocations.get(strategy_id)

    def update_allocation(
        self,
        strategy_id: str,
        position_updates: Dict[str, float],
    ):
        """更新分配"""
        allocation = self._allocations.get(strategy_id)
        if allocation:
            allocation.current_positions.update(position_updates)
            allocation.current_exposure = sum(
                abs(p) for p in allocation.current_positions.values()
            )


# ============ 动态权重调整器 ============

class DynamicWeightAdjuster:
    """动态权重调整器"""

    def __init__(self, config: CoordinatorConfig = None):
        self.config = config or CoordinatorConfig()
        self._performance_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=252))
        self._weight_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

    def adjust_weights(
        self,
        strategies: List[Strategy],
        current_weights: Dict[str, float],
        recent_performance: Dict[str, float],
    ) -> Dict[str, float]:
        """调整权重"""
        if not self.config.enable_auto_adjustment:
            return current_weights

        new_weights = {}

        for strategy in strategies:
            sid = strategy.strategy_id
            current = current_weights.get(sid, 1.0 / len(strategies))

            # 记录绩效
            perf = recent_performance.get(sid, 0)
            self._performance_history[sid].append(perf)

            # 计算调整因子
            adjustment = self._calculate_adjustment(strategy, perf)

            # 应用调整
            new_weight = current * adjustment

            # 限制范围
            new_weight = max(0.05, min(0.5, new_weight))
            new_weights[sid] = new_weight

        # 归一化
        total = sum(new_weights.values())
        new_weights = {sid: w / total for sid, w in new_weights.items()}

        # 记录历史
        for sid, w in new_weights.items():
            self._weight_history[sid].append(w)

        return new_weights

    def _calculate_adjustment(self, strategy: Strategy, recent_perf: float) -> float:
        """计算调整因子"""
        history = list(self._performance_history.get(strategy.strategy_id, []))

        if len(history) < 5:
            return 1.0

        # 计算趋势
        recent_avg = np.mean(history[-5:])
        overall_avg = np.mean(history)

        if overall_avg == 0:
            return 1.0

        trend = recent_avg / overall_avg

        # 考虑最大回撤
        dd_factor = 1.0 - strategy.max_drawdown * 2

        # 综合调整
        adjustment = trend * dd_factor

        return max(0.5, min(1.5, adjustment))

    def get_weight_history(
        self,
        strategy_id: str,
        limit: int = 10,
    ) -> List[float]:
        """获取权重历史"""
        history = list(self._weight_history.get(strategy_id, []))
        return history[-limit:]


# ============ 策略绩效归因器 ============

class StrategyAttribution:
    """策略绩效归因器"""

    def __init__(self):
        self._attributions: Dict[str, Dict] = {}

    def calculate_attribution(
        self,
        strategy_returns: Dict[str, List[float]],
        portfolio_returns: List[float],
        benchmark_returns: List[float] = None,
    ) -> Dict:
        """计算归因"""
        total_return = np.sum(portfolio_returns)

        # 各策略贡献
        contributions = {}
        for sid, rets in strategy_returns.items():
            if len(rets) == len(portfolio_returns):
                contribution = np.sum(rets)
                contributions[sid] = {
                    "total_contribution": contribution,
                    "contribution_pct": contribution / total_return if total_return != 0 else 0,
                    "avg_return": np.mean(rets),
                    "volatility": np.std(rets),
                    "sharpe": np.mean(rets) / np.std(rets) if np.std(rets) > 0 else 0,
                }

        # 相对基准
        if benchmark_returns:
            excess_return = np.sum(portfolio_returns) - np.sum(benchmark_returns)
            tracking_error = np.std(np.array(portfolio_returns) - np.array(benchmark_returns)) * np.sqrt(252)
            information_ratio = excess_return / tracking_error if tracking_error > 0 else 0
        else:
            excess_return = 0
            tracking_error = 0
            information_ratio = 0

        result = {
            "total_return": total_return,
            "contributions": contributions,
            "excess_return": excess_return,
            "tracking_error": tracking_error,
            "information_ratio": information_ratio,
            "timestamp": datetime.now().isoformat(),
        }

        self._attributions[datetime.now().date().isoformat()] = result

        return result

    def get_attribution(self, date: str = None) -> Optional[Dict]:
        """获取归因"""
        if date:
            return self._attributions.get(date)
        elif self._attributions:
            return list(self._attributions.values())[-1]
        return None


# ============ 多策略协调器 ============

class StrategyCoordinator:
    """多策略协调器"""

    def __init__(self, config: CoordinatorConfig = None):
        self.config = config or CoordinatorConfig()

        self.signal_fusion = SignalFusion(config)
        self.conflict_resolver = ConflictResolver(config)
        self.capital_allocator = CapitalAllocator(config)
        self.weight_adjuster = DynamicWeightAdjuster(config)
        self.attribution = StrategyAttribution()

        self._strategies: Dict[str, Strategy] = {}
        self._active_signals: List[Signal] = []
        self._lock = threading.Lock()

    def register_strategy(self, strategy: Strategy) -> bool:
        """注册策略"""
        with self._lock:
            if len(self._strategies) >= self.config.max_strategy_count:
                logger.warning(f"[StrategyCoordinator] 策略数量已达上限")
                return False

            self._strategies[strategy.strategy_id] = strategy
            logger.info(f"[StrategyCoordinator] 策略已注册: {strategy.name}")
            return True

    def unregister_strategy(self, strategy_id: str) -> bool:
        """注销策略"""
        with self._lock:
            if strategy_id in self._strategies:
                del self._strategies[strategy_id]
                return True
            return False

    def submit_signal(self, signal: Signal) -> bool:
        """提交信号"""
        with self._lock:
            if signal.strategy_id not in self._strategies:
                logger.warning(f"[StrategyCoordinator] 未知策略: {signal.strategy_id}")
                return False

            self._active_signals.append(signal)
            return True

    def process_signals(self) -> List[FusedSignal]:
        """处理信号"""
        with self._lock:
            signals = self._active_signals.copy()
            self._active_signals.clear()

        if not signals:
            return []

        # 获取策略权重和优先级
        weights = {sid: s.weight for sid, s in self._strategies.items()}
        priorities = {sid: s.priority for sid, s in self._strategies.items()}

        # 检测冲突
        conflicts = self.conflict_resolver.detect_conflicts(signals)

        # 解决冲突
        resolved_signals = []
        for conflict_signals in conflicts:
            conflict = self.conflict_resolver.resolve_conflict(
                conflict_signals, weights, priorities
            )
            resolved_signals.append(conflict.resolved_signal)
            logger.info(f"[StrategyCoordinator] 冲突已解决: {conflict.conflict_id}")

        # 融合信号
        fused = self.signal_fusion.fuse_signals(signals, weights)

        if fused:
            resolved_signals.append(fused)

        return resolved_signals

    def allocate_capital(
        self,
        total_capital: float,
        returns: Dict[str, List[float]] = None,
    ) -> Dict[str, StrategyAllocation]:
        """分配资金"""
        strategies = [s for s in self._strategies.values() if s.status == StrategyStatus.ACTIVE]

        return self.capital_allocator.allocate(
            total_capital=total_capital,
            strategies=strategies,
            returns=returns,
        )

    def adjust_weights(
        self,
        recent_performance: Dict[str, float],
    ) -> Dict[str, float]:
        """调整权重"""
        current_weights = {sid: s.weight for sid, s in self._strategies.items()}

        return self.weight_adjuster.adjust_weights(
            strategies=list(self._strategies.values()),
            current_weights=current_weights,
            recent_performance=recent_performance,
        )

    def calculate_attribution(
        self,
        strategy_returns: Dict[str, List[float]],
        portfolio_returns: List[float],
        benchmark_returns: List[float] = None,
    ) -> Dict:
        """计算归因"""
        return self.attribution.calculate_attribution(
            strategy_returns=strategy_returns,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
        )

    def get_strategy(self, strategy_id: str) -> Optional[Strategy]:
        """获取策略"""
        return self._strategies.get(strategy_id)

    def get_all_strategies(self) -> List[Strategy]:
        """获取所有策略"""
        return list(self._strategies.values())

    def get_active_strategies(self) -> List[Strategy]:
        """获取活跃策略"""
        return [s for s in self._strategies.values() if s.status == StrategyStatus.ACTIVE]


# ============ 便捷函数 ============

def create_coordinator(config: CoordinatorConfig = None) -> StrategyCoordinator:
    """创建协调器"""
    return StrategyCoordinator(config)


def create_signal(
    strategy_id: str,
    code: str,
    signal_type: SignalType,
    strength: SignalStrength,
    confidence: float,
    price: float,
) -> Signal:
    """创建信号"""
    return Signal(
        signal_id=f"signal_{int(datetime.now().timestamp() * 1000)}",
        strategy_id=strategy_id,
        code=code,
        signal_type=signal_type,
        strength=strength,
        confidence=confidence,
        price=price,
        timestamp=datetime.now(),
    )
