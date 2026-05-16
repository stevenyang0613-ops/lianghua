"""Tests for database connection pool module"""
import pytest
import tempfile
import os
import sqlite3
from unittest.mock import MagicMock, patch
import threading

from app.core.db_pool import (
    PoolStatus, PoolConfig, ConnectionMetrics,
    ConnectionPoolMonitor, DatabaseConnectionManager,
)


class TestConnectionMetrics:
    """连接指标测试"""

    def test_metrics_initialization(self):
        """测试指标初始化"""
        metrics = ConnectionMetrics()
        assert metrics.total_connections == 0
        assert metrics.active_connections == 0
        assert metrics.idle_connections == 0
        assert metrics.avg_wait_time_ms == 0.0


class TestPoolConfig:
    """连接池配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = PoolConfig()
        assert config.min_connections == 5
        assert config.max_connections == 20
        assert config.health_check_interval == 30

    def test_custom_config(self):
        """测试自定义配置"""
        config = PoolConfig(
            min_connections=10,
            max_connections=50,
            health_check_interval=60,
        )
        assert config.min_connections == 10
        assert config.max_connections == 50
        assert config.health_check_interval == 60


class TestConnectionPoolMonitor:
    """连接池监控器测试"""

    def test_monitor_initialization(self):
        """测试监控器初始化"""
        monitor = ConnectionPoolMonitor()
        assert monitor.status == PoolStatus.OFFLINE
        assert monitor.metrics.total_connections == 0

    def test_update_metrics(self):
        """测试更新指标"""
        monitor = ConnectionPoolMonitor()

        monitor.update_metrics(total=10, active=3, idle=7)

        assert monitor.metrics.total_connections == 10
        assert monitor.metrics.active_connections == 3
        assert monitor.metrics.idle_connections == 7

    def test_status_healthy(self):
        """测试健康状态"""
        monitor = ConnectionPoolMonitor()

        monitor.update_metrics(total=10, active=5, idle=5)

        assert monitor.status == PoolStatus.HEALTHY

    def test_status_degraded(self):
        """测试降级状态"""
        config = PoolConfig(max_connections=10)
        monitor = ConnectionPoolMonitor(config)

        # 活跃连接超过70%
        monitor.update_metrics(total=10, active=8, idle=2)

        assert monitor.status == PoolStatus.DEGRADED

    def test_status_critical(self):
        """测试临界状态"""
        config = PoolConfig(max_connections=10)
        monitor = ConnectionPoolMonitor(config)

        # 活跃连接超过90%
        monitor.update_metrics(total=10, active=10, idle=0)

        assert monitor.status == PoolStatus.CRITICAL

    def test_record_request_success(self):
        """测试记录成功请求"""
        monitor = ConnectionPoolMonitor()

        monitor.record_request(True, wait_time_ms=10.0, query_time_ms=50.0)

        assert monitor.metrics.total_requests == 1
        assert monitor.metrics.failed_requests == 0
        assert monitor.metrics.avg_wait_time_ms == 10.0
        assert monitor.metrics.avg_query_time_ms == 50.0

    def test_record_request_failure(self):
        """测试记录失败请求"""
        monitor = ConnectionPoolMonitor()

        monitor.record_request(False, error="Connection timeout")

        assert monitor.metrics.total_requests == 1
        assert monitor.metrics.failed_requests == 1
        assert monitor.metrics.last_error == "Connection timeout"
        assert monitor.metrics.last_error_time is not None

    def test_get_health_report(self):
        """测试获取健康报告"""
        monitor = ConnectionPoolMonitor()
        monitor.update_metrics(total=10, active=3, idle=7)
        monitor.record_request(True, query_time_ms=50.0)

        report = monitor.get_health_report()

        assert report['status'] == 'healthy'
        assert report['metrics']['total_connections'] == 10
        assert 'avg_query_time_ms' in report['metrics']

    def test_callback_notification(self):
        """测试回调通知"""
        config = PoolConfig(max_connections=10)
        monitor = ConnectionPoolMonitor(config)

        callback_called = []
        def callback(status, metrics):
            callback_called.append((status, metrics))

        monitor.register_callback(callback)
        # 需要设置total_connections才能正确判断状态
        monitor._metrics.total_connections = 10
        monitor.update_metrics(total=10, active=10, idle=0)

        assert len(callback_called) == 1
        assert callback_called[0][0] == PoolStatus.CRITICAL


class TestDatabaseConnectionManager:
    """数据库连接管理器测试"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)

        # 创建测试表
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)')
        conn.commit()
        conn.close()

        yield path

        os.unlink(path)

    def test_manager_initialization(self, temp_db):
        """测试管理器初始化"""
        config = PoolConfig(min_connections=2)
        manager = DatabaseConnectionManager(temp_db, config)
        manager.initialize()

        assert manager._initialized is True
        assert len(manager._pool) >= 2

        manager.close_all()

    def test_get_connection(self, temp_db):
        """测试获取连接"""
        manager = DatabaseConnectionManager(temp_db)
        manager.initialize()

        with manager.get_connection() as conn:
            assert conn is not None
            cursor = conn.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1

        manager.close_all()

    def test_connection_metrics(self, temp_db):
        """测试连接指标"""
        manager = DatabaseConnectionManager(temp_db)
        manager.initialize()

        initial_metrics = manager.get_metrics()
        initial_active = initial_metrics.active_connections

        with manager.get_connection() as conn:
            conn.execute("SELECT 1")

        # 归还后活跃连接应恢复
        final_metrics = manager.get_metrics()
        assert final_metrics.active_connections == initial_active

        manager.close_all()

    def test_request_recording(self, temp_db):
        """测试请求记录"""
        manager = DatabaseConnectionManager(temp_db)
        manager.initialize()

        with manager.get_connection() as conn:
            conn.execute("SELECT 1")

        metrics = manager.get_metrics()
        assert metrics.total_requests >= 1

        manager.close_all()

    def test_invalid_connection_removal(self, temp_db):
        """测试无效连接移除"""
        manager = DatabaseConnectionManager(temp_db)
        manager.initialize()

        # 获取连接并手动关闭
        conn = manager._pool[0] if manager._pool else None
        if conn:
            conn.close()

        # 尝试使用连接时应自动检测并创建新连接
        with manager.get_connection() as conn:
            assert conn is not None

        manager.close_all()

    def test_close_all(self, temp_db):
        """测试关闭所有连接"""
        manager = DatabaseConnectionManager(temp_db)
        manager.initialize()

        manager.close_all()

        assert len(manager._pool) == 0
        assert len(manager._in_use) == 0
        assert manager.monitor.metrics.total_connections == 0

    @pytest.mark.asyncio
    async def test_health_check(self, temp_db):
        """测试健康检查"""
        manager = DatabaseConnectionManager(temp_db)
        manager.initialize()

        report = await manager.health_check()

        assert 'status' in report
        assert report['ping'] == 'ok'

        manager.close_all()

    def test_pool_exhaustion(self, temp_db):
        """测试连接池耗尽"""
        config = PoolConfig(min_connections=1, max_connections=2)
        manager = DatabaseConnectionManager(temp_db, config)
        manager.initialize()

        # 获取所有连接
        contexts = []
        for _ in range(2):
            ctx = manager.get_connection()
            contexts.append(ctx)
            ctx.__enter__()

        # 再次获取应失败
        with pytest.raises(RuntimeError, match="无法获取数据库连接"):
            with manager.get_connection():
                pass

        # 归还连接
        for ctx in contexts:
            ctx.__exit__(None, None, None)

        manager.close_all()


class TestConnectionPoolConcurrency:
    """并发测试"""

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)

        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)')
        conn.commit()
        conn.close()

        yield path

        os.unlink(path)

    def test_concurrent_access(self, temp_db):
        """测试并发访问"""
        config = PoolConfig(min_connections=3, max_connections=10)
        manager = DatabaseConnectionManager(temp_db, config)
        manager.initialize()

        results = []
        errors = []

        def worker(worker_id):
            try:
                with manager.get_connection() as conn:
                    conn.execute("INSERT INTO test (value) VALUES (?)", (f"worker_{worker_id}",))
                    conn.commit()
                    cursor = conn.execute("SELECT COUNT(*) FROM test")
                    count = cursor.fetchone()[0]
                    results.append(count)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 5

        manager.close_all()

    def test_metrics_thread_safety(self, temp_db):
        """测试指标线程安全"""
        manager = DatabaseConnectionManager(temp_db)
        manager.initialize()

        def update_metrics():
            for _ in range(100):
                manager.monitor.update_metrics(
                    total=10,
                    active=5,
                    idle=5,
                )

        threads = [threading.Thread(target=update_metrics) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不应崩溃，指标应一致
        metrics = manager.get_metrics()
        assert metrics.total_connections == 10

        manager.close_all()
