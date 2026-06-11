"""去重配置持久化测试"""
import tempfile
import os
from app.engine.storage import DataStorage


def test_config_get_set():
    """测试配置存取"""
    with tempfile.TemporaryDirectory() as d:
        db = DataStorage(os.path.join(d, "test.db"))
        # 默认返回 None
        assert db.get_config("notexist") is None
        assert db.get_config("notexist", "default") == "default"

        # 设置并获取
        db.set_config("dedup_window_seconds", "300")
        assert db.get_config("dedup_window_seconds") == "300"

        # 更新
        db.set_config("dedup_window_seconds", "600")
        assert db.get_config("dedup_window_seconds") == "600"
        db.close()


def test_config_persist_across_restarts():
    """测试配置在重启后持久化"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.db")
        db1 = DataStorage(path)
        db1.set_config("dedup_window_seconds", "300")
        db1.set_config("dedup_price_threshold", "0.05")
        db1.close()

        # 重新打开同一数据库
        db2 = DataStorage(path)
        assert db2.get_config("dedup_window_seconds") == "300"
        assert db2.get_config("dedup_price_threshold") == "0.05"
        db2.close()


def test_dedup_config_restore_on_signal_engine():
    """测试 SignalEngine 启动时恢复去重配置"""
    from app.engine.signals import SignalEngine
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.db")
        # 先保存配置
        db1 = DataStorage(path)
        db1.set_config("dedup_window_seconds", "600")
        db1.set_config("dedup_price_threshold", "0.05")
        db1.close()

        # 创建引擎并设置存储
        engine = SignalEngine()
        assert engine._dedup_window_seconds == 300  # 默认值
        assert engine._dedup_price_threshold == 0.02  # 默认值

        db2 = DataStorage(path)
        engine.set_storage(db2)
        assert engine._dedup_window_seconds == 600  # 从持久化恢复
        assert engine._dedup_price_threshold == 0.05  # 从持久化恢复
        db2.close()


def test_dedup_config_save_on_set():
    """测试 set_dedup_config 自动持久化"""
    from app.engine.signals import SignalEngine
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test.db")
        engine = SignalEngine()
        db = DataStorage(path)
        engine.set_storage(db)

        engine.set_dedup_config(window_seconds=900, price_threshold=0.1)

        # 直接从数据库验证
        assert db.get_config("dedup_window_seconds") == "900"
        assert db.get_config("dedup_price_threshold") == "0.1"
        db.close()
