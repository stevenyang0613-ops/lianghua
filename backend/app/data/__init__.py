"""
数据源模块

提供统一的数据访问接口
"""

from .manager import (
    DataSourceManager,
    DataSourceStatus,
    DataSourcePriority,
    get_data_source_manager,
    init_data_sources,
)
from .sync_service import (
    DataSyncService,
    SyncTask,
    get_sync_service,
)
from .config import (
    DataSourceSettings,
    load_data_source_config,
)

__all__ = [
    # 管理器
    'DataSourceManager',
    'DataSourceStatus',
    'DataSourcePriority',
    'get_data_source_manager',
    'init_data_sources',

    # 同步服务
    'DataSyncService',
    'SyncTask',
    'get_sync_service',

    # 配置
    'DataSourceSettings',
    'load_data_source_config',
]
