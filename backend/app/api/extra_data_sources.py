"""
补全数据源 — 璇玑v8策略回测所需的额外数据

核心问题: bond_value/纯债溢价率/转股价值 在历史回测中长期为 0%
解决方案: 通过 akshare.bond_zh_cov_value_analysis 从东方财富数据中心获取每只转债的
         300-1500 天的纯债价值、转股价值、纯债溢价率、转股溢价率、收盘价

信息来源:
  ① 东方财富数据中心 (akshare.bond_zh_cov_value_analysis) — 纯债价值/转股价值历史
  ② 东方财富数据中心 (datacenter-web.eastmoney.com)      — 转债日K线/转债行情
  ③ 同花顺 THS (akshare.bond_zh_hs_cov_spot)             — 剩余规模/换手率实时
  ④ 中证转债指数 (akshare.stock_zh_index_daily)          — 基准对比
  ⑤ 同花顺财务摘要 (akshare.stock_financial_abstract_ths) — ROE/GPM/EPS/BPS
  ⑥ 妙想 MX (东方财富官方 API)                           — 自然语言查询行业/财务/行情
     - mx-data: 金融数据自然语言查询
     - mx-search: 资讯搜索
     - 需 MX_APIKEY 配置
"""

import logging
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Optional

import numpy as np
import pandas as pd
from app.engine.data_enrich_utils import safe_float, safe_int
from app.services.task_registry import TaskStatus, get_registry

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

_bg = get_registry()

# ============================================================
# 妙想 MX 全局配置与工具函数
# ============================================================
_MX_TIMEOUT_SINGLE = 15       # 单只查询超时(秒): 行业/财务单只
_MX_TIMEOUT_BATCH = 30        # 批量查询超时(秒): 财务批量兜底
_MX_MAX_BATCH_SIZE = 30       # 批量兜底最大只数
_MX_WARN_COOLDOWN_SEC = 60    # 降级日志冷却时间(秒)
_MX_WARN_LAST_TS = 0.0        # 上次降级日志时间戳


def _mx_warn(msg: str):
    """妙想 MX 降级日志节流 — 60 秒内只 warn 一次"""
    global _MX_WARN_LAST_TS
    now = _time.time()
    if now - _MX_WARN_LAST_TS >= _MX_WARN_COOLDOWN_SEC:
        logger.warning(msg)
        _MX_WARN_LAST_TS = now
    else:
        logger.debug(msg)


def _mx_validate_value(v: float, name: str) -> bool:
    """MX 返回数值合理性校验
    
    校验范围:
      PE: 0~10000, PB: 0~1000, ROE: -50%~50%, 
      毛利率: 0~100%, 资产负债率: 0~100%,
      EPS: 0~1000, BPS: 0~1000, 净利率: -100%~100%
    """
    if np.isnan(v) or np.isinf(v):
        return False
    if name == "pe":
        return 0.0 < v < 10000.0
    if name == "pb":
        return 0.0 < v < 1000.0
    if name == "roe":
        return -50.0 < v < 50.0
    if name in ("gpm", "npm"):
        return -10.0 < v < 100.0
    if name == "debt_ratio":
        return 0.0 < v < 100.0
    if name == "eps":
        return 0.0 < v < 1000.0
    if name == "bps":
        return 0.0 < v < 1000.0
    if name == "revenue":
        return 0.0 < v < 1e9
    if name == "turnover":
        return 0.0 < v < 100.0
    return True


class ValueAnalysisRequest(BaseModel):
    bond_codes: list[str]
    max_workers: int = 10
    async_task: bool = False  # True: 后台异步, 返回 task_id


class IndustryRequest(BaseModel):
    stock_codes: list[str]
    max_workers: int = 8
    async_task: bool = False


class BondDailyEMRequest(BaseModel):
    bond_codes: list[str]
    start_date: str
    end_date: str
    max_workers: int = 10
    async_task: bool = False


class CSIIndexRequest(BaseModel):
    start_date: str
    end_date: str
    async_task: bool = False


class FinancialTHSRequest(BaseModel):
    stock_codes: list[str]
    max_workers: int = 8
    async_task: bool = False


class BondKlineEMRequest(BaseModel):
    bond_codes: list[str]
    start_date: str
    end_date: str
    max_workers: int = 10
    async_task: bool = False


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str


def _to_records(obj: Any) -> Any:
    """将 DataFrame / list / dict 转成可 JSON 序列化的结构"""
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict("records")
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    return obj


def _wrap_result(name: str, result: Any) -> dict[str, Any]:
    return {"status": "ok", "source": name, "data": _to_records(result)}


@router.post("/value-analysis")
async def api_value_analysis(req: ValueAnalysisRequest):
    """批量获取转债纯债价值/转股价值/溢价率历史"""
    if req.async_task:
        task_id = _bg.submit(
            "extra_value_analysis",
            lambda codes, **kw: _wrap_result("value_analysis", fetch_value_analysis_batch(codes, **kw)),
            req.bond_codes,
            max_workers=req.max_workers,
        )
        return TaskCreateResponse(task_id=task_id, status=TaskStatus.PENDING.value)
    try:
        df = fetch_value_analysis_batch(req.bond_codes, max_workers=req.max_workers)
        return _wrap_result("value_analysis", df)
    except Exception as e:
        logger.error(f"[Extra] value-analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bond-daily-em")
async def api_bond_daily_em(req: BondDailyEMRequest):
    """批量获取转债日行情"""
    if req.async_task:
        task_id = _bg.submit(
            "extra_bond_daily_em",
            lambda codes, start, end, **kw: _wrap_result("bond_daily_em", fetch_bond_daily_em_batch(codes, start, end, **kw)),
            req.bond_codes,
            date.fromisoformat(req.start_date),
            date.fromisoformat(req.end_date),
            max_workers=req.max_workers,
        )
        return TaskCreateResponse(task_id=task_id, status=TaskStatus.PENDING.value)
    try:
        df = fetch_bond_daily_em_batch(
            req.bond_codes,
            date.fromisoformat(req.start_date),
            date.fromisoformat(req.end_date),
            max_workers=req.max_workers,
        )
        return _wrap_result("bond_daily_em", df)
    except Exception as e:
        logger.error(f"[Extra] bond-daily-em error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/industry")
async def api_industry(req: IndustryRequest):
    """批量获取正股行业归属"""
    if req.async_task:
        task_id = _bg.submit(
            "extra_industry",
            lambda codes, **kw: _wrap_result("industry", fetch_industry_batch(codes, **kw)),
            req.stock_codes,
            max_workers=req.max_workers,
        )
        return TaskCreateResponse(task_id=task_id, status=TaskStatus.PENDING.value)
    try:
        result = fetch_industry_batch(req.stock_codes, max_workers=req.max_workers)
        return _wrap_result("industry", result)
    except Exception as e:
        logger.error(f"[Extra] industry error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/csi-index")
async def api_csi_index(req: CSIIndexRequest):
    """获取中证转债指数历史"""
    if req.async_task:
        task_id = _bg.submit(
            "extra_csi_index",
            lambda start, end: _wrap_result("csi_index", fetch_csi_index(start, end)),
            date.fromisoformat(req.start_date),
            date.fromisoformat(req.end_date),
        )
        return TaskCreateResponse(task_id=task_id, status=TaskStatus.PENDING.value)
    try:
        df = fetch_csi_index(
            date.fromisoformat(req.start_date),
            date.fromisoformat(req.end_date),
        )
        return _wrap_result("csi_index", df)
    except Exception as e:
        logger.error(f"[Extra] csi-index error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/financial-ths")
async def api_financial_ths(req: FinancialTHSRequest):
    """批量获取 THS 财务摘要"""
    if req.async_task:
        task_id = _bg.submit(
            "extra_financial_ths",
            lambda codes, **kw: _wrap_result("financial_ths", fetch_stock_financial_ths_batch(codes, **kw)),
            req.stock_codes,
            max_workers=req.max_workers,
        )
        return TaskCreateResponse(task_id=task_id, status=TaskStatus.PENDING.value)
    try:
        result = fetch_stock_financial_ths_batch(req.stock_codes, max_workers=req.max_workers)
        return _wrap_result("financial_ths", result)
    except Exception as e:
        logger.error(f"[Extra] financial-ths error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bond-kline-em")
async def api_bond_kline_em(req: BondKlineEMRequest):
    """批量获取转债 K 线"""
    if req.async_task:
        task_id = _bg.submit(
            "extra_bond_kline_em",
            lambda codes, start, end, **kw: _wrap_result("bond_kline_em", fetch_bond_kline_em_dc_batch(codes, start, end, **kw)),
            req.bond_codes,
            date.fromisoformat(req.start_date),
            date.fromisoformat(req.end_date),
            max_workers=req.max_workers,
        )
        return TaskCreateResponse(task_id=task_id, status=TaskStatus.PENDING.value)
    try:
        df = fetch_bond_kline_em_dc_batch(
            req.bond_codes,
            date.fromisoformat(req.start_date),
            date.fromisoformat(req.end_date),
            max_workers=req.max_workers,
        )
        return _wrap_result("bond_kline_em", df)
    except Exception as e:
        logger.error(f"[Extra] bond-kline-em error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def api_get_task(task_id: str):
    info = _bg.get(task_id)
    if info is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "task_id": info.task_id,
        "name": info.name,
        "status": info.status.value,
        "created_at": info.created_at,
        "updated_at": info.updated_at,
        "progress": info.progress,
        "result": info.result if info.status == TaskStatus.SUCCESS else None,
        "error": info.error,
    }


@router.get("/tasks")
async def api_list_tasks(status: Optional[str] = None, limit: int = 50):
    st = None
    if status:
        try:
            st = TaskStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid status")
    items = _bg.list_tasks(status=st, limit=limit)
    return [
        {
            "task_id": t.task_id,
            "name": t.name,
            "status": t.status.value,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            "progress": t.progress,
        }
        for t in items
    ]


# ============================================================
# 关键源 1: akshare.bond_zh_cov_value_analysis (东方财富数据中心)
# 字段: 日期/收盘价/纯债价值/转股价值/纯债溢价率/转股溢价率
# 范围: 每只转债 300-1500 天的完整历史 (不依赖IP)
# ============================================================
def _fetch_value_analysis_single(code: str) -> list[dict]:
    """
    获取单只转债的纯债价值/转股价值/溢价率历史数据

    数据源: 东方财富数据中心 (https://datacenter-web.eastmoney.com)
    接口: ak.bond_zh_cov_value_analysis(symbol=code)
    """
    import akshare as ak
    try:
        df = ak.bond_zh_cov_value_analysis(symbol=code)
        if df is None or df.empty:
            return []
        records = []
        for _, r in df.iterrows():
            try:
                dt_str = str(r.get("日期", ""))[:10]
                if not dt_str or dt_str == "nan":
                    continue
                dt = date.fromisoformat(dt_str)
            except (ValueError, TypeError):
                continue
            rec = {
                "code": code,
                "date": dt,
                "bond_value": safe_float(r.get("纯债价值")),
                "conversion_value": safe_float(r.get("转股价值")),
                "pure_bond_premium_ratio": safe_float(r.get("纯债溢价率")),
                "premium_ratio": safe_float(r.get("转股溢价率")),
                "close_price": safe_float(r.get("收盘价")),
            }
            records.append(rec)
        return records
    except Exception as e:
        logger.debug(f"[ValueAnalysis] {code}: {e}")
        return []


def fetch_value_analysis_batch(bond_codes: list[str], max_workers: int = 10) -> pd.DataFrame:
    """
    批量获取多只转债的纯债价值/转股价值历史数据

    Args:
        bond_codes: 转债代码列表
        max_workers: 并发线程数

    Returns:
        DataFrame(columns=['code', 'date', 'bond_value', 'conversion_value',
                          'pure_bond_premium_ratio', 'premium_ratio', 'close_price'])
    """
    if not bond_codes:
        return pd.DataFrame()
    logger.info(f"[ValueAnalysis] 并行下载{len(bond_codes)}只转债价值分析 (max_workers={max_workers})...")
    t0 = _time.time()
    all_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_value_analysis_single, code): code
                   for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                logger.debug(f"[ValueAnalysis] {code}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(bond_codes)} ({len(all_records)}条)")
                _time.sleep(0.1)

    if not all_records:
        logger.warning("[ValueAnalysis] 无数据")
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    elapsed = _time.time() - t0
    logger.info(f"[ValueAnalysis] 完成: {len(df)}条, {df['code'].nunique()}只, {df['date'].nunique()}天 ({elapsed:.0f}s)")
    return df


# ============================================================
# 关键源 2: 转债日K线 (东方财富数据中心 web API)
# 这个接口提供 3.5+ 年的转债K线 (日频), 通过 EM datacenter 而非 push2his
# ============================================================
def _fetch_bond_daily_em(code: str, start_date: date, end_date: date) -> list[dict]:
    """
    通过东方财富数据中心接口获取转债日K线 (不依赖被封的 push2his)

    接口: https://datacenter-web.eastmoney.com/api/data/v1/get
    """
    import requests as _req
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        # 转债代码需带前缀 (sh/sz)
        if code.startswith(("11", "13")):
            market = "sh"
        else:
            market = "sz"
        sort_type = "(SECURITY_CODE=\"" + market + code + "\")"
        params = {
            "sty": "ALL",
            "token": "894050c76af8597a853f5b408b759f5d",
            "st": "TRADE_DATE",
            "sr": "1",
            "source": "WEB",
            "type": "RPTA_WEB_KZZ_MRHQ",
            "filter": sort_type,
            "p": "1",
            "ps": "5000",
            "varName": "RT_WEB_KZZ_MRHQ",
        }
        resp = _req.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        result = data.get("result", {})
        if not result or not result.get("data"):
            return []
        records = []
        for row in result["data"]:
            try:
                dt = date.fromisoformat(str(row.get("TRADE_DATE", ""))[:10])
            except (ValueError, TypeError):
                continue
            if dt < start_date or dt > end_date:
                continue
            records.append({
                "code": code,
                "date": dt,
                "close_price": safe_float(row.get("CLOSE_PRICE")),
                "open_price": safe_float(row.get("OPEN_PRICE")),
                "high_price": safe_float(row.get("HIGH_PRICE")),
                "low_price": safe_float(row.get("LOW_PRICE")),
                "volume": safe_float(row.get("VOL")),
                "amount": safe_float(row.get("AMOUNT")),
            })
        return records
    except Exception as e:
        logger.debug(f"[BondDailyEM] {code}: {e}")
        return []


def fetch_bond_daily_em_batch(bond_codes: list[str], start_date: date, end_date: date,
                              max_workers: int = 15) -> pd.DataFrame:
    """
    批量获取转债日K线 (东方财富数据中心, 不依赖被封的 push2his)

    与 Tencent K线对比:
    - 优点: 提供 3.5+ 年历史数据 (vs 腾讯仅 90 天)
    - 缺点: 速度稍慢, IP可能限速
    """
    if not bond_codes:
        return pd.DataFrame()
    logger.info(f"[BondDailyEM] 并行下载{len(bond_codes)}只转债K线 ({start_date}~{end_date})...")
    t0 = _time.time()
    all_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_bond_daily_em, code, start_date, end_date): code
                   for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                logger.debug(f"[BondDailyEM] {futures[future]}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(bond_codes)} ({len(all_records)}条)")
                _time.sleep(0.2)

    if not all_records:
        return pd.DataFrame()
    df = pd.DataFrame(all_records)
    elapsed = _time.time() - t0
    logger.info(f"[BondDailyEM] 完成: {len(df)}条, {df['code'].nunique()}只, {df['date'].nunique()}天 ({elapsed:.0f}s)")
    return df


# ============================================================
# 关键源 3: 行业数据 (多源兜底)
# 优先级: 东方财富个股信息 → THS行业 → 新浪行业 → yfinance
# ============================================================
def _fetch_industry_em_single(stock_code: str) -> Optional[str]:
    """
    东方财富F10接口 (含行业) - 实际可用接口
    
    返回 sszjhhy (申万行业) / sshy (所属市场行业) 字段
    """
    import requests as _req
    try:
        if stock_code.startswith(("6", "9")):
            market = "SH"
        elif stock_code.startswith(("0", "3")):
            market = "SZ"
        elif stock_code.startswith(("4", "8")):
            market = "BJ"
        else:
            market = "SH"
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={market}{stock_code}"
        resp = _req.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        data = resp.json()
        jbzl = data.get("jbzl", {})
        industry = jbzl.get("sszjhhy") or jbzl.get("sshy")
        if industry and industry != "--" and len(industry) < 30:
            return industry
        return None
    except Exception as e:
        logger.debug(f"[IndustryEM] {stock_code}: {e}")
        return None


def _fetch_industry_ths_single(stock_code: str) -> Optional[str]:
    """从 东方财富 个股信息获取行业（原 THS stock_individual_info_ths 在 akshare 1.18.x 中已移除）"""
    import akshare as ak
    try:
        df = ak.stock_individual_info_em(symbol=stock_code)
        if df is None or df.empty:
            return None
        for _, r in df.iterrows():
            key = str(r.get("item", ""))
            if key in ("行业", "所属行业", "行业分类", "industry"):
                val = str(r.get("value", "")).strip()
                if val and val != "--":
                    return val
        return None
    except Exception:
        return None


def _fetch_industry_sina_single(stock_code: str) -> Optional[str]:
    """从新浪 F10 获取行业"""
    import requests as _req
    try:
        prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
        url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{stock_code}.phtml"
        resp = _req.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn"
        })
        if resp.status_code != 200:
            return None
        # 解析: 所属行业
        import re
        match = re.search(r'所属行业[：:]\s*<[^>]*>([^<]+)', resp.text)
        if match:
            industry = match.group(1).strip()
            if industry and len(industry) < 30:
                return industry
        # 备用: 找 sw_level1
        match2 = re.search(r'(中信一级|申万一级|申万二级|申万行业)[：:]\s*<[^>]*>([^<]+)', resp.text)
        if match2:
            return match2.group(2).strip()
        return None
    except Exception:
        return None


def _fetch_industry_yfinance_single(stock_code: str) -> Optional[str]:
    """从 yfinance 获取行业"""
    try:
        import yfinance as yf
        suffix = ".SS" if stock_code.startswith(("6", "9")) else ".SZ"
        ticker = yf.Ticker(f"{stock_code}{suffix}")
        info = ticker.info
        return info.get("industry") or info.get("sector")
    except Exception:
        return None


def _fetch_industry_mx_single(code: str) -> Optional[str]:
    """从妙想 MX 获取行业归属"""
    try:
        import asyncio
        from app.data.adapters.mx_adapter import MXAdapter
        from app.data.adapters.base import DataSourceConfig

        async def _query():
            from app.config import settings
            mx = MXAdapter(DataSourceConfig(name="mx"))
            await mx.connect()
            if getattr(mx, '_degraded_mode', False):
                _mx_warn(f"[MX Industry] {code}: 降级模式(无API Key), 跳过")
                return None
            if not settings.MX_APIKEY:
                _mx_warn(f"[MX Industry] {code}: MX_APIKEY 未配置")
                return None
            query_text = f"{code} 所属行业"
            resp = await mx.query_natural(query_text, "financial")
            if not resp.get("success"):
                return None
            rows = resp.get("data", [])
            for row in rows:
                for k in ["行业", "所属行业", "industry", "sector", "申万行业", "证监会行业", "行业分类", "一级行业", "二级行业"]:
                    if k in row and row[k]:
                        val = str(row[k]).strip()
                        if val and val != "--" and val != "-":
                            return val
            return None

        try:
            return asyncio.run(_query())
        except RuntimeError:
            import threading
            result_holder = {}
            def _run():
                result_holder["data"] = asyncio.run(_query())
            t = threading.Thread(target=_run)
            t.start()
            t.join(timeout=_MX_TIMEOUT_SINGLE)
            return result_holder.get("data")
    except Exception:
        return None


def _fetch_industry_single(code: str) -> Optional[str]:
    """多源兜底获取单个股票行业 - EM F10 > THS > Sina > yfinance > MX"""
    for fetcher in [_fetch_industry_em_single, _fetch_industry_ths_single, _fetch_industry_sina_single, _fetch_industry_yfinance_single, _fetch_industry_mx_single]:
        try:
            ind = fetcher(code)
            if ind:
                return ind
        except Exception:
            continue
    return None


def fetch_industry_batch(stock_codes: list[str], max_workers: int = 8) -> dict[str, str]:
    """
    批量获取多只正股的行业归属 (多源兜底)

    Returns: {stock_code: industry_name}
    """
    if not stock_codes:
        return {}
    logger.info(f"[Industry] 多源兜底获取{len(stock_codes)}只正股行业 (max_workers={max_workers})...")
    t0 = _time.time()
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_industry_single, code): code
                   for code in stock_codes}
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                ind = future.result()
                if ind:
                    results[code] = ind
            except Exception as e:
                logger.debug(f"[Industry] {code}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(stock_codes)} ({len(results)}只有行业)")
                _time.sleep(0.2)

    elapsed = _time.time() - t0
    logger.info(f"[Industry] 完成: {len(results)}/{len(stock_codes)}只有行业 ({elapsed:.0f}s)")
    return results


# ============================================================
# 关键源 4: 转债剩余规模 + 换手率 (THS bond_zh_hs_cov_spot 实时)
# ============================================================
def fetch_bond_misc_data() -> dict:
    """
    从转债实时行情获取剩余规模/换手率/流通规模/上市日期

    包含字段: 转债代码/转债名称/最新价/涨跌幅/剩余规模/换手率/成交额
    """
    import akshare as ak
    logger.info("[BondMisc] 下载转债实时misc数据(剩余规模/换手率)...")
    result = {}
    for attempt in range(2):
        try:
            df = ak.bond_zh_hs_cov_spot()
            if df is not None and not df.empty:
                for _, r in df.iterrows():
                    code = str(r.get("code", "")).strip()
                    if not code or len(code) != 6:
                        continue
                    out_scale = safe_float(r.get("剩余规模"))
                    turnover = safe_float(r.get("换手率"))
                    volume = safe_float(r.get("成交量"))
                    amount = safe_float(r.get("成交额"))
                    result[code] = {
                        "outstanding_scale": out_scale,
                        "turnover_rate": turnover,
                        "volume": volume,
                        "amount": amount,
                    }
                logger.info(f"[BondMisc] 完成: {len(result)}只")
                return result
        except Exception as e:
            logger.warning(f"[BondMisc] attempt{attempt+1}: {e}")
            _time.sleep(1)
    return result


# ============================================================
# 关键源 5: 中证转债指数 (CSI Convertible Bond Index) - 基准
# 字段: 收盘价/涨跌幅, 用于策略对比基准
# ============================================================
def fetch_csi_index(start_date: date, end_date: date) -> pd.DataFrame:
    """
    中证转债指数 (000832.CSI) 历史数据 - 基准对比

    Returns: DataFrame(date, close, change_pct)
    """
    import akshare as ak
    logger.info(f"[CSI Index] 下载中证转债指数 {start_date}~{end_date}...")
    try:
        df = ak.stock_zh_index_daily(symbol="sh000832")
        if df is None or df.empty:
            return pd.DataFrame()
        df['date'] = pd.to_datetime(df['date']).dt.date
        mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        df = df[mask].copy()
        df['change_pct'] = df['close'].pct_change() * 100
        df = df.rename(columns={'close': 'csi_index_close'})
        logger.info(f"[CSI Index] 完成: {len(df)}天")
        return df[['date', 'csi_index_close', 'change_pct']]
    except Exception as e:
        logger.warning(f"[CSI Index] 失败: {e}")
        return pd.DataFrame()


# ============================================================
# 关键源 6: 转债发行人/正股财务摘要 (THS)
# 用于补全 ROE/GPM 等基本面因子
# ============================================================
def fetch_stock_financial_ths_batch(stock_codes: list[str], max_workers: int = 8) -> dict[str, dict]:
    """
    批量获取正股财务摘要 (ROE/GPM/EPS/BPS/CAGR/资产负债率)

    Returns: {stock_code: {roe, gpm, eps, bps, cagr, debt_ratio, revenue}}
    """
    import akshare as ak
    logger.info(f"[THS Financial] 批量获取{len(stock_codes)}只正股财务摘要 (max_workers={max_workers})...")
    result: dict[str, dict] = {}

    def _fetch_one(code: str) -> tuple:
        try:
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
            if df is None or df.empty:
                return code, {}
            row = df.iloc[0]
            entry = {}
            for k_src, k_dst in [
                ("基本每股收益", "eps"),
                ("每股净资产", "bps"),
                ("净资产收益率", "roe"),
                ("毛利率", "gpm"),
                ("净利率", "npm"),
                ("营业收入", "revenue"),
                ("资产负债率", "debt_ratio"),
                ("销售毛利率", "gpm"),
                ("每股经营现金流", "ocfps"),
            ]:
                v = row.get(k_src, None)
                if v is not None and str(v) not in ("False", "None", ""):
                    try:
                        f = float(v)
                        if not (np.isnan(f) or np.isinf(f)):
                            entry[k_dst] = f
                    except (ValueError, TypeError):
                        pass
            return code, entry
        except Exception as e:
            return code, {}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_one, code): code for code in stock_codes}
        for i, future in enumerate(as_completed(futures)):
            code, entry = future.result()
            if entry:
                result[code] = entry
            if (i + 1) % 30 == 0:
                logger.info(f"  进度: {i+1}/{len(stock_codes)} ({len(result)}只有数据)")
                _time.sleep(0.3)

    # ===== 兜底: 妙想 MX 查询缺失的财务数据 =====
    missing = [c for c in stock_codes if c not in result]
    mx_count = 0
    if missing:
        # 动态调整兜底数量: 缺失少兜底多, 缺失多兜底上限
        dynamic_batch = min(max(len(missing), 20), _MX_MAX_BATCH_SIZE)
        logger.info(f"[THS Financial] MX 兜底: {len(missing)}只, 动态取{dynamic_batch}只...")
        t0 = _time.time()
        mx_result = _fetch_financial_mx_batch(missing[:dynamic_batch])
        for code, entry in mx_result.items():
            if entry and code not in result:
                result[code] = entry
                mx_count += 1
        logger.info(f"[THS Financial] MX 兜底完成: {mx_count}只 ({_time.time()-t0:.1f}s)")

    logger.info(f"[THS Financial] 完成: {len(result)}/{len(stock_codes)}只 (THS={len(result)-mx_count}, MX={mx_count})")
    return result


def _fetch_financial_mx_batch(codes: list[str]) -> dict[str, dict]:
    """通过妙想 MX 自然语言查询批量获取财务摘要"""
    if not codes:
        return {}
    try:
        import asyncio
        from app.data.adapters.mx_adapter import MXAdapter
        from app.data.adapters.base import DataSourceConfig

        async def _query():
            from app.config import settings
            mx = MXAdapter(DataSourceConfig(name="mx"))
            await mx.connect()
            if getattr(mx, '_degraded_mode', False):
                _mx_warn("[MX Financial] 降级模式(无API Key), 跳过批量财务兜底")
                return {}
            if not settings.MX_APIKEY:
                _mx_warn("[MX Financial] MX_APIKEY 未配置, 跳过")
                return {}
            results = {}
            for code in codes:
                query_text = f"{code} 净资产收益率 毛利率 资产负债率 基本每股收益 每股净资产"
                resp = await mx.query_natural(query_text, "financial")
                if not resp.get("success"):
                    continue
                rows = resp.get("data", [])
                if not rows:
                    continue
                row = rows[0]
                entry = {}
                for k in ["净资产收益率", "ROE", "roe", "净资产收益率(摊薄)", "净资产收益率_摊薄", "ROE_TTM", "roe_ttm", "净资产收益率TTM"]:
                    if k in row and row[k] is not None:
                        try:
                            v = float(row[k])
                            if _mx_validate_value(v, "roe"):
                                entry["roe"] = v
                                break
                        except (ValueError, TypeError):
                            pass
                for k in ["毛利率", "gross_margin", "销售毛利率", "Gross Margin", "主营业务毛利率"]:
                    if k in row and row[k] is not None:
                        try:
                            v = float(row[k])
                            if _mx_validate_value(v, "gpm"):
                                entry["gpm"] = v
                                break
                        except (ValueError, TypeError):
                            pass
                for k in ["资产负债率", "debt_ratio", "asset_liability_ratio", "资产负债率(%)", "总资产负债率"]:
                    if k in row and row[k] is not None:
                        try:
                            v = float(row[k])
                            if _mx_validate_value(v, "debt_ratio"):
                                entry["debt_ratio"] = v
                                break
                        except (ValueError, TypeError):
                            pass
                for k in ["基本每股收益", "EPS", "eps", "每股收益", "每股盈利", "基本EPS"]:
                    if k in row and row[k] is not None:
                        try:
                            v = float(row[k])
                            if _mx_validate_value(v, "eps"):
                                entry["eps"] = v
                                break
                        except (ValueError, TypeError):
                            pass
                for k in ["每股净资产", "BPS", "bps", "每股净值", "每股净资产(元)", "每股账面价值"]:
                    if k in row and row[k] is not None:
                        try:
                            v = float(row[k])
                            if _mx_validate_value(v, "bps"):
                                entry["bps"] = v
                                break
                        except (ValueError, TypeError):
                            pass
                for k in ["净利率", "npm", "净利率(%)", "销售净利率", "净利润率"]:
                    if k in row and row[k] is not None:
                        try:
                            v = float(row[k])
                            if _mx_validate_value(v, "npm"):
                                entry["npm"] = v
                                break
                        except (ValueError, TypeError):
                            pass
                for k in ["营业收入", "revenue", "营业总收入", "总营收", "Revenue"]:
                    if k in row and row[k] is not None:
                        try:
                            v = float(row[k])
                            if _mx_validate_value(v, "revenue"):
                                entry["revenue"] = v
                                break
                        except (ValueError, TypeError):
                            pass
                if entry:
                    import re
                    code_found = None
                    for k in ["代码", "code", "股票代码", "symbol"]:
                        if k in row and row[k]:
                            m = re.search(r'(\d{6})', str(row[k]))
                            if m:
                                code_found = m.group(1)
                                break
                    target_code = code_found if code_found else code
                    results[target_code] = entry
            return results

        try:
            return asyncio.run(_query())
        except RuntimeError:
            import threading
            result_holder = {}
            def _run():
                result_holder["data"] = asyncio.run(_query())
            t = threading.Thread(target=_run)
            t.start()
            t.join(timeout=_MX_TIMEOUT_BATCH)
            return result_holder.get("data", {})
    except Exception as e:
        logger.debug(f"[MX Financial] batch error: {e}")
        return {}


# ============================================================
# 关键源 7: East Money datacenter 历史K线 (push2his 被封时的备选)
# 接口: kzz.kline 获取 3.5+ 年日K线
# ============================================================
def _fetch_bond_kline_em_dc(code: str, start_date: date, end_date: date) -> list[dict]:
    """
    从东方财富数据中心获取转债日K线 (备选push2his)

    接口: https://datacenter-web.eastmoney.com/api/data/v1/get
    """
    import requests as _req
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        # 转债代码需带前缀
        if code.startswith(("11", "13")):
            market = "1"  # 上海
        else:
            market = "0"  # 深圳
        secid = f"{market}.{code}"
        params = {
            "sty": "ALL",
            "token": "894050c76af8597a853f5b408b759f5d",
            "st": "TRADE_DATE",
            "sr": "1",
            "source": "WEB",
            "type": "RPTA_WEB_KZZ_MRHQ",
            "filter": f'(SECURITY_CODE=\"{secid}\")',
            "p": "1",
            "ps": "5000",
        }
        resp = _req.get(url, params=params, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return []
        data = resp.json()
        result = data.get("result", {})
        if not result or not result.get("data"):
            return []
        records = []
        for row in result["data"]:
            try:
                dt = date.fromisoformat(str(row.get("TRADE_DATE", ""))[:10])
            except (ValueError, TypeError):
                continue
            if dt < start_date or dt > end_date:
                continue
            records.append({
                "code": code,
                "date": dt,
                "close_price": safe_float(row.get("CLOSE_PRICE")),
                "open_price": safe_float(row.get("OPEN_PRICE")),
                "high_price": safe_float(row.get("HIGH_PRICE")),
                "low_price": safe_float(row.get("LOW_PRICE")),
                "volume": safe_float(row.get("VOL")),
                "amount": safe_float(row.get("AMOUNT")),
            })
        return records
    except Exception as e:
        logger.debug(f"[BondKlineEM-DC] {code}: {e}")
        return []


def fetch_bond_kline_em_dc_batch(bond_codes: list[str], start_date: date, end_date: date,
                                  max_workers: int = 12) -> pd.DataFrame:
    """
    批量从东方财富数据中心获取转债日K线 (3.5+ 年历史)
    """
    if not bond_codes:
        return pd.DataFrame()
    logger.info(f"[BondKlineEM-DC] 下载{len(bond_codes)}只转债K线 (max_workers={max_workers})...")
    t0 = _time.time()
    all_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_bond_kline_em_dc, code, start_date, end_date): code
                   for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                logger.debug(f"[BondKlineEM-DC] {futures[future]}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(bond_codes)} ({len(all_records)}条)")
                _time.sleep(0.2)
    if not all_records:
        return pd.DataFrame()
    df = pd.DataFrame(all_records)
    elapsed = _time.time() - t0
    logger.info(f"[BondKlineEM-DC] 完成: {len(df)}条, {df['code'].nunique()}只 ({elapsed:.0f}s)")
    return df
