"""
估值结果缓存 — SQLite持久化Baidu PE/PB, 避免每次跑150s
"""
import os
import sqlite3
import logging
from datetime import datetime
import pandas as pd

from app.api.data_sources import get_stock_valuations

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_PATH = os.path.join(CACHE_DIR, "valuations_cache.db")


def _get_conn():
    conn = sqlite3.connect(CACHE_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pe_pb_cache (
            stock_code TEXT PRIMARY KEY,
            pe REAL,
            pb REAL,
            fetch_date TEXT
        )
    """)
    conn.commit()
    return conn


def load_cached_valuations() -> dict:
    """从缓存加载PE/PB"""
    conn = _get_conn()
    rows = conn.execute("SELECT stock_code, pe, pb FROM pe_pb_cache WHERE pe IS NOT NULL").fetchall()
    conn.close()
    result = {}
    for code, pe, pb in rows:
        entry = {}
        if pe is not None: entry["pe"] = pe
        if pb is not None: entry["pb"] = pb
        if entry:
            result[code] = entry
    return result


def save_valuations(valuations: dict):
    """保存PE/PB到缓存"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    rows = [(code, v.get("pe"), v.get("pb"), now) for code, v in valuations.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO pe_pb_cache (stock_code, pe, pb, fetch_date) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_cached_valuations(
    stock_codes: list[str], stock_prices: dict[str, float] = None, force_refresh: bool = False
) -> dict[str, dict]:
    """
    获取PE/PB估值 (缓存优先)
    
    如果缓存未命中或force_refresh=True, 调用Baidu获取
    """
    cached = {} if force_refresh else load_cached_valuations()
    
    missing = [c for c in stock_codes if c not in cached]
    if not missing:
        logger.info(f"  PE/PB缓存命中: {len(cached)}/{len(stock_codes)}")
        return cached
    
    logger.info(f"  PE/PB下载: {len(missing)} 只 (缓存未命中)")
    fresh = get_stock_valuations(missing, stock_prices)
    
    # 合并
    result = dict(cached)
    for code, val in fresh.items():
        result[code] = val
    
    # 保存新数据到缓存
    if fresh:
        save_valuations(fresh)
    
    return result