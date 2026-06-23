"""Tests for SignalEngine._auto_execute method."""
import pytest
from unittest.mock import MagicMock, PropertyMock, call
from datetime import datetime

from app.engine.signals import SignalEngine, TradeSignal, ExecutedPosition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(code='120001', action='buy', strategy='dual_low',
                 price=100.0, confidence=0.8, executed=False):
    """Build a TradeSignal with sensible defaults."""
    sig = TradeSignal(
        strategy=strategy,
        code=code,
        name=f'债{code}',
        action=action,
        price=price,
        reason='test',
        confidence=confidence,
    )
    sig.executed = executed
    return sig


def _make_mock_position(code='120001', volume=10):
    pos = MagicMock()
    pos.code = code
    pos.volume = volume
    return pos


def _make_engine_with_mocks(cash=100000.0, positions=None):
    """Create a SignalEngine wired up with mocked trade_engine and storage."""
    engine = SignalEngine()
    engine.set_auto_execute_min_confidence(0.5)

    trade_engine = MagicMock()
    # account.cash must be a real float so division works
    account = MagicMock()
    account.cash = cash
    trade_engine.account = account
    trade_engine.positions = positions or []
    engine.set_trade_engine(trade_engine)

    storage = MagicMock()
    storage.get_config.return_value = None
    engine.set_storage(storage)
    # Prevent _load_executed_positions from interfering
    storage.get_executed_positions.return_value = []

    return engine, trade_engine, storage


# ---------------------------------------------------------------------------
# 1. Sell before buy ordering
# ---------------------------------------------------------------------------

def test_sell_executed_before_buy():
    """Signals with action='sell' must be processed before action='buy'."""
    engine, trade_engine, storage = _make_engine_with_mocks(
        cash=50000.0,
        positions=[_make_mock_position(code='120001', volume=20)],
    )

    signals = [
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.9),
        _make_signal(code='120001', action='sell', price=110.0, confidence=0.9),
        _make_signal(code='120003', action='buy', price=90.0, confidence=0.8),
    ]

    engine._auto_execute(signals)

    # Verify call order: sell first, then buys
    call_order = [c[0] for c in trade_engine.method_calls]
    assert call_order[0] == 'sell', f"Expected 'sell' first, got {call_order[0]}"
    sell_idx = next(i for i, c in enumerate(trade_engine.method_calls) if c[0] == 'sell')
    buy_indices = [i for i, c in enumerate(trade_engine.method_calls) if c[0] == 'buy']
    for bi in buy_indices:
        assert bi > sell_idx, "All buys must come after sell"


# ---------------------------------------------------------------------------
# 2. Remaining count decrements per buy
# ---------------------------------------------------------------------------

def test_remaining_count_decrements_per_buy():
    """Each buy decrements remaining cash, affecting volume allocation."""
    cash = 1000.0
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash)

    # 3 buy signals at price=100 => alloc per buy = cash / count (fixed denominator)
    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.9),
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.8),
        _make_signal(code='120003', action='buy', price=100.0, confidence=0.7),
    ]

    engine._auto_execute(signals)

    # alloc = cash / count (fixed denominator), then remaining_cash decreases by volume*price
    # buy1: alloc = 1000/3 ≈ 333.3, volume = 3, remaining = 700
    # buy2: alloc = 700/3 ≈ 233.3, volume = 2, remaining = 500
    # buy3: alloc = 500/3 ≈ 166.6, volume = 1, remaining = 400
    buy_calls = trade_engine.buy.call_args_list
    assert len(buy_calls) == 3

    volumes = [c.kwargs['volume'] for c in buy_calls]

    assert volumes[0] == 3, f"First buy volume should be 3, got {volumes[0]}"
    assert volumes[1] == 2, f"Second buy volume should be 2, got {volumes[1]}"
    assert volumes[2] == 1, f"Third buy volume should be 1, got {volumes[2]}"


# ---------------------------------------------------------------------------
# 3. Cash allocation formula
# ---------------------------------------------------------------------------

def test_cash_allocation_formula():
    """Buy volume = max(1, int(cash / count / price)). Cash decreases only on success."""
    cash = 1000.0
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash)

    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.9),
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.8),
    ]

    engine._auto_execute(signals)

    buy_calls = trade_engine.buy.call_args_list
    assert len(buy_calls) == 2

    # alloc = 1000/2 = 500, volume = int(500/100) = 5
    # After first buy, remaining = 500, second alloc = 500/2 = 250, volume = 2
    v1 = buy_calls[0].kwargs['volume']
    assert v1 == 5, f"First buy volume should be 5, got {v1}"

    v2 = buy_calls[1].kwargs['volume']
    assert v2 == 2, f"Second buy volume should be 2, got {v2}"


def test_cash_allocation_minimum_volume_is_1():
    """When cash is very low, volume is at least 1."""
    cash = 50.0  # Not enough for 1 lot at price=100
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash)

    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.9),
    ]

    engine._auto_execute(signals)

    buy_calls = trade_engine.buy.call_args_list
    assert len(buy_calls) == 1
    v = buy_calls[0].kwargs['volume']
    assert v >= 1, f"Volume should be at least 1, got {v}"


# ---------------------------------------------------------------------------
# 4. Sell frees cash for buy
# ---------------------------------------------------------------------------

def test_sell_frees_cash_for_buy():
    """Selling a position first increases cash available for subsequent buys."""
    cash = 200.0  # Very little cash
    positions = [_make_mock_position(code='120001', volume=20)]
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash, positions=positions)

    # Make sell succeed and increase account.cash for the buy step
    original_cash = cash

    def _sell_side_effect(*args, **kwargs):
        # Simulate cash freed by sell
        trade_engine.account.cash = original_cash + 2000.0
        return MagicMock()

    trade_engine.sell.side_effect = _sell_side_effect

    signals = [
        _make_signal(code='120001', action='sell', price=110.0, confidence=0.9),
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.8),
    ]

    engine._auto_execute(signals)

    # Sell should have been called
    trade_engine.sell.assert_called_once()
    # Buy should also succeed (cash now 2200)
    trade_engine.buy.assert_called_once()
    buy_call = trade_engine.buy.call_args
    v = buy_call.kwargs['volume']
    # alloc = 2200 / 1 = 2200, volume = int(2200/100) = 22
    assert v == 22, f"Buy volume should be 22 after sell freed cash, got {v}"


# ---------------------------------------------------------------------------
# 5. Buy failure doesn't block remaining
# ---------------------------------------------------------------------------

def test_buy_failure_doesnt_block_remaining():
    """If one buy fails, remaining cash is unchanged and others proceed with same alloc."""
    cash = 10000.0
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash)

    call_count = {'n': 0}

    def _buy_side_effect(*args, **kwargs):
        call_count['n'] += 1
        if call_count['n'] == 1:
            raise RuntimeError("Simulated buy failure")
        return MagicMock()

    trade_engine.buy.side_effect = _buy_side_effect

    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.9),
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.8),
        _make_signal(code='120003', action='buy', price=100.0, confidence=0.7),
    ]

    engine._auto_execute(signals)

    # All 3 buys were attempted
    assert trade_engine.buy.call_count == 3

    # The first signal should NOT be marked executed (it failed)
    assert signals[0].executed is False
    # The other two should be marked executed
    assert signals[1].executed is True
    assert signals[2].executed is True

    # With cash-based allocation: alloc = remaining_cash / count (fixed denominator)
    # buy1 fails, remaining_cash stays 10000
    # buy2: alloc = 10000/3 = 3333.3, volume = 33, remaining = 6677
    # buy3: alloc = 6677/3 = 2225.6, volume = 22
    buy_calls = trade_engine.buy.call_args_list
    v2 = buy_calls[1].kwargs['volume']
    v3 = buy_calls[2].kwargs['volume']
    assert v2 == 33, f"Second buy volume should be 33, got {v2}"
    assert v3 == 22, f"Third buy volume should be 22, got {v3}"


# ---------------------------------------------------------------------------
# 6. Threshold filtering
# ---------------------------------------------------------------------------

def test_threshold_filters_low_confidence_signals():
    """Signals below the confidence threshold are not executed."""
    engine, trade_engine, storage = _make_engine_with_mocks(cash=50000.0)
    engine.set_auto_execute_min_confidence(0.7)

    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.9),
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.5),  # below
        _make_signal(code='120003', action='sell', price=110.0, confidence=0.3),  # below
        _make_signal(code='120004', action='sell', price=105.0, confidence=0.8),
    ]

    # Need a position for the sell
    trade_engine.positions = [_make_mock_position(code='120004', volume=10)]

    engine._auto_execute(signals)

    # Only 1 buy and 1 sell should have been executed
    trade_engine.buy.assert_called_once()
    trade_engine.sell.assert_called_once()
    assert signals[0].executed is True   # above threshold
    assert signals[1].executed is False  # below threshold
    assert signals[2].executed is False  # below threshold
    assert signals[3].executed is True   # above threshold


def test_zero_threshold_skips_all():
    """With threshold=0 (default), _auto_execute returns immediately."""
    engine, trade_engine, storage = _make_engine_with_mocks(cash=50000.0)
    engine.set_auto_execute_min_confidence(0.0)

    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.9),
    ]

    engine._auto_execute(signals)

    trade_engine.buy.assert_not_called()
    trade_engine.sell.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Batch save
# ---------------------------------------------------------------------------

def test_batch_save_called_once():
    """save_executed_positions_batch is called once with all positions."""
    cash = 50000.0
    positions = [_make_mock_position(code='120001', volume=10)]
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash, positions=positions)

    signals = [
        _make_signal(code='120001', action='sell', price=110.0, confidence=0.9),
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.8),
        _make_signal(code='120003', action='buy', price=90.0, confidence=0.7),
    ]

    engine._auto_execute(signals)

    # Batch save should be called exactly once
    storage.save_executed_positions_batch.assert_called_once()

    # The argument should be a list of dicts with length = number of executed signals
    batch_arg = storage.save_executed_positions_batch.call_args[0][0]
    assert isinstance(batch_arg, list)
    assert len(batch_arg) == 3  # 1 sell + 2 buys
    for item in batch_arg:
        assert isinstance(item, dict)
        assert 'code' in item
        assert 'side' in item
        assert 'volume' in item


def test_no_batch_save_when_nothing_executed():
    """If no signals pass threshold, batch save is NOT called."""
    engine, trade_engine, storage = _make_engine_with_mocks(cash=50000.0)
    engine.set_auto_execute_min_confidence(0.9)

    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.5),
    ]

    engine._auto_execute(signals)

    storage.save_executed_positions_batch.assert_not_called()


# ---------------------------------------------------------------------------
# 8. No signals
# ---------------------------------------------------------------------------

def test_empty_signals_handled_gracefully():
    """An empty signals list should not cause errors."""
    engine, trade_engine, storage = _make_engine_with_mocks(cash=50000.0)

    engine._auto_execute([])

    trade_engine.buy.assert_not_called()
    trade_engine.sell.assert_not_called()
    storage.save_executed_positions_batch.assert_not_called()


def test_no_trade_engine_returns_early():
    """Without a trade_engine set, _auto_execute returns immediately."""
    engine = SignalEngine()
    engine.set_auto_execute_min_confidence(0.5)
    storage = MagicMock()
    storage.get_config.return_value = None
    engine.set_storage(storage)
    storage.get_executed_positions.return_value = []

    signals = [_make_signal(code='120001', action='buy', price=100.0, confidence=0.9)]

    # Should not raise
    engine._auto_execute(signals)

    assert signals[0].executed is False


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

def test_sell_failure_doesnt_stop_other_sells():
    """If one sell fails, other sells still proceed."""
    cash = 50000.0
    positions = [
        _make_mock_position(code='120001', volume=10),
        _make_mock_position(code='120002', volume=20),
    ]
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash, positions=positions)

    call_count = {'n': 0}

    def _sell_side_effect(*args, **kwargs):
        call_count['n'] += 1
        if call_count['n'] == 1:
            raise RuntimeError("Sell failed")
        return MagicMock()

    trade_engine.sell.side_effect = _sell_side_effect

    signals = [
        _make_signal(code='120001', action='sell', price=110.0, confidence=0.9),
        _make_signal(code='120002', action='sell', price=105.0, confidence=0.8),
    ]

    engine._auto_execute(signals)

    assert trade_engine.sell.call_count == 2
    assert signals[0].executed is False  # First sell failed
    assert signals[1].executed is True   # Second sell succeeded


def test_executed_positions_appended_in_order():
    """ExecutedPosition objects are appended to _executed_positions in order."""
    cash = 50000.0
    positions = [_make_mock_position(code='120001', volume=15)]
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash, positions=positions)

    signals = [
        _make_signal(code='120001', action='sell', price=110.0, confidence=0.9),
        _make_signal(code='120002', action='buy', price=100.0, confidence=0.8),
    ]

    engine._auto_execute(signals)

    eps = engine._executed_positions
    assert len(eps) == 2
    assert isinstance(eps[0], ExecutedPosition)
    assert isinstance(eps[1], ExecutedPosition)
    # Sell first, then buy
    assert eps[0].side == 'sell'
    assert eps[0].code == '120001'
    assert eps[0].volume == 15  # From mock position
    assert eps[1].side == 'buy'
    assert eps[1].code == '120002'


def test_sell_without_position_is_skipped():
    """When no matching position found, sell is skipped to avoid short selling."""
    cash = 50000.0
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash, positions=[])

    signals = [
        _make_signal(code='120001', action='sell', price=110.0, confidence=0.9),
    ]

    engine._auto_execute(signals)

    # No sell should be called (no position to sell)
    trade_engine.sell.assert_not_called()
    assert signals[0].executed is False


def test_already_executed_signals_are_skipped():
    """Signals already marked as executed should not be processed again."""
    cash = 50000.0
    engine, trade_engine, storage = _make_engine_with_mocks(cash=cash)

    signals = [
        _make_signal(code='120001', action='buy', price=100.0, confidence=0.9, executed=True),
    ]

    engine._auto_execute(signals)

    trade_engine.buy.assert_not_called()
