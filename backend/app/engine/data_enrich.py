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
import threading
import time
from pathlib import Path
from typing import Optional

import akshare as ak
import numpy as np

logger = logging.getLogger(__name__)

# 保护所有全局缓存映射的写入（多线程后台刷新 vs 异步 enrich_quotes 读）
_cache_lock = threading.RLock()

_CACHE_DIR = Path(os.environ.get("HOME", ".")) / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_INDUSTRY_CACHE_TTL = 86400 * 7
_SPOT_CACHE_TTL = 300
_FIN_CACHE_TTL = 3600 * 24
_FUND_FLOW_CACHE_TTL = 300
_DEBT_CACHE_TTL = 3600 * 24
_VOL_CACHE_TTL = 3600 * 24
_BUYBACK_CACHE_TTL = 3600 * 12
_MGMT_CACHE_TTL = 3600 * 24

_INDUSTRY_CACHE = _CACHE_DIR / "stock_industry.json"
_SPOT_CACHE = _CACHE_DIR / "stock_spot.json"
_FIN_CACHE = _CACHE_DIR / "stock_fin.json"
_FUND_FLOW_CACHE = _CACHE_DIR / "stock_fund_flow.json"
_DEBT_CACHE = _CACHE_DIR / "stock_debt.json"
_VOL_CACHE = _CACHE_DIR / "stock_volatility.json"
_BUYBACK_CACHE = _CACHE_DIR / "stock_buyback.json"
_MGMT_CACHE = _CACHE_DIR / "stock_mgmt.json"

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
_mgmt_map: dict[str, float] = {}
_mgmt_loaded = False


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

        def _clean(o):
            if isinstance(o, dict):
                return {k: _clean(v) for k, v in o.items()}
            if isinstance(o, float) and o != o:
                return None
            return o

        with open(path, "w") as f:
            json.dump(_clean(data), f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"[DataEnrich] Cache save failed: {e}")


def _fresh(ttl: int, data) -> bool:
    return data is not None and time.time() - data.get("_ts", 0) < ttl


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


def _set_global_map(name: str, new_value):
    """线程安全地设置全局缓存映射"""
    with _cache_lock:
        globals()[name] = new_value


# ==================== 公共读取接口 ====================


def get_industry(stock_code: str) -> Optional[str]:
    return _industry_map.get(stock_code)


def get_stock_spot(stock_code: str) -> dict:
    return _spot_map.get(stock_code, {})


def get_all_stock_change_pct() -> dict[str, float]:
    with _cache_lock:
        snap = dict(_spot_map)
    return {
        code: info.get("change_pct")
        for code, info in snap.items()
        if isinstance(info, dict) and info.get("change_pct") is not None
    }


def get_financial(code: str) -> dict:
    return _fin_map.get(code, {})


def get_fund_flow(code: str) -> dict:
    return _fund_flow_map.get(code, {})


def get_debt_info(stock_code: str) -> dict:
    return _debt_map.get(stock_code, {})


def get_volatility(stock_code: str) -> Optional[float]:
    return _vol_map.get(stock_code)


def get_buyback_amount(stock_code: str) -> Optional[float]:
    return _buyback_map.get(stock_code)


def get_mgmt_buy_price(stock_code: str) -> Optional[float]:
    return _mgmt_map.get(stock_code)


def _inject_spot_data(data: dict[str, dict]):
    if data:
        for code, info in data.items():
            if code in _spot_map and isinstance(_spot_map[code], dict):
                _spot_map[code].update(info)
            else:
                _spot_map[code] = info
        logger.info(f"[DataEnrich] Injected {len(data)} Sina spot records into memory")


# ==================== 缓存加载 ====================


def _load_industry_cache():
    global _industry_map, _industry_loaded
    if _industry_loaded:
        return
    cached = _load_cache(_INDUSTRY_CACHE)
    if _fresh(_INDUSTRY_CACHE_TTL, cached):
        _set_global_map("_industry_map", {k: v for k, v in cached.items() if k != "_ts"})
    _industry_loaded = True


def _load_spot_cache():
    global _spot_map, _spot_loaded
    if _spot_loaded:
        return
    cached = _load_cache(_SPOT_CACHE)
    if cached:
        _set_global_map("_spot_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
        has_pe = any(v.get("pe") is not None for v in _spot_map.values())
        if not has_pe:
            logger.warning("[DataEnrich] Cached spot data has no PE/PB, will fetch fresh")
            _set_global_map("_spot_map", {})
    _spot_loaded = True


def _load_fin_cache():
    global _fin_map, _fin_loaded
    if _fin_loaded:
        return
    cached = _load_cache(_FIN_CACHE)
    if cached:
        _set_global_map("_fin_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
    _fin_loaded = True


def _load_fund_flow_cache():
    global _fund_flow_map, _fund_flow_loaded
    if _fund_flow_loaded:
        return
    cached = _load_cache(_FUND_FLOW_CACHE)
    if cached:
        _set_global_map("_fund_flow_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
    _fund_flow_loaded = True


def _load_debt_cache():
    global _debt_map, _debt_loaded
    if _debt_loaded:
        return
    cached = _load_cache(_DEBT_CACHE)
    if _fresh(_DEBT_CACHE_TTL, cached):
        _set_global_map("_debt_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
    _debt_loaded = True


def _load_vol_cache():
    global _vol_map, _vol_loaded
    if _vol_loaded:
        return
    cached = _load_cache(_VOL_CACHE)
    if _fresh(_VOL_CACHE_TTL, cached):
        _set_global_map("_vol_map", {k: v for k, v in cached.items() if k != "_ts"})
    _vol_loaded = True


def _load_buyback_cache():
    global _buyback_map, _buyback_loaded
    if _buyback_loaded:
        return
    cached = _load_cache(_BUYBACK_CACHE)
    if _fresh(_BUYBACK_CACHE_TTL, cached):
        _set_global_map("_buyback_map", {k: v for k, v in cached.items() if k != "_ts"})
    _buyback_loaded = True


def _load_mgmt_cache():
    global _mgmt_map, _mgmt_loaded
    if _mgmt_loaded:
        return
    cached = _load_cache(_MGMT_CACHE)
    if _fresh(_MGMT_CACHE_TTL, cached):
        _set_global_map("_mgmt_map", {k: v for k, v in cached.items() if k != "_ts"})
    _mgmt_loaded = True


# ==================== 后台刷新 ====================


def _build_industry_cache():
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
        _set_global_map("_industry_map", result)
        _save_cache(_INDUSTRY_CACHE, result)
        logger.info(f"[DataEnrich] Industry built: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Industry build failed: {e}")


def _fill_pe_pb_from_baidu(codes: list[str], pe_map: dict, pb_map: dict):
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _baidu_one(code: str):
            try:
                df_pe = ak.stock_zh_valuation_baidu(symbol=code, indicator="市盈率(TTM)", period="近一年")
                pe_val = None
                if df_pe is not None and len(df_pe) > 0:
                    raw = df_pe["value"].iloc[-1]
                    pe_val = _sf(raw)
                df_pb = ak.stock_zh_valuation_baidu(symbol=code, indicator="市净率", period="近一年")
                pb_val = None
                if df_pb is not None and len(df_pb) > 0:
                    raw = df_pb["value"].iloc[-1]
                    pb_val = _sf(raw)
                return code, pe_val, pb_val
            except Exception:
                return code, None, None

        missing = [c for c in codes if c not in pe_map or c not in pb_map]
        if not missing:
            return
        logger.info(f"[DataEnrich] Baidu: fetching {len(missing)} stocks for PE/PB")
        filled = 0
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(_baidu_one, c) for c in missing]
            for i, future in enumerate(as_completed(futures)):
                code, pe_val, pb_val = future.result()
                if pe_val is not None and code not in pe_map:
                    pe_map[code] = pe_val
                    filled += 1
                if pb_val is not None and code not in pb_map:
                    pb_map[code] = pb_val
                if (i + 1) % 50 == 0:
                    time.sleep(1)
        logger.info(f"[DataEnrich] Baidu: filled {filled} PE, total PE={len(pe_map)}, PB={len(pb_map)}")
    except Exception as e:
        logger.warning(f"[DataEnrich] Baidu PE/PB fallback failed: {e}")


def _fill_pe_pb_from_ths(codes: list[str], pe_map: dict, pb_map: dict, sina_map: dict = None):
    sina_map = sina_map or {}
    try:
        missing = [c for c in codes if c not in pe_map or c not in pb_map]
        if not missing:
            return
        logger.info(f"[DataEnrich] THS: fetching {len(missing)} stocks for EPS/BPS → PE/PB")
        filled = 0
        for i, code in enumerate(missing):
            try:
                df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
                if df is None or len(df) == 0:
                    continue
                for _, r in df.iterrows():
                    eps_raw = r.get("基本每股收益")
                    bps_raw = r.get("每股净资产")
                    if not eps_raw or eps_raw == "False" or not bps_raw or bps_raw == "False":
                        continue
                    eps = _sf(eps_raw)
                    bps = _sf(bps_raw)
                    spot = _spot_map.get(code, {})
                    price = spot.get("price") or _sf(sina_map.get(code, {}).get("price"))
                    if eps and eps > 0 and price and price > 0:
                        if code not in pe_map:
                            pe_map[code] = round(price / eps, 2)
                            filled += 1
                    if bps and bps > 0 and price and price > 0:
                        if code not in pb_map:
                            pb_map[code] = round(price / bps, 2)
                    break
            except Exception:
                continue
            if (i + 1) % 30 == 0:
                time.sleep(1)
        logger.info(f"[DataEnrich] THS: filled {filled} PE, total PE={len(pe_map)}, PB={len(pb_map)}")
    except Exception as e:
        logger.warning(f"[DataEnrich] THS PE/PB fallback failed: {e}")


sina_map_global: dict[str, dict] = {}
_bond_stock_codes: set[str] = set()


def set_bond_stock_codes(codes: list[str]):
    global _bond_stock_codes
    _bond_stock_codes = set(c for c in codes if c)
    logger.info(f"[DataEnrich] Bond stock codes set: {len(_bond_stock_codes)} stocks")


def _ensure_bond_stock_codes():
    global _bond_stock_codes
    if _bond_stock_codes:
        return
    try:
        df = ak.bond_zh_cov_info_ths()
        if df is not None and len(df) > 0:
            col = None
            for c in ["正股代码", "股票代码", "代码"]:
                if c in df.columns:
                    col = c
                    break
            if col:
                codes = set()
                for v in df[col].dropna():
                    s = str(v).strip()
                    if s and s.isdigit() and len(s) == 6 and not s.startswith(("8", "9")):
                        codes.add(s)
                _bond_stock_codes = codes
                logger.info(f"[DataEnrich] Auto-loaded {len(codes)} bond stock codes from THS")
    except Exception as e:
        logger.debug(f"[DataEnrich] Auto-load bond stock codes failed: {e}")


def _refresh_spot_cache():
    try:
        logger.info("[DataEnrich] Refreshing stock spot via Sina + push2.eastmoney.com (PE/PB/turnover)...")
        import requests as _req
        import time as _time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        _headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

        df = ak.stock_zh_a_spot()
        all_codes = []
        sina_map = {}
        for _, r in df.iterrows():
            raw_code = str(r.get("代码", "")).strip()
            if not raw_code or raw_code.startswith("bj"):
                continue
            s_code = raw_code[2:] if (raw_code.startswith("sz") or raw_code.startswith("sh")) else raw_code
            all_codes.append(s_code)
            sina_map[s_code] = {
                "change_pct": _sf(r.get("涨跌幅")),
                "price": _sf(r.get("最新价")),
                "volume": _sf(r.get("成交额")),
            }

        pe_map: dict[str, float] = {}
        pb_map: dict[str, float] = {}
        tr_map: dict[str, float] = {}

        def _fetch_batch(batch: list[str]) -> dict[str, dict]:
            secids = ','.join(
                f"{'1' if c.startswith('6') else '0'}.{c}" for c in batch
            )
            try:
                r = _req.get(
                    'https://push2.eastmoney.com/api/qt/ulist.np/get',
                    params={'fields': 'f12,f9,f23,f8',
                            'secids': secids, 'ut': 'bd1d9ddb04089700cf9c27f6f7426281'},
                    headers=_headers, timeout=15,
                )
                data = r.json()
                result = {}
                if data.get('data') and data['data'].get('diff'):
                    for item in data['data']['diff']:
                        code = item.get('f12', '')
                        if not code:
                            continue
                        result[code] = {
                            'pe': item.get('f9', 0),
                            'pb': item.get('f23', 0),
                            'tr': item.get('f8', 0),
                        }
                return result
            except Exception:
                return {}

        batch_size = 50
        batches = [all_codes[i:i + batch_size] for i in range(0, len(all_codes), batch_size)]
        total_filled = 0
        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, future in enumerate(as_completed([ex.submit(_fetch_batch, b) for b in batches])):
                batch_result = future.result()
                for code, vals in batch_result.items():
                    if vals.get('pe'):
                        pe_map[code] = round(vals['pe'] / 100, 2)
                    if vals.get('pb'):
                        pb_map[code] = round(vals['pb'] / 100, 2)
                    if vals.get('tr'):
                        tr_map[code] = round(vals['tr'] / 100, 2)
                if (i + 1) % 5 == 0:
                    _time.sleep(0.3)

        if len(pe_map) < len(all_codes) * 0.3:
            logger.info(f"[DataEnrich] ulist only got {len(pe_map)}/{len(all_codes)}, trying stock/get fallback")
            def _fetch_single(code: str) -> dict:
                secid = f"{'1' if code.startswith('6') else '0'}.{code}"
                try:
                    r = _req.get(
                        'https://push2.eastmoney.com/api/qt/stock/get',
                        params={'fields': 'f57,f162,f167,f168', 'secid': secid},
                        headers=_headers, timeout=8,
                    )
                    d = r.json().get('data', {})
                    if d:
                        return {code: {
                            'pe': d.get('f162', 0),
                            'pb': d.get('f167', 0),
                            'tr': d.get('f168', 0),
                        }}
                except Exception:
                    pass
                return {}

            missing = [c for c in all_codes if c not in pe_map or c not in pb_map]
            sample = missing[:5]
            sample_ok = 0
            for code in sample:
                res = _fetch_single(code)
                if res:
                    sample_ok += 1
                    for c, vals in res.items():
                        if vals.get('pe'):
                            pe_map[c] = round(vals['pe'] / 100, 2)
                        if vals.get('pb'):
                            pb_map[c] = round(vals['pb'] / 100, 2)
                        if vals.get('tr'):
                            tr_map[c] = round(vals['tr'] / 100, 2)
            if sample_ok == 0:
                logger.info(f"[DataEnrich] stock/get also blocked (0/{len(sample)} sample), skipping individual fallback")
            else:
                logger.info(f"[DataEnrich] Fallback: fetching {len(missing)} stocks individually")
                with ThreadPoolExecutor(max_workers=6) as ex:
                    futures = [ex.submit(_fetch_single, code) for code in missing[5:]]
                    for i, future in enumerate(as_completed(futures)):
                        res = future.result()
                        for code, vals in res.items():
                            if vals.get('pe') and code not in pe_map:
                                pe_map[code] = round(vals['pe'] / 100, 2)
                            if vals.get('pb') and code not in pb_map:
                                pb_map[code] = round(vals['pb'] / 100, 2)
                            if vals.get('tr') and code not in tr_map:
                                tr_map[code] = round(vals['tr'] / 100, 2)
                        if (i + 1) % 30 == 0:
                            _time.sleep(0.5)

        if _bond_stock_codes:
            bond_missing = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
        else:
            _ensure_bond_stock_codes()
            if _bond_stock_codes:
                bond_missing = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
            else:
                bond_missing = [c for c in all_codes if c not in pe_map or c not in pb_map] if len(pe_map) < len(all_codes) * 0.3 else []

        if bond_missing:
            logger.info(f"[DataEnrich] {len(bond_missing)} bond stocks missing PE/PB, trying Baidu fallback")
            _fill_pe_pb_from_baidu(bond_missing, pe_map, pb_map)

        if _bond_stock_codes:
            bond_missing2 = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
        else:
            _ensure_bond_stock_codes()
            if _bond_stock_codes:
                bond_missing2 = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
            else:
                bond_missing2 = [c for c in all_codes if c not in pe_map or c not in pb_map] if len(pe_map) < len(all_codes) * 0.3 else []

        if bond_missing2:
            logger.info(f"[DataEnrich] {len(bond_missing2)} bond stocks still missing PE/PB, trying THS fallback")
            _fill_pe_pb_from_ths(bond_missing2, pe_map, pb_map, sina_map)

        global sina_map_global
        sina_map_global = sina_map

        result = {}
        for code in all_codes:
            sina = sina_map.get(code, {})
            entry = {
                "pe": pe_map.get(code),
                "pb": pb_map.get(code),
                "change_pct": sina.get("change_pct"),
                "price": sina.get("price"),
                "volume": sina.get("volume"),
                "turnover_rate": tr_map.get(code),
            }
            result[code] = entry

        if pe_map and len(pe_map) >= len(all_codes) * 0.1:
            _set_global_map("_spot_map", result)
            _save_cache(_SPOT_CACHE, result)
            logger.info(f"[DataEnrich] Stock spot: {len(result)} stocks, {len(pe_map)} PE, {len(pb_map)} PB, {len(tr_map)} turnover")
        else:
            logger.warning(f"[DataEnrich] Stock spot refresh poor quality ({len(pe_map)} PE / {len(all_codes)} stocks), merging with existing cache")
            if not _spot_map:
                _load_spot_cache()
            with _cache_lock:
                existing = dict(_spot_map) if _spot_map else {}
            merged = {}
            for code in all_codes:
                old = existing.get(code, {})
                new = result.get(code, {})
                merged[code] = {
                    "pe": new.get("pe") if new.get("pe") is not None else old.get("pe"),
                    "pb": new.get("pb") if new.get("pb") is not None else old.get("pb"),
                    "change_pct": new.get("change_pct") if new.get("change_pct") is not None else old.get("change_pct"),
                    "price": new.get("price") if new.get("price") is not None else old.get("price"),
                    "volume": new.get("volume") if new.get("volume") is not None else old.get("volume"),
                    "turnover_rate": new.get("turnover_rate") if new.get("turnover_rate") is not None else old.get("turnover_rate"),
                }
            _set_global_map("_spot_map", merged)
            _save_cache(_SPOT_CACHE, merged)
            merged_pe = sum(1 for v in merged.values() if isinstance(v, dict) and v.get("pe") is not None)
            logger.info(f"[DataEnrich] Stock spot merged: {len(merged)} stocks, {merged_pe} PE (from cache)")
    except Exception as e:
        logger.warning(f"[DataEnrich] Stock spot refresh failed: {e}")
        _load_spot_cache()


def _refresh_fund_flow_cache():
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
            _set_global_map("_fund_flow_map", result)
            _save_cache(_FUND_FLOW_CACHE, result)
            logger.info(f"[DataEnrich] Fund flow: {len(result)} stocks")
            return
        except Exception as e:
            logger.warning(f"[DataEnrich] Fund flow attempt {attempt+1} failed: {e}")
            time.sleep(5 * (attempt + 1))
    if not _fund_flow_map:
        _load_fund_flow_cache()
        if _fund_flow_map:
            logger.warning(f"[DataEnrich] Fund flow: using expired cache ({len(_fund_flow_map)} stocks)")
        else:
            logger.warning("[DataEnrich] Fund flow: trying stock_zh_a_spot_em fallback...")
            _refresh_fund_flow_from_spot_em()


def _refresh_fund_flow_from_spot_em():
    try:
        df = ak.stock_zh_a_spot_em()
        flow_cols = [c for c in df.columns if '主力' in str(c)]
        if not flow_cols:
            logger.warning("[DataEnrich] stock_zh_a_spot_em has no 主力 columns, skipping fund flow fallback")
            return
        net_col = next((c for c in flow_cols if '净流入' in str(c) and '占比' not in str(c)), None)
        pct_col = next((c for c in flow_cols if '占比' in str(c)), None)
        if not net_col:
            logger.warning(f"[DataEnrich] stock_zh_a_spot_em columns: {flow_cols}, no net inflow column found")
            return
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("代码", "")).strip()
            if not code:
                continue
            entry = {"net_main": _sf(r.get(net_col))}
            if pct_col:
                entry["net_main_pct"] = _sf(r.get(pct_col))
            if entry["net_main"] is not None:
                result[code] = entry
        if result:
            _set_global_map("_fund_flow_map", result)
            _save_cache(_FUND_FLOW_CACHE, result)
            logger.info(f"[DataEnrich] Fund flow from spot_em: {len(result)} stocks")
        else:
            logger.warning("[DataEnrich] Fund flow from spot_em: no data extracted")
    except Exception as e:
        logger.warning(f"[DataEnrich] Fund flow spot_em fallback also failed: {e}")


def _refresh_fin_cache():
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

            cur_rev = _sf(r.get("营业总收入-营业总收入"))
            if cur_rev and cur_rev > 0 and code in old_rev:
                try:
                    cagr = (math.pow(cur_rev / old_rev[code], 1.0 / 3.0) - 1) * 100
                    if -100 < cagr < 500:
                        entry["cagr"] = round(cagr, 2)
                except (ValueError, ZeroDivisionError):
                    pass

            result[code] = entry

        _set_global_map("_fin_map", result)
        _save_cache(_FIN_CACHE, result)
        cagr_count = sum(1 for v in result.values() if isinstance(v, dict) and v.get("cagr") is not None)
        logger.info(f"[DataEnrich] Financial: {len(result)} stocks, {cagr_count} with CAGR")
    except Exception as e:
        logger.warning(f"[DataEnrich] Financial refresh failed: {e}", exc_info=True)
        if not _fin_map:
            _load_fin_cache()


def _refresh_debt_cache():
    try:
        logger.info("[DataEnrich] Refreshing debt & current ratio...")
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"
        df = ak.stock_zcfz_em(date=fin_date)
        if df is None or len(df) == 0:
            logger.warning(f"[DataEnrich] zcfz returned empty df for {fin_date}, skipping")
            return
        logger.info(f"[DataEnrich] zcfz fetched {len(df)} rows")
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

            if total_debt > 0 and cash + receivables + inventory >= 0:
                approx_ca = cash + receivables + inventory
                if approx_ca > 0:
                    cr = approx_ca / (total_debt * 0.65)
                    if 0 < cr < 50 and cr == cr:
                        entry["current_ratio"] = round(cr, 2)

        if entry:
            result[code] = entry

        _set_global_map("_debt_map", result)
        _save_cache(_DEBT_CACHE, result)
        dr = sum(1 for v in result.values() if isinstance(v, dict) and "debt_ratio" in v)
        cr = sum(1 for v in result.values() if isinstance(v, dict) and "current_ratio" in v)
        logger.info(f"[DataEnrich] Debt: {len(result)} stocks, {dr} dr, {cr} cr")
    except Exception as e:
        logger.warning(f"[DataEnrich] Debt refresh failed: {e}", exc_info=True)
        if not _debt_map:
            _load_debt_cache()


def _refresh_volatility_cache():
    try:
        logger.info("[DataEnrich] Refreshing stock volatility (top 300)...")
        source = _spot_map if _spot_map else {}
        if not source:
            logger.warning("[DataEnrich] No spot data for volatility calc, skipping")
            return
        sorted_stocks = sorted(
            source.items(),
            key=lambda x: x[1].get("circ_mv", 0) or 0,
            reverse=True,
        )[:300]

        result = dict(_vol_map)
        count = 0
        for code, _ in sorted_stocks:
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
                    logger.info(f"[DataEnrich] Volatility: {count}/300")
                    time.sleep(1)
            except Exception:
                continue

        _set_global_map("_vol_map", result)
        _save_cache(_VOL_CACHE, result)
        logger.info(f"[DataEnrich] Volatility: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Volatility refresh failed: {e}")
        if not _vol_map:
            _load_vol_cache()


def _refresh_buyback_cache():
    try:
        logger.info("[DataEnrich] Refreshing buyback data...")
        df = ak.stock_repurchase_em()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            done = _sf(r.get("已回购金额"))
            plan = _sf(r.get("计划回购金额区间-上限"))
            amount = done if done and done > 0 else plan
            if amount and amount > 0:
                result[code] = round(amount / 1e8, 2)
        _set_global_map("_buyback_map", result)
        _save_cache(_BUYBACK_CACHE, result)
        logger.info(f"[DataEnrich] Buyback: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Buyback refresh failed: {e}")
        if not _buyback_map:
            _load_buyback_cache()


def _refresh_mgmt_cache():
    try:
        logger.info("[DataEnrich] Refreshing mgmt buy price...")
        df = ak.stock_hold_management_detail_cninfo(symbol="增持")
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("证券代码", "")).strip()
            avg_price = _sf(r.get("成交均价"))
            if code and avg_price and avg_price > 0:
                if code not in result or avg_price > result[code]:
                    result[code] = avg_price
        _set_global_map("_mgmt_map", result)
        _save_cache(_MGMT_CACHE, result)
        logger.info(f"[DataEnrich] Mgmt buy price: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[DataEnrich] Mgmt buy price refresh failed: {e}")
        if not _mgmt_map:
            _load_mgmt_cache()


# ==================== enrich 入口 ====================


async def enrich_quotes(bonds: list) -> list:
    if not bonds:
        return bonds

    # 在锁内对所有缓存做一次性快照，避免后台刷新与 enrich 读之间的竞态
    with _cache_lock:
        with _cache_lock:
            spot_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _spot_map.items()}
            industry_snapshot = dict(_industry_map)
            fin_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _fin_map.items()}
            fund_flow_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _fund_flow_map.items()}
            debt_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _debt_map.items()}
        vol_snapshot = _vol_map.copy()
        buyback_snapshot = _buyback_map.copy()
        mgmt_snapshot = _mgmt_map.copy()

    for b in bonds:
        stock_code = getattr(b, "stock_code", "") or ""
        if not stock_code and hasattr(b, "code"):
            stock_code = b.code[2:] if len(b.code) >= 3 else ""

        spot = spot_snapshot.get(stock_code, {})
        if spot:
            if spot.get("pe") is not None:
                b.pe = spot["pe"]
            if spot.get("pb") is not None:
                b.pb = spot["pb"]
            if spot.get("turnover_rate") is not None:
                b.turnover_rate = spot["turnover_rate"]
            if not b.stock_price and spot.get("price"):
                b.stock_price = spot["price"]
            if not b.stock_change_pct and spot.get("change_pct"):
                b.stock_change_pct = spot["change_pct"]

        if b.industry is None:
            industry = industry_snapshot.get(stock_code)
            if industry:
                b.industry = industry

        fin = fin_snapshot.get(stock_code, {})
        if fin.get("roe") is not None:
            b.roe = fin["roe"]
        if fin.get("gpm") is not None:
            b.gpm = fin["gpm"]
        if fin.get("cagr") is not None:
            b.cagr = fin["cagr"]
        if fin.get("industry") and not b.industry:
            b.industry = fin["industry"]

        debt_info = debt_snapshot.get(stock_code, {})
        if debt_info.get("debt_ratio") is not None:
            b.debt_ratio = debt_info["debt_ratio"]
        if debt_info.get("current_ratio") is not None:
            b.current_ratio = debt_info["current_ratio"]

        vol = vol_snapshot.get(stock_code)
        if vol is not None:
            b.iv = vol
            b.iv_source = "hv_proxy"

        buyback = buyback_snapshot.get(stock_code)
        if buyback is not None:
            b.buyback_amount = buyback

        mgmt = mgmt_snapshot.get(stock_code)
        if mgmt is not None:
            b.mgmt_buy_price = mgmt

        flow = fund_flow_snapshot.get(stock_code, {})
        if flow.get("net_main") is not None:
            b.net_capital_flow = flow["net_main"]
        if flow.get("net_main_pct") is not None:
            b.net_capital_flow_pct = flow["net_main_pct"]

    return bonds


async def start_background_refresh():
    loop = asyncio.get_event_loop()

    _load_industry_cache()
    _load_fin_cache()
    _load_fund_flow_cache()
    _load_debt_cache()
    _load_vol_cache()
    _load_buyback_cache()
    _load_mgmt_cache()

    # 后台刷新所有缓存
    for fn in (_build_industry_cache, _refresh_fin_cache, _refresh_fund_flow_cache,
               _refresh_debt_cache, _refresh_buyback_cache, _refresh_mgmt_cache):
        loop.run_in_executor(None, fn)

    # 后台刷新现货行情（~60s），不阻塞启动
    loop.run_in_executor(None, _refresh_spot_cache)

    await asyncio.sleep(30)
    loop.run_in_executor(None, _refresh_volatility_cache)
