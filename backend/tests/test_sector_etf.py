"""Tests for sector ETF mapping endpoint and module."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from fastapi.testclient import TestClient
from app.api.sector_etf import (
    SECTOR_ETF_MAP,
    SectorEtfMapping,
    get_sector_etf_map_for_backtest,
)


class TestSectorEtfMap:
    """测试 ETF 映射表的正确性"""

    def test_map_not_empty(self):
        assert len(SECTOR_ETF_MAP) > 0, "映射表不应为空"

    def test_map_count_is_20(self):
        """申万行业 2021 版共 20 个一级行业"""
        assert len(SECTOR_ETF_MAP) == 20, f"期望 20 个行业, 实际 {len(SECTOR_ETF_MAP)}"

    def test_codes_unique(self):
        """sw_code 必须唯一"""
        codes = [m.sw_code for m in SECTOR_ETF_MAP]
        assert len(codes) == len(set(codes)), "sw_code 存在重复"

    def test_etf_codes_unique(self):
        """etf_code 必须唯一（一个 ETF 只能映射到一个行业）"""
        codes = [m.etf_code for m in SECTOR_ETF_MAP]
        assert len(codes) == len(set(codes)), "etf_code 存在重复"

    def test_sw_code_format(self):
        """sw_code 必须是 6 位数字（801010 格式）"""
        import re
        for m in SECTOR_ETF_MAP:
            assert re.match(r"^80[0-9]{4}$", m.sw_code), f"无效 sw_code: {m.sw_code}"

    def test_etf_code_format(self):
        """etf_code 必须是 6 位数字"""
        import re
        for m in SECTOR_ETF_MAP:
            assert re.match(r"^[0-9]{6}$", m.etf_code), f"无效 etf_code: {m.etf_code}"

    def test_no_placeholder_codes(self):
        """禁止使用 000000 占位"""
        for m in SECTOR_ETF_MAP:
            assert m.sw_code != "000000"
            assert m.etf_code != "000000"

    def test_no_default_price_100(self):
        """禁止 price=100.0 默认值"""
        for m in SECTOR_ETF_MAP:
            # 这里没有 price 字段，但确保没有混入
            assert not hasattr(m, "price")


class TestGetSectorEtfMapForBacktest:
    """测试回测辅助函数"""

    def test_returns_dict(self):
        result = get_sector_etf_map_for_backtest()
        assert isinstance(result, dict)

    def test_dict_keys_are_sw_codes(self):
        result = get_sector_etf_map_for_backtest()
        for k in result.keys():
            assert k.startswith("80"), f"键必须是 sw_code: {k}"

    def test_dict_values_are_tuples_of_3(self):
        """值是 (etf_code, etf_name, sector) 三元组"""
        result = get_sector_etf_map_for_backtest()
        for code, info in result.items():
            assert isinstance(info, tuple)
            assert len(info) == 3
            etf_code, etf_name, sector = info
            assert isinstance(etf_code, str) and len(etf_code) == 6
            assert isinstance(etf_name, str) and len(etf_name) > 0
            assert isinstance(sector, str) and len(sector) > 0

    def test_dict_count_matches_list(self):
        """dict 数量应等于 SECTOR_ETF_MAP 数量"""
        result = get_sector_etf_map_for_backtest()
        assert len(result) == len(SECTOR_ETF_MAP)


class TestDataSourceEnum:
    """测试数据源枚举"""

    def test_all_sources_defined(self):
        from app.utils.data_source import DataSource
        assert DataSource.REAL.value == "real"
        assert DataSource.ESTIMATED.value == "estimated"
        assert DataSource.FALLBACK.value == "fallback"
        assert DataSource.MOCK.value == "mock"
        assert DataSource.MISSING.value == "missing"

    def test_annotate_with_source(self):
        from app.utils.data_source import annotate_with_source, DataSource
        result = annotate_with_source({"price": 100.0}, DataSource.REAL)
        assert result["_source"] == "real"
        assert result["price"] == 100.0

    def test_is_real_source(self):
        from app.utils.data_source import is_real_source
        assert is_real_source("real") is True
        assert is_real_source("estimated") is False
        assert is_real_source("fallback") is False
        assert is_real_source("mock") is False
        assert is_real_source("missing") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
