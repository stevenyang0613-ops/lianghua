"""
Tests for endpoints that the frontend uses but the backend was missing.
These tests guard against future route drift that would cause 404 errors in the UI.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth_headers) as ac:
        yield ac


@pytest.mark.asyncio
async def test_history_quote_by_code_with_storage(client: AsyncClient):
    """/api/v1/history/{code} should return history items from storage"""
    from unittest.mock import MagicMock

    mock_storage = MagicMock()
    mock_storage.get_quote_history = MagicMock(return_value=[
        {"timestamp": "2026-06-11T10:00:00", "price": 120.0, "premium_ratio": -3.6, "dual_low": 116.4},
        {"timestamp": "2026-06-11T11:00:00", "price": 121.0, "premium_ratio": -3.0, "dual_low": 118.0},
    ])
    original_storage = getattr(app.state, "storage", None)
    app.state.storage = mock_storage
    try:
        resp = await client.get("/api/v1/history/113044?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "113044"
        assert len(data["history"]) == 2
        assert data["history"][0]["price"] == 120.0
        assert data["history"][0]["premium_ratio"] == -3.6
    finally:
        app.state.storage = original_storage


@pytest.mark.asyncio
async def test_market_quote_by_code_not_found(client: AsyncClient):
    """/api/v1/market/quotes/{code} should return 404 when code is unknown"""
    from unittest.mock import AsyncMock, MagicMock

    mock_engine = MagicMock()
    mock_engine.get_quote = AsyncMock(return_value=None)
    mock_storage = MagicMock()
    mock_storage.get_latest_quotes = MagicMock(return_value=[])

    original_engine = getattr(app.state, "engine", None)
    original_storage = getattr(app.state, "storage", None)
    app.state.engine = mock_engine
    app.state.storage = mock_storage
    try:
        resp = await client.get("/api/v1/market/quotes/999999")
        assert resp.status_code == 404
    finally:
        app.state.engine = original_engine
        app.state.storage = original_storage


@pytest.mark.asyncio
async def test_market_quote_by_code_from_engine(client: AsyncClient):
    """/api/v1/market/quotes/{code} should return quote from engine"""
    from unittest.mock import AsyncMock, MagicMock
    from app.models.convertible import ConvertibleQuote

    mock_engine = MagicMock()
    mock_engine.get_quote = AsyncMock(return_value=ConvertibleQuote(
        code="113044", name="测试转债", price=120.0, change_pct=2.0,
        stock_price=25.0, stock_change_pct=1.0,
        conversion_price=20.0, conversion_value=125.0,
        premium_ratio=-4.0, dual_low=116.0,
    ))

    original_engine = getattr(app.state, "engine", None)
    app.state.engine = mock_engine
    try:
        resp = await client.get("/api/v1/market/quotes/113044")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "113044"
        assert data["name"] == "测试转债"
        assert data["price"] == 120.0
        assert data["change_pct"] == 2.0
        assert data["premium_ratio"] == -4.0
    finally:
        app.state.engine = original_engine


@pytest.mark.asyncio
async def test_market_quote_by_code_fallback_to_storage(client: AsyncClient):
    """/api/v1/market/quotes/{code} should fall back to storage when engine is unavailable"""
    from unittest.mock import AsyncMock, MagicMock

    mock_engine = MagicMock()
    mock_engine.get_quote = AsyncMock(return_value=None)
    mock_storage = MagicMock()
    mock_storage.get_latest_quotes = MagicMock(return_value=[
        {"code": "113044", "name": "存储转债", "price": 130.0, "change_pct": 1.5,
         "stock_price": 26.0, "stock_change_pct": 0.5,
         "conversion_price": 21.0, "conversion_value": 123.8,
         "premium_ratio": 5.0, "dual_low": 135.0},
        {"code": "113045", "name": "其他转债", "price": 100.0, "change_pct": 0.0,
         "stock_price": 20.0, "stock_change_pct": 0.0,
         "conversion_price": 18.0, "conversion_value": 111.1,
         "premium_ratio": -10.0, "dual_low": 90.0},
    ])

    original_engine = getattr(app.state, "engine", None)
    original_storage = getattr(app.state, "storage", None)
    app.state.engine = mock_engine
    app.state.storage = mock_storage
    try:
        resp = await client.get("/api/v1/market/quotes/113044")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "113044"
        assert data["name"] == "存储转债"
    finally:
        app.state.engine = original_engine
        app.state.storage = original_storage


@pytest.mark.asyncio
async def test_history_daily_still_works(client: AsyncClient):
    """Regression: /daily/{code} should not be shadowed by new /{code} route"""
    from unittest.mock import MagicMock

    mock_storage = MagicMock()
    mock_storage.get_daily_history = MagicMock(return_value=[
        {"snapshot_date": "2026-06-10", "price": 120.0},
    ])
    original_storage = getattr(app.state, "storage", None)
    app.state.storage = mock_storage
    try:
        resp = await client.get("/api/v1/history/daily/113044?days=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "113044"
        assert data["days"] == 10
        assert "history" in data
    finally:
        app.state.storage = original_storage


@pytest.mark.asyncio
async def test_history_records_still_works(client: AsyncClient):
    """Regression: /records should not be shadowed by new /{code} route"""
    resp = await client.get("/api/v1/history/records?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert "count" in data
