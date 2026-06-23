"""Tests for data_source field in API responses"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from app.utils.data_source import DataSource, annotate_with_source, is_real_source


class TestDataSourceEnum:
    def test_values(self):
        assert DataSource.REAL.value == "real"
        assert DataSource.ESTIMATED.value == "estimated"
        assert DataSource.FALLBACK.value == "fallback"
        assert DataSource.MOCK.value == "mock"
        assert DataSource.MISSING.value == "missing"

    def test_is_string(self):
        """确保枚举是 str 子类，可直接与字符串比较"""
        assert DataSource.REAL == "real"
        assert DataSource.ESTIMATED == "estimated"

    def test_iteration(self):
        sources = list(DataSource)
        assert len(sources) == 5


class TestAnnotateWithSource:
    def test_dict_gets_source(self):
        result = annotate_with_source({"price": 100.0}, DataSource.REAL)
        assert result["_source"] == "real"
        assert result["price"] == 100.0

    def test_non_dict_wrapped(self):
        result = annotate_with_source(42, DataSource.FALLBACK)
        assert result == {"value": 42, "_source": "fallback"}

    def test_empty_dict(self):
        result = annotate_with_source({}, DataSource.MISSING)
        assert result == {"_source": "missing"}


class TestIsRealSource:
    def test_real_is_real(self):
        assert is_real_source("real") is True

    def test_estimated_not_real(self):
        assert is_real_source("estimated") is False

    def test_fallback_not_real(self):
        assert is_real_source("fallback") is False

    def test_mock_not_real(self):
        assert is_real_source("mock") is False

    def test_missing_not_real(self):
        assert is_real_source("missing") is False

    def test_unknown_not_real(self):
        assert is_real_source("something_weird") is False

    def test_empty_not_real(self):
        assert is_real_source("") is False


class TestTagHelper:
    """测试 fund_flow / xuanji 中 _tag helper 函数的语义"""

    def test_tag_dict_adds_source(self):
        """dict 应被原地修改并添加 data_source 字段"""
        from app.api.fund_flow import _tag
        d = {"stocks": [1, 2, 3], "total": 3}
        result = _tag(d)
        assert result["data_source"] == "real"
        assert result["stocks"] == [1, 2, 3]

    def test_tag_dict_with_custom_source(self):
        from app.api.fund_flow import _tag
        from app.utils.data_source import DataSource
        d = {"stocks": []}
        result = _tag(d, source=DataSource.MISSING.value)
        assert result["data_source"] == "missing"

    def test_tag_list_wrapped(self):
        """list 应被包装为 dict"""
        from app.api.fund_flow import _tag
        result = _tag([{"a": 1}, {"b": 2}])
        assert "items" in result
        assert result["items"] == [{"a": 1}, {"b": 2}]
        assert result["data_source"] == "real"

    def test_tag_list_with_custom_source(self):
        from app.api.fund_flow import _tag
        from app.utils.data_source import DataSource
        result = _tag([], source=DataSource.MISSING.value)
        assert result == {"items": [], "data_source": "missing"}

    def test_tag_passthrough(self):
        """非 list/dict 应原样返回"""
        from app.api.fund_flow import _tag
        assert _tag("string") == "string"
        assert _tag(42) == 42
        assert _tag(None) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
