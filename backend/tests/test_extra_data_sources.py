"""
测试 extra_data_sources.py 中的新增数据源
"""
import pytest
from datetime import date


def test_value_analysis_import():
    """测试 _fetch_value_analysis_single 导入"""
    from app.api.extra_data_sources import _fetch_value_analysis_single
    assert callable(_fetch_value_analysis_single)


def test_value_analysis_data_format():
    """测试 value_analysis 返回的字段格式"""
    from app.api.extra_data_sources import _fetch_value_analysis_single
    recs = _fetch_value_analysis_single("113050")
    if not recs:
        pytest.skip("113050 value_analysis 无数据")
    assert len(recs) > 0
    required_fields = {"code", "date", "bond_value", "conversion_value", "premium_ratio"}
    sample = recs[0]
    for field in required_fields:
        assert field in sample, f"Missing field {field}"


def test_value_analysis_batch():
    """测试批量下载"""
    from app.api.extra_data_sources import fetch_value_analysis_batch
    df = fetch_value_analysis_batch(["113050", "110079"], max_workers=2)
    if df.empty:
        pytest.skip("value_analysis_batch 失败")
    assert "code" in df.columns
    assert "bond_value" in df.columns
    assert df["code"].nunique() >= 1


def test_industry_batch_import():
    """测试 industry 导入"""
    from app.api.extra_data_sources import fetch_industry_batch
    assert callable(fetch_industry_batch)


def test_bond_misc_data():
    """测试转债misc数据"""
    from app.api.extra_data_sources import fetch_bond_misc_data
    misc = fetch_bond_misc_data()
    # 可能为空,但应该返回dict
    assert isinstance(misc, dict)


def test_csi_index():
    """测试中证转债指数"""
    from app.api.extra_data_sources import fetch_csi_index
    df = fetch_csi_index(date(2022, 1, 1), date(2022, 12, 31))
    if df.empty:
        pytest.skip("CSI index 无数据")
    assert "csi_index_close" in df.columns


def test_stock_financial_ths():
    """测试正股财务摘要"""
    from app.api.extra_data_sources import fetch_stock_financial_ths_batch
    fin = fetch_stock_financial_ths_batch(["601318"], max_workers=1)
    assert isinstance(fin, dict)


def test_xuanji_v8_new_factor_pure_bond_premium():
    """测试v8策略新增 pure_bond_premium 因子"""
    import pandas as pd
    import numpy as np
    from app.strategies.xuanji_v8 import XuanjiV8Strategy

    s = XuanjiV8Strategy(hold_count=15)
    # 验证权重
    assert "pure_bond_premium" in s.FACTOR_WEIGHTS
    assert abs(sum(s.FACTOR_WEIGHTS.values()) - 1.0) < 0.001

    # 模拟 day_data
    day_data = pd.DataFrame({
        "code": ["113050", "110079", "128039"],
        "price": [120, 130, 110],
        "bond_value": [100, 105, 95],
        "premium_ratio": [20, 25, 15],
        "volume": [1000000, 2000000, 1500000],
        "ytm": [1.0, 0.5, 2.0],
        "remaining_years": [3.0, 4.0, 2.0],
        "roe": [10, 12, 8],
        "gpm": [25, 30, 20],
        "pe": [15, 18, 12],
        "pb": [2, 3, 1.5],
        "hv": [20, 25, 18],
        "industry": ["金融", "制造", "金融"],
    })
    # 测试 compute_factor_scores
    scores = s._compute_factor_scores(day_data)
    assert "pure_bond_premium" in scores
    # 该因子得分应基于 bond_value/price 计算
    # bond_value/price: 100/120=0.83 (pbp=-16.7%), 105/130=0.81 (pbp=-19.2%), 95/110=0.86 (pbp=-13.6%)
    # 低 pbp → 高分 (ascending=True)
    pbp_score = scores["pure_bond_premium"].values
    # 应该是 score[1] > score[0] > score[2] (因为 pbp[1] < pbp[0] < pbp[2])
    # 实际: pbp[0] = (120/100-1)*100 = 20, pbp[1] = (130/105-1)*100 = 23.8, pbp[2] = (110/95-1)*100 = 15.8
    # 低 pbp → 高分: score[2] > score[0] > score[1]
    assert pbp_score[2] > pbp_score[0]
    assert pbp_score[2] > pbp_score[1]


def test_xuanji_v8_apply_filters_uses_bond_value():
    """测试v8策略的纯债价值比过滤使用 bond_value"""
    import pandas as pd
    from app.strategies.xuanji_v8 import XuanjiV8Strategy

    s = XuanjiV8Strategy(hold_count=15, max_price_to_cbv=1.5)
    # bond=100, price=120, ratio=1.2 -> 通过 (1.2 < 1.5)
    # bond=100, price=180, ratio=1.8 -> 不通过
    day_data = pd.DataFrame({
        "code": ["A", "B"],
        "name": ["A", "B"],
        "price": [120, 180],
        "bond_value": [100, 100],
        "premium_ratio": [10, 10],
        "volume": [1000000, 1000000],
        "ytm": [1.0, 1.0],
        "remaining_years": [3.0, 3.0],
        "roe": [10, 10],
        "gpm": [20, 20],
        "pe": [15, 15],
        "pb": [2, 2],
        "hv": [20, 20],
        "industry": ["其他", "其他"],
    })
    s._fill_missing_columns(day_data)
    filtered = s._apply_filters(day_data)
    assert len(filtered) == 1
    assert filtered.iloc[0]["code"] == "A"


def test_xuanji_v8_cross_section_keeps_index():
    """测试 _cross_section_zscore 保留所有index"""
    import pandas as pd
    from app.strategies.xuanji_v8 import XuanjiV8Strategy

    s = XuanjiV8Strategy(hold_count=15)
    s = XuanjiV8Strategy(hold_count=15)
    s = XuanjiV8Strategy(hold_count=15)
    s = XuanjiV8Strategy(hold_count=15)

    # 输入5个, 2个NaN
    series = pd.Series([1.0, 2.0, float('nan'), 3.0, float('nan')], index=['a','b','c','d','e'])
    result = s._cross_section_zscore(series, ascending=True)
    # 输出应有相同index
    assert list(result.index) == list(series.index)
    # NaN位置应保持0.5
    assert result['c'] == 0.5
    assert result['e'] == 0.5
    # 有效值的相对排名 (ascending=True: 低值=高分)
    assert result['a'] > result['b'] > result['d']  # a=1.0低值高分, d=3.0高值低分
