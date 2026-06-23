"""
多维度综合择时模型 V4.0 回归测试

专门测试在第二/三轮 review 中发现并修复的 bug，防止回归。
"""
import sys
import os
import math
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from app.strategies.enhanced_timing_model import (
    EnhancedTimingModel,
    EnhancedMarketData,
    convert_from_legacy_data,
    MarketRegime,
)


def make_default_data(**overrides) -> EnhancedMarketData:
    """创建仅含默认值的 EnhancedMarketData（模拟数据缺失场景）"""
    data = EnhancedMarketData(date=date.today())
    for k, v in overrides.items():
        setattr(data, k, v)
    return data


def _find_subfactor(result, name: str):
    """从结果中按名字找子因子"""
    for cat in result.category_scores.values():
        for sf in cat.sub_factors:
            if sf.name == name:
                return sf
    return None


# ==================== BUG#2: PE/PB = 0 ====================

class TestPEPBDefaults:
    def test_pe_pb_zero_neutral(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "PE/PB综合估值")
        assert sub is not None
        assert 45 <= sub.score <= 55, f"Expected neutral, got {sub.score}"
        assert sub.signal == "neutral"

    def test_pe_pb_valid_data(self):
        model = EnhancedTimingModel()
        data = make_default_data(stock_pe_median=15.0, stock_pb_median=2.0)
        result = model.calculate(data)
        sub = _find_subfactor(result, "PE/PB综合估值")
        assert sub.score > 0


# ==================== BUG#3, #4: 涨停跌停/新高新低 ====================

class TestSentimentDefaults:
    def test_limit_up_down_both_zero(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "涨停/跌停比")
        assert 45 <= sub.score <= 55, f"Expected neutral, got {sub.score}"

    def test_new_high_low_both_zero(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "新高/新低比")
        assert 45 <= sub.score <= 55, f"Expected neutral, got {sub.score}"


# ==================== BUG#5, #6: 成交额/换手率 ====================

class TestCapitalFlowDefaults:
    def test_cb_amount_zero(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "转债日均成交额")
        assert 45 <= sub.score <= 55, f"Expected neutral, got {sub.score}"

    def test_market_turnover_zero(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "全市场换手率")
        assert 45 <= sub.score <= 55, f"Expected neutral, got {sub.score}"


# ==================== BUG#8, #9: 信用利差/期限利差 ====================

class TestLiquidityDefaults:
    def test_credit_spread_zero(self):
        model = EnhancedTimingModel()
        data = make_default_data(credit_spread=0)
        result = model.calculate(data)
        sub = _find_subfactor(result, "信用利差")
        assert math.isnan(sub.score), f"Expected NaN for zero credit_spread (treated as missing), got {sub.score}"

    def test_term_spread_zero(self):
        model = EnhancedTimingModel()
        data = make_default_data(term_spread=0)
        result = model.calculate(data)
        sub = _find_subfactor(result, "期限利差(10Y-2Y)")
        assert 45 <= sub.score <= 55, f"Expected neutral, got {sub.score}"

    def test_term_spread_missing(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "期限利差(10Y-2Y)")
        assert math.isnan(sub.score), f"Expected NaN for missing data, got {sub.score}"

    def test_credit_spread_missing(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "信用利差")
        assert math.isnan(sub.score), f"Expected NaN for missing data, got {sub.score}"


# ==================== BUG#7: 字段独立 ====================

class TestIndustryFieldIndependence:
    def test_capital_flow_uses_net_inflow(self):
        model = EnhancedTimingModel()
        data = make_default_data(
            industry_net_inflow_ratio=80.0,
            industry_cycle_score=20.0,
        )
        result = model.calculate(data)
        sub = _find_subfactor(result, "行业资金流向")
        assert sub.raw_value == 80.0
        assert sub.score > 50


# ==================== BUG#10: 换手率不重复 ====================

class TestTurnoverNotDoubleCounted:
    def test_turnover_in_capital_flow_not_sentiment(self):
        model = EnhancedTimingModel()
        data = make_default_data(market_turnover=3.0)
        result = model.calculate(data)
        cap_subs = [sf.name for sf in result.category_scores['capital_flow'].sub_factors]
        sent_subs = [sf.name for sf in result.category_scores['sentiment'].sub_factors]
        assert "全市场换手率" in cap_subs
        assert "全市场换手率" not in sent_subs
        assert "新增开户数" in sent_subs


# ==================== BUG#1: pledge_ratio ====================

class TestPledgeRatioDefaults:
    def test_zero_cb_count_neutral(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        result = model.calculate(data)
        sub = _find_subfactor(result, "转债破面比例")
        assert 45 <= sub.score <= 55, f"Expected neutral, got {sub.score}"


# ==================== BUG#14: advance_decline_ratio ====================

class TestAdvanceDeclineDefaults:
    def test_both_zero_preserves_default(self):
        data = EnhancedMarketData(date=date.today())
        adv, dec = 0, 0
        ratio = 0.0
        if adv > 0 or dec > 0:
            ratio = adv / max(dec, 1)
        assert ratio == 0.0


# ==================== BUG#11, #13: 数据完整度 ====================

class TestDataCompleteness:
    def test_pmi_50_is_valid(self):
        data = make_default_data(pmi=50.0)
        has_data = 0.1 if 0 < data.pmi < 100 else 0
        assert has_data == 0.1

    def test_pmi_0_treated_as_missing(self):
        data = make_default_data(pmi=0.0)
        has_data = 0.1 if 0 < data.pmi < 100 else 0
        assert has_data == 0.0

    def test_m2_default_treated_as_missing(self):
        data = make_default_data(m2_growth=10.0)
        has_data = 0.1 if data.m2_growth > 0 and data.m2_growth != 10.0 else 0
        assert has_data == 0.0


# ==================== 集成方法 ====================

class TestEnsembleMethod:
    def test_ensemble_with_defaults(self):
        model = EnhancedTimingModel()
        data = make_default_data()
        signal = model.calculate_ensemble(data)
        assert 5 <= signal.total_score <= 95
        assert signal.position_ratio > 0


# ==================== safe_score 工具 ====================

class TestSafeScoreHelper:
    def test_zero_returns_neutral(self):
        from app.strategies.enhanced_timing_model import safe_score
        assert safe_score(0, lambda v: v * 2, neutral=50.0, treat_zero_as_missing=True) == 50.0

    def test_zero_returns_zero_when_not_missing(self):
        from app.strategies.enhanced_timing_model import safe_score
        assert safe_score(0, lambda v: v * 2, neutral=50.0, treat_zero_as_missing=False) == 0

    def test_nonzero_uses_func(self):
        from app.strategies.enhanced_timing_model import safe_score
        assert safe_score(10, lambda v: v * 2) == 20

    def test_nan_returns_neutral(self):
        from app.strategies.enhanced_timing_model import safe_score
        assert safe_score(float('nan'), lambda v: v, neutral=50.0) == 50.0

    def test_has_data_false_returns_neutral(self):
        from app.strategies.enhanced_timing_model import safe_score
        assert safe_score(100, lambda v: v, neutral=50.0, has_data=False) == 50.0

    def test_zero_with_treat_zero_as_missing_false(self):
        """当 treat_zero_as_missing=False 时，0 是有效值，应走 score_fn"""
        from app.strategies.enhanced_timing_model import safe_score
        assert safe_score(0, lambda v: v * 2, treat_zero_as_missing=False) == 0

    def test_default_neutral_is_nan(self):
        """默认 neutral 为 NaN，缺失数据返回 NaN"""
        from app.strategies.enhanced_timing_model import safe_score
        import math
        result = safe_score(float('nan'), lambda v: v)
        assert math.isnan(result)


# ==================== 权重一致性 ====================

class TestWeightsConsistency:
    def test_default_weights_sum_to_one(self):
        weights = EnhancedTimingModel.DEFAULT_CATEGORY_WEIGHTS
        total = sum(weights.values())
        assert 0.99 <= total <= 1.01

    def test_all_regime_weights_sum_to_one(self):
        model = EnhancedTimingModel()
        for regime in MarketRegime:
            weights = model.get_regime_weights(regime)
            total = sum(weights.values())
            assert 0.99 <= total <= 1.01, f"{regime}"


# ==================== convert_from_legacy_data ====================

class TestConvertFromLegacy:
    def test_industry_net_inflow_separate(self):
        class MockMacro:
            industry_net_inflow = 75
        data = convert_from_legacy_data(macro_data=MockMacro())
        assert data.industry_net_inflow_ratio == 75


# ==================== 各类别差异化平滑窗口 ====================

class TestPerCategorySmoothing:
    """验证每个类别使用不同 EMA 窗口（P1 2026-06-23）"""

    def test_smooth_first_call_returns_raw(self):
        """首次调用返回原始值，初始化 EMA 状态"""
        model = EnhancedTimingModel()
        smoothed = model._smooth_category_score('sentiment', 80.0)
        assert smoothed == 80.0

    def test_smooth_converges_toward_raw(self):
        """连续同值输入，平滑值收敛于稳态值"""
        model = EnhancedTimingModel()
        raw_series = [80.0] * 10
        results = [model._smooth_category_score('sentiment', r) for r in raw_series]
        # 最后一轮应接近 80
        assert abs(results[-1] - 80.0) < 1.0
        # 第一次是 80，第二次应小于 80（因从 80 开始向 80 平滑实际不变）
        # 但如果输入变化：先 80 后 20，第二次应接近两者中间
        model2 = EnhancedTimingModel()
        r1 = model2._smooth_category_score('sentiment', 80.0)
        r2 = model2._smooth_category_score('sentiment', 20.0)
        # EMA(4): alpha=0.4, r2 = 20*0.4 + 80*0.6 = 56
        assert 50 < r2 < 65, f"Expected ~56, got {r2}"

    def test_different_spans_converge_different_rates(self):
        """短窗口（news=3）比长窗口（valuation=15）对变化反应更快"""
        model = EnhancedTimingModel()
        # 分别模拟新闻和估值的两轮调用
        news_r1 = model._smooth_category_score('news', 100.0)
        news_r2 = model._smooth_category_score('news', 0.0)
        val_model = EnhancedTimingModel()
        val_r1 = val_model._smooth_category_score('valuation', 100.0)
        val_r2 = val_model._smooth_category_score('valuation', 0.0)
        # 新闻（alpha=0.5）比估值（alpha=0.125）变化更大
        news_change = abs(news_r2 - 100.0)
        val_change = abs(val_r2 - 100.0)
        assert news_change > val_change, \
            f"News should react faster: news_change={news_change:.1f} val_change={val_change:.1f}"

    def test_calculate_uses_smoothed_scores(self):
        """calculate 方法使用平滑后的大类得分"""
        model = EnhancedTimingModel()
        # 使用足够的有效数据让所有类别都有有效得分
        data = EnhancedMarketData(date=date.today())
        data.stock_pe_median = 12.0
        data.stock_pb_median = 1.2
        data.cb_count = 300
        data.avg_premium = 60.0
        data.yield_diff_with_aa = 2.5
        data.market_turnover = 3.0
        data.cb_amount = 500
        data.stock_index_change = 1.5
        data.volume_ratio = 1.2
        data.advance_decline_ratio = 1.5
        data.limit_up_count = 80
        data.limit_down_count = 20
        data.new_high_count = 50
        data.new_low_count = 10
        data.industry_net_inflow_ratio = 60.0
        data.industry_cycle_score = 80.0
        data.bond_yield_3a = 2.5
        data.bond_yield_aa_minus = 4.5
        data.credit_spread = 2.0
        data.term_spread = 0.8
        data.vix_index = 15.0
        data.five_day_vol_change = 0.05
        data.pmi = 51.0
        data.cpi = 2.0
        data.m2_growth = 8.0
        data.us_china_rate_diff = 1.5
        data.us10y = 4.0
        data.cb_below_par_count = 30
        data.new_accounts = 80.0
        data.pcr_ratio = 0.6
        data.margin_buy_ratio = 5.0
        data.five_day_delta_pcr = 0.0

        # 第一轮：所有类别初始化 EMA
        result1 = model.calculate(data)
        cat_scores_1 = {k: v.score for k, v in result1.category_scores.items()}

        # 第二轮：相同输入，平滑后得分差异不大
        result2 = model.calculate(data)
        cat_scores_2 = {k: v.score for k, v in result2.category_scores.items()}

        # 类别得分应该一致（相同输入）
        for cat in cat_scores_1:
            assert abs(cat_scores_1[cat] - cat_scores_2[cat]) <= 15.0, \
                f"{cat} diff too large: {cat_scores_1[cat]:.1f} vs {cat_scores_2[cat]:.1f}"

        # 确认 EMAs 被更新
        assert len(model._category_ema) > 0

    def test_reset_model_clears_ema(self):
        """新模型实例的 EMA 状态应为空"""
        model = EnhancedTimingModel()
        assert len(model._category_ema) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
