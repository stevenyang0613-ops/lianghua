"""
可转债数据增强模块
从多个数据源补充转债的行业/评级/基本面等字段，
单次增量刷新，长时间缓存，失败不阻塞。
"""
import asyncio
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Optional

import akshare as ak
import numpy as np

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.environ.get("HOME", ".")) / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_INDUSTRY_CACHE_TTL = 86400 * 7
_SPOT_CACHE_TTL = 300
_FIN_CACHE_TTL = 3600 * 24
_FUND_FLOW_CACHE_TTL = 300
_DEBT_CACHE_TTL = 3600 * 24
_VOL_CACHE_TTL = 3600 * 24
_BUYBACK_CACHE_TTL = 3600 * 12

_INDUSTRY_CACHE = _CACHE_DIR / "stock_industry.json"
_SPOT_CACHE = _CACHE_DIR / "stock_spot.json"
_FIN_CACHE = _CACHE_DIR / "stock_fin.json"
_FUND_FLOW_CACHE = _CACHE_DIR / "stock_fund_flow.json"
_DEBT_CACHE = _CACHE_DIR / "stock_debt.json"
_VOL_CACHE = _CACHE_DIR / "stock_volatility.json"
_BUYBACK_CACHE = _CACHE_DIR / "stock_buyback.json"

_industry_map: dict[str, str] = {}
_industry_loaded = False
_spot_map: dict[str, dict] = {}
_spot_loaded = False
_fin_map: dict[str, dict] = {}
_fin_loaded = False
_fund_flow_map: dict[str, dict] = {}
_fund_flow_loaded = False
_debt_map: dict[str, dict] = {}
_debt_loaded = False
_vol_map: dict[str, float] = {}
_vol_loaded = False
_buyback_map: dict[str, float] = {}
_buyback_loaded = False


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


def get_all_stock_change_pct() -> dict[str, float]:
    """返回所有缓存的 stock_code -> change_pct 映射 (供正股涨跌幅填充)"""
    global _spot_map
    return {
        code: info.get("change_pct")
        for code, info in _spot_map.items()
        if info.get("change_pct") is not None
    }


def get_financial(code: str) -> dict:
    global _fin_map
    return _fin_map.get(code, {})


def get_fund_flow(code: str) -> dict:
    global _fund_flow_map
    return _fund_flow_map.get(code, {})


def get_debt_info(stock_code: str) -> dict:
    global _debt_map
    return _debt_map.get(stock_code, {})


def get_volatility(stock_code: str) -> Optional[float]:
    global _vol_map
    return _vol_map.get(stock_code)


def get_buyback_amount(stock_code: str) -> Optional[float]:
    global _buyback_map
    return _buyback_map.get(stock_code)


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


def _load_debt_cache():
    global _debt_map, _debt_loaded
    if _debt_loaded:
        return
    cached = _load_cache(_DEBT_CACHE)
    if _fresh(_DEBT_CACHE_TTL, cached):
        _debt_map = cached
    _debt_loaded = True


def _load_vol_cache():
    global _vol_map, _vol_loaded
    if _vol_loaded:
        return
    cached = _load_cache(_VOL_CACHE)
    if _fresh(_VOL_CACHE_TTL, cached):
        _vol_map = {k: v for k, v in cached.items() if k != "_ts"}
    _vol_loaded = True


def _load_buyback_cache():
    global _buyback_map, _buyback_loaded
    if _buyback_loaded:
        return
    cached = _load_cache(_BUYBACK_CACHE)
    if _fresh(_BUYBACK_CACHE_TTL, cached):
        _buyback_map = {k: v for k, v in cached.items() if k != "_ts"}
    _buyback_loaded = True


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
    for attempt in range(3):
        try:
            logger.info(f"[DataEnrich] Refreshing stock spot (PE/PB/turnover) attempt {attempt+1}...")
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
            return
        except Exception as e:
            logger.warning(f"[DataEnrich] Stock spot attempt {attempt+1} failed: {e}")
            time.sleep(5 * (attempt + 1))


def _refresh_fund_flow_cache():
    global _fund_flow_map
    for attempt in range(3):
        try:
            logger.info(f"[DataEnrich] Refreshing fund flow rank attempt {attempt+1}...")
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
            return
        except Exception as e:
            logger.warning(f"[DataEnrich] Fund flow attempt {attempt+1} failed: {e}")
            time.sleep(5 * (attempt + 1))


def _refresh_fin_cache():
    global _fin_map
    try:
        logger.info("[DataEnrich] Refreshing financial data...")
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"
        logger.info(f"[DataEnrich] Using financial date: {fin_date}")
        df = ak.stock_yjbb_em(date=fin_date)

        cagr_date = f"{int(fin_date[:4])-3}{fin_date[4:]}"
        logger.info(f"[DataEnrich] CAGR base date: {cagr_date}")
        df_old = None
        try:
            df_old = ak.stock_yjbb_em(date=cagr_date)
        except Exception as e:
            logger.warning(f"[DataEnrich] CAGR base data fetch failed: {e}")

        old_rev = {}
        if df_old is not None:
            for _, r in df_old.iterrows():
                code = str(r.get("股票代码", "")).strip()
                rev = _sf(r.get("营业总收入-营业总收入"))
                if code and rev and rev > 0:
                    old_rev[code] = rev

        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            entry = {
                "roe": _sf(r.get("净资产收益率")),
                "gpm": _sf(r.get("销售毛利率")),
                "industry": str(r.get("所处行业", "")).strip() or None,
                "eps": _sf(r.get("每股收益")),
                "bps": _sf(r.get("每股净资产")),
                "revenue_yoy": _sf(r.get("营业总收入-同比增长")),
                "profit_yoy": _sf(r.get("净利润-同比增长")),
            }

            cur_rev = _sf(r.get("营业总收入-营业收入"))
            if cur_rev and cur_rev > 0 and code in old_rev:
                try:
                    cagr = (math.pow(cur_rev / old_rev[code], 1.0 / 3.0) - 1) * 100
                    if -100 < cagr < 500:
                        entry["cagr"] = round(cagr, 2)
                except (ValueError, ZeroDivisionError):
                    pass

            result[code] = entry

        _fin_map = result
        _save_cache(_FIN_CACHE, result)
        cagr_count = sum(1 for v in result.values() if v.get("cagr") is not None)
        logger.info(f"[DataEnrich] Financial: {len(result)} stocks, {cagr_count} with CAGR")
    except Exception as e:
        logger.warning(f"[DataEnrich] Financial refresh failed: {e}")


def _sf(v, default=None) -> Optional[float]:
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return default
    try:
        fv = float(v)
        if fv != fv:
            return default
        return fv
    except (ValueError, TypeError):
        return default


def _refresh_debt_cache():
    global _debt_map
    try:
        logger.info("[DataEnrich] Refreshing debt & current ratio...")
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"
        df = ak.stock_zcfz_em(date=fin_date)
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            debt_ratio = _sf(r.get("资产负债率"))
            cash = _sf(r.get("资产-货币资金")) or 0
            receivables = _sf(r.get("资产-应收账款")) or 0
            inventory = _sf(r.get("资产-存货")) or 0
            total_debt = _sf(r.get("负债-总负债")) or 0

            entry = {}
            if debt_ratio is not None:
                entry["debt_ratio"] = debt_ratio

            if total_debt > 0:
                approx_current_assets = cash + receivables + inventory
                approx_current_ratio = approx_current_assets / (total_debt * 0.65)
                if 0 < approx_current_ratio < 50:
                    entry["current_ratio"] = round(approx_current_ratio, 2)

            if entry:
                result[code] = entry

        _debt_map = result
        _save_cache(_DEBT_CACHE, result)
        dr_count = sum(1 for v in result.values() if "debt_ratio" in v)
        cr_count = sum(1 for v in result.values() if "current_ratio" in v)
        logger.info(f"[DataEnrich] Debt: {len(result)} stocks, {dr_count} debt_ratio, {cr_count} current_ratio")
    except Exception as e:
        logger.warning(f"[DataEnrich] Debt refresh failed: {e}")


def _refresh_volatility_cache():
    global _vol_map
    try:
        logger.info("[DataEnrich] Refreshing stock volatility (top 300)...")
        global _spot_map
        sorted_stocks = sorted(
            _spot_map.items(),
            key=lambda x: x[1].get("circ_mv", 0) or 0,
            reverse=True,
        )[:300]

        result = dict(_vol_map)
        count = 0
        for code, info in sorted_stocks:
            if not code:
                continue
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=time.strftime("%Y%m%d", time.localtime(time.time() - 90 * 86400)),
                    end_date=time.strftime("%Y%m%d"),
                    adjust="qfq",
                )
                if len(df) < 20:
                    continue
                closes = df["收盘"].astype(float).values
                returns = np.diff(closes) / closes[:-1]
                vol = float(np.std(returns) * np.sqrt(252) * 100)
                if 0 < vol < 300:
                    result[code] = round(vol, 2)
                count += 1
                if count % 50 == 0:
                    logger.info(f"[DataEnrich] Volatility: {count}/300 stocks")
                    time.sleep(1)
            except Exception:
                continue

        _vol_map = result
        _save_cache(_VOL_CACHE, result)
        logger.info(f"[DataEnrich] Volatility: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Volatility refresh failed: {e}")


def _refresh_buyback_cache():
    global _buyback_map
    try:
        logger.info("[DataEnrich] Refreshing buyback data...")
        df = ak.stock_repurchase_em()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            done_amount = _sf(r.get("已回购金额"))
            plan_upper = _sf(r.get("计划回购金额区间-上限"))
            amount = done_amount if done_amount and done_amount > 0 else plan_upper
            if amount and amount > 0:
                result[code] = round(amount / 1e8, 2)
        _buyback_map = result
        _save_cache(_BUYBACK_CACHE, result)
        logger.info(f"[DataEnrich] Buyback: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Buyback refresh failed: {e}")


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
        if fin.get("gpm") is not None:
            b.gpm = fin["gpm"]
        if fin.get("cagr") is not None:
            b.cagr = fin["cagr"]
        if fin.get("industry") and not b.industry:
            b.industry = fin["industry"]

        debt_info = get_debt_info(stock_code)
        if debt_info.get("debt_ratio") is not None:
            b.debt_ratio = debt_info["debt_ratio"]
        if debt_info.get("current_ratio") is not None:
            b.current_ratio = debt_info["current_ratio"]

        vol = get_volatility(stock_code)
        if vol is not None:
            b.iv = vol

        buyback = get_buyback_amount(stock_code)
        if buyback is not None:
            b.buyback_amount = buyback

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
    _load_debt_cache()
    _load_vol_cache()
    _load_buyback_cache()

    loop.run_in_executor(None, _build_industry_cache)
    loop.run_in_executor(None, _refresh_spot_cache)
    loop.run_in_executor(None, _refresh_fin_cache)
    loop.run_in_executor(None, _refresh_fund_flow_cache)
    loop.run_in_executor(None, _refresh_debt_cache)
    loop.run_in_executor(None, _refresh_buyback_cache)

    await asyncio.sleep(30)
    loop.run_in_executor(None, _refresh_volatility_cache)
