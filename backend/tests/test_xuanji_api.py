"""璇玑API端点测试"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.api.xuanji import (
    _normalize_rank, _detect_market_state, _compute_xuanji_scores,
    _compute_greeks, MARKET_WEIGHTS, FACTOR_NAMES
)


class TestXuanjiHelpers:
    """测试璇玑API辅助函数"""

    def test_normalize_rank_empty(self):
        """空Series应该返回0.5"""
        import pandas as pd
        s = pd.Series([], dtype=float)
        result = _normalize_rank(s)
        assert len(result) == 0

    def test_normalize_rank_basic(self):
        """基本排名归一化"""
        import pandas as pd
        s = pd.Series([10, 30, 20, 50, 40])
        result = _normalize_rank(s, ascending=True)
        # 最小值(10)的归一化排名为0
        assert result.min() == 0.0
        # 最大值(50)的归一化排名应为 (5-1)/5 = 0.8 (公式: (rank-1)/max_rank)
        assert abs(result.max() - 0.8) < 0.01
        # 所有值在[0, 1)之间
        assert all(0 <= v < 1 for v in result)

    def test_normalize_rank_descending(self):
        """降序排名"""
        import pandas as pd
        s = pd.Series([10, 30, 20])
        result = _normalize_rank(s, ascending=False)
        # 降序时最大值(30)排名为0
        assert result.min() == 0.0
        # 最小值(10)排名为 (3-1)/3 ≈ 0.667
        assert abs(result.max() - 0.667) < 0.01
        # 所有值在[0, 1)之间
        assert all(0 <= v < 1 for v in result)

    def test_market_state_detection(self):
        """市场状态自动检测"""
        import pandas as pd
        # 极端牛
        df = pd.DataFrame({"price": [145] * 5, "premium_ratio": [10] * 5})
        assert _detect_market_state(df) == "extreme_bull"
        # 温和牛
        df = pd.DataFrame({"price": [130] * 5, "premium_ratio": [30] * 5})
        assert _detect_market_state(df) == "mild_bull"
        # 极端熊
        df = pd.DataFrame({"price": [100] * 5, "premium_ratio": [40] * 5})
        assert _detect_market_state(df) == "extreme_bear"
        # 温和熊
        df = pd.DataFrame({"price": [108] * 5, "premium_ratio": [60] * 5})
        assert _detect_market_state(df) == "mild_bear"
        # 震荡
        df = pd.DataFrame({"price": [115] * 5, "premium_ratio": [30] * 5})
        assert _detect_market_state(df) == "neutral"
        # 空DataFrame
        assert _detect_market_state(pd.DataFrame()) == "neutral"

    def test_compute_xuanji_scores_neutral(self):
        """测试震荡市场评分计算"""
        import pandas as pd
        df = pd.DataFrame({
            "code": ["A", "B", "C", "D", "E"],
            "price": [110, 120, 130, 100, 115],
            "premium_ratio": [30, 25, 40, 50, 35],
            "dual_low": [140, 145, 170, 150, 150],
            "hv": [20, 25, 30, 35, 22],
            "ytm": [1, 0, -1, 2, 1.5],
        })
        result = _compute_xuanji_scores(df.copy(), "neutral")
        assert "score" in result.columns
        assert "score_dual_low" in result.columns
        assert "score_hv" in result.columns
        assert "vol_factor" in result.columns
        # score应在0-1之间
        assert all(0 <= s <= 1 for s in result['score'])

    def test_compute_xuanji_scores_market_weights(self):
        """测试不同市场状态使用不同权重"""
        import pandas as pd
        df = pd.DataFrame({
            "code": ["A", "B", "C"],
            "price": [110, 120, 130],
            "premium_ratio": [30, 25, 40],
            "dual_low": [140, 145, 170],
            "hv": [20, 25, 30],
            "ytm": [1, 0, -1],
        })
        score_neutral = _compute_xuanji_scores(df.copy(), "neutral")['score'].tolist()
        score_extreme_bull = _compute_xuanji_scores(df.copy(), "extreme_bull")['score'].tolist()
        # 不同状态应该有不同评分
        assert score_neutral != score_extreme_bull

    def test_compute_greeks_basic(self):
        """测试Greeks计算"""
        bond = MagicMock()
        bond.price = 120
        bond.conversion_value = 110
        bond.premium_ratio = 9  # 9% 转股溢价
        bond.stock_price = 100
        bond.change_pct = 1
        greeks = _compute_greeks(bond)
        assert "delta" in greeks
        assert "gamma" in greeks
        assert "vega" in greeks
        assert "theta" in greeks
        assert "iv" in greeks
        assert 0 < greeks['delta'] < 1

    def test_compute_greeks_high_delta(self):
        """测试高Delta(深度股性)情况"""
        bond = MagicMock()
        bond.price = 110
        bond.conversion_value = 108
        bond.premium_ratio = 2
        bond.stock_price = 100
        bond.change_pct = 1
        greeks = _compute_greeks(bond)
        # 深度股性, delta应该很高
        assert greeks['delta'] > 0.8

    def test_market_weights_integrity(self):
        """测试所有市场状态权重总和为1"""
        for state, weights in MARKET_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.01, f"{state}: sum={total}"

    def test_factor_names_completeness(self):
        """测试因子名称映射完整性"""
        required = ["dual_low", "momentum", "hv", "quality", "valuation", "ytm", "event", "delta"]
        for f in required:
            assert f in FACTOR_NAMES
            assert FACTOR_NAMES[f] is not None
            assert len(FACTOR_NAMES[f]) > 0


class TestXuanjiEndpointStructure:
    """测试端点结构"""

    def test_market_weights_endpoint(self):
        """测试市场权重响应结构"""
        from app.api.xuanji import get_market_weights
        # 同步函数, 直接调用
        result = None
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(get_market_weights())
        finally:
            loop.close()
        assert "states" in result
        assert len(result["states"]) == 5
        for state in result["states"]:
            assert "value" in state
            assert "label_cn" in state
            assert "weights" in state

    def test_alpha_sources_endpoint(self):
        """测试alpha源响应"""
        from app.api.xuanji import get_alpha_sources
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(get_alpha_sources())
        finally:
            loop.close()
        assert "sources" in result
        assert len(result["sources"]) == 12
        ids = [s["id"] for s in result["sources"]]
        assert ids == [f"A{i}" for i in range(1, 13)]
        for s in result["sources"]:
            assert s["status"] == "active"

    def test_health_endpoint(self):
        """测试健康检查"""
        from app.api.xuanji import xuanji_health
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(xuanji_health())
        finally:
            loop.close()
        assert result["status"] == "ok"
        assert result["strategy"] == "xuanji_twelve_factor"
        assert result["version"] == "3.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
