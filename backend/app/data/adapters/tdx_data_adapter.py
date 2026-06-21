"""
通达信 (TDX) 数据适配器

基于 pytdx 的低延迟数据源，作为东方财富数据源的补充。
支持所有数据类型：QUOTE, CONVERTIBLE, STOCK, FINANCIAL, INDUSTRY, MACRO
"""

from datetime import date, datetime
from typing import Optional, List, Dict, Any
import pandas as pd
import asyncio
import logging

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

logger = logging.getLogger(__name__)

# ── 简单行业分类规则 ──

# 根据股票代码前缀推断行业（TDX 无原生行业分类）
CODE_INDUSTRY_RULES: Dict[str, str] = {
    "6": "主板",
    "0": "主板",
    "3": "创业板",
    "4": "科创板",
    "8": "科创板",
    "9": "主板",
    "2": "中小企业板",
}

# 根据转债名称关键词映射行业
BOND_INDUSTRY_KEYWORDS: Dict[str, str] = {
    "银行": "银行",
    "证券": "非银金融",
    "保险": "非银金融",
    "地产": "房地产",
    "医药": "医药生物",
    "医疗": "医药生物",
    "科技": "科技",
    "信息": "信息技术",
    "软件": "信息技术",
    "电子": "电子",
    "半导体": "电子",
    "芯片": "电子",
    "汽车": "汽车",
    "新能源": "电力设备",
    "光伏": "电力设备",
    "风电": "电力设备",
    "电池": "电力设备",
    "化工": "基础化工",
    "材料": "基础化工",
    "钢铁": "钢铁",
    "有色": "有色金属",
    "煤炭": "煤炭",
    "电力": "公用事业",
    "能源": "公用事业",
    "环保": "环保",
    "建筑": "建筑装饰",
    "建材": "建筑材料",
    "机械": "机械设备",
    "装备": "机械设备",
    "军工": "国防军工",
    "航天": "国防军工",
    "通信": "通信",
    "传媒": "传媒",
    "食品": "食品饮料",
    "饮料": "食品饮料",
    "白酒": "食品饮料",
    "农业": "农林牧渔",
    "养殖": "农林牧渔",
    "纺织": "纺织服饰",
    "服装": "纺织服饰",
    "家电": "家用电器",
    "轻工": "轻工制造",
    "交运": "交通运输",
    "物流": "交通运输",
    "商贸": "商贸零售",
    "零售": "商贸零售",
    "社服": "社会服务",
    "旅游": "社会服务",
    "建材": "建筑材料",
    "房地产": "房地产",
    "公用": "公用事业",
    "计算机": "计算机",
    "军工": "国防军工",
    "电气": "电力设备",
    "采掘": "石油石化",
    "石化": "石油石化",
    "石油": "石油石化",
}


def _infer_industry_from_name(name: str) -> str:
    """根据名称关键词推断行业"""
    if not name:
        return "未知"
    for keyword, industry in BOND_INDUSTRY_KEYWORDS.items():
        if keyword in name:
            return industry
    return "其他"


def _code_to_market_label(code: str) -> str:
    """根据代码前缀推断板块"""
    if not code:
        return "未知"
    for prefix, label in CODE_INDUSTRY_RULES.items():
        if code.startswith(prefix):
            return label
    return "其他"


class TdxDataAdapter(DataSourceAdapter):
    """通达信数据适配器 - 基于 pytdx 的低延迟行情与数据"""

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        self._adapter: Any = None  # TdxAdapter instance (lazy)

    async def connect(self) -> bool:
        """建立 TDX 连接"""
        try:
            from app.adapters.tdx_adapter import get_tdx_adapter

            adapter = get_tdx_adapter()
            # 在 executor 中执行同步的 _ensure_connected
            ok = await asyncio.to_thread(adapter._ensure_connected)
            if ok:
                self._adapter = adapter
                self._connected = True
                logger.info("[TDX] Connected successfully")
                return True
            else:
                self._last_error = "Failed to connect to any TDX server"
                return False
        except Exception as e:
            self._handle_error(e)
            return False

    async def disconnect(self) -> None:
        """断开 TDX 连接"""
        if self._adapter is not None:
            await asyncio.to_thread(self._adapter.disconnect)
        self._adapter = None
        self._connected = False
        logger.info("[TDX] Disconnected")

    async def query(self, query: DataQuery) -> pd.DataFrame:
        """执行查询 - 按数据类型路由"""
        if not self._connected or self._adapter is None:
            logger.warning("[TDX] Not connected, returning empty")
            return pd.DataFrame()

        try:
            if query.data_type == DataType.QUOTE:
                return await self.get_realtime_quotes(query.codes or [])
            elif query.data_type == DataType.CONVERTIBLE:
                return await self.get_convertible_bonds(query.end_date)
            elif query.data_type == DataType.STOCK:
                return await self._query_stock_list(query)
            elif query.data_type == DataType.FINANCIAL:
                return await self._query_financial(query.codes or [])
            elif query.data_type == DataType.ANNOUNCEMENT:
                return await self.get_announcements(
                    codes=query.codes,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    keywords=query.filters.get("keywords"),
                )
            elif query.data_type == DataType.INDUSTRY:
                return await self.get_industry_data()
            elif query.data_type == DataType.MACRO:
                return await self.get_macro_data()
            else:
                logger.warning(f"[TDX] Unsupported DataType: {query.data_type}")
                return pd.DataFrame()
        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def _query_stock_list(self, query: DataQuery) -> pd.DataFrame:
        """查询股票列表"""
        if self._adapter is None:
            return pd.DataFrame()

        # 收集指定市场的证券
        markets = query.filters.get("markets", [0, 1])  # 默认深市+沪市
        rows = []
        for market in markets:
            securities = await asyncio.to_thread(
                self._adapter.fetch_security_list, market, 0, 2000
            )
            for s in securities:
                code = s.get("code", "")
                name = s.get("name", "")
                # 可选代码过滤
                if query.codes and code not in query.codes:
                    continue
                rows.append({
                    "code": code,
                    "name": name,
                    "market": market,
                    "pre_close": s.get("pre_close"),
                })

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    async def _query_financial(self, codes: List[str]) -> pd.DataFrame:
        """查询财务数据"""
        if not codes or self._adapter is None:
            return pd.DataFrame()

        result = await asyncio.to_thread(
            self._adapter.fetch_finance_batch, codes
        )
        if not result:
            return pd.DataFrame()

        rows = []
        for code, data in result.items():
            row = {"code": code}
            row.update(data)
            rows.append(row)

        return pd.DataFrame(rows) if rows else pd.DataFrame()

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """获取实时行情

        通过 TDX 获取批量实时行情，返回统一格式的 DataFrame。
        """
        if not codes or self._adapter is None:
            return pd.DataFrame()

        raw = await asyncio.to_thread(self._adapter.fetch_quotes, codes)
        if not raw:
            return pd.DataFrame()

        rows = []
        for code, data in raw.items():
            rows.append({
                "code": code,
                "name": data.get("name", ""),
                "price": data.get("price"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "pre_close": data.get("last_close"),
                "change_pct": data.get("change_pct"),
                "change": data.get("change"),
                "volume": data.get("vol"),
                "amount": data.get("amount"),
                "source": "tdx",
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df.set_index("code", inplace=True)
        return df

    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """获取可转债列表

        通过证券名称搜索包含"转债"的品种。TDX 通过证券列表扫描匹配。
        """
        if self._adapter is None:
            return pd.DataFrame()

        securities = await asyncio.to_thread(
            self._adapter.fetch_securities_by_name, "转债"
        )
        if not securities:
            return pd.DataFrame()

        codes = [s["code"] for s in securities if s.get("code")]
        name_map = {s["code"]: s.get("name", "") for s in securities if s.get("code")}

        # 获取转债行情
        quotes = {}
        if codes:
            quotes = await asyncio.to_thread(self._adapter.fetch_quotes, codes)

        rows = []
        for code in codes:
            bond_name = name_map.get(code, "")
            q = quotes.get(code, {})
            rows.append({
                "code": code,
                "name": bond_name,
                "price": q.get("price"),
                "change_pct": q.get("change_pct"),
                "change": q.get("change"),
                "volume": q.get("vol"),
                "amount": q.get("amount"),
                "open": q.get("open"),
                "high": q.get("high"),
                "low": q.get("low"),
                "pre_close": q.get("last_close"),
                "source": "tdx",
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df.set_index("code", inplace=True)
        return df

    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取公告（简化实现）

        TDX 不直接提供公告 API，此实现利用证券列表返回名称匹配结果，
        作为公告数据的简化替代。
        """
        if self._adapter is None:
            return pd.DataFrame()

        # 如果指定了代码范围，优先使用
        if codes:
            target_codes = codes
        else:
            # 获取全量证券列表作为候选
            all_sec = await asyncio.to_thread(self._adapter.fetch_all_securities)
            target_codes = list(all_sec.keys())

        # 获取行情作为"公告"内容的简化替代
        quotes = await asyncio.to_thread(self._adapter.fetch_quotes, target_codes)
        if not quotes:
            return pd.DataFrame()

        rows = []
        for code, data in quotes.items():
            name = data.get("name", "")
            # 关键词过滤
            if keywords:
                name_lower = name.lower()
                if not any(kw.lower() in name_lower for kw in keywords):
                    continue
            rows.append({
                "code": code,
                "name": name,
                "title": f"[{name}] 行情数据",
                "publish_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "tdx",
                "content": f"价格={data.get('price')}, "
                           f"涨跌幅={data.get('change_pct')}%, "
                           f"成交量={data.get('vol')}, "
                           f"成交额={data.get('amount')}",
            })

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    async def get_industry_data(self) -> pd.DataFrame:
        """获取行业分类数据

        基于证券名称关键词进行行业映射。TDX 原生不提供行业分类，
        此实现为简化版行业聚类。
        """
        if self._adapter is None:
            return pd.DataFrame()

        # 从多个市场获取全部证券
        rows = []
        for market in [0, 1, 2]:
            securities = await asyncio.to_thread(
                self._adapter.fetch_security_list, market, 0, 2000
            )
            for s in securities:
                code = s.get("code", "")
                name = s.get("name", "")
                if not code or not name:
                    continue
                industry = _infer_industry_from_name(name)
                market_label = _code_to_market_label(code)
                rows.append({
                    "code": code,
                    "name": name,
                    "industry": industry,
                    "market": market_label,
                    "pre_close": s.get("pre_close"),
                })

        if not rows:
            logger.warning("[TDX] No industry data available")
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # 按行业聚合统计
        summary = (
            df.groupby("industry")
            .agg(
                count=("code", "count"),
                codes=("code", lambda x: ",".join(x.head(10))),
            )
            .reset_index()
        )
        summary["source"] = "tdx"
        logger.info(
            f"[TDX] Industry data: {len(summary)} industries, "
            f"{len(df)} securities"
        )
        return summary

    async def get_macro_data(self) -> pd.DataFrame:
        """获取宏观数据（占位实现）

        TDX 不提供宏观经济数据，返回空的 DataFrame 并记录日志。
        """
        logger.info("[TDX] Macro data not available from TDX source")
        return pd.DataFrame(
            [{"indicator": "N/A", "message": "TDX does not provide macro data", "source": "tdx"}]
        )
