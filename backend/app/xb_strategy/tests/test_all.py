"""测试七维打分引擎"""
import pytest
from datetime import date
import sys
from pathlib import Path
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.xb_strategy.core.scoring import SevenDimScoringEngine
from app.xb_strategy.core.types import ConvertibleBondData, StockData
from app.xb_strategy.config.weights import MarketRegime


def test_scoring_engine_init():
    """测试打分引擎初始化"""
    engine = SevenDimScoringEngine(MarketRegime.RANGE, 10000.0)
    assert engine.regime == MarketRegime.RANGE
    assert engine.STOCK_TOTAL_SCORE == 55.0
    assert engine.CB_TOTAL_SCORE == 45.0


def test_score_bond():
    """测试单只转债打分"""
    engine = SevenDimScoringEngine(MarketRegime.RANGE, 10000.0)

    cb = ConvertibleBondData(
        code="110001",
        name="测试转债",
        stock_code="000001",
        stock_name="测试股票",
        date=date.today(),
        close=105.0,
        conversion_premium=15.0,
        remaining_years=3.0,
        daily_amount_20d=5000.0,
        implied_vol_percentile=50.0,
        vol_skew=0.1,
    )

    stock = StockData(
        code="000001",
        date=date.today(),
        close=10.0,
        change_pct=2.0,
        volume_ratio=1.5,
        turnover_rate=3.0,
        sector_change_pct=1.0,
        sector_limit_up_count=5,
        sector_total_count=50,
    )

    score = engine.score_bond(cb, stock)

    assert score.cb_code == "110001"
    assert score.total_score > 0
    assert score.stock_total >= 0
    assert score.cb_total >= 0


def test_score_all_bonds():
    """测试批量打分"""
    engine = SevenDimScoringEngine(MarketRegime.RANGE, 10000.0)

    bonds = [
        ConvertibleBondData(
            code=f"11000{i}",
            name=f"测试转债{i}",
            stock_code=f"00000{i}",
            stock_name=f"测试股票{i}",
            date=date.today(),
            close=100.0 + i * 5,
            conversion_premium=10.0 + i * 5,
            remaining_years=3.0,
            daily_amount_20d=5000.0,
        )
        for i in range(5)
    ]

    scores = engine.score_all_bonds(bonds)

    assert len(scores) == 5
    # 检查是否按总分排序
    for i in range(len(scores) - 1):
        assert scores[i].total_score >= scores[i + 1].total_score
        assert scores[i].rank == i + 1


# ==================== V4 → V3 统一映射测试 ====================

class TestV4toV3RegimeMapping:
    """验证 map_v4_to_v3_regime 的正确性"""

    def test_none_returns_range(self):
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime(None) == MarketRegime.RANGE

    def test_strong_bull_maps_to_bull(self):
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime("STRONG_BULL") == MarketRegime.BULL

    def test_bull_maps_to_bull(self):
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime("BULL") == MarketRegime.BULL

    def test_range_maps_to_range(self):
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime("RANGE") == MarketRegime.RANGE

    def test_bear_maps_to_bear(self):
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime("BEAR") == MarketRegime.BEAR

    def test_strong_bear_maps_to_bear(self):
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime("STRONG_BEAR") == MarketRegime.BEAR

    def test_case_insensitive(self):
        """不区分大小写"""
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime("strong_bull") == MarketRegime.BULL

    def test_unknown_regime_falls_back_to_range(self):
        """未知 regime 默认回退到 RANGE"""
        from app.xb_strategy.config.weights import map_v4_to_v3_regime
        assert map_v4_to_v3_regime("UNKNOWN") == MarketRegime.RANGE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
