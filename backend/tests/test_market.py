# backend/tests/test_market.py
from httpx import AsyncClient, ASGITransport
import pytest

from app.main import app, settings


from app.engine.market import MarketEngine


@pytest.fixture
async def client(auth_headers):
    app.state.engine = MarketEngine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == settings.app_name


from app.models.convertible import ConvertibleQuote


def test_convertible_quote_model():
    q = ConvertibleQuote(code="113044", name="测试转债", price=128.5)
    assert q.code == "113044"
    assert q.name == "测试转债"
    assert q.price == 128.5
    assert q.dual_low == 0.0


def test_premium_calculation():
    price = 128.5
    cv = 125.0
    premium = round((price - cv) / cv * 100, 2)
    assert premium == 2.8

    dual_low = round(price + premium, 2)
    assert dual_low == 131.3


@pytest.mark.asyncio
async def test_quotes_endpoint(client):
    resp = await client.get("/api/v1/market/quotes?symbols=113044")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


from datetime import date
from app.models.backtest import PerformanceMetrics, TradeRecord, BacktestResult

def test_performance_metrics_defaults():
    m = PerformanceMetrics()
    assert m.total_return_pct == 0.0
    assert m.sharpe_ratio == 0.0


def test_trade_record():
    t = TradeRecord(code="113044", buy_date=date(2024, 1, 1), buy_price=120.0, volume=10)
    assert t.code == "113044"
    assert t.profit_pct is None  # not closed yet


from app.engine.backtest import _calculate_metrics


def test_calculate_metrics_empty():
    m = _calculate_metrics([1.0])
    assert m.total_return_pct == 0.0


def test_calculate_metrics_up():
    m = _calculate_metrics([1.0, 1.1, 1.2])
    assert m.total_return_pct > 0
    assert m.max_drawdown_pct == 0.0
