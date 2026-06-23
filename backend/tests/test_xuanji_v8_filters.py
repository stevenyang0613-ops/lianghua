"""测试 xuanji_v8 策略的条款过滤"""
import pandas as pd
import numpy as np
import pytest
from app.strategies.xuanji_v8 import XuanjiV8Strategy


def _make_v8_data(codes, prices, premiums, called=None, call_status=None,
                  forced_call_days=None, names=None):
    """构造 v8 策略 on_init 所需的最小数据集 (至少 100 行)"""
    n = len(codes)
    rows = []
    # 需要至少 100 行以满足数据完备性要求
    for i in range(max(n, 100)):
        code = codes[i % n] if n > 0 else f"110{i:03d}"
        rows.append({
            'code': code,
            'date': '2024-01-01',
            'price': prices[i % len(prices)] if len(prices) > 0 else 110.0,
            'premium_ratio': premiums[i % len(premiums)] if len(premiums) > 0 else 10.0,
            'volume': 1_000_000,
            'remaining_years': 3.0,
            'pe': 20.0, 'pb': 1.5, 'roe': 8.0, 'gpm': 15.0,
            'hv': 20.0, 'ytm': 2.0, 'turnover_rate': 0.5,
            'bond_value': 100.0, 'conversion_value': 90.0,
        })
    df = pd.DataFrame(rows)
    # 添加条款列
    if called is not None:
        df['is_called'] = [called[i % n] for i in range(len(df))]
    if call_status is not None:
        df['call_status'] = [call_status[i % n] for i in range(len(df))]
    if forced_call_days is not None:
        df['forced_call_days'] = [forced_call_days[i % n] for i in range(len(df))]
    if names is not None:
        df['name'] = [names[i % n] for i in range(len(df))]
    return df


class TestXuanjiV8ForcedCallFilter:
    """验证 xuanji_v8 能过滤已强赎/可交换债"""

    def test_filters_out_called_bonds(self):
        """is_called=True 的转债应被过滤"""
        df = _make_v8_data(
            codes=['110001', '110002'],
            prices=[110.0, 105.0],
            premiums=[5.0, 3.0],
            called=[False, True],
        )
        s = XuanjiV8Strategy()
        s.on_init(df)
        day_data = df[df['date'] == '2024-01-01'].copy()
        day_data = s._apply_filters(day_data)
        assert '110002' not in day_data['code'].values, "已强赎转债应被过滤"

    def test_filters_exchangeable_bonds(self):
        """132/133 开头的可交换债应被过滤"""
        df = _make_v8_data(
            codes=['110001', '132001'],
            prices=[110.0, 105.0],
            premiums=[5.0, 3.0],
        )
        s = XuanjiV8Strategy()
        s.on_init(df)
        day_data = df[df['date'] == '2024-01-01'].copy()
        day_data = s._apply_filters(day_data)
        assert '132001' not in day_data['code'].values, "可交换债(132开头)应被过滤"

    def test_filters_exchangeable_by_name(self):
        """名称含'可交换债'的应被过滤"""
        df = _make_v8_data(
            codes=['110001', '110002'],
            prices=[110.0, 105.0],
            premiums=[5.0, 3.0],
            names=['某某转债', '某某可交换债'],
        )
        s = XuanjiV8Strategy()
        s.on_init(df)
        day_data = df[df['date'] == '2024-01-01'].copy()
        day_data = s._apply_filters(day_data)
        assert '110002' not in day_data['code'].values, "名称含可交换债的应被过滤"

    def test_graceful_when_columns_missing(self):
        """缺失条款列时不应崩溃"""
        df = _make_v8_data(
            codes=['110001'],
            prices=[110.0],
            premiums=[5.0],
        )
        # 删除 is_called 等列（_make_v8_data 默认不添加）
        s = XuanjiV8Strategy()
        s.on_init(df)
        day_data = df[df['date'] == '2024-01-01'].copy()
        day_data = s._apply_filters(day_data)  # 不应崩溃
        assert len(day_data) > 0, "应返回数据"
