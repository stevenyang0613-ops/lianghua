"""
Wind金融终端适配器

需要安装WindPy: pip install WindPy
"""

from datetime import date, datetime
from typing import Optional, List, Dict, Any
import pandas as pd
import asyncio
import logging

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

logger = logging.getLogger(__name__)


class WindAdapter(DataSourceAdapter):
    """Wind金融终端适配器"""

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        self._w = None

    async def connect(self) -> bool:
        """建立Wind连接"""
        try:
            # 尝试导入WindPy
            try:
                from WindPy import w
                self._w = w
            except ImportError:
                logger.warning("[Wind] WindPy not installed, using mock mode")
                self._connected = False
                return False

            # 启动Wind
            result = await asyncio.to_thread(w.start)

            if result.errorCode == 0:
                self._connected = True
                logger.info("[Wind] Connected successfully")
                return True
            else:
                self._last_error = f"Wind start failed: {result.errorCode}"
                return False

        except Exception as e:
            self._handle_error(e)
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False
        logger.info("[Wind] Disconnected")

    async def query(self, query: DataQuery) -> pd.DataFrame:
        """执行Wind查询"""
        if not self._connected or self._w is None:
            return pd.DataFrame()

        try:
            if query.data_type == DataType.QUOTE:
                return await self._query_quotes(query)
            elif query.data_type == DataType.CONVERTIBLE:
                return await self.get_convertible_bonds(query.end_date)
            elif query.data_type == DataType.FINANCIAL:
                return await self._query_financial(query)
            else:
                return pd.DataFrame()

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def _query_quotes(self, query: DataQuery) -> pd.DataFrame:
        """查询行情"""
        codes = query.codes or []
        if not codes:
            return pd.DataFrame()

        fields = query.fields or ['open', 'high', 'low', 'close', 'volume', 'amt']

        start = query.start_date.strftime('%Y-%m-%d') if query.start_date else '2023-01-01'
        end = query.end_date.strftime('%Y-%m-%d') if query.end_date else datetime.now().strftime('%Y-%m-%d')

        result = await asyncio.to_thread(
            self._w.wsd,
            codes,
            fields,
            start,
            end,
            ""
        )

        if result.errorCode != 0:
            logger.error(f"[Wind] Query error: {result.errorCode}")
            return pd.DataFrame()

        return pd.DataFrame(result.Data, index=fields).T

    async def _query_financial(self, query: DataQuery) -> pd.DataFrame:
        """查询财务数据"""
        codes = query.codes or []
        if not codes:
            return pd.DataFrame()

        fields = query.fields or ['tot_assets', 'tot_liab', 'revenue', 'net_profit']

        result = await asyncio.to_thread(
            self._w.wss,
            codes,
            fields,
            ""
        )

        if result.errorCode != 0:
            return pd.DataFrame()

        return pd.DataFrame(result.Data, index=fields).T

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取实时行情"""
        if not self._connected or self._w is None:
            return pd.DataFrame()

        fields = ['rt_last', 'rt_chg_pct', 'rt_vol', 'rt_amt', 'rt_bid1', 'rt_ask1']

        result = await asyncio.to_thread(
            self._w.wsq,
            codes,
            fields
        )

        if result.errorCode != 0:
            return pd.DataFrame()

        df = pd.DataFrame(result.Data, index=fields).T
        df['code'] = codes
        return df

    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """获取转债列表"""
        if not self._connected or self._w is None:
            return pd.DataFrame()

        # 获取所有转债代码
        result = await asyncio.to_thread(
            self._w.wset,
            "sectorconstituent",
            f"date={date.strftime('%Y-%m-%d') if date else datetime.now().strftime('%Y-%m-%d')}",
            "sectorid=a1b010e01040000"  # 可转债板块
        )

        if result.errorCode != 0:
            return pd.DataFrame()

        codes = [item[1] for item in result.Data]

        # 获取转债详细信息
        fields = [
            'bond_code', 'bond_name', 'close', 'convpremium_ratio',
            'conv_price', 'convpremium_ratio', 'ipo_date', 'maturity_date',
            'coupon_rate', 'b_carrying_interest', 'volume', 'amt'
        ]

        if not codes:
            return pd.DataFrame()

        result = await asyncio.to_thread(
            self._w.wss,
            codes[:500],  # 限制数量
            fields
        )

        if result.errorCode != 0:
            return pd.DataFrame()

        return pd.DataFrame(result.Data, index=fields).T

    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取公告"""
        if not self._connected or self._w is None:
            return pd.DataFrame()

        # Wind公告查询
        start = start_date.strftime('%Y-%m-%d') if start_date else (datetime.now() - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
        end = end_date.strftime('%Y-%m-%d') if end_date else datetime.now().strftime('%Y-%m-%d')

        result = await asyncio.to_thread(
            self._w.wset,
            "announcement",
            f"startdate={start}",
            f"enddate={end}",
            "sectorid=a1b010e01040000"  # 可转债
        )

        if result.errorCode != 0:
            return pd.DataFrame()

        return pd.DataFrame(result.Data)
