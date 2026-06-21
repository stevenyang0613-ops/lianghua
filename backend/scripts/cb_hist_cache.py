"""可转债历史行情数据下载器+SQLite缓存
使用新浪quotes.sina.cn API获取真实历史数据
"""
import os, sys, sqlite3, json, time, logging
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cb_hist")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(CACHE_DIR, exist_ok=True)
DB_PATH = os.path.join(CACHE_DIR, "cb_hist_cache.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cb_daily (
            bond_code TEXT, trade_date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (bond_code, trade_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cb_daily_code ON cb_daily(bond_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cb_daily_date ON cb_daily(trade_date)")
    conn.commit()
    return conn

def get_cached_dates(conn, bond_code):
    """返回已缓存的交易日期列表"""
    cur = conn.execute("SELECT trade_date FROM cb_daily WHERE bond_code=?", (bond_code,))
    return set(row[0] for row in cur.fetchall())

def fetch_single_bond(bond_code):
    """下载单个可转债的历史K线"""
    prefix = 'sh' if bond_code.startswith('11') else 'sz'
    symbol = f"{prefix}{bond_code}"
    url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&datalen=1023&scale=240"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return bond_code, []
        data = r.json()
        if not data or not isinstance(data, list):
            return bond_code, []
        rows = []
        for item in data:
            d = item.get("day", "")
            if not d: continue
            rows.append((
                bond_code, d,
                float(item.get("open", 0) or 0),
                float(item.get("high", 0) or 0),
                float(item.get("low", 0) or 0),
                float(item.get("close", 0) or 0),
                float(item.get("volume", 0) or 0),
            ))
        return bond_code, rows
    except Exception as e:
        return bond_code, []

def download_all(bond_codes, max_workers=10, force=False):
    """批量下载所有可转债历史行情"""
    conn = init_db()
    
    # Check cache
    if not force:
        cached = set()
        for code in bond_codes:
            dates = get_cached_dates(conn, code)
            if dates:
                cached.add(code)
        todo = [c for c in bond_codes if c not in cached]
    else:
        todo = list(bond_codes)
    
    logger.info(f"CB历史: {len(todo)}/{len(bond_codes)} 需要下载 (缓存{len(bond_codes)-len(todo)}只)")
    
    if not todo:
        logger.info("全部已缓存, 跳过下载")
        conn.close()
        return
    
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_single_bond, c): c for c in todo}
        for f in as_completed(futs):
            code, rows = f.result()
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO cb_daily VALUES (?,?,?,?,?,?,?)",
                    rows
                )
                conn.commit()
            done += 1
            if done % 50 == 0:
                elapsed = time.time() - t0
                logger.info(f"  CB: {done}/{len(todo)} ({elapsed:.0f}s)")
    
    elapsed = time.time() - t0
    # Stats
    cur = conn.execute("SELECT COUNT(DISTINCT bond_code), COUNT(*) FROM cb_daily")
    codes, rows = cur.fetchone()
    logger.info(f"CB历史完成: {codes}只, {rows}行 ({elapsed:.0f}s)")
    conn.close()

def get_hist_data(bond_codes, start_date, end_date):
    """获取缓存的行情数据"""
    conn = init_db()
    placeholders = ",".join("?" for _ in bond_codes)
    query = f"""
        SELECT bond_code, trade_date, close 
        FROM cb_daily 
        WHERE bond_code IN ({placeholders})
        AND trade_date >= ? AND trade_date <= ?
        ORDER BY bond_code, trade_date
    """
    params = list(bond_codes) + [start_date.isoformat(), end_date.isoformat()]
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if not df.empty:
        df['trade_date'] = pd.to_datetime(df['trade_date'])
    return df

def get_cache_stats():
    conn = init_db()
    cur = conn.execute("SELECT COUNT(DISTINCT bond_code), COUNT(*) FROM cb_daily")
    codes, rows = cur.fetchone()
    cur = conn.execute("SELECT MIN(trade_date), MAX(trade_date) FROM cb_daily")
    dmin, dmax = cur.fetchone()
    conn.close()
    return {"codes": codes, "rows": rows, "date_min": dmin, "date_max": dmax}

if __name__ == "__main__":
    import akshare as ak
    df = ak.bond_zh_cov_info_ths()
    codes = [str(r.get("债券代码","")).strip() for _, r in df.iterrows()
             if str(r.get("债券代码","")).strip() and len(str(r.get("债券代码","")).strip()) == 6]
    print(f"Total bonds: {len(codes)}")
    download_all(codes, max_workers=10)
    stats = get_cache_stats()
    print(f"Cache: {stats}")
