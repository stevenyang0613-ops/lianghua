import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.engine.trade import TradeEngine


@pytest.fixture
async def client():
    app.state.trade_engine = TradeEngine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_account(client: AsyncClient):
    resp = await client.get("/api/v1/trade/account")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_asset" in data
    assert data["cash"] == 100000.0


@pytest.mark.asyncio
async def test_get_positions_empty(client: AsyncClient):
    resp = await client.get("/api/v1/trade/positions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["positions"] == []


@pytest.mark.asyncio
async def test_place_buy_order(client: AsyncClient):
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "测试转债",
        "side": "buy",
        "price": 120.0,
        "volume": 10,
        "order_type": "market",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "filled"
    assert data["code"] == "113044"


@pytest.mark.asyncio
async def test_place_sell_order(client: AsyncClient):
    # First buy
    await client.post("/api/v1/trade/order", json={
        "code": "113044", "name": "测试转债",
        "side": "buy", "price": 120.0, "volume": 10,
    })
    # Then sell
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044", "name": "测试转债",
        "side": "sell", "price": 125.0, "volume": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "filled"


@pytest.mark.asyncio
async def test_order_rejected_insufficient_funds(client: AsyncClient):
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044", "name": "测试转债",
        "side": "buy", "price": 999999.0, "volume": 10,
    })
    assert resp.status_code == 200  # returns order with rejected status
    data = resp.json()
    assert data["status"] == "rejected"


@pytest.mark.asyncio
async def test_reset(client: AsyncClient):
    await client.post("/api/v1/trade/order", json={
        "code": "113044", "name": "测试转债",
        "side": "buy", "price": 120.0, "volume": 10,
    })
    resp = await client.post("/api/v1/trade/reset")
    assert resp.status_code == 200
    resp2 = await client.get("/api/v1/trade/account")
    assert resp2.json()["cash"] == 100000.0
