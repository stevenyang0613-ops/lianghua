#!/usr/bin/env python3
"""
璇玑量化系统 — 3.5年完整历史数据下载脚本

数据源优先级 (从免费到付费):
  ① BaoStock        — A股正股5年+日K线 (免费, 稳定, 主力)
  ② AKShare Tencent — 可转债日K线 (90天+)
  ③ AKShare THS      — 可转债列表/转股价/到期日
  ④ AKShare Sina     — 可转债实时行情
  ⑤ AKShare Jisilu   — 可转债溢价率/双低/评级/YTM
  ⑥ AKShare Baidu    — 正股PE/PB估值
  ⑦ Tushare Pro      — 纯债价值/bond_value (可选付费)

使用方法:
    python scripts/download_historical_data.py [--days 1260] [--start 2022-01-01]

输出: 直接写入 ~/.lianghua/market.db 的 daily_snapshots 表
"""

import argparse
import logging
import os
import sys
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('historical_download')

# ==================== 路径配置 ====================
DB_PATH = os.environ.get(
    "LH_DB_PATH",
    str(Path.home() / ".lianghua" / "market.db")
)

# ==================== 辅助函数 ====================

def _init_db(conn: duckdb.DuckDBPyConnection):
    """确保daily_snapshots表存在且有正确的schema"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            code VARCHAR NOT NULL,
            name VARCHAR DEFAULT '',
            close_price DOUBLE DEFAULT 0,
            open_price DOUBLE DEFAULT 0,
            high_price DOUBLE DEFAULT 0,
            low_price DOUBLE DEFAULT 0,
            volume DOUBLE DEFAULT 0,
            snapshot_date DATE NOT NULL,
            premium_ratio DOUBLE,
            change_pct DOUBLE,
            stock_price DOUBLE,
            stock_code VARCHAR DEFAULT '',
            conversion_value DOUBLE,
            conversion_price DOUBLE,
            dual_low DOUBLE,
            ytm DOUBLE,
            remaining_years DOUBLE,
            pe DOUBLE,
            pb DOUBLE,
            iv DOUBLE,
            hv DOUBLE,
            roe DOUBLE,
            gpm DOUBLE,
            rating VARCHAR DEFAULT '',
            bond_value DOUBLE,
            coupon_rate DOUBLE,
            add_rate DOUBLE,
            outstanding_scale DOUBLE,
            industry VARCHAR DEFAULT '',
            PRIMARY KEY (snapshot_date, code)
        )
    """)
    # 确保列存在 (兼容旧表)
    for col_sql in [
        "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS bond_value DOUBLE",
        "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS coupon_rate DOUBLE",
        "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS add_rate DOUBLE",
        "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS hv DOUBLE",
        "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS industry VARCHAR DEFAULT ''",
        "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS outstanding_scale DOUBLE",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bond_info (
            code VARCHAR PRIMARY KEY,
            name VARCHAR,
            stock_code VARCHAR,
            stock_name VARCHAR,
            conversion_price DOUBLE,
            maturity_date DATE,
            coupon_rate DOUBLE,
            add_rate DOUBLE,
            issue_size DOUBLE,
            remain_size DOUBLE,
            list_date DATE,
            delist_date DATE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_log (
            date DATE PRIMARY KEY,
            bond_count INTEGER,
            stock_count INTEGER,
            duration_seconds DOUBLE
        )
    """)


def _db_save_batch(conn: duckdb.DuckDBPyConnection, rows: list[dict]):
    """批量保存到daily_snapshots (UPSERT)"""
    if not rows:
        return 0

    # DuckDB参数化批量插入
    import json as _json
    values = []
    for r in rows:
        snap_dt = r.get("date", r.get("snapshot_date"))
        if isinstance(snap_dt, str):
            snap_dt = date.fromisoformat(snap_dt)
        values.append((
            str(r.get("code", "")),
            str(r.get("name", "")),
            float(r.get("close_price", r.get("price", 0)) or 0),
            float(r.get("open_price", r.get("open", 0)) or 0),
            float(r.get("high_price", r.get("high", 0)) or 0),
            float(r.get("low_price", r.get("low", 0)) or 0),
            float(r.get("volume", 0) or 0),
            snap_dt,
            float(r["premium_ratio"]) if pd.notna(r.get("premium_ratio")) else None,
            float(r["change_pct"]) if pd.notna(r.get("change_pct")) else None,
            float(r["stock_price"]) if pd.notna(r.get("stock_price")) else None,
            str(r.get("stock_code", "")),
            float(r["conversion_value"]) if pd.notna(r.get("conversion_value")) else None,
            float(r["conversion_price"]) if pd.notna(r.get("conversion_price")) else None,
            float(r["dual_low"]) if pd.notna(r.get("dual_low")) else None,
            float(r["ytm"]) if pd.notna(r.get("ytm")) else None,
            float(r["remaining_years"]) if pd.notna(r.get("remaining_years")) else None,
            float(r["pe"]) if pd.notna(r.get("pe")) else None,
            float(r["pb"]) if pd.notna(r.get("pb")) else None,
            float(r["iv"]) if pd.notna(r.get("iv")) else None,
            float(r["hv"]) if pd.notna(r.get("hv")) else None,
            float(r["roe"]) if pd.notna(r.get("roe")) else None,
            float(r["gpm"]) if pd.notna(r.get("gpm")) else None,
            str(r.get("rating", "")),
            float(r["bond_value"]) if pd.notna(r.get("bond_value")) else None,
            float(r["coupon_rate"]) if pd.notna(r.get("coupon_rate")) else None,
            float(r["add_rate"]) if pd.notna(r.get("add_rate")) else None,
            float(r["outstanding_scale"]) if pd.notna(r.get("outstanding_scale")) else None,
            str(r.get("industry", "")),
        ))

    conn.executemany("""
        INSERT INTO daily_snapshots (
            code, name, close_price, open_price, high_price, low_price,
            volume, snapshot_date, premium_ratio, change_pct,
            stock_price, stock_code, conversion_value, conversion_price,
            dual_low, ytm, remaining_years, pe, pb, iv, hv,
            roe, gpm, rating, bond_value, coupon_rate, add_rate,
            outstanding_scale, industry
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (snapshot_date, code) DO UPDATE SET
            close_price = COALESCE(excluded.close_price, daily_snapshots.close_price),
            premium_ratio = COALESCE(excluded.premium_ratio, daily_snapshots.premium_ratio),
            change_pct = COALESCE(excluded.change_pct, daily_snapshots.change_pct),
            stock_price = COALESCE(excluded.stock_price, daily_snapshots.stock_price),
            conversion_value = COALESCE(excluded.conversion_value, daily_snapshots.conversion_value),
            pe = COALESCE(excluded.pe, daily_snapshots.pe),
            pb = COALESCE(excluded.pb, daily_snapshots.pb),
            iv = COALESCE(excluded.iv, daily_snapshots.iv),
            hv = COALESCE(excluded.hv, daily_snapshots.hv),
            roe = COALESCE(excluded.roe, daily_snapshots.roe),
            gpm = COALESCE(excluded.gpm, daily_snapshots.gpm),
            rating = COALESCE(excluded.rating, daily_snapshots.rating),
            bond_value = COALESCE(excluded.bond_value, daily_snapshots.bond_value),
            coupon_rate = COALESCE(excluded.coupon_rate, daily_snapshots.coupon_rate),
            ytm = COALESCE(excluded.ytm, daily_snapshots.ytm),
            dual_low = COALESCE(excluded.dual_low, daily_snapshots.dual_low)
    """, values)
    return len(values)


def _compute_hv(series: pd.Series, min_periods: int = 5) -> float:
    """从价格序列计算年化波动率(HV)"""
    s = series.dropna()
    if len(s) < min_periods:
        return float('nan')
    # 取最近最多60个交易日
    recent = s.tail(60).values
    if len(recent) < 2:
        return float('nan')
    returns = [(recent[i] / recent[i-1] - 1) for i in range(1, len(recent)) if recent[i-1] > 0]
    if len(returns) < min_periods:
        return float('nan')
    hv = float(np.std(returns, ddof=1) * np.sqrt(252) * 100)
    return max(5.0, min(80.0, hv))


def _compute_bond_value(face_value: float, coupon_rate: float, add_rate: float,
                        remaining_years: float, discount_rate: float = 0.035) -> float:
    """
    计算纯债价值 (债券底)
    
    可转债纯债价值 = 各期利息现值 + 到期本金及补偿利率现值
    
    Args:
        face_value: 面值 (通常100)
        coupon_rate: 票面利率 (%)
        add_rate: 到期补偿利率 (%)
        remaining_years: 剩余年限
        discount_rate: 贴现率 (通常取3.5%或同期限国债收益率)
    
    Returns:
        纯债价值 (元)
    """
    if coupon_rate <= 0 or remaining_years <= 0:
        return float('nan')

    total_pv = 0.0
    # 每年付息
    for yr in range(1, int(remaining_years) + 1):
        if yr < remaining_years:
            cf = face_value * coupon_rate / 100
        else:
            # 最后一年: 利息 + 本金 + 补偿利率
            cf = face_value * (1 + coupon_rate / 100 + add_rate / 100)
        total_pv += cf / ((1 + discount_rate) ** yr)

    # 处理小数年份
    frac = remaining_years - int(remaining_years)
    if frac > 0.01:
        cf = face_value * coupon_rate / 100
        total_pv += cf / ((1 + discount_rate) ** remaining_years)

    return round(total_pv, 2)


# ==================== 第1步: 获取转债主列表 ====================

def fetch_bond_list_ths() -> dict:
    """THS可转债主列表"""
    import akshare as ak
    logger.info("[Step 1] 从THS获取可转债主列表...")
    for attempt in range(3):
        try:
            df = ak.bond_zh_cov_info_ths()
            if df is not None and not df.empty:
                bond_info = {}
                for _, r in df.iterrows():
                    code = str(r.get("债券代码", "")).strip()
                    if not code or len(code) != 6:
                        continue
                    mat_date = r.get("到期时间")
                    if isinstance(mat_date, str) and mat_date:
                        try:
                            mat_date = date.fromisoformat(mat_date[:10])
                        except:
                            mat_date = None
                    elif hasattr(mat_date, 'date'):
                        mat_date = mat_date.date()
                    bond_info[code] = {
                        "code": code,
                        "name": str(r.get("债券简称", "")).strip(),
                        "stock_code": str(r.get("正股代码", "")).strip(),
                        "stock_name": str(r.get("正股简称", "")).strip(),
                        "conversion_price": float(r.get("转股价格", 0) or 0),
                        "maturity_date": mat_date,
                    }
                logger.info(f"  THS: {len(bond_info)}只可转债")
                return bond_info
        except Exception as e:
            logger.warning(f"  THS attempt {attempt+1}: {e}")
            _time.sleep(2)
    logger.error("  THS三次重试均失败!")
    return {}


def fetch_bond_list_tushare() -> dict:
    """Tushare Pro可转债基本信息 (含coupon_rate, add_rate, maturity_date等)"""
    try:
        from app.config import settings
        token = settings.TUSHARE_TOKEN
        if not token:
            logger.info("  Tushare: 无token, 跳过")
            return {}
    except Exception:
        token = os.environ.get('LH_TUSHARE_TOKEN', '')
        if not token:
            return {}

    try:
        import tushare as ts
        pro = ts.pro_api(token)
        df = pro.cb_basic(fields='ts_code,bond_short_name,stk_code,stk_short_name,'
                                  'maturity_date,coupon_rate,add_rate,conv_price,'
                                  'remain_size,list_date,delist_date,issue_size')
        if df is None or df.empty:
            return {}
        result = {}
        for _, r in df.iterrows():
            code = str(r.get('ts_code', '')).split('.')[0]
            if not code or len(code) != 6:
                continue
            mat_date = r.get('maturity_date')
            if isinstance(mat_date, str) and mat_date:
                try:
                    mat_date = date.fromisoformat(mat_date[:10])
                except:
                    mat_date = None
            result[code] = {
                "code": code,
                "name": str(r.get('bond_short_name', '')),
                "stock_code": str(r.get('stk_code', '')).split('.')[0],
                "stock_name": str(r.get('stk_short_name', '')),
                "conversion_price": float(r.get('conv_price', 0) or 0),
                "maturity_date": mat_date,
                "coupon_rate": float(r.get('coupon_rate', 0) or 0),
                "add_rate": float(r.get('add_rate', 0) or 0),
                "issue_size": float(r.get('issue_size', 0) or 0),
                "remain_size": float(r.get('remain_size', 0) or 0),
                "list_date": r.get('list_date'),
                "delist_date": r.get('delist_date'),
            }
        logger.info(f"  Tushare: {len(result)}只可转债基本信息")
        return result
    except ImportError:
        logger.info("  Tushare: tushare包未安装")
        return {}
    except Exception as e:
        logger.warning(f"  Tushare: 获取失败: {e}")
        return {}


# ==================== 第2步: 获取Jisilu数据 (溢价率/双低/评级/YTM) ====================

def fetch_jisilu_data() -> dict:
    """集思录 — 溢价率/双低/评级/YTM/剩余规模/换手率"""
    import akshare as ak
    logger.info("[Step 2] 从Jisilu获取转债实时数据...")
    result = {}
    try:
        df = ak.bond_cb_jsl()
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                if not code or len(code) != 6:
                    continue
                result[code] = {
                    "premium_ratio": float(r.get("转股溢价率", 0) or 0),
                    "dual_low": float(r.get("双低", 0) or 0),
                    "rating": str(r.get("债券评级", "")).strip(),
                    "ytm": float(r.get("到期税前收益", 0) or 0),
                    "remaining_scale": float(r.get("剩余规模", 0) or 0),
                    "turnover_rate": float(r.get("换手率", 0) or 0),
                    "price": float(r.get("现价", 0) or 0),
                    "stock_price": float(r.get("正股价", 0) or 0),
                    "conversion_value": float(r.get("转股价值", 0) or 0),
                }
            logger.info(f"  Jisilu: {len(result)}只有数据")
    except Exception as e:
        logger.warning(f"  Jisilu失败: {e}")
    return result


# ==================== 第3步: 下载可转债日K线 (腾讯) ====================

def _fetch_bond_kline_tx(code: str, start_date: date, end_date: date) -> list[dict]:
    """腾讯K线: 每只可转债最多90天"""
    import akshare as ak
    market = "sh" if code.startswith(("11", "13")) else "sz"
    symbol = f"{market}{code}"
    try:
        df = ak.stock_zh_a_hist_tx(symbol=symbol, adjust="qfq")
        if df is None or df.empty:
            return []
        records = []
        for _, r in df.iterrows():
            try:
                dt = r["date"]
                if isinstance(dt, str):
                    dt = date.fromisoformat(dt[:10])
                elif hasattr(dt, 'date'):
                    dt = dt.date()
                else:
                    continue
            except:
                continue
            if dt < start_date or dt > end_date:
                continue
            close_v = float(r.get("close", 0) or 0)
            if close_v <= 0:
                continue
            records.append({
                "code": code,
                "date": dt,
                "close_price": close_v,
                "open_price": float(r.get("open", close_v) or close_v),
                "high_price": float(r.get("high", close_v) or close_v),
                "low_price": float(r.get("low", close_v) or close_v),
                "volume": float(r.get("volume", 0) or 0),
                "change_pct": float(r.get("percent", 0) or 0),
            })
        return records
    except Exception as e:
        logger.debug(f"  腾讯K线 {code}: {e}")
        return []


def download_bond_kline_tx(bond_codes: list[str], start_date: date, end_date: date,
                           max_workers: int = 10) -> pd.DataFrame:
    """并行下载可转债腾讯K线"""
    logger.info(f"[Step 3] 下载可转债腾讯K线 ({len(bond_codes)}只, {start_date}~{end_date})...")
    all_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_bond_kline_tx, code, start_date, end_date): code
                   for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            try:
                records = future.result()
                all_records.extend(records)
            except Exception:
                pass
            if (i + 1) % 100 == 0:
                logger.info(f"  进度: {i+1}/{len(bond_codes)} ({len(all_records)}条)")
                _time.sleep(0.05)

    if not all_records:
        logger.warning("  腾讯K线无数据!")
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    logger.info(f"  腾讯K线: {len(df)}条, {df['code'].nunique()}只, {df['date'].nunique()}个交易日")
    return df


# ==================== 第4步: 下载正股日K线 (BaoStock — 5年+) ====================

def _fetch_stock_kline_baostock(stock_code: str, start_date: date, end_date: date) -> list[dict]:
    """BaoStock A股正股日K线 (免费, 5年+数据)"""
    try:
        import baostock as bs
        bs.login()
        prefix = "sz" if stock_code.startswith(("0", "3")) else "sh"
        symbol = f"{prefix}.{stock_code}"
        rs = bs.query_history_k_data_plus(
            symbol,
            "date,open,high,low,close,volume,amount",
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            frequency="d",
            adjustflag="2"  # 后复权
        )
        records = []
        while (rs.error_code == '0') and rs.next():
            row = rs.get_row_data()
            if not row or len(row) < 6:
                continue
            try:
                dt = date.fromisoformat(row[0])
            except:
                continue
            close_v = float(row[4] or 0)
            if close_v <= 0:
                continue
            records.append({
                "stock_code": stock_code,
                "date": dt,
                "close_price": close_v,
                "open_price": float(row[1] or close_v),
                "high_price": float(row[2] or close_v),
                "low_price": float(row[3] or close_v),
                "volume": float(row[5] or 0),
            })
        bs.logout()
        return records
    except Exception as e:
        logger.debug(f"  BaoStock {stock_code}: {e}")
        return []


def download_stock_kline_baostock(stock_codes: list[str], start_date: date, end_date: date,
                                   max_workers: int = 10) -> dict[str, pd.DataFrame]:
    """并行下载正股BaoStock K线"""
    logger.info(f"[Step 4] 下载正股BaoStock K线 ({len(stock_codes)}只, {start_date}~{end_date})...")
    result: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_stock_kline_baostock, sc, start_date, end_date): sc
                   for sc in stock_codes}
        for i, future in enumerate(as_completed(futures)):
            sc = futures[future]
            try:
                records = future.result()
                if records:
                    result[sc] = records
            except Exception:
                pass
            if (i + 1) % 50 == 0:
                logger.info(f"  进度: {i+1}/{len(stock_codes)} ({sum(len(v) for v in result.values())}条)")

    # 转为 {stock_code: {date: record}}
    stock_data: dict[str, dict] = {}
    for sc, records in result.items():
        stock_data[sc] = {}
        for r in records:
            dt = r["date"]
            if dt not in stock_data[sc]:
                stock_data[sc][dt] = r
    logger.info(f"  正股K线: {len(stock_data)}只股票有数据, {sum(len(v) for v in stock_data.values())}条记录")
    return stock_data


# ==================== 第5步: PE/PB估值数据 ====================

def fetch_baidu_valuation(stock_codes: list[str], max_workers: int = 15) -> dict[str, dict]:
    """百度估值 - PE/PB"""
    from app.api.data_sources import get_stock_valuations
    logger.info(f"[Step 5] Baidu PE/PB ({len(stock_codes)}只)...")
    result = get_stock_valuations(stock_codes)
    pe_ok = sum(1 for v in result.values() if v.get('pe'))
    pb_ok = sum(1 for v in result.values() if v.get('pb'))
    logger.info(f"  PE/PB: PE={pe_ok}, PB={pb_ok}/{len(stock_codes)}")
    return result


# ==================== 第6步: THS财务摘要 ====================

def fetch_ths_financial(stock_codes: list[str]) -> dict[str, dict]:
    """THS财务摘要 — ROE/GPM/EPS/BPS"""
    import akshare as ak
    logger.info(f"[Step 6] THS财务摘要 ({len(stock_codes)}只, 限200只)...")
    result = {}
    limit = min(200, len(stock_codes))
    for i, sc in enumerate(stock_codes[:limit]):
        try:
            df = ak.stock_financial_abstract_ths(symbol=sc, indicator='按年度')
            if df is not None and not df.empty:
                row = df.iloc[0]
                eps_val = row.get('基本每股收益', None)
                bps_val = row.get('每股净资产', None)
                roe_val = row.get('净资产收益率', None)
                gpm_val = row.get('毛利率', None)
                entry = {}
                if eps_val is not None and str(eps_val) not in ('False', 'None', ''):
                    try: entry['eps'] = float(eps_val)
                    except: pass
                if bps_val is not None and str(bps_val) not in ('False', 'None', ''):
                    try: entry['bps'] = float(bps_val)
                    except: pass
                if roe_val is not None and str(roe_val) not in ('False', 'None', ''):
                    try: entry['roe'] = float(roe_val)
                    except: pass
                if gpm_val is not None and str(gpm_val) not in ('False', 'None', ''):
                    try: entry['gpm'] = float(gpm_val)
                    except: pass
                if entry:
                    result[sc] = entry
        except Exception:
            pass
        if (i + 1) % 50 == 0:
            logger.info(f"  进度: {i+1}/{limit}")
            _time.sleep(0.5)
    logger.info(f"  THS财务: {len(result)}只有数据")
    return result


# ==================== 第7步: Tushare Pro可转债日行情 ====================

def fetch_tushare_cb_daily(trade_date: Optional[str] = None,
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> pd.DataFrame:
    """Tushare Pro可转债日行情 - bond_value/ytm"""
    try:
        from app.config import settings
        token = settings.TUSHARE_TOKEN
        if not token:
            return pd.DataFrame()
    except Exception:
        token = os.environ.get('LH_TUSHARE_TOKEN', '')
        if not token:
            return pd.DataFrame()
    try:
        import tushare as ts
        pro = ts.pro_api(token)
        fields = 'ts_code,trade_date,close,bond_value,cb_value,bond_over_rate,cb_over_rate,vol,amount'
        df = pro.cb_daily(trade_date=trade_date, start_date=start_date, end_date=end_date, fields=fields)
        if df is not None and not df.empty:
            df['code'] = df['ts_code'].str.extract(r'(\d{6})')
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            logger.info(f"  Tushare cb_daily: {len(df)}条, {df['code'].nunique()}只")
            return df
    except Exception as e:
        logger.warning(f"  Tushare cb_daily: {e}")
    return pd.DataFrame()


# ==================== 主流程 ====================

def main(start_date: date, end_date: date, use_tushare: bool = True):
    t0_total = _time.time()
    logger.info("=" * 60)
    logger.info(f"璇玑历史数据下载: {start_date} ~ {end_date}")
    logger.info(f"数据库: {DB_PATH}")
    conn = duckdb.connect(DB_PATH)
    _init_db(conn)

    # 第1步: THS转债主列表
    bond_info = fetch_bond_list_ths()
    if not bond_info:
        logger.error("无法获取可转债主列表!")
        return

    # 补充Tushare数据 (coupon_rate, add_rate等)
    if use_tushare:
        tushare_info = fetch_bond_list_tushare()
        if tushare_info:
            for code, info in tushare_info.items():
                if code in bond_info:
                    bond_info[code].update({
                        k: v for k, v in info.items()
                        if k in ('coupon_rate', 'add_rate', 'issue_size', 'remain_size',
                                 'list_date', 'delist_date')
                    })

    bond_codes = list(bond_info.keys())

    # 第2步: Jisilu数据
    jisilu = fetch_jisilu_data()

    # 第3步: 腾讯K线 (可转债)
    df_bond_kline = download_bond_kline_tx(bond_codes, start_date, end_date)

    # 第4步: 正股K线 (BaoStock)
    unique_stocks = sorted(set(
        info.get("stock_code", "") for info in bond_info.values()
        if info.get("stock_code") and len(info["stock_code"]) == 6
    ))
    stock_kline = download_stock_kline_baostock(unique_stocks, start_date, end_date)

    # 第5步: PE/PB估值
    stock_valuation = {}
    if unique_stocks:
        stock_valuation = fetch_baidu_valuation(unique_stocks)

    # 第6步: THS财务
    ths_fin = fetch_ths_financial(unique_stocks)

    # 第7步: Tushare Pro cb_daily (bond_value)
    tushare_hist = pd.DataFrame()
    if use_tushare:
        tushare_hist = fetch_tushare_cb_daily(
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d")
        )

    # ============ 合并构建 ============
    logger.info("[合并] 构建完整数据集...")

    # 正股K线: {stock_code: {date: record}}
    # 转为 {date: {stock_code: close_price}} 便于查询
    stock_price_by_date: dict[date, dict[str, float]] = {}
    for sc, date_records in stock_kline.items():
        for dt, rec in date_records.items():
            if dt not in stock_price_by_date:
                stock_price_by_date[dt] = {}
            stock_price_by_date[dt][sc] = rec["close_price"]

    stock_price_by_code: dict[str, dict[date, float]] = {}
    for sc, date_records in stock_kline.items():
        stock_price_by_code[sc] = {}
        for dt, rec in date_records.items():
            stock_price_by_code[sc][dt] = rec["close_price"]

    # 构建行: 用腾讯K线作为骨架, 再补全因子
    if df_bond_kline.empty:
        logger.error("腾讯K线为空, 无法构建!")
        conn.close()
        return

    all_rows = []
    for _, row in df_bond_kline.iterrows():
        code = row["code"]
        dt = row["date"]
        bi = bond_info.get(code, {})

        bond_row = {
            "code": code,
            "name": bi.get("name", ""),
            "snapshot_date": dt,
            "date": dt,
            "close_price": float(row["close_price"]),
            "open_price": float(row["open_price"]),
            "high_price": float(row["high_price"]),
            "low_price": float(row["low_price"]),
            "volume": float(row.get("volume", 0) or 0),
            "price": float(row["close_price"]),
            "stock_code": bi.get("stock_code", ""),
            "conversion_price": float(bi.get("conversion_price", 0) or 0),
            "coupon_rate": float(bi.get("coupon_rate", 0) or 0),
            "add_rate": float(bi.get("add_rate", 0) or 0),
            "outstanding_scale": float(bi.get("remain_size", bi.get("issue_size", 0)) or 0),
        }

        # 从BaoStock正股K线计算conversion_value
        sc = bi.get("stock_code", "")
        cp = float(bi.get("conversion_price", 0) or 0)
        if sc and cp > 0:
            sp = stock_price_by_code.get(sc, {}).get(dt, None)
            if sp and sp > 0:
                bond_row["stock_price"] = sp
                bond_row["conversion_value"] = round(sp / cp * 100, 2)
                # 溢价率
                bp = float(row["close_price"])
                cv = bond_row["conversion_value"]
                if bp > 0 and cv > 0:
                    bond_row["premium_ratio"] = round((bp / cv - 1) * 100, 2)
                bond_row["change_pct"] = float(row.get("change_pct", 0) or 0)

        # 用Jisilu补全
        jd = jisilu.get(code, {})
        if bond_row.get("premium_ratio") is None and jd.get("premium_ratio"):
            bond_row["premium_ratio"] = float(jd["premium_ratio"])
        if jd.get("dual_low"):
            bond_row["dual_low"] = float(jd["dual_low"])
        if jd.get("rating"):
            bond_row["rating"] = jd["rating"]
        bond_row["ytm"] = float(jd.get("ytm", 0) or 0)

        # PE/PB
        if sc and sc in stock_valuation:
            sv = stock_valuation[sc]
            if sv.get("pe"):
                bond_row["pe"] = float(sv["pe"])
            if sv.get("pb"):
                bond_row["pb"] = float(sv["pb"])

        # THS财务
        if sc and sc in ths_fin:
            tf = ths_fin[sc]
            if tf.get("roe"):
                bond_row["roe"] = float(tf["roe"])
            if tf.get("gpm"):
                bond_row["gpm"] = float(tf["gpm"])

        # 剩余年限
        mat_date = bi.get("maturity_date")
        if mat_date and isinstance(mat_date, date) and mat_date > dt:
            bond_row["remaining_years"] = max(0.1, round((mat_date - dt).days / 365, 2))
        else:
            bond_row["remaining_years"] = 3.0

        # 纯债价值 (从coupon_rate + add_rate估算)
        cr = float(bi.get("coupon_rate", 0) or 0)
        ar = float(bi.get("add_rate", 0) or 0)
        ry = bond_row["remaining_years"]
        if cr > 0 and ry > 0:
            # 贴现率: 取3.5% (参考3年期国债收益率)
            bond_row["bond_value"] = _compute_bond_value(100, cr, ar, ry, discount_rate=0.035)
            # 如果Tushare有直接bond_value, 优先使用
            if not tushare_hist.empty:
                ts_mask = (tushare_hist["code"] == code) & (tushare_hist["trade_date"] == dt)
                ts_row = tushare_hist[ts_mask]
                if not ts_row.empty and pd.notna(ts_row["bond_value"].iloc[0]):
                    bond_row["bond_value"] = float(ts_row["bond_value"].iloc[0])

        # 双低
        if bond_row.get("dual_low") is None:
            pr = bond_row.get("premium_ratio")
            bp = bond_row.get("price", bond_row.get("close_price", 0))
            if pr is not None and bp > 0:
                bond_row["dual_low"] = bp + pr

        # 默认值
        if bond_row.get("premium_ratio") is None:
            bond_row["premium_ratio"] = 15.0
        if bond_row.get("change_pct") is None:
            bond_row["change_pct"] = 0.0
        if bond_row.get("volume") is None or bond_row["volume"] == 0:
            bond_row["volume"] = 100000
        if bond_row.get("ytm") is None:
            bond_row["ytm"] = 1.0

        all_rows.append(bond_row)

    # ============ 计算HV和change_pct ============
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.sort_values(["code", "date"])
        df["change_pct"] = df.groupby("code")["close_price"].transform(
            lambda x: x.pct_change() * 100
        ).fillna(0)

        # HV: 20日滚动窗口
        df["hv"] = df.groupby("code")["change_pct"].transform(
            lambda x: x.rolling(20, min_periods=5).std() * np.sqrt(252) * 100
        )
        hv_median = df["hv"].median()
        if pd.isna(hv_median) or hv_median <= 0:
            hv_median = 20.0
        df["hv"] = df["hv"].fillna(hv_median)
        df.loc[df["hv"] <= 0, "hv"] = hv_median
        df["iv"] = df["hv"]

    # ============ 保存到DuckDB ============
    logger.info(f"[保存] 写入DuckDB...")
    saved_records = []
    for _, r in df.iterrows():
        saved_records.append(r.to_dict())

    saved = _db_save_batch(conn, saved_records)
    conn.commit()

    # 记录下载日志
    try:
        conn.execute("""
            INSERT INTO download_log (date, bond_count, stock_count, duration_seconds)
            VALUES (?, ?, ?, ?)
        """, (date.today(), df['code'].nunique(), len(unique_stocks), round(_time.time() - t0_total, 1)))
        conn.commit()
    except Exception:
        pass

    conn.close()

    elapsed = _time.time() - t0_total
    logger.info("=" * 60)
    logger.info(f"完成! {elapsed:.0f}秒")
    logger.info(f"  - {df['code'].nunique()}只可转债")
    logger.info(f"  - {df['date'].nunique()}个交易日")
    logger.info(f"  - {len(df)}条K线记录")
    logger.info(f"  - 保存到: {DB_PATH}")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="璇玑历史数据下载")
    parser.add_argument("--start", type=str, default="2022-01-01", help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="结束日期 (YYYY-MM-DD, 默认今天)")
    parser.add_argument("--no-tushare", action="store_true", help="不使用Tushare Pro")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()
    main(start, end, use_tushare=not args.no_tushare)