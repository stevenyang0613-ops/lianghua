"""
东方财富适配器

通过HTTP API获取行情和财务数据
"""

from datetime import date, datetime
from typing import Optional, List
import pandas as pd
import asyncio
import aiohttp
import logging

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

logger = logging.getLogger(__name__)


class EastmoneyAdapter(DataSourceAdapter):
    """东方财富适配器"""

    QUOTE_URL = "http://push2.eastmoney.com/api/qt/ulist.np"
    CONVERTIBLE_URL = "http://datacenter-web.eastmoney.com/api/data/v1/get"

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """建立连接"""
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'http://data.eastmoney.com/',
                }
            )
            self._connected = True
            logger.info("[Eastmoney] Connected successfully")
            return True

        except Exception as e:
            self._handle_error(e)
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        if self._session:
            await self._session.close()
        self._connected = False
        logger.info("[Eastmoney] Disconnected")

    async def query(self, query: DataQuery) -> pd.DataFrame:
        """执行查询"""
        if not self._connected:
            return pd.DataFrame()

        if query.data_type == DataType.QUOTE:
            return await self.get_realtime_quotes(query.codes or [])
        elif query.data_type == DataType.CONVERTIBLE:
            return await self.get_convertible_bonds(query.end_date)

        return pd.DataFrame()

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取实时行情"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        if not codes:
            return pd.DataFrame()

        try:
            # 转换代码格式：123456 -> 123456.SH 或 123456.SZ
            secids = []
            for code in codes:
                if code.startswith('11'):
                    secids.append(f"{code}.SH")
                elif code.startswith('12'):
                    secids.append(f"{code}.SZ")
                else:
                    secids.append(f"{code}.SZ")

            params = {
                'fltt': 2,
                'invt': 2,
                'fields': 'f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124,f128,f136',
                'secids': ','.join(secids),
            }

            async with self._session.get(self.QUOTE_URL, params=params) as response:
                if response.status != 200:
                    return pd.DataFrame()

                data = await response.json()

                if not data or 'data' not in data or 'diff' not in data['data']:
                    return pd.DataFrame()

                df = pd.DataFrame(data['data']['diff'])

                # 重命名列
                column_map = {
                    'f12': 'code',
                    'f14': 'name',
                    'f2': 'price',
                    'f3': 'change_pct',
                    'f62': 'premium_ratio',
                    'f128': 'ytm',
                }

                df = df.rename(columns=column_map)

                return df

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """获取转债列表"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            params = {
                'sortColumns': 'PUBLIC_START_DATE',
                'sortTypes': -1,
                'pageSize': 500,
                'pageNumber': 1,
                'reportName': 'RPT_BOND_CB_LIST',
                'columns': 'ALL',
                'quoteColumns': 'f2~01~CONVERTCODE',
                'source': 'WEB',
                'client': 'WEB',
            }

            async with self._session.get(self.CONVERTIBLE_URL, params=params) as response:
                if response.status != 200:
                    return pd.DataFrame()

                data = await response.json()

                if not data or 'result' not in data or 'data' not in data['result']:
                    return pd.DataFrame()

                result_data = data['result']['data']

                if not result_data:
                    return pd.DataFrame()

                df = pd.DataFrame(result_data)

                # 解析字段
                if 'BOND_CODE' in df.columns:
                    df = df.rename(columns={
                        'BOND_CODE': 'code',
                        'BOND_SHORT_NAME': 'name',
                        'CLOSE': 'price',
                        'CONVERTPREMIUM_RATIO': 'premium_ratio',
                        'CONVERT_PRICE': 'conversion_price',
                        'PUBLIC_START_DATE': 'ipo_date',
                        'EXPIRE_DATE': 'maturity_date',
                    })

                return df

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """东方财富公告接口"""
        # 东方财富公告需要不同的API
        return pd.DataFrame()

    async def get_financial_indicators(self, codes: List[str]) -> pd.DataFrame:
        """获取财务指标"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            # 转换为股票代码
            stock_codes = []
            for code in codes:
                # 简单假设转债代码对应正股
                stock_codes.append(code.replace('12', '00'))

            url = "http://push2.eastmoney.com/api/qt/stock/kline/get"

            results = []
            for code in stock_codes[:50]:  # 限制请求
                params = {
                    'secid': f"0.{code}",  # 深市
                    'fields1': 'f1,f2,f3,f4,f5,f6',
                    'fields2': 'f51,f52,f53,f54,f55,f56,f57',
                    'klt': 101,  # 日K
                    'fqt': 1,
                    'end': '20500101',
                    'lmt': 30,
                }

                async with self._session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and 'data' in data and 'klines' in data['data']:
                            for line in data['data']['klines']:
                                parts = line.split(',')
                                results.append({
                                    'code': code,
                                    'date': parts[0],
                                    'open': float(parts[1]),
                                    'close': float(parts[2]),
                                    'high': float(parts[3]),
                                    'low': float(parts[4]),
                                    'volume': float(parts[5]),
                                })

            return pd.DataFrame(results)

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()
