"""
东方财富适配器

通过HTTP API获取行情和财务数据
支持数据源: QUOTE, CONVERTIBLE, STOCK, FINANCIAL, ANNOUNCEMENT, INDUSTRY
"""
import json
import re
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any
import pandas as pd
import asyncio
import aiohttp
import logging

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

logger = logging.getLogger(__name__)


class EastmoneyAdapter(DataSourceAdapter):
    """东方财富适配器 - 全数据类型支持"""

    # API 端点
    QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np"
    CONVERTIBLE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    STOCK_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
    KLINE_URL = "https://push2.eastmoney.com/api/qt/stock/kline/get"
    FINANCIAL_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    INDUSTRY_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    ANNOUNCEMENT_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    FUND_FLOW_URL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    CB_DETAIL_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

    # Eastmoney 字段映射 - 全量
    QUOTE_FIELD_MAP = {
        'f12': 'code',        # 代码
        'f14': 'name',        # 名称
        'f2': 'price',        # 最新价
        'f3': 'change_pct',   # 涨跌幅
        'f4': 'change',       # 涨跌额
        'f5': 'volume',       # 成交量
        'f6': 'amount',       # 成交额
        'f7': 'amplitude',    # 振幅
        'f8': 'turnover_rate',# 换手率
        'f9': 'pe',           # 市盈率(动态)
        'f10': 'pe_ttm',      # 市盈率TTM
        'f15': 'high',        # 最高
        'f16': 'low',         # 最低
        'f17': 'open',        # 开盘
        'f18': 'pre_close',   # 昨收
        'f20': 'market_cap',  # 总市值
        'f21': 'circ_mv',     # 流通市值
        'f23': 'pb',          # 市净率
        'f24': 'time',        # 时间戳
        'f37': 'weight',      # 加权均价
        'f38': 'total_vol',   # 总手
        'f39': 'total_amt',   # 总额
        'f62': 'premium_ratio',  # 溢价率 (转债)
        'f66': 'conversion_value',  # 转股价值
        'f69': 'conversion_price',  # 转股价
        'f72': 'stock_price',  # 正股价
        'f75': 'stock_code',   # 正股代码
        'f78': 'stock_change_pct',  # 正股涨跌幅
        'f81': 'ytm',          # 到期收益率
        'f84': 'dual_low',     # 双低值
        'f87': 'remaining_years',  # 剩余年限
        'f124': 'issue_date',  # 发行日期
        'f128': 'coupon_rate', # 票面利率
        'f136': 'maturity_date',  # 到期日
        'f140': 'rating',      # 评级
        'f152': 'margin_ratio',  # 担保比例
        'f184': 'cb_type',     # 转债类型
    }

    # 可转债列表字段映射
    CB_COLUMN_MAP = {
        'BOND_CODE': 'code',
        'BOND_SHORT_NAME': 'name',
        'STOCK_CODE': 'stock_code',
        'STOCK_SHORT_NAME': 'stock_name',
        'CLOSE': 'price',
        'CHANGE_PCT': 'change_pct',
        'PREMIUM_RATIO': 'premium_ratio',
        'CONVERTPREMIUM_RATIO': 'premium_ratio',
        'CONVERT_PRICE': 'conversion_price',
        'CONVERT_VALUE': 'conversion_value',
        'STOCK_PRICE': 'stock_price',
        'BOND_VALUE': 'bond_value',
        'YTM': 'ytm',
        'VOLUME_RATIO': 'volume_ratio',
        'TURNOVER_RATE': 'turnover_rate',
        'RATING': 'rating',
        'RATING_ORG': 'rating_org',
        'ISSUE_DATE': 'issue_date',
        'EXPIRE_DATE': 'maturity_date',
        'PUBLIC_START_DATE': 'ipo_date',
        'BALANCE': 'outstanding_scale',
        'COUPON': 'coupon_rate',
        'FORCED_CALL_PRICE': 'forced_call_price',
        'FORCED_CALL_DAYS': 'forced_call_days',
        'PUT_PRICE': 'put_price',
        'DUAL_LOW': 'dual_low',
        'CONVERT_RATIO': 'convert_ratio',
        'REMAINING_YEARS': 'remaining_years',
        'LISTING_DATE': 'listing_date',
        'RESALE_TRIGGER_PRICE': 'resale_trigger_price',
        'RESALE_CLAUSE': 'resale_clause',
        'FORCED_CALL_CLAUSE': 'forced_call_clause',
    }

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """建立连接"""
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://data.eastmoney.com/',
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
        """执行查询 - 支持全数据类型"""
        if not self._connected:
            logger.warning("[Eastmoney] Not connected, returning empty")
            return pd.DataFrame()

        try:
            if query.data_type == DataType.QUOTE:
                return await self.get_realtime_quotes(query.codes or [])
            elif query.data_type == DataType.CONVERTIBLE:
                return await self.get_convertible_bonds(query.end_date)
            elif query.data_type == DataType.STOCK:
                return await self.get_stock_quotes(query.codes or [])
            elif query.data_type == DataType.FINANCIAL:
                return await self.get_financial_indicators(query.codes or [])
            elif query.data_type == DataType.ANNOUNCEMENT:
                return await self.get_announcements(
                    codes=query.codes,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    keywords=query.filters.get('keywords')
                )
            elif query.data_type == DataType.INDUSTRY:
                return await self.get_industry_data()
            elif query.data_type == DataType.MACRO:
                return await self.get_macro_data()
            else:
                logger.warning(f"[Eastmoney] Unsupported data type: {query.data_type}")
                return pd.DataFrame()
        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取实时行情 - 全字段映射

        codes 应为6位数字代码如 123456, 600519, 000001
        """
        if not self._connected or not self._session:
            return pd.DataFrame()
        if not codes:
            return pd.DataFrame()

        try:
            secids = []
            for code in codes:
                if code.startswith('6'):
                    secids.append(f"1.{code}")
                elif code.startswith(('0', '3')):
                    secids.append(f"0.{code}")
                elif code.startswith(('4', '8')):
                    secids.append(f"0.{code}")
                else:
                    secids.append(f"0.{code}")

            fields = ','.join(self.QUOTE_FIELD_MAP.keys())
            params = {
                'fltt': 2,
                'invt': 2,
                'fields': fields,
                'secids': ','.join(secids),
            }

            async with self._session.get(self.QUOTE_URL, params=params) as response:
                if response.status != 200:
                    logger.warning(f"[Eastmoney] Quote API returned {response.status}")
                    return pd.DataFrame()

                data = await response.json()
                if not data or 'data' not in data or 'diff' not in data['data']:
                    return pd.DataFrame()

                diff = data['data']['diff']
                if not diff:
                    return pd.DataFrame()

                df = pd.DataFrame(diff)
                df = df.rename(columns=self.QUOTE_FIELD_MAP)

                # 只保留映射后的字段
                mapped_cols = [v for v in self.QUOTE_FIELD_MAP.values() if v in df.columns]
                df = df[mapped_cols]

                # 数值类型转换
                for col in ['price', 'change_pct', 'premium_ratio', 'ytm', 'volume',
                            'amount', 'pe', 'pb', 'turnover_rate', 'stock_price',
                            'conversion_value', 'conversion_price', 'dual_low',
                            'remaining_years', 'stock_change_pct']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                return df

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """获取全量转债列表 - 完整字段映射"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            # 第一页
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

            all_data = []
            async with self._session.get(self.CONVERTIBLE_URL, params=params) as response:
                if response.status != 200:
                    return pd.DataFrame()

                data = await response.json()
                if not data or 'result' not in data:
                    return pd.DataFrame()

                result = data['result']
                pages = result.get('pages', 1)
                first_data = result.get('data', [])
                if first_data:
                    all_data.extend(first_data)

                # 多页获取
                for page in range(2, min(pages + 1, 5)):  # 最多5页
                    params['pageNumber'] = page
                    try:
                        async with self._session.get(self.CONVERTIBLE_URL, params=params) as r2:
                            if r2.status == 200:
                                d2 = await r2.json()
                                if d2 and 'result' in d2 and 'data' in d2['result']:
                                    all_data.extend(d2['result']['data'])
                    except Exception:
                        break

            if not all_data:
                return pd.DataFrame()

            df = pd.DataFrame(all_data)
            df = df.rename(columns=self.CB_COLUMN_MAP)

            # 数值转换
            numeric_cols = ['price', 'change_pct', 'premium_ratio', 'conversion_price',
                           'conversion_value', 'stock_price', 'ytm', 'volume_ratio',
                           'turnover_rate', 'outstanding_scale', 'coupon_rate',
                           'dual_low', 'remaining_years', 'convert_ratio']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            return df

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_stock_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取正股实时行情"""
        if not self._connected or not self._session:
            return pd.DataFrame()
        if not codes:
            return pd.DataFrame()

        results = []
        for code in codes[:100]:
            market = '1' if code.startswith('6') else '0'
            params = {
                'secid': f"{market}.{code}",
                'fields': 'f43,f44,f45,f46,f47,f48,f50,f57,f58,f170,f171',
                'fltt': 2,
            }
            try:
                async with self._session.get(self.STOCK_QUOTE_URL, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and 'data' in data and data['data']:
                            d = data['data']
                            results.append({
                                'code': code,
                                'price': d.get('f43', 0),
                                'high': d.get('f44', 0),
                                'low': d.get('f45', 0),
                                'open': d.get('f46', 0),
                                'pre_close': d.get('f47', 0),
                                'change_pct': d.get('f170', 0),
                                'change': d.get('f171', 0),
                                'volume': d.get('f50', 0),
                                'amount': d.get('f48', 0),
                                'pe': d.get('f57', 0),
                                'turnover_rate': d.get('f58', 0),
                            })
            except Exception:
                continue

        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results)

    async def get_financial_indicators(self, codes: List[str]) -> pd.DataFrame:
        """获取财务指标（正股ROE/营收/净利润等）"""
        if not self._connected or not self._session:
            return pd.DataFrame()
        if not codes:
            return pd.DataFrame()

        results = []
        batch_size = 50
        for i in range(0, min(len(codes), 200), batch_size):
            batch = codes[i:i + batch_size]
            params = {
                'sortColumns': 'NOTICE_DATE',
                'sortTypes': -1,
                'pageSize': 50,
                'pageNumber': 1,
                'reportName': 'RPT_LICO_FN_CPD',
                'columns': 'SECUCODE,REPORT_DATE,BASIC_EPS,WEIGHTAVG_ROE,BPS,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,GROSS_PROFIT_RATIO,OPERATE_TAX,LIABILITY_RATIO,CURRENT_RATIO',
                'source': 'WEB',
                'client': 'WEB',
            }
            secucodes = []
            for code in batch:
                market = '.SZ' if code.startswith(('0', '3')) else '.SH'
                secucodes.append(f"{code}{market}")
            if secucodes:
                params['filter'] = f'(SECUCODE="{",".join(secucodes)}")'

            try:
                async with self._session.get(self.FINANCIAL_URL, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and 'result' in data and 'data' in data['result']:
                            for item in data['result']['data']:
                                secucode = item.get('SECUCODE', '')
                                results.append({
                                    'code': secucode.split('.')[0] if '.' in secucode else secucode,
                                    'report_date': item.get('REPORT_DATE'),
                                    'eps': item.get('BASIC_EPS'),
                                    'roe': item.get('WEIGHTAVG_ROE'),
                                    'bps': item.get('BPS'),
                                    'revenue': item.get('TOTAL_OPERATE_INCOME'),
                                    'net_profit': item.get('PARENT_NETPROFIT'),
                                    'gross_profit_ratio': item.get('GROSS_PROFIT_RATIO'),
                                    'debt_ratio': item.get('LIABILITY_RATIO'),
                                    'current_ratio': item.get('CURRENT_RATIO'),
                                })
            except Exception:
                continue

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        numeric_cols = ['eps', 'roe', 'bps', 'revenue', 'net_profit',
                       'gross_profit_ratio', 'debt_ratio', 'current_ratio']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取公告 - 东方财富公告API"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            params = {
                'sr': -1,
                'page_size': 100,
                'page_index': 1,
                'ann_type': 'A',
                'stock_list': ','.join(codes) if codes else '',
                'start_date': (start_date or date.today() - timedelta(days=30)).strftime('%Y-%m-%d'),
                'end_date': (end_date or date.today()).strftime('%Y-%m-%d'),
            }

            all_announcements = []
            max_pages = 5

            for page in range(1, max_pages + 1):
                params['page_index'] = page
                async with self._session.get(self.ANNOUNCEMENT_URL, params=params) as resp:
                    if resp.status != 200:
                        break
                    text = await resp.text()
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        break

                    if not data or 'data' not in data or 'list' not in data['data']:
                        break

                    items = data['data']['list']
                    if not items:
                        break

                    for item in items:
                        title = item.get('title', '') or item.get('ann_title', '')
                        # 关键词过滤
                        if keywords:
                            if not any(kw.lower() in title.lower() for kw in keywords):
                                continue
                        all_announcements.append({
                            'code': item.get('stock_code', item.get('code', '')),
                            'name': item.get('stock_name', item.get('name', '')),
                            'title': title,
                            'publish_time': item.get('date', item.get('notice_date', item.get('publish_time', ''))),
                            'source': 'eastmoney',
                            'content': item.get('content', item.get('abstract', '')),
                        })

                    if len(items) < params['page_size']:
                        break

            if not all_announcements:
                return pd.DataFrame()

            return pd.DataFrame(all_announcements)

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_industry_data(self) -> pd.DataFrame:
        """获取行业板块数据"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            params = {
                'pn': 1,
                'pz': 200,
                'po': 1,
                'np': 1,
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': 2,
                'invt': 2,
                'fid': 'f3',
                'fs': 'm:90+t:2',
                'fields': 'f2,f3,f4,f12,f14,f15,f16,f17,f18,f20,f21',
            }

            async with self._session.get(self.INDUSTRY_URL, params=params) as resp:
                if resp.status != 200:
                    return pd.DataFrame()

                data = await resp.json()
                if not data or 'data' not in data or 'diff' not in data['data']:
                    return pd.DataFrame()

                diff = data['data']['diff']
                if not diff:
                    return pd.DataFrame()

                df = pd.DataFrame(diff)
                df = df.rename(columns={
                    'f12': 'industry_code',
                    'f14': 'industry_name',
                    'f2': 'price',
                    'f3': 'change_pct',
                    'f4': 'change',
                    'f15': 'high',
                    'f16': 'low',
                    'f17': 'open',
                    'f20': 'total_market_cap',
                    'f21': 'circ_market_cap',
                })
                return df

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_macro_data(self) -> pd.DataFrame:
        """获取宏观数据 - 通过东方财富宏观API"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            # 获取宏观经济指标
            results = []
            urls = [
                ("CPI", "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_ECON_MACRO&columns=ALL&filter=(INDICATOR_ID=\"EMI000000000001\")&pageSize=10&pageNumber=1&sortTypes=-1&sortColumns=REPORT_DATE"),
                ("PMI", "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_ECON_MACRO&columns=ALL&filter=(INDICATOR_ID=\"EMI000000000013\")&pageSize=10&pageNumber=1&sortTypes=-1&sortColumns=REPORT_DATE"),
                ("GDP", "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_ECON_MACRO&columns=ALL&filter=(INDICATOR_ID=\"EMI000000000004\")&pageSize=10&pageNumber=1&sortTypes=-1&sortColumns=REPORT_DATE"),
                ("M2", "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_ECON_MACRO_GJ&columns=ALL&filter=(INDICATOR_ID=\"EMI000000000041\")&pageSize=10&pageNumber=1&sortTypes=-1&sortColumns=REPORT_DATE"),
            ]

            for name, url in urls:
                try:
                    async with self._session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data and 'result' in data and 'data' in data['result']:
                                for item in data['result']['data'][:3]:
                                    results.append({
                                        'indicator': name,
                                        'value': item.get('VALUE', item.get('DATA_VALUE', 0)),
                                        'report_date': item.get('REPORT_DATE', item.get('REPORT_DATE', '')),
                                    })
                except Exception:
                    continue

            if not results:
                return pd.DataFrame()

            return pd.DataFrame(results)

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()
