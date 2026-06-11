"""
TDD: 信号去重唯一索引优化

验证点:
  1. 同一 strategy+code+ts 但不同 id 的两条信号都应入库
  2. 相同 id 的信号不应重复插入
"""
import pytest
import tempfile
import os
from datetime import datetime
from app.engine.storage import DataStorage


class TestSignalDedup:
    def test_same_strategy_code_ts_different_id_both_stored(self):
        """同一 strategy+code+ts 但不同 id 的两条信号都应入库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_dedup.duckdb")
            storage = DataStorage(db_path, checkpoint_interval=0)
            ts = datetime.now().isoformat()
            storage.save_signals_batch([
                {"id": "abc1", "strategy": "dual_low", "code": "123456", "name": "测试A",
                 "action": "buy", "price": 100.0, "reason": "test1",
                 "confidence": 0.8, "ts": ts},
            ])
            storage.save_signals_batch([
                {"id": "def2", "strategy": "dual_low", "code": "123456", "name": "测试B",
                 "action": "sell", "price": 105.0, "reason": "test2",
                 "confidence": 0.9, "ts": ts},
            ])
            result, total = storage.get_signal_history()
            assert total == 2

    def test_same_id_not_duplicated(self):
        """相同 id 的信号不应重复插入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_dedup2.duckdb")
            storage = DataStorage(db_path, checkpoint_interval=0)
            ts1 = datetime.now().isoformat()
            ts2 = datetime.now().isoformat()
            storage.save_signals_batch([
                {"id": "same_id", "strategy": "dual_low", "code": "123456", "name": "测试",
                 "action": "buy", "price": 100.0, "reason": "test",
                 "confidence": 0.8, "ts": ts1},
            ])
            storage.save_signals_batch([
                {"id": "same_id", "strategy": "dual_low", "code": "123456", "name": "测试",
                 "action": "buy", "price": 100.0, "reason": "test",
                 "confidence": 0.8, "ts": ts2},
            ])
            result, total = storage.get_signal_history()
            assert total == 1
