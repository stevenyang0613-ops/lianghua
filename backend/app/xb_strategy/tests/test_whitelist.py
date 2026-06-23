"""测试白名单轮换引擎"""
import pytest
from datetime import date
import sys
from pathlib import Path
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.xb_strategy.core.whitelist import WhitelistManager, EnhancedWhitelistManager
from app.xb_strategy.core.types import SevenDimScore, Portfolio, Position
from app.xb_strategy.config.weights import MarketRegime


def test_whitelist_init():
    """测试白名单管理器初始化"""
    wm = WhitelistManager(10000.0, MarketRegime.RANGE)
    assert wm.aum == 10000.0
    assert wm.regime == MarketRegime.RANGE


def test_update_whitelist():
    """测试更新白名单"""
    wm = WhitelistManager(10000.0, MarketRegime.RANGE)

    scores = [
        SevenDimScore(cb_code=f"11000{i}", date=date.today(), total_score=80.0 - i * 5)
        for i in range(70)
    ]

    state = wm.update_whitelist(scores, date.today())

    assert len(state.whitelist) == 60  # 震荡市60只
    assert len(state.buffer_zone) == 10  # 55-65


def test_check_position():
    """测试持仓检查"""
    wm = WhitelistManager(10000.0, MarketRegime.RANGE)

    # 先更新白名单
    scores = [
        SevenDimScore(cb_code=f"11000{i}", date=date.today(), total_score=80.0 - i * 5)
        for i in range(70)
    ]
    wm.update_whitelist(scores, date.today())

    # 在白名单内的持仓
    pos_in = Position(cb_code="110001", cb_name="测试1", quantity=100, current_price=100)
    score_in = scores[1]

    should_keep, reason = wm.check_position(pos_in, score_in)
    assert should_keep

    # 不在白名单的持仓
    pos_out = Position(cb_code="110070", cb_name="测试70", quantity=100, current_price=100)
    score_out = scores[-1]

    should_keep, reason = wm.check_position(pos_out, score_out)
    assert not should_keep


def test_rebalance_frequency():
    """测试调仓频率"""
    # 小规模 - 每日调仓
    wm_small = WhitelistManager(5000.0, MarketRegime.RANGE)
    assert wm_small.get_rebalance_frequency() == "daily"

    # 中等规模 - 每日调仓
    wm_medium = WhitelistManager(30000.0, MarketRegime.RANGE)
    assert wm_medium.get_rebalance_frequency() == "daily"

    # 大规模 - 每周两次
    wm_large = WhitelistManager(80000.0, MarketRegime.RANGE)
    assert wm_large.get_rebalance_frequency() == "weekly"


def test_position_limit():
    """测试仓位限制"""
    wm = WhitelistManager(10000.0, MarketRegime.RANGE)

    # 极品评分
    score_excellent = SevenDimScore(cb_code="110001", date=date.today(), total_score=88.0)
    limit, level = wm.get_position_limit(score_excellent)
    assert limit == 0.05  # 5%
    assert level == "极品"

    # 良好评分
    score_good = SevenDimScore(cb_code="110002", date=date.today(), total_score=72.0)
    limit, level = wm.get_position_limit(score_good)
    assert limit == pytest.approx(0.02)  # 2%
    assert level == "良好"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
