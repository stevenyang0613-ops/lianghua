# backend/tests/test_executed_position_persistence.py
"""Tests for ExecutedPosition persistence to DuckDB."""
import tempfile
import os
from datetime import datetime, timedelta

import pytest

from app.engine.storage import DataStorage
from app.engine.signals import SignalEngine, ExecutedPosition, TradeSignal


@pytest.fixture
def storage(tmp_path):
    """Create a DataStorage instance with a temporary DB."""
    db_path = str(tmp_path / "test_market.db")
    s = DataStorage(db_path=db_path)
    yield s
    s.close()


@pytest.fixture
def engine():
    return SignalEngine()


# --- Storage layer tests ---

def test_save_and_get_executed_position(storage):
    pos = {
        'code': '113044',
        'name': '测试转债A',
        'side': 'buy',
        'price': 120.5,
        'volume': 10,
        'ts': datetime(2025, 1, 15, 10, 30, 0),
    }
    storage.save_executed_position(pos)

    result = storage.get_executed_positions(limit=10)
    assert len(result) == 1
    assert result[0]['code'] == '113044'
    assert result[0]['name'] == '测试转债A'
    assert result[0]['side'] == 'buy'
    assert result[0]['price'] == 120.5
    assert result[0]['volume'] == 10


def test_get_executed_positions_ordered_by_ts_desc(storage):
    for i in range(5):
        storage.save_executed_position({
            'code': f'1130{i}',
            'name': f'转债{i}',
            'side': 'buy',
            'price': 100.0 + i,
            'volume': 10,
            'ts': datetime(2025, 1, i + 1),
        })

    result = storage.get_executed_positions(limit=10)
    assert len(result) == 5
    # Most recent first
    assert result[0]['code'] == '11304'
    assert result[-1]['code'] == '11300'


def test_get_executed_positions_pagination(storage):
    for i in range(5):
        storage.save_executed_position({
            'code': f'1130{i}',
            'name': f'转债{i}',
            'side': 'buy',
            'price': 100.0,
            'volume': 10,
            'ts': datetime(2025, 1, i + 1),
        })

    page1 = storage.get_executed_positions(limit=2, offset=0)
    page2 = storage.get_executed_positions(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    # Pages should not overlap
    codes_p1 = {r['code'] for r in page1}
    codes_p2 = {r['code'] for r in page2}
    assert codes_p1.isdisjoint(codes_p2)


def test_cleanup_executed_positions(storage):
    old_ts = datetime.now() - timedelta(days=60)
    recent_ts = datetime.now() - timedelta(days=5)

    storage.save_executed_position({
        'code': 'OLD001', 'name': '旧转债', 'side': 'buy',
        'price': 100.0, 'volume': 10, 'ts': old_ts,
    })
    storage.save_executed_position({
        'code': 'RECENT01', 'name': '新转债', 'side': 'buy',
        'price': 110.0, 'volume': 10, 'ts': recent_ts,
    })

    deleted = storage.cleanup_executed_positions(keep_days=30)
    assert deleted == 1

    remaining = storage.get_executed_positions(limit=10)
    assert len(remaining) == 1
    assert remaining[0]['code'] == 'RECENT01'


def test_cleanup_executed_positions_nothing_to_delete(storage):
    recent_ts = datetime.now() - timedelta(days=5)
    storage.save_executed_position({
        'code': 'RECENT01', 'name': '新转债', 'side': 'buy',
        'price': 110.0, 'volume': 10, 'ts': recent_ts,
    })

    deleted = storage.cleanup_executed_positions(keep_days=30)
    assert deleted == 0


def test_executed_positions_table_created_on_init(tmp_path):
    """Verify the executed_positions table exists after DataStorage init."""
    db_path = str(tmp_path / "test_table_check.db")
    s = DataStorage(db_path=db_path)
    tables = s.conn.execute("SHOW TABLES").fetchall()
    table_names = [t[0] for t in tables]
    assert 'executed_positions' in table_names
    s.close()


def test_executed_positions_indexes_exist(tmp_path):
    """Verify indexes on executed_positions are created."""
    db_path = str(tmp_path / "test_idx_check.db")
    s = DataStorage(db_path=db_path)
    indexes = s.conn.execute(
        "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'executed_positions'"
    ).fetchall()
    idx_names = {i[0] for i in indexes}
    assert 'idx_exec_pos_ts' in idx_names
    assert 'idx_exec_pos_code' in idx_names
    s.close()


# --- SignalEngine integration tests ---

def test_set_storage_loads_executed_positions(storage):
    """When set_storage is called, it should load saved positions from DB."""
    # Pre-populate the DB
    storage.save_executed_position({
        'code': '113044', 'name': '转债A', 'side': 'buy',
        'price': 120.0, 'volume': 10,
        'ts': datetime(2025, 1, 15, 10, 0, 0),
    })
    storage.save_executed_position({
        'code': '113045', 'name': '转债B', 'side': 'sell',
        'price': 135.0, 'volume': 10,
        'ts': datetime(2025, 1, 15, 11, 0, 0),
    })

    engine = SignalEngine()
    engine.set_storage(storage)

    positions = engine.executed_positions
    assert len(positions) == 2
    # Oldest first in the in-memory list
    codes = [p['code'] for p in positions]
    assert '113044' in codes
    assert '113045' in codes


def test_set_storage_does_not_overwrite_existing_positions(storage):
    """If _executed_positions is already populated, set_storage should not replace them."""
    engine = SignalEngine()
    # Manually add a position before set_storage
    engine._executed_positions.append(ExecutedPosition(
        code='MANUAL', name='手动', side='buy', price=100.0, volume=5,
        ts=datetime.now(),
    ))

    storage.save_executed_position({
        'code': 'DB_ONLY', 'name': '数据库', 'side': 'buy',
        'price': 200.0, 'volume': 10, 'ts': datetime.now(),
    })

    engine.set_storage(storage)
    positions = engine.executed_positions
    # Should keep only the existing one, not load from DB
    assert len(positions) == 1
    assert positions[0]['code'] == 'MANUAL'


def test_auto_execute_saves_to_storage(storage):
    """Auto-executed positions should be persisted to storage."""
    engine = SignalEngine()
    engine.set_storage(storage)
    engine.set_auto_execute_min_confidence(0.5)

    from app.engine.trade import TradeEngine
    trade = TradeEngine()
    engine.set_trade_engine(trade)

    # Create a high-confidence signal
    signal = TradeSignal(
        strategy='dual_low', code='113044', name='测试转债',
        action='buy', price=120.0, reason='test', confidence=0.8,
    )

    engine._auto_execute([signal])

    # Check in-memory
    assert len(engine.executed_positions) == 1

    # Check in DB
    saved = storage.get_executed_positions(limit=10)
    assert len(saved) == 1
    assert saved[0]['code'] == '113044'


def test_cleanup_history_also_cleans_executed_positions(storage):
    """cleanup_history should also clean executed_positions table."""
    old_ts = datetime.now() - timedelta(days=60)
    storage.save_executed_position({
        'code': 'OLD001', 'name': '旧转债', 'side': 'buy',
        'price': 100.0, 'volume': 10, 'ts': old_ts,
    })

    engine = SignalEngine()
    engine.set_storage(storage)
    engine.cleanup_history(keep_days=30)

    remaining = storage.get_executed_positions(limit=10)
    assert len(remaining) == 0


def test_persistence_across_restart(tmp_path):
    """Executed positions should survive a process restart (new DataStorage instance)."""
    db_path = str(tmp_path / "test_restart.db")

    # First session: save a position
    s1 = DataStorage(db_path=db_path)
    s1.save_executed_position({
        'code': '113044', 'name': '转债A', 'side': 'buy',
        'price': 120.0, 'volume': 10,
        'ts': datetime(2025, 3, 15, 10, 0, 0),
    })
    s1.close()

    # Second session: new DataStorage instance, should load the data
    s2 = DataStorage(db_path=db_path)
    result = s2.get_executed_positions(limit=10)
    assert len(result) == 1
    assert result[0]['code'] == '113044'
    s2.close()

    # Third session: new SignalEngine with storage should load on set_storage
    s3 = DataStorage(db_path=db_path)
    engine = SignalEngine()
    engine.set_storage(s3)
    assert len(engine.executed_positions) == 1
    assert engine.executed_positions[0]['code'] == '113044'
    s3.close()
