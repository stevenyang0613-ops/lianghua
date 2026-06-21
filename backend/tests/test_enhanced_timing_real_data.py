"""增强择时模型真实数据与中性缺失值处理测试

验证：
1. convert_from_legacy_data 能把 MacroData 的真实字段正确映射到 EnhancedMarketData。
2. 数据源不可用的字段（北向、主力、新增开户、行业资金）不会 skew 综合得分。
3. 不可用字段的子因子描述为"数据源暂不可用"，confidence=0。
4. 数据完整度计算不会故意扣减不可用字段的分数。
"""
import pytest
from datetime import date
from unittest.mock import MagicMock

from app.strategies.enhanced_timing_model import (
    EnhancedTimingModel,
    EnhancedMarketData,
    convert_from_legacy_data,
)


def _make_real_macro_data():
    """构造一份模拟真实抓取后的 MacroData（关键字段均有值）"""
    m = MagicMock()
    m.treasury_10y_yield = 2.25
    m.treasury_2y_yield = 1.85
    m.shibor_overnight = 1.35
    m.shibor_1w = 1.55
    m.shibor_1m = 1.80
    m.credit_spread_aa = 95.0
    m.pmi_current = 49.8
    m.pmi_prev = 49.5
    m.cpi = 0.3
    m.ppi = -1.2
    m.m2_growth = 7.2
    m.social_financing_growth = 8.5
    m.gdp_growth = 5.3
    m.cb_median_premium = 32.5
    m.cb_median_price = 118.0
    m.cb_avg_daily_amount = 420.0
    m.cb_index_current = 410.5
    m.cb_index_change = 0.4
    m.cb_index_ma20 = 408.0
    m.cb_index_ma60 = 405.0
    m.cb_below_par_count = 12
    m.cb_count = 520
    m.cb_ytm_median = 0.0  # 当前未接入真实 YTM 中位数，保持 0
    m.stock_index_current = 3500.0
    m.stock_index_change = 0.6
    m.stock_index_ma20 = 3480.0
    m.stock_index_ma60 = 3450.0
    m.stock_pe_median = 22.5
    m.stock_pb_median = 2.1
    m.stock_pe_percentile = 45.0
    m.stock_pb_percentile = 35.0
    # 以下字段数据源当前不可用，按中性值返回
    m.north_bound_net_flow = 0.0
    m.main_force_net_flow = 0.0
    m.industry_net_inflow = 50.0
    m.new_accounts = 0.0
    # 真实可获取字段
    m.margin_balance = 15000.0
    m.margin_balance_change = 120.0
    m.margin_buy_ratio = 9.5
    m.industrial_output = 5.8
    m.retail_sales = 4.2
    m.export_growth = 7.1
    m.pcr_ratio = 0.92
    m.vix_index = 18.5
    m.ma_arrangement = "bullish"
    m.macd_signal = "bullish"
    m.rsi_14 = 58.0
    m.bollinger_position = 0.55
    m.volume_ratio = 1.1
    m.institutional_holding_change = 0.3
    m.earnings_surprise_ratio = 0.55
    m.policy_signal_score = 55.0
    m.event_impact_score = 52.0
    m.industry_cycle_score = 54.0
    m.limit_up_count = 45
    m.limit_down_count = 8
    m.advance_count = 2800
    m.decline_count = 2100
    m.new_high_60d = 120
    m.new_low_60d = 60
    m.market_turnover = 1.2
    return m


def test_convert_from_legacy_data_maps_real_fields():
    """MacroData 的真实字段应正确映射到 EnhancedMarketData"""
    macro = _make_real_macro_data()
    data = convert_from_legacy_data(macro_data=macro)

    assert data.treasury_10y_yield == pytest.approx(2.25)
    assert data.pmi == pytest.approx(49.8)
    assert data.pmi_prev == pytest.approx(49.5)
    assert data.cpi == pytest.approx(0.3)
    assert data.m2_growth == pytest.approx(7.2)
    assert data.gdp_growth == pytest.approx(5.3)
    assert data.shibor_overnight == pytest.approx(1.35)
    assert data.credit_spread == pytest.approx(95.0)
    assert data.cb_median_premium == pytest.approx(32.5)
    assert data.cb_median_price == pytest.approx(118.0)
    assert data.stock_index_current == pytest.approx(3500.0)
    assert data.stock_pe_median == pytest.approx(22.5)
    assert data.stock_pb_percentile == pytest.approx(35.0)
    assert data.pcr_ratio == pytest.approx(0.92)
    assert data.vix_index == pytest.approx(18.5)
    assert data.margin_buy_ratio == pytest.approx(9.5)
    assert data.advance_decline_ratio == pytest.approx(2800 / 2100, rel=1e-3)
    assert data.data_completeness > 0.5


def test_unavailable_fields_do_not_skew_score():
    """不可用字段（0/50默认值）按中性处理，不应导致异常得分或描述"""
    macro = _make_real_macro_data()
    data = convert_from_legacy_data(macro_data=macro)
    model = EnhancedTimingModel()
    signal = model.calculate(data)

    # 综合得分应处于合理区间（不可用字段为中性，不应拉到极端值）
    assert 20 <= signal.total_score <= 80

    capital = signal.category_scores["capital_flow"]
    sub_names = {sf.name: sf for sf in capital.sub_factors}

    # 主力资金和北向资金不可用 -> 中性分 + confidence=0 + 明确描述
    assert sub_names["主力资金净流入"].score == pytest.approx(50.0)
    assert sub_names["主力资金净流入"].confidence == 0.0
    assert "数据源暂不可用" in sub_names["主力资金净流入"].description

    assert sub_names["北向资金净流入"].score == pytest.approx(50.0)
    assert sub_names["北向资金净流入"].confidence == 0.0
    assert "数据源暂不可用" in sub_names["北向资金净流入"].description

    # 行业资金流向默认 50 视为不可用
    assert sub_names["行业资金流向"].score == pytest.approx(50.0)
    assert sub_names["行业资金流向"].confidence == 0.0
    assert "数据源暂不可用" in sub_names["行业资金流向"].description

    sentiment = signal.category_scores["sentiment"]
    sent_subs = {sf.name: sf for sf in sentiment.sub_factors}
    assert sent_subs["新增开户数"].score == pytest.approx(50.0)
    assert sent_subs["新增开户数"].confidence == 0.0
    assert "数据源暂不可用" in sent_subs["新增开户数"].description


def test_real_fields_produce_non_neutral_signals():
    """真实数据字段应产生非中性子因子信号和描述"""
    macro = _make_real_macro_data()
    data = convert_from_legacy_data(macro_data=macro)
    model = EnhancedTimingModel()
    signal = model.calculate(data)

    # 流动性面：Shibor、国债、信用利差等真实字段应产生非中性信号
    liq = signal.category_scores["liquidity"]
    liq_descs = " ".join(sf.description for sf in liq.sub_factors)
    assert "数据源暂不可用" not in liq_descs
    assert any(sf.score != 50.0 for sf in liq.sub_factors)

    # 宏观面：PMI、GDP、工业增加值等真实字段应产生非中性信号
    macro_cat = signal.category_scores["macro"]
    macro_descs = " ".join(sf.description for sf in macro_cat.sub_factors)
    assert "数据源暂不可用" not in macro_descs
    assert any(sf.score != 50.0 for sf in macro_cat.sub_factors)

    # 技术面：MA/MACD/RSI 等真实字段应产生非中性信号
    tech = signal.category_scores["technical"]
    tech_descs = " ".join(sf.description for sf in tech.sub_factors)
    assert "数据源暂不可用" not in tech_descs
    assert any(sf.score != 50.0 for sf in tech.sub_factors)


def test_data_completeness_not_penalized_for_unavailable_fields():
    """不可用字段为中性默认值时，完整度不应被大幅拉低"""
    macro = _make_real_macro_data()
    data = convert_from_legacy_data(macro_data=macro)
    # 真实数据较全时，完整度应较高（不可用字段不扣分）
    assert data.data_completeness >= 0.6
