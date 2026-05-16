"""
数据源适配器模块

提供统一的数据源接口，支持：
- Wind金融终端
- 同花顺iFinD
- 巨潮资讯
- 东方财富
"""

from .base import DataSourceAdapter, DataQuery
from .wind_adapter import WindAdapter
from .tonghuashun_adapter import TonghuashunAdapter
from .cninfo_adapter import CNInfoAdapter
from .eastmoney_adapter import EastmoneyAdapter

__all__ = [
    'DataSourceAdapter',
    'DataQuery',
    'WindAdapter',
    'TonghuashunAdapter',
    'CNInfoAdapter',
    'EastmoneyAdapter',
]
