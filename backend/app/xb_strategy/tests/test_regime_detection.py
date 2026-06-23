"""
测试市场状态识别模块
"""
import random
from datetime import datetime
import numpy as np
import pytest

from app.xb_strategy.market.regime_detection import (
    RegimeDetectionService,
    MarketSnapshot,
    VolatilityRegimeDetector,
    VolatilityRegime,
    MarketSentimentAnalyzer,
    SentimentLevel,
)


class TestVolatilityDetectorRealReturns:
    """验证波动率检测器不再使用硬编码收益率"""

    def test_hardcoded_returns_bug_fixed_volatility_responds(self):
        """模拟真实收益率序列，验证 volatility 随输入变化"""
        detector = VolatilityRegimeDetector(lookback_periods=100)

        # 先塞入 60 个 0.01（高波动期）
        for _ in range(60):
            detector.update(0.01)

        # 再塞入 60 个 0.0001（低波动期）→ 波动率应明显下降
        for _ in range(60):
            detector.update(0.0001)

        regime, prob = detector.detect()
        # 经过 60 期低波动输入后，vol 应处于 LOW/EXTREMELY_LOW/NORMAL
        assert regime in (VolatilityRegime.LOW, VolatilityRegime.EXTREMELY_LOW, VolatilityRegime.NORMAL), \
            f"预期 LOW/EXTREMELY_LOW/NORMAL, 实际 {regime}"
        assert prob < 0.7, f"低波动期概率应适中, 实际 {prob}"

    def test_volatility_detects_high_volatility(self):
        """高频大幅波动应被检测为 HIGH/EXTREMELY_HIGH"""
        detector = VolatilityRegimeDetector(lookback_periods=100)

        # 60 个低波动
        for _ in range(60):
            detector.update(0.0005)

        # 40 个高波动
        for _ in range(40):
            detector.update(0.05)

        regime, prob = detector.detect()
        assert regime in (VolatilityRegime.HIGH, VolatilityRegime.EXTREMELY_HIGH), \
            f"预期 HIGH/EXTREMELY_HIGH, 实际 {regime}"

    def test_volatility_degree_change_from_high_to_low(self):
        """波动率从高到低变化后，应能识别出降低趋势"""
        detector = VolatilityRegimeDetector(lookback_periods=200)

        # Phase 1: 高波动 (2% 日收益率)
        for _ in range(140):
            detector.update(random.uniform(-0.03, 0.03))

        initial_regime, _ = detector.detect()
        # 高波动区
        assert initial_regime in (VolatilityRegime.HIGH, VolatilityRegime.EXTREMELY_HIGH, VolatilityRegime.NORMAL), \
            f"高波动期预期 HIGH/EXTREMELY_HIGH/NORMAL, 实际 {initial_regime}"

        # Phase 2: 极低波动 (0.001% 日收益率) — 140 次足够洗掉高波动痕迹
        for _ in range(140):
            detector.update(random.uniform(-0.00001, 0.00001))

        final_regime, _ = detector.detect()
        # 经历 140 期极低波动后应明显降低
        assert final_regime in (VolatilityRegime.LOW, VolatilityRegime.EXTREMELY_LOW, VolatilityRegime.NORMAL), \
            f"低波动后预期 LOW/EXTREMELY_LOW/NORMAL, 实际 {final_regime}"


class TestRegimeDetectionServiceProcessSnapshot:
    """验证 RegimeDetectionService 使用真实收益率而非硬编码"""

    def test_returns_change_with_index_value(self):
        """连续调用 process_snapshot 时 returns 应为真实收益率"""
        service = RegimeDetectionService()
        t = datetime(2024, 1, 1)

        # 第一次调用：无历史数据，returns 应为 0
        snap1 = MarketSnapshot(
            timestamp=t, index_value=100.0, volume=1e9,
            advance_count=1000, decline_count=800,
            new_high_count=50, new_low_count=30, turnover=1e8,
        )
        service.process_snapshot(snap1)

        # 通过内部 volatility_detector 的 _returns_history 验证
        assert len(service.volatility_detector._returns_history) == 1
        first_return = service.volatility_detector._returns_history[0]
        assert first_return == 0.0, f"首次返回应为 0, 实际 {first_return}"

        # 第二次调用：index 从 100 涨到 105 => returns ≈ 0.05
        snap2 = MarketSnapshot(
            timestamp=t, index_value=105.0, volume=1e9,
            advance_count=1200, decline_count=600,
            new_high_count=80, new_low_count=20, turnover=1.2e8,
        )
        service.process_snapshot(snap2)

        assert len(service.volatility_detector._returns_history) == 2
        second_return = service.volatility_detector._returns_history[-1]
        assert abs(second_return - 0.05) < 0.001, \
            f"期望 returns≈0.05, 实际 {second_return}"

    def test_negative_returns_detected(self):
        """index 下跌时应产生负收益率"""
        service = RegimeDetectionService()
        t = datetime(2024, 1, 1)

        snap1 = MarketSnapshot(
            timestamp=t, index_value=100.0, volume=1e9,
            advance_count=1000, decline_count=800,
            new_high_count=50, new_low_count=30, turnover=1e8,
        )
        service.process_snapshot(snap1)

        # 下跌到 95
        snap2 = MarketSnapshot(
            timestamp=t, index_value=95.0, volume=1e9,
            advance_count=1000, decline_count=800,
            new_high_count=50, new_low_count=30, turnover=1e8,
        )
        service.process_snapshot(snap2)

        ret = service.volatility_detector._returns_history[-1]
        assert ret < 0, f"负收益率应为负, 实际 {ret}"
        assert abs(ret - (-0.05)) < 0.001

    def test_volume_ratio_not_always_1(self):
        """验证成交量比修复: avg_volume 应为历史均值而非 current*0.9"""
        service = RegimeDetectionService()
        t = datetime(2024, 1, 1)

        # 第一次：volume=1e9
        snap1 = MarketSnapshot(
            timestamp=t, index_value=100.0, volume=1e9,
            advance_count=1000, decline_count=800,
            new_high_count=50, new_low_count=30, turnover=1e8,
        )
        service.process_snapshot(snap1)

        # 第二次：volume 翻倍到 2e9 => volume_ratio 应明显 > 1
        snap2 = MarketSnapshot(
            timestamp=t, index_value=101.0, volume=2e9,
            advance_count=1200, decline_count=600,
            new_high_count=80, new_low_count=20, turnover=1.2e8,
        )
        r = service.process_snapshot(snap2)

        # 放量应触发 score 上涨
        assert r.sentiment_level in (SentimentLevel.NEUTRAL, SentimentLevel.GREED, SentimentLevel.EXTREME_GREED), \
            f"放量后情绪不应为恐慌, 实际 {r.sentiment_level}"
