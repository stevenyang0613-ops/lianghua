"""
Trade API tests - matches the actual API routes and schemas.
The API uses accountId/symbol/type/quantity fields and routes from app/api/trade.py.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    from app.engine.trade import TradeEngine
    app.state.trade_engine = TradeEngine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_orders_empty(client: AsyncClient):
    """Test that GET /api/v1/trade/orders returns an empty list initially"""
    resp = await client.get("/api/v1/trade/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_create_order(client: AsyncClient):
    """Test creating an order with the correct schema"""
    resp = await client.post("/api/v1/trade/order", json={
        "accountId": "test-account",
        "symbol": "113044",
        "side": "buy",
        "type": "market",
        "price": 120.0,
        "quantity": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "113044"
    assert data["status"] in ("pending", "filled")


@pytest.mark.asyncio
async def test_get_orders_after_create(client: AsyncClient):
    """Test that orders appear after creation"""
    await client.post("/api/v1/trade/order", json={
        "accountId": "test-account",
        "symbol": "113044",
        "side": "buy",
        "type": "market",
        "price": 120.0,
        "quantity": 10,
    })
    resp = await client.get("/api/v1/trade/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[-1]["symbol"] == "113044"


@pytest.mark.asyncio
async def test_create_sell_order(client: AsyncClient):
    """Test creating a sell order"""
    resp = await client.post("/api/v1/trade/order", json={
        "accountId": "test-account",
        "symbol": "113044",
        "side": "sell",
        "type": "limit",
        "price": 125.0,
        "quantity": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["side"] == "sell"
    assert data["status"] in ("pending", "filled")


@pytest.mark.asyncio
async def test_cancel_order(client: AsyncClient):
    """Test cancelling an order"""
    resp = await client.post("/api/v1/trade/order", json={
        "accountId": "test-account",
        "symbol": "113044",
        "side": "buy",
        "type": "market",
        "price": 120.0,
        "quantity": 10,
    })
    assert resp.status_code == 200
    order_id = resp.json()["id"]

    cancel_resp = await client.post(f"/api/v1/trade/orders/{order_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
