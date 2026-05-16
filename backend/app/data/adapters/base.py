"""
数据源适配器基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum
import pandas as pd


class DataType(Enum):
    """数据类型"""
    QUOTE = 'quote'              # 行情数据
    CONVERTIBLE = 'convertible'  # 转债数据
    STOCK = 'stock'              # 股票数据
    FINANCIAL = 'financial'      # 财务数据
    ANNOUNCEMENT = 'announcement' # 公告数据
    INDUSTRY = 'industry'        # 行业数据
    MACRO = 'macro'              # 宏观数据


@dataclass
class DataQuery:
    """数据查询请求"""
    data_type: DataType
    codes: Optional[List[str]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    fields: Optional[List[str]] = None
    filters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'data_type': self.data_type.value,
            'codes': self.codes,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'fields': self.fields,
            'filters': self.filters,
        }


@dataclass
class DataSourceConfig:
    """数据源配置"""
    name: str
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    endpoint: Optional[str] = None
    timeout: int = 30
    retry_count: int = 3
    retry_delay: float = 1.0
    extra: Dict[str, Any] = field(default_factory=dict)


class DataSourceAdapter(ABC):
    """数据源适配器基类"""

    def __init__(self, config: DataSourceConfig):
        self._config = config
        self._connected = False
        self._last_error: Optional[str] = None

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    async def query(self, query: DataQuery) -> pd.DataFrame:
        """执行查询"""
        pass

    @abstractmethod
    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取实时行情"""
        pass

    @abstractmethod
    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """获取转债列表"""
        pass

    @abstractmethod
    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取公告"""
        pass

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            'name': self.name,
            'connected': self._connected,
            'last_error': self._last_error,
            'timestamp': datetime.now().isoformat(),
        }

    def _handle_error(self, error: Exception) -> None:
        """处理错误"""
        self._last_error = str(error)
        import logging
        logging.getLogger(__name__).error(f"[{self.name}] Error: {error}")
