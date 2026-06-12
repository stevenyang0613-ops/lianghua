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
from datetime import datetime
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# 缓存目录
_CACHE_DIR = Path(os.environ.get("HOME", ".")) / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 缓存TTL（秒）
_INDUSTRY_CACHE_TTL = 86400 * 7  # 行业一周刷新一次
_SPOT_CACHE_TTL = 300            # 正股行情5分钟刷新
_FIN_CACHE_TTL = 3600 * 24       # 财务数据一天刷新

# 缓存文件路径
_INDUSTRY_CACHE = _CACHE_DIR / "stock_industry.json"
_SPOT_CACHE = _CACHE_DIR / "stock_spot.json"
_FIN_CACHE = _CACHE_DIR / "stock_fin.json"

# 内存缓存
_industry_map: dict[str, str] = {}
_industry_loaded = False
_spot_map: dict[str, dict] = {}
_spot_loaded = False
_fin_map: dict[str, dict] = {}
_fin_loaded = False


def _load_cache(path: str) -> Optional[dict]:
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            age = time.time() - data.get("_ts", 0)
            return data
    except Exception as e:
        logger.debug(f"[DataEnrich] Cache load failed {path}: {e}")
    return None


def _save_cache(path: str, data: dict):
    try:
        data["_ts"] = time.time()
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"[DataEnrich] Cache save failed {path}: {e}")


def _fresh(ttl: int, data: Optional[dict]) -> bool:
    if data is None:
        return False
    age = time.time() - data.get("_ts", 0)
    return age < ttl


def get_industry(stock_code: str) -> Optional[str]:
    """获取正股所属行业（缓存 + 磁盘持久化）"""
    global _industry_map, _industry_loaded

    if not _industry_loaded:
        cached = _load_cache(_INDUSTRY_CACHE)
        if _fresh(_INDUSTRY_CACHE_TTL, cached):
            _industry_map = {k: v for k, v in cached.items() if k != "_ts"}
        else:
            _build_industry_cache()
        _industry_loaded = True

    return _industry_map.get(stock_code)


def _build_industry_cache():
    """构建行业映射（后台线程,失败不阻塞）"""
    global _industry_map
    try:
        logger.info("[DataEnrich] Building industry cache...")
        df = ak.stock_board_industry_name_em()
        result = {}
        count = 0
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
                    logger.info(f"[DataEnrich] Industry: {count}/496 boards done")
            except Exception:
                continue
        _industry_map = result
        _save_cache(_INDUSTRY_CACHE, result)
        logger.info(f"[DataEnrich] Industry cache built: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Industry cache build failed: {e}")


def get_stock_spot(stock_code: str) -> dict:
    """获取正股实时行情（PE/PB/涨跌幅）"""
    global _spot_map, _spot_loaded

    if not _spot_loaded:
        cached = _load_cache(_SPOT_CACHE)
        if _fresh(_SPOT_CACHE_TTL, cached):
            _spot_map = cached
        else:
            _refresh_spot_cache()
        _spot_loaded = True

    return _spot_map.get(stock_code, {})


def _refresh_spot_cache():
    """刷新正股行情（含PE/PB）"""
    global _spot_map
    try:
        logger.info("[DataEnrich] Refreshing stock spot data...")
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
            }
        _spot_map = result
        _save_cache(_SPOT_CACHE, result)
        logger.info(f"[DataEnrich] Stock spot: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Stock spot refresh failed: {e}")


def get_financial(code: str) -> dict:
    """获取转债对应的财务数据（ROE/毛利率等）"""
    global _fin_map, _fin_loaded

    if not _fin_loaded:
        cached = _load_cache(_FIN_CACHE)
        if _fresh(_FIN_CACHE_TTL, cached):
            _fin_map = cached
        else:
            _refresh_fin_cache()
        _fin_loaded = True

    return _fin_map.get(code, {})


def _refresh_fin_cache():
    """刷新财务数据（从东方财富获取）"""
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
        logger.info(f"[DataEnrich] Financial data: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Financial refresh failed: {e}")


def _sf(v, default=None) -> Optional[float]:
    """安全转float"""
    if v is None or v == "" or v == "nan":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


async def enrich_quotes(bonds: list) -> list:
    """批量增强行情数据：补充行业/PE/PB/ROE等字段"""
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

        industry = get_industry(stock_code)
        if industry:
            b.industry = industry

        fin = get_financial(stock_code)
        if fin.get("roe") is not None:
            b.roe = fin["roe"]

    return bonds


async def start_background_refresh():
    """后台启动缓存刷新（不阻塞启动）"""
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _build_industry_cache)
    loop.run_in_executor(None, _refresh_spot_cache)
    loop.run_in_executor(None, _refresh_fin_cache)