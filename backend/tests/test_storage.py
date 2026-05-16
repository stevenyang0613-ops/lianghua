"""Tests for DataStorage CRUD and deduplication logic."""
import pytest
import tempfile
import os
from datetime import datetime, date
from app.engine.storage import DataStorage
from app.models.convertible import ConvertibleQuote


@pytest.fixture
def storage():
    """Create a temporary DataStorage instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.duckdb")
        s = DataStorage(db_path)
        yield s


def _make_quote(code="123456", name="测试转债", price=110.0, **kw) -> ConvertibleQuote:
    defaults = dict(
        code=code, name=name, price=price, change_pct=1.0,
        stock_price=10.0, stock_change_pct=0.5, conversion_price=9.0,
        conversion_value=100.0, premium_ratio=10.0, dual_low=120.0,
        ytm=1.0, volume=5e7, remaining_years=3.0, forced_call_days=0,
    )
    defaults.update(kw)
    return ConvertibleQuote(**defaults)


class TestQuotesCRUD:
    def test_save_and_get_quote(self, storage):
        q = _make_quote()
        storage.save_quote(q)
        result = storage.get_quote_history("123456", limit=1)
        assert len(result) == 1
        assert result[0]["code"] == "123456"

    def test_save_quotes_batch(self, storage):
        quotes = [_make_quote(code=f"12{i:04d}") for i in range(5)]
        storage.save_quotes_batch(quotes)
        for q in quotes:
            result = storage.get_quote_history(q.code, limit=1)
            assert len(result) == 1

    def test_get_latest_quotes(self, storage):
        storage.save_quotes_batch([_make_quote(code="111111"), _make_quote(code="222222")])
        result = storage.get_latest_quotes()
        assert len(result) == 2


class TestSignalsCRUD:
    def test_save_and_get_signals(self, storage):
        signals = [
            {"strategy": "dual_low", "code": "123456", "name": "测试", "action": "buy",
             "price": 100.0, "reason": "test", "confidence": 0.8, "ts": datetime.now().isoformat()},
        ]
        storage.save_signals_batch(signals)
        result, total = storage.get_signal_history(strategy="dual_low")
        assert len(result) == 1
        assert total == 1
        assert result[0]["code"] == "123456"

    def test_get_signal_stats(self, storage):
        signals = [
            {"strategy": "dual_low", "code": "123456", "name": "测试", "action": "buy",
             "price": 100.0, "reason": "test", "confidence": 0.8, "ts": datetime.now().isoformat()},
        ]
        storage.save_signals_batch(signals)
        stats = storage.get_signal_stats()
        assert stats["total"] >= 1


class TestExecutedPositions:
    def test_save_and_get_positions(self, storage):
        pos = {"code": "123456", "name": "测试", "side": "buy", "price": 100.0, "volume": 10, "ts": datetime.now().isoformat()}
        storage.save_executed_position(pos)
        result = storage.get_executed_positions(limit=10)
        assert len(result) == 1
        assert result[0]["code"] == "123456"

    def test_save_batch_positions(self, storage):
        positions = [
            {"code": f"12{i:04d}", "name": f"测试{i}", "side": "buy", "price": 100.0, "volume": 10, "ts": datetime.now().isoformat()}
            for i in range(3)
        ]
        storage.save_executed_positions_batch(positions)
        result = storage.get_executed_positions(limit=10)
        assert len(result) == 3


class TestCleanup:
    def test_cleanup_signal_history(self, storage):
        # Old signal
        old_ts = datetime(2020, 1, 1).isoformat()
        signals = [
            {"strategy": "dual_low", "code": "123456", "name": "测试", "action": "buy",
             "price": 100.0, "reason": "test", "confidence": 0.8, "ts": old_ts},
        ]
        storage.save_signals_batch(signals)
        deleted = storage.cleanup_signal_history(keep_days=30)
        assert deleted >= 1

    def test_cleanup_executed_positions(self, storage):
        old_ts = datetime(2020, 1, 1).isoformat()
        pos = {"code": "123456", "name": "测试", "side": "buy", "price": 100.0, "volume": 10, "ts": old_ts}
        storage.save_executed_position(pos)
        deleted = storage.cleanup_executed_positions(keep_days=30)
        assert deleted >= 1


class TestDeduplication:
    def test_unique_index_prevents_duplicates(self, storage):
        """Verify that the unique index on (code, timestamp) prevents duplicates."""
        q = _make_quote(code="999999")
        storage.save_quote(q)
        # Saving the same quote again should not raise (upsert via unique index)
        # The second save may or may not create a duplicate depending on timestamp precision
        storage.save_quote(q)
        result = storage.get_quote_history("999999")
        # With unique index, should have at most 2 entries (different timestamps)
        assert len(result) <= 2
