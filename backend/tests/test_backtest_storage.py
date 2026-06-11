"""Tests for backtest result persistence in DataStorage."""
import pytest
import tempfile
import os
from datetime import datetime
from app.engine.storage import DataStorage


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_backtest.db")
        s = DataStorage(db_path)
        yield s


class TestBacktestResultsCRUD:
    def test_save_and_get_backtest_result(self, storage):
        backtest_id = storage.save_backtest_result(
            summary={"avg_return_pct": 5.2, "avg_win_rate": 60.0, "total_periods": 10},
            details=[
                {"date": "2025-01-01", "end_date": "2025-01-06", "top_n": 20,
                 "avg_return_pct": 3.1, "win_rate": 55.0, "max_return": 8.0, "min_return": -2.0},
                {"date": "2025-01-06", "end_date": "2025-01-11", "top_n": 20,
                 "avg_return_pct": 7.3, "win_rate": 65.0, "max_return": 12.0, "min_return": -1.5},
            ],
            params={"startDate": "2025-01-01", "endDate": "2025-03-01", "topN": 20, "holdDays": 5},
        )
        assert isinstance(backtest_id, int)
        assert backtest_id > 0

        results, total = storage.get_backtest_results(limit=10)
        assert len(results) == 1
        assert total == 1
        assert results[0]["avg_return_pct"] == 5.2
        assert results[0]["win_rate"] == 60.0
        assert results[0]["total_periods"] == 10

    def test_get_backtest_details(self, storage):
        backtest_id = storage.save_backtest_result(
            summary={"avg_return_pct": 2.0, "avg_win_rate": 50.0, "total_periods": 2},
            details=[
                {"date": "2025-01-01", "end_date": "2025-01-06", "top_n": 20,
                 "avg_return_pct": 1.0, "win_rate": 45.0, "max_return": 5.0, "min_return": -3.0},
                {"date": "2025-01-06", "end_date": "2025-01-11", "top_n": 20,
                 "avg_return_pct": 3.0, "win_rate": 55.0, "max_return": 7.0, "min_return": -1.0},
            ],
            params={"startDate": "2025-01-01", "endDate": "2025-02-01", "topN": 20, "holdDays": 5},
        )

        details = storage.get_backtest_details(backtest_id)
        assert len(details) == 2
        assert details[0]["avg_return_pct"] == 1.0
        assert details[1]["avg_return_pct"] == 3.0

    def test_save_backtest_without_details(self, storage):
        backtest_id = storage.save_backtest_result(
            summary={"avg_return_pct": 0.0, "avg_win_rate": 0.0, "total_periods": 0},
            details=[],
            params={"startDate": "2025-01-01", "endDate": "2025-02-01", "topN": 30, "holdDays": 10},
        )
        assert backtest_id > 0
        details = storage.get_backtest_details(backtest_id)
        assert len(details) == 0

    def test_multiple_backtest_results_ordered_by_ts(self, storage):
        storage.save_backtest_result(
            summary={"avg_return_pct": 1.0, "avg_win_rate": 40.0, "total_periods": 5},
            details=[], params={"startDate": "2025-01-01", "endDate": "2025-02-01", "topN": 20, "holdDays": 5},
        )
        storage.save_backtest_result(
            summary={"avg_return_pct": 2.0, "avg_win_rate": 50.0, "total_periods": 5},
            details=[], params={"startDate": "2025-02-01", "endDate": "2025-03-01", "topN": 20, "holdDays": 5},
        )
        results, total = storage.get_backtest_results(limit=10)
        assert len(results) == 2
        assert total == 2
        assert results[0]["avg_return_pct"] == 2.0
        assert results[1]["avg_return_pct"] == 1.0

    def test_backtest_results_limit_and_offset(self, storage):
        for i in range(5):
            storage.save_backtest_result(
                summary={"avg_return_pct": float(i), "avg_win_rate": 50.0, "total_periods": 1},
                details=[], params={"startDate": "2025-01-01", "endDate": "2025-02-01", "topN": 20, "holdDays": 5},
            )
        results, total = storage.get_backtest_results(limit=3)
        assert len(results) == 3
        assert total == 5

        # Test offset
        results2, _ = storage.get_backtest_results(limit=3, offset=3)
        assert len(results2) == 2

    def test_get_backtest_details_nonexistent(self, storage):
        details = storage.get_backtest_details(99999)
        assert len(details) == 0

    def test_delete_backtest_result(self, storage):
        backtest_id = storage.save_backtest_result(
            summary={"avg_return_pct": 1.0, "avg_win_rate": 50.0, "total_periods": 1},
            details=[
                {"date": "2025-01-01", "end_date": "2025-01-06", "top_n": 20,
                 "avg_return_pct": 1.0, "win_rate": 50.0, "max_return": 3.0, "min_return": -1.0},
            ],
            params={"startDate": "2025-01-01", "endDate": "2025-02-01", "topN": 20, "holdDays": 5},
        )
        assert storage.delete_backtest_result(backtest_id) is True
        assert storage.get_backtest_details(backtest_id) == []
        results, _ = storage.get_backtest_results(limit=100)
        assert all(r["id"] != backtest_id for r in results)

    def test_delete_nonexistent_backtest(self, storage):
        assert storage.delete_backtest_result(99999) is False

    def test_cleanup_backtest_results(self, storage):
        storage.save_backtest_result(
            summary={"avg_return_pct": 1.0, "avg_win_rate": 50.0, "total_periods": 1},
            details=[], params={"startDate": "2025-01-01", "endDate": "2025-02-01", "topN": 20, "holdDays": 5},
        )
        storage.conn.execute("UPDATE backtest_results SET run_ts = '2020-01-01' WHERE id = 1")

        deleted = storage.cleanup_backtest_results(keep_days=30)
        assert deleted >= 1
        results, _ = storage.get_backtest_results(limit=100)
        assert all(r["id"] != 1 for r in results)
