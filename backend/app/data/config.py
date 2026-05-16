"""
数据源配置示例

配置真实数据源API
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import os


@dataclass
class DataSourceSettings:
    """数据源配置"""

    # 东方财富（免费，无需认证）
    eastmoney: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'timeout': 30,
    })

    # 巨潮资讯（免费，无需认证）
    cninfo: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'timeout': 30,
    })

    # Wind金融终端（需要授权）
    wind: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': False,  # 需要安装WindPy并登录
        'username': '',
        'password': '',
        'timeout': 30,
    })

    # 同花顺iFinD（需要授权）
    tonghuashun: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': False,  # 需要安装iFinD并登录
        'username': '',
        'password': '',
        'timeout': 30,
    })

    # 数据同步配置
    sync: Dict[str, Any] = field(default_factory=lambda: {
        'quotes_interval': 60,      # 行情同步间隔（秒）
        'announcements_interval': 300,  # 公告同步间隔（秒）
        'cache_ttl': 300,           # 缓存有效期（秒）
    })


# 从环境变量加载配置
def load_data_source_config() -> DataSourceSettings:
    """从环境变量加载配置"""
    settings = DataSourceSettings()

    # Wind配置
    wind_enabled = os.getenv('WIND_ENABLED', 'false').lower() == 'true'
    if wind_enabled:
        settings.wind = {
            'enabled': True,
            'username': os.getenv('WIND_USERNAME', ''),
            'password': os.getenv('WIND_PASSWORD', ''),
            'timeout': int(os.getenv('WIND_TIMEOUT', '30')),
        }

    # 同花顺配置
    ths_enabled = os.getenv('THS_ENABLED', 'false').lower() == 'true'
    if ths_enabled:
        settings.tonghuashun = {
            'enabled': True,
            'username': os.getenv('THS_USERNAME', ''),
            'password': os.getenv('THS_PASSWORD', ''),
            'timeout': int(os.getenv('THS_TIMEOUT', '30')),
        }

    # 同步配置
    settings.sync = {
        'quotes_interval': int(os.getenv('SYNC_QUOTES_INTERVAL', '60')),
        'announcements_interval': int(os.getenv('SYNC_ANNOUNCEMENTS_INTERVAL', '300')),
        'cache_ttl': int(os.getenv('CACHE_TTL', '300')),
    }

    return settings


# 配置示例
CONFIG_EXAMPLE = """
# .env 文件配置示例

# Wind金融终端配置
WIND_ENABLED=false
WIND_USERNAME=your_username
WIND_PASSWORD=your_password
WIND_TIMEOUT=30

# 同花顺iFinD配置
THS_ENABLED=false
THS_USERNAME=your_username
THS_PASSWORD=your_password
THS_TIMEOUT=30

# 数据同步配置
SYNC_QUOTES_INTERVAL=60
SYNC_ANNOUNCEMENTS_INTERVAL=300
CACHE_TTL=300
"""


# 使用示例
USAGE_EXAMPLE = """
# 在 main.py 中初始化数据源

from app.data.manager import init_data_sources
from app.core.config import load_data_source_config

async def startup():
    # 加载配置
    config = load_data_source_config()

    # 初始化数据源
    manager = await init_data_sources({
        'eastmoney': config.eastmoney,
        'cninfo': config.cninfo,
        'wind': config.wind,
        'tonghuashun': config.tonghuashun,
    })

    # 检查连接状态
    status = await manager.health_check()
    for name, health in status.items():
        print(f"{name}: {'connected' if health.get('connected') else 'disconnected'}")

# 查询数据
from app.data.manager import get_data_source_manager, DataType

async def get_convertibles():
    manager = get_data_source_manager()

    # 获取转债列表
    bonds = await manager.get_convertible_bonds()

    # 获取实时行情
    quotes = await manager.get_realtime_quotes(['123456', '123457'])

    # 获取公告
    announcements = await manager.get_announcements(
        keywords=['下修', '强赎'],
        start_date='2024-01-01',
    )

    return bonds, quotes, announcements
"""
