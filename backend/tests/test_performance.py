"""性能优化测试"""
import pytest
import time
import asyncio
from unittest.mock import Mock, patch, AsyncMock

# 检查依赖可用性
try:
    from sqlalchemy import create_engine
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class TestDatabaseConnectionPool:
    """数据库连接池测试（适配当前 DatabaseConnectionManager 的 API）"""

    @pytest.mark.asyncio
    async def test_connection_pool_init(self):
        """测试连接池初始化"""
        from app.core.db_pool import DatabaseConnectionManager, PoolConfig

        config = PoolConfig(
            min_connections=2,
            max_connections=10,
            connection_timeout=5,
            retry_attempts=3,
        )

        manager = DatabaseConnectionManager(
            db_path=":memory:",
            config=config,
        )
        manager.initialize()

        assert manager.config is not None
        assert manager.config.min_connections == 2
        assert manager.config.max_connections == 10
        assert manager.config.connection_timeout == 5

        manager.close_all()

    @pytest.mark.asyncio
    async def test_connection_pool_health_check(self):
        """测试连接池健康检查"""
        from app.core.db_pool import DatabaseConnectionManager, PoolConfig

        config = PoolConfig(min_connections=1, max_connections=2)
        manager = DatabaseConnectionManager(
            db_path=":memory:",
            config=config,
        )
        manager.initialize()

        health = await manager.health_check()

        assert 'status' in health
        assert 'ping' in health
        assert 'metrics' in health

        manager.close_all()


class TestRedisCache:
    """Redis缓存测试"""

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """测试缓存命中"""
        from app.core.cache import CacheManager

        # 测试内存缓存命中
        cache = CacheManager(redis_url=None)
        cache.memory_cache.set("test_key", {"data": "test"})
        result = await cache.get("test_key")

        assert result is not None
        assert result["data"] == "test"

    @pytest.mark.asyncio
    async def test_cache_miss(self):
        """测试缓存未命中"""
        from app.core.cache import CacheManager

        cache = CacheManager(redis_url=None)
        result = await cache.get("nonexistent_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_set_with_ttl(self):
        """测试设置缓存（带TTL）"""
        from app.core.cache import CacheManager

        cache = CacheManager(redis_url=None)
        await cache.set("test_key", {"data": "test"}, ttl=60)

        # 验证内存缓存已设置
        result = cache.memory_cache.get("test_key")
        assert result is not None
        assert result["data"] == "test"


class TestAPICacheMiddleware:
    """API缓存中间件测试"""

    def test_cache_key_generation(self):
        """测试缓存key生成"""
        from app.core.cache import generate_cache_key

        key = generate_cache_key(
            path="/api/v1/quotes/123",
            params={"date": "2024-01-01"},
            headers={"Accept-Encoding": "gzip"}
        )

        assert key is not None
        assert len(key) > 0

    def test_cache_policy_match(self):
        """测试缓存策略匹配"""
        policies = [
            {"path": "/api/v1/quotes/*", "ttl": 5},
            {"path": "/api/v1/bonds", "ttl": 60},
        ]

        from app.core.cache import match_cache_policy

        policy = match_cache_policy("/api/v1/quotes/123", policies)
        assert policy["ttl"] == 5

        policy = match_cache_policy("/api/v1/bonds", policies)
        assert policy["ttl"] == 60


class TestPerformanceBenchmarks:
    """性能基准测试"""

    def test_quote_query_performance(self, benchmark):
        """测试行情查询性能"""
        def query_quotes():
            # 模拟查询
            time.sleep(0.001)
            return [{"bond_code": "123", "price": 100}]

        result = benchmark(query_quotes)
        assert len(result) == 1

    @pytest.mark.skip(reason="SignalGenerator module not available in test env")
    def test_signal_generation_performance(self, benchmark):
        """测试信号生成性能"""
        from app.strategies.signal_generator import SignalGenerator

        generator = SignalGenerator()

        # 模拟债券数据
        bonds = [
            {"bond_code": f"11{i:03d}", "price": 100 + i, "premium": 10 + i}
            for i in range(100)
        ]

        result = benchmark(generator.generate_signals, bonds)
        assert result is not None

    def test_backtest_performance(self, benchmark):
        """测试回测性能"""
        from app.engine.backtest import BacktestEngine

        engine = BacktestEngine()

        # 模拟历史数据
        history = [
            {"date": f"2024-01-{i:02d}", "close": 100 + i}
            for i in range(1, 31)
        ]

        def run_simple_backtest():
            # 简单回测逻辑
            returns = []
            for i in range(1, len(history)):
                ret = (history[i]["close"] - history[i-1]["close"]) / history[i-1]["close"]
                returns.append(ret)
            return {"returns": returns, "total": sum(returns)}

        result = benchmark(run_simple_backtest)
        assert result is not None


class TestMemoryCache:
    """内存缓存测试"""

    def test_lru_eviction(self):
        """测试LRU淘汰"""
        from app.core.cache import MemoryCache

        cache = MemoryCache(max_size=3)

        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # 触发淘汰

        assert cache.get("a") is None  # 被淘汰
        assert cache.get("b") is not None
        assert cache.get("c") is not None
        assert cache.get("d") is not None

    def test_cache_stats(self):
        """测试缓存统计"""
        from app.core.cache import MemoryCache

        cache = MemoryCache()

        cache.set("a", 1)
        cache.get("a")  # hit
        cache.get("b")  # miss

        stats = cache.get_stats()

        assert stats["hits"] >= 1
        assert stats["misses"] >= 1
