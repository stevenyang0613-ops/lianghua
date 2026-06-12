"""
可转债数据增强模块
从多个数据源补充转债的行业/评级/基本面等字段，
单次增量刷新，长时间缓存，失败不阻塞。
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import akshare as ak

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.environ.get("HOME", ".")) / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_INDUSTRY_CACHE_TTL = 86400 * 7
_SPOT_CACHE_TTL = 300
_FIN_CACHE_TTL = 3600 * 24
_FUND_FLOW_CACHE_TTL = 300

_INDUSTRY_CACHE = _CACHE_DIR / "stock_industry.json"
_SPOT_CACHE = _CACHE_DIR / "stock_spot.json"
_FIN_CACHE = _CACHE_DIR / "stock_fin.json"
_FUND_FLOW_CACHE = _CACHE_DIR / "stock_fund_flow.json"

_industry_map: dict[str, str] = {}
_industry_loaded = False
_spot_map: dict[str, dict] = {}
_spot_loaded = False
_fin_map: dict[str, dict] = {}
_fin_loaded = False
_fund_flow_map: dict[str, dict] = {}
_fund_flow_loaded = False


def _load_cache(path) -> Optional[dict]:
    try:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_cache(path, data: dict):
    try:
        data["_ts"] = time.time()
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"[DataEnrich] Cache save failed: {e}")


def _fresh(ttl: int, data) -> bool:
    return data is not None and time.time() - data.get("_ts", 0) < ttl


def get_industry(stock_code: str) -> Optional[str]:
    global _industry_map
    return _industry_map.get(stock_code)


def get_stock_spot(stock_code: str) -> dict:
    global _spot_map
    return _spot_map.get(stock_code, {})


def get_financial(code: str) -> dict:
    global _fin_map
    return _fin_map.get(code, {})


def get_fund_flow(code: str) -> dict:
    global _fund_flow_map
    return _fund_flow_map.get(code, {})


def _load_industry_cache():
    global _industry_map, _industry_loaded
    if _industry_loaded:
        return
    cached = _load_cache(_INDUSTRY_CACHE)
    if _fresh(_INDUSTRY_CACHE_TTL, cached):
        _industry_map = {k: v for k, v in cached.items() if k != "_ts"}
    _industry_loaded = True


def _load_spot_cache():
    global _spot_map, _spot_loaded
    if _spot_loaded:
        return
    cached = _load_cache(_SPOT_CACHE)
    if _fresh(_SPOT_CACHE_TTL, cached):
        _spot_map = cached
    _spot_loaded = True


def _load_fin_cache():
    global _fin_map, _fin_loaded
    if _fin_loaded:
        return
    cached = _load_cache(_FIN_CACHE)
    if _fresh(_FIN_CACHE_TTL, cached):
        _fin_map = cached
    _fin_loaded = True


def _load_fund_flow_cache():
    global _fund_flow_map, _fund_flow_loaded
    if _fund_flow_loaded:
        return
    cached = _load_cache(_FUND_FLOW_CACHE)
    if _fresh(_FUND_FLOW_CACHE_TTL, cached):
        _fund_flow_map = {k: v for k, v in cached.items() if k != "_ts"}
    _fund_flow_loaded = True


def _build_industry_cache():
    global _industry_map
    try:
        logger.info("[DataEnrich] Building industry cache (may take minutes)...")
        df = ak.stock_board_industry_name_em()
        result = {}
        count = 0
        total = len(df)
        for _, board in df.iterrows():
            bcode = str(board.get("板块代码", "")).strip()
            bname = str(board.get("板块名称", "")).strip()
            if not bcode or not bname:
                continue
            try:
                cons = ak.stock_board_industry_cons_em(symbol=bcode)
                for _, c in cons.iterrows():
                    scode = str(c.get("代码", "")).strip()
                    if scode:
                        result[scode] = bname
                count += 1
                if count % 100 == 0:
                    logger.info(f"[DataEnrich] Industry: {count}/{total} boards")
            except Exception:
                continue
        _industry_map = result
        _save_cache(_INDUSTRY_CACHE, result)
        logger.info(f"[DataEnrich] Industry built: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Industry build failed: {e}")


def _refresh_spot_cache():
    global _spot_map
    try:
        logger.info("[DataEnrich] Refreshing stock spot (PE/PB/turnover)...")
        df = ak.stock_zh_a_spot_em()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("代码", "")).strip()
            if not code:
                continue
            result[code] = {
                "pe": _sf(r.get("市盈率-动态")),
                "pb": _sf(r.get("市净率")),
                "change_pct": _sf(r.get("涨跌幅")),
                "price": _sf(r.get("最新价")),
                "volume": _sf(r.get("成交额")),
                "turnover_rate": _sf(r.get("换手率")),
                "total_mv": _sf(r.get("总市值")),
                "circ_mv": _sf(r.get("流通市值")),
            }
        _spot_map = result
        _save_cache(_SPOT_CACHE, result)
        logger.info(f"[DataEnrich] Stock spot: {len(result)} stocks (with turnover_rate)")
    except Exception as e:
        logger.warning(f"[DataEnrich] Stock spot refresh failed: {e}")


def _refresh_fund_flow_cache():
    global _fund_flow_map
    try:
        logger.info("[DataEnrich] Refreshing fund flow rank...")
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("代码", "")).strip()
            if not code:
                continue
            result[code] = {
                "net_main": _sf(r.get("今日主力净流入-净额")),
                "net_main_pct": _sf(r.get("今日主力净流入-净占比")),
                "net_super": _sf(r.get("今日超大单净流入-净额")),
                "net_big": _sf(r.get("今日大单净流入-净额")),
            }
        _fund_flow_map = result
        _save_cache(_FUND_FLOW_CACHE, result)
        logger.info(f"[DataEnrich] Fund flow: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Fund flow refresh failed: {e}")


def _refresh_fin_cache():
    global _fin_map
    try:
        logger.info("[DataEnrich] Refreshing financial data...")
        df = ak.stock_yjbb_em(date="20251231")
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            result[code] = {
                "roe": _sf(r.get("净资产收益率")),
                "gpm": _sf(r.get("营业收入同比增长率")),
            }
        _fin_map = result
        _save_cache(_FIN_CACHE, result)
        logger.info(f"[DataEnrich] Financial: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Financial refresh failed: {e}")


def _sf(v, default=None) -> Optional[float]:
    if v is None or v == "" or v == "nan":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


async def enrich_quotes(bonds: list) -> list:
    if not bonds:
        return bonds
    for b in bonds:
        stock_code = getattr(b, "stock_code", "") or ""
        if not stock_code and hasattr(b, "code"):
            stock_code = b.code[2:] if len(b.code) >= 3 else ""

        spot = get_stock_spot(stock_code)
        if spot:
            if spot.get("pe") is not None:
                b.pe = spot["pe"]
            if spot.get("pb") is not None:
                b.pb = spot["pb"]
            if spot.get("turnover_rate") is not None:
                b.turnover_rate = spot["turnover_rate"]

        industry = get_industry(stock_code)
        if industry:
            b.industry = industry

        fin = get_financial(stock_code)
        if fin.get("roe") is not None:
            b.roe = fin["roe"]

        flow = get_fund_flow(stock_code)
        if flow.get("net_main") is not None:
            b.net_capital_flow = flow["net_main"]
        if flow.get("net_main_pct") is not None:
            b.net_capital_flow_pct = flow["net_main_pct"]

    return bonds


async def start_background_refresh():
    loop = asyncio.get_event_loop()

    _load_industry_cache()
    _load_spot_cache()
    _load_fin_cache()
    _load_fund_flow_cache()

    loop.run_in_executor(None, _build_industry_cache)
    loop.run_in_executor(None, _refresh_spot_cache)
    loop.run_in_executor(None, _refresh_fin_cache)
    loop.run_in_executor(None, _refresh_fund_flow_cache)