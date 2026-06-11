# backend/tests/test_signal_engine.py
from httpx import AsyncClient, ASGITransport
import pytest

from app.main import app
from app.engine.signals import SignalEngine, TradeSignal
from app.engine.market import MarketEngine
from app.models.convertible import ConvertibleQuote


@pytest.fixture
def engine():
    return SignalEngine()


@pytest.fixture
def sample_bonds():
    return [
        ConvertibleQuote(code="113044", name="测试转债A", price=120.0, premium_ratio=8.5, volume=5e7, dual_low=128.5, change_pct=1.2),
        ConvertibleQuote(code="113045", name="测试转债B", price=135.0, premium_ratio=25.0, volume=2e7, dual_low=160.0, change_pct=-0.5),
        ConvertibleQuote(code="113046", name="测试转债C", price=105.0, premium_ratio=3.2, volume=1e8, dual_low=108.2, change_pct=3.1),
    ]


@pytest.mark.asyncio
async def test_process_quotes_returns_signals(engine, sample_bonds):
    signals = await engine.process_quotes(sample_bonds)
    assert isinstance(signals, list)
    # With default "dual_low" strategy, should produce some buy signals
    assert len(signals) > 0
    for s in signals:
        assert isinstance(s, TradeSignal)
        assert s.action == "buy"
        assert s.code in ("113044", "113045", "113046")
        assert 0 <= s.confidence <= 1.0


@pytest.mark.asyncio
async def test_current_signals_only_unexecuted(engine, sample_bonds):
    signals = await engine.process_quotes(sample_bonds)
    assert len(signals) > 0

    current = engine.current_signals
    assert len(current) == len(signals)
    for s in current:
        assert s["executed"] is False

    # Mark one as executed
    engine.mark_executed(signals[0].code, signals[0].strategy)
    current = engine.current_signals
    executed_count = sum(1 for s in signals if s.executed)
    assert len(current) == len(signals) - executed_count


@pytest.mark.asyncio
async def test_empty_bonds_no_signals(engine):
    signals = await engine.process_quotes([])
    assert signals == []


def test_active_strategies_default(engine):
    assert engine.active_strategies == ["dual_low"]


def test_set_active_strategies(engine):
    engine.set_active_strategies(["low_premium", "momentum"])
    assert engine.active_strategies == ["low_premium", "momentum"]


@pytest.mark.asyncio
async def test_process_quotes_invalid_strategy_does_not_crash(engine, sample_bonds):
    engine.set_active_strategies(["nonexistent_strategy"])
    signals = await engine.process_quotes(sample_bonds)
    assert signals == []


@pytest.mark.asyncio
async def test_repeated_calls_preserve_signals(engine, sample_bonds):
    """
    Regression test for: self._signals being cleared when cross-call dedup
    removes all signals (e.g., when the strategy produces the same output
    on every refresh within the dedup window).

    The fix: self._signals should preserve signals that the strategy still
    wants to keep, even if all newly generated signals are deduped.
    """
    # 1st call: should generate signals and store in self._signals
    first = await engine.process_quotes(sample_bonds)
    assert len(first) > 0, "Strategy should produce signals on first call"
    assert len(engine._signals) == len(first), \
        f"self._signals should have {len(first)} entries, got {len(engine._signals)}"
    initial_count = len(engine.current_signals)
    assert initial_count == len(first)

    # 2nd call with same data: all signals should be deduped (returned empty)
    second = await engine.process_quotes(sample_bonds)
    assert len(second) == 0, \
        f"Repeated call with same data should be fully deduped, got {len(second)} new signals"

    # CRITICAL: self._signals should NOT be cleared by dedup
    assert len(engine._signals) == initial_count, (
        f"BUG: self._signals was cleared on dedup! "
        f"expected {initial_count}, got {len(engine._signals)}. "
        f"This is the regression - signals were lost on subsequent calls."
    )
    assert len(engine.current_signals) == initial_count, \
        f"current_signals should still show {initial_count} entries, got {len(engine.current_signals)}"

    # 3rd call: drop a bond, then re-run — strategy should no longer
    # want signals for the dropped bond
    fewer_bonds = sample_bonds[:1]
    third = await engine.process_quotes(fewer_bonds)
    # self._signals should be reduced (dropped bonds removed) and not empty
    assert len(engine._signals) > 0, "Should still have signals for remaining bond"


@pytest.mark.asyncio
async def test_executed_signals_removed_from_current_but_preserved_in_memory(engine, sample_bonds):
    """Executed signals stay in self._signals but are filtered from current_signals."""
    signals = await engine.process_quotes(sample_bonds)
    assert len(signals) > 0

    initial_total = len(engine._signals)
    initial_current = len(engine.current_signals)
    assert initial_total == initial_current

    # Mark first signal as executed
    engine.mark_executed(signals[0].code, signals[0].strategy)

    # self._signals should retain the signal (for dedup state)
    assert len(engine._signals) == initial_total
    # current_signals should not show executed ones
    assert len(engine.current_signals) == initial_current - 1


@pytest.mark.asyncio
async def test_removed_strategy_signals_cleaned_up(engine, sample_bonds):
    """
    When a strategy is removed from active_strategies, its signals should
    be removed from self._signals on the next process_quotes call.

    Regression test: previously preserved + new_signals could overlap
    (counting the same signal twice), keeping removed strategies' signals.
    """
    # Activate two strategies
    engine.set_active_strategies(["dual_low", "low_premium"])
    await engine.process_quotes(sample_bonds)
    initial_total = len(engine._signals)
    assert initial_total > 0

    # Now remove low_premium — only dual_low remains
    engine.set_active_strategies(["dual_low"])
    await engine.process_quotes(sample_bonds)

    # All remaining signals should be from "dual_low" only
    remaining_strategies = {s.strategy for s in engine._signals}
    assert remaining_strategies == {"dual_low"}, (
        f"After removing low_premium, expected only dual_low signals, "
        f"got {remaining_strategies}"
    )


@pytest.mark.asyncio
async def test_reactivated_strategy_shows_signals_again(engine, sample_bonds):
    """
    When a strategy is removed and re-added within the dedup window,
    its signals should still appear (the dedup history for that strategy
    should be cleared on re-activation).
    """
    # 1. Initial run with dual_low
    await engine.process_quotes(sample_bonds)
    assert len(engine._signals) > 0
    initial_count = len(engine._signals)

    # 2. Remove dual_low (signals should be cleared)
    engine.set_active_strategies(["low_premium"])
    await engine.process_quotes(sample_bonds)
    remaining = {s.strategy for s in engine._signals}
    assert "dual_low" not in remaining

    # 3. Re-add dual_low — its signals should appear again, not be deduped
    engine.set_active_strategies(["dual_low", "low_premium"])
    await engine.process_quotes(sample_bonds)

    strategies_present = {s.strategy for s in engine._signals}
    assert "dual_low" in strategies_present, (
        "Re-activated dual_low should have its signals in self._signals, "
        f"got strategies: {strategies_present}"
    )


@pytest.mark.asyncio
async def test_signals_api_get_signals(auth_headers):
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        resp = await client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert "signals" in data
    assert "active_strategies" in data
    assert data["active_strategies"] == ["dual_low"]


@pytest.mark.asyncio
async def test_signals_api_available_strategies(auth_headers):
    app.state.engine = MarketEngine()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        resp = await client.get("/api/v1/signals/available-strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategies" in data
    assert len(data["strategies"]) >= 3
    strat_ids = [s["id"] for s in data["strategies"]]
    assert "dual_low" in strat_ids
    assert "low_premium" in strat_ids
    assert "momentum" in strat_ids


@pytest.mark.asyncio
async def test_signals_api_set_strategies(auth_headers):
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        resp = await client.post(
            "/api/v1/signals/strategies",
            json={"strategies": ["low_premium", "momentum"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_strategies"] == ["low_premium", "momentum"]


@pytest.mark.asyncio
async def test_signals_api_set_unknown_strategy(auth_headers):
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        resp = await client.post(
            "/api/v1/signals/strategies",
            json={"strategies": ["made_up_strategy"]},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_signals_api_execute_signal(auth_headers):
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    from app.engine.trade import TradeEngine
    app.state.trade_engine = TradeEngine()

    # Process some bonds to generate signals
    bond = ConvertibleQuote(code="113044", name="测试转债A", price=120.0, premium_ratio=8.5, volume=5e7, dual_low=128.5)
    await signal_engine.process_quotes([bond])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        resp = await client.post("/api/v1/signals/113044/execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["executed"] >= 1
    assert len(data["orders"]) >= 1


@pytest.mark.asyncio
async def test_signals_api_execute_no_signal(auth_headers):
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine
    from app.engine.trade import TradeEngine
    app.state.trade_engine = TradeEngine()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as client:
        resp = await client.post("/api/v1/signals/NONEXISTENT/execute")
    assert resp.status_code == 404
