"""
SQLite K线缓存 — 修复版: 批量insert + 列名统一
"""
import os
import time as _time
import sqlite3
import logging
import pandas as pd
import akshare as ak
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import tqdm as _tqdm_module
_original_tqdm = _tqdm_module.tqdm
_tqdm_module.tqdm = lambda *a, **kw: _original_tqdm(*a, **{'disable': True, **kw})

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_PATH = os.path.join(CACHE_DIR, "kline_cache.db")


def _get_conn():
    conn = sqlite3.connect(CACHE_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kline_cache (
            stock_code TEXT, trade_date TEXT,
            open REAL, close REAL, high REAL, low REAL, amount REAL,
            PRIMARY KEY (stock_code, trade_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache_meta (
            stock_code TEXT PRIMARY KEY, last_fetch TEXT, n_days INTEGER
        )
    """)
    conn.commit()
    return conn


def get_cached_kline(stock_code: str, start_date: date, end_date: date) -> pd.DataFrame:
    """从缓存获取K线 (返回列: stock_code, trade_date, close, date)"""
    conn = _get_conn()
    df = pd.read_sql_query(
        "SELECT stock_code, trade_date, close, open, high, low, amount "
        "FROM kline_cache WHERE stock_code = ? AND trade_date BETWEEN ? AND ? "
        "ORDER BY trade_date",
        conn,
        params=(stock_code, start_date.isoformat(), end_date.isoformat()),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["trade_date"])
    return df


def is_cached(stock_code: str) -> bool:
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM cache_meta WHERE stock_code = ?", (stock_code,)).fetchone()
    conn.close()
    return row is not None


def cache_kline_data_bulk(stock_code: str, df: pd.DataFrame):
    """批量写入K线缓存 (修复: 使用executemany替代逐行insert)"""
    if df.empty or "date" not in df.columns or "close" not in df.columns:
        return
    conn = _get_conn()
    # 准备批量数据
    rows = []
    for _, r in df.iterrows():
        d = pd.to_datetime(r["date"]).strftime("%Y-%m-%d")
        rows.append((
            stock_code, d,
            float(r.get("open", 0) or 0), float(r.get("close", 0) or 0),
            float(r.get("high", 0) or 0), float(r.get("low", 0) or 0),
            float(r.get("amount", 0) or 0),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO kline_cache VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta VALUES (?,?,?)",
        (stock_code, datetime.now().isoformat(), len(rows)),
    )
    conn.commit()
    conn.close()


def _code_prefix(code: str) -> str:
    if code.startswith("6"):
        return f"sh{code}"
    elif code.startswith(("0", "3")):
        return f"sz{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sh{code}"


def _fetch_single(code: str, start_date: date, end_date: date):
    """下载单只股票K线 (返回: code, 全量df, 子集df)"""
    try:
        symbol = _code_prefix(code)
        df = ak.stock_zh_a_hist_tx(symbol=symbol, adjust="hfq")
        if df is None or df.empty:
            return code, None, None
        df["date"] = pd.to_datetime(df["date"])
        mask = (df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)
        subset = df[mask].copy()
        return code, df, subset
    except Exception as e:
        return code, None, None


def batch_fetch_stock_kline(
    stock_codes: list[str],
    start_date: date,
    end_date: date,
    max_workers: int = 6,
    force_refresh: bool = False,
) -> dict:
    """
    批量获取/更新K线 (修复版: 统一列名 + 批量insert)
    返回: {stock_code: DataFrame[stock_code, trade_date, close, date]}
    """
    result = {}
    need_fetch = []

    for sc in stock_codes:
        if not force_refresh and is_cached(sc):
            cached_df = get_cached_kline(sc, start_date, end_date)
            if not cached_df.empty and "close" in cached_df.columns:
                result[sc] = cached_df
                continue
        need_fetch.append(sc)

    if not need_fetch:
        hit = sum(1 for sc in stock_codes if sc in result)
        logger.info(f"  K线缓存命中: {hit}/{len(stock_codes)}")
        return result

    logger.info(f"  K线下载: {len(need_fetch)} 只 (6线程)...")
    t0 = _time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_single, sc, start_date, end_date): sc for sc in need_fetch}
        done = [0]

        for future in as_completed(futures):
            sc = futures[future]
            try:
                code, full_df, subset = future.result(timeout=120)
                if full_df is not None and not full_df.empty:
                    cache_kline_data_bulk(code, full_df)
                if subset is not None and not subset.empty:
                    # 统一列名: 添加 trade_date
                    subset["trade_date"] = pd.to_datetime(subset["date"]).dt.strftime("%Y-%m-%d")
                    result[code] = subset
            except Exception:
                pass
            done[0] += 1
            if done[0] % 100 == 0:
                logger.info(f"    K线: {done[0]}/{len(need_fetch)} ({len(result)}成功, {_time.time()-t0:.0f}s)")

    total = len(need_fetch)
    logger.info(f"  K线完成: {len(result)}/{total} 只 ({_time.time()-t0:.0f}s)")
    return result


def get_cache_stats() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM cache_meta").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM kline_cache").fetchone()[0]
    conn.close()
    return {"total_stocks": total, "total_rows": rows}