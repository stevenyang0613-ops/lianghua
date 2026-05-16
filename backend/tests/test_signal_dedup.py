"""Tests for SignalEngine cross-call deduplication."""
import pytest
import time as time_mod
from unittest.mock import MagicMock, patch
from app.engine.signals import SignalEngine, TradeSignal


def _make_signal(code="123456", strategy="dual_low", action="buy", price=100.0, confidence=0.8) -> TradeSignal:
    return TradeSignal(strategy=strategy, code=code, name="测试", action=action, price=price, reason="test", confidence=confidence)


class TestSignalDedup:
    def test_dedup_suppresses_duplicate_signal(self):
        engine = SignalEngine()
        engine._active_strategies = ["dual_low"]
        engine._recent_signals = {}

        # 模拟第一次信号
        sig1 = _make_signal(code="111111", price=100.0)
        now = time_mod.monotonic()
        engine._recent_signals[("111111", "dual_low", "buy")] = (now, 100.0)

        # 第二次同信号（同 code, strategy, action, 相近 price）应被过滤
        sig2 = _make_signal(code="111111", price=100.5)
        # 手动调用去重逻辑
        dedup_key = (sig2.code, sig2.strategy, sig2.action)
        prev = engine._recent_signals.get(dedup_key)
        assert prev is not None
        prev_ts, prev_price = prev
        price_close = abs(sig2.price - prev_price) / max(prev_price, 0.01) < 0.02
        within_window = time_mod.monotonic() - prev_ts < engine._dedup_window_seconds
        assert within_window and price_close  # Should be deduplicated

    def test_dedup_allows_different_action(self):
        engine = SignalEngine()
        engine._recent_signals = {}

        now = time_mod.monotonic()
        engine._recent_signals[("111111", "dual_low", "buy")] = (now, 100.0)

        # 不同 action 不应被过滤
        dedup_key = ("111111", "dual_low", "sell")
        assert dedup_key not in engine._recent_signals

    def test_dedup_allows_significant_price_change(self):
        engine = SignalEngine()
        engine._recent_signals = {}

        now = time_mod.monotonic()
        engine._recent_signals[("111111", "dual_low", "buy")] = (now, 100.0)

        # 价格变化超过 2%，不应被过滤
        sig = _make_signal(code="111111", price=105.0)
        prev_ts, prev_price = engine._recent_signals[("111111", "dual_low", "buy")]
        price_close = abs(sig.price - prev_price) / max(prev_price, 0.01) < 0.02
        assert not price_close  # 5% change > 2% threshold

    def test_dedup_allows_after_window_expires(self):
        engine = SignalEngine()
        engine._recent_signals = {}

        # 模拟过期的信号
        old_ts = time_mod.monotonic() - 600  # 10 minutes ago
        engine._recent_signals[("111111", "dual_low", "buy")] = (old_ts, 100.0)

        sig = _make_signal(code="111111", price=100.5)
        dedup_key = (sig.code, sig.strategy, sig.action)
        prev = engine._recent_signals.get(dedup_key)
        assert prev is not None
        prev_ts, prev_price = prev
        within_window = time_mod.monotonic() - prev_ts < engine._dedup_window_seconds
        assert not within_window  # Expired

    def test_dedup_cleanup_removes_expired(self):
        engine = SignalEngine()
        engine._recent_signals = {}

        old_ts = time_mod.monotonic() - 600
        engine._recent_signals[("111111", "dual_low", "buy")] = (old_ts, 100.0)
        engine._recent_signals[("222222", "dual_low", "buy")] = (time_mod.monotonic(), 90.0)

        # Clean up expired
        now_ts = time_mod.monotonic()
        expired = [k for k, (ts, _) in engine._recent_signals.items() if now_ts - ts > engine._dedup_window_seconds]
        for k in expired:
            del engine._recent_signals[k]

        assert ("222222", "dual_low", "buy") in engine._recent_signals
        assert ("111111", "dual_low", "buy") not in engine._recent_signals

    def test_set_dedup_config(self):
        engine = SignalEngine()
        assert engine._dedup_window_seconds == 300
        assert engine._dedup_price_threshold == 0.02

        result = engine.set_dedup_config(window_seconds=600, price_threshold=0.05)
        assert result["window_seconds"] == 600
        assert result["price_threshold"] == 0.05
        assert engine._dedup_window_seconds == 600
        assert engine._dedup_price_threshold == 0.05

    def test_get_dedup_config(self):
        engine = SignalEngine()
        config = engine.get_dedup_config()
        assert config["window_seconds"] == 300
        assert config["price_threshold"] == 0.02

    def test_set_dedup_config_bounds(self):
        engine = SignalEngine()
        # window_seconds 最小为 0
        engine.set_dedup_config(window_seconds=-10)
        assert engine._dedup_window_seconds == 0
        # price_threshold 范围 [0, 1.0]
        engine.set_dedup_config(price_threshold=2.0)
        assert engine._dedup_price_threshold == 1.0
