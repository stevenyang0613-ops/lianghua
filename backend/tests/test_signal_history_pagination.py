"""信号历史服务端分页测试"""
import tempfile
import os
from datetime import datetime
from app.engine.storage import DataStorage


def test_signal_history_with_total():
    """测试 get_signal_history 返回 (signals, total)"""
    with tempfile.TemporaryDirectory() as d:
        db = DataStorage(os.path.join(d, "test.db"))
        # 插入测试数据
        db.save_signals_batch([
            {"strategy": "dual_low", "code": "123001", "name": "测试1", "action": "buy",
             "price": 100.0, "reason": "test", "confidence": 0.8, "executed": False, "ts": datetime.now()},
            {"strategy": "dual_low", "code": "123002", "name": "测试2", "action": "sell",
             "price": 105.0, "reason": "test", "confidence": 0.7, "executed": True, "ts": datetime.now()},
            {"strategy": "premium_low", "code": "123003", "name": "测试3", "action": "buy",
             "price": 98.0, "reason": "test", "confidence": 0.6, "executed": False, "ts": datetime.now()},
        ])

        # 查询所有
        signals, total = db.get_signal_history()
        assert total == 3
        assert len(signals) == 3

        # 按策略过滤
        signals, total = db.get_signal_history(strategy="dual_low")
        assert total == 2
        assert len(signals) == 2

        # 分页
        signals, total = db.get_signal_history(limit=1, offset=0)
        assert total == 3
        assert len(signals) == 1

        # 按代码过滤
        signals, total = db.get_signal_history(code="123001")
        assert total == 1
        db.close()


def test_signal_history_empty():
    """测试空信号历史"""
    with tempfile.TemporaryDirectory() as d:
        db = DataStorage(os.path.join(d, "test.db"))
        signals, total = db.get_signal_history()
        assert total == 0
        assert signals == []
        db.close()
