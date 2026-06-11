"""活跃策略持久化测试"""
import json
import tempfile
import os
from app.engine.storage import DataStorage
from app.engine.signals import SignalEngine


def test_active_strategies_persist_on_set():
    """测试 set_active_strategies 自动持久化"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.db")
        engine = SignalEngine()
        db = DataStorage(path)
        engine.set_storage(db)

        engine.set_active_strategies(["dual_low", "premium_low"])
        saved = db.get_config("active_strategies")
        assert saved is not None
        assert json.loads(saved) == ["dual_low", "premium_low"]
        db.close()


def test_active_strategies_restore_on_startup():
    """测试启动时恢复活跃策略"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.db")
        # 先保存
        db1 = DataStorage(path)
        db1.set_config("active_strategies", json.dumps(["momentum", "volume_spike"]))
        db1.close()

        # 重新创建引擎，验证恢复
        engine = SignalEngine()
        assert engine._active_strategies == ["dual_low"]  # 默认值

        db2 = DataStorage(path)
        engine.set_storage(db2)
        assert engine._active_strategies == ["momentum", "volume_spike"]
        db2.close()


def test_active_strategies_default_when_no_saved():
    """测试无持久化数据时使用默认策略"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.db")
        engine = SignalEngine()
        db = DataStorage(path)
        engine.set_storage(db)
        assert engine._active_strategies == ["dual_low"]  # 默认值
        db.close()


def test_active_strategies_invalid_json_fallback():
    """测试无效 JSON 时回退到默认策略"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.db")
        db = DataStorage(path)
        db.set_config("active_strategies", "invalid json")
        db.close()

        engine = SignalEngine()
        db2 = DataStorage(path)
        engine.set_storage(db2)
        assert engine._active_strategies == ["dual_low"]  # 回退到默认
        db2.close()
