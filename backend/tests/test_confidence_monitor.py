"""
置信度分布退化检测器 测试

验证 ConfidenceMonitor 的正确性：
- PSI 计算的数值正确性
- 分布偏移检测
- 冷启动行为
- 重置/告警功能
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import math
import pytest
from app.strategies.confidence_monitor import (
    ConfidenceMonitor,
    CONFIDENCE_BUCKETS,
    PSI_NO_CHANGE,
    PSI_MODERATE,
)


class TestBucketDistribution:
    def test_empty_returns_zeros(self):
        dist = ConfidenceMonitor._bucket_distribution([])
        assert len(dist) == len(CONFIDENCE_BUCKETS) - 1
        assert all(d == 0.0 for d in dist)

    def test_all_high_confidence(self):
        """所有值都在 0.95-1.0 区间"""
        dist = ConfidenceMonitor._bucket_distribution([0.99, 0.98, 0.96])
        # 最后一个桶应该是 100%
        assert abs(dist[-1] - 100.0) < 1e-6

    def test_mixed_distribution(self):
        """混合值分布在多个桶"""
        vals = [0.1, 0.5, 0.8, 0.99]
        dist = ConfidenceMonitor._bucket_distribution(vals)
        assert len(dist) == 4
        # 每个桶应该恰好有 1 个值（25%）
        for d in dist:
            assert abs(d - 25.0) < 1e-6


class TestPSICalculation:
    def test_identical_distributions(self):
        """相同分布 → PSI = 0"""
        dist = [25.0, 25.0, 25.0, 25.0]
        psi = ConfidenceMonitor._psi(dist, dist)
        assert abs(psi) < 1e-6

    def test_different_distributions(self):
        """不同分布 → PSI > 0"""
        dist1 = [25.0, 25.0, 25.0, 25.0]
        dist2 = [100.0, 0.0, 0.0, 0.0]
        psi = ConfidenceMonitor._psi(dist1, dist2)
        assert psi > 0.1

    def test_no_nan_on_zero_expected(self):
        """即使 expected=0 也不产生 NaN"""
        dist1 = [0.0, 0.0, 100.0, 0.0]
        dist2 = [0.0, 100.0, 0.0, 0.0]
        psi = ConfidenceMonitor._psi(dist1, dist2)
        assert not math.isnan(psi)
        assert psi > 0


class TestConfidenceMonitor:
    def test_initial_health_score_is_1(self):
        """冷启动阶段 health_score 应为 1.0"""
        monitor = ConfidenceMonitor()
        assert monitor.health_score == 1.0

    def test_cold_start_no_alert(self):
        """冷启动阶段无告警"""
        monitor = ConfidenceMonitor()
        for _ in range(3):
            monitor.update([0.9, 0.85, 0.95])
        assert monitor.get_alert() is None

    def test_stable_confidence_no_alert(self):
        """置信度持续稳定 → 无告警"""
        monitor = ConfidenceMonitor(window=20)
        # 填充参考分布
        for _ in range(20):
            monitor.update([0.9, 0.85, 0.95, 0.88])

        # 再更新相同的分布
        for _ in range(5):
            monitor.update([0.9, 0.85, 0.95, 0.88])

        alert = monitor.get_alert()
        assert alert is None or alert['psi'] < PSI_MODERATE

    def test_degradation_detected(self):
        """置信度从高变低 → 触发告警"""
        monitor = ConfidenceMonitor(window=20)

        # 阶段1：填充高置信度参考分布
        for _ in range(20):
            monitor.update([0.90, 0.85, 0.95, 0.88, 0.92])

        # 阶段2：突然所有置信度降到 0（数据缺失）
        for _ in range(5):
            monitor.update([0.0, 0.0, 0.0, 0.0, 0.0])

        alert = monitor.get_alert()
        assert alert is not None
        assert "confidence_degradation" in alert['type']
        assert alert['psi'] > PSI_MODERATE

    def test_psi_property(self):
        """psi 属性在冷启动后返回正确值"""
        monitor = ConfidenceMonitor(window=20)

        # 冷启动期间 psi 为 None
        assert monitor.psi is None

        # 填充后应有值
        for _ in range(25):
            monitor.update([0.9, 0.85, 0.95, 0.88])
        assert monitor.psi is not None
        assert monitor.psi >= 0

    def test_reset_clears_state(self):
        """reset() 后恢复到初始状态"""
        monitor = ConfidenceMonitor(window=60)
        # 填充 30 轮 * 5 因子 = 150 值（远超 50 阈值）
        for _ in range(30):
            monitor.update([0.9, 0.85, 0.88, 0.92, 0.95])
        # 健康的，不应该告警
        assert monitor.get_alert() is None

        # 突然退化
        for _ in range(10):
            monitor.update([0.0, 0.0, 0.0, 0.0, 0.0])
        assert monitor.get_alert() is not None

        monitor.reset()
        assert monitor.health_score == 1.0
        assert monitor.psi is None
        assert monitor.get_alert() is None
        assert monitor.alert_days == 0

    def test_alert_days_counting(self):
        """连续告警天数计数正常"""
        monitor = ConfidenceMonitor(window=60, psi_threshold=0.05)

        # 快速填充参考分布（20 轮 * 5 因子 = 100 值）
        for _ in range(20):
            monitor.update([0.9, 0.95, 0.88, 0.92, 0.85])

        # 触发退化
        monitor.update([0.1, 0.0, 0.05, 0.0, 0.1])
        assert monitor.alert_days >= 1, f"alert_days={monitor.alert_days}"

        # 持续退化
        monitor.update([0.0, 0.0, 0.0, 0.0, 0.0])
        assert monitor.alert_days >= 2, f"alert_days={monitor.alert_days}"

    def test_health_score_decays_with_degradation(self):
        """退化严重时 health_score 应明显下降"""
        monitor = ConfidenceMonitor(window=20)

        # 健康阶段
        for _ in range(20):
            monitor.update([0.9, 0.95, 0.88])

        health_before = monitor.health_score

        # 退化阶段
        for _ in range(10):
            monitor.update([0.0, 0.0, 0.0])

        health_after = monitor.health_score
        assert health_after < health_before
        assert health_after < 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
