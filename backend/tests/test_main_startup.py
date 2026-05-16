"""
TDD测试: 验证后端启动逻辑
1. FastAPI app 能正常创建
2. /health 端点正常响应
3. /health 返回 market_running 和 db_ok 状态
4. API v1 路由已挂载
5. 后台启动不阻塞服务器就绪
"""

import asyncio
import time
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app():
    from app.main import app as _app
    return _app


def test_app_creates_successfully():
    """测试: FastAPI app 能正常创建"""
    from app.main import app
    assert app is not None
    assert app.title == "LiangHua"


def test_api_v1_router_included(app):
    """测试: /api/v1 路由已挂载"""
    routes = [r.path for r in app.routes]
    api_routes = [r for r in routes if r.startswith("/api/v1")]
    assert len(api_routes) > 0, f"Expected /api/v1 routes, got: {routes}"


def test_health_route_exists(app):
    """测试: /health 路由已注册"""
    routes = [r.path for r in app.routes]
    assert "/health" in routes, f"Expected /health route, got: {routes}"


def test_lifespan_configured(app):
    """测试: lifespan 已配置"""
    from app.main import lifespan
    assert lifespan is not None
    assert callable(lifespan)


@pytest.mark.asyncio
async def test_health_endpoint_responds(app):
    """测试: /health 端点正常响应"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["app"] == "LiangHua"


@pytest.mark.asyncio
async def test_health_returns_market_and_db_status(app):
    """测试: /health 返回 market_running 和 db_ok 状态"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        data = resp.json()
        assert "market_running" in data
        assert "db_ok" in data


@pytest.mark.asyncio
async def test_server_starts_quickly(app):
    """测试: 服务器快速就绪（后台加载不阻塞）"""
    transport = ASGITransport(app=app)
    start = time.monotonic()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        # 服务器应在2秒内就绪（不包括数据加载时间）
        assert elapsed < 2.0, f"Server took {elapsed:.1f}s to respond - background loading may be blocking"


@pytest.mark.asyncio
async def test_cors_headers(app):
    """测试: CORS 中间件已配置"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers
