"""
资金流向 API 端点

提供个股资金流向、行业资金流向、主力资金流向、换手率排名等数据
数据来源：AKShare (东方财富)

可用接口:
  - stock_fund_flow_individual: 个股资金流向（5190只，8-10秒）
  - stock_fund_flow_industry: 行业资金流向（90行业，1秒）
  - stock_hsgt_fund_flow_summary_em: 沪深港通资金流向
  - stock_individual_fund_flow_rank: 个股资金流向排名（含超大单/大单/中单/小单拆分，常被IP封禁）

优化:
  1. 共享 stock_fund_flow_individual 调用 — individual/main/turnover_rank 三端点共用一次数据
  2. 优先尝试 stock_individual_fund_flow_rank 获取真实拆分，失败则降级估算
  3. 沪深港通非交易时段显示交易状态
  4. 请求级去重 + 交易时段感知 TTL
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import logging
import time
from datetime import datetime

router = APIRouter(prefix="/fund_flow", tags=["fund_flow"])
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Smart Cache — 交易时段感知 TTL + 请求级去重
# ═══════════════════════════════════════════════════════════════════════════════

def _is_trading_hours() -> bool:
    """判断当前是否在 A 股交易时段 (9:15-15:05 工作日)"""
    now = datetime.now()
    # 周末
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1505


def _cache_ttl() -> int:
    """交易时段 30s 缓存，非交易时段 5 分钟"""
    return 30 if _is_trading_hours() else 300


_cache: dict = {}
# 请求级去重：防止并发请求重复调用 AKShare
_pending: dict = {}


def _get_cached(key: str):
    ttl = _cache_ttl()
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _set_cached(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


async def _get_individual_df():
    """
    共享 stock_fund_flow_individual 调用
    多个端点共用同一次 API 调用结果，8-10秒耗时只发生一次
    """
    # 检查缓存
    cached = _get_cached("individual_df")
    if cached is not None:
        return cached

    # 请求级去重：如果已有进行中的请求，等待它
    if "individual_df" in _pending:
        return await _pending["individual_df"]

    # 发起请求
    async def _fetch():
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_fund_flow_individual)
        _set_cached("individual_df", df)
        return df

    fut = asyncio.ensure_future(_fetch())
    _pending["individual_df"] = fut
    try:
        result = await fut
        return result
    finally:
        _pending.pop("individual_df", None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Response Models
# ═══════════════════════════════════════════════════════════════════════════════

class IndividualFundFlow(BaseModel):
    """个股资金流向"""
    code: str
    name: str
    price: float
    change_pct: float
    turnover_rate: float
    inflow: float
    outflow: float
    net_inflow: float
    amount: float


class IndustryFundFlow(BaseModel):
    """行业资金流向"""
    rank: int
    industry: str
    industry_index: float
    change_pct: float
    inflow: float
    outflow: float
    net_inflow: float
    company_count: int
    leading_stock: str
    leading_change: float
    current_price: float


class MainFundFlow(BaseModel):
    """主力资金流向"""
    code: str
    name: str
    price: float
    change_pct: float
    turnover_rate: float
    main_net_inflow: float
    super_large_net: float
    large_net: float
    medium_net: float
    small_net: float
    inflow: float
    outflow: float
    amount: float
    is_estimated: bool = True  # True=按比例估算, False=真实数据


class TurnoverRank(BaseModel):
    """换手率排名"""
    code: str
    name: str
    price: float
    change_pct: float
    turnover_rate: float
    amount: float


class HsgtFundFlow(BaseModel):
    """沪深港通资金流向"""
    date: str
    type: str
    plate: str
    direction: str
    status: int  # 0=未开盘, 1=交易中, 2=午休, 3=已收盘
    status_text: str = ""  # 交易状态中文描述
    net_buy: Optional[float] = None
    net_inflow: Optional[float] = None
    balance: Optional[float] = None
    up_count: Optional[int] = None
    hold_count: Optional[int] = None
    down_count: Optional[int] = None
    index_name: str = ""
    index_change: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  API Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/individual", response_model=List[IndividualFundFlow])
async def get_individual_fund_flow(
    limit: int = Query(100, ge=1, le=500, description="返回条数限制"),
):
    """
    个股资金流向排名

    数据源：AKShare stock_fund_flow_individual (东方财富)
    覆盖：约5200只A股
    耗时：8-10秒（首次），后续走缓存
    """
    cached = _get_cached("individual")
    if cached:
        return cached[:limit]

    try:
        df = await _get_individual_df()
        if df.empty:
            return []

        df = _normalize_individual_df(df)
        df = df.sort_values("net_inflow", ascending=False)

        result = [IndividualFundFlow(**row.to_dict()) for _, row in df.iterrows()]
        _set_cached("individual", result)
        return result[:limit]

    except Exception as e:
        logger.error(f"Failed to get individual fund flow via AKShare: {e}")
        # Fallback: 使用 data_enrich 缓存（macOS Electron 中 PyMiniRacer 会导致 AKShare 失败）
        try:
            from app.engine import data_enrich as _de
            result = []
            for code, spot in _de._spot_map.items():
                if code.startswith("_"):
                    continue
                name = _de._name_map.get(code, "")
                if not name:
                    continue
                price = spot.get("price", 0) or 0
                change_pct = spot.get("change_pct", 0) or 0
                turnover_rate = spot.get("turnover_rate", 0) or 0
                amount = spot.get("amount", 0) or 0
                ff = _de._fund_flow_map.get(code, {})
                net_main = ff.get("net_main", 0) or 0
                inflow = (amount + net_main) / 2
                outflow = (amount - net_main) / 2
                result.append(IndividualFundFlow(
                    code=code,
                    name=name,
                    price=price,
                    change_pct=change_pct,
                    turnover_rate=turnover_rate,
                    inflow=inflow,
                    outflow=outflow,
                    net_inflow=net_main,
                    amount=amount,
                ))
            result.sort(key=lambda x: x.net_inflow, reverse=True)
            _set_cached("individual", result)
            return result[:limit]
        except Exception as e2:
            logger.error(f"Failed to get individual fund flow from cache: {e2}")
            return []


@router.get("/industry", response_model=List[IndustryFundFlow])
async def get_industry_fund_flow(
    indicator: str = Query("今日", description="时间指标: 今日, 3日, 5日, 10日"),
):
    """
    行业资金流向

    数据源：AKShare stock_fund_flow_industry (东方财富)
    覆盖：90个申万行业
    耗时：<1秒
    """
    cached = _get_cached(f"industry_{indicator}")
    if cached:
        return cached

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_fund_flow_industry)
        if df.empty:
            return []

        col_map = {
            "序号": "rank", "行业": "industry", "行业指数": "industry_index",
            "行业-涨跌幅": "change_pct", "流入资金": "inflow",
            "流出资金": "outflow", "净额": "net_inflow",
            "公司家数": "company_count", "领涨股": "leading_stock",
            "领涨股-涨跌幅": "leading_change", "当前价": "current_price",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        for col in ["inflow", "outflow", "net_inflow"]:
            if col in df.columns:
                df[col] = df[col].apply(_parse_amount)
        for col in ["change_pct", "leading_change", "current_price", "industry_index"]:
            if col in df.columns:
                df[col] = df[col].fillna(0)

        result = [IndustryFundFlow(**row.to_dict()) for _, row in df.iterrows()]
        _set_cached(f"industry_{indicator}", result)
        return result

    except Exception as e:
        logger.error(f"Failed to get industry fund flow: {e}")
        return []


@router.get("/main", response_model=List[MainFundFlow])
async def get_main_fund_flow(
    limit: int = Query(100, ge=1, le=500, description="返回条数限制"),
):
    """
    主力资金流向（超大单/大单/中单/小单拆分）

    优先尝试 stock_individual_fund_flow_rank 获取真实拆分数据。
    如被封禁则降级为 stock_fund_flow_individual + 标准比例估算。
    """
    cached = _get_cached("main")
    if cached:
        return cached[:limit]

    # 1) 尝试真实拆分数据
    real_data = await _try_real_fund_flow_rank(limit)
    if real_data is not None:
        _set_cached("main", real_data)
        return real_data[:limit]

    # 2) 降级：共享个股数据 + 估算
    try:
        df = await _get_individual_df()
        if df.empty:
            return []

        df = _normalize_individual_df(df)

        # 按标准 A 股资金分类比例估算
        # 主力净流入 = 超大单 + 大单，约占净流入 65%
        df["main_net_inflow"] = df["net_inflow"] * 0.65
        df["super_large_net"] = df["net_inflow"] * 0.35
        df["large_net"] = df["net_inflow"] * 0.30
        df["medium_net"] = df["net_inflow"] * 0.20
        df["small_net"] = df["net_inflow"] * 0.15
        df["is_estimated"] = True

        df["abs_main"] = df["main_net_inflow"].abs()
        df = df.sort_values("abs_main", ascending=False)
        df = df.drop(columns=["abs_main"])

        result = [MainFundFlow(**row.to_dict()) for _, row in df.iterrows()]
        _set_cached("main", result)
        return result[:limit]

    except Exception as e:
        logger.error(f"Failed to get main fund flow via AKShare: {e}")
        # Fallback: 使用 data_enrich 缓存（macOS Electron 中 PyMiniRacer 会导致 AKShare 失败）
        try:
            from app.engine import data_enrich as _de
            result = []
            for code, ff in _de._fund_flow_map.items():
                if code.startswith("_"):
                    continue
                spot = _de._spot_map.get(code, {})
                name = _de._name_map.get(code, "")
                if not name:
                    continue
                price = spot.get("price", 0) or 0
                change_pct = spot.get("change_pct", 0) or 0
                turnover_rate = spot.get("turnover_rate", 0) or 0
                amount = spot.get("amount", 0) or 0
                net_main = ff.get("net_main", 0) or 0
                inflow = (amount + net_main) / 2
                outflow = (amount - net_main) / 2
                result.append(MainFundFlow(
                    code=code,
                    name=name,
                    price=price,
                    change_pct=change_pct,
                    turnover_rate=turnover_rate,
                    main_net_inflow=net_main,
                    super_large_net=ff.get("net_super", 0) or 0,
                    large_net=ff.get("net_big", 0) or 0,
                    medium_net=net_main * 0.3,
                    small_net=net_main * 0.15,
                    inflow=inflow,
                    outflow=outflow,
                    amount=amount,
                    is_estimated=True,
                ))
            result.sort(key=lambda x: abs(x.main_net_inflow), reverse=True)
            _set_cached("main", result)
            return result[:limit]
        except Exception as e2:
            logger.error(f"Failed to get main fund flow from cache: {e2}")
            return []


@router.get("/turnover_rank", response_model=List[TurnoverRank])
async def get_turnover_rank(
    limit: int = Query(100, ge=1, le=500, description="返回条数限制"),
):
    """
    换手率排名

    数据源：复用 stock_fund_flow_individual（共享调用，零额外耗时）
    """
    cached = _get_cached("turnover")
    if cached:
        return cached[:limit]

    try:
        df = await _get_individual_df()
        if df.empty:
            return []

        df = _normalize_individual_df(df)
        df = df.sort_values("turnover_rate", ascending=False)

        result = [TurnoverRank(**row.to_dict()) for _, row in df.iterrows()]
        _set_cached("turnover", result)
        return result[:limit]

    except Exception as e:
        logger.error(f"Failed to get turnover rank via AKShare: {e}")
        # Fallback: 使用 data_enrich 缓存（macOS Electron 中 PyMiniRacer 会导致 AKShare 失败）
        try:
            from app.engine import data_enrich as _de
            result = []
            for code, spot in _de._spot_map.items():
                if code.startswith("_"):
                    continue
                name = _de._name_map.get(code, "")
                if not name:
                    continue
                result.append(TurnoverRank(
                    code=code,
                    name=name,
                    price=spot.get("price", 0) or 0,
                    change_pct=spot.get("change_pct", 0) or 0,
                    turnover_rate=spot.get("turnover_rate", 0) or 0,
                    amount=spot.get("amount", 0) or 0,
                ))
            result.sort(key=lambda x: x.turnover_rate, reverse=True)
            _set_cached("turnover", result)
            return result[:limit]
        except Exception as e2:
            logger.error(f"Failed to get turnover rank from cache: {e2}")
            return []


@router.get("/hsgt", response_model=List[HsgtFundFlow])
async def get_hsgt_fund_flow():
    """
    沪深港通资金流向

    数据源：AKShare stock_hsgt_fund_flow_summary_em (东方财富)
    非交易时段：status_text 标注状态，数值字段返回 None 而非 0
    """
    cached = _get_cached("hsgt")
    if cached:
        return cached

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_hsgt_fund_flow_summary_em)
        if df.empty:
            return []

        col_map = {
            "交易日": "date", "类型": "type", "板块": "plate",
            "资金方向": "direction", "交易状态": "status",
            "成交净买额": "net_buy", "资金净流入": "net_inflow",
            "当日资金余额": "balance", "上涨数": "up_count",
            "持平数": "hold_count", "下跌数": "down_count",
            "相关指数": "index_name", "指数涨跌幅": "index_change",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # 交易状态映射
        status_map = {0: "未开盘", 1: "交易中", 2: "午休", 3: "已收盘"}
        is_closed = False

        result = []
        for _, row in df.iterrows():
            status = int(row.get("status", 0))
            status_text = status_map.get(status, "未知")
            if status in (0, 3):
                is_closed = True

            r = row.to_dict()

            # 非交易时段：零值字段改为 None，避免误导
            if status in (0, 3):
                for col in ["net_buy", "net_inflow", "balance"]:
                    val = r.get(col)
                    if val is not None and (isinstance(val, (int, float)) and val == 0):
                        r[col] = None
                for col in ["up_count", "hold_count", "down_count"]:
                    val = r.get(col)
                    if val is not None and (isinstance(val, (int, float)) and val == 0):
                        r[col] = None

            r["status_text"] = status_text
            result.append(HsgtFundFlow(**r))

        _set_cached("hsgt", result)
        return result

    except Exception as e:
        logger.error(f"Failed to get HSGT fund flow: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
#  Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_individual_df(df):
    """标准化 stock_fund_flow_individual 的 DataFrame"""
    col_map = {
        "股票代码": "code", "股票简称": "name", "最新价": "price",
        "涨跌幅": "change_pct", "换手率": "turnover_rate",
        "流入资金": "inflow", "流出资金": "outflow",
        "净额": "net_inflow", "成交额": "amount",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 解析百分比字符串
    for col in ["change_pct", "turnover_rate"]:
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].astype(str).str.replace("%", "", regex=False)
            df[col] = df[col].apply(_safe_float)

    # 解析金额
    for col in ["inflow", "outflow", "net_inflow", "amount"]:
        if col in df.columns:
            df[col] = df[col].apply(_parse_amount)

    # 填充缺失值
    for col in ["price", "change_pct", "turnover_rate", "inflow", "outflow", "net_inflow", "amount"]:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    return df


async def _try_real_fund_flow_rank(limit: int):
    """
    尝试获取 stock_individual_fund_flow_rank 真实拆分数据
    返回 None 表示接口不可用（IP 封禁等）
    """
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_individual_fund_flow_rank, indicator="今日")
        if df.empty:
            return None

        # 东方财富返回的列名
        rename_map = {
            "代码": "code", "名称": "name", "最新价": "price",
            "涨跌幅": "change_pct", "换手率": "turnover_rate",
            "主力净流入-净额": "main_net_inflow",
            "超大单净流入-净额": "super_large_net",
            "大单净流入-净额": "large_net",
            "中单净流入-净额": "medium_net",
            "小单净流入-净额": "small_net",
            "主力净流入-净占比": "main_pct",
            "超大单净流入-净占比": "super_large_pct",
            "大单净流入-净占比": "large_pct",
            "中单净流入-净占比": "medium_pct",
            "小单净流入-净占比": "small_pct",
            "今日涨跌幅": "change_pct",
            "今日换手率": "turnover_rate",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        # 确保必需字段存在
        for col in ["main_net_inflow", "super_large_net", "large_net", "medium_net", "small_net"]:
            if col not in df.columns:
                return None  # 列名不匹配，降级

        # 删除不需要的列
        drop_cols = [c for c in df.columns if c.endswith("_pct") or c not in {
            "code", "name", "price", "change_pct", "turnover_rate",
            "main_net_inflow", "super_large_net", "large_net", "medium_net", "small_net",
            "inflow", "outflow", "amount",
        }]
        df = df.drop(columns=drop_cols, errors="ignore")

        # 补充缺失字段
        for col in ["inflow", "outflow", "amount", "price", "change_pct", "turnover_rate"]:
            if col not in df.columns:
                df[col] = 0.0

        df["is_estimated"] = False

        # 解析百分比
        for col in ["change_pct", "turnover_rate"]:
            if col in df.columns and df[col].dtype == object:
                df[col] = df[col].astype(str).str.replace("%", "", regex=False)
                df[col] = df[col].apply(_safe_float)

        # 按主力净流入排序
        df = df.sort_values("main_net_inflow", ascending=False)

        result = [MainFundFlow(**row.to_dict()) for _, row in df.iterrows()]
        logger.info(f"Got real fund flow rank: {len(result)} stocks")
        return result[:limit]

    except Exception as e:
        logger.warning(f"stock_individual_fund_flow_rank unavailable (falling back to estimation): {e}")
        return None


def _parse_amount(value) -> float:
    """解析金额字符串（如 '5.24亿' -> 5.24, '5676.70万' -> 0.567670）"""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return 0.0
    value = value.strip()
    if value.endswith("亿"):
        return _safe_float(value[:-1])
    elif value.endswith("万"):
        return _safe_float(value[:-1]) / 10000
    return _safe_float(value)


def _safe_float(value) -> float:
    """安全转换为 float"""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0
