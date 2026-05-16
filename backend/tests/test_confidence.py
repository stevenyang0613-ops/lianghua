"""Tests for app/engine/confidence.py — confidence calculation module."""
import pytest
from app.engine.confidence import (
    calc_confidence,
    register_confidence_calculator,
    _default_confidence,
    _confidence_calculators,
)
from app.models.convertible import ConvertibleQuote


def _make_bond(**overrides) -> ConvertibleQuote:
    defaults = dict(
        code="123456", name="测试转债", price=110.0,
        change_pct=1.0, dual_low=140.0, premium_ratio=15.0, volume=5e7,
    )
    defaults.update(overrides)
    return ConvertibleQuote(**defaults)


class TestDefaultConfidence:
    def test_bond_none_returns_half(self):
        assert calc_confidence("dual_low", None, {}) == 0.5

    def test_dual_low_very_low(self):
        bond = _make_bond(dual_low=120, premium_ratio=5)
        score = calc_confidence("dual_low", bond, {})
        assert score > 0.5

    def test_dual_low_medium(self):
        bond = _make_bond(dual_low=140, premium_ratio=15)
        score = calc_confidence("dual_low", bond, {})
        assert 0.5 < score < 1.0

    def test_low_premium_strategy(self):
        bond = _make_bond(premium_ratio=3)
        score = calc_confidence("low_premium", bond, {})
        assert score > 0.5

    def test_momentum_strategy_high_change(self):
        bond = _make_bond(change_pct=3.5, volume=2e8)
        score = calc_confidence("momentum", bond, {})
        assert score > 0.5

    def test_momentum_strategy_low_change(self):
        bond = _make_bond(change_pct=0.5, volume=1e7)
        score = calc_confidence("momentum", bond, {})
        assert score == 0.5

    def test_unknown_strategy_defaults(self):
        bond = _make_bond()
        score = calc_confidence("unknown_strat", bond, {})
        assert score == 0.5

    def test_score_capped_at_one(self):
        bond = _make_bond(dual_low=100, premium_ratio=0)
        score = calc_confidence("dual_low", bond, {})
        assert score <= 1.0


class TestRegisterConfidenceCalculator:
    def setup_method(self):
        _confidence_calculators.clear()

    def teardown_method(self):
        _confidence_calculators.clear()

    def test_register_and_use_custom(self):
        register_confidence_calculator("my_strat", lambda bond, sig: 0.88)
        score = calc_confidence("my_strat", _make_bond(), {})
        assert score == 0.88

    def test_custom_overrides_default(self):
        register_confidence_calculator("dual_low", lambda bond, sig: 0.99)
        score = calc_confidence("dual_low", _make_bond(), {})
        assert score == 0.99

    def test_unregister_falls_back_to_default(self):
        register_confidence_calculator("temp_strat", lambda b, s: 0.77)
        assert calc_confidence("temp_strat", _make_bond(), {}) == 0.77
        del _confidence_calculators["temp_strat"]
        score = calc_confidence("temp_strat", _make_bond(), {})
        assert score == 0.5

    def test_custom_receives_bond_and_signal(self):
        calls = []
        def tracker(bond, sig):
            calls.append((bond.code, sig.get("action")))
            return 0.6
        register_confidence_calculator("tracker_strat", tracker)
        calc_confidence("tracker_strat", _make_bond(code="789"), {"action": "buy"})
        assert len(calls) == 1
        assert calls[0] == ("789", "buy")
