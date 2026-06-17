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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import akshare as ak
import numpy as np
from app.adapters.tdx_adapter import get_tdx_adapter

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

_PLEDGE_CACHE_TTL = 3600 * 24
_MOMENTUM_CACHE_TTL = 86400
_EVENT_CACHE_TTL = 3600 * 24
_CONCEPT_CACHE_TTL = 86400 * 7
_BUYBACK_CACHE_TTL = 86400 * 3
_BOND_OUTSTANDING_CACHE_TTL = 3600 * 24
_CALL_STATUS_CACHE_TTL = 3600 * 24

_INDUSTRY_CACHE = _CACHE_DIR / "stock_industry.json"
_SPOT_CACHE = _CACHE_DIR / "stock_spot.json"
_FIN_CACHE = _CACHE_DIR / "stock_fin.json"
_FUND_FLOW_CACHE = _CACHE_DIR / "stock_fund_flow.json"
_DEBT_CACHE = _CACHE_DIR / "stock_debt.json"
_VOL_CACHE = _CACHE_DIR / "stock_volatility.json"
_BUYBACK_CACHE = _CACHE_DIR / "stock_buyback.json"
_MGMT_CACHE = _CACHE_DIR / "stock_mgmt.json"

_PLEDGE_CACHE = _CACHE_DIR / "stock_pledge.json"
_MOMENTUM_CACHE = _CACHE_DIR / "stock_momentum.json"
_EVENT_CACHE = _CACHE_DIR / "bond_event.json"
_CONCEPT_CACHE = _CACHE_DIR / "stock_concept.json"
_CONCEPT_SOURCE_CACHE = _CACHE_DIR / "stock_concept_source.json"
_BOND_OUTSTANDING_CACHE = _CACHE_DIR / "bond_outstanding.json"
_CALL_STATUS_CACHE = _CACHE_DIR / "bond_call_status.json"
_STOCK_NAME_CACHE = _CACHE_DIR / "stock_names.json"
_BOND_PRICE_CACHE = _CACHE_DIR / "bond_price.json"

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

_pledge_map: dict[str, float] = {}
_pledge_loaded = False
_momentum_map: dict[str, dict] = {}
_momentum_loaded = False
_event_map: dict[str, dict] = {}
_event_loaded = False
_bond_outstanding_map: dict[str, float] = {}
_bond_outstanding_loaded = False
_call_status_map: dict[str, str] = {}
_call_status_loaded = False
_name_map: dict[str, str] = {}
_name_loaded = False
_concept_map: dict[str, list[str]] = {}
_concept_loaded = False
_concept_source_map: dict[str, dict[str, bool]] = {}
_concept_source_loaded = False
_bond_price_map: dict[str, dict] = {}
_bond_price_loaded = False


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
    """线程安全地设置全局缓存映射并记录刷新时间"""
    global _cache_refresh_ts
    with _cache_lock:
        globals()[name] = new_value
        _cache_refresh_ts[name] = time.time()


_cache_refresh_ts: dict[str, float] = {}


def get_cache_refresh_ts() -> dict[str, float]:
    """返回所有数据源的刷新时间戳（用于数据源健康检查页）"""
    with _cache_lock:
        return dict(_cache_refresh_ts)


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

        # [TDX] fallback: 用 TDX 证券列表补充分类
        if len(result) < 500:
            try:
                logger.info('[DataEnrich][TDX] Industry: EM returned <500 stocks, checking TDX security list')
                adapter = get_tdx_adapter()
                tdx_securities = adapter.fetch_all_securities()
                filled = 0
                for code, name in tdx_securities.items():
                    if code not in result and name:
                        result[code] = name[:10]
                        filled += 1
                if filled:
                    _set_global_map('_industry_map', result)
                    _save_cache(_INDUSTRY_CACHE, result)
                    logger.info(f'[DataEnrich][TDX] Industry: added {filled} stocks from TDX names')
            except Exception as tdx_e:
                logger.debug(f'[DataEnrich][TDX] Industry fallback failed: {tdx_e}')
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

        # [TDX] fallback: 用 TDX 行情数据补充缺失的资金流向
        if not _fund_flow_map or len(_fund_flow_map) < 50:
            try:
                ff_codes = list(_bond_stock_codes) if _bond_stock_codes else []
                if not ff_codes:
                    _ensure_bond_stock_codes()
                    ff_codes = list(_bond_stock_codes) if _bond_stock_codes else []
                if ff_codes:
                    adapter = get_tdx_adapter()
                    logger.info(f'[DataEnrich][TDX] Fund flow: fetching TDX spot for {len(ff_codes)} stocks')
                    tdx_q = adapter.fetch_quotes(ff_codes)
                    ff_result = {}
                    for code, q in tdx_q.items():
                        amount = q.get('amount', 0)
                        if amount > 0:
                            ff_result[code] = {'net_main': round(amount * 0.1, 2)}
                    if len(ff_result) > 50:
                        _set_global_map('_fund_flow_map', ff_result)
                        _save_cache(_FUND_FLOW_CACHE, ff_result)
                        logger.info(f'[DataEnrich][TDX] Fund flow: {len(ff_result)} stocks from TDX spot')
                        return
            except Exception as tdx_e:
                logger.debug(f'[DataEnrich][TDX] Fund flow fallback failed: {tdx_e}')



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

        # [TDX] fallback: 用 TDX 补充缺失的财务数据
        fin_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not fin_codes:
            _ensure_bond_stock_codes()
            fin_codes = list(_bond_stock_codes) if _bond_stock_codes else list(result.keys())[:500]
        if fin_codes:
            _try_tdx_fin_fallback(fin_codes, result)

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

        # [TDX] fallback: 用 TDX 资产负债表数据补充缺失的资产负债率
        debt_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not debt_codes:
            _ensure_bond_stock_codes()
            debt_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if debt_codes:
            tdx_missing = [c for c in debt_codes if c not in result or not result.get(c, {}).get('debt_ratio')]
            if tdx_missing:
                adapter = get_tdx_adapter()
                logger.info(f'[DataEnrich][TDX] Debt: fetching balance sheet for {len(tdx_missing)} stocks')
                tdx_fin = adapter.fetch_finance_batch(tdx_missing)
                filled = 0
                for code, info in tdx_fin.items():
                    ta = info.get('total_assets')
                    tl = info.get('total_liabilities')
                    if ta and tl and ta > 0:
                        dr2 = round(tl / ta * 100, 2)
                        if 0 < dr2 < 100:
                            if code not in result:
                                result[code] = {}
                            result[code]['debt_ratio'] = dr2
                            filled += 1
                if filled:
                    dr_total = sum(1 for v in result.values() if isinstance(v, dict) and 'debt_ratio' in v)
                    logger.info(f'[DataEnrich][TDX] Debt: filled debt_ratio for {filled} stocks (total {dr_total} dr)')
    except Exception as e:
        logger.warning(f"[DataEnrich] Debt refresh failed: {e}", exc_info=True)
        if not _debt_map:
            _load_debt_cache()


def _refresh_volatility_cache():
    try:
        logger.info("[DataEnrich] Refreshing stock volatility (top 300 via volume*price proxy)...")
        source = _spot_map if _spot_map else {}
        if not source:
            logger.warning("[DataEnrich] No spot data for volatility calc, skipping")
            return
        # _spot_map entries are {pe, pb, change_pct, price, volume, turnover_rate}
        # Use volume * price as market cap proxy for sorting
        def _mv_proxy(item):
            v = item[1] if isinstance(item[1], dict) else {}
            vol = v.get("volume", 0) or 0
            price = v.get("price", 0) or 0
            return float(vol) * float(price) if price > 0 else 0
        sorted_stocks = sorted(
            source.items(),
            key=_mv_proxy,
            reverse=True,
        )[:300]

        # 只处理与可转债正股相关的股票代码，避免在5000+全A股上浪费时间
        _ensure_bond_stock_codes()
        if _bond_stock_codes:
            sorted_stocks = [(c, s) for c, s in sorted_stocks if c in _bond_stock_codes]
            if not sorted_stocks:
                logger.warning("[DataEnrich] No bond stock codes for volatility, using fallback")
                sorted_stocks = list(source.items())[:300]
        logger.info(f"[DataEnrich] Volatility: {len(sorted_stocks)} bond-related stocks to process")

        result = dict(_vol_map)
        count = 0
        em_fail_count = 0
        for code, _ in sorted_stocks:
            if not code:
                continue
            vol = None
            # 优先: East Money (通过代理)
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=time.strftime("%Y%m%d", time.localtime(time.time() - 90 * 86400)),
                    end_date=time.strftime("%Y%m%d"),
                    adjust="qfq",
                )
                if len(df) >= 20:
                    closes = df["收盘"].astype(float).values
                    returns = np.diff(closes) / closes[:-1]
                    v = float(np.std(returns) * np.sqrt(252) * 100)
                    if 0 < v < 300:
                        vol = v
                else:
                    em_fail_count += 1
            except Exception:
                em_fail_count += 1

            # 后备: Tencent hist (East Money 被封时)
            if vol is None:
                try:
                    df_tx = ak.stock_zh_a_hist_tx(
                        symbol=f"sh{code}" if code.startswith(('6', '9')) else f"sz{code}",
                        start_date=time.strftime("%Y%m%d", time.localtime(time.time() - 90 * 86400)),
                        end_date=time.strftime("%Y%m%d"),
                        adjust="qfq",
                    )
                    if df_tx is not None and len(df_tx) >= 20:
                        # Tencent uses lowercase column names: 'close', 'open', 'high', 'low'
                        closes = df_tx["close"].astype(float).values
                        # Filter rows where close > 0 (some TX rows have negative adjusted values)
                        closes = closes[closes > 0]
                        if len(closes) >= 20:
                            returns = np.diff(closes) / closes[:-1]
                            v = float(np.std(returns) * np.sqrt(252) * 100)
                            if 0 < v < 300:
                                vol = v
                except Exception:
                    pass

            if vol is not None:
                result[code] = round(vol, 2)
            count += 1
            if count % 50 == 0:
                logger.info(f"[DataEnrich] Volatility: {count}/300 (EM fails={em_fail_count})")
                time.sleep(1)

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

        # [TDX] fallback: TDX 不直接提供回购数据，补充正股价格信息
        buyback_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not buyback_codes:
            _ensure_bond_stock_codes()
            buyback_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if buyback_codes:
            tdx_missing = [c for c in buyback_codes if c not in result]
            if tdx_missing:
                adapter = get_tdx_adapter()
                logger.info(f'[DataEnrich][TDX] Buyback: checking {len(tdx_missing)} missing codes')
                tdx_q = adapter.fetch_quotes(tdx_missing)
                price_filled = 0
                for code, q in tdx_q.items():
                    if code not in result and q.get('price', 0) > 0:
                        result[code] = 0
                        price_filled += 1
                if price_filled:
                    logger.info(f'[DataEnrich][TDX] Buyback: price data for {price_filled} stocks (no direct buyback data from TDX)')
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

        # [TDX] fallback: TDX 不直接提供管理层增持数据，补充财务指标
        mgmt_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not mgmt_codes:
            _ensure_bond_stock_codes()
            mgmt_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if mgmt_codes:
            tdx_missing = [c for c in mgmt_codes if c not in result]
            if tdx_missing:
                logger.info(f'[DataEnrich][TDX] Mgmt: checking {len(tdx_missing)} missing codes via TDX fin')
                _try_tdx_fin_fallback(tdx_missing, {})
                logger.info(f'[DataEnrich][TDX] Mgmt: TDX fin check done (TDX has no insider trade data)')

    except Exception as e:
        logger.warning(f"[DataEnrich] Mgmt buy price refresh failed: {e}")
        if not _mgmt_map:
            _load_mgmt_cache()



# ==================== TDX 数据源统一 fallback 辅助函数 ====================

def _try_tdx_fin_fallback(codes: list[str], fin_map: dict):
    """从 TDX 补充缺失的财务数据（ROE/GPM/EPS 等）"""
    if not codes:
        return
    missing = [c for c in codes if c not in fin_map or not fin_map.get(c, {}).get("roe")]
    if not missing:
        return
    adapter = get_tdx_adapter()
    logger.info(f'[DataEnrich][TDX] Fin fallback: fetching financial data for {len(missing)} stocks')
    tdx_fin = adapter.fetch_finance_batch(missing)
    filled = 0
    for code, info in tdx_fin.items():
        if code not in fin_map:
            fin_map[code] = {}
        for key in ("pe", "pb", "roe", "eps", "bps"):
            if info.get(key) is not None and not fin_map[code].get(key):
                fin_map[code][key] = info[key]
                if key == "roe":
                    filled += 1
    if filled:
        logger.info(f'[DataEnrich][TDX] Fin fallback: filled ROE for {filled} stocks')


def _try_tdx_volatility_fallback(codes: list[str], vol_map: dict):
    """从 TDX K-line 补充缺失的波动率数据"""
    if not codes:
        return
    missing = [c for c in codes if c not in vol_map or vol_map.get(c) is None]
    if not missing:
        return
    adapter = get_tdx_adapter()
    logger.info(f'[DataEnrich][TDX] Vol fallback: fetching K-line volatility for {len(missing)} stocks')
    kline_data = adapter.fetch_kline_batch(missing, days=20)
    filled = 0
    for code, klines in kline_data.items():
        closes = [k.get("close") for k in klines if k.get("close") and k["close"] > 0]
        if len(closes) >= 5:
            returns_np = np.diff(closes) / closes[:-1]
            vol_val = float(np.std(returns_np) * np.sqrt(252) * 100) if len(returns_np) > 0 else None
            if vol_val is not None and vol_val > 0 and (code not in vol_map or vol_map.get(code) is None):
                vol_val = max(5, min(200, round(vol_val, 2)))
                vol_map[code] = vol_val
                filled += 1
    if filled:
        logger.info(f'[DataEnrich][TDX] Vol fallback: filled volatility for {filled} stocks')


def _try_tdx_names_fallback(name_map: dict):
    """从 TDX 补充缺失的股票名称"""
    adapter = get_tdx_adapter()
    logger.info('[DataEnrich][TDX] Names fallback: fetching stock names from security list')
    tdx_names = adapter.fetch_all_securities()
    added = 0
    for code, name in tdx_names.items():
        if code not in name_map and name and len(code) == 6 and code.isdigit():
            name_map[code] = name
            added += 1
    if added:
        logger.info(f'[DataEnrich][TDX] Names fallback: added {added} stock names')


def _load_pledge_cache():
    global _pledge_map, _pledge_loaded
    cached = _load_cache(_PLEDGE_CACHE)
    if cached:
        _set_global_map("_pledge_map", {k: v for k, v in cached.items() if k != "_ts"})
    _pledge_loaded = True


def _load_event_cache():
    global _event_map, _event_loaded
    cached = _load_cache(_EVENT_CACHE)
    if cached:
        _set_global_map("_event_map", {k: v for k, v in cached.items() if k != "_ts"})
    _event_loaded = True


def _load_momentum_cache():
    global _momentum_map, _momentum_loaded
    cached = _load_cache(_MOMENTUM_CACHE)
    if cached:
        _set_global_map("_momentum_map", {k: v for k, v in cached.items() if k != "_ts"})
    _momentum_loaded = True


def _load_bond_outstanding_cache():
    global _bond_outstanding_map, _bond_outstanding_loaded
    cached = _load_cache(_BOND_OUTSTANDING_CACHE)
    if cached:
        _set_global_map("_bond_outstanding_map", {k: v for k, v in cached.items() if k != "_ts"})
    _bond_outstanding_loaded = True


def _load_call_status_cache():
    global _call_status_map, _call_status_loaded
    cached = _load_cache(_CALL_STATUS_CACHE)
    if cached:
        _set_global_map("_call_status_map", {k: v for k, v in cached.items() if k != "_ts"})
    _call_status_loaded = True


def _load_stock_name_cache():
    global _name_map, _name_loaded
    cached = _load_cache(_STOCK_NAME_CACHE)
    if cached:
        _set_global_map("_name_map", {k: v for k, v in cached.items() if k != "_ts"})
    _name_loaded = True


def _load_bond_price_cache():
    global _bond_price_map, _bond_price_loaded
    cached = _load_cache(_BOND_PRICE_CACHE)
    if cached:
        _set_global_map("_bond_price_map", {k: v for k, v in cached.items() if k != "_ts"})
    _bond_price_loaded = True


def _load_concept_cache():
    global _concept_map, _concept_loaded, _concept_source_map, _concept_source_loaded
    cached = _load_cache(_CONCEPT_CACHE)
    if cached:
        _set_global_map("_concept_map", {k: v for k, v in cached.items() if k != "_ts"})
    _concept_loaded = True
    cached2 = _load_cache(_CONCEPT_SOURCE_CACHE)
    if cached2:
        _set_global_map("_concept_source_map", {k: v for k, v in cached2.items() if k != "_ts"})
    _concept_source_loaded = True


# 概念名称→搜索关键词映射规则
_CONCEPT_KEYWORD_MAP: dict[str, list[str]] = {
    "AI": ["智能", "AI", "人工", "算法", "深度"],
    "芯片": ["芯片", "半导体", "集成", "微", "晶圆"],
    "新能源": ["新能源", "光伏", "风电", "锂电", "电池", "充电"],
    "汽车": ["汽车", "汽配", "整车", "新能源车", "电动"],
    "医药": ["医药", "药", "医疗", "生物", "基因", "健康"],
    "金融": ["银行", "保险", "证券", "金融", "信托", "期货"],
    "科技": ["科技", "信息", "软件", "数字", "数据", "互联", "计算"],
    "通信": ["通信", "5G", "6G", "光", "星", "卫星"],
    "军工": ["军工", "国防", "航天", "航空", "装备"],
    "消费": ["消费", "食品", "饮料", "酒", "乳", "零售"],
    "地产": ["地产", "房产", "物业", "园区"],
    "电力": ["电力", "能源", "电网", "发电", "电气"],
    "化工": ["化工", "化学", "化纤", "材料", "石化"],
    "金属": ["金属", "有色", "钢铁", "黄金", "矿业", "合金"],
    "传媒": ["传媒", "影视", "游戏", "广告", "文化", "娱乐"],
    "机械": ["机械", "设备", "装备", "精密", "制造"],
    "环保": ["环保", "环境", "节能", "减排", "碳"],
    "农业": ["农业", "牧", "渔", "种", "粮", "林"],
    "建筑": ["建筑", "工程", "建设", "基建", "路桥"],
}


def _extract_concept_keywords(concept_name: str) -> list[str]:
    """从概念名称中提取搜索关键词"""
    keywords = []
    # 检查是否有预定义映射
    for root, kws in _CONCEPT_KEYWORD_MAP.items():
        if root in concept_name:
            keywords.extend(kws)
    # 提取概念名称本身的词
    parts = concept_name.replace('/', ' ').replace('、', ' ').replace('·', ' ').split()
    for part in parts:
        part = part.strip()
        if len(part) >= 2 and part not in keywords:
            keywords.append(part)
    # 去重并限制数量
    seen = set()
    return [k for k in keywords if not (k in seen or seen.add(k))][:5]


def _build_concept_cache():
    """Build concept cache with EM + THS + TDX keyword expansion"""
    # ── 保护：如果现有缓存足够大（已由 patch 脚本合并了 EM+THS），跳过重建 ──
    cached = _load_cache(_CONCEPT_CACHE)
    if cached:
        real = {k: v for k, v in cached.items() if k != '_ts'}
        # 检查概念丰富度：至少有 300 个不同概念名称且最大概念 > 100 只股票
        from collections import defaultdict
        _rev = defaultdict(int)
        for scodes in real.values():
            if isinstance(scodes, list):
                for cn in scodes:
                    _rev[cn] += 1
        total_pairs = sum(len(scodes) for scodes in real.values() if isinstance(scodes, list))
        if len(_rev) >= 300 and (max(_rev.values()) > 100 or total_pairs > 50000):
            logger.info(f'[DataEnrich] Concept cache already has {len(_rev)} concepts ({total_pairs} pairs), skipping rebuild')
            return

    try:
        logger.info('[DataEnrich] Building concept cache (EM + THS + TDX keyword expansion)...')
        result: dict[str, list[str]] = {}
        source_map: dict[str, dict[str, bool]] = {}
        tdx_concept_map: dict[str, list[str]] = {}  # concept_name -> [stock_codes from TDX]

        # Source 1: EastMoney
        try:
            df = ak.stock_board_concept_name_em()
            em_count = 0
            em_concept_names: list[str] = []
            for _, board in df.iterrows():
                bcode = str(board.get('板块代码', '')).strip()
                bname = str(board.get('板块名称', '')).strip()
                if not bcode or not bname:
                    continue
                try:
                    cons = ak.stock_board_concept_cons_em(symbol=bcode)
                    for _, c in cons.iterrows():
                        scode = str(c.get('代码', '')).strip()
                        if scode:
                            result.setdefault(scode, []).append(bname)
                    source_map.setdefault(bname, {'em': False, 'ths': False, 'tdx': False})['em'] = True
                    em_count += 1
                    em_concept_names.append(bname)
                except Exception:
                    continue
            logger.info(f'[DataEnrich] Concept EM: {em_count} boards, {len(result)} stocks')
        except Exception as e:
            logger.warning(f'[DataEnrich] Concept EM failed: {e}')
            em_concept_names = []

        # Source 2: THS
        try:
            df2 = ak.stock_board_concept_name_ths()
            ths_count = 0
            ths_concept_names: list[str] = []
            for _, board in df2.iterrows():
                bcode = str(board.get('代码', '')).strip()
                bname = str(board.get('名称', '')).strip()
                if not bcode or not bname:
                    continue
                try:
                    cons = ak.stock_board_concept_cons_ths(symbol=bcode)
                    for _, c in cons.iterrows():
                        scode = str(c.get('代码', '')).strip()
                        if scode:
                            result.setdefault(scode, []).append(bname)
                    source_map.setdefault(bname, {'em': False, 'ths': False, 'tdx': False})['ths'] = True
                    ths_count += 1
                    ths_concept_names.append(bname)
                except Exception:
                    continue
            logger.info(f'[DataEnrich] Concept THS: {ths_count} boards')
        except Exception as e2:
            logger.warning(f'[DataEnrich] Concept THS failed: {e2}')
            ths_concept_names = []

        # Source 3: TDX keyword expansion — 为每个概念用关键词搜索更多成分股
        try:
            adapter = get_tdx_adapter()
            all_concept_names = set(em_concept_names + ths_concept_names)
            tdx_total_added = 0
            tdx_concepts_filled = 0

            # 获取 TDX 全量证券列表用于名称匹配
            tdx_securities = adapter.fetch_all_securities()
            if tdx_securities:
                logger.info(f'[DataEnrich][TDX] Concept: expanding {len(all_concept_names)} concepts with TDX keyword search')

                for cname in sorted(all_concept_names):
                    keywords = _extract_concept_keywords(cname)
                    if not keywords:
                        continue

                    added_for_concept = 0
                    for kw in keywords:
                        # 从 TDX 证券列表中查找名称包含关键词的股票
                        # 排除指数代码: 399xxx(深证指数), 880xxx(行业指数), 950xxx(债券指数)
                        for code, name in tdx_securities.items():
                            if not code or len(code) != 6 or not code.isdigit():
                                continue
                            if not name:
                                continue
                            if code.startswith(('399', '880', '950')):
                                continue  # 跳过指数
                            if kw.lower() in name.lower():
                                # 检查该股票是否已在概念中
                                if code in result:
                                    if cname not in result[code]:
                                        result[code].append(cname)
                                        added_for_concept += 1
                                else:
                                    result[code] = [cname]
                                    added_for_concept += 1

                    if added_for_concept > 0:
                        source_map.setdefault(cname, {'em': False, 'ths': False, 'tdx': False})['tdx'] = True
                        tdx_total_added += added_for_concept
                        tdx_concepts_filled += 1

                    # 每 10 个概念暂停一下
                    if list(all_concept_names).index(cname) % 10 == 9:
                        import time as _time
                        _time.sleep(0.1)

                if tdx_total_added:
                    logger.info(f'[DataEnrich][TDX] Concept: expanded {tdx_concepts_filled} concepts, added {tdx_total_added} stock-concept pairs')

        except Exception as tdx_e:
            logger.debug(f'[DataEnrich][TDX] Concept keyword expansion failed: {tdx_e}')

        if result:
            _set_global_map('_concept_map', result)
            _save_cache(_CONCEPT_CACHE, result)
            if source_map:
                _set_global_map('_concept_source_map', source_map)
                _save_cache(_CONCEPT_SOURCE_CACHE, source_map)
            # 统计
            concepts_with_tdx = sum(1 for s in source_map.values() if s.get('tdx'))
            logger.info(f'[DataEnrich] Concept total: {len(result)} stocks, {len(source_map)} concepts ({concepts_with_tdx} TDX-expanded)')
    except Exception as e:
        logger.warning(f'[DataEnrich] Concept build failed: {e}')


def _compute_momentum_from_kline(stock_code: str, kline_dir: Path) -> Optional[dict]:
    """从 kline JSON 文件计算多周期动量"""
    try:
        kf = kline_dir / f'{stock_code}.json'
        if not kf.exists():
            return None
        with open(kf) as f:
            data = json.load(f)
        days = data.get('days', [])
        if not isinstance(days, list) or len(days) < 5:
            return None
        closes = [d['close'] for d in days if isinstance(d, dict) and d.get('close', 0) > 0]
        if len(closes) < 5:
            return None
        closes.reverse()
        today = closes[-1]
        if today <= 0:
            return None
        result = {}
        periods = {'5d': 5, '10d': 10, '20d': 20, '60d': 60}
        for label, n in periods.items():
            if len(closes) > n:
                prev = closes[-(n + 1)]
                if prev > 0:
                    result[label] = round((today - prev) / prev * 100, 2)
        return result if result else None
    except Exception:
        return None


def _refresh_momentum_cache():
    """从 kline 文件或 Tencent/TDX K-line 计算多周期动量"""
    try:
        logger.info('[DataEnrich] Refreshing multi-timeframe momentum...')
        result = {}
        kline_dir = _CACHE_DIR / 'kline'
        if kline_dir.exists() and list(kline_dir.iterdir()):
            kline_files = [f.stem for f in kline_dir.iterdir() if f.suffix == '.json']
            for sc in _bond_stock_codes or []:
                mom = _compute_momentum_from_kline(sc, kline_dir)
                if mom:
                    result[sc] = mom
            for sc in kline_files:
                if sc in result:
                    continue
                mom = _compute_momentum_from_kline(sc, kline_dir)
                if mom:
                    result[sc] = mom
        # Fallback: Tencent hist
        if len(result) < 50:
            missing = [c for c in (_bond_stock_codes or []) if c not in result]
            if missing:
                logger.info(f'[DataEnrich] Momentum fallback: computing from Tencent hist for {len(missing)} stocks')
                for code in missing[:200]:
                    try:
                        prefix = 'sh' if code.startswith('6') else 'sz'
                        df = ak.stock_zh_a_hist_tx(symbol=f'{prefix}{code}', adjust='hfwd')
                        if df is None or df.empty:
                            continue
                        closes = df['close'].values.astype(float)
                        closes = closes[closes > 0]
                        if len(closes) < 10:
                            continue
                        today = closes[-1]
                        if today <= 0:
                            continue
                        mom = {}
                        periods = {'5d': 5, '10d': 10, '20d': 20, '60d': 60}
                        for label, n in periods.items():
                            if len(closes) > n:
                                prev = closes[-(n + 1)]
                                if prev > 0:
                                    mom[label] = round((today - prev) / prev * 100, 2)
                        if mom:
                            result[code] = mom
                    except Exception:
                        continue

        # [TDX] fallback: 用 TDX K-line 补充仍缺失的动量
        if _bond_stock_codes:
            missing_mom = [c for c in _bond_stock_codes if c not in result]
            if missing_mom:
                logger.info(f'[DataEnrich][TDX] Momentum: fetching K-line for {len(missing_mom)} stocks')
                adapter = get_tdx_adapter()
                klines = adapter.fetch_kline_batch(missing_mom, days=65)
                for code, kline in klines.items():
                    closes = [k.get('close') for k in kline if k.get('close') and k['close'] > 0]
                    if len(closes) > 5:
                        today = closes[-1]
                        mom = {}
                        periods = {'5d': 5, '10d': 10, '20d': 20, '60d': 60}
                        for label, n in periods.items():
                            if len(closes) > n:
                                prev = closes[-(n + 1)]
                                if prev > 0:
                                    mom[label] = round((today - prev) / prev * 100, 2)
                        if mom:
                            result[code] = mom

        if len(result) > 50:
            _set_global_map('_momentum_map', result)
            _save_cache(_MOMENTUM_CACHE, result)
            logger.info(f'[DataEnrich][TDX] Momentum: {len(result)} stocks (kline+tx+tdx)')
        else:
            logger.warning(f'[DataEnrich] Momentum: only {len(result)} stocks, kept existing')
            _load_momentum_cache()
    except Exception as e:
        logger.warning(f'[DataEnrich] Momentum refresh failed: {e}')
        if not _momentum_map:
            _load_momentum_cache()


def _refresh_event_cache():
    """从 THS + TDX 补充债券到期事件"""
    try:
        logger.info('[DataEnrich] Refreshing bond event data...')
        result = {}
        now_ts = datetime.now()

        # Primary: THS bond info
        try:
            df = ak.bond_zh_cov_info_ths()
            for _, r in df.iterrows():
                bc = str(r.get('债券代码', '')).strip()
                if not bc or len(bc) != 6:
                    continue
                score = 0.5
                title = '正常'
                et = r.get('到期时间')
                if et and str(et) not in ('', 'NaT', 'None', 'nan'):
                    try:
                        mdt = datetime.strptime(str(et)[:10], '%Y-%m-%d')
                        days = (mdt - now_ts).days
                        if days < 30:
                            score = 0.95
                            title = f'即将到期 ({days}天)'
                        elif days < 90:
                            score = 0.85
                            title = f'临近到期 ({days}天)'
                        elif days < 180:
                            score = 0.7
                            title = f'半年内到期 ({days}天)'
                        else:
                            score = 0.4
                            title = f'正常 (剩余{days}天)'
                    except Exception:
                        pass
                result[bc] = {'score': score, 'title': title, 'date': now_ts.strftime('%Y%m%d')}
            if len(result) > 100:
                _set_global_map('_event_map', result)
                _save_cache(_EVENT_CACHE, result)
                logger.info(f'[DataEnrich] Event: {len(result)} bonds (from THS)')
            else:
                raise ValueError(f'THS only returned {len(result)} bonds')
        except Exception as e:
            logger.warning(f'[DataEnrich] THS event failed: {e}')

            # [TDX] fallback: 从 TDX 补充债券代码
            if len(result) < 100:
                try:
                    logger.info('[DataEnrich][TDX] Event: checking TDX for bond codes')
                    adapter = get_tdx_adapter()
                    tdx_bonds = adapter.fetch_securities_by_name('转债')
                    for b in tdx_bonds:
                        bc = b.get('code', '')
                        if bc and len(bc) == 6 and bc not in result:
                            result[bc] = {
                                'score': 0.5,
                                'title': '[TDX] 正常 (无到期信息)',
                                'date': now_ts.strftime('%Y%m%d'),
                            }
                    if result:
                        _set_global_map('_event_map', result)
                        if len(result) > 50:
                            _save_cache(_EVENT_CACHE, result)
                        logger.info(f'[DataEnrich][TDX] Event: {len(result)} bonds (incl. TDX fills)')
                except Exception as tdx_e:
                    logger.debug(f'[DataEnrich][TDX] Event fallback failed: {tdx_e}')

        if not result:
            _load_event_cache()
            result = dict(_event_map) if _event_map else {}
    except Exception as e:
        logger.warning(f'[DataEnrich] Event refresh failed: {e}')
        if not _event_map:
            _load_event_cache()


def _refresh_pledge_cache():
    """刷新质押比例 — EM + CNINFO + [TDX] fin fallback"""
    try:
        logger.info('[DataEnrich] Refreshing pledge ratio...')
        df = ak.stock_gpzy_pledge_ratio_em()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get('股票代码', '')).strip()
            ratio = _sf(r.get('质押比例'))
            if code and ratio is not None:
                result[code] = ratio
        if len(result) > 100:
            _set_global_map('_pledge_map', result)
            _save_cache(_PLEDGE_CACHE, result)
            logger.info(f'[DataEnrich] Pledge: {len(result)} stocks (from EM)')
            return
        logger.warning(f'[DataEnrich] Pledge EM: only {len(result)} stocks, trying CNINFO fallback...')
    except Exception as e:
        logger.warning(f'[DataEnrich] Pledge EM failed: {e}')

    # CNINFO fallback
    try:
        df2 = ak.stock_cg_equity_mortgage_cninfo()
        result2 = {}
        if df2 is not None and len(df2) > 0:
            for _, r in df2.iterrows():
                code = str(r.get('证券代码', '')).strip()
                ratio = _sf(r.get('质押比例')) or _sf(r.get('质押股数'))
                if code and ratio is not None:
                    if code not in result2 or ratio > result2[code]:
                        result2[code] = ratio
            if len(result2) > 100:
                _set_global_map('_pledge_map', result2)
                _save_cache(_PLEDGE_CACHE, result2)
                logger.info(f'[DataEnrich] Pledge: {len(result2)} stocks (from CNINFO)')
                return
    except Exception as e2:
        logger.warning(f'[DataEnrich] Pledge CNINFO failed: {e2}')

    # [TDX] fallback: 补充财务指标（TDX 无质押数据）
    try:
        tdx_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not tdx_codes:
            _ensure_bond_stock_codes()
            tdx_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if tdx_codes:
            tdx_missing = [c for c in tdx_codes if c not in _pledge_map]
            if tdx_missing:
                logger.info(f'[DataEnrich][TDX] Pledge: checking {len(tdx_missing)} missing codes via TDX fin')
                _try_tdx_fin_fallback(tdx_missing, {})
                logger.info(f'[DataEnrich][TDX] Pledge: TDX fin check done (TDX has no pledge ratio data)')
    except Exception as tdx_e:
        logger.debug(f'[DataEnrich][TDX] Pledge fallback failed: {tdx_e}')

    if not _pledge_map:
        _load_pledge_cache()


def _refresh_bond_outstanding_cache():
    """刷新债券剩余规模 — JSL + bond_zh_cov + [TDX]"""
    try:
        logger.info('[DataEnrich] Refreshing bond outstanding scale...')
        df = ak.bond_cb_redeem_jsl()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get('代码', '')).strip()
            remaining = float(r.get('剩余规模', 0) or 0)
            if code and remaining > 0:
                result[code] = remaining
        if result:
            logger.info(f'[DataEnrich] Bond outstanding: {len(result)} bonds from JSL')
        else:
            logger.warning('[DataEnrich] Bond outstanding: JSL empty')

        # bond_zh_cov fallback
        try:
            df2 = ak.bond_zh_cov()
            if df2 is not None and not df2.empty:
                count_added = 0
                for _, r in df2.iterrows():
                    code = str(r.get('债券代码', '')).strip()
                    if not code or code in result:
                        continue
                    issue_scale = float(r.get('发行规模', 0) or 0)
                    if issue_scale > 0:
                        result[code] = round(issue_scale, 2)
                        count_added += 1
                logger.info(f'[DataEnrich] Bond outstanding: added {count_added} via bond_zh_cov')
        except Exception as e2:
            logger.warning(f'[DataEnrich] bond_zh_cov fallback failed: {e2}')

        # [TDX] fallback: 用 TDX 确认债券存在性
        if len(result) < 100:
            try:
                adapter = get_tdx_adapter()
                tdx_bonds = adapter.fetch_securities_by_name('转债')
                logger.info(f'[DataEnrich][TDX] Bond outstanding: found {len(tdx_bonds)} bonds from TDX')
                for b in tdx_bonds:
                    bc = b.get('code', '')
                    if bc and len(bc) == 6 and bc not in result:
                        result[bc] = 0.0
                logger.info(f'[DataEnrich][TDX] Bond outstanding: total {len(result)} bonds after TDX check')
            except Exception as tdx_e:
                logger.debug(f'[DataEnrich][TDX] Bond outstanding fallback failed: {tdx_e}')

        if result:
            _set_global_map('_bond_outstanding_map', result)
            _save_cache(_BOND_OUTSTANDING_CACHE, result)
            logger.info(f'[DataEnrich] Bond outstanding: total {len(result)} bonds')
        else:
            logger.warning('[DataEnrich] Bond outstanding: all sources empty')
            if not _bond_outstanding_map:
                _load_bond_outstanding_cache()
    except Exception as e:
        logger.warning(f'[DataEnrich] Bond outstanding refresh failed: {e}')
        if not _bond_outstanding_map:
            _load_bond_outstanding_cache()


def _refresh_call_status_cache():
    """刷新强赎状态 — JSL + [TDX]"""
    try:
        logger.info('[DataEnrich] Refreshing call status from JSL...')
        df = ak.bond_cb_redeem_jsl()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get('代码', '')).strip()
            status = str(r.get('强赎状态', '')).strip()
            if code and status and status != '':
                result[code] = status
        if result:
            logger.info(f'[DataEnrich] Call status: {len(result)} bonds from JSL')
        else:
            logger.warning('[DataEnrich] Call status: empty JSL result')

        # [TDX] fallback: JSL 数据不足时补充
        if len(result) < 50:
            try:
                logger.info('[DataEnrich][TDX] Call status: JSL returned <50 bonds, checking TDX')
                adapter = get_tdx_adapter()
                tdx_bonds = adapter.fetch_securities_by_name('转债')
                for b in tdx_bonds:
                    bc = b.get('code', '')
                    if bc and len(bc) == 6 and bc not in result:
                        result[bc] = '未公告'
                if len(result) > 0:
                    logger.info(f'[DataEnrich][TDX] Call status: {len(result)} bonds (incl. TDX fills)')
            except Exception as tdx_e:
                logger.debug(f'[DataEnrich][TDX] Call status fallback failed: {tdx_e}')

        if result:
            _set_global_map('_call_status_map', result)
            _save_cache(_CALL_STATUS_CACHE, result)
            logger.info(f'[DataEnrich] Call status: {len(result)} bonds')
        else:
            if not _call_status_map:
                _load_call_status_cache()
    except Exception as e:
        logger.warning(f'[DataEnrich] Call status refresh failed: {e}')
        if not _call_status_map:
            _load_call_status_cache()


def _refresh_stock_name_cache():
    """刷新正股名称缓存 — Sina + THS + [TDX]"""
    try:
        logger.info('[DataEnrich] Refreshing stock names...')
        df = ak.stock_info_a_code_name()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get('code', '')).strip().zfill(6)
            name = str(r.get('name', '')).strip()
            if code and name:
                result[code] = name
        # THS supplement
        try:
            df_ths = ak.bond_zh_cov_info_ths()
            if df_ths is not None and not df_ths.empty:
                for _, r in df_ths.iterrows():
                    sc = str(r.get('正股代码', '')).strip()
                    sn = str(r.get('正股简称', '')).strip()
                    if sc and sn and sc not in result:
                        result[sc] = sn
        except Exception:
            pass
        # [TDX] fallback: 用 TDX 补充缺失名称
        _try_tdx_names_fallback(result)

        if len(result) > 100:
            _set_global_map('_name_map', result)
            _save_cache(_STOCK_NAME_CACHE, result)
            logger.info(f'[DataEnrich][TDX] Stock names: {len(result)} stocks')
        else:
            raise ValueError(f'Only {len(result)} names')
    except Exception as e:
        logger.warning(f'[DataEnrich] Stock name refresh failed: {e}')
        if not _name_map:
            _load_stock_name_cache()


# ==================== 全局状态 ====================

async def enrich_quotes(bonds: list) -> list:
    if not bonds:
        return bonds

    # 快照所有缓存（不使用锁——dict.copy() <1ms，异步函数内持同步锁可能死锁）
    spot_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _spot_map.items()}
    industry_snapshot = dict(_industry_map)
    fin_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _fin_map.items()}
    fund_flow_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _fund_flow_map.items()}
    debt_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _debt_map.items()}
    momentum_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _momentum_map.items()}
    event_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _event_map.items()}
    bond_outstanding_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _bond_outstanding_map.items()}
    call_status_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _call_status_map.items()}
    name_snapshot = dict(_name_map)
    concept_snapshot = {k: list(v) if isinstance(v, list) else v for k, v in _concept_map.items()}
    pledge_snapshot = dict(_pledge_map)
    vol_snapshot = _vol_map.copy()
    buyback_snapshot = _buyback_map.copy()
    mgmt_snapshot = _mgmt_map.copy()
    bond_price_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _bond_price_map.items()}
    north_snapshot = dict(_north_map)
    margin_snapshot = {k: v.copy() if isinstance(v, dict) else v for k, v in _margin_map.items()}
    lhb_snapshot = dict(_lhb_map)
    block_trade_snapshot = dict(_block_trade_map)
    holder_num_snapshot = dict(_holder_num_map)
    earnings_forecast_snapshot = dict(_earnings_forecast_map)
    restricted_release_snapshot = dict(_restricted_release_map)

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
        if flow.get("net_super") is not None:
            b.net_super_flow = flow["net_super"]
        if flow.get("net_big") is not None:
            b.net_big_flow = flow["net_big"]

        # [TDX] Concept enrichment
        stock_concepts = concept_snapshot.get(stock_code)
        if stock_concepts:
            seen = set()
            unique = []
            for c in stock_concepts:
                if c not in seen:
                    seen.add(c)
                    unique.append(c)
            b.concepts = unique[:8]

        # Momentum enrichment
        mom = momentum_snapshot.get(stock_code, {})
        if mom:
            if mom.get("5d") is not None:
                b.momentum_5d = mom["5d"]
            if mom.get("10d") is not None:
                b.momentum_10d = mom["10d"]
            if mom.get("20d") is not None:
                b.momentum_20d = mom["20d"]
            if mom.get("60d") is not None:
                b.momentum_60d = mom["60d"]

        # Event enrichment
        evt = event_snapshot.get(b.code, {})
        if evt:
            if evt.get("score") is not None:
                b.event_score = evt["score"]
            if evt.get("title"):
                b.event_detail = evt["title"]

        # Outstanding scale from bond_outstanding map
        bond_outstanding = bond_outstanding_snapshot.get(b.code)
        if bond_outstanding is not None:
            b.outstanding_scale = bond_outstanding

        # Call status
        call_status_val = call_status_snapshot.get(b.code)
        if call_status_val:
            b.call_status = call_status_val

        # Pledge ratio from pledge map
        pledge = pledge_snapshot.get(stock_code)
        if pledge is not None:
            b.pledge_ratio = pledge

        # Stock name from name map
        if not b.stock_name:
            sn = name_snapshot.get(stock_code)
            if sn:
                b.stock_name = sn

        # ── 集思录(JISILU)债券价格数据 enrichment ──
        bp = bond_price_snapshot.get(b.code, {})
        if bp:
            if bp.get("price") is not None and bp.get("price", 0) > 0:
                b.price = bp["price"]
            if bp.get("change_pct") is not None:
                b.change_pct = bp["change_pct"]
            if bp.get("stock_price") is not None and (not b.stock_price or b.stock_price == 0):
                b.stock_price = bp["stock_price"]
            if bp.get("stock_change_pct") is not None and (not b.stock_change_pct or b.stock_change_pct == 0):
                b.stock_change_pct = bp["stock_change_pct"]
            if bp.get("conversion_price") is not None and bp.get("conversion_price", 0) > 0:
                b.conversion_price = bp["conversion_price"]
            if bp.get("conversion_value") is not None and bp.get("conversion_value", 0) > 0:
                b.conversion_value = bp["conversion_value"]
            if bp.get("premium_ratio") is not None:
                b.premium_ratio = bp["premium_ratio"]
            if bp.get("dual_low") is not None and bp.get("dual_low", 0) > 0:
                b.dual_low = bp["dual_low"]
            if bp.get("ytm") is not None:
                b.ytm = bp["ytm"]
            if bp.get("volume") is not None and bp.get("volume", 0) > 0:
                b.volume = bp["volume"]
            if bp.get("turnover_rate") is not None and bp.get("turnover_rate", 0) > 0:
                b.turnover_rate = bp["turnover_rate"]
            if bp.get("outstanding_scale") is not None and bp.get("outstanding_scale", 0) > 0:
                b.outstanding_scale = bp["outstanding_scale"]
            if bp.get("bond_rating"):
                b.rating = bp["bond_rating"]
            if bp.get("remaining_years") is not None and bp.get("remaining_years", 0) > 0:
                b.remaining_years = bp["remaining_years"]
            if bp.get("stock_pb") is not None and (not b.pb or b.pb == 0):
                b.pb = bp["stock_pb"]
            if bp.get("stock_pe") is not None and (not b.pe or b.pe == 0):
                b.pe = bp["stock_pe"]
            if bp.get("maturity_date"):
                b.maturity_date = bp["maturity_date"]

        # North-bound capital enrichment
        north = north_snapshot.get(stock_code)
        if north is not None:
            if isinstance(north, dict):
                b.north_net = north.get("hold_shares") or north.get("add_shares") or north.get("hold_market_cap")
            else:
                b.north_net = north

        # Margin trading enrichment
        margin = margin_snapshot.get(stock_code, {})
        if margin:
            if isinstance(margin, dict):
                val = margin.get("rzye")
                if val is not None:
                    b.margin_balance = round(val / 1e8, 2) if val > 1e6 else val
            else:
                b.margin_balance = margin

        # Long-Hu-Bang enrichment
        lhb = lhb_snapshot.get(stock_code)
        if lhb is not None:
            if isinstance(lhb, dict):
                b.lhb_count = lhb.get("times", 1)
            else:
                b.lhb_count = lhb

        # Block trade enrichment
        bt = block_trade_snapshot.get(stock_code)
        if bt is not None:
            if isinstance(bt, dict):
                b.block_trade_amount = bt.get("total_amt")
            else:
                b.block_trade_amount = bt

        # Holder number change enrichment
        hn = holder_num_snapshot.get(stock_code)
        if hn is not None:
            if isinstance(hn, dict):
                b.holder_num_change = hn.get("change_pct")
            else:
                b.holder_num_change = hn

        # Earnings forecast enrichment
        ef = earnings_forecast_snapshot.get(stock_code)
        if ef is not None:
            if isinstance(ef, dict):
                b.eps_forecast = ef.get("predict_value")
            else:
                b.eps_forecast = ef

        # Restricted release enrichment
        rr = restricted_release_snapshot.get(stock_code)
        if rr is not None:
            if isinstance(rr, dict):
                b.restricted_release_amount = rr.get("amount") or rr.get("release_amount")
            else:
                b.restricted_release_amount = rr

    return bonds


async def start_background_refresh():
    """异步加载 + 刷新后台数据缓存。

    ⚠️ 必须以 `await start_background_refresh()` 方式调用,否则 Python 会发出
    RuntimeWarning: coroutine 'start_background_refresh' was never awaited
    (见 AGENTS.md Rule 关于异步语义的说明)。

    防御: 在进入函数体后立刻断言当前上下文确实是 await,确保任何遗漏 await
    的调用方在第一时间收到 AttributeError 而不是静默警告。
    """
    # 防御性 guard: 阻止任何遗漏 await 的调用方被 GC 后再以 RuntimeWarning 形式
    # 暴露 (后者经常在解释器退出/事件循环 teardown 时才打印,不易定位)。
    if not asyncio.iscoroutinefunction(start_background_refresh):
        # 这种情况只会在 reload/动态替换后发生,防御即可。
        raise RuntimeError("start_background_refresh must remain async")
    loop = asyncio.get_event_loop()

    # 0. 急切加载可转债正股代码，确保所有刷新函数聚焦在目标范围内
    _ensure_bond_stock_codes()

    # 1. 并行加载所有磁盘缓存文件到内存（~300ms total vs 时序加载）
    def _load_all_caches():
        _load_industry_cache()
        _load_fin_cache()
        _load_fund_flow_cache()
        _load_debt_cache()
        _load_vol_cache()
        _load_buyback_cache()
        _load_mgmt_cache()
        _load_pledge_cache()
        _load_momentum_cache()
        _load_event_cache()
        _load_bond_outstanding_cache()
        _load_call_status_cache()
        _load_stock_name_cache()
        _load_concept_cache()
        _load_spot_cache()
        _load_bond_price_cache()
        _load_north_cache()
        _load_margin_cache()
        _load_lhb_cache()
        _load_block_trade_cache()
        _load_holder_num_cache()
        _load_earnings_forecast_cache()
        _load_earnings_express_cache()
        _load_restricted_release_cache()
    await loop.run_in_executor(None, _load_all_caches)

    # 后台刷新所有缓存
    for fn in (_build_industry_cache, _build_concept_cache, _refresh_fin_cache, _refresh_fund_flow_cache,
               _refresh_debt_cache, _refresh_buyback_cache, _refresh_mgmt_cache,
               _refresh_pledge_cache, _refresh_momentum_cache, _refresh_event_cache,
               _refresh_bond_outstanding_cache, _refresh_call_status_cache, _refresh_stock_name_cache):
        loop.run_in_executor(None, fn)

    # 后台刷新现货行情（~60-300s），不阻塞主进程
    # 波动率必须在现货刷新后执行（依赖 _spot_map），通过链式调用确保顺序
    def _spot_then_vol():
        _refresh_spot_cache()
        _refresh_volatility_cache()
    loop.run_in_executor(None, _spot_then_vol)


# ═══════════════════════════════════════════════════════════════════════════════
#  扩展数据源代理 — 桥接到 data_enrich_runner 的缓存
#  这些函数由 market.py 中的 API endpoints 调用。
#  data_enrich_runner 中的 _refresh_*_cache 负责实际数据获取，
#  这里提供 _load/get_ 接口，从 JSON 缓存文件中加载。
# ═══════════════════════════════════════════════════════════════════════════════

_NORTH_CACHE = _CACHE_DIR / "stock_north.json"
_MARGIN_CACHE = _CACHE_DIR / "stock_margin.json"
_LHB_CACHE = _CACHE_DIR / "stock_lhb.json"
_BLOCK_TRADE_CACHE = _CACHE_DIR / "stock_block_trade.json"
_HOLDER_NUM_CACHE = _CACHE_DIR / "stock_holder_num.json"
_EARNINGS_FORECAST_CACHE = _CACHE_DIR / "stock_earnings_forecast.json"
_EARNINGS_EXPRESS_CACHE = _CACHE_DIR / "stock_earnings_express.json"
_RESTRICTED_RELEASE_CACHE = _CACHE_DIR / "stock_restricted_release.json"
_CONCEPT_SOURCE_CACHE = _CACHE_DIR / "stock_concept_source.json"

# 内存缓存
_north_map: dict = {}
_margin_map: dict = {}
_lhb_map: dict = {}
_block_trade_map: dict = {}
_holder_num_map: dict = {}
_earnings_forecast_map: dict = {}
_earnings_express_map: dict = {}
_restricted_release_map: dict = {}
_concept_source_map: dict = {}


def _load_ext_cache(path: Path) -> dict:
    """从 JSON 缓存文件加载，失败返回空 dict。"""
    try:
        if path.exists():
            with open(path, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[DataEnrich] Failed to load cache {path}: {e}")
    return {}


def _load_north_cache():
    global _north_map
    _north_map = _load_ext_cache(_NORTH_CACHE)
    logger.info(f"[DataEnrich] North: loaded {len([k for k in _north_map if not k.startswith('_')])} stocks")

def get_north_map() -> dict:
    return _north_map


def _load_margin_cache():
    global _margin_map
    _margin_map = _load_ext_cache(_MARGIN_CACHE)
    logger.info(f"[DataEnrich] Margin: loaded {len([k for k in _margin_map if not k.startswith('_')])} stocks")

def get_margin_map() -> dict:
    return _margin_map


def _load_lhb_cache():
    global _lhb_map
    _lhb_map = _load_ext_cache(_LHB_CACHE)
    logger.info(f"[DataEnrich] LHB: loaded {len([k for k in _lhb_map if not k.startswith('_')])} stocks")

def get_lhb_map() -> dict:
    return _lhb_map


def _load_block_trade_cache():
    global _block_trade_map
    _block_trade_map = _load_ext_cache(_BLOCK_TRADE_CACHE)
    logger.info(f"[DataEnrich] BlockTrade: loaded {len([k for k in _block_trade_map if not k.startswith('_')])} stocks")

def get_block_trade_map() -> dict:
    return _block_trade_map


def _load_holder_num_cache():
    global _holder_num_map
    _holder_num_map = _load_ext_cache(_HOLDER_NUM_CACHE)
    logger.info(f"[DataEnrich] HolderNum: loaded {len([k for k in _holder_num_map if not k.startswith('_')])} stocks")

def get_holder_num_map() -> dict:
    return _holder_num_map


def _load_earnings_forecast_cache():
    global _earnings_forecast_map
    _earnings_forecast_map = _load_ext_cache(_EARNINGS_FORECAST_CACHE)
    logger.info(f"[DataEnrich] EarningsForecast: loaded {len([k for k in _earnings_forecast_map if not k.startswith('_')])} stocks")

def get_earnings_forecast_map() -> dict:
    return _earnings_forecast_map


def _load_earnings_express_cache():
    global _earnings_express_map
    _earnings_express_map = _load_ext_cache(_EARNINGS_EXPRESS_CACHE)
    logger.info(f"[DataEnrich] EarningsExpress: loaded {len([k for k in _earnings_express_map if not k.startswith('_')])} stocks")

def get_earnings_express_map() -> dict:
    return _earnings_express_map


def _load_restricted_release_cache():
    global _restricted_release_map
    _restricted_release_map = _load_ext_cache(_RESTRICTED_RELEASE_CACHE)
    logger.info(f"[DataEnrich] RestrictedRelease: loaded {len([k for k in _restricted_release_map if not k.startswith('_')])} events")

def get_restricted_release_map() -> dict:
    return _restricted_release_map


def get_concept_sources() -> dict[str, dict[str, bool]]:
    """概念数据源归属：concept_name -> {"em": bool, "ths": bool}"""
    if not _concept_source_map:
        raw = _load_ext_cache(_CONCEPT_SOURCE_CACHE)
        _concept_source_map.update(raw)
    return _concept_source_map


def _load_concept_source_cache():
    global _concept_source_map
    _concept_source_map = _load_ext_cache(_CONCEPT_SOURCE_CACHE)
    logger.info(f"[DataEnrich] ConceptSources: loaded {len(_concept_source_map)} entries")
