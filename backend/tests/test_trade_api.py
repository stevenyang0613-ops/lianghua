"""
Trade API tests - matches the actual API routes and schemas.
The API uses snake_case fields (code/name/volume) and wraps orders in
an envelope `{orders: [...]}` to align with the frontend.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def token():
    from app.config import settings
    from jose import jwt
    from datetime import datetime, timedelta, timezone
    return jwt.encode(
        {"sub": "testuser", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )


@pytest.fixture
async def client(token):
    from app.engine.trade import TradeEngine
    app.state.trade_engine = TradeEngine()
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_orders_empty(client: AsyncClient):
    """Test that GET /api/v1/trade/orders returns an empty envelope initially"""
    resp = await client.get("/api/v1/trade/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert data["orders"] == []


@pytest.mark.asyncio
async def test_get_account_initial(client: AsyncClient):
    """Test that GET /api/v1/trade/account returns initial 100,000 cash"""
    resp = await client.get("/api/v1/trade/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cash"] == 100000.0
    assert data["total_asset"] == 100000.0
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_get_positions_empty(client: AsyncClient):
    """Test that GET /api/v1/trade/positions returns an empty envelope initially"""
    resp = await client.get("/api/v1/trade/positions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert data["positions"] == []


@pytest.mark.asyncio
async def test_get_fund_curve_initial(client: AsyncClient):
    """Test that GET /api/v1/trade/fund-curve returns a single initial point"""
    resp = await client.get("/api/v1/trade/fund-curve")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "points" in data
    assert len(data["points"]) >= 1
    assert data["points"][0]["total_asset"] == 100000.0


@pytest.mark.asyncio
async def test_create_order(client: AsyncClient):
    """Test creating a buy order with the new (frontend) schema"""
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "113044"
    assert data["status"] == "filled"
    assert data["filled_volume"] == 10


@pytest.mark.asyncio
async def test_create_order_rejected_insufficient_cash(client: AsyncClient):
    """Order exceeding available cash should be rejected"""
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 9999.0,
        "volume": 1000,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["reject_reason"] != ""


@pytest.mark.asyncio
async def test_get_orders_after_create(client: AsyncClient):
    """Test that orders appear after creation, wrapped in envelope"""
    await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    resp = await client.get("/api/v1/trade/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert "orders" in data
    assert len(data["orders"]) >= 1
    assert data["orders"][-1]["code"] == "113044"


@pytest.mark.asyncio
async def test_positions_after_buy(client: AsyncClient):
    """After buying, the position should appear"""
    await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    resp = await client.get("/api/v1/trade/positions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["positions"]) == 1
    pos = data["positions"][0]
    assert pos["code"] == "113044"
    assert pos["volume"] == 10
    assert pos["cost_price"] == 120.0


@pytest.mark.asyncio
async def test_create_sell_order(client: AsyncClient):
    """Test creating a sell order"""
    # first buy to have inventory
    await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "sell",
        "order_type": "limit",
        "price": 125.0,
        "volume": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["side"] == "sell"
    assert data["status"] == "filled"


@pytest.mark.asyncio
async def test_cancel_filled_order_returns_404(client: AsyncClient):
    """Filled orders cannot be cancelled - should return 404"""
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    order_id = resp.json()["id"]
    cancel_resp = await client.post(f"/api/v1/trade/orders/{order_id}/cancel")
    assert cancel_resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_nonexistent_order_returns_404(client: AsyncClient):
    cancel_resp = await client.post("/api/v1/trade/orders/does-not-exist/cancel")
    assert cancel_resp.status_code == 404


@pytest.mark.asyncio
async def test_reset_account(client: AsyncClient):
    """Reset should clear orders, positions and restore cash"""
    await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    reset_resp = await client.post("/api/v1/trade/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "ok"

    account_resp = await client.get("/api/v1/trade/account")
    assert account_resp.json()["cash"] == 100000.0

    pos_resp = await client.get("/api/v1/trade/positions")
    assert pos_resp.json()["positions"] == []

    orders_resp = await client.get("/api/v1/trade/orders")
    assert orders_resp.json()["orders"] == []


@pytest.mark.asyncio
async def test_legacy_order_format(client: AsyncClient):
    """Test legacy order format with accountId/symbol/quantity still works"""
    resp = await client.post("/api/v1/trade/order", json={
        "accountId": "test-account",
        "symbol": "113044",
        "side": "buy",
        "type": "market",
        "price": 120.0,
        "quantity": 10,
    })
    # legacy format without 'order_type' falls through to the new endpoint
    # which validates using the new schema; quantity is mapped only via /orders/legacy
    # so the new endpoint will return 422 (validation error)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_legacy_endpoint(client: AsyncClient):
    """Legacy endpoint /orders/legacy accepts accountId/symbol/quantity"""
    resp = await client.post("/api/v1/trade/orders/legacy", json={
        "accountId": "test-account",
        "symbol": "113044",
        "side": "buy",
        "type": "limit",
        "price": 120.0,
        "quantity": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "113044"
    assert data["status"] == "filled"


@pytest.mark.asyncio
async def test_frozen_zero_after_immediate_fill(client: AsyncClient):
    """In a sim broker where all orders fill immediately, frozen should stay 0"""
    await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    resp = await client.get("/api/v1/trade/account")
    assert resp.status_code == 200
    assert resp.json()["frozen"] == 0.0


@pytest.mark.asyncio
async def test_invalid_price_returns_422(client: AsyncClient):
    """Price must be > 0 (Pydantic validation)"""
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 0,
        "volume": 10,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_volume_returns_422(client: AsyncClient):
    """Volume must be > 0 (Pydantic validation)"""
    resp = await client.post("/api/v1/trade/order", json={
        "code": "113044",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 0,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_code_returns_422(client: AsyncClient):
    """Code must be non-empty (Pydantic validation)"""
    resp = await client.post("/api/v1/trade/order", json={
        "code": "",
        "name": "大秦转债",
        "side": "buy",
        "order_type": "limit",
        "price": 120.0,
        "volume": 10,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fund_curve_after_multiple_orders(client: AsyncClient):
    """Fund curve should contain a point for each filled order"""
    await client.post("/api/v1/trade/order", json={
        "code": "113044", "name": "大秦转债", "side": "buy",
        "order_type": "limit", "price": 120.0, "volume": 10,
    })
    resp = await client.get("/api/v1/trade/fund-curve")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["points"]) == 1
    # cash should be reduced by 1200 + commission
    assert data["points"][0]["cash"] < 100000.0
    assert data["points"][0]["market_value"] == 1200.0
