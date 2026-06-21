"""
策略市场(strategies-share) API 测试
"""

import json
import pytest
from unittest.mock import MagicMock
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.main import app
from app.api import strategies as strategies_mod
from app.api.strategies import strategies_db


@pytest.fixture
def client(test_token, tmp_path):
    """创建带认证的测试客户端，使用临时持久化目录。"""
    strategies_mod.set_data_dir(tmp_path)

    @asynccontextmanager
    async def noop_lifespan(_app: FastAPI):
        _app.state.signal_engine = MagicMock()
        _app.state.storage = MagicMock()
        _app.state.trade_engine = MagicMock()
        _app.state.engine = MagicMock()
        _app.state.scheduler = MagicMock()
        yield

    app.router.lifespan_context = noop_lifespan
    auth_headers = {"Authorization": f"Bearer {test_token}"}

    class AuthedClient:
        def __init__(self, tc: TestClient):
            self._tc = tc

        def _inject_headers(self, kwargs):
            headers = kwargs.pop("headers", {}) or {}
            headers.update(auth_headers)
            kwargs["headers"] = headers
            return kwargs

        def get(self, url, **kwargs):
            return self._tc.get(url, **self._inject_headers(kwargs))

        def post(self, url, **kwargs):
            return self._tc.post(url, **self._inject_headers(kwargs))

    with TestClient(app, raise_server_exceptions=True) as c:
        yield AuthedClient(c)


@pytest.fixture(autouse=True)
def ensure_seed_loaded():
    """种子数据在模块导入时即加载，此处确保测试时非空。"""
    assert len(strategies_db) > 0, "策略市场种子数据未加载"


def test_list_strategies(client):
    resp = client.get("/api/v1/strategies-share/?pageSize=100")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategies" in data
    assert "total" in data
    strategies = data["strategies"]
    assert isinstance(strategies, list)
    assert len(strategies) >= 10
    s = strategies[0]
    assert "id" in s
    assert "name" in s
    assert "description" in s
    assert "type" in s
    assert "backtestResult" in s
    assert "code" in s
    assert "params" in s
    assert "downloads" in s["stats"]


def test_strategy_filter_by_type(client):
    resp = client.get("/api/v1/strategies-share/?type=quant")
    assert resp.status_code == 200
    data = resp.json()["strategies"]
    assert all(item["type"] == "quant" for item in data)


def test_strategy_search(client):
    resp = client.get("/api/v1/strategies-share/?query=双低")
    assert resp.status_code == 200
    data = resp.json()["strategies"]
    assert len(data) > 0
    assert any("双低" in item["name"] or "双低" in item["description"] for item in data)


def test_get_strategy_detail(client):
    first_id = list(strategies_db.keys())[0]
    resp = client.get(f"/api/v1/strategies-share/{first_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == first_id


def test_strategy_tags(client):
    resp = client.get("/api/v1/strategies-share/tags?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_recommended_strategies(client):
    resp = client.get("/api/v1/strategies-share/recommended?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) <= 5


def test_like_strategy_persisted(client, tmp_path):
    first_id = list(strategies_db.keys())[0]
    before = strategies_db[first_id].stats["likes"]
    resp = client.post(f"/api/v1/strategies-share/{first_id}/like")
    assert resp.status_code == 200
    assert strategies_db[first_id].stats["likes"] == before + 1

    # 验证持久化文件已写入
    data_file = tmp_path / "strategy_market_data.json"
    assert data_file.exists()
    persisted = json.loads(data_file.read_text())
    persisted_strategy = next(s for s in persisted["strategies"] if s["id"] == first_id)
    assert persisted_strategy["stats"]["likes"] == before + 1


def test_download_strategy_persisted(client, tmp_path):
    first_id = list(strategies_db.keys())[0]
    before = strategies_db[first_id].stats.get("downloads", 0)
    resp = client.post(f"/api/v1/strategies-share/{first_id}/download")
    assert resp.status_code == 200
    assert resp.json()["downloads"] == before + 1
    assert strategies_db[first_id].stats["downloads"] == before + 1

    data_file = tmp_path / "strategy_market_data.json"
    assert data_file.exists()


def test_rate_strategy(client):
    first_id = list(strategies_db.keys())[0]
    resp = client.post(f"/api/v1/strategies-share/{first_id}/rate?rating=5")
    assert resp.status_code == 200
    assert strategies_db[first_id].ratings["count"] >= 1


def test_unknown_strategy_returns_404(client):
    resp = client.get("/api/v1/strategies-share/nonexistent-id")
    assert resp.status_code == 404


def test_persistence_reload(client, tmp_path):
    """验证切换数据目录后能重新加载持久化数据。"""
    first_id = list(strategies_db.keys())[0]
    client.post(f"/api/v1/strategies-share/{first_id}/like")

    # 重新 set_data_dir 到同一个目录，模拟重启后加载
    strategies_mod.set_data_dir(tmp_path)
    assert strategies_db[first_id].stats["likes"] >= 1
