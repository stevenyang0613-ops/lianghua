"""Tests for data source adapters and failover functionality"""
import pytest
import pandas as pd
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.data.adapters.base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType
from app.data.manager import DataSourceManager, DataSourcePriority, DataSourceStatus


class MockAdapter(DataSourceAdapter):
    """模拟数据源适配器"""

    def __init__(self, config: DataSourceConfig, should_fail: bool = False):
        super().__init__(config)
        self.should_fail = should_fail
        self._connected = False
        self.query_count = 0

    async def connect(self) -> bool:
        if self.should_fail:
            raise ConnectionError("Mock connection failed")
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def query(self, query: DataQuery) -> pd.DataFrame:
        self.query_count += 1
        if self.should_fail:
            raise RuntimeError("Mock query failed")
        return pd.DataFrame({
            'code': ['123456', '123457'],
            'price': [100.0, 101.0],
        })

    async def get_realtime_quotes(self, codes: list) -> pd.DataFrame:
        """获取实时行情"""
        if self.should_fail:
            raise RuntimeError("Mock query failed")
        return pd.DataFrame({
            'code': codes,
            'price': [100.0] * len(codes),
        })

    async def get_convertible_bonds(self, date=None) -> pd.DataFrame:
        """获取转债列表"""
        if self.should_fail:
            raise RuntimeError("Mock query failed")
        return pd.DataFrame({
            'code': ['123456', '123457'],
            'name': ['测试转债1', '测试转债2'],
        })

    async def get_announcements(
        self,
        codes: list = None,
        start_date=None,
        end_date=None,
        keywords: list = None,
    ) -> pd.DataFrame:
        """获取公告"""
        if self.should_fail:
            raise RuntimeError("Mock query failed")
        return pd.DataFrame({
            'code': ['123456'],
            'title': ['测试公告'],
        })

    async def health_check(self) -> dict:
        return {
            'name': self._config.name,
            'connected': self._connected,
        }


class TestDataSourceManager:
    """数据源管理器测试"""

    def test_register_adapter(self):
        """测试注册数据源"""
        manager = DataSourceManager()
        adapter = MockAdapter(DataSourceConfig(name='test'))

        manager.register(
            name='test',
            adapter=adapter,
            priority=100,
            data_types=[DataType.QUOTE],
            is_primary=True,
        )

        assert 'test' in manager._adapters
        assert manager._priorities['test'].is_primary is True
        assert manager._status['test'].connected is False

    def test_get_best_source(self):
        """测试获取最佳数据源"""
        manager = DataSourceManager()

        # 注册多个数据源
        adapter1 = MockAdapter(DataSourceConfig(name='primary'))
        adapter2 = MockAdapter(DataSourceConfig(name='secondary'))

        manager.register('primary', adapter1, priority=10, data_types=[DataType.QUOTE])
        manager.register('secondary', adapter2, priority=20, data_types=[DataType.QUOTE])

        # 未连接时无可用源
        assert manager.get_best_source(DataType.QUOTE) is None

        # 连接后应返回优先级最高的
        manager._status['primary'].connected = True
        manager._status['secondary'].connected = True
        assert manager.get_best_source(DataType.QUOTE) == 'primary'

    def test_get_best_source_with_unavailable(self):
        """测试部分数据源不可用时的最佳源选择"""
        manager = DataSourceManager()

        adapter1 = MockAdapter(DataSourceConfig(name='primary'))
        adapter2 = MockAdapter(DataSourceConfig(name='secondary'))

        manager.register('primary', adapter1, priority=10, data_types=[DataType.QUOTE])
        manager.register('secondary', adapter2, priority=20, data_types=[DataType.QUOTE])

        # 只连接secondary
        manager._status['primary'].connected = False
        manager._status['secondary'].connected = True

        # 应返回可用的secondary
        assert manager.get_best_source(DataType.QUOTE) == 'secondary'

    @pytest.mark.asyncio
    async def test_query_success(self):
        """测试查询成功"""
        manager = DataSourceManager()
        adapter = MockAdapter(DataSourceConfig(name='test'))
        manager.register('test', adapter, data_types=[DataType.QUOTE])
        manager._status['test'].connected = True

        result = await manager.query(DataType.QUOTE, codes=['123456'])

        assert not result.empty
        assert adapter.query_count == 1

    @pytest.mark.asyncio
    async def test_query_with_cache(self):
        """测试查询缓存"""
        manager = DataSourceManager()
        adapter = MockAdapter(DataSourceConfig(name='test'))
        manager.register('test', adapter, data_types=[DataType.QUOTE])
        manager._status['test'].connected = True

        # 第一次查询
        await manager.query(DataType.QUOTE, codes=['123456'])
        assert adapter.query_count == 1

        # 第二次应使用缓存
        await manager.query(DataType.QUOTE, codes=['123456'])
        assert adapter.query_count == 1  # 未增加

    @pytest.mark.asyncio
    async def test_failover_on_error(self):
        """测试故障转移"""
        manager = DataSourceManager()

        # 主数据源会失败
        primary = MockAdapter(DataSourceConfig(name='primary'), should_fail=True)
        backup = MockAdapter(DataSourceConfig(name='backup'))

        manager.register('primary', primary, priority=10, data_types=[DataType.QUOTE], failover_to='backup')
        manager.register('backup', backup, priority=20, data_types=[DataType.QUOTE])

        manager._status['primary'].connected = True
        manager._status['backup'].connected = True

        result = await manager.query(DataType.QUOTE, codes=['123456'])

        # 应该通过backup获取数据
        assert not result.empty
        assert backup.query_count == 1

    @pytest.mark.asyncio
    async def test_all_sources_failed(self):
        """测试所有数据源都失败"""
        manager = DataSourceManager()

        primary = MockAdapter(DataSourceConfig(name='primary'), should_fail=True)
        backup = MockAdapter(DataSourceConfig(name='backup'), should_fail=True)

        manager.register('primary', primary, priority=10, data_types=[DataType.QUOTE], failover_to='backup')
        manager.register('backup', backup, priority=20, data_types=[DataType.QUOTE])

        manager._status['primary'].connected = True
        manager._status['backup'].connected = True

        result = await manager.query(DataType.QUOTE, codes=['123456'])

        # 应返回空DataFrame
        assert result.empty

    @pytest.mark.asyncio
    async def test_connect_all(self):
        """测试连接所有数据源"""
        manager = DataSourceManager()

        adapter1 = MockAdapter(DataSourceConfig(name='source1'))
        adapter2 = MockAdapter(DataSourceConfig(name='source2'), should_fail=True)

        manager.register('source1', adapter1)
        manager.register('source2', adapter2)

        results = await manager.connect_all()

        assert results['source1'] is True
        assert results['source2'] is False

    @pytest.mark.asyncio
    async def test_health_check(self):
        """测试健康检查"""
        manager = DataSourceManager()

        adapter = MockAdapter(DataSourceConfig(name='test'))
        manager.register('test', adapter)
        # 连接adapter
        await adapter.connect()

        results = await manager.health_check()

        assert 'test' in results
        assert results['test']['connected'] is True

    def test_cache_operations(self):
        """测试缓存操作"""
        manager = DataSourceManager()

        # 添加缓存
        manager._cache['test_key'] = pd.DataFrame({'a': [1, 2]})
        manager._cache_ttl['test_key'] = datetime.now()

        # 清除缓存
        count = manager.clear_cache()

        assert count == 1
        assert len(manager._cache) == 0

    def test_status_update(self):
        """测试状态更新"""
        manager = DataSourceManager()
        adapter = MockAdapter(DataSourceConfig(name='test'))
        manager.register('test', adapter)

        # 更新成功状态
        manager._update_status('test', success=True, latency=100)
        assert manager._status['test'].request_count == 1
        assert manager._status['test'].last_success is not None

        # 更新失败状态
        manager._update_status('test', success=False, error="test error")
        assert manager._status['test'].error_count == 1
        assert manager._status['test'].last_error == "test error"


class TestDataTypeRouting:
    """测试数据类型路由"""

    def test_data_type_filtering(self):
        """测试数据类型过滤"""
        manager = DataSourceManager()

        adapter1 = MockAdapter(DataSourceConfig(name='quotes'))
        adapter2 = MockAdapter(DataSourceConfig(name='announcements'))

        manager.register('quotes', adapter1, priority=10, data_types=[DataType.QUOTE])
        manager.register('announcements', adapter2, priority=10, data_types=[DataType.ANNOUNCEMENT])

        manager._status['quotes'].connected = True
        manager._status['announcements'].connected = True

        # 应根据数据类型选择正确的源
        assert manager.get_best_source(DataType.QUOTE) == 'quotes'
        assert manager.get_best_source(DataType.ANNOUNCEMENT) == 'announcements'

    def test_multiple_types_per_source(self):
        """测试一个源支持多种数据类型"""
        manager = DataSourceManager()

        adapter = MockAdapter(DataSourceConfig(name='multi'))
        manager.register(
            'multi',
            adapter,
            data_types=[DataType.QUOTE, DataType.CONVERTIBLE, DataType.FINANCIAL],
        )
        manager._status['multi'].connected = True

        assert manager.get_best_source(DataType.QUOTE) == 'multi'
        assert manager.get_best_source(DataType.CONVERTIBLE) == 'multi'
        assert manager.get_best_source(DataType.FINANCIAL) == 'multi'


class TestCacheBehavior:
    """测试缓存行为"""

    @pytest.mark.asyncio
    async def test_cache_ttl(self):
        """测试缓存过期"""
        manager = DataSourceManager()
        adapter = MockAdapter(DataSourceConfig(name='test'))
        manager.register('test', adapter, data_types=[DataType.QUOTE])
        manager._status['test'].connected = True

        # 第一次查询
        await manager.query(DataType.QUOTE, codes=['123456'], cache_ttl=1)

        # 立即查询应使用缓存
        await manager.query(DataType.QUOTE, codes=['123456'])
        assert adapter.query_count == 1

        # 等待缓存过期
        await asyncio.sleep(1.1)

        # 应重新查询
        await manager.query(DataType.QUOTE, codes=['123456'])
        assert adapter.query_count == 2

    @pytest.mark.asyncio
    async def test_cache_disabled(self):
        """测试禁用缓存"""
        manager = DataSourceManager()
        adapter = MockAdapter(DataSourceConfig(name='test'))
        manager.register('test', adapter, data_types=[DataType.QUOTE])
        manager._status['test'].connected = True

        # 禁用缓存查询两次
        await manager.query(DataType.QUOTE, codes=['123456'], use_cache=False)
        await manager.query(DataType.QUOTE, codes=['123456'], use_cache=False)

        assert adapter.query_count == 2
