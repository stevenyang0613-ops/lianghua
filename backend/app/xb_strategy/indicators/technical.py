"""西部量化可转债策略 V3.0 技术指标模块

功能:
- 移动平均线 (MA/EMA/SMA)
- MACD指标
- KDJ指标
- 布林带 (BOLL)
- RSI相对强弱指标
- ATR真实波动幅度
- 威廉指标 (WR)
- 成交量指标 (OBV/VWAP)
- 信号生成
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class SignalType(str, Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    STRONG_BUY = "strong_buy"
    STRONG_SELL = "strong_sell"


class TrendType(str, Enum):
    """趋势类型"""
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    SIDEWAYS = "sideways"


# ============ 配置类 ============

@dataclass
class IndicatorConfig:
    """指标配置"""
    # MA配置
    ma_periods: List[int] = field(default_factory=lambda: [5, 10, 20, 60])

    # MACD配置
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # KDJ配置
    kdj_n: int = 9
    kdj_m1: int = 3
    kdj_m2: int = 3

    # BOLL配置
    boll_period: int = 20
    boll_std: float = 2.0

    # RSI配置
    rsi_period: int = 14

    # ATR配置
    atr_period: int = 14

    # WR配置
    wr_period: int = 14


@dataclass
class IndicatorResult:
    """指标结果"""
    name: str
    value: float
    signal: SignalType
    strength: float  # 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "signal": self.signal.value,
            "strength": round(self.strength, 4),
            "metadata": self.metadata,
        }


# ============ 基础指标计算 ============

class BaseIndicators:
    """基础指标计算"""

    @staticmethod
    def ma(prices: List[float], period: int) -> List[float]:
        """简单移动平均"""
        if len(prices) < period:
            return []

        result = []
        for i in range(len(prices)):
            if i < period - 1:
                result.append(np.nan)
            else:
                result.append(np.mean(prices[i-period+1:i+1]))
        return result

    @staticmethod
    def ema(prices: List[float], period: int) -> List[float]:
        """指数移动平均"""
        if len(prices) < period:
            return []

        result = []
        multiplier = 2 / (period + 1)

        # 初始SMA
        sma = np.mean(prices[:period])
        result.extend([np.nan] * (period - 1))
        result.append(sma)

        # EMA计算
        for i in range(period, len(prices)):
            ema_val = (prices[i] - result[-1]) * multiplier + result[-1]
            result.append(ema_val)

        return result

    @staticmethod
    def sma(prices: List[float], period: int) -> List[float]:
        """加权移动平均"""
        if len(prices) < period:
            return []

        result = []
        weights = list(range(1, period + 1))
        weight_sum = sum(weights)

        for i in range(len(prices)):
            if i < period - 1:
                result.append(np.nan)
            else:
                weighted_sum = sum(prices[i-period+1+j] * (j+1) for j in range(period))
                result.append(weighted_sum / weight_sum)

        return result


# ============ MACD指标 ============

class MACDIndicator:
    """MACD指标"""

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

    def calculate(self, prices: List[float]) -> Dict[str, Any]:
        """计算MACD"""
        if len(prices) < self.config.macd_slow + self.config.macd_signal:
            return {"macd": [], "signal": [], "histogram": [], "trend": None}

        # 计算EMA
        ema_fast = BaseIndicators.ema(prices, self.config.macd_fast)
        ema_slow = BaseIndicators.ema(prices, self.config.macd_slow)

        # DIF
        dif = [f - s if not (np.isnan(f) or np.isnan(s)) else np.nan
               for f, s in zip(ema_fast, ema_slow)]

        # DEA (信号线)
        valid_dif = [d for d in dif if not np.isnan(d)]
        dea = BaseIndicators.ema(valid_dif, self.config.macd_signal)

        # 填充前面的NaN
        nan_count = len(dif) - len(dea)
        dea_full = [np.nan] * nan_count + dea

        # MACD柱
        macd = []
        histogram = []
        for d, s in zip(dif, dea_full):
            if np.isnan(d) or np.isnan(s):
                macd.append(np.nan)
                histogram.append(np.nan)
            else:
                macd.append(d)
                histogram.append(2 * (d - s))

        # 判断趋势
        trend = self._determine_trend(histogram)

        return {
            "macd": macd,
            "signal": dea_full,
            "histogram": histogram,
            "trend": trend,
            "latest_macd": macd[-1] if macd and not np.isnan(macd[-1]) else None,
            "latest_signal": dea_full[-1] if dea_full and not np.isnan(dea_full[-1]) else None,
            "latest_histogram": histogram[-1] if histogram and not np.isnan(histogram[-1]) else None,
        }

    def _determine_trend(self, histogram: List[float]) -> Optional[str]:
        """判断趋势"""
        valid = [h for h in histogram if not np.isnan(h)]
        if len(valid) < 3:
            return None

        recent = valid[-3:]
        if all(h > 0 for h in recent):
            return "bullish"
        elif all(h < 0 for h in recent):
            return "bearish"
        elif recent[-1] > recent[-2] > recent[-3]:
            return "turning_bullish"
        elif recent[-1] < recent[-2] < recent[-3]:
            return "turning_bearish"
        else:
            return "neutral"

    def generate_signal(self, prices: List[float]) -> IndicatorResult:
        """生成信号"""
        result = self.calculate(prices)
        histogram = result.get("latest_histogram")
        trend = result.get("trend")

        if histogram is None:
            return IndicatorResult(
                name="MACD",
                value=0,
                signal=SignalType.HOLD,
                strength=0,
            )

        # 信号判断
        if trend == "turning_bullish":
            signal = SignalType.BUY
            strength = min(0.9, abs(histogram) * 10)
        elif trend == "turning_bearish":
            signal = SignalType.SELL
            strength = min(0.9, abs(histogram) * 10)
        elif trend == "bullish":
            signal = SignalType.HOLD
            strength = 0.3
        elif trend == "bearish":
            signal = SignalType.HOLD
            strength = 0.3
        else:
            signal = SignalType.HOLD
            strength = 0.2

        return IndicatorResult(
            name="MACD",
            value=histogram,
            signal=signal,
            strength=strength,
            metadata={"trend": trend, "macd": result.get("latest_macd")},
        )


# ============ KDJ指标 ============

class KDJIndicator:
    """KDJ指标"""

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

    def calculate(
        self,
        high: List[float],
        low: List[float],
        close: List[float],
    ) -> Dict[str, Any]:
        """计算KDJ"""
        n = self.config.kdj_n

        if len(close) < n:
            return {"k": [], "d": [], "j": []}

        # 计算RSV
        rsv = []
        for i in range(len(close)):
            if i < n - 1:
                rsv.append(50)  # 默认值
            else:
                high_n = max(high[i-n+1:i+1])
                low_n = min(low[i-n+1:i+1])
                if high_n == low_n:
                    rsv.append(50)
                else:
                    rsv.append((close[i] - low_n) / (high_n - low_n) * 100)

        # 计算K、D、J
        k = [50]  # 初始值
        d = [50]

        alpha_k = 1 / self.config.kdj_m1
        alpha_d = 1 / self.config.kdj_m2

        for i in range(1, len(rsv)):
            k_val = (1 - alpha_k) * k[-1] + alpha_k * rsv[i]
            d_val = (1 - alpha_d) * d[-1] + alpha_d * k_val
            k.append(k_val)
            d.append(d_val)

        # J值
        j = [3 * k[i] - 2 * d[i] for i in range(len(k))]

        return {
            "k": k,
            "d": d,
            "j": j,
            "latest_k": k[-1] if k else None,
            "latest_d": d[-1] if d else None,
            "latest_j": j[-1] if j else None,
        }

    def generate_signal(
        self,
        high: List[float],
        low: List[float],
        close: List[float],
    ) -> IndicatorResult:
        """生成信号"""
        result = self.calculate(high, low, close)
        k = result.get("latest_k")
        d = result.get("latest_d")
        j = result.get("latest_j")

        if k is None or d is None:
            return IndicatorResult(
                name="KDJ",
                value=0,
                signal=SignalType.HOLD,
                strength=0,
            )

        # 超买超卖判断
        if k < 20 and d < 20:
            signal = SignalType.BUY
            strength = 0.8
        elif k > 80 and d > 80:
            signal = SignalType.SELL
            strength = 0.8
        # 金叉死叉
        elif len(result["k"]) >= 2:
            k_prev, d_prev = result["k"][-2], result["d"][-2]
            if k_prev < d_prev and k > d:  # 金叉
                signal = SignalType.BUY
                strength = 0.7
            elif k_prev > d_prev and k < d:  # 死叉
                signal = SignalType.SELL
                strength = 0.7
            else:
                signal = SignalType.HOLD
                strength = 0.3
        else:
            signal = SignalType.HOLD
            strength = 0.3

        return IndicatorResult(
            name="KDJ",
            value=k,
            signal=signal,
            strength=strength,
            metadata={"k": k, "d": d, "j": j},
        )


# ============ 布林带指标 ============

class BOLLIndicator:
    """布林带指标"""

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

    def calculate(self, prices: List[float]) -> Dict[str, Any]:
        """计算布林带"""
        period = self.config.boll_period
        std_mult = self.config.boll_std

        if len(prices) < period:
            return {"upper": [], "middle": [], "lower": [], "width": []}

        middle = BaseIndicators.ma(prices, period)

        upper = []
        lower = []
        width = []

        for i in range(len(prices)):
            if i < period - 1:
                upper.append(np.nan)
                lower.append(np.nan)
                width.append(np.nan)
            else:
                window = prices[i-period+1:i+1]
                std = np.std(window)
                upper.append(middle[i] + std_mult * std)
                lower.append(middle[i] - std_mult * std)
                width.append((upper[-1] - lower[-1]) / middle[i] if middle[i] > 0 else 0)

        return {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "width": width,
            "latest_upper": upper[-1] if upper and not np.isnan(upper[-1]) else None,
            "latest_middle": middle[-1] if middle and not np.isnan(middle[-1]) else None,
            "latest_lower": lower[-1] if lower and not np.isnan(lower[-1]) else None,
            "latest_width": width[-1] if width and not np.isnan(width[-1]) else None,
        }

    def generate_signal(self, prices: List[float]) -> IndicatorResult:
        """生成信号"""
        result = self.calculate(prices)
        upper = result.get("latest_upper")
        middle = result.get("latest_middle")
        lower = result.get("latest_lower")
        current_price = prices[-1] if prices else None

        if upper is None or lower is None or current_price is None:
            return IndicatorResult(
                name="BOLL",
                value=0,
                signal=SignalType.HOLD,
                strength=0,
            )

        # 计算位置
        boll_position = (current_price - lower) / (upper - lower) if upper != lower else 0.5

        # 信号判断
        if current_price < lower:
            signal = SignalType.STRONG_BUY
            strength = 0.9
        elif current_price > upper:
            signal = SignalType.STRONG_SELL
            strength = 0.9
        elif boll_position < 0.2:
            signal = SignalType.BUY
            strength = 0.6
        elif boll_position > 0.8:
            signal = SignalType.SELL
            strength = 0.6
        else:
            signal = SignalType.HOLD
            strength = 0.3

        return IndicatorResult(
            name="BOLL",
            value=boll_position,
            signal=signal,
            strength=strength,
            metadata={
                "upper": upper,
                "middle": middle,
                "lower": lower,
                "width": result.get("latest_width"),
            },
        )


# ============ RSI指标 ============

class RSIIndicator:
    """RSI相对强弱指标"""

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

    def calculate(self, prices: List[float]) -> Dict[str, Any]:
        """计算RSI"""
        period = self.config.rsi_period

        if len(prices) < period + 1:
            return {"rsi": [], "latest_rsi": None}

        # 计算价格变化
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]

        # 分离涨跌
        gains = [c if c > 0 else 0 for c in changes]
        losses = [-c if c < 0 else 0 for c in changes]

        # 计算平均涨跌
        avg_gains = []
        avg_losses = []

        # 初始平均
        if len(gains) >= period:
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            avg_gains.append(avg_gain)
            avg_losses.append(avg_loss)

            # 后续使用EMA
            for i in range(period, len(gains)):
                avg_gain = (avg_gains[-1] * (period - 1) + gains[i]) / period
                avg_loss = (avg_losses[-1] * (period - 1) + losses[i]) / period
                avg_gains.append(avg_gain)
                avg_losses.append(avg_loss)

        # 计算RSI
        rsi = []
        for ag, al in zip(avg_gains, avg_losses):
            if al == 0:
                rsi.append(100 if ag > 0 else 50)
            else:
                rs = ag / al
                rsi.append(100 - 100 / (1 + rs))

        # 填充前面的NaN
        rsi_full = [np.nan] * (period) + rsi

        return {
            "rsi": rsi_full,
            "latest_rsi": rsi[-1] if rsi else None,
        }

    def generate_signal(self, prices: List[float]) -> IndicatorResult:
        """生成信号"""
        result = self.calculate(prices)
        rsi = result.get("latest_rsi")

        if rsi is None:
            return IndicatorResult(
                name="RSI",
                value=0,
                signal=SignalType.HOLD,
                strength=0,
            )

        # 超买超卖判断
        if rsi < 30:
            signal = SignalType.STRONG_BUY
            strength = (30 - rsi) / 30
        elif rsi > 70:
            signal = SignalType.STRONG_SELL
            strength = (rsi - 70) / 30
        elif rsi < 40:
            signal = SignalType.BUY
            strength = 0.5
        elif rsi > 60:
            signal = SignalType.SELL
            strength = 0.5
        else:
            signal = SignalType.HOLD
            strength = 0.3

        return IndicatorResult(
            name="RSI",
            value=rsi,
            signal=signal,
            strength=strength,
        )


# ============ ATR指标 ============

class ATRIndicator:
    """ATR真实波动幅度"""

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

    def calculate(
        self,
        high: List[float],
        low: List[float],
        close: List[float],
    ) -> Dict[str, Any]:
        """计算ATR"""
        period = self.config.atr_period

        if len(close) < period + 1:
            return {"atr": [], "atr_pct": [], "latest_atr": None}

        # 计算True Range
        tr = []
        for i in range(1, len(close)):
            tr1 = high[i] - low[i]
            tr2 = abs(high[i] - close[i-1])
            tr3 = abs(low[i] - close[i-1])
            tr.append(max(tr1, tr2, tr3))

        # 计算ATR
        atr = []
        if len(tr) >= period:
            # 初始ATR
            initial_atr = np.mean(tr[:period])
            atr.append(initial_atr)

            # 后续ATR
            for i in range(period, len(tr)):
                current_atr = (atr[-1] * (period - 1) + tr[i]) / period
                atr.append(current_atr)

        # ATR百分比
        atr_pct = [a / c * 100 if c > 0 else 0 for a, c in zip(atr, close[period:])]

        # 填充
        atr_full = [np.nan] * period + atr

        return {
            "atr": atr_full,
            "atr_pct": atr_pct,
            "latest_atr": atr[-1] if atr else None,
            "latest_atr_pct": atr_pct[-1] if atr_pct else None,
        }

    def generate_signal(
        self,
        high: List[float],
        low: List[float],
        close: List[float],
    ) -> IndicatorResult:
        """生成信号 - ATR主要用于波动性评估"""
        result = self.calculate(high, low, close)
        atr_pct = result.get("latest_atr_pct")

        if atr_pct is None:
            return IndicatorResult(
                name="ATR",
                value=0,
                signal=SignalType.HOLD,
                strength=0,
            )

        # 波动性判断
        if atr_pct > 5:
            volatility = "high"
            strength = 0.8
        elif atr_pct > 3:
            volatility = "medium"
            strength = 0.5
        else:
            volatility = "low"
            strength = 0.3

        return IndicatorResult(
            name="ATR",
            value=atr_pct,
            signal=SignalType.HOLD,  # ATR不直接生成买卖信号
            strength=strength,
            metadata={"volatility": volatility, "atr_pct": atr_pct},
        )


# ============ 威廉指标 ============

class WRIndicator:
    """威廉指标"""

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

    def calculate(
        self,
        high: List[float],
        low: List[float],
        close: List[float],
    ) -> Dict[str, Any]:
        """计算WR"""
        period = self.config.wr_period

        if len(close) < period:
            return {"wr": [], "latest_wr": None}

        wr = []
        for i in range(len(close)):
            if i < period - 1:
                wr.append(np.nan)
            else:
                high_n = max(high[i-period+1:i+1])
                low_n = min(low[i-period+1:i+1])
                if high_n == low_n:
                    wr.append(-50)
                else:
                    wr.append((high_n - close[i]) / (high_n - low_n) * -100)

        return {
            "wr": wr,
            "latest_wr": wr[-1] if wr and not np.isnan(wr[-1]) else None,
        }

    def generate_signal(
        self,
        high: List[float],
        low: List[float],
        close: List[float],
    ) -> IndicatorResult:
        """生成信号"""
        result = self.calculate(high, low, close)
        wr = result.get("latest_wr")

        if wr is None:
            return IndicatorResult(
                name="WR",
                value=0,
                signal=SignalType.HOLD,
                strength=0,
            )

        # 超买超卖判断 (WR范围: -100 to 0)
        if wr > -20:
            signal = SignalType.STRONG_SELL
            strength = 0.8
        elif wr < -80:
            signal = SignalType.STRONG_BUY
            strength = 0.8
        elif wr > -40:
            signal = SignalType.SELL
            strength = 0.5
        elif wr < -60:
            signal = SignalType.BUY
            strength = 0.5
        else:
            signal = SignalType.HOLD
            strength = 0.3

        return IndicatorResult(
            name="WR",
            value=wr,
            signal=signal,
            strength=strength,
        )


# ============ 成交量指标 ============

class VolumeIndicators:
    """成交量指标"""

    @staticmethod
    def obv(prices: List[float], volumes: List[int]) -> List[float]:
        """OBV能量潮"""
        if len(prices) != len(volumes):
            return []

        obv = [0]
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                obv.append(obv[-1] + volumes[i])
            elif prices[i] < prices[i-1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])

        return obv

    @staticmethod
    def vwap(
        high: List[float],
        low: List[float],
        close: List[float],
        volumes: List[int],
    ) -> List[float]:
        """VWAP成交量加权平均价"""
        if not close or not volumes:
            return []

        vwap = []
        cumulative_tp_volume = 0
        cumulative_volume = 0

        for h, l, c, v in zip(high, low, close, volumes):
            typical_price = (h + l + c) / 3
            cumulative_tp_volume += typical_price * v
            cumulative_volume += v
            vwap.append(cumulative_tp_volume / cumulative_volume if cumulative_volume > 0 else 0)

        return vwap

    @staticmethod
    def volume_ma(volumes: List[int], period: int = 20) -> List[float]:
        """成交量移动平均"""
        return BaseIndicators.ma(volumes, period)


# ============ 综合指标分析器 ============

class TechnicalAnalyzer:
    """综合技术分析器"""

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

        self._macd = MACDIndicator(self.config)
        self._kdj = KDJIndicator(self.config)
        self._boll = BOLLIndicator(self.config)
        self._rsi = RSIIndicator(self.config)
        self._atr = ATRIndicator(self.config)
        self._wr = WRIndicator(self.config)

    def analyze(
        self,
        open_prices: List[float],
        high: List[float],
        low: List[float],
        close: List[float],
        volumes: List[int] = None,
    ) -> Dict[str, Any]:
        """综合分析"""
        results = {}

        # 价格指标
        results["macd"] = self._macd.calculate(close)
        results["kdj"] = self._kdj.calculate(high, low, close)
        results["boll"] = self._boll.calculate(close)
        results["rsi"] = self._rsi.calculate(close)
        results["atr"] = self._atr.calculate(high, low, close)
        results["wr"] = self._wr.calculate(high, low, close)

        # 移动平均线
        for period in self.config.ma_periods:
            results[f"ma{period}"] = BaseIndicators.ma(close, period)

        # 成交量指标
        if volumes:
            results["obv"] = VolumeIndicators.obv(close, volumes)
            results["vwap"] = VolumeIndicators.vwap(high, low, close, volumes)
            results["volume_ma"] = VolumeIndicators.volume_ma(volumes)

        return results

    def generate_signals(
        self,
        open_prices: List[float],
        high: List[float],
        low: List[float],
        close: List[float],
        volumes: List[int] = None,
    ) -> Dict[str, IndicatorResult]:
        """生成所有信号"""
        signals = {}

        signals["macd"] = self._macd.generate_signal(close)
        signals["kdj"] = self._kdj.generate_signal(high, low, close)
        signals["boll"] = self._boll.generate_signal(close)
        signals["rsi"] = self._rsi.generate_signal(close)
        signals["wr"] = self._wr.generate_signal(high, low, close)

        return signals

    def get_combined_signal(
        self,
        open_prices: List[float],
        high: List[float],
        low: List[float],
        close: List[float],
        volumes: List[int] = None,
        weights: Dict[str, float] = None,
    ) -> IndicatorResult:
        """综合信号"""
        signals = self.generate_signals(open_prices, high, low, close, volumes)

        # 默认权重
        weights = weights or {
            "macd": 0.25,
            "kdj": 0.20,
            "boll": 0.20,
            "rsi": 0.20,
            "wr": 0.15,
        }

        # 计算加权得分
        buy_score = 0
        sell_score = 0
        total_weight = 0

        for name, signal in signals.items():
            weight = weights.get(name, 0.1)
            total_weight += weight

            if signal.signal in [SignalType.BUY, SignalType.STRONG_BUY]:
                buy_score += weight * signal.strength
            elif signal.signal in [SignalType.SELL, SignalType.STRONG_SELL]:
                sell_score += weight * signal.strength

        # 归一化
        if total_weight > 0:
            buy_score /= total_weight
            sell_score /= total_weight

        # 综合判断
        diff = buy_score - sell_score
        if diff > 0.3:
            signal = SignalType.STRONG_BUY
            strength = diff
        elif diff > 0.1:
            signal = SignalType.BUY
            strength = diff
        elif diff < -0.3:
            signal = SignalType.STRONG_SELL
            strength = abs(diff)
        elif diff < -0.1:
            signal = SignalType.SELL
            strength = abs(diff)
        else:
            signal = SignalType.HOLD
            strength = 0.3

        return IndicatorResult(
            name="Combined",
            value=diff,
            signal=signal,
            strength=strength,
            metadata={
                "buy_score": buy_score,
                "sell_score": sell_score,
                "individual_signals": {k: v.to_dict() for k, v in signals.items()},
            },
        )


# ============ 趋势分析 ============

class TrendAnalyzer:
    """趋势分析"""

    @staticmethod
    def identify_trend(
        prices: List[float],
        ma_periods: List[int] = None,
    ) -> TrendType:
        """识别趋势"""
        ma_periods = ma_periods or [5, 10, 20, 60]

        if len(prices) < max(ma_periods):
            return TrendType.SIDEWAYS

        # 计算MA
        mas = {}
        for period in ma_periods:
            ma = BaseIndicators.ma(prices, period)
            if ma:
                mas[period] = ma[-1]

        if not mas:
            return TrendType.SIDEWAYS

        # 判断趋势
        current_price = prices[-1]
        ma_values = list(mas.values())

        # 多头排列: 价格 > MA5 > MA10 > MA20 > MA60
        if current_price > ma_values[0] > ma_values[1] > ma_values[2]:
            return TrendType.UPTREND

        # 空头排列: 价格 < MA5 < MA10 < MA20 < MA60
        if current_price < ma_values[0] < ma_values[1] < ma_values[2]:
            return TrendType.DOWNTREND

        return TrendType.SIDEWAYS

    @staticmethod
    def find_support_resistance(
        prices: List[float],
        window: int = 20,
    ) -> Dict[str, float]:
        """寻找支撑阻力位"""
        if len(prices) < window:
            return {}

        recent = prices[-window:]
        return {
            "support": min(recent),
            "resistance": max(recent),
            "pivot": (max(recent) + min(recent) + recent[-1]) / 3,
        }


# ============ 便捷函数 ============

def calculate_all_indicators(
    open_prices: List[float],
    high: List[float],
    low: List[float],
    close: List[float],
    volumes: List[int] = None,
) -> Dict[str, Any]:
    """计算所有指标"""
    analyzer = TechnicalAnalyzer()
    return analyzer.analyze(open_prices, high, low, close, volumes)


def get_trading_signal(
    open_prices: List[float],
    high: List[float],
    low: List[float],
    close: List[float],
    volumes: List[int] = None,
) -> IndicatorResult:
    """获取交易信号"""
    analyzer = TechnicalAnalyzer()
    return analyzer.get_combined_signal(open_prices, high, low, close, volumes)


def analyze_trend(prices: List[float]) -> TrendType:
    """分析趋势"""
    return TrendAnalyzer.identify_trend(prices)
