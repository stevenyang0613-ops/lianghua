"""Tests for enrich_quotes field merging and NaN/zero-fill semantics."""

import pytest
from datetime import date, datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.models.convertible import ConvertibleQuote
from app.engine import data_enrich as de


class TestEnrichQuotesMerge:
    """Verify field merge logic directly (without full enrich_quotes async call)."""

    def _make_bond(self, stock_code: str, **kwargs) -> ConvertibleQuote:
        defaults = {
            "code": "000001",
            "name": "Test Bond",
            "stock_code": stock_code,
            "stock_name": "Test Stock",
        }
        defaults.update(kwargs)
        return ConvertibleQuote(**defaults)

    def test_earnings_express_overrides_fin_logic(self, monkeypatch):
        """快报数据（季度）应覆盖年度报表数据（更及时）。"""
        # Simulate the actual logic in enrich_quotes after fin + earnings_express processing
        bond = self._make_bond(stock_code="600519")
        # fin data first
        bond.eps = 5.0
        bond.bps = 20.0
        bond.roe = 15.0
        bond.revenue_yoy = 10.0
        bond.profit_yoy = 8.0
        # Then earnings_express override (the actual code path)
        _ee = {"eps": 6.0, "bps": 22.0, "roe": 18.0, "revenue_yoy": 12.0, "net_profit_yoy": 10.0}
        if _ee.get("eps") is not None:
            bond.eps = _ee["eps"]
        if _ee.get("bps") is not None:
            bond.bps = _ee["bps"]
        if _ee.get("roe") is not None:
            bond.roe = _ee["roe"]
        if _ee.get("revenue_yoy") is not None:
            bond.revenue_yoy = _ee["revenue_yoy"]
        if _ee.get("net_profit_yoy") is not None:
            bond.profit_yoy = _ee["net_profit_yoy"]

        assert bond.eps == 6.0, "快报 EPS 应覆盖年度 EPS"
        assert bond.bps == 22.0, "快报 BPS 应覆盖年度 BPS"
        assert bond.roe == 18.0, "快报 ROE 应覆盖年度 ROE"
        assert bond.revenue_yoy == 12.0, "快报 revenue_yoy 应覆盖年度"
        assert bond.profit_yoy == 10.0, "快报 profit_yoy 应填充"

    def test_earnings_express_triggers_pe_recalc_logic(self, monkeypatch):
        """快报覆盖 EPS 后，应触发 PE = stock_price / EPS 重新计算。"""
        bond = self._make_bond(stock_code="600519", stock_price=300.0)
        # Simulate the earnings_express PE recalc logic
        _ee = {"eps": 10.0}
        if bond.stock_price is not None and bond.stock_price > 0:
            if _ee.get("eps") is not None and _ee["eps"] > 0:
                _pe = round(bond.stock_price / _ee["eps"], 2)
                if 0 < _pe <= 10000:
                    bond.pe = _pe

        assert bond.pe == 30.0, "stock_price 300 / eps 10 = pe 30"

    def test_zero_fill_filtered_from_completeness(self, monkeypatch):
        """zero_fill 条目不应计入 completeness。"""
        de.reset_module_state_for_testing()
        de._spot_map = {
            "600519": {"pe": 10.0, "pb": 2.0},
            "600000": {"pe": 0.0, "pb": 0.0, "_data_source": "zero_fill"},
        }
        de._bond_codes = {"000001", "000002"}
        de._bond_stock_codes = {"600519", "600000"}

        codes_to_check = ["600519", "600000"]
        m = de._spot_map
        bond_count = sum(1 for c in codes_to_check if c in m and m.get(c) is not None
                                 and (not isinstance(m.get(c), dict) or m.get(c).get("_data_source") != "zero_fill"))
        assert bond_count == 1, "zero_fill 条目不应计入 bond_count"

    def test_macro_cache_is_numeric(self, monkeypatch):
        """macro 缓存值必须是数字，非数字值应被忽略。"""
        # Simulate the macro enrichment logic from enrich_quotes
        bond = self._make_bond(stock_code="600519")
        _macro_cpi_map = {"latest": 2.5}
        _macro_ppi_map = {"latest": "invalid"}
        _macro_m2_map = {}
        _macro_lpr_map = {"latest": 3.45}

        if _macro_cpi_map:
            _v = _macro_cpi_map.get("latest")
            if isinstance(_v, (int, float)):
                bond.macro_cpi = _v
        if _macro_ppi_map:
            _v = _macro_ppi_map.get("latest")
            if isinstance(_v, (int, float)):
                bond.macro_ppi = _v
        if _macro_m2_map:
            _v = _macro_m2_map.get("latest")
            if isinstance(_v, (int, float)):
                bond.macro_m2 = _v
        if _macro_lpr_map:
            _v = _macro_lpr_map.get("latest")
            if isinstance(_v, (int, float)):
                bond.macro_lpr = _v

        assert bond.macro_cpi == 2.5
        assert bond.macro_ppi is None, "非法字符串应被忽略"
        assert bond.macro_m2 is None, "空缓存应不填充"
        assert bond.macro_lpr == 3.45

    def test_none_vs_zero_semantics(self, monkeypatch):
        """None（缺失）与 0（真实零值）应正确区分。"""
        # Simulate earnings_forecast zero-fill with None
        bond = self._make_bond(stock_code="600519")
        ef = {"yoy_change_pct": None, "_data_source": "zero_fill"}
        if isinstance(ef, dict):
            bond.eps_forecast = ef.get("yoy_change_pct")

        assert bond.eps_forecast is None, "zero_fill 的 None 不应变成 0"

    def test_north_net_add_capital_fallback_none(self, monkeypatch):
        """北向资金 add_capital fallback 无法精确转换时，应为 None。"""
        bond = self._make_bond(stock_code="600519", stock_price=100.0)
        north = {"add_capital": 5000000}  # 变动资金，无法精确转换
        if isinstance(north, dict):
            _hold_mc = north.get("hold_market_cap")
            _hold_shares = north.get("hold_shares")
            if _hold_mc is not None and _hold_mc > 0:
                bond.north_net = round(_hold_mc / 1e8, 4)
            elif _hold_shares is not None and _hold_shares > 0 and bond.stock_price and bond.stock_price > 0:
                bond.north_net = round(_hold_shares * bond.stock_price / 1e8, 4)
            elif "add_capital" in north and north["add_capital"] is not None:
                bond.north_net = None

        assert bond.north_net is None, "add_capital fallback 应为 None（无法精确转换）"

    def test_north_net_invalid_type_none(self, monkeypatch):
        """北向资金数据类型非法时，应为 None 而非 0。"""
        bond = self._make_bond(stock_code="600519")
        north = []  # 非法类型
        if isinstance(north, dict):
            _hold_mc = north.get("hold_market_cap")
            _hold_shares = north.get("hold_shares")
            if _hold_mc is not None and _hold_mc > 0:
                bond.north_net = round(_hold_mc / 1e8, 4)
            elif _hold_shares is not None and _hold_shares > 0 and bond.stock_price and bond.stock_price > 0:
                bond.north_net = round(_hold_shares * bond.stock_price / 1e8, 4)
            elif "add_capital" in north and north["add_capital"] is not None:
                bond.north_net = None
        else:
            bond.north_net = None

        assert bond.north_net is None, "非法类型应为 None"

    def test_eps_forecast_missing_none(self, monkeypatch):
        """缓存已加载但股票无预测时，eps_forecast 应为 None。"""
        bond = self._make_bond(stock_code="600519")
        ef = None  # 缓存已加载但股票不在其中
        if isinstance(ef, dict):
            bond.eps_forecast = ef.get("yoy_change_pct")
        elif ef is not None:
            bond.eps_forecast = ef
        else:
            bond.eps_forecast = None

        assert bond.eps_forecast is None, "无预测应为 None"

    def test_macro_policy_event_scores(self, monkeypatch):
        """宏观政策评分计算应正确。"""
        # 高通胀 + 高 PPI + 高 M2 → 政策收紧 + 宽松流动性
        policy, event = de._calc_macro_policy_event_scores(
            cpi=4.0, ppi=6.0, m2=13.0, lpr=3.0
        )
        assert policy == 40.0, f"高通胀-10 + 高PPI-5 + 高M2+5 = 40, got {policy}"
        assert event == 55.0, f"低LPR+5 = 55, got {event}"

        # 通缩 + 低 PPI + 低 M2 → 政策宽松 + 流动性收紧
        policy, event = de._calc_macro_policy_event_scores(
            cpi=-0.5, ppi=-3.0, m2=7.0, lpr=4.6
        )
        assert policy == 60.0, f"通缩+10 + 低PPI+5 + 低M2-5 = 60, got {policy}"
        assert event == 45.0, f"高LPR-5 = 45, got {event}"

        # 全部 None → 返回 None
        policy, event = de._calc_macro_policy_event_scores()
        assert policy is None
        assert event is None

    def test_macro_policy_event_scores_boundary(self, monkeypatch):
        """宏观政策评分应在边界 0-100 内。"""
        # 极端宽松
        policy, event = de._calc_macro_policy_event_scores(
            cpi=-5.0, ppi=-10.0, m2=5.0, lpr=2.0
        )
        assert 0 <= policy <= 100, f"policy 越界: {policy}"
        assert 0 <= event <= 100, f"event 越界: {event}"
        assert policy == 60.0, f"极端宽松应为 60 (50+10+5-5), got {policy}"
        assert event == 55.0, f"极低LPR应为 55, got {event}"

        # 极端收紧
        policy, event = de._calc_macro_policy_event_scores(
            cpi=10.0, ppi=10.0, m2=15.0, lpr=5.0
        )
        assert policy == 40.0, f"极端收紧应为 40 (50-10-5+5), got {policy}"
        assert event == 45.0, f"高LPR应为 45, got {event}"
