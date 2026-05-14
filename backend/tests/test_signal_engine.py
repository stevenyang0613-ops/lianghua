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
async def test_signals_api_get_signals():
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert "signals" in data
    assert "active_strategies" in data
    assert data["active_strategies"] == ["dual_low"]


@pytest.mark.asyncio
async def test_signals_api_available_strategies():
    app.state.engine = MarketEngine()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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
async def test_signals_api_set_strategies():
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/signals/strategies",
            json={"strategies": ["low_premium", "momentum"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_strategies"] == ["low_premium", "momentum"]


@pytest.mark.asyncio
async def test_signals_api_set_unknown_strategy():
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/signals/strategies",
            json={"strategies": ["made_up_strategy"]},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_signals_api_execute_signal():
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine

    from app.engine.trade import TradeEngine
    app.state.trade_engine = TradeEngine()

    # Process some bonds to generate signals
    bond = ConvertibleQuote(code="113044", name="测试转债A", price=120.0, premium_ratio=8.5, volume=5e7, dual_low=128.5)
    await signal_engine.process_quotes([bond])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/signals/113044/execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["executed"] >= 1
    assert len(data["orders"]) >= 1


@pytest.mark.asyncio
async def test_signals_api_execute_no_signal():
    app.state.engine = MarketEngine()
    signal_engine = SignalEngine()
    app.state.signal_engine = signal_engine
    from app.engine.trade import TradeEngine
    app.state.trade_engine = TradeEngine()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/signals/NONEXISTENT/execute")
    assert resp.status_code == 404
