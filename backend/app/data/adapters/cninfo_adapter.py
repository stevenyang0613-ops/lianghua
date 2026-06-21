"""
巨潮资讯适配器

通过HTTP API获取公告数据
"""
import json
from datetime import date, datetime, timedelta
from typing import Optional, List
import pandas as pd
import asyncio
import aiohttp
import re
import logging

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

logger = logging.getLogger(__name__)


class CNInfoAdapter(DataSourceAdapter):
    """巨潮资讯适配器 - 公告数据源"""

    BASE_URL = "https://www.cninfo.com.cn/new"
    DISCLOSURE_URL = "https://www.cninfo.com.cn/new/disclosure"

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
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                    'Origin': 'http://www.cninfo.com.cn',
                    'Referer': 'http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice',
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
        """获取公告 - 巨潮资讯"""
        if not self._connected or not self._session:
            return pd.DataFrame()

        try:
            end = end_date or date.today()
            start = start_date or (end - timedelta(days=30))

            # 公告类型: 全部
            all_results = []
            params_template = {
                'pageNum': 1,
                'pageSize': 100,
                'column': 'szse_latest',
                'tabName': 'fulltext',
                'plate': 'sz',
                'stock': ','.join(codes) if codes else '',
                'searchkey': '',
                'secid': '',
                'category': '',
                'trade': '',
                'seDate': f"{start.strftime('%Y-%m-%d')}~{end.strftime('%Y-%m-%d')}",
                'sortName': '',
                'sortType': '',
                'isHLtitle': 'true',
            }

            # 搜索深交所
            params_template['plate'] = 'sz'
            results_sz = await self._fetch_announcement_page(params_template)
            all_results.extend(results_sz)

            # 搜索上交所
            params_template['plate'] = 'sh'
            results_sh = await self._fetch_announcement_page(params_template)
            all_results.extend(results_sh)

            # 搜索北交所
            params_template['plate'] = 'bj'
            results_bj = await self._fetch_announcement_page(params_template)
            all_results.extend(results_bj)

            if not all_results:
                return pd.DataFrame()

            df = pd.DataFrame(all_results)

            # 关键词过滤
            if keywords:
                mask = df['title'].str.contains('|'.join(keywords), na=False, case=False)
                df = df[mask]

            # 标准化列名
            df = df.rename(columns={
                'code': 'code',
                'name': 'name',
                'title': 'title',
                'publish_time': 'publish_time',
                'source': 'source',
            })

            return df

        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def _fetch_announcement_page(self, params: dict) -> List[dict]:
        """获取单页公告"""
        if not self._session:
            return []

        results = []
        url = f"{self.BASE_URL}/fulltextSearch/notice"

        for page in range(1, 6):  # 最多5页
            params['pageNum'] = page
            try:
                async with self._session.get(url, params=params) as response:
                    if response.status != 200:
                        break

                    try:
                        data = await response.json()
                    except (json.JSONDecodeError, aiohttp.ContentTypeError):
                        break

                    if not data:
                        break

                    announcements = data.get('announcements', [])
                    if not announcements:
                        break

                    for item in announcements:
                        adjunct_url = item.get('adjunctUrl', '')
                        results.append({
                            'code': item.get('secCode', ''),
                            'name': item.get('secName', ''),
                            'title': item.get('announcementTitle', ''),
                            'publish_time': item.get('announcementTime', ''),
                            'source': 'cninfo',
                            'content_url': f"{self.BASE_URL}/{adjunct_url}" if adjunct_url else '',
                            'category': item.get('categoryName', ''),
                        })

                    if len(announcements) < params['pageSize']:
                        break

            except Exception as e:
                logger.warning(f"[CNInfo] Page fetch error: {e}")
                break

        return results

    async def get_convertible_announcements(
        self,
        keywords: List[str] = None,
        days: int = 7,
    ) -> pd.DataFrame:
        """获取转债相关公告"""
        default_keywords = [
            '转股价', '下修', '强赎', '赎回', '回售',
            '转股', '利息', '评级', '可转债',
        ]
        keywords = keywords or default_keywords
        start_date = date.today() - timedelta(days=days)

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
                text = re.sub(r'<[^>]+>', '', html)
                text = re.sub(r'\s+', ' ', text)
                return text[:5000]

        except Exception as e:
            logger.warning(f"[CNInfo] Parse error: {e}")
            return ""
