"""TDD 测试: volume 字段默认填充逻辑"""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

from app.adapters.akshare import AKShareAdapter
from app.models.convertible import ConvertibleQuote


class TestAKShareVolumeFilling:
    """测试 volume 字段的默认填充逻辑"""

    def test_spot_data_provides_volume(self):
        """当 spot 接口有数据时，应该有 volume"""
        adapter = AKShareAdapter()

        # 模拟 spot 接口返回带 volume 的数据
        mock_spot_df = pd.DataFrame({
            'symbol': ['128139'],
            'name': ['测绘转债'],
            'trade': [145.5],
            'volume': [1234567.89],
        })

        with patch('akshare.bond_zh_hs_cov_spot', return_value=mock_spot_df):
            adapter._cache = None
            adapter._cache_time = None
            result = adapter._row_to_quote(mock_spot_df.iloc[0])

            assert result is not None
            assert result.code == '128139'
            assert result.volume == 1234567.89

    def test_cov_data_fallback_has_no_volume(self):
        """当 fallback 到 cov 接口时，volume 为 0（cov 接口无 volume）"""
        adapter = AKShareAdapter()

        # 模拟 cov 接口返回数据（无 volume 列）
        mock_cov_df = pd.DataFrame({
            '债券代码': ['128139'],
            '债券简称': ['测绘转债'],
            '债现价': [145.5],
            '转股价值': [140.0],
            '转股溢价率': [3.93],
            '转股价': [16.77],
            '正股价': [15.89],
        })

        result = adapter._row_to_quote(mock_cov_df.iloc[0])

        assert result is not None
        assert result.code == '128139'
        # 注意：cov 数据没有 volume，所以为 0
        assert result.volume == 0.0

    def test_volume_filling_from_bond_zh_cov(self):
        """测试能否从 bond_zh_cov 获取 volume（如果有的话）"""
        adapter = AKShareAdapter()

        # 检查 bond_zh_cov 是否有 volume 相关列
        try:
            import akshare as ak
            df = ak.bond_zh_cov()
            columns = df.columns.tolist()
            volume_columns = [c for c in columns if 'volume' in c.lower() or '成交' in c]
            print(f"[DEBUG] bond_zh_cov columns with volume: {volume_columns}")
        except Exception as e:
            print(f"[DEBUG] bond_zh_cov error: {e}")

    def test_empty_price_becomes_zero(self):
        """测试 price 为空时会被设置为 0 而不是返回 None"""
        adapter = AKShareAdapter()

        mock_df = pd.DataFrame({
            '债券代码': ['128139'],
            '债券简称': ['测绘转债'],
            '债现价': [None],  # 价格为空
            'volume': [None],  # volume 为空
        })

        result = adapter._row_to_quote(mock_df.iloc[0])
        # price 为 None 时 _safe_float 返回 0.0，但代码仍会返回有效 quote
        assert result is not None
        assert result.price == 0.0

    def test_volume_zero_filter_not_applied(self):
        """验证 volume=0 的记录不会被过滤掉"""
        adapter = AKShareAdapter()

        mock_cov_df = pd.DataFrame({
            '债券代码': ['128139'],
            '债券简称': ['测绘转债'],
            '债现价': [145.5],
            '转股价值': [140.0],
            '转股溢价率': [3.93],
            '转股价': [16.77],
            '正股价': [15.89],
        })

        result = adapter._row_to_quote(mock_cov_df.iloc[0])
        assert result is not None
        # volume=0 不应被过滤
        assert result.volume == 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])