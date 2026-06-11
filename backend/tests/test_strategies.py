"""
策略模块单元测试

测试覆盖：
- 七维打分策略测试
- 多维度综合择时测试
- 信用评分模型测试
- 交易成本模型测试
- 事件驱动策略测试
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ==================== 七维打分策略测试 ====================

class TestSonggangSevenDimensionStrategy:
    """松岗七维打分策略测试"""

    @pytest.fixture
    def strategy(self):
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy
        return SonggangSevenDimensionStrategy()

    @pytest.fixture
    def sample_data(self):
        """创建测试数据"""
        np.random.seed(42)
        codes = [f"12{str(i).zfill(4)}" for i in range(50)]
        return pd.DataFrame({
            'code': codes,
            'name': [f'测试转债{i}' for i in range(50)],
            'price': np.random.uniform(90, 150, 50),
            'premium_ratio': np.random.uniform(5, 80, 50),
            'volume': np.random.uniform(0.1, 10, 50),
            'dual_low': np.random.uniform(100, 200, 50),
            'change_pct': np.random.uniform(-5, 5, 50),
            'ytm': np.random.uniform(-5, 10, 50),
            'remaining_years': np.random.uniform(0.5, 6, 50),
            'stock_change_pct': np.random.uniform(-3, 3, 50),
            'forced_call_days': np.random.randint(0, 30, 50),
            'date': datetime.now().date(),
        })

    def test_strategy_init(self, strategy):
        """测试策略初始化"""
        assert strategy.name == "松岗七维打分策略"
        assert strategy.STOCK_WEIGHTS['momentum'] == 0.30
        assert strategy.BOND_WEIGHTS['valuation'] == 0.38

    def test_veto_check_pass(self, strategy, sample_data):
        """测试一票否决通过的情况"""
        row = pd.Series({
            'code': '123456',
            'price': 110,
            'premium_ratio': 30,
            'remaining_years': 3,
            'forced_call_days': 0,
            'volume': 1,
            'dual_low': 140,
            'ytm': 2,
        })
        result = strategy._check_veto(row)
        assert result.passed == True
        assert len(result.reasons) == 0

    def test_veto_check_fail_premium(self, strategy, sample_data):
        """测试溢价率过高被否决"""
        row = pd.Series({
            'code': '123456',
            'price': 110,
            'premium_ratio': 120,
            'remaining_years': 3,
            'forced_call_days': 0,
            'volume': 1,
            'dual_low': 140,
            'ytm': 2,
        })
        result = strategy._check_veto(row)
        assert result.passed == False
        assert any('溢价率' in r for r in result.reasons)

    def test_veto_check_fail_remaining(self, strategy, sample_data):
        """测试剩余期限不足被否决"""
        row = pd.Series({
            'code': '123456',
            'price': 110,
            'premium_ratio': 30,
            'remaining_years': 0.3,
            'forced_call_days': 0,
            'volume': 1,
            'dual_low': 140,
            'ytm': 2,
        })
        result = strategy._check_veto(row)
        assert result.passed == False
        assert any('剩余期限' in r for r in result.reasons)

    def test_credit_score_estimation(self, strategy):
        """测试信用评分估算"""
        # 高信用评分
        row_high = pd.Series({
            'price': 120,
            'premium_ratio': 20,
            'ytm': 3,
            'dual_low': 140,
        })
        score_high = strategy._estimate_credit_score(row_high)
        assert score_high >= 80

        # 低信用评分
        row_low = pd.Series({
            'price': 70,
            'premium_ratio': 90,
            'ytm': 15,
            'dual_low': 90,
        })
        score_low = strategy._estimate_credit_score(row_low)
        assert score_low <= 60

    def test_calc_total_score(self, strategy, sample_data):
        """测试综合评分计算"""
        strategy.on_init(sample_data)
        row = sample_data.iloc[0]
        result = strategy._calc_total_score(row, sample_data)

        assert 'total' in result
        assert 'stock_score' in result
        assert 'bond_score' in result
        assert result['total'] <= 100
        assert result['stock_score'] <= 55
        assert result['bond_score'] <= 45

    def test_buffer_status_update(self, strategy):
        """测试缓冲带状态更新"""
        # 在前60名内（rank=50）- 不在缓冲带
        status = strategy._update_buffer_status('123456', 50)
        assert status.in_buffer == False
        assert status.days_above_60 == 1

        # 在缓冲带内（rank=62，60名之外但65名之内）
        status = strategy._update_buffer_status('123456', 62)
        assert status.in_buffer == True
        assert status.days_in_buffer == 1
        assert status.days_below_60 == 1  # 因为62不在前60名内

        # 跌出缓冲带（rank=70，超过65名）
        status = strategy._update_buffer_status('123456', 70)
        assert status.in_buffer == False
        assert status.days_below_60 == 2  # 累积计数

    def test_market_env_detection(self, strategy, sample_data):
        """测试市场环境检测"""
        # 模拟牛市数据
        bull_data = sample_data.copy()
        bull_data['change_pct'] = np.random.uniform(1, 5, 50)
        env = strategy._detect_market_environment(bull_data)
        assert env in ['bull', 'bear', 'neutral']


# ==================== 多维度综合择时测试 ====================

class TestFourFactorTiming:
    """四因子择时模型 V3 (Legacy) 测试"""

    @pytest.fixture
    def timing(self):
        from app.strategies.four_factor_timing import FourFactorTiming
        return FourFactorTiming()

    @pytest.fixture
    def sample_bonds(self):
        np.random.seed(42)
        return pd.DataFrame({
            'premium_ratio': np.random.uniform(10, 50, 100),
        })

    def test_valuation_score_low(self, timing, sample_bonds):
        """测试低估值得满分"""
        sample_bonds['premium_ratio'] = np.random.uniform(5, 18, 100)
        result = timing.calc_valuation_score(sample_bonds)
        assert result['score'] == 40

    def test_valuation_score_high(self, timing, sample_bonds):
        """测试高估值得低分"""
        sample_bonds['premium_ratio'] = np.random.uniform(35, 60, 100)
        result = timing.calc_valuation_score(sample_bonds)
        assert result['score'] == 0

    def test_sentiment_score(self, timing):
        """测试市场情绪评分"""
        # 高情绪
        result = timing.calc_sentiment_score(700)
        assert result['score'] == 25

        # 低情绪
        result = timing.calc_sentiment_score(200)
        assert result['score'] == 0

    def test_liquidity_score(self, timing):
        """测试流动性评分"""
        # 宽松
        result = timing.calc_liquidity_score(2.0)
        assert result['score'] == 20

        # 收紧
        result = timing.calc_liquidity_score(3.5)
        assert result['score'] == 0

    def test_macro_score(self, timing):
        """测试宏观经济评分"""
        # 确认扩张
        result = timing.calc_macro_score(52, 53)
        assert result['score'] == 15

        # 收缩
        result = timing.calc_macro_score(48, 47)
        assert result['score'] == 0

    def test_total_score_calculation(self, timing, sample_bonds):
        """测试综合得分计算"""
        signal = timing.calc_total_score(
            bonds_df=sample_bonds,
            total_volume=500,
            bond_yield_10y=2.3,
            pmi_current=52,
            pmi_prev=53,
        )

        assert 0 <= signal.score <= 100
        assert 0 <= signal.position_limit <= 1
        assert signal.market_env in ['bull', 'bear', 'neutral']

    def test_position_limit_mapping(self, timing):
        """测试仓位上限映射"""
        assert timing.get_position_limit(75) == 0.80
        assert timing.get_position_limit(55) == 0.55
        assert timing.get_position_limit(35) == 0.275
        assert timing.get_position_limit(20) == 0.10


# ==================== 信用评分模型测试 ====================

class TestKMVCreditModel:
    """KMV信用评分模型测试"""

    @pytest.fixture
    def model(self):
        from app.strategies.credit_model import KMVCreditModel
        return KMVCreditModel()

    def test_price_implied_default_healthy(self, model):
        """测试健康转债的价格隐含违约概率"""
        result = model.calc_price_implied_default(
            bond_price=120,
            pure_bond_value=100,
            stock_price=15,
            net_asset_per_share=10,
            market_cap=10000000000,
            total_debt=3000000000,
        )
        assert result['score'] >= 20

    def test_price_implied_default_distressed(self, model):
        """测试困境转债的价格隐含违约概率"""
        result = model.calc_price_implied_default(
            bond_price=70,
            pure_bond_value=95,
            stock_price=3,
            net_asset_per_share=8,
            market_cap=2000000000,
            total_debt=5000000000,
        )
        assert result['score'] < 15

    def test_rating_score(self, model):
        """测试评级评分"""
        assert model.calc_rating_score('AAA')['score'] == 10
        assert model.calc_rating_score('AA+')['score'] == 7
        assert model.calc_rating_score('AA')['score'] == 5
        assert model.calc_rating_score('A+')['score'] == 2

    def test_debt_ratio_score(self, model):
        """测试资产负债率评分"""
        assert model.calc_debt_ratio_score(40)['score'] == 15
        assert model.calc_debt_ratio_score(60)['score'] == 7.5
        assert model.calc_debt_ratio_score(80)['score'] == 0

    def test_current_ratio_score(self, model):
        """测试流动比率评分"""
        assert model.calc_current_ratio_score(2.5)['score'] == 15
        assert model.calc_current_ratio_score(1.5)['score'] == 7.5
        assert model.calc_current_ratio_score(0.8)['score'] == 0

    def test_total_credit_score(self, model):
        """测试综合信用评分"""
        result = model.calc_total_score(
            bond_price=115,
            pure_bond_value=100,
            stock_price=12,
            net_asset_per_share=10,
            market_cap=5000000000,
            total_debt=2000000000,
            rating='AA',
            asset_liability_ratio=55,
            current_ratio=1.8,
            operating_cashflow=800000000,
            interest_bearing_debt=1500000000,
            guarantee_ratio=8,
            pledge_ratio=25,
            industry='电子',
        )

        assert 0 <= result.total_score <= 100
        assert result.grade in ['AAA', 'AA', 'A', 'BBB', 'BB', 'B']
        assert result.risk_level in ['low', 'medium', 'high']


# ==================== 交易成本模型测试 ====================

class TestTransactionCostModel:
    """交易成本模型测试"""

    @pytest.fixture
    def model(self):
        from app.strategies.transaction_cost import TransactionCostModel
        return TransactionCostModel(aum=100000000)

    def test_commission_calculation(self, model):
        """测试佣金计算"""
        cost = model.calc_commission(1000000)
        assert cost == 100  # 万分之一

    def test_slippage_high_liquidity(self, model):
        """测试高流动性滑点"""
        cost, tier = model.calc_slippage(1000000, 15000)  # 1.5亿成交额
        assert tier == 'high'
        assert cost < 1000

    def test_slippage_low_liquidity(self, model):
        """测试低流动性滑点"""
        cost, tier = model.calc_slippage(1000000, 2000)  # 2000万成交额（1000万-5000万区间）
        assert tier == 'low'
        assert cost > 1000

    def test_slippage_blocked(self, model):
        """测试流动性不足禁止交易"""
        cost, tier = model.calc_slippage(1000000, 500)  # 500万成交额
        assert tier == 'blocked'
        assert cost == float('inf')

    def test_market_impact(self, model):
        """测试冲击成本"""
        # 小额交易
        impact = model.calc_market_impact(500000, 50000000)  # 50万/5000万
        assert impact < 5000

        # 大额交易
        impact = model.calc_market_impact(10000000, 50000000)  # 1000万/5000万
        assert impact > 10000

    def test_total_cost(self, model):
        """测试总成本计算"""
        result = model.calc_total_cost(
            trade_amount=1000000,
            daily_volume=10000,  # 1亿
        )

        assert result.total > 0
        assert result.total_ratio > 0
        assert result.commission > 0
        assert result.slippage > 0

    def test_round_trip_cost(self, model):
        """测试往返交易成本"""
        cost = model.estimate_round_trip_cost(
            position_value=1000000,
            daily_volume=10000,
        )
        assert cost > 0


# ==================== 事件驱动策略测试 ====================

class TestEventDrivenStrategy:
    """事件驱动策略测试"""

    @pytest.fixture
    def strategy(self):
        from app.strategies.event_driven import EventDrivenStrategy
        return EventDrivenStrategy()

    @pytest.fixture
    def sample_bond(self):
        return pd.Series({
            'code': '123456',
            'name': '测试转债',
            'price': 105,
            'premium_ratio': 35,
            'dual_low': 140,
            'volume': 2,
            'stock_price': 12,
            'conversion_price': 15,
            'remaining_years': 3,
        })

    def test_downside_probability_model(self, strategy):
        """测试下修概率模型"""
        from app.strategies.event_driven import DownsideProbabilityModel
        model = DownsideProbabilityModel()

        prob = model.calc_probability(
            asset_liability_ratio=75,
            days_to_put=90,
            holder_ratio=25,
            has_downside=True,
        )
        assert prob >= 0.6  # 高概率下修

        prob = model.calc_probability(
            asset_liability_ratio=40,
            days_to_put=500,
            holder_ratio=2,
            has_downside=False,
        )
        assert prob < 0.3  # 低概率下修

    def test_arbitrage_opportunity(self, strategy, sample_bond):
        """测试折价套利机会"""
        # 设置折价
        sample_bond['premium_ratio'] = -3.5

        signal = strategy.check_arbitrage_opportunity(
            sample_bond,
            stock_tradable=True,
            stock_not_st=True,
            stock_not_limit_down=True,
        )

        assert signal is not None
        assert signal.event_type.value == 'arbitrage'
        assert signal.expected_return > 0

    def test_no_arbitrage_when_premium(self, strategy, sample_bond):
        """测试溢价时无套利机会"""
        sample_bond['premium_ratio'] = 20

        signal = strategy.check_arbitrage_opportunity(
            sample_bond,
            stock_tradable=True,
            stock_not_st=True,
            stock_not_limit_down=True,
        )

        assert signal is None


# ==================== 运行测试 ====================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
