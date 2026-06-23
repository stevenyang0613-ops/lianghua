"""测试一票否决过滤"""
import pytest
from datetime import date, timedelta
import sys
from pathlib import Path
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent.parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.xb_strategy.core.filters import VetoFilter, VetoResult
from app.xb_strategy.core.types import ConvertibleBondData, StockData


def test_veto_filter_init():
    """测试过滤器初始化"""
    veto = VetoFilter(10000.0)
    assert veto.aum == 10000.0


def test_veto_high_premium():
    """测试高溢价率一票否决"""
    veto = VetoFilter(10000.0)

    cb = ConvertibleBondData(
        code="110001",
        name="测试转债",
        stock_code="000001",
        stock_name="测试股票",
        date=date.today(),
        close=150.0,
        conversion_premium=120.0,  # 超过100%
        remaining_years=3.0,
        daily_amount_20d=5000.0,
    )

    result = veto.check_all(cb)
    assert not result.passed
    assert any("溢价率" in r for r in result.veto_reasons)


def test_veto_short_maturity():
    """测试临近到期一票否决"""
    veto = VetoFilter(10000.0)

    cb = ConvertibleBondData(
        code="110001",
        name="测试转债",
        stock_code="000001",
        stock_name="测试股票",
        date=date.today(),
        close=100.0,
        conversion_premium=20.0,
        remaining_years=0.3,  # < 0.5年
        daily_amount_20d=5000.0,
    )

    result = veto.check_all(cb)
    assert not result.passed
    assert any("剩余期限" in r for r in result.veto_reasons)


def test_veto_low_liquidity():
    """测试流动性不足一票否决"""
    veto = VetoFilter(50000.0)  # 5亿规模，需要2000万流动性

    cb = ConvertibleBondData(
        code="110001",
        name="测试转债",
        stock_code="000001",
        stock_name="测试股票",
        date=date.today(),
        close=100.0,
        conversion_premium=20.0,
        remaining_years=3.0,
        daily_amount_20d=500.0,  # 低于阈值
    )

    result = veto.check_all(cb)
    assert not result.passed
    assert any("成交额" in r for r in result.veto_reasons)


def test_veto_st_stock():
    """测试ST股票一票否决"""
    veto = VetoFilter(10000.0)

    cb = ConvertibleBondData(
        code="110001",
        name="测试转债",
        stock_code="000001",
        stock_name="测试股票",
        date=date.today(),
        close=100.0,
        conversion_premium=20.0,
        remaining_years=3.0,
        daily_amount_20d=5000.0,
    )

    stock = StockData(
        code="000001",
        date=date.today(),
        close=5.0,
        is_st=True,  # ST股票
    )

    result = veto.check_all(cb, stock)
    assert not result.passed
    assert any("ST" in r for r in result.veto_reasons)


def test_veto_pass():
    """测试通过过滤"""
    veto = VetoFilter(10000.0)

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
    )

    stock = StockData(
        code="000001",
        date=date.today(),
        close=10.0,
        is_st=False,
    )

    result = veto.check_all(cb, stock)
    assert result.passed
    assert len(result.veto_reasons) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
