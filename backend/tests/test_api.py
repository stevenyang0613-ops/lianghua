"""
API集成测试

测试覆盖：
- 信号策略API端点
- 策略参数和缓存管理API
"""

import pytest
import tempfile
import os
from unittest.mock import MagicMock, patch


@pytest.fixture
def client():
    """创建测试客户端，使用临时数据库且跳过 lifespan 避免网络请求"""
    import tempfile, os, shutil
    from contextlib import contextmanager
    from fastapi import FastAPI
    from app.engine.signals import SignalEngine
    from app.engine.storage import DataStorage
    from starlette.testclient import TestClient
    from app.main import app

    tmpdir = tempfile.mkdtemp()
    tmpdb = os.path.join(tmpdir, "test.db")

    engine = SignalEngine()
    storage = DataStorage(db_path=tmpdb)
    engine.set_storage(storage)

    # Replace lifespan to be a no-op to prevent background tasks
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        app.state.signal_engine = engine
        app.state.storage = storage
        app.state.trade_engine = MagicMock()
        app.state.engine = MagicMock()
        app.state.scheduler = MagicMock()
        yield
        app.state.signal_engine = None
        app.state.storage = None

    app.router.lifespan_context = noop_lifespan

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    shutil.rmtree(tmpdir, ignore_errors=True)


# ==================== 信号API测试 ====================

class TestSignalAPI:
    """信号API测试"""

    def test_get_signals(self, client):
        """测试获取信号列表"""
        response = client.get('/api/v1/signals')
        assert response.status_code == 200
        data = response.json()
        assert 'signals' in data
        assert 'active_strategies' in data

    def test_get_available_strategies(self, client):
        """测试获取可用策略"""
        response = client.get('/api/v1/signals/available-strategies')
        assert response.status_code == 200
        data = response.json()
        assert 'strategies' in data

    def test_set_strategy_params(self, client):
        """测试设置策略参数"""
        with patch("app.api.signals.list_strategies", return_value=[{"id": "dual_low"}]):
            response = client.put('/api/v1/signals/strategy-params', json={
                "strategy": "dual_low",
                "params": {"threshold": 130},
            })
        assert response.status_code == 200
        data = response.json()
        assert data["strategy"] == "dual_low"
        assert data["params"] == {"threshold": 130}

    def test_set_params_unknown_strategy(self, client):
        """测试设置未知策略参数"""
        with patch("app.api.signals.list_strategies", return_value=[{"id": "dual_low"}]):
            response = client.put('/api/v1/signals/strategy-params', json={
                "strategy": "nonexistent",
                "params": {},
            })
        assert response.status_code == 400

    def test_invalidate_cache_all(self, client):
        """测试清除所有缓存"""
        response = client.post('/api/v1/signals/invalidate-cache', json={})
        assert response.status_code == 200
        data = response.json()
        assert data["invalidated"] == "all"

    def test_invalidate_cache_specific(self, client):
        """测试清除指定策略缓存"""
        engine = client.app.state.signal_engine
        engine._strategy_cache = {"dual_low": (MagicMock(), 0, "")}

        response = client.post('/api/v1/signals/invalidate-cache', json={"strategy": "dual_low"})
        assert response.status_code == 200
        data = response.json()
        assert data["invalidated"] == "dual_low"

    def test_set_active_strategies(self, client):
        """测试设置活跃策略"""
        with patch("app.api.signals.list_strategies", return_value=[{"id": "dual_low"}, {"id": "momentum"}]):
            response = client.post('/api/v1/signals/strategies', json={"strategies": ["dual_low"]})
        assert response.status_code == 200
        data = response.json()
        assert "dual_low" in data["active_strategies"]

    def test_set_auto_execute(self, client):
        """测试设置自动执行阈值"""
        response = client.post('/api/v1/signals/auto-execute', json={"min_confidence": 0.8})
        assert response.status_code == 200

    def test_get_signal_history(self, client):
        """测试获取信号历史"""
        response = client.get('/api/v1/signals/history')
        assert response.status_code == 200

    def test_get_signal_stats(self, client):
        """测试获取信号统计"""
        response = client.get('/api/v1/signals/stats')
        assert response.status_code == 200

    def test_get_executed_positions(self, client):
        """测试获取已执行持仓"""
        response = client.get('/api/v1/signals/executed-positions')
        assert response.status_code == 200


# ==================== 策略参数和缓存管理集成测试 ====================

class TestStrategyParamsIntegration:
    """策略参数和缓存管理集成测试"""

    def test_params_change_reflected_in_engine(self, client):
        """测试参数变更反映在引擎状态中"""
        engine = client.app.state.signal_engine
        with patch("app.api.signals.list_strategies", return_value=[{"id": "dual_low"}]):
            client.put('/api/v1/signals/strategy-params', json={
                "strategy": "dual_low",
                "params": {"threshold": 130},
            })
        assert engine._strategy_params["dual_low"] == {"threshold": 130}

    def test_invalidate_cache_removes_entry(self, client):
        """测试清除缓存删除条目"""
        engine = client.app.state.signal_engine
        engine._strategy_cache = {
            "dual_low": (MagicMock(), 0, ""),
            "momentum": (MagicMock(), 0, ""),
        }
        client.post('/api/v1/signals/invalidate-cache', json={"strategy": "dual_low"})
        assert "dual_low" not in engine._strategy_cache
        assert "momentum" in engine._strategy_cache

    def test_invalidate_all_clears_everything(self, client):
        """测试清除全部缓存"""
        engine = client.app.state.signal_engine
        engine._strategy_cache = {
            "dual_low": (MagicMock(), 0, ""),
            "momentum": (MagicMock(), 0, ""),
        }
        client.post('/api/v1/signals/invalidate-cache', json={})
        assert len(engine._strategy_cache) == 0
