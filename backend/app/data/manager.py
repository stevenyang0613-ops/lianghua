"""
数据源管理器

统一管理多个数据源，支持：
- 多数据源切换
- 数据源健康检查
- 自动故障转移
- 数据缓存

已注册数据源:
  ① eastmoney   — 东方财富 (默认启用, 无需认证, 全数据类型)
  ② cninfo      — 巨潮资讯 (公告专用, 默认关闭, macOS沙盒下可能失败)
  ③ mx (妙想)   — 东方财富官方API (需 MX_APIKEY, 行情/财务/资讯)
  ④ wind        — Wind (需授权, 最高优先级)
  ⑤ tonghuashun — 同花顺 (需授权)
  ⑥ tdx         — 通达信 (默认启用, 低延迟行情备份)
"""

import asyncio
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import pandas as pd
import logging

from .adapters.base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DataSourceStatus:
    """数据源状态"""
    name: str
    connected: bool
    last_success: Optional[datetime]
    last_error: Optional[str]
    request_count: int
    error_count: int
    avg_latency_ms: float


@dataclass
class DataSourcePriority:
    """数据源优先级配置"""
    name: str
    priority: int  # 越小优先级越高
    data_types: List[DataType]  # 支持的数据类型
    is_primary: bool = False
    failover_to: Optional[str] = None  # 故障转移目标


class DataSourceManager:
    """数据源管理器"""

    def __init__(self):
        self._adapters: Dict[str, DataSourceAdapter] = {}
        self._priorities: Dict[str, DataSourcePriority] = {}
        self._status: Dict[str, DataSourceStatus] = {}
        self._cache: Dict[str, Any] = {}
        self._cache_ttl: Dict[str, datetime] = {}

    def register(
        self,
        name: str,
        adapter: DataSourceAdapter,
        priority: int = 100,
        data_types: List[DataType] = None,
        is_primary: bool = False,
        failover_to: str = None,
    ) -> None:
        """注册数据源"""
        self._adapters[name] = adapter
        self._priorities[name] = DataSourcePriority(
            name=name,
            priority=priority,
            data_types=data_types or list(DataType),
            is_primary=is_primary,
            failover_to=failover_to,
        )
        self._status[name] = DataSourceStatus(
            name=name,
            connected=False,
            last_success=None,
            last_error=None,
            request_count=0,
            error_count=0,
            avg_latency_ms=0,
        )
        logger.info(f"[DataSource] Registered: {name} (priority={priority}, primary={is_primary})")

    async def connect_all(self) -> Dict[str, bool]:
        """连接所有数据源"""
        results = {}
        for name, adapter in self._adapters.items():
            try:
                connected = await adapter.connect()
                self._status[name].connected = connected
                results[name] = connected
                if connected:
                    logger.info(f"[DataSource] Connected: {name}")
                else:
                    logger.warning(f"[DataSource] Connection failed: {name}")
            except Exception as e:
                logger.error(f"[DataSource] Connection error {name}: {e}")
                results[name] = False
                self._status[name].last_error = str(e)
        return results

    async def disconnect_all(self) -> None:
        """断开所有数据源"""
        for name, adapter in self._adapters.items():
            try:
                await adapter.disconnect()
                self._status[name].connected = False
            except Exception as e:
                logger.warning(f"[DataSource] Disconnect error {name}: {e}")

    def get_best_source(self, data_type: DataType) -> Optional[str]:
        """获取指定数据类型的最佳数据源"""
        candidates = []
        for name, priority in self._priorities.items():
            if data_type in priority.data_types and self._status[name].connected:
                candidates.append((priority.priority, name))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    async def query(
        self,
        data_type: DataType,
        codes: List[str] = None,
        start_date = None,
        end_date = None,
        use_cache: bool = True,
        cache_ttl: int = 300,  # 5分钟缓存
    ) -> pd.DataFrame:
        """执行数据查询"""
        # 检查缓存
        cache_key = self._make_cache_key(data_type, codes, start_date, end_date)
        if use_cache and cache_key in self._cache:
            if datetime.now() < self._cache_ttl.get(cache_key, datetime.min):
                logger.debug(f"[DataSource] Using cached data for {cache_key}")
                return self._cache[cache_key]

        # 获取最佳数据源
        source_name = self.get_best_source(data_type)
        if not source_name:
            logger.error(f"[DataSource] No available source for {data_type}")
            return pd.DataFrame()

        query = DataQuery(
            data_type=data_type,
            codes=codes,
            start_date=start_date,
            end_date=end_date,
        )

        # 执行查询
        start_time = datetime.now()
        try:
            adapter = self._adapters[source_name]
            result = await adapter.query(query)

            # 更新状态
            latency = (datetime.now() - start_time).total_seconds() * 1000
            self._update_status(source_name, success=True, latency=latency)

            # 缓存结果
            if use_cache and not result.empty:
                self._cache[cache_key] = result
                self._cache_ttl[cache_key] = datetime.now() + timedelta(seconds=cache_ttl)
                # 随机采样淘汰：每次 set 有 5% 概率检查过期缓存
                if len(self._cache) > 100 and random.random() < 0.05:
                    self._clear_expired()

            return result

        except Exception as e:
            self._update_status(source_name, success=False, error=str(e))

            # 尝试故障转移
            failover = self._priorities[source_name].failover_to
            if failover and failover in self._adapters:
                logger.warning(f"[DataSource] Failover from {source_name} to {failover}")
                try:
                    adapter = self._adapters[failover]
                    result = await adapter.query(query)
                    return result
                except Exception as e2:
                    logger.error(f"[DataSource] Failover error: {e2}")

            return pd.DataFrame()

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取实时行情"""
        return await self.query(DataType.QUOTE, codes=codes, use_cache=False)

    async def get_convertible_bonds(self, date=None) -> pd.DataFrame:
        """获取转债列表"""
        return await self.query(DataType.CONVERTIBLE, end_date=date)

    async def get_announcements(
        self,
        codes: List[str] = None,
        start_date=None,
        end_date=None,
        keywords: List[str] = None,
    ) -> pd.DataFrame:
        """获取公告"""
        query = DataQuery(
            data_type=DataType.ANNOUNCEMENT,
            codes=codes,
            start_date=start_date,
            end_date=end_date,
            filters={'keywords': keywords},
        )

        source_name = self.get_best_source(DataType.ANNOUNCEMENT)
        if not source_name:
            return pd.DataFrame()

        adapter = self._adapters[source_name]
        return await adapter.get_announcements(codes, start_date, end_date, keywords)

    def _make_cache_key(
        self,
        data_type: DataType,
        codes: List[str],
        start_date,
        end_date,
    ) -> str:
        """生成缓存键"""
        codes_str = ','.join(sorted(codes)) if codes else 'all'
        start_str = start_date.isoformat() if start_date else 'none'
        end_str = end_date.isoformat() if end_date else 'none'
        return f"{data_type.value}:{codes_str}:{start_str}:{end_str}"

    def _update_status(
        self,
        source_name: str,
        success: bool,
        latency: float = 0,
        error: str = None,
    ) -> None:
        """更新数据源状态"""
        status = self._status[source_name]
        status.request_count += 1

        if success:
            status.last_success = datetime.now()
            # 更新平均延迟
            if status.avg_latency_ms == 0:
                status.avg_latency_ms = latency
            else:
                status.avg_latency_ms = (status.avg_latency_ms * 0.9 + latency * 0.1)
        else:
            status.error_count += 1
            status.last_error = error

    def get_status(self) -> Dict[str, DataSourceStatus]:
        """获取所有数据源状态"""
        return self._status.copy()

    def clear_cache(self) -> int:
        """清除缓存"""
        count = len(self._cache)
        self._cache.clear()
        self._cache_ttl.clear()
        return count

    def _clear_expired(self) -> int:
        """清除已过期缓存条目，防止内存无限增长"""
        now = datetime.now()
        expired = [k for k, t in self._cache_ttl.items() if now >= t]
        for k in expired:
            self._cache.pop(k, None)
            self._cache_ttl.pop(k, None)
        return len(expired)

    async def health_check(self) -> Dict[str, Any]:
        """健康检查所有数据源"""
        results = {}
        for name, adapter in self._adapters.items():
            try:
                health = await adapter.health_check()
                results[name] = health
            except Exception as e:
                results[name] = {
                    'name': name,
                    'connected': False,
                    'error': str(e),
                }
        return results


# 全局单例
_data_source_manager: Optional[DataSourceManager] = None


def get_data_source_manager() -> DataSourceManager:
    """获取数据源管理器"""
    global _data_source_manager
    if _data_source_manager is None:
        _data_source_manager = DataSourceManager()
    return _data_source_manager


async def init_data_sources(config: Dict[str, Any] = None) -> DataSourceManager:
    """初始化数据源"""
    manager = get_data_source_manager()
    config = config or {}

    # 注册东方财富（默认可用，无需认证）- 全数据类型支持
    if config.get('eastmoney', {}).get('enabled', True):
        from .adapters.eastmoney_adapter import EastmoneyAdapter
        adapter = EastmoneyAdapter(DataSourceConfig(name='eastmoney'))
        manager.register(
            name='eastmoney',
            adapter=adapter,
            priority=100,
            data_types=[
                DataType.QUOTE, DataType.CONVERTIBLE, DataType.STOCK,
                DataType.FINANCIAL, DataType.INDUSTRY, DataType.MACRO,
            ],
            is_primary=True,
        )

    # 注册巨潮资讯 - 公告数据源（默认关闭：cninfo 在 macOS sandbox 下 py_mini_racer 失败，见 AGENTS.md #48）
    if config.get('cninfo', {}).get('enabled', settings.CNINFO_ENABLED):
        from .adapters.cninfo_adapter import CNInfoAdapter
        adapter = CNInfoAdapter(DataSourceConfig(name='cninfo'))
        manager.register(
            name='cninfo',
            adapter=adapter,
            priority=50,
            data_types=[DataType.ANNOUNCEMENT],
            is_primary=True,
            failover_to='eastmoney',
        )

    # 注册东方财富妙想MX（需要API Key）- 行情/财务/资讯
    if config.get('mx', {}).get('enabled', True):
        try:
            from .adapters.mx_adapter import MXAdapter
            # 剥离 enabled 等配置级 key，只保留 api_key 等用户参数
            mx_cfg = config.get('mx', {})
            mx_extra = {k: v for k, v in mx_cfg.items() if k not in ('enabled', 'timeout')}
            adapter = MXAdapter(DataSourceConfig(
                name='mx',
                timeout=mx_cfg.get('timeout', 30),
                extra=mx_extra,
            ))
            connected = await adapter.connect()
            # 降级模式下降低优先级，避免空查询触发failover
            priority = 120 if getattr(adapter, '_degraded_mode', False) else 80
            manager.register(
                name='mx',
                adapter=adapter,
                priority=priority,
                data_types=[
                    DataType.QUOTE, DataType.STOCK, DataType.FINANCIAL,
                    DataType.CONVERTIBLE, DataType.ANNOUNCEMENT,
                ],
                is_primary=False,
                failover_to='eastmoney',
            )
            mode = 'degraded' if getattr(adapter, '_degraded_mode', False) else 'full'
            logger.info(f'[DataSource] Registered: mx (priority={priority}, mode={mode}, primary=False, failover=eastmoney)')
        except Exception as e:
            logger.warning(f'[DataSource] MX adapter registration failed: {e}')

    # 注册Wind（需要授权）
    if config.get('wind', {}).get('enabled', False):
        from .adapters.wind_adapter import WindAdapter
        adapter = WindAdapter(DataSourceConfig(
            name='wind',
            extra=config.get('wind', {}),
        ))
        manager.register(
            name='wind',
            adapter=adapter,
            priority=10,  # 最高优先级
            data_types=list(DataType),
            is_primary=False,
            failover_to='eastmoney',
        )

    # 注册同花顺（需要授权）
    if config.get('tonghuashun', {}).get('enabled', False):
        from .adapters.tonghuashun_adapter import TonghuashunAdapter
        adapter = TonghuashunAdapter(DataSourceConfig(
            name='tonghuashun',
            extra=config.get('tonghuashun', {}),
        ))
        manager.register(
            name='tonghuashun',
            adapter=adapter,
            priority=20,
            data_types=[DataType.QUOTE, DataType.CONVERTIBLE, DataType.FINANCIAL],
            is_primary=False,
            failover_to='eastmoney',
        )

    # 注册通达信（默认启用，无需认证）- 低延迟行情备份
    if config.get('tdx', {}).get('enabled', True):
        from .adapters.tdx_data_adapter import TdxDataAdapter
        adapter = TdxDataAdapter(DataSourceConfig(
            name='tdx',
            timeout=config.get('tdx', {}).get('timeout', 10),
        ))
        manager.register(
            name='tdx',
            adapter=adapter,
            priority=60,
            data_types=[
                DataType.QUOTE, DataType.STOCK, DataType.FINANCIAL,
            ],
            is_primary=False,
            failover_to='eastmoney',
        )

    # 连接所有数据源
    await manager.connect_all()

    return manager
