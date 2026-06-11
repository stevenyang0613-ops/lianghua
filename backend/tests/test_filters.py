"""测试 app.engine.filters 的过滤逻辑（修复 ModuleNotFoundError）。"""
from datetime import date, timedelta
import pytest

from app.engine.filters import (
    is_delisted_bond,
    is_exchangeable_bond,
    is_delisted_or_exchangeable,
    is_tradeable_bond,
)
from app.models.convertible import ConvertibleQuote


# ─────────── is_exchangeable_bond ───────────

class TestIsExchangeableBond:
    def test_eb_code_prefix(self):
        assert is_exchangeable_bond("EB123456", "测试EB") is True

    def test_eb_code_lowercase(self):
        assert is_exchangeable_bond("eb123456", "测试") is True

    def test_regular_convertible(self):
        assert is_exchangeable_bond("113044", "大秦转债") is False

    def test_name_contains_kjjz(self):
        assert is_exchangeable_bond("123456", "中国石油可交换债") is True

    def test_empty_inputs(self):
        assert is_exchangeable_bond("", "") is False


# ─────────── is_delisted_bond ───────────

class TestIsDelistedBond:
    def test_z_prefix_code(self):
        assert is_delisted_bond("Z123456", "测试") is True

    def test_name_contains_delisted(self):
        assert is_delisted_bond("123456", "退市转债") is True

    def test_regular_bond(self):
        assert is_delisted_bond("113044", "大秦转债") is False

    def test_empty_inputs(self):
        assert is_delisted_bond("", "") is False

    def test_name_转退(self):
        assert is_delisted_bond("123099", "普利转退") is True

    def test_name_退债(self):
        assert is_delisted_bond("128001", "搜特退债") is True

    def test_name_退市(self):
        assert is_delisted_bond("123456", "某退市债") is True

    def test_name_含退_not_false_positive(self):
        assert is_delisted_bond("113044", "大秦转债") is False


# ─────────── is_delisted_or_exchangeable ───────────

class TestIsDelistedOrExchangeable:
    def test_combines_both(self):
        assert is_delisted_or_exchangeable("EB123", "EB测试") is True
        assert is_delisted_or_exchangeable("Z123", "退市") is True
        assert is_delisted_or_exchangeable("113044", "大秦转债") is False


# ─────────── is_tradeable_bond ───────────

def _bond(**overrides) -> ConvertibleQuote:
    defaults = {
        "code": "113044", "name": "大秦转债", "price": 120.0,
        "is_called": False, "call_status": "",
    }
    defaults.update(overrides)
    return ConvertibleQuote(**defaults)


class TestIsTradeableBond:
    def test_normal_bond_is_tradeable(self):
        assert is_tradeable_bond(_bond()) is True

    def test_exchangeable_excluded(self):
        assert is_tradeable_bond(_bond(code="EB123456", name="测试EB")) is False

    def test_delisted_excluded(self):
        assert is_tradeable_bond(_bond(code="Z123456", name="退市")) is False

    def test_delisted_转退_excluded(self):
        assert is_tradeable_bond(_bond(code="123099", name="普利转退")) is False

    def test_delisted_退债_excluded(self):
        assert is_tradeable_bond(_bond(code="128001", name="搜特退债")) is False

    def test_zero_price_excluded(self):
        assert is_tradeable_bond(_bond(price=0.0)) is False

    def test_negative_price_excluded(self):
        assert is_tradeable_bond(_bond(price=-1.0)) is False

    def test_none_price_excluded(self):
        bond = _bond()
        bond.price = None  # type: ignore[assignment]
        assert is_tradeable_bond(bond) is False

    def test_already_called_excluded(self):
        assert is_tradeable_bond(_bond(is_called=True)) is False

    def test_call_status_announced_excluded(self):
        assert is_tradeable_bond(_bond(call_status="已公告强赎")) is False
        assert is_tradeable_bond(_bond(call_status="公告要强赎")) is False

    def test_call_status_not_yet_excluded(self):
        # "已满足强赎条件" 尚未公告，应保留
        assert is_tradeable_bond(_bond(call_status="已满足强赎条件")) is True
        # "公告不强赎" 也保留
        assert is_tradeable_bond(_bond(call_status="公告不强赎")) is True

    def test_maturity_within_3_days_excluded(self):
        soon = date.today() + timedelta(days=2)
        assert is_tradeable_bond(_bond(maturity_date=soon)) is False

    def test_last_trade_within_3_days_excluded(self):
        soon = date.today() + timedelta(days=1)
        assert is_tradeable_bond(_bond(last_trade_date=soon)) is False

    def test_maturity_more_than_3_days_ok(self):
        ok_date = date.today() + timedelta(days=30)
        assert is_tradeable_bond(_bond(maturity_date=ok_date)) is True

    def test_maturity_in_past_excluded(self):
        past = date.today() - timedelta(days=1)
        assert is_tradeable_bond(_bond(maturity_date=past)) is False

    def test_explicit_today(self):
        assert is_tradeable_bond(_bond(), today=date.today()) is True

    def test_none_bond_returns_false(self):
        assert is_tradeable_bond(None) is False  # type: ignore[arg-type]

    def test_handles_string_date(self):
        # 字符串日期应能解析
        b = _bond(maturity_date="2099-12-31")
        assert is_tradeable_bond(b) is True
