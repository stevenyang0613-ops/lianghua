"""Tests for strategy params and cache management API endpoints."""
import pytest
from unittest.mock import MagicMock, patch
from app.engine.signals import SignalEngine


class TestStrategyParams:
    def test_set_params_stored(self):
        engine = SignalEngine()
        with patch("app.api.signals.list_strategies", return_value=[{"id": "dual_low"}, {"id": "momentum"}]):
            engine.set_strategy_params("dual_low", {"threshold": 130})
        assert engine._strategy_params["dual_low"] == {"threshold": 130}

    def test_set_params_invalidates_cache(self):
        engine = SignalEngine()
        fake = MagicMock()
        engine._strategy_cache = {"dual_low": (fake, 0, "")}

        engine.set_strategy_params("dual_low", {"threshold": 130})

        assert "dual_low" not in engine._strategy_cache
        assert fake.on_destroy.called

    def test_same_params_no_invalidation(self):
        engine = SignalEngine()
        fake = MagicMock()
        engine._strategy_cache = {"dual_low": (fake, 0, "dual_low:[('threshold', 130)]")}
        engine._strategy_params = {"dual_low": {"threshold": 130}}

        engine.set_strategy_params("dual_low", {"threshold": 130})

        assert "dual_low" in engine._strategy_cache

    def test_invalidate_specific_strategy(self):
        engine = SignalEngine()
        fake_a = MagicMock()
        fake_b = MagicMock()
        engine._strategy_cache = {
            "dual_low": (fake_a, 0, ""),
            "momentum": (fake_b, 0, ""),
        }

        engine.invalidate_cache("dual_low")

        assert "dual_low" not in engine._strategy_cache
        assert "momentum" in engine._strategy_cache
        assert fake_a.on_destroy.called
        assert not fake_b.on_destroy.called

    def test_invalidate_all_cache(self):
        engine = SignalEngine()
        fake_a = MagicMock()
        fake_b = MagicMock()
        engine._strategy_cache = {
            "dual_low": (fake_a, 0, ""),
            "momentum": (fake_b, 0, ""),
        }

        engine.invalidate_cache()

        assert len(engine._strategy_cache) == 0
        assert fake_a.on_destroy.called
        assert fake_b.on_destroy.called

    def test_invalidate_nonexistent_strategy(self):
        engine = SignalEngine()
        engine.invalidate_cache("nonexistent")
        assert len(engine._strategy_cache) == 0

    def test_params_signature_deterministic(self):
        sig1 = SignalEngine._params_signature("dual_low", {"threshold": 130, "mode": "strict"})
        sig2 = SignalEngine._params_signature("dual_low", {"mode": "strict", "threshold": 130})
        assert sig1 == sig2

    def test_params_signature_empty(self):
        sig = SignalEngine._params_signature("dual_low", {})
        assert sig == ""
