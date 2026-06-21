"""
同花顺iFinD适配器

需要安装iFinD: pip install iFinD
"""

from datetime import date, datetime
from typing import Optional, List
import pandas as pd
import asyncio
import logging

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

logger = logging.getLogger(__name__)


class TonghuashunAdapter(DataSourceAdapter):
    """同花顺iFinD适配器"""

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        self._ths = None
        self._ths_logout = None

    async def connect(self) -> bool:
        """建立iFinD连接"""
        try:
            try:
                from iFinD import THS_iFinDLogin, THS_iFinDLogout
                self._ths_login = THS_iFinDLogin
                self._ths_logout = THS_iFinDLogout
            except ImportError:
                logger.warning("[iFinD] iFinD not installed, using mock mode")
                self._connected = False
                return False

            # 登录iFinD
            result = await asyncio.to_thread(
                self._ths_login,
                self._config.extra.get('username', ''),
                self._config.extra.get('password', '')
            )

            if result == 0 or result == -201:  # 0成功, -201已登录
                self._connected = True
                logger.info("[iFinD] Connected successfully")
                return True
            else:
                self._last_error = f"iFinD login failed: {result}"
                return False

        except Exception as e:
            self._handle_error(e)
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        if getattr(self, '_ths_logout', None):
            await asyncio.to_thread(self._ths_logout)
        self._connected = False
        logger.info("[iFinD] Disconnected")

    async def query(self, query: DataQuery) -> pd.DataFrame:
        """执行iFinD查询"""
        if not self._connected:
            return pd.DataFrame()

        try:
            if query.data_type == DataType.QUOTE:
                return await self._query_quotes(query)
            elif query.data_type == DataType.CONVERTIBLE:
                return await self.get_convertible_bonds(query.end_date)
            else:
                return pd.DataFrame()

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def _query_quotes(self, query: DataQuery) -> pd.DataFrame:
        """查询行情"""
        from iFinD import THS_HQ, THS_DateSerial

        codes = query.codes or []
        if not codes:
            return pd.DataFrame()

        start = query.start_date.strftime('%Y-%m-%d') if query.start_date else '2023-01-01'
        end = query.end_date.strftime('%Y-%m-%d') if query.end_date else datetime.now().strftime('%Y-%m-%d')

        codes_str = ','.join(codes)
        fields = 'ths_open_price;ths_high_price;ths_low_price;ths_close_price;ths_vol'

        result = await asyncio.to_thread(
            THS_DateSerial,
            codes_str,
            fields,
            start,
            end,
            'date:Y',
            'block'
        )

        if result is None or result.empty:
            return pd.DataFrame()

        return result

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取实时行情"""
        if not self._connected:
            return pd.DataFrame()

        from iFinD import THS_RealtimeQuotes

        codes_str = ','.join(codes)
        fields = 'ths_close;ths_chg_ratio;ths_vol;ths_amount'

        result = await asyncio.to_thread(
            THS_RealtimeQuotes,
            codes_str,
            fields
        )

        if result is None or result.empty:
            return pd.DataFrame()

        return result

    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """获取转债列表"""
        if not self._connected:
            return pd.DataFrame()

        from iFinD import THS_DataPool

        # 获取转债板块成分
        result = await asyncio.to_thread(
            THS_DataPool,
            'ths_bond_convertible' if date is None else date.strftime('%Y-%m-%d'),
            '',
            'ths_name;ths_code'
        )

        if result is None or result.empty:
            return pd.DataFrame()

        # 获取详细信息
        codes = result['ths_code'].tolist()
        codes_str = ','.join(codes[:500])

        from iFinD import THS_BasicData
        fields = 'ths_bond_short_name;ths_close_price;ths_convpremium_ratio;ths_conv_price'

        detail = await asyncio.to_thread(
            THS_BasicData,
            codes_str,
            fields
        )

        if detail is None:
            return result

        return detail

    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取公告"""
        if not self._connected:
            return pd.DataFrame()

        from iFinD import THS_News

        start = start_date.strftime('%Y-%m-%d') if start_date else (datetime.now() - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
        end = end_date.strftime('%Y-%m-%d') if end_date else datetime.now().strftime('%Y-%m-%d')

        codes_str = ','.join(codes) if codes else ''

        result = await asyncio.to_thread(
            THS_News,
            codes_str,
            'ths_public_date;ths_news_title;ths_news_content',
            start,
            end
        )

        if result is None:
            return pd.DataFrame()

        # 关键词过滤
        if keywords:
            mask = result['ths_news_title'].str.contains('|'.join(keywords), na=False)
            result = result[mask]

        return result
