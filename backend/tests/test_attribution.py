"""
归因分析和参数优化测试

测试覆盖：
- Brison归因分析计算
- 因子归因
- 成本追踪
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ==================== Brison归因分析测试 ====================

class TestBrisonAttribution:
    """Brison归因分析测试"""

    def test_allocation_effect_calculation(self):
        """测试配置效应计算"""
        from app.strategies.attribution import BrisonAttribution

        # 创建简单的测试数据
        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.4},
            {'date': '2023-01-01', 'code': 'bond2', 'industry': '金融', 'weight': 0.3},
        ])

        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.02},
            {'date': '2023-01-01', 'code': 'bond2', 'return': 0.01},
        ])

        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.3},
            {'date': '2023-01-01', 'industry': '金融', 'weight': 0.35},
        ])

        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.015},
            {'date': '2023-01-01', 'industry': '金融', 'return': 0.01},
        ])

        attribution = BrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        # 测试单因子计算
        effect = attribution.calc_allocation_effect(
            portfolio_weight=0.4,
            benchmark_weight=0.3,
            benchmark_return=0.015,
            total_benchmark_return=0.012,
        )

        # Allocation = (0.4 - 0.3) * (0.015 - 0.012) = 0.1 * 0.003 = 0.0003
        assert effect == pytest.approx(0.0003, rel=0.01)

    def test_selection_effect_calculation(self):
        """测试选择效应计算"""
        from app.strategies.attribution import BrisonAttribution

        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.4},
        ])
        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.02},
        ])
        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.3},
        ])
        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.015},
        ])

        attribution = BrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        effect = attribution.calc_selection_effect(
            portfolio_return=0.02,
            benchmark_return=0.015,
            benchmark_weight=0.3,
        )

        # Selection = 0.3 * (0.02 - 0.015) = 0.0015
        assert effect == pytest.approx(0.0015, rel=0.01)

    def test_interaction_effect_calculation(self):
        """测试交互效应计算"""
        from app.strategies.attribution import BrisonAttribution

        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.4},
        ])
        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.02},
        ])
        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.3},
        ])
        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.015},
        ])

        attribution = BrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        effect = attribution.calc_interaction_effect(
            portfolio_weight=0.4,
            benchmark_weight=0.3,
            portfolio_return=0.02,
            benchmark_return=0.015,
        )

        # Interaction = (0.4 - 0.3) * (0.02 - 0.015) = 0.1 * 0.005 = 0.0005
        assert effect == pytest.approx(0.0005, rel=0.01)


# ==================== 因子归因测试 ====================

class TestFactorAttribution:
    """因子归因分析测试"""

    def test_factor_contribution(self):
        """测试因子贡献计算"""
        from app.strategies.attribution import FactorAttribution

        # 创建组合暴露数据
        portfolio_exposures = pd.DataFrame([
            {'date': '2023-01-01', 'factor': 'momentum', 'exposure': 1.2},
            {'date': '2023-01-01', 'factor': 'value', 'exposure': 0.8},
            {'date': '2023-01-01', 'factor': 'quality', 'exposure': 1.0},
        ])

        # 创建因子收益数据
        factor_returns = pd.DataFrame([
            {'date': '2023-01-01', 'factor': 'momentum', 'return': 0.05},
            {'date': '2023-01-01', 'factor': 'value', 'return': 0.03},
            {'date': '2023-01-01', 'factor': 'quality', 'return': 0.02},
        ])

        attribution = FactorAttribution(factor_returns)

        contribution = attribution.calc_factor_contribution(
            portfolio_exposures, factor_returns
        )

        # 验证结果
        assert contribution is not None
        # momentum贡献 = 1.2 * 0.05 = 0.06
        assert contribution['momentum'] == pytest.approx(0.06, rel=0.01)


# ==================== 成本追踪测试 ====================

class TestCostTracking:
    """成本追踪测试"""

    def test_cost_tracker_init(self):
        """测试成本追踪器初始化"""
        from app.strategies.cost_tracking import CostTracker

        tracker = CostTracker(aum=100000000)
        assert tracker._aum == 100000000

    def test_cost_recording(self):
        """测试成本记录"""
        from app.strategies.cost_tracking import CostTracker

        tracker = CostTracker(aum=100000000)

        tracker.record_trade(
            trade_id='trade_001',
            code='123456',
            action='buy',
            planned_price=100.0,
            actual_price=100.5,
            volume=1000,
            planned_commission=100.0,
            actual_commission=105.0,
            planned_slippage=50.0,
            actual_slippage=75.0,
            planned_impact=30.0,
            actual_impact=40.0,
        )

        assert len(tracker._records) == 1

    def test_get_daily_report(self):
        """测试获取日报告"""
        from app.strategies.cost_tracking import CostTracker

        tracker = CostTracker(aum=100000000)

        # 记录交易
        tracker.record_trade(
            trade_id='trade_001',
            code='123456',
            action='buy',
            planned_price=100.0,
            actual_price=100.5,
            volume=1000,
            planned_commission=100.0,
            actual_commission=105.0,
            planned_slippage=50.0,
            actual_slippage=75.0,
            planned_impact=30.0,
            actual_impact=40.0,
        )

        today = datetime.now().strftime('%Y-%m-%d')
        report = tracker.get_daily_report(today)

        assert report is not None
        # 报告应包含日期和交易计数
        assert 'date' in report or 'buy_trades' in report


# ==================== 交易成本模型测试 ====================

class TestTransactionCostModel:
    """交易成本模型测试（复用现有测试）"""

    def test_cost_model_init(self):
        """测试成本模型初始化"""
        from app.strategies.transaction_cost import TransactionCostModel

        model = TransactionCostModel(aum=100000000)
        assert model.aum == 100000000


# ==================== 运行测试 ====================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])


# ==================== 增强版Brison归因测试 ====================

class TestEnhancedBrisonAttribution:
    """增强版Brison归因分析测试 - 三维交互效应"""

    def test_three_way_interaction_calculation(self):
        """测试三维交互效应计算"""
        from app.strategies.attribution import EnhancedBrisonAttribution

        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.4},
        ])
        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.02},
        ])
        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.3},
        ])
        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.015},
        ])

        attribution = EnhancedBrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        interaction = attribution.calc_three_way_interaction(
            portfolio_weight=0.4,
            benchmark_weight=0.3,
            portfolio_return=0.02,
            benchmark_return=0.015,
            portfolio_timing=0.005,
            benchmark_timing=0.0,
        )

        # 验证结果
        assert interaction is not None
        assert isinstance(interaction.allocation_selection, float)
        assert isinstance(interaction.total_interaction, float)

    def test_allocation_selection_interaction(self):
        """测试配置×选券交互"""
        from app.strategies.attribution import EnhancedBrisonAttribution

        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.5},
        ])
        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.03},
        ])
        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.3},
        ])
        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.015},
        ])

        attribution = EnhancedBrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        interaction = attribution.calc_three_way_interaction(
            portfolio_weight=0.5,
            benchmark_weight=0.3,
            portfolio_return=0.03,
            benchmark_return=0.015,
            portfolio_timing=0.0,
            benchmark_timing=0.0,
        )

        # 配置×选券 = (0.5 - 0.3) * (0.03 - 0.015) = 0.2 * 0.015 = 0.003
        assert interaction.allocation_selection == pytest.approx(0.003, rel=0.01)

    def test_timing_interaction(self):
        """测试时机交互效应"""
        from app.strategies.attribution import EnhancedBrisonAttribution

        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.4},
        ])
        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.02},
        ])
        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.4},
        ])
        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.02},
        ])

        attribution = EnhancedBrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        interaction = attribution.calc_three_way_interaction(
            portfolio_weight=0.4,
            benchmark_weight=0.4,
            portfolio_return=0.02,
            benchmark_return=0.02,
            portfolio_timing=0.01,  # 1%时机收益
            benchmark_timing=0.0,
        )

        # 配置×时机 = (0.4 - 0.4) * 0.01 = 0
        assert interaction.allocation_timing == pytest.approx(0.0, abs=0.0001)

    def test_detailed_report_generation(self):
        """测试详细报告生成"""
        from app.strategies.attribution import EnhancedBrisonAttribution, BrisonAttribution

        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.4},
            {'date': '2023-01-01', 'code': 'bond2', 'industry': '金融', 'weight': 0.3},
        ])
        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.02},
            {'date': '2023-01-01', 'code': 'bond2', 'return': 0.01},
        ])
        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.3},
            {'date': '2023-01-01', 'industry': '金融', 'weight': 0.35},
        ])
        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.015},
            {'date': '2023-01-01', 'industry': '金融', 'return': 0.01},
        ])

        attribution = EnhancedBrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        result = attribution.analyze_period('2023-01-01', '2023-01-01')
        report = attribution.generate_detailed_report(result)

        # 验证报告结构
        assert '增强版Brison归因分析报告' in report
        assert '配置效应' in report
        assert '选券效应' in report
        assert '交互效应' in report

    def test_three_way_effects_zero_timing(self):
        """测试无时机效应时的三维交互"""
        from app.strategies.attribution import EnhancedBrisonAttribution

        portfolio_positions = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'industry': '科技', 'weight': 0.5},
        ])
        portfolio_returns = pd.DataFrame([
            {'date': '2023-01-01', 'code': 'bond1', 'return': 0.02},
        ])
        benchmark_weights = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'weight': 0.5},
        ])
        benchmark_returns = pd.DataFrame([
            {'date': '2023-01-01', 'industry': '科技', 'return': 0.02},
        ])

        attribution = EnhancedBrisonAttribution(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns
        )

        interaction = attribution.calc_three_way_interaction(
            portfolio_weight=0.5,
            benchmark_weight=0.5,
            portfolio_return=0.02,
            benchmark_return=0.02,
            portfolio_timing=0.0,
            benchmark_timing=0.0,
        )

        # 所有效应应为0
        assert interaction.allocation_selection == pytest.approx(0.0, abs=0.0001)
        assert interaction.allocation_timing == pytest.approx(0.0, abs=0.0001)
        assert interaction.selection_timing == pytest.approx(0.0, abs=0.0001)
        assert interaction.three_way == pytest.approx(0.0, abs=0.0001)
