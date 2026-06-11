"""松岗量化可转债策略 V3.0 市场状态识别模块

功能:
- 牛熊市识别
- 波动率状态
- 趋势强度判断
- 市场情绪指标
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import math
import numpy as np
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class MarketRegime(str, Enum):
    """市场状态"""
    BULL = "bull"               # 牛市
    BEAR = "bear"               # 熊市
    SIDEWAYS = "sideways"       # 震荡
    RECOVERY = "recovery"       # 反弹
    CORRECTION = "correction"   # 回调
    HIGH_VOLATILITY = "high_vol"  # 高波动
    LOW_VOLATILITY = "low_vol"    # 低波动


class TrendStrength(str, Enum):
    """趋势强度"""
    STRONG_UP = "strong_up"
    UP = "up"
    WEAK_UP = "weak_up"
    NEUTRAL = "neutral"
    WEAK_DOWN = "weak_down"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class VolatilityRegime(str, Enum):
    """波动率状态"""
    EXTREMELY_LOW = "extremely_low"
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREMELY_HIGH = "extremely_high"


class SentimentLevel(str, Enum):
    """情绪水平"""
    EXTREME_FEAR = "extreme_fear"
    FEAR = "fear"
    NEUTRAL = "neutral"
    GREED = "greed"
    EXTREME_GREED = "extreme_greed"


# ============ 数据模型 ============

@dataclass
class MarketSnapshot:
    """市场快照"""
    timestamp: datetime
    index_value: float
    volume: float
    advance_count: int
    decline_count: int
    new_high_count: int
    new_low_count: int
    turnover: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "index_value": self.index_value,
            "volume": self.volume,
            "advance_count": self.advance_count,
            "decline_count": self.decline_count,
        }


@dataclass
class RegimeResult:
    """状态识别结果"""
    timestamp: datetime
    regime: MarketRegime
    regime_probability: float
    trend_strength: TrendStrength
    volatility_regime: VolatilityRegime
    sentiment_level: SentimentLevel
    confidence: float
    indicators: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "regime": self.regime.value,
            "regime_probability": round(self.regime_probability, 4),
            "trend_strength": self.trend_strength.value,
            "volatility_regime": self.volatility_regime.value,
            "sentiment_level": self.sentiment_level.value,
            "confidence": round(self.confidence, 4),
            "indicators": {k: round(v, 4) for k, v in self.indicators.items()},
        }


@dataclass
class TrendAnalysis:
    """趋势分析"""
    direction: str
    strength: float
    slope: float
    r_squared: float
    duration_days: int
    support_level: float
    resistance_level: float

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "strength": round(self.strength, 4),
            "slope": round(self.slope, 6),
            "r_squared": round(self.r_squared, 4),
            "duration_days": self.duration_days,
            "support_level": round(self.support_level, 4),
            "resistance_level": round(self.resistance_level, 4),
        }


# ============ 牛熊市识别器 ============

class BullBearDetector:
    """牛熊市识别器"""

    def __init__(self, lookback_periods: int = 252):
        self.lookback_periods = lookback_periods
        self._price_history: deque = deque(maxlen=lookback_periods)
        self._regime_history: List[MarketRegime] = []

    def update(self, price: float, timestamp: datetime = None):
        """更新价格"""
        self._price_history.append({
            "price": price,
            "timestamp": timestamp or datetime.now(),
        })

    def detect(self) -> Tuple[MarketRegime, float]:
        """识别市场状态"""
        if len(self._price_history) < 60:
            return MarketRegime.SIDEWAYS, 0.5

        prices = [p["price"] for p in self._price_history]

        # 计算多个指标
        ma20 = np.mean(prices[-20:])
        ma60 = np.mean(prices[-60:])
        ma120 = np.mean(prices[-120:]) if len(prices) >= 120 else ma60

        current_price = prices[-1]

        # 高点低点判断
        recent_high = max(prices[-60:])
        recent_low = min(prices[-60:])

        # 从高点/低点的位置
        from_high = (current_price - recent_high) / recent_high if recent_high > 0 else 0
        from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0

        # 牛熊判断
        score = 0

        # 均线多头排列
        if ma20 > ma60 > ma120:
            score += 3
        elif ma20 > ma60:
            score += 2
        elif ma20 < ma60 < ma120:
            score -= 3
        elif ma20 < ma60:
            score -= 2

        # 价格位置
        if current_price > ma20:
            score += 1
        else:
            score -= 1

        # 回撤判断
        if from_high < -0.2:
            score -= 2  # 超过20%回撤
        elif from_high < -0.1:
            score -= 1

        # 确定状态
        if score >= 4:
            regime = MarketRegime.BULL
            probability = min(0.95, 0.6 + score * 0.05)
        elif score <= -4:
            regime = MarketRegime.BEAR
            probability = min(0.95, 0.6 + abs(score) * 0.05)
        elif score >= 2:
            regime = MarketRegime.RECOVERY
            probability = 0.6
        elif score <= -2:
            regime = MarketRegime.CORRECTION
            probability = 0.6
        else:
            regime = MarketRegime.SIDEWAYS
            probability = 0.5

        self._regime_history.append(regime)

        return regime, probability

    def get_regime_duration(self) -> int:
        """获取当前状态持续时间"""
        if not self._regime_history:
            return 0

        current = self._regime_history[-1]
        count = 0

        for regime in reversed(self._regime_history):
            if regime == current:
                count += 1
            else:
                break

        return count


# ============ 波动率状态识别器 ============

class VolatilityRegimeDetector:
    """波动率状态识别器"""

    def __init__(self, lookback_periods: int = 252):
        self.lookback_periods = lookback_periods
        self._returns_history: deque = deque(maxlen=lookback_periods)
        self._vol_history: deque = deque(maxlen=lookback_periods)

    def update(self, return_value: float):
        """更新收益率"""
        self._returns_history.append(return_value)

        # 计算滚动波动率
        if len(self._returns_history) >= 20:
            vol = np.std(list(self._returns_history)[-20:]) * np.sqrt(252)
            self._vol_history.append(vol)

    def detect(self) -> Tuple[VolatilityRegime, float]:
        """识别波动率状态"""
        if len(self._vol_history) < 60:
            return VolatilityRegime.NORMAL, 0.5

        current_vol = self._vol_history[-1]
        vol_history = list(self._vol_history)

        # 分位数
        sorted_vol = sorted(vol_history)
        n = len(sorted_vol)

        q10 = sorted_vol[int(n * 0.1)]
        q25 = sorted_vol[int(n * 0.25)]
        q75 = sorted_vol[int(n * 0.75)]
        q90 = sorted_vol[int(n * 0.9)]

        # 确定状态
        if current_vol >= q90:
            regime = VolatilityRegime.EXTREMELY_HIGH
            probability = (current_vol - q90) / (sorted_vol[-1] - q90 + 0.01)
        elif current_vol >= q75:
            regime = VolatilityRegime.HIGH
            probability = (current_vol - q75) / (q90 - q75 + 0.01)
        elif current_vol <= q10:
            regime = VolatilityRegime.EXTREMELY_LOW
            probability = (q10 - current_vol) / (q10 - sorted_vol[0] + 0.01)
        elif current_vol <= q25:
            regime = VolatilityRegime.LOW
            probability = (q25 - current_vol) / (q25 - q10 + 0.01)
        else:
            regime = VolatilityRegime.NORMAL
            probability = 0.5

        return regime, min(0.95, probability)

    def get_vol_percentile(self) -> float:
        """获取当前波动率分位"""
        if not self._vol_history:
            return 0.5

        current_vol = self._vol_history[-1]
        vol_history = list(self._vol_history)

        below_count = sum(1 for v in vol_history if v < current_vol)
        percentile = below_count / len(vol_history)

        return percentile


# ============ 趋势强度分析器 ============

class TrendStrengthAnalyzer:
    """趋势强度分析器"""

    def __init__(self):
        self._price_history: deque = deque(maxlen=252)

    def update(self, price: float):
        """更新价格"""
        self._price_history.append(price)

    def analyze(self, window: int = 60) -> TrendAnalysis:
        """分析趋势"""
        if len(self._price_history) < window:
            return TrendAnalysis(
                direction="neutral",
                strength=0,
                slope=0,
                r_squared=0,
                duration_days=0,
                support_level=0,
                resistance_level=0,
            )

        prices = list(self._price_history)[-window:]

        # 线性回归
        x = np.arange(len(prices))
        y = np.array(prices)

        # 斜率和截距
        n = len(x)
        sum_x = np.sum(x)
        sum_y = np.sum(y)
        sum_xy = np.sum(x * y)
        sum_x2 = np.sum(x ** 2)

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
        intercept = (sum_y - slope * sum_x) / n

        # R²
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # 趋势强度 (结合斜率和R²)
        strength = abs(slope) / np.mean(prices) * r_squared * 100

        # 方向
        if slope > 0.0001 * np.mean(prices):
            if strength > 2:
                direction = "strong_up"
            elif strength > 1:
                direction = "up"
            else:
                direction = "weak_up"
        elif slope < -0.0001 * np.mean(prices):
            if strength > 2:
                direction = "strong_down"
            elif strength > 1:
                direction = "down"
            else:
                direction = "weak_down"
        else:
            direction = "neutral"

        # 支撑阻力
        support = min(prices[-20:])
        resistance = max(prices[-20:])

        # 趋势持续时间
        duration = 0
        current_direction = "up" if slope > 0 else "down"

        for i in range(len(self._price_history) - 1, 0, -1):
            if i < 1:
                break
            prev = self._price_history[i - 1]
            curr = self._price_history[i]

            if current_direction == "up" and curr >= prev:
                duration += 1
            elif current_direction == "down" and curr <= prev:
                duration += 1
            else:
                break

        return TrendAnalysis(
            direction=direction,
            strength=min(10, strength),
            slope=slope,
            r_squared=r_squared,
            duration_days=duration,
            support_level=support,
            resistance_level=resistance,
        )


# ============ 市场情绪分析器 ============

class MarketSentimentAnalyzer:
    """市场情绪分析器"""

    def __init__(self):
        self._indicators: Dict[str, deque] = {
            "advance_decline": deque(maxlen=20),
            "new_high_low": deque(maxlen=20),
            "volume_ratio": deque(maxlen=20),
            "put_call": deque(maxlen=20),
            "vix": deque(maxlen=20),
        }

    def update(
        self,
        advance_count: int,
        decline_count: int,
        new_high: int,
        new_low: int,
        volume: float,
        avg_volume: float,
        put_call_ratio: float = None,
        vix: float = None,
    ):
        """更新指标"""
        # 涨跌比
        total = advance_count + decline_count
        ad_ratio = advance_count / total if total > 0 else 0.5
        self._indicators["advance_decline"].append(ad_ratio)

        # 新高新低比
        total_hl = new_high + new_low
        hl_ratio = new_high / total_hl if total_hl > 0 else 0.5
        self._indicators["new_high_low"].append(hl_ratio)

        # 成交量比
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        self._indicators["volume_ratio"].append(vol_ratio)

        if put_call_ratio:
            self._indicators["put_call"].append(put_call_ratio)

        if vix:
            self._indicators["vix"].append(vix)

    def calculate_sentiment(self) -> Tuple[SentimentLevel, float]:
        """计算市场情绪"""
        if not all(self._indicators.values()):
            return SentimentLevel.NEUTRAL, 0.5

        # 综合情绪分数 (0-100)
        score = 50

        # 涨跌比贡献
        ad_values = list(self._indicators["advance_decline"])
        if ad_values:
            ad_avg = np.mean(ad_values[-5:])
            score += (ad_avg - 0.5) * 30

        # 新高新低贡献
        hl_values = list(self._indicators["new_high_low"])
        if hl_values:
            hl_avg = np.mean(hl_values[-5:])
            score += (hl_avg - 0.5) * 20

        # 成交量贡献
        vol_values = list(self._indicators["volume_ratio"])
        if vol_values:
            vol_avg = np.mean(vol_values[-5:])
            if vol_avg > 1.2:
                score += 10  # 放量
            elif vol_avg < 0.8:
                score -= 5  # 缩量

        # VIX贡献
        vix_values = list(self._indicators["vix"])
        if vix_values:
            vix_avg = np.mean(vix_values[-5:])
            if vix_avg > 30:
                score -= 15  # 高恐慌
            elif vix_avg < 15:
                score += 10  # 低恐慌

        # 确定情绪水平
        score = max(0, min(100, score))

        if score >= 80:
            return SentimentLevel.EXTREME_GREED, score / 100
        elif score >= 60:
            return SentimentLevel.GREED, score / 100
        elif score >= 40:
            return SentimentLevel.NEUTRAL, score / 100
        elif score >= 20:
            return SentimentLevel.FEAR, score / 100
        else:
            return SentimentLevel.EXTREME_FEAR, score / 100

    def get_fear_greed_index(self) -> float:
        """获取恐惧贪婪指数"""
        _, score = self.calculate_sentiment()
        return score * 100


# ============ 市场状态识别服务 ============

class RegimeDetectionService:
    """市场状态识别服务"""

    def __init__(self):
        self.bull_bear_detector = BullBearDetector()
        self.volatility_detector = VolatilityRegimeDetector()
        self.trend_analyzer = TrendStrengthAnalyzer()
        self.sentiment_analyzer = MarketSentimentAnalyzer()

        self._history: List[RegimeResult] = []

    def process_snapshot(self, snapshot: MarketSnapshot) -> RegimeResult:
        """处理市场快照"""
        # 更新各模块
        self.bull_bear_detector.update(snapshot.index_value, snapshot.timestamp)

        # 假设有历史价格计算收益率
        returns = 0.001  # 简化
        self.volatility_detector.update(returns)

        self.trend_analyzer.update(snapshot.index_value)

        self.sentiment_analyzer.update(
            advance_count=snapshot.advance_count,
            decline_count=snapshot.decline_count,
            new_high=snapshot.new_high_count,
            new_low=snapshot.new_low_count,
            volume=snapshot.volume,
            avg_volume=snapshot.volume * 0.9,
        )

        # 识别各状态
        regime, regime_prob = self.bull_bear_detector.detect()
        vol_regime, vol_prob = self.volatility_detector.detect()
        trend = self.trend_analyzer.analyze()
        sentiment, sent_score = self.sentiment_analyzer.calculate_sentiment()

        # 确定趋势强度
        trend_map = {
            "strong_up": TrendStrength.STRONG_UP,
            "up": TrendStrength.UP,
            "weak_up": TrendStrength.WEAK_UP,
            "neutral": TrendStrength.NEUTRAL,
            "weak_down": TrendStrength.WEAK_DOWN,
            "down": TrendStrength.DOWN,
            "strong_down": TrendStrength.STRONG_DOWN,
        }
        trend_strength = trend_map.get(trend.direction, TrendStrength.NEUTRAL)

        # 整合波动率状态
        if vol_regime in [VolatilityRegime.HIGH, VolatilityRegime.EXTREMELY_HIGH]:
            if regime == MarketRegime.SIDEWAYS:
                regime = MarketRegime.HIGH_VOLATILITY

        # 计算综合置信度
        confidence = (regime_prob + vol_prob + sent_score) / 3

        result = RegimeResult(
            timestamp=snapshot.timestamp,
            regime=regime,
            regime_probability=regime_prob,
            trend_strength=trend_strength,
            volatility_regime=vol_regime,
            sentiment_level=sentiment,
            confidence=confidence,
            indicators={
                "trend_strength_value": trend.strength,
                "volatility_percentile": self.volatility_detector.get_vol_percentile(),
                "fear_greed_index": self.sentiment_analyzer.get_fear_greed_index(),
            },
        )

        self._history.append(result)

        return result

    def get_current_regime(self) -> Optional[RegimeResult]:
        """获取当前状态"""
        if self._history:
            return self._history[-1]
        return None

    def get_regime_summary(self) -> Dict:
        """获取状态摘要"""
        current = self.get_current_regime()

        if not current:
            return {}

        return {
            "regime": current.regime.value,
            "trend": current.trend_strength.value,
            "volatility": current.volatility_regime.value,
            "sentiment": current.sentiment_level.value,
            "confidence": current.confidence,
            "fear_greed_index": current.indicators.get("fear_greed_index", 50),
        }


# ============ 便捷函数 ============

def create_regime_service() -> RegimeDetectionService:
    """创建状态识别服务"""
    return RegimeDetectionService()


def detect_market_regime(prices: List[float]) -> MarketRegime:
    """识别市场状态"""
    detector = BullBearDetector()

    for price in prices:
        detector.update(price)

    regime, _ = detector.detect()
    return regime


def analyze_trend(prices: List[float]) -> TrendAnalysis:
    """分析趋势"""
    analyzer = TrendStrengthAnalyzer()

    for price in prices:
        analyzer.update(price)

    return analyzer.analyze()
