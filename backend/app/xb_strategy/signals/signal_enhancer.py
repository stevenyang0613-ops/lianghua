"""西部量化可转债策略 V3.0 交易信号增强模块

功能:
- 多时间框架融合
- 信号过滤器
- 自适应权重
- 信号衰减管理
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import math
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class TimeFrame(str, Enum):
    """时间框架"""
    TICK = "tick"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"


class SignalStrength(str, Enum):
    """信号强度"""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class FilterType(str, Enum):
    """过滤器类型"""
    TREND = "trend"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"


class SignalStatus(str, Enum):
    """信号状态"""
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# ============ 数据模型 ============

@dataclass
class RawSignal:
    """原始信号"""
    signal_id: str
    code: str
    action: str  # buy, sell, hold
    price: float
    quantity: int
    confidence: float
    timeframe: TimeFrame
    source: str
    timestamp: datetime
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "code": self.code,
            "action": self.action,
            "price": self.price,
            "quantity": self.quantity,
            "confidence": round(self.confidence, 4),
            "timeframe": self.timeframe.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class EnhancedSignal:
    """增强信号"""
    signal_id: str
    code: str
    action: str
    price: float
    quantity: int
    base_confidence: float
    enhanced_confidence: float
    strength: SignalStrength
    timeframe_scores: Dict[str, float]
    filter_scores: Dict[str, float]
    decay_factor: float
    status: SignalStatus
    created_at: datetime
    expires_at: datetime
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "code": self.code,
            "action": self.action,
            "price": self.price,
            "quantity": self.quantity,
            "base_confidence": round(self.base_confidence, 4),
            "enhanced_confidence": round(self.enhanced_confidence, 4),
            "strength": self.strength.value,
            "timeframe_scores": {k: round(v, 4) for k, v in self.timeframe_scores.items()},
            "filter_scores": {k: round(v, 4) for k, v in self.filter_scores.items()},
            "decay_factor": round(self.decay_factor, 4),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass
class SignalFilter:
    """信号过滤器"""
    filter_id: str
    filter_type: FilterType
    name: str
    weight: float
    parameters: Dict = field(default_factory=dict)
    enabled: bool = True

    def apply(self, signal: RawSignal, market_data: Dict) -> float:
        """应用过滤器"""
        if not self.enabled:
            return 1.0

        if self.filter_type == FilterType.TREND:
            return self._apply_trend_filter(signal, market_data)
        elif self.filter_type == FilterType.VOLATILITY:
            return self._apply_volatility_filter(signal, market_data)
        elif self.filter_type == FilterType.VOLUME:
            return self._apply_volume_filter(signal, market_data)
        elif self.filter_type == FilterType.MOMENTUM:
            return self._apply_momentum_filter(signal, market_data)
        else:
            return 1.0

    def _apply_trend_filter(self, signal: RawSignal, market_data: Dict) -> float:
        """趋势过滤"""
        trend = market_data.get("trend", 0)

        if signal.action == "buy" and trend > 0:
            return 1.0 + trend * 0.5
        elif signal.action == "sell" and trend < 0:
            return 1.0 + abs(trend) * 0.5
        else:
            return 0.8  # 逆向信号轻微降权

    def _apply_volatility_filter(self, signal: RawSignal, market_data: Dict) -> float:
        """波动率过滤"""
        volatility = market_data.get("volatility", 0.02)
        threshold = self.parameters.get("volatility_threshold", 0.05)

        if volatility > threshold:
            return 0.7  # 高波动降权
        else:
            return 1.0

    def _apply_volume_filter(self, signal: RawSignal, market_data: Dict) -> float:
        """成交量过滤"""
        volume_ratio = market_data.get("volume_ratio", 1.0)

        if volume_ratio > 2.0:
            return 1.2  # 放量信号加权
        elif volume_ratio < 0.5:
            return 0.8  # 缩量信号降权
        else:
            return 1.0

    def _apply_momentum_filter(self, signal: RawSignal, market_data: Dict) -> float:
        """动量过滤"""
        momentum = market_data.get("momentum", 0)
        threshold = self.parameters.get("momentum_threshold", 0.02)

        if abs(momentum) > threshold:
            return 1.0 + abs(momentum) * 2
        else:
            return 0.9


# ============ 多时间框架融合器 ============

class MultiTimeFrameFusion:
    """多时间框架融合器"""

    def __init__(self):
        # 时间框架权重
        self._timeframe_weights = {
            TimeFrame.TICK: 0.1,
            TimeFrame.MINUTE_1: 0.15,
            TimeFrame.MINUTE_5: 0.2,
            TimeFrame.MINUTE_15: 0.15,
            TimeFrame.MINUTE_30: 0.1,
            TimeFrame.HOUR_1: 0.15,
            TimeFrame.HOUR_4: 0.1,
            TimeFrame.DAY_1: 0.05,
        }

        # 各时间框架信号缓存
        self._signals_by_timeframe: Dict[str, Dict[TimeFrame, List[RawSignal]]] = defaultdict(lambda: defaultdict(list))

    def add_signal(self, signal: RawSignal):
        """添加信号"""
        self._signals_by_timeframe[signal.code][signal.timeframe].append(signal)

    def calculate_timeframe_score(self, code: str) -> Dict[str, float]:
        """计算时间框架评分"""
        scores = {}

        for timeframe, signals in self._signals_by_timeframe[code].items():
            if not signals:
                scores[timeframe.value] = 0
                continue

            # 计算平均置信度
            avg_confidence = sum(s.confidence for s in signals[-10:]) / min(10, len(signals))

            # 计算方向一致性
            buy_signals = sum(1 for s in signals[-10:] if s.action == "buy")
            sell_signals = sum(1 for s in signals[-10:] if s.action == "sell")
            total = buy_signals + sell_signals

            if total > 0:
                direction_score = max(buy_signals, sell_signals) / total
            else:
                direction_score = 0.5

            # 综合评分
            scores[timeframe.value] = avg_confidence * direction_score

        return scores

    def fuse_signals(self, code: str, primary_action: str) -> Tuple[float, Dict[str, float]]:
        """融合信号"""
        scores = self.calculate_timeframe_score(code)

        # 加权融合
        fused_score = 0
        total_weight = 0

        for timeframe, score in scores.items():
            weight = self._timeframe_weights.get(TimeFrame(timeframe), 0.1)
            fused_score += score * weight
            total_weight += weight

        if total_weight > 0:
            fused_score /= total_weight

        return fused_score, scores

    def detect_alignment(self, code: str) -> Dict[str, Any]:
        """检测时间框架对齐"""
        signals = self._signals_by_timeframe[code]

        if not signals:
            return {"aligned": False, "direction": "none"}

        # 统计各时间框架方向
        directions = {}

        for timeframe, sigs in signals.items():
            if not sigs:
                continue

            latest = sigs[-1]
            directions[timeframe.value] = latest.action

        # 检查对齐
        buy_count = sum(1 for d in directions.values() if d == "buy")
        sell_count = sum(1 for d in directions.values() if d == "sell")
        total = buy_count + sell_count

        if total == 0:
            return {"aligned": False, "direction": "none"}

        if buy_count / total > 0.7:
            return {"aligned": True, "direction": "buy", "alignment_score": buy_count / total}
        elif sell_count / total > 0.7:
            return {"aligned": True, "direction": "sell", "alignment_score": sell_count / total}
        else:
            return {"aligned": False, "direction": "mixed", "alignment_score": max(buy_count, sell_count) / total}


# ============ 自适应权重管理器 ============

class AdaptiveWeightManager:
    """自适应权重管理器"""

    def __init__(self):
        self._signal_sources: Dict[str, Dict] = {}
        self._performance_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

    def register_source(self, source_id: str, initial_weight: float = 1.0):
        """注册信号源"""
        self._signal_sources[source_id] = {
            "weight": initial_weight,
            "total_signals": 0,
            "correct_signals": 0,
            "accuracy": 0.5,
        }

    def update_weight(self, source_id: str, performance: float):
        """更新权重"""
        if source_id not in self._signal_sources:
            return

        source = self._signal_sources[source_id]
        self._performance_history[source_id].append(performance)

        # 计算近期表现
        history = list(self._performance_history[source_id])
        if history:
            recent_performance = sum(history[-20:]) / len(history[-20:])

            # 调整权重 (表现好的加权，表现差的降权)
            base_weight = 1.0
            adjustment = (recent_performance - 0.5) * 2  # -1 到 1
            new_weight = max(0.1, min(2.0, base_weight + adjustment))

            source["weight"] = new_weight

    def get_weight(self, source_id: str) -> float:
        """获取权重"""
        source = self._signal_sources.get(source_id)
        return source["weight"] if source else 1.0

    def record_signal_outcome(self, source_id: str, was_correct: bool):
        """记录信号结果"""
        if source_id not in self._signal_sources:
            return

        source = self._signal_sources[source_id]
        source["total_signals"] += 1

        if was_correct:
            source["correct_signals"] += 1

        source["accuracy"] = source["correct_signals"] / source["total_signals"]

    def get_top_sources(self, n: int = 5) -> List[Dict]:
        """获取最佳信号源"""
        sources = [
            {
                "source_id": sid,
                "weight": s["weight"],
                "accuracy": s["accuracy"],
                "total_signals": s["total_signals"],
            }
            for sid, s in self._signal_sources.items()
        ]

        return sorted(sources, key=lambda x: x["weight"], reverse=True)[:n]


# ============ 信号衰减管理器 ============

class SignalDecayManager:
    """信号衰减管理器"""

    def __init__(self):
        # 衰减配置
        self._decay_config = {
            TimeFrame.TICK: {"half_life_minutes": 1, "max_age_minutes": 5},
            TimeFrame.MINUTE_1: {"half_life_minutes": 5, "max_age_minutes": 30},
            TimeFrame.MINUTE_5: {"half_life_minutes": 15, "max_age_minutes": 60},
            TimeFrame.MINUTE_15: {"half_life_minutes": 30, "max_age_minutes": 120},
            TimeFrame.MINUTE_30: {"half_life_minutes": 60, "max_age_minutes": 240},
            TimeFrame.HOUR_1: {"half_life_minutes": 120, "max_age_minutes": 480},
            TimeFrame.HOUR_4: {"half_life_minutes": 240, "max_age_minutes": 1440},
            TimeFrame.DAY_1: {"half_life_minutes": 720, "max_age_minutes": 10080},
        }

    def calculate_decay(
        self,
        signal_time: datetime,
        timeframe: TimeFrame,
        current_time: datetime = None,
    ) -> float:
        """计算衰减因子"""
        current_time = current_time or datetime.now()

        config = self._decay_config.get(timeframe, {"half_life_minutes": 60, "max_age_minutes": 240})

        age_minutes = (current_time - signal_time).total_seconds() / 60
        half_life = config["half_life_minutes"]
        max_age = config["max_age_minutes"]

        if age_minutes > max_age:
            return 0.0

        # 指数衰减
        decay = math.exp(-math.log(2) * age_minutes / half_life)

        return max(0, min(1, decay))

    def is_expired(
        self,
        signal_time: datetime,
        timeframe: TimeFrame,
        current_time: datetime = None,
    ) -> bool:
        """判断信号是否过期"""
        current_time = current_time or datetime.now()

        config = self._decay_config.get(timeframe, {"max_age_minutes": 240})
        age_minutes = (current_time - signal_time).total_seconds() / 60

        return age_minutes > config["max_age_minutes"]

    def get_remaining_validity(
        self,
        signal_time: datetime,
        timeframe: TimeFrame,
        current_time: datetime = None,
    ) -> float:
        """获取剩余有效期 (分钟)"""
        current_time = current_time or datetime.now()

        config = self._decay_config.get(timeframe, {"max_age_minutes": 240})
        age_minutes = (current_time - signal_time).total_seconds() / 60

        remaining = config["max_age_minutes"] - age_minutes

        return max(0, remaining)


# ============ 信号增强器 ============

class SignalEnhancer:
    """信号增强器"""

    def __init__(self):
        self.timeframe_fusion = MultiTimeFrameFusion()
        self.weight_manager = AdaptiveWeightManager()
        self.decay_manager = SignalDecayManager()

        self._filters: List[SignalFilter] = []
        self._enhanced_signals: Dict[str, EnhancedSignal] = {}

    def add_filter(self, filter_obj: SignalFilter):
        """添加过滤器"""
        self._filters.append(filter_obj)

    def enhance_signal(
        self,
        signal: RawSignal,
        market_data: Dict = None,
    ) -> EnhancedSignal:
        """增强信号"""
        # 1. 计算时间框架融合评分
        self.timeframe_fusion.add_signal(signal)
        fused_score, timeframe_scores = self.timeframe_fusion.fuse_signals(signal.code, signal.action)

        # 2. 应用过滤器
        filter_scores = {}
        filter_multiplier = 1.0

        for f in self._filters:
            score = f.apply(signal, market_data or {})
            filter_scores[f.filter_id] = score
            filter_multiplier *= score

        # 3. 应用自适应权重
        source_weight = self.weight_manager.get_weight(signal.source)

        # 4. 计算衰减因子
        decay_factor = self.decay_manager.calculate_decay(
            signal.timestamp, signal.timeframe
        )

        # 5. 计算增强置信度
        enhanced_confidence = (
            signal.confidence *
            fused_score *
            filter_multiplier *
            source_weight *
            decay_factor
        )

        # 6. 确定信号强度
        strength = self._determine_strength(enhanced_confidence)

        # 7. 计算过期时间
        config = self.decay_manager._decay_config.get(signal.timeframe, {"max_age_minutes": 240})
        expires_at = signal.timestamp + timedelta(minutes=config["max_age_minutes"])

        # 创建增强信号
        enhanced = EnhancedSignal(
            signal_id=f"enhanced_{signal.signal_id}",
            code=signal.code,
            action=signal.action,
            price=signal.price,
            quantity=signal.quantity,
            base_confidence=signal.confidence,
            enhanced_confidence=enhanced_confidence,
            strength=strength,
            timeframe_scores=timeframe_scores,
            filter_scores=filter_scores,
            decay_factor=decay_factor,
            status=SignalStatus.ACTIVE,
            created_at=datetime.now(),
            expires_at=expires_at,
            metadata={"original_signal": signal.signal_id, "source": signal.source},
        )

        self._enhanced_signals[enhanced.signal_id] = enhanced

        return enhanced

    def _determine_strength(self, confidence: float) -> SignalStrength:
        """确定信号强度"""
        if confidence >= 0.9:
            return SignalStrength.VERY_STRONG
        elif confidence >= 0.7:
            return SignalStrength.STRONG
        elif confidence >= 0.5:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK

    def update_signal_outcome(self, signal_id: str, was_correct: bool):
        """更新信号结果"""
        enhanced = self._enhanced_signals.get(signal_id)
        if not enhanced:
            return

        source = enhanced.metadata.get("source")
        if source:
            self.weight_manager.record_signal_outcome(source, was_correct)

        enhanced.status = SignalStatus.CONFIRMED if was_correct else SignalStatus.CANCELLED

    def get_active_signals(self, code: str = None) -> List[EnhancedSignal]:
        """获取活跃信号"""
        signals = [s for s in self._enhanced_signals.values() if s.status == SignalStatus.ACTIVE]

        if code:
            signals = [s for s in signals if s.code == code]

        # 应用衰减
        current_time = datetime.now()
        valid_signals = []

        for s in signals:
            decay = self.decay_manager.calculate_decay(s.created_at, TimeFrame.MINUTE_5, current_time)
            if decay > 0.1:  # 保留衰减大于10%的信号
                s.decay_factor = decay
                valid_signals.append(s)
            else:
                s.status = SignalStatus.EXPIRED

        return sorted(valid_signals, key=lambda x: x.enhanced_confidence, reverse=True)


# ============ 便捷函数 ============

def create_signal_enhancer() -> SignalEnhancer:
    """创建信号增强器"""
    return SignalEnhancer()


def enhance_signal(
    signal: RawSignal,
    market_data: Dict = None,
) -> EnhancedSignal:
    """增强信号"""
    enhancer = SignalEnhancer()
    return enhancer.enhance_signal(signal, market_data)


def calculate_signal_decay(
    signal_time: datetime,
    timeframe: str,
) -> float:
    """计算信号衰减"""
    manager = SignalDecayManager()
    return manager.calculate_decay(signal_time, TimeFrame(timeframe))
