"""测试 dual_low 策略的强赎条款过滤"""
import pandas as pd
import pytest
from app.strategies.dual_low import DualLowStrategy


class TestDualLowForcedCallFilter:
    """验证 dual_low 策略能过滤已强赎/即将强赎的转债"""

    @pytest.fixture
    def strategy(self):
        s = DualLowStrategy()
        data = pd.DataFrame({
            'code': ['110001', '110002', '110003', '110004'],
            'date': ['2024-01-01'] * 4,
            'price': [110.0, 105.0, 115.0, 108.0],
            'premium_ratio': [5.0, 8.0, 12.0, 3.0],
            'dual_low': [115.0, 113.0, 127.0, 111.0],
            'is_called': [False, True, False, False],
            'call_status': ['', '已公告强赎', '', ''],
            'forced_call_days': [None, 0, None, 10],
        })
        s.on_init(data)
        return s

    def test_filters_out_called_bond(self, strategy):
        """is_called=True 的转债应被过滤"""
        signals = strategy.on_data(strategy._data, 0)
        if signals is None:
            signals = []
        codes_in_signals = set(s['code'] for s in signals if s['action'] == 'buy')
        assert '110002' not in codes_in_signals, \
            "已强赎转债不应出现在买入信号中"

    def test_filters_out_called_by_status(self):
        """call_status 包含 '强赎' 的应被过滤"""
        s = DualLowStrategy()
        data = pd.DataFrame({
            'code': ['110001', '110002'],
            'date': ['2024-01-01'] * 2,
            'price': [110.0, 105.0],
            'premium_ratio': [5.0, 8.0],
            'dual_low': [115.0, 113.0],
            'is_called': [False, False],
            'call_status': ['', '公告要强赎'],
            'forced_call_days': [None, 5],
        })
        s.on_init(data)
        signals = s.on_data(data, 0)
        codes = set(s['code'] for s in (signals or []) if s['action'] == 'buy')
        assert '110002' not in codes, \
            "call_status 含强赎的转债不应出现"

    def test_allows_normal_bond(self, strategy):
        """正常转债（未强赎）应可通过过滤"""
        signals = strategy.on_data(strategy._data, 0)
        codes = set(s['code'] for s in (signals or []) if s['action'] == 'buy')
        assert '110001' in codes, "正常转债应出现在买入信号中"

    def test_graceful_when_columns_missing(self):
        """数据列缺失时不应崩溃"""
        s = DualLowStrategy()
        data = pd.DataFrame({
            'code': ['110001'],
            'date': ['2024-01-01'],
            'price': [110.0],
            'premium_ratio': [5.0],
            'dual_low': [115.0],
        })
        s.on_init(data)
        signals = s.on_data(data, 0)
        assert signals is not None  # 不应崩溃
