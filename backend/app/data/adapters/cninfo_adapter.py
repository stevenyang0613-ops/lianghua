"""
巨潮资讯适配器

通过HTTP API获取公告数据
"""

from datetime import date, datetime
from typing import Optional, List
import pandas as pd
import asyncio
import aiohttp
import re
import logging

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

logger = logging.getLogger(__name__)


class CNInfoAdapter(DataSourceAdapter):
    """巨潮资讯适配器"""

    BASE_URL = "http://www.cninfo.com.cn/new"

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
                    'Accept': 'application/json, text/plain, */*',
                }
            )
            self._connected = True
            logger.info("[CNInfo] Connected successfully")
            return True

        except Exception as e:
            self._handle_error(e)
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        if self._session:
            await self._session.close()
        self._connected = False
        logger.info("[CNInfo] Disconnected")

    async def query(self, query: DataQuery) -> pd.DataFrame:
        """执行查询"""
        if not self._connected:
            return pd.DataFrame()

        if query.data_type == DataType.ANNOUNCEMENT:
            return await self.get_announcements(
                codes=query.codes,
                start_date=query.start_date,
                end_date=query.end_date,
                keywords=query.filters.get('keywords')
            )

        return pd.DataFrame()

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """巨潮不提供实时行情"""
        return pd.DataFrame()

    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """巨潮不提供转债列表"""
        return pd.DataFrame()

    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取公告"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            # 构建查询参数
            params = {
                'pageNum': 1,
                'pageSize': 100,
                'column': 'szse',  # 深交所
                'tabName': 'fulltext',
                'plate': '',
                'stock': ','.join(codes) if codes else '',
                'seDate': f"{start_date or '2023-01-01'}~{end_date or datetime.now().strftime('%Y-%m-%d')}",
                'searchkey': '|'.join(keywords) if keywords else '',
                'category': '',
                'isHLtitle': 'true',
            }

            url = f"{self.BASE_URL}/fulltextSearch"

            all_results = []
            max_pages = 10

            for page in range(1, max_pages + 1):
                params['pageNum'] = page

                async with self._session.get(url, params=params) as response:
                    if response.status != 200:
                        break

                    data = await response.json()

                    if not data or 'announcements' not in data:
                        break

                    announcements = data.get('announcements', [])
                    if not announcements:
                        break

                    all_results.extend(announcements)

                    if len(announcements) < params['pageSize']:
                        break

            if not all_results:
                return pd.DataFrame()

            # 解析结果
            df = pd.DataFrame(all_results)

            if 'adjunctUrl' in df.columns:
                df['content_url'] = 'http://www.cninfo.com.cn/' + df['adjunctUrl']

            return df

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_convertible_announcements(
        self,
        keywords: List[str] = None,
        days: int = 7,
    ) -> pd.DataFrame:
        """获取转债相关公告"""
        default_keywords = [
            '转股价', '下修', '强赎', '赎回', '回售',
            '转股', '利息', '评级',
        ]

        keywords = keywords or default_keywords

        start_date = date.today() - pd.Timedelta(days=days)

        return await self.get_announcements(
            start_date=start_date,
            keywords=keywords,
        )

    async def parse_announcement_content(self, url: str) -> str:
        """解析公告内容"""
        if not self._session:
            return ""

        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    return ""

                html = await response.text()

                # 简单提取正文内容
                # 实际实现需要更复杂的HTML解析
                text = re.sub(r'<[^>]+>', '', html)
                text = re.sub(r'\s+', ' ', text)

                return text[:5000]  # 限制长度

        except Exception as e:
            logger.warning(f"[CNInfo] Parse error: {e}")
            return ""
