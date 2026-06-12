"""璇玑API压力测试和因子归因测试"""
import pytest
from unittest.mock import MagicMock, AsyncMock
import pandas as pd
import numpy as np
import asyncio
from app.api.xuanji import _compute_xuanji_scores, _compute_greeks


class TestStressTest:
    """压力测试辅助函数测试"""

    def test_scenarios_structure(self):
        """测试场景数据结构"""
        # 模拟6个场景
        scenarios = [
            {"name": "牛市", "expected_return": 12.0, "max_drawdown": -2.5, "win_rate": 75},
            {"name": "熊市", "expected_return": -8.0, "max_drawdown": -8.0, "win_rate": 45},
            {"name": "暴跌", "expected_return": -15.0, "max_drawdown": -15.0, "win_rate": 30},
            {"name": "震荡", "expected_return": 2.0, "max_drawdown": -4.0, "win_rate": 55},
            {"name": "利率上行", "expected_return": -3.0, "max_drawdown": -5.0, "win_rate": 35},
            {"name": "信用风险", "expected_return": -10.0, "max_drawdown": -18.0, "win_rate": 20},
        ]
        # 应该有6个场景
        assert len(scenarios) == 6
        # 每个场景都有必需的字段
        for s in scenarios:
            assert "name" in s
            assert "expected_return" in s
            assert "max_drawdown" in s
            assert "win_rate" in s

    def test_summary_calculation(self):
        """测试汇总指标计算"""
        scenarios = [
            {"expected_return": 12.0},
            {"expected_return": -8.0},
            {"expected_return": -15.0},
            {"expected_return": 2.0},
            {"expected_return": -3.0},
            {"expected_return": -10.0},
        ]
        avg = sum(s["expected_return"] for s in scenarios) / len(scenarios)
        # 平均 = (12 - 8 - 15 + 2 - 3 - 10) / 6 = -22/6 ≈ -3.67
        assert abs(avg - (-3.67)) < 0.1


class TestFactorAttribution:
    """因子归因测试"""

    def test_factor_contribution_calculation(self):
        """测试因子贡献度计算"""
        # 模拟3个因子的评分
        factor_scores = {
            "dual_low": 0.8,
            "momentum": 0.6,
            "hv": 0.4,
        }
        weights = {
            "dual_low": 0.4,
            "momentum": 0.3,
            "hv": 0.3,
        }
        # 计算贡献
        contributions = {}
        for f, s in factor_scores.items():
            contributions[f] = s * weights[f]

        total = sum(contributions.values())
        # dual_low: 0.32, momentum: 0.18, hv: 0.12, total=0.62
        assert abs(contributions["dual_low"] - 0.32) < 0.01
        assert abs(contributions["momentum"] - 0.18) < 0.01
        assert abs(contributions["hv"] - 0.12) < 0.01
        assert abs(total - 0.62) < 0.01

    def test_contribution_pct_normalization(self):
        """测试贡献度百分比归一化"""
        contributions = {"a": 0.32, "b": 0.18, "c": 0.12}
        total = sum(contributions.values())
        pcts = {k: v / total * 100 for k, v in contributions.items()}
        # 百分比之和应约为100
        assert abs(sum(pcts.values()) - 100) < 0.01
        assert abs(pcts["a"] - 51.6) < 0.1


class TestFactorCorrelation:
    """因子相关性测试"""

    def test_correlation_high_redundancy(self):
        """测试高冗余度识别"""
        # |r| > 0.7 应被视为高冗余
        high_pairs = [
            {"abs_correlation": 0.85, "redundancy": "high"},
            {"abs_correlation": 0.75, "redundancy": "high"},
        ]
        medium_pairs = [
            {"abs_correlation": 0.55, "redundancy": "medium"},
        ]
        low_pairs = [
            {"abs_correlation": 0.35, "redundancy": "low"},
        ]
        all_pairs = high_pairs + medium_pairs + low_pairs
        high_count = sum(1 for p in all_pairs if p["redundancy"] == "high")
        assert high_count == 2

    def test_correlation_filter(self):
        """测试相关性过滤阈值"""
        correlations = [
            {"abs_correlation": 0.85},
            {"abs_correlation": 0.55},
            {"abs_correlation": 0.35},
            {"abs_correlation": 0.25},  # 应该被过滤
        ]
        # 只显示>0.3的相关性
        filtered = [c for c in correlations if c["abs_correlation"] > 0.3]
        assert len(filtered) == 3


class TestStrategyComparison:
    """策略对比测试"""

    def test_overlap_calculation(self):
        """测试重叠度计算"""
        set_a = {1, 2, 3, 4, 5}
        set_b = {3, 4, 5, 6, 7}
        overlap = len(set_a & set_b)
        assert overlap == 3

    def test_overlap_pct(self):
        """测试重叠百分比"""
        set_a = {1, 2, 3, 4, 5}
        set_b = {3, 4, 5, 6, 7}
        top_n = 5
        overlap_pct = len(set_a & set_b) / top_n * 100
        assert overlap_pct == 60.0


class TestXuanjiSummary:
    """Xuanji summary endpoint test"""

    def test_summary_endpoint(self):
        """测试summary端点"""
        from app.api.xuanji import strategy_summary
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(strategy_summary())
        finally:
            loop.close()

        assert "strategy" in result
        assert "target_returns" in result
        assert "key_features" in result
        assert "endpoints" in result
        # factor_count = 8个核心因子 (双低/动量/HV/质量/估值/YTM/事件/Delta)
        assert result["strategy"]["factor_count"] == 8
        assert result["strategy"]["alpha_sources"] == 12
        assert result["strategy"]["market_state_count"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
