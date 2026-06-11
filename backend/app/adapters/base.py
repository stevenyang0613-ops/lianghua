from abc import ABC, abstractmethod
from app.models.convertible import ConvertibleQuote


class DataSourceAdapter(ABC):
    """数据源适配器基类"""

    @abstractmethod
    async def fetch_all_quotes(self) -> list[ConvertibleQuote]:
        """获取所有可转债实时行情"""
        ...

    @abstractmethod
    async def fetch_quote(self, code: str) -> ConvertibleQuote:
        """获取单只可转债行情"""
        ...
