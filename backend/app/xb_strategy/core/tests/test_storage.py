"""数据持久化模块测试"""
import pytest
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np

from app.xb_strategy.core.storage import (
    StorageBackend,
    StorageConfig,
    DataType,
    MemoryStorage,
    StorageManager,
    DataMigrator,
    get_storage_manager,
)


class TestMemoryStorage:
    """内存存储测试"""

    @pytest.fixture
    def storage(self):
        """创建存储实例"""
        config = StorageConfig(backend=StorageBackend.MEMORY)
        storage = MemoryStorage(config)
        storage.connect()
        storage.create_tables()
        yield storage
        storage.close()

    def test_connect(self, storage):
        """测试连接"""
        assert storage.connect() is True
        assert storage.health_check() is True

    def test_insert_and_query_cb_daily(self, storage):
        """测试转债日线数据插入和查询"""
        # 准备测试数据
        today = date.today()
        data = pd.DataFrame([
            {
                "date": today,
                "code": "110001",
                "name": "测试转债1",
                "stock_code": "600001",
                "stock_name": "测试正股",
                "close": 105.5,
                "volume": 1000000,
                "amount": 105500000,
                "turnover_rate": 2.5,
                "conversion_premium": 0.15,
            },
            {
                "date": today,
                "code": "110002",
                "name": "测试转债2",
                "stock_code": "600002",
                "stock_name": "测试正股2",
                "close": 98.0,
                "volume": 2000000,
                "amount": 196000000,
                "turnover_rate": 3.0,
                "conversion_premium": 0.20,
            },
        ])

        # 插入数据
        assert storage.insert(DataType.CB_DAILY, data) is True

        # 查询数据
        result = storage.query(DataType.CB_DAILY)
        assert len(result) == 2
        assert "110001" in result["code"].values
        assert "110002" in result["code"].values

    def test_query_with_filters(self, storage):
        """测试带过滤条件的查询"""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # 插入多日数据
        data = []
        for i, d in enumerate([yesterday, today]):
            for j in range(3):
                data.append({
                    "date": d,
                    "code": f"11000{j}",
                    "name": f"测试转债{j}",
                    "close": 100.0 + i * 2,
                })

        storage.insert(DataType.CB_DAILY, pd.DataFrame(data))

        # 按日期过滤
        result = storage.query(DataType.CB_DAILY, start_date=today)
        assert len(result) == 3

        # 按代码过滤
        result = storage.query(DataType.CB_DAILY, codes=["110000", "110001"])
        assert len(result) == 4  # 两天各2条

    def test_get_latest_date(self, storage):
        """测试获取最新日期"""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # 插入数据
        storage.insert(DataType.CB_DAILY, pd.DataFrame([
            {"date": yesterday, "code": "110001", "close": 100.0},
            {"date": today, "code": "110002", "close": 101.0},
        ]))

        latest = storage.get_latest_date(DataType.CB_DAILY)
        assert latest == today

    def test_delete(self, storage):
        """测试删除数据"""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # 插入数据
        storage.insert(DataType.CB_DAILY, pd.DataFrame([
            {"date": yesterday, "code": "110001", "close": 100.0},
            {"date": today, "code": "110002", "close": 101.0},
        ]))

        # 删除昨天数据
        storage.delete(DataType.CB_DAILY, end_date=yesterday)

        # 验证
        result = storage.query(DataType.CB_DAILY)
        assert len(result) == 1
        assert result.iloc[0]["code"] == "110002"


class TestStorageManager:
    """存储管理器测试"""

    @pytest.fixture
    def manager(self):
        """创建管理器实例"""
        config = StorageConfig(backend=StorageBackend.MEMORY)
        manager = StorageManager(config)
        manager.connect()
        yield manager
        manager.close()

    def test_singleton(self, manager):
        """测试单例模式"""
        manager2 = get_storage_manager()
        assert manager is manager2

    def test_save_and_get_daily_data(self, manager):
        """测试保存和获取日线数据"""
        today = date.today()

        cb_data = pd.DataFrame([{
            "date": today,
            "code": "110001",
            "name": "测试转债",
            "close": 105.0,
        }])

        stock_data = pd.DataFrame([{
            "date": today,
            "code": "600001",
            "name": "测试正股",
            "close": 10.5,
        }])

        # 保存
        assert manager.save_daily_data(cb_data, stock_data) is True

        # 获取
        result = manager.get_cb_data()
        assert len(result) == 1

        result = manager.get_stock_data()
        assert len(result) == 1

    def test_save_signals(self, manager):
        """测试保存交易信号"""
        signals = [{
            "signal_id": "sig_001",
            "signal_time": datetime.now(),
            "code": "110001",
            "name": "测试转债",
            "action": "buy",
            "quantity": 1000,
            "price": 105.0,
            "reason": "测试信号",
        }]

        assert manager.save_signals(signals) is True

        result = manager.get_signals()
        assert len(result) == 1

    def test_save_positions(self, manager):
        """测试保存持仓"""
        positions = [{
            "snapshot_time": datetime.now(),
            "code": "110001",
            "name": "测试转债",
            "quantity": 1000,
            "cost_price": 100.0,
            "market_price": 105.0,
            "market_value": 105000.0,
        }]

        assert manager.save_positions(positions) is True

    def test_save_trades(self, manager):
        """测试保存成交"""
        trades = [{
            "trade_id": "trade_001",
            "trade_time": datetime.now(),
            "code": "110001",
            "name": "测试转债",
            "side": "buy",
            "quantity": 1000,
            "price": 105.0,
            "amount": 105000.0,
        }]

        assert manager.save_trades(trades) is True

    def test_save_portfolio(self, manager):
        """测试保存组合净值"""
        portfolio_data = {
            "date": date.today(),
            "aum": 1000.0,
            "total_value": 980.0,
            "cash": 200.0,
            "position_count": 5,
            "daily_return": 0.01,
        }

        assert manager.save_portfolio(portfolio_data) is True

        result = manager.get_portfolio_history()
        assert len(result) == 1

    def test_save_scores(self, manager):
        """测试保存得分"""
        scores = [{
            "score_time": datetime.now(),
            "code": "110001",
            "name": "测试转债",
            "total_score": 75.5,
            "stock_score": 42.0,
            "cb_score": 33.5,
            "rank": 1,
            "in_whitelist": True,
        }]

        assert manager.save_scores(scores) is True

    def test_save_risk_alerts(self, manager):
        """测试保存风控记录"""
        alerts = [{
            "risk_time": datetime.now(),
            "risk_type": "drawdown",
            "risk_level": "warning",
            "message": "回撤预警",
            "value": 0.08,
            "threshold": 0.10,
        }]

        assert manager.save_risk_alerts(alerts) is True


class TestDataType:
    """数据类型枚举测试"""

    def test_data_types(self):
        """测试所有数据类型"""
        assert DataType.CB_DAILY.value == "cb_daily"
        assert DataType.STOCK_DAILY.value == "stock_daily"
        assert DataType.SIGNALS.value == "signals"
        assert DataType.POSITIONS.value == "positions"
        assert DataType.TRADES.value == "trades"
        assert DataType.PORTFOLIO.value == "portfolio"
        assert DataType.SCORES.value == "scores"
        assert DataType.RISK.value == "risk"


class TestStorageConfig:
    """存储配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = StorageConfig()
        assert config.backend == StorageBackend.MEMORY
        assert config.host == "localhost"
        assert config.port == 9000
        assert config.batch_size == 10000

    def test_custom_config(self):
        """测试自定义配置"""
        config = StorageConfig(
            backend=StorageBackend.CLICKHOUSE,
            host="192.168.1.100",
            port=8123,
            database="test_db",
            batch_size=5000,
        )
        assert config.backend == StorageBackend.CLICKHOUSE
        assert config.host == "192.168.1.100"
        assert config.port == 8123
        assert config.database == "test_db"
        assert config.batch_size == 5000


class TestLargeDataHandling:
    """大数据量处理测试"""

    @pytest.fixture
    def storage(self):
        """创建存储实例"""
        config = StorageConfig(backend=StorageBackend.MEMORY)
        storage = MemoryStorage(config)
        storage.connect()
        yield storage
        storage.close()

    def test_batch_insert(self, storage):
        """测试批量插入"""
        today = date.today()
        n_records = 10000

        # 生成大批量数据
        data = pd.DataFrame([
            {
                "date": today,
                "code": f"110{i:04d}",
                "name": f"测试转债{i}",
                "close": 100.0 + i * 0.01,
            }
            for i in range(n_records)
        ])

        # 插入
        assert storage.insert(DataType.CB_DAILY, data) is True

        # 查询验证
        result = storage.query(DataType.CB_DAILY)
        assert len(result) == n_records

    def test_multiple_dates(self, storage):
        """测试多日数据"""
        today = date.today()
        n_days = 100
        n_codes = 100

        # 生成多日数据
        data = []
        for d in range(n_days):
            for c in range(n_codes):
                data.append({
                    "date": today - timedelta(days=d),
                    "code": f"110{c:03d}",
                    "close": 100.0 + d * 0.1 + c * 0.01,
                })

        storage.insert(DataType.CB_DAILY, pd.DataFrame(data))

        # 验证总数
        result = storage.query(DataType.CB_DAILY)
        assert len(result) == n_days * n_codes

        # 验证最新日期
        latest = storage.get_latest_date(DataType.CB_DAILY)
        assert latest == today


class TestDataMigrator:
    """数据迁移工具测试"""

    def test_migrate_data(self):
        """测试数据迁移"""
        # 创建源存储
        source_config = StorageConfig(backend=StorageBackend.MEMORY)
        source = MemoryStorage(source_config)
        source.connect()

        # 创建目标存储
        target_config = StorageConfig(backend=StorageBackend.MEMORY)
        target = MemoryStorage(target_config)
        target.connect()

        # 向源存储写入数据
        today = date.today()
        source.insert(DataType.CB_DAILY, pd.DataFrame([
            {"date": today, "code": "110001", "close": 100.0},
            {"date": today, "code": "110002", "close": 101.0},
        ]))

        # 迁移
        migrator = DataMigrator(source, target)
        count = migrator.migrate(DataType.CB_DAILY)

        assert count == 2

        # 验证目标存储
        result = target.query(DataType.CB_DAILY)
        assert len(result) == 2

        # 清理
        source.close()
        target.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
