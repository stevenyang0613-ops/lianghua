"""
改进的择时信号后处理器 V2

设计原则：
1. 保留 EnhancedTimingModel 的原始仓位建议（position_ratio）作为基础
2. 通过 ML 校准的置信度来调节原始仓位
3. 波动率过滤和高换手保护作为附加层
4. 只在有明显改进空间时调整，否则保持基线
"""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.strategies.enhanced_timing_model import (
    EnhancedTimingModel,
    EnhancedMarketData,
    EnhancedTimingSignal,
    MarketRegime,
)


@dataclass
class CalibratedTimingSignal:
    date: date
    raw_score: float
    raw_position: float          # 基线原始仓位
    calibrated_score: float      # ML 校准后得分 0-100
    final_position: float        # 最终仓位 0-1
    confidence: float            # ML 模型置信度 0-1
    regime: MarketRegime
    vol_filter: bool             # 高波动过滤生效
    data_quality: float          # 数据质量 0-1
    reason: str


class TimingSignalImprover:
    """择时信号增强器 V2"""

    DEFAULT_NEUTRAL_FIELDS = {
        "policy_signal_score",
        "event_impact_score",
        "industry_cycle_score",
    }

    def __init__(
        self,
        base_model: Optional[EnhancedTimingModel] = None,
        train_window: int = 120,
        min_train_samples: int = 60,
        vol_atr_window: int = 20,
        vol_atr_percentile: float = 80.0,
        tx_cost: float = 0.001,
        l2_reg: float = 1.0,
        # 仓位调整参数
        min_quality_for_full: float = 0.4,
        vol_reduction_factor: float = 0.5,
        confidence_threshold: float = 0.45,
    ):
        self.base_model = base_model or EnhancedTimingModel()
        self.train_window = train_window
        self.min_train_samples = min_train_samples
        self.vol_atr_window = vol_atr_window
        self.vol_atr_percentile = vol_atr_percentile
        self.tx_cost = tx_cost
        self.l2_reg = l2_reg
        self.min_quality_for_full = min_quality_for_full
        self.vol_reduction_factor = vol_reduction_factor
        self.confidence_threshold = confidence_threshold

        self._history: List[Dict[str, Any]] = []
        self._scaler = StandardScaler()
        self._clf = LogisticRegression(
            C=1.0 / l2_reg if l2_reg > 0 else 1.0,
            max_iter=1000,
            class_weight="balanced",
            solver="lbfgs",
        )
        self._last_calibrated: Optional[CalibratedTimingSignal] = None
        self._last_final_pos: Optional[float] = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def calibrate(
        self,
        raw_signal: EnhancedTimingSignal,
        data: EnhancedMarketData,
        hs300_close: Optional[float] = None,
    ) -> CalibratedTimingSignal:
        # 1. 数据质量
        data_quality = self._evaluate_data_quality(data)

        # 2. 记录历史
        record = self._record(raw_signal, data, hs300_close)
        self._history.append(record)
        if len(self._history) > self.train_window * 3:
            self._history = self._history[-self.train_window * 3:]

        # 3. ML 校准方向置信度
        calibrated_score, prob = self._ml_calibrate(raw_signal)

        # 4. 波动率过滤
        vol_high = self._is_high_vol(hs300_close) if self.vol_atr_window else False

        # 5. 从基线位置出发，做分层调整
        final_pos = self._adjust_position(
            raw_position=raw_signal.position_ratio,
            calibrated_score=calibrated_score,
            prob=prob,
            data_quality=data_quality,
            vol_high=vol_high,
            regime=raw_signal.market_regime,
        )

        reason = self._build_reason(raw_signal, calibrated_score, prob, data_quality, vol_high)

        result = CalibratedTimingSignal(
            date=raw_signal.date,
            raw_score=raw_signal.total_score,
            raw_position=raw_signal.position_ratio,
            calibrated_score=calibrated_score,
            final_position=final_pos,
            confidence=round(prob, 4),
            regime=raw_signal.market_regime,
            vol_filter=vol_high,
            data_quality=round(data_quality, 4),
            reason=reason,
        )
        self._last_calibrated = result
        self._last_final_pos = final_pos
        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _evaluate_data_quality(self, data: EnhancedMarketData) -> float:
        """评估有效数据占比"""
        fields = [
            "cb_median_premium", "cb_median_price", "cb_avg_daily_amount", "cb_count",
            "stock_index_change", "stock_index_change_20d", "rsi_14", "bollinger_position",
            "treasury_10y_yield", "shibor_overnight", "pmi", "cpi", "ppi", "m2_growth",
            "advance_decline_ratio", "vix_index", "north_bound_net_flow", "margin_balance_change",
        ]
        valid = sum(
            1 for f in fields
            if getattr(data, f, None) is not None and not (isinstance(getattr(data, f), float) and math.isnan(getattr(data, f)))
        )
        for f in self.DEFAULT_NEUTRAL_FIELDS:
            v = getattr(data, f, 50.0)
            if v != 50.0:
                valid += 1
        total = len(fields) + len(self.DEFAULT_NEUTRAL_FIELDS)
        return valid / total if total > 0 else 0.0

    def _record(self, signal: EnhancedTimingSignal, data: EnhancedMarketData, close: Optional[float]) -> Dict:
        return {
            "date": signal.date,
            "raw_score": signal.total_score,
            "raw_position": signal.position_ratio,
            "regime": signal.market_regime.value,
            "consensus_score": signal.consensus_score,
            "confidence": signal.confidence,
            "data_quality": self._evaluate_data_quality(data),
            "hs300_close": close,
        }

    def _ml_calibrate(self, raw_signal: EnhancedTimingSignal) -> Tuple[float, float]:
        """滚动逻辑回归校准，返回 (校准分0-100, 上涨概率)"""
        if len(self._history) < self.min_train_samples:
            return round(raw_signal.total_score, 2), raw_signal.total_score / 100.0

        df = pd.DataFrame(self._history).copy()
        df["future_ret"] = df["hs300_close"].shift(-1) / df["hs300_close"] - 1
        df["label"] = (df["future_ret"] > 0).astype(int)

        train = df.dropna(subset=["future_ret", "raw_score"]).tail(self.train_window)
        if len(train) < self.min_train_samples:
            return round(raw_signal.total_score, 2), raw_signal.total_score / 100.0

        # 特征：原始分 + 共识分 + 历史准确率趋势
        X = train[["raw_score", "consensus_score", "confidence"]].copy()
        X["raw_sq"] = X["raw_score"] ** 2
        X["raw_z"] = (X["raw_score"] - X["raw_score"].mean()) / (X["raw_score"].std() + 1e-9)
        X = X.fillna(0).values
        y = train["label"].values

        try:
            X_scl = self._scaler.fit_transform(X)
            self._clf.fit(X_scl, y)

            cur = np.array([[
                raw_signal.total_score,
                raw_signal.consensus_score,
                raw_signal.confidence,
                raw_signal.total_score ** 2,
                (raw_signal.total_score - train["raw_score"].mean()) / (train["raw_score"].std() + 1e-9),
            ]])
            cur_scl = self._scaler.transform(cur)
            prob = self._clf.predict_proba(cur_scl)[0][1]

            # 校准分：保守映射，只在 ML 有把握时偏离中性
            calibrated = 50.0 + (prob - 0.5) * 100.0 * min(1.0, max(0.3, len(train) / self.train_window))
            return round(max(0, min(100, calibrated)), 2), round(prob, 4)
        except Exception:
            return round(raw_signal.total_score, 2), raw_signal.total_score / 100.0

    def _is_high_vol(self, close: Optional[float]) -> bool:
        if close is None:
            return False
        prices = [r["hs300_close"] for r in self._history if r.get("hs300_close")]
        if len(prices) < self.vol_atr_window + 5:
            return False
        s = pd.Series(prices)
        atr = s.diff().abs().rolling(self.vol_atr_window).mean().iloc[-1]
        med = s.diff().abs().rolling(self.vol_atr_window).mean().median()
        if pd.isna(atr) or pd.isna(med) or med == 0:
            return False
        return atr > med * (self.vol_atr_percentile / 50.0)

    def _adjust_position(
        self,
        raw_position: float,
        calibrated_score: float,
        prob: float,
        data_quality: float,
        vol_high: bool,
        regime: MarketRegime,
    ) -> float:
        """
        分层调整仓位：
        - 从基线的 position_ratio 出发
        - 质量折扣：数据质量低时减少仓位
        - 置信度阈值：ML 没把握时保持中性
        - 高波动过滤：额外减仓
        - 极端 regime：硬限制
        """
        pos = raw_position

        # 1. 数据质量折扣（线性减仓）
        if data_quality < self.min_quality_for_full and self.min_quality_for_full > 0:
            quality_ratio = data_quality / self.min_quality_for_full
            pos = 0.5 + (pos - 0.5) * max(0.1, quality_ratio)

        # 2. ML 置信度调节：confidence 低时向 0.5 收缩
        if prob < self.confidence_threshold and self.confidence_threshold > 0:
            conf_ratio = prob / self.confidence_threshold
            pos = 0.5 + (pos - 0.5) * conf_ratio

        # 3. 方向修正：如果 ML 信号与原始信号相反且置信度高
        ml_dir = 1 if calibrated_score > 50 else (-1 if calibrated_score < 50 else 0)
        raw_dir = 1 if raw_position > 0.5 else (-1 if raw_position < 0.5 else 0)
        if ml_dir != 0 and raw_dir != 0 and ml_dir != raw_dir and prob > 0.6:
            # ML 与基线方向相反且有把握 → 向中性靠拢而非完全反转
            pos = 0.5 + (pos - 0.5) * 0.5  # 减半方向信号

        # 4. 高波动过滤
        if vol_high:
            # 只在高仓位时减仓，低位不继续减
            if pos > 0.5:
                pos = 0.5 + (pos - 0.5) * self.vol_reduction_factor

        # 5. 极端 regime 保护
        if regime in (MarketRegime.STRONG_BEAR,):
            pos = min(pos, 0.3)
        elif regime in (MarketRegime.STRONG_BULL,):
            pos = max(pos, 0.6)

        # 6. 交易成本保护：小变化不执行
        if self._last_final_pos is not None:
            change = abs(pos - self._last_final_pos)
            if change < self.tx_cost * 3:
                pos = self._last_final_pos

        return round(max(0.0, min(1.0, pos)), 4)

    def _build_reason(self, raw: EnhancedTimingSignal, cal_score: float,
                      prob: float, quality: float, vol: bool) -> str:
        parts = [
            f"基线分 {raw.total_score:.0f} → 校准分 {cal_score:.0f}",
            f"置信度 {prob:.0%}",
            f"数据质量 {quality:.0%}",
        ]
        if vol:
            parts.append("高波动过滤")
        return "; ".join(parts)


def batch_calibrate(
    signals: List[EnhancedTimingSignal],
    data_list: List[EnhancedMarketData],
    closes: List[float],
    **kwargs,
) -> List[CalibratedTimingSignal]:
    improver = TimingSignalImprover(**kwargs)
    results = []
    for sig, data, close in zip(signals, data_list, closes):
        results.append(improver.calibrate(sig, data, close))
    return results
