"""
测试 timing_signal_improved 模块的核心逻辑
"""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.strategies.enhanced_timing_model import (
    EnhancedMarketData,
    EnhancedTimingSignal,
    MarketRegime,
)
from app.strategies.timing_signal_improved import (
    TimingSignalImprover,
    batch_calibrate,
)


class TestDataQuality:
    """数据质量评估"""

    def test_default_news_fields_treated_as_missing(self):
        data = EnhancedMarketData(date=date(2024, 1, 1))
        improver = TimingSignalImprover()
        quality = improver._evaluate_data_quality(data)
        # 默认所有硬字段为 NaN，news 字段为 50.0 视为缺失
        assert quality < 0.1

    def test_filled_fields_counted(self):
        data = EnhancedMarketData(
            date=date(2024, 1, 1),
            cb_median_premium=20.0,
            stock_index_change=1.0,
            rsi_14=55.0,
            treasury_10y_yield=2.5,
            policy_signal_score=60.0,  # 偏离 50 才视为有效
        )
        improver = TimingSignalImprover()
        quality = improver._evaluate_data_quality(data)
        assert quality > 0.15


class TestPositionMapping:
    """仓位调整"""

    def test_bullish_raw_position_maintained(self):
        improver = TimingSignalImprover()
        pos = improver._adjust_position(raw_position=0.8, calibrated_score=75.0,
                                        prob=0.7, data_quality=1.0, vol_high=False,
                                        regime=MarketRegime.RANGE)
        assert pos > 0.4

    def test_low_quality_reduces_position(self):
        improver = TimingSignalImprover()
        pos_high = improver._adjust_position(0.8, 75.0, 0.7, 1.0, False, MarketRegime.RANGE)
        pos_low = improver._adjust_position(0.8, 75.0, 0.7, 0.3, False, MarketRegime.RANGE)
        assert pos_low < pos_high

    def test_volatility_filter_reduces_high_position(self):
        improver = TimingSignalImprover()
        pos_normal = improver._adjust_position(0.8, 75.0, 0.7, 1.0, False, MarketRegime.RANGE)
        pos_vol = improver._adjust_position(0.8, 75.0, 0.7, 1.0, True, MarketRegime.RANGE)
        assert pos_vol < pos_normal

    def test_strong_bear_caps_position(self):
        improver = TimingSignalImprover()
        pos = improver._adjust_position(0.8, 40.0, 0.3, 1.0, False, MarketRegime.STRONG_BEAR)
        assert pos <= 0.3


class TestBatchCalibration:
    """批量校准流程"""

    def test_batch_calibrate_runs_without_error(self):
        n = 80
        dates = [date(2024, 1, 1) + pd.Timedelta(days=i) for i in range(n)]
        signals = []
        data_list = []
        closes = []
        for i, d in enumerate(dates):
            raw_score = 50 + 20 * math.sin(i / 10.0)
            sig = EnhancedTimingSignal(
                date=d,
                total_score=raw_score,
                position_ratio=0.5,
                market_regime=MarketRegime.RANGE,
                consensus_score=50.0,
                confidence=0.6,
            )
            data = EnhancedMarketData(
                date=d,
                cb_median_premium=20.0,
                stock_index_change=(1 if i % 2 == 0 else -1),
                rsi_14=50.0,
                policy_signal_score=55.0 if i % 3 == 0 else 50.0,
            )
            signals.append(sig)
            data_list.append(data)
            closes.append(100.0 + i * 0.1)

        results = batch_calibrate(signals, data_list, closes, train_window=40)
        assert len(results) == n
        assert all(0 <= r.final_position <= 1.0 for r in results)

    def test_calibrated_score_differs_from_raw(self):
        """当历史存在可预测模式时，校准分应与原始分不同"""
        n = 100
        dates = [date(2024, 1, 1) + pd.Timedelta(days=i) for i in range(n)]
        signals = []
        data_list = []
        closes = []
        for i, d in enumerate(dates):
            # 构造：高分→上涨，低分→下跌 的模式
            raw_score = 75.0 if i % 5 < 3 else 25.0
            sig = EnhancedTimingSignal(
                date=d,
                total_score=raw_score,
                position_ratio=0.5,
                market_regime=MarketRegime.RANGE,
                consensus_score=raw_score,
                confidence=0.7,
            )
            data = EnhancedMarketData(
                date=d,
                cb_median_premium=20.0,
                stock_index_change=1.5 if raw_score > 50 else -1.5,
                rsi_14=raw_score,
            )
            signals.append(sig)
            data_list.append(data)
            # 高分后+1%，低分后-1%，这样 label 与 raw_score 强相关
            closes.append(100.0 if i == 0 else closes[-1] * (1.01 if raw_score > 60 else 0.99))

        results = batch_calibrate(signals, data_list, closes, train_window=60)
        diffs = [abs(r.calibrated_score - r.raw_score) for r in results[60:]]
        assert np.mean(diffs) > 1.0


class TestNoLookahead:
    """无未来函数"""

    def test_calibration_uses_only_past_data(self):
        improver = TimingSignalImprover(train_window=20, min_train_samples=10)
        n = 30
        dates = [date(2024, 1, 1) + pd.Timedelta(days=i) for i in range(n)]
        for i, d in enumerate(dates):
            sig = EnhancedTimingSignal(
                date=d,
                total_score=50 + i,
                position_ratio=0.5,
                market_regime=MarketRegime.RANGE,
                consensus_score=50.0,
                confidence=0.5,
            )
            data = EnhancedMarketData(date=d, cb_median_premium=20.0)
            improver.calibrate(sig, data, hs300_close=100.0 + i)
            # 第 i 步只能看到 i 条历史（含当前）
            assert len(improver._history) == i + 1
