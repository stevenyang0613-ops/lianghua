"""Tests for SignalEngine strategy caching and TTL"""
import pytest
import time as time_mod
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.engine.signals import SignalEngine
from app.strategies.base import Strategy


class FakeStrategy(Strategy):
    name = "fake"
    description = "fake"
    params = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.init_calls = 0
        self.data_calls = 0

    def on_init(self, data):
        self.init_calls += 1

    def on_data(self, data, idx):
        self.data_calls += 1
        return [{"code": "120000", "action": "buy", "price": 100.0, "reason": "test"}]

    def on_destroy(self):
        self._destroyed = True


class TestStrategyCache:
    def test_cache_reuses_instance_same_day(self):
        """Same-day calls should reuse the cached strategy instance"""
        engine = SignalEngine()
        engine.set_active_strategies(["fake"])

        fake = FakeStrategy()
        with patch("app.engine.signals.get_strategy", return_value=lambda: fake):
            import pandas as pd
            df = pd.DataFrame({"code": ["120000"], "date": [datetime.now().date()], "price": [100.0], "premium_ratio": [10.0], "volume": [1000], "dual_low": [110.0]})
            bonds = [MagicMock(code="120000", name="测试", price=100.0, premium_ratio=10.0, dual_low=110.0, change_pct=0, volume=1000)]

            # First call - creates instance
            engine._process_strategies(df, bonds)
            assert "fake" in engine._strategy_cache
            cached_entry = engine._strategy_cache["fake"]
            first_strategy = cached_entry[0]
            assert first_strategy.init_calls == 1

            # Second call - should reuse
            engine._process_strategies(df, bonds)
            cached_entry2 = engine._strategy_cache["fake"]
            assert cached_entry2[0] is first_strategy
            assert first_strategy.init_calls == 1

    def test_invalidate_cache_specific(self):
        """invalidate_cache with strat_id should only remove that strategy"""
        engine = SignalEngine()
        engine._strategy_cache = {
            "strat_a": (FakeStrategy(), time_mod.monotonic(), ""),
            "strat_b": (FakeStrategy(), time_mod.monotonic(), ""),
        }

        engine.invalidate_cache("strat_a")

        assert "strat_a" not in engine._strategy_cache
        assert "strat_b" in engine._strategy_cache

    def test_invalidate_cache_all(self):
        """invalidate_cache without strat_id should clear all"""
        engine = SignalEngine()
        engine._strategy_cache = {
            "strat_a": (FakeStrategy(), time_mod.monotonic(), ""),
            "strat_b": (FakeStrategy(), time_mod.monotonic(), ""),
        }

        engine.invalidate_cache()

        assert len(engine._strategy_cache) == 0

    def test_ttl_expiry_rebuilds_instance(self):
        """Cached instance older than TTL should be rebuilt"""
        engine = SignalEngine()
        engine.set_active_strategies(["fake"])
        engine._last_init_date = str(datetime.now().date())

        fake_old = FakeStrategy()
        expired_ts = time_mod.monotonic() - engine._CACHE_TTL_SECONDS - 1
        engine._strategy_cache["fake"] = (fake_old, expired_ts, "")

        fake_new = FakeStrategy()
        with patch("app.engine.signals.get_strategy", return_value=lambda: fake_new):
            import pandas as pd
            df = pd.DataFrame({"code": ["120000"], "date": [datetime.now().date()], "price": [100.0], "premium_ratio": [10.0], "volume": [1000], "dual_low": [110.0]})
            bonds = [MagicMock(code="120000", name="测试", price=100.0, premium_ratio=10.0, dual_low=110.0, change_pct=0, volume=1000)]

            engine._process_strategies(df, bonds)

            assert getattr(fake_old, '_destroyed', False)
            new_entry = engine._strategy_cache["fake"]
            assert new_entry[0] is fake_new
            assert new_entry[0].init_calls == 1

    def test_set_active_strategies_cleans_removed(self):
        """Removing a strategy from active list should clean its cache"""
        engine = SignalEngine()
        engine._active_strategies = ["dual_low", "momentum"]
        engine._strategy_cache = {
            "dual_low": (FakeStrategy(), time_mod.monotonic(), ""),
            "momentum": (FakeStrategy(), time_mod.monotonic(), ""),
        }

        engine.set_active_strategies(["dual_low"])

        assert "dual_low" in engine._strategy_cache
        assert "momentum" not in engine._strategy_cache

    def test_params_change_invalidates_cache(self):
        """Changing strategy params should invalidate the cache"""
        engine = SignalEngine()
        engine.set_active_strategies(["fake"])
        engine._last_init_date = str(datetime.now().date())

        fake = FakeStrategy()
        with patch("app.engine.signals.get_strategy", return_value=lambda: fake):
            import pandas as pd
            df = pd.DataFrame({"code": ["120000"], "date": [datetime.now().date()], "price": [100.0], "premium_ratio": [10.0], "volume": [1000], "dual_low": [110.0]})
            bonds = [MagicMock(code="120000", name="测试", price=100.0, premium_ratio=10.0, dual_low=110.0, change_pct=0, volume=1000)]

            # First call - creates instance with empty params
            engine._process_strategies(df, bonds)
            first = engine._strategy_cache["fake"][0]
            assert first.init_calls == 1

            # Change params - should invalidate cache
            engine.set_strategy_params("fake", {"extra_param": 5})
            assert "fake" not in engine._strategy_cache

            # Next call should rebuild with new params
            # The factory function must accept **kwargs
            with patch("app.engine.signals.get_strategy", return_value=lambda **kw: FakeStrategy(**kw)):
                engine._process_strategies(df, bonds)
                second = engine._strategy_cache["fake"][0]
                assert second.init_calls == 1

    def test_same_params_no_invalidation(self):
        """Setting same params should NOT invalidate cache"""
        engine = SignalEngine()
        engine.set_active_strategies(["fake"])
        engine._last_init_date = str(datetime.now().date())

        fake = FakeStrategy()
        with patch("app.engine.signals.get_strategy", return_value=lambda: fake):
            import pandas as pd
            df = pd.DataFrame({"code": ["120000"], "date": [datetime.now().date()], "price": [100.0], "premium_ratio": [10.0], "volume": [1000], "dual_low": [110.0]})
            bonds = [MagicMock(code="120000", name="测试", price=100.0, premium_ratio=10.0, dual_low=110.0, change_pct=0, volume=1000)]

            engine._process_strategies(df, bonds)
            first = engine._strategy_cache["fake"][0]

            # Set same empty params - should not invalidate
            engine.set_strategy_params("fake", {})
            assert "fake" in engine._strategy_cache
            assert engine._strategy_cache["fake"][0] is first
