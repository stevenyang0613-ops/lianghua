"""
Data Enrichment Subprocess Runner

Runs all AKShare-based data enrichment tasks in an isolated subprocess.
If AKShare C extensions segfault (known macOS issue), only this process dies,
not the main server.

Usage:
    python -m app.engine.data_enrich_runner [--cache-ttl N]

Cache TTL override (hours):
    --spot 0.083    # 5 minutes
    --fin 24        # 24 hours
    --debt 24       # 24 hours
    --vol 24        # 24 hours
    --buyback 12    # 12 hours
    --mgmt 24       # 24 hours
    --outstanding 24 # 24 hours
    --pledge 24     # 24 hours
    --momentum 24   # 24 hours
    --event 24      # 24 hours
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# ── Fix sys.path so `from app.config` works when run as a script ──
# When launched via `python /path/to/runner.py`, the script's directory
# becomes sys.path[0], but we need the parent that contains `app/`.
_SCRIPT_DIR = Path(__file__).resolve().parent  # .../app/engine
_APP_DIR = _SCRIPT_DIR.parent                     # .../app
_BACKEND_DIR = _APP_DIR.parent                     # .../backend
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# Silence noisy loggers before anything else
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("akshare").setLevel(logging.WARNING)
from datetime import datetime
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("matplotlib").setLevel(logging.WARNING)

from app.engine.data_enrich_utils import load_cache, save_cache, fresh, safe_float, safe_int, safe_str, record_refresh_metric

logger = logging.getLogger("data_enrich_runner")

# 安装AKShare代理补丁(解锁东方财富API) - 从 settings 读取
from app.config import settings as _settings
_AKSHARE_PROXY_GATEWAY = _settings.AKSHARE_PROXY_GATEWAY
_AKSHARE_PROXY_TOKEN = _settings.AKSHARE_PROXY_TOKEN
_AKSHARE_PROXY_ENABLED = _settings.AKSHARE_PROXY_ENABLED
_AKSHARE_PROXY_RETRY = _settings.AKSHARE_PROXY_RETRY
_HOOK_DOMAINS = [
    "push2.eastmoney.com",
    "push2his.eastmoney.com",
    "emweb.securities.eastmoney.com",
    "datacenter.eastmoney.com",
    "82.push2.eastmoney.com",
    "17.push2.eastmoney.com",
    "np-anotice.eastmoney.com",
    "push1.eastmoney.com",
    "push1his.eastmoney.com",
]
if _AKSHARE_PROXY_ENABLED:
    try:
        import akshare_proxy_patch
        akshare_proxy_patch.install_patch(
            _AKSHARE_PROXY_GATEWAY,
            auth_token=_AKSHARE_PROXY_TOKEN,
            retry=_AKSHARE_PROXY_RETRY,
            hook_domains=_HOOK_DOMAINS,
        )
        logger.info(f"[Proxy] AKShare proxy patch installed (gateway={_AKSHARE_PROXY_GATEWAY}, retry={_AKSHARE_PROXY_RETRY})")
        if not _AKSHARE_PROXY_TOKEN or len(_AKSHARE_PROXY_TOKEN) < 12:
            logger.warning("[Proxy] AKSHARE_PROXY_TOKEN looks empty/demo; East Money APIs may fail. Set LH_AKSHARE_PROXY_TOKEN to a valid token.")
    except Exception as e:
        logger.warning(f"[Proxy] AKShare proxy patch install failed: {e}")
else:
    logger.info("[Proxy] AKShare proxy patch DISABLED via LH_AKSHARE_PROXY_ENABLED=0")

_CACHE_DIR = Path(os.environ.get("HOME", ".")) / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_METRICS_FILE = _CACHE_DIR / "refresh_metrics.json"

# 函数名到 metrics name 的映射（runner 内部函数名可能与 data_enrich.py 不同）
_METRICS_NAME_MAP = {
    "_build_industry_cache": "_build_industry_cache",
    "_refresh_spot_cache": "_refresh_spot_cache",
    "_refresh_fin_cache": "_refresh_fin_cache",
    "_refresh_fund_flow_cache": "_refresh_fund_flow_cache",
    "_refresh_debt_cache": "_refresh_debt_cache",
    "_refresh_volatility_cache": "_refresh_volatility_cache",
    "_refresh_buyback_cache": "_refresh_buyback_cache",
    "_refresh_mgmt_cache": "_refresh_mgmt_cache",
    "_refresh_bond_outstanding_cache": "_refresh_bond_outstanding_cache",
    "_refresh_call_status_cache": "_refresh_call_status_cache",
    "_refresh_bond_price_cache": "_refresh_bond_price_cache",
    "_refresh_pledge_cache": "_refresh_pledge_cache",
    "_refresh_momentum_cache": "_refresh_momentum_cache",
    "_refresh_event_cache": "_refresh_event_cache",
    "_build_concept_cache": "_build_concept_cache",
    "_refresh_north_cache": "_refresh_north_cache",
    "_refresh_margin_cache": "_refresh_margin_cache",
    "_refresh_lhb_cache": "_refresh_lhb_cache",
    "_refresh_block_trade_cache": "_refresh_block_trade_cache",
    "_refresh_holder_num_cache": "_refresh_holder_num_cache",
    "_refresh_earnings_forecast_cache": "_refresh_earnings_forecast_cache",
    "_refresh_earnings_express_cache": "_refresh_earnings_express_cache",
    "_refresh_restricted_release_cache": "_refresh_restricted_release_cache",
}


def _record_runner_metric(fn_name: str, elapsed_s: float, count: int, status: str = "ok", error: str = ""):
    """runner 子进程刷新完成后记录指标到共享 metrics 文件。"""
    metric_name = _METRICS_NAME_MAP.get(fn_name, fn_name)
    record_refresh_metric(_METRICS_FILE, metric_name, elapsed_s, count, status, error)


_CACHE_FILES = {
    "industry": _CACHE_DIR / "stock_industry.json",
    "spot": _CACHE_DIR / "stock_spot.json",
    "fin": _CACHE_DIR / "stock_fin.json",
    "fund_flow": _CACHE_DIR / "stock_fund_flow.json",
    "debt": _CACHE_DIR / "stock_debt.json",
    "vol": _CACHE_DIR / "stock_volatility.json",
    "buyback": _CACHE_DIR / "stock_buyback.json",
    "mgmt": _CACHE_DIR / "stock_mgmt.json",
    "outstanding": _CACHE_DIR / "bond_outstanding.json",
    "call_status": _CACHE_DIR / "bond_call_status.json",
    "pledge": _CACHE_DIR / "stock_pledge.json",
    "momentum": _CACHE_DIR / "stock_momentum.json",
    "event": _CACHE_DIR / "bond_event.json",
    "stock_names": _CACHE_DIR / "stock_names.json",
    "concept": _CACHE_DIR / "stock_concept.json",
    "north": _CACHE_DIR / "stock_north.json",
    "margin": _CACHE_DIR / "stock_margin.json",
    "lhb": _CACHE_DIR / "stock_lhb.json",
    "block_trade": _CACHE_DIR / "stock_block_trade.json",
    "holder_num": _CACHE_DIR / "stock_holder_num.json",
    "earnings_forecast": _CACHE_DIR / "stock_earnings_forecast.json",
    "earnings_express": _CACHE_DIR / "stock_earnings_express.json",
    "restricted_release": _CACHE_DIR / "stock_restricted_release.json",
    "bond_price": _CACHE_DIR / "bond_price.json",
}

# Default TTLs in seconds
_TTL = {
    "industry": 86400 * 7,
    "spot": 300,
    "fin": 3600 * 24,
    "fund_flow": 300,  # baseline; _fund_flow_ttl() overrides dynamically
    "debt": 3600 * 24,
    "vol": 3600 * 24,
    "buyback": 3600 * 12,
    "mgmt": 3600 * 24,
    "outstanding": 3600 * 24,
    "call_status": 3600 * 24,
    "pledge": 3600 * 24,
    "momentum": 86400,
    "event": 3600 * 24,
    "stock_names": 86400 * 7,
    "concept": 86400 * 7,
    "north": 3600 * 6,
    "margin": 3600 * 12,
    "lhb": 3600 * 12,
    "block_trade": 3600 * 24,
    "holder_num": 86400 * 7,
    "earnings_forecast": 3600 * 24,
    "earnings_express": 3600 * 24,
    "restricted_release": 86400 * 3,
    "bond_price": 300,
}


def _is_trading_hours() -> bool:
    """判断当前是否在 A 股交易时段 (9:15-15:05 工作日)"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1505


def _fund_flow_ttl() -> int:
    """基金流向缓存TTL: 交易时段30s, 非交易时段600s"""
    return 30 if _is_trading_hours() else 600


# ── 通达信 (TDX) fallback 辅助函数 ──
_TRY_TDX_IMPORTED = False
try:
    from app.adapters.tdx_adapter import get_tdx_adapter
    _TRY_TDX_IMPORTED = True
except Exception:
    pass


def _try_tdx_spot_fallback(codes: list[str], pe_map: dict, pb_map: dict, tr_map: dict, price_map: dict):
    """从 TDX 补充缺失的行情/PE/PB 数据（最后一道防线）"""
    if not codes or not _TRY_TDX_IMPORTED:
        return
    from app.adapters.tdx_adapter import get_tdx_adapter
    adapter = get_tdx_adapter()
    missing_pe = [c for c in codes if c not in pe_map or pe_map.get(c) is None]
    missing_pb = [c for c in codes if c not in pb_map or pb_map.get(c) is None]
    missing = list(set(missing_pe + missing_pb))
    if missing:
        logger.info(f"[TDX] Spot: fetching PE/PB for {len(missing)} stocks")
        fin_data = adapter.fetch_finance_batch(missing)
        filled_pe = filled_pb = 0
        for code, info in fin_data.items():
            pe = info.get("pe")
            pb = info.get("pb")
            if pe is not None and code not in pe_map:
                pe_map[code] = pe
                filled_pe += 1
            if pb is not None and code not in pb_map:
                pb_map[code] = pb
                filled_pb += 1
        if filled_pe or filled_pb:
            logger.info(f"[TDX] Spot: filled PE={filled_pe}, PB={filled_pb}")
    # Also try to fill price for bond stock codes
    if price_map and codes:
        missing_price = [c for c in codes if c not in price_map or not price_map.get(c)]
        if missing_price:
            tdx_q = adapter.fetch_quotes(missing_price)
            for code, q in tdx_q.items():
                if code not in price_map:
                    price_map[code] = {}
                if not price_map[code].get("price"):
                    price_map[code]["price"] = q.get("price")
                    price_map[code]["change_pct"] = q.get("change_pct")


def _try_tdx_fin_fallback(codes: list[str], fin_map: dict):
    """从 TDX 补充缺失的财务数据"""
    if not codes or not _TRY_TDX_IMPORTED:
        return
    missing = [c for c in codes if c not in fin_map or not fin_map.get(c, {}).get("roe")]
    if not missing:
        return
    from app.adapters.tdx_adapter import get_tdx_adapter
    adapter = get_tdx_adapter()
    logger.info(f"[TDX] Fin: fetching for {len(missing)} stocks")
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
        logger.info(f"[TDX] Fin: filled ROE for {filled} stocks")


def _try_tdx_vol_fallback(codes: list[str], vol_map: dict):
    """从 TDX K-line 补充缺失的波动率"""
    if not codes or not _TRY_TDX_IMPORTED:
        return
    missing = [c for c in codes if c not in vol_map or vol_map.get(c) is None]
    if not missing:
        return
    from app.adapters.tdx_adapter import get_tdx_adapter
    adapter = get_tdx_adapter()
    logger.info(f"[TDX] Vol: fetching K-line for {len(missing)} stocks")
    klines = adapter.fetch_kline_batch(missing, days=20)
    import numpy as np
    filled = 0
    for code, bars in klines.items():
        closes = [k.get("close") for k in bars if k.get("close") and k["close"] > 0]
        if len(closes) >= 5:
            returns = np.diff(closes) / closes[:-1]
            vol = float(np.std(returns) * np.sqrt(252) * 100) if len(returns) > 0 else None
            if vol is not None and vol > 0 and (code not in vol_map or vol_map.get(code) is None):
                vol = max(10, min(100, round(vol, 2)))
                vol_map[code] = vol
                filled += 1
    if filled:
        logger.info(f"[TDX] Vol: filled for {filled} stocks")


# ── 共享工具函数别名（从 data_enrich_utils 导入，保持 _ 前缀向后兼容）──
_load_cache = load_cache
_save_cache = save_cache
_fresh = fresh
_safe_float = safe_float
_safe_str = safe_str
_safe_int = safe_int


# ============================================================
# Data source: Industry
# ============================================================
def _build_industry_cache():
    """从东方财富获取行业分类

    主源: ak.stock_industry_category_cninfo()
    备用1: ak.stock_board_industry_name_em() — 东方财富行业板块 (IP封禁时不可用)
    备用2: ak.stock_board_industry_name_ths() — 同花顺行业板块
    保存时自动过滤无效条目（nan / 非6位代码）
    """
    cache_path = _CACHE_FILES["industry"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["industry"], cached, cache_path) and cached:
        # Even if fresh, filter out garbage entries from existing cache
        real = {k: v for k, v in cached.items() if k != "_ts" and len(k) == 6 and k.isdigit() and v and str(v).strip() not in ("nan", "None", "")}
        if len(real) != len(cached) - 1:
            logger.info(f"[Industry] Cleaning {len(cached)-1-len(real)} garbage entries from cache")
            _save_cache(cache_path, real)
        logger.info(f"[Industry] Cache fresh ({len(real)} valid stocks)")
        return len(real)

    result = {}

    # Primary: cninfo
    try:
        import akshare as ak
        df = ak.stock_industry_category_cninfo()
        for _, r in df.iterrows():
            code = str(r.get("代码", "")).strip()
            industry = str(r.get("行业", "")).strip()
            if code and industry and len(code) == 6 and code.isdigit():
                result[code] = industry
        logger.info(f"[Industry] cninfo: {len(result)} stocks")
    except Exception as e:
        logger.warning(f"[Industry] cninfo failed: {e}")

    # Fallback: try EM industry boards for any remaining stocks
    if len(result) < 5000:
        try:
            import akshare as ak2
            # Try stock_zh_a_spot_em for industry (it has an industry column)
            spot_df = ak2.stock_zh_a_spot_em()
            if spot_df is not None and not spot_df.empty:
                industry_cols = [c for c in spot_df.columns if '行业' in c]
                if industry_cols:
                    icol = industry_cols[0]
                    for _, r in spot_df.iterrows():
                        code = str(r.get("代码", "")).strip()
                        industry = str(r.get(icol, "")).strip()
                        if code and industry and code not in result and len(code) == 6 and code.isdigit():
                            result[code] = industry
                    logger.info(f"[Industry] spot_em fallback: {len(result)} stocks")
        except Exception as e2:
            logger.warning(f"[Industry] spot_em fallback failed: {e2}")

    # Final filter: only valid 6-digit numeric codes with non-nan values
    result = {
        k: v for k, v in result.items()
        if len(k) == 6 and k.isdigit() and v and str(v).strip() not in ("nan", "None", "")
    }

    if result:
        _save_cache(cache_path, result)
        logger.info(f"[Industry] Updated: {len(result)} stocks")
        return len(result)
    logger.warning("[Industry] All sources empty, keeping existing")
    if cached:
        # Clean existing cache
        cleaned = {k: v for k, v in cached.items() if k != "_ts" and len(k) == 6 and k.isdigit() and v and str(v).strip() not in ("nan", "None", "")}
        if len(cleaned) != len(cached) - 1:
            _save_cache(cache_path, cleaned)
            logger.info(f"[Industry] Cleaned existing cache: {len(cleaned)} stocks")
        return len(cleaned)
    return 0


# ============================================================
# Data source: Spot cache (stock_zh_a_spot - the segfault-prone one)
# ============================================================


# ============================================================
# Data source: Spot cache (price/PE/PB/turnover for all A-shares)
# ============================================================
def _refresh_spot_cache():
    """刷新现货行情（PE/PB/换手率/价格/涨跌幅）
    使用 腾讯批量API (web.sqt.gtimg.cn) 拉所有A股
    + 东方财富 ulist API 补 PE/PB/换手率
    """
    cache_path = _CACHE_FILES["spot"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["spot"], cached, cache_path):
        logger.info(f"[Spot] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)

    import requests
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _headers_em = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
    _headers_tx = {"Referer": "https://finance.qq.com", "User-Agent": "Mozilla/5.0"}

    try:
        # Step 1: 优先用 industry 文件拿全部A股代码 (11k+) 不再调 ak.stock_zh_a_spot()
        all_codes = []
        industry_path = _CACHE_FILES.get("industry")
        if industry_path and industry_path.exists():
            try:
                ind = json.loads(industry_path.read_text())
                ind.pop("_ts", None)
                all_codes = [c for c in ind.keys() if c and len(c) == 6 and c.isdigit()]
                logger.info(f"[Spot] Got {len(all_codes)} codes from industry cache")
            except Exception as e:
                logger.warning(f"[Spot] Industry load failed: {e}")

        # 回退: bond_zh_cov 正股代码
        if not all_codes:
            try:
                import akshare as ak
                df_bond = ak.bond_zh_cov()
                for _, r in df_bond.iterrows():
                    code = str(r.get("正股代码", "")).strip()
                    if code and len(code) == 6:
                        all_codes.append(code)
                logger.info(f"[Spot] Got {len(all_codes)} bond stock codes (fallback)")
            except Exception:
                pass

        if not all_codes:
            logger.warning("[Spot] No stock codes available")
            return 0

        # Step 2: 腾讯批量 (30/req) 全 A 股行情
        result = {}
        BATCH = 30
        batches = [all_codes[i:i + BATCH] for i in range(0, len(all_codes), BATCH)]
        logger.info(f"[Spot] Tencent: {len(batches)} batches")

        def _fetch_tx(batch):
            if not batch:
                return {}
            syms = [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch]
            url = f"https://web.sqt.gtimg.cn/q={','.join(syms)}"
            try:
                r = requests.get(url, headers=_headers_tx, timeout=15)
                out = {}
                for line in r.text.split(";"):
                    if "=" not in line:
                        continue
                    val = line.split("=")[1].strip('";')
                    fields = val.split("~")
                    if len(fields) < 45:
                        continue
                    code = fields[2] if len(fields) > 2 else ""
                    if not code:
                        continue
                    price = _safe_float(fields[3])
                    pe = _safe_float(fields[39]) if len(fields) > 39 else None
                    if price is None or price <= 0:
                        if pe is None or pe <= 0:
                            continue
                    tencent_volume = _safe_float(fields[6])  # 成交量 (shares)
                    tencent_amount = _safe_float(fields[37]) if len(fields) > 37 else None  # 成交额 (yuan)
                    out[code] = {
                        "price": price,
                        "open": _safe_float(fields[5]),
                        "high": _safe_float(fields[33]) if len(fields) > 33 else None,
                        "low": _safe_float(fields[34]) if len(fields) > 34 else None,
                        "change_pct": _safe_float(fields[32]) if len(fields) > 32 else None,
                        # NOTE: "volume" means 成交额 (yuan), NOT 成交量 (shares).
                        # Main process (data_enrich.py) stores 成交额 from Sina under "volume".
                        # Subprocess must match this schema, otherwise consumers
                        # (market.py, seed_duckdb.py) get share counts instead of yuan.
                        "volume": tencent_amount if tencent_amount is not None else tencent_volume,
                        "amount": tencent_amount if tencent_amount is not None else tencent_volume,
                        "pe": pe if pe and 0 < pe < 1000 else None,
                        "pb": _safe_float(fields[46]) if len(fields) > 46 and 0 < _safe_float(fields[46]) < 100 else None,
                        "turnover_rate": _safe_float(fields[38]) if len(fields) > 38 else None,
                    }
                return out
            except Exception:
                return {}

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(_fetch_tx, b): b for b in batches}
            done = 0
            for fut in as_completed(futures):
                try:
                    batch_out = fut.result(timeout=20)
                    result.update(batch_out)
                except Exception:
                    pass
                done += 1
                if done % 50 == 0:
                    logger.info(f"[Spot] Tencent: {done}/{len(batches)} batches, {len(result)} stocks")
                time.sleep(0.02)

        logger.info(f"[Spot] Tencent: {len(result)} stocks")

        # Step 3: EM ulist 补 PE/PB (50/req) for codes still missing PE
        missing_pe = [c for c in all_codes if c in result and result[c].get("pe") is None]
        if missing_pe:
            logger.info(f"[Spot] EM ulist: {len(missing_pe)} codes missing PE")
            EM_BATCH = 50
            em_batches = [missing_pe[i:i + EM_BATCH] for i in range(0, len(missing_pe), EM_BATCH)]

            def _fetch_em(batch):
                if not batch:
                    return {}
                secids = ','.join(f"{'1' if c.startswith('6') else '0'}.{c}" for c in batch)
                try:
                    r = requests.get(
                        'https://push2.eastmoney.com/api/qt/ulist.np/get',
                        params={'fields': 'f12,f9,f23,f8', 'secids': secids,
                                'ut': 'bd1d9ddb04089700cf9c27f6f7426281'},
                        headers=_headers_em, timeout=15,
                    )
                    data = r.json()
                    out = {}
                    if data.get('data') and data['data'].get('diff'):
                        for item in data['data']['diff']:
                            if not isinstance(item, dict):
                                continue
                            code = _safe_str(item.get('f12', ''))
                            if code:
                                out[code] = {
                                    'pe': _safe_float(item.get('f9')),
                                    'pb': _safe_float(item.get('f23')),
                                    'turnover_rate': _safe_float(item.get('f8')),
                                }
                    return out
                except Exception:
                    return {}

            em_done = 0
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = {ex.submit(_fetch_em, b): b for b in em_batches}
                for fut in as_completed(futures):
                    try:
                        batch_out = fut.result(timeout=20)
                        for code, vals in batch_out.items():
                            if code in result and isinstance(result[code], dict):
                                pe_v = vals.get('pe')
                                pb_v = vals.get('pb')
                                tr_v = vals.get('turnover_rate')
                                # EM returns PE*100, PB*100, turnover*100
                                if pe_v and 0 < pe_v < 100000:
                                    if result[code].get('pe') is None:
                                        result[code]['pe'] = round(pe_v / 100, 2)
                                if pb_v and 0 < pb_v < 10000:
                                    if result[code].get('pb') is None:
                                        result[code]['pb'] = round(pb_v / 100, 2)
                                if tr_v and 0 < tr_v < 10000:
                                    if result[code].get('turnover_rate') is None:
                                        result[code]['turnover_rate'] = round(tr_v / 100, 2)
                    except Exception:
                        pass
                    em_done += 1
                    if em_done % 20 == 0:
                        logger.info(f"[Spot] EM: {em_done}/{len(em_batches)} batches")
                    time.sleep(0.05)

        pe_final = sum(1 for v in result.values() if v.get("pe") is not None)
        pb_final = sum(1 for v in result.values() if v.get("pb") is not None)
        logger.info(f"[Spot] Final: {len(result)} stocks, {pe_final} PE, {pb_final} PB")

        # TDX fallback: 补充仍缺失的 PE/PB
        if _TRY_TDX_IMPORTED and all_codes:
            bond_codes = [c for c in all_codes if len(c) == 6]
            pe_map_tdx = {c: result[c]["pe"] for c in result if result[c].get("pe") is not None}
            pb_map_tdx = {c: result[c]["pb"] for c in result if result[c].get("pb") is not None}
            _try_tdx_spot_fallback(bond_codes, pe_map_tdx, pb_map_tdx, {}, {})
            for c, pe in pe_map_tdx.items():
                if c not in result:
                    result[c] = {}
                if result[c].get("pe") is None and pe is not None:
                    result[c]["pe"] = pe
            for c, pb in pb_map_tdx.items():
                if c not in result:
                    result[c] = {}
                if result[c].get("pb") is None and pb is not None:
                    result[c]["pb"] = pb

        _save_cache(cache_path, result)
        return len(result)
    except Exception as e:
        logger.warning(f"[Spot] Fetch failed: {e}")
        return 0


# ============================================================
# Data source: Financial cache (ROE/GPM/CAGR/PE/PB)
# ============================================================
def _refresh_fin_cache():
    """刷新财务数据（ROE/GPM/CAGR）- 从东方财富业绩报表获取"""
    cache_path = _CACHE_FILES["fin"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["fin"], cached, cache_path):
        logger.info(f"[Fin] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)

    try:
        import akshare as ak
        import math
        import time as _time
        now = _time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"
        df = ak.stock_yjbb_em(date=fin_date)

        # Also fetch 3-year-old data for CAGR computation
        cagr_date = f"{int(fin_date[:4])-3}{fin_date[4:]}"
        df_old = None
        try:
            df_old = ak.stock_yjbb_em(date=cagr_date)
        except Exception:
            pass

        old_rev = {}
        if df_old is not None:
            for _, r in df_old.iterrows():
                code = str(r.get("股票代码", "")).strip()
                rev = _safe_float(r.get("营业总收入-营业总收入", None))
                if code and rev and rev > 0:
                    old_rev[code] = rev

        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            entry = {
                "roe": _safe_float(r.get("净资产收益率", None)),
                "gpm": _safe_float(r.get("销售毛利率", None)),
                "industry": str(r.get("所处行业", "")) if r.get("所处行业") else None,
                "eps": _safe_float(r.get("每股收益", None)),
                "bps": _safe_float(r.get("每股净资产", None)),
                "revenue_yoy": _safe_float(r.get("营业总收入-同比增长", None)),
            }

            # Compute CAGR from 3-year revenue growth
            cur_rev = _safe_float(r.get("营业总收入-营业总收入", None))
            if cur_rev and cur_rev > 0 and code in old_rev and old_rev[code] > 0:
                try:
                    cagr = (math.pow(cur_rev / old_rev[code], 1.0 / 3.0) - 1) * 100
                    if -100 < cagr < 500:
                        entry["cagr"] = round(cagr, 2)
                except (ValueError, ZeroDivisionError):
                    pass

            if "cagr" not in entry:
                # Fallback: use revenue YoY as approximate CAGR
                rev_yoy = _safe_float(r.get("营业总收入-同比增长", None))
                if rev_yoy is not None:
                    entry["cagr"] = round(rev_yoy, 2)

            result[code] = entry

        # TDX fallback: 补充缺失的财务数据
        if _TRY_TDX_IMPORTED and result:
            fin_codes = list(result.keys())
            _try_tdx_fin_fallback(fin_codes, result)

        _save_cache(cache_path, result)
        cagr_count = sum(1 for v in result.values() if v.get("cagr") is not None)
        logger.info(f"[Fin] Updated: {len(result)} stocks, {cagr_count} with CAGR")
        return len(result)
    except Exception as e:
        logger.warning(f"[Fin] Fetch failed: {e}")
        return 0


# ============================================================
# Data source: Debt cache
# ============================================================
def _refresh_debt_cache():
    """刷新负债数据（debt_ratio/current_ratio）- 从东方财富资产负债表获取"""
    cache_path = _CACHE_FILES["debt"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["debt"], cached, cache_path):
        logger.info(f"[Debt] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)

    try:
        import akshare as ak
        import time as _time
        now = _time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"
        df = ak.stock_zcfz_em(date=fin_date)
        if df is None or df.empty:
            logger.warning(f"[Debt] zcfz returned empty for {fin_date}")
            return 0
        result = {}
        for _, r in df.iterrows():
            try:
                code = _safe_str(r.get("股票代码", ""))
                if not code:
                    continue
                # Use default=None so "is not None" check is meaningful
                debt_ratio = _safe_float(r.get("资产负债率", None), default=None)
                cash = _safe_float(r.get("资产-货币资金", None)) or 0
                receivables = _safe_float(r.get("资产-应收账款", None)) or 0
                inventory = _safe_float(r.get("资产-存货", None)) or 0
                total_debt = _safe_float(r.get("负债-总负债", None)) or 0

                entry = {}
                if debt_ratio is not None:
                    entry["debt_ratio"] = debt_ratio
                if total_debt > 0 and (cash + receivables + inventory) > 0:
                    approx_ca = cash + receivables + inventory
                    cr = approx_ca / (total_debt * 0.65)
                    if 0 < cr < 50:
                        entry["current_ratio"] = round(cr, 2)
                if entry:
                    result[code] = entry
            except Exception as row_err:
                logger.debug(f"[Debt] Row skipped: {row_err}")
                continue
        _save_cache(cache_path, result)
        dr_count = sum(1 for v in result.values() if isinstance(v, dict) and "debt_ratio" in v)
        cr_count = sum(1 for v in result.values() if isinstance(v, dict) and "current_ratio" in v)
        logger.info(f"[Debt] Updated: {len(result)} stocks ({dr_count} debt_ratio, {cr_count} current_ratio)")
        return len(result)
    except Exception as e:
        logger.warning(f"[Debt] Fetch failed: {e}")
        return 0




# ============================================================
# Data source: Fund flow cache (net_main/net_super/net_big)
# ============================================================
def _refresh_fund_flow_cache():
    """刷新资金流数据：全 A 股
    数据源: AKShare stock_individual_fund_flow_rank (通过代理, 5290+ 只全量)
    字段: f62=主力净额, f184=主力净占比, f66=超大单, f72=大单 (均为亿元)
    注意: 腾讯GTIM fields 7/8/9 是外盘/内盘/买一价而非资金流向，不使用
    """
    cache_path = _CACHE_FILES["fund_flow"]
    cached = _load_cache(cache_path)
    if _fresh(_fund_flow_ttl(), cached, cache_path):
        logger.info(f"[FundFlow] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)

    import time as _time

    for attempt in range(5):
        try:
            logger.info(f"[FundFlow] AKShare stock_individual_fund_flow_rank attempt {attempt+1}...")
            import akshare as ak
            df = ak.stock_individual_fund_flow_rank(indicator="今日")
            result = {}
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                if not code:
                    continue
                r2m = lambda c: _safe_float(r.get(c))
                net_main = r2m("今日主力净流入-净额")
                net_main_pct = r2m("今日主力净流入-净占比")
                net_super = r2m("今日超大单净流入-净额")
                net_big = r2m("今日大单净流入-净额")
                if net_main is not None or net_main_pct is not None or net_super is not None or net_big is not None:
                    result[code] = {
                        "net_main": net_main if net_main is not None and net_main != 0 else None,
                        "net_main_pct": net_main_pct if net_main_pct is not None and net_main_pct != 0 else None,
                        "net_super": net_super if net_super is not None and net_super != 0 else None,
                        "net_big": net_big if net_big is not None and net_big != 0 else None,
                    }
            _save_cache(cache_path, result)
            non_null = sum(1 for v in result.values() if isinstance(v, dict) and v.get("net_main") is not None)
            logger.info(f"[FundFlow] AKShare: {len(result)} stocks ({non_null} with net_main)")
            return len(result)
        except Exception as e:
            logger.warning(f"[FundFlow] AKShare attempt {attempt+1} failed: {e}")
            _time.sleep(3 * (attempt + 1))

    logger.warning("[FundFlow] All attempts failed, fund flow data will be empty")
    return 0

def _refresh_volatility_cache():
    """刷新波动率数据（从Tencent历史K线计算HV）覆盖全A股"""
    cache_path = _CACHE_FILES["vol"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["vol"], cached, cache_path):
        # Report coverage even when fresh
        if cached:
            real = {k: v for k, v in cached.items() if k != "_ts" and len(k) == 6 and k.isdigit()}
            logger.info(f"[Vol] Cache fresh ({len(real)} stocks), skipping")
            return len(real)
        return len(cached)

    try:
        import akshare as ak
        import numpy as np

        # Get all stock codes from stock_names or spot cache
        stock_codes = set()
        names_path = _CACHE_FILES.get("stock_names") or (_CACHE_DIR / "stock_names.json")
        names_data = _load_cache(names_path)
        if names_data:
            stock_codes = {k for k in names_data if not k.startswith("_") and len(k) == 6 and k.isdigit()}

        if not stock_codes:
            # Fallback: bond stocks
            try:
                df_bond = ak.bond_zh_cov()
                for _, r in df_bond.iterrows():
                    code = str(r.get("正股代码", "")).strip()
                    if code and len(code) == 6 and code.isdigit():
                        stock_codes.add(code)
            except Exception:
                pass

        if not stock_codes:
            logger.warning("[Vol] No stock codes available")
            return 0

        all_codes = sorted(stock_codes)
        logger.info(f"[Vol] Processing {len(all_codes)} stocks...")

        result = {}
        # Load existing results to resume
        if cached:
            result = {k: v for k, v in cached.items() if k != "_ts" and len(k) == 6 and k.isdigit()}

        for idx, code in enumerate(all_codes):
            if code in result:
                continue
            try:
                prefix = "sh" if code.startswith("6") else "sz"
                df_hist = ak.stock_zh_a_hist_tx(symbol=f"{prefix}{code}", adjust="hfwd")
                if df_hist is None or df_hist.empty:
                    continue
                closes = df_hist["close"].values.astype(float)
                closes = closes[closes > 0]
                if len(closes) < 10:
                    continue
                returns = np.diff(closes) / closes[:-1]
                returns = returns[~np.isnan(returns) & ~np.isinf(returns)]
                if len(returns) < 5:
                    continue
                hv = float(np.std(returns) * np.sqrt(252) * 100)
                hv = max(10, min(100, hv))
                result[code] = round(hv, 2)

                if len(result) % 200 == 0:
                    _save_cache(cache_path, result)
                    logger.info(f"[Vol] Progress: {len(result)}/{len(all_codes)}")
            except Exception:
                continue

            # Gentle delay every 20 calls to avoid rate limiting
            if idx % 20 == 0 and idx > 0:
                import time as _t
                import random as _rnd
                _t.sleep(0.1 + _rnd.random() * 0.2)

        # TDX fallback: 补充缺失的波动率
        if _TRY_TDX_IMPORTED and all_codes:
            _try_tdx_vol_fallback(all_codes, result)

        _save_cache(cache_path, result)
        logger.info(f"[Vol] Updated: {len(result)} stocks")
        return len(result)
    except Exception as e:
        logger.warning(f"[Vol] Fetch failed: {e}")
        if cached:
            real = {k: v for k, v in cached.items() if k != "_ts" and len(k) == 6 and k.isdigit()}
            return len(real)
        return 0


# ============================================================
# Data source: Buyback cache
# ============================================================
def _refresh_buyback_cache():
    """刷新回购数据"""
    cache_path = _CACHE_FILES["buyback"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["buyback"], cached, cache_path):
        logger.info(f"[Buyback] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)

    try:
        import akshare as ak
        df = ak.stock_repurchase_em()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            amount = _safe_float(r.get("已回购金额", None))
            if code and amount and amount > 0:
                # deduplicate: keep the largest amount if multiple rows
                if code in result:
                    result[code] = max(result[code], amount)
                else:
                    result[code] = amount
        _save_cache(cache_path, result)
        logger.info(f"[Buyback] Updated: {len(result)} stocks")
        return len(result)
    except Exception as e:
        logger.warning(f"[Buyback] Fetch failed: {e}")
        return 0


# ============================================================
# Data source: Management buy price cache
# ============================================================
def _refresh_mgmt_cache():
    """刷新管理层增持数据 - 多数据源容错

    数据源 (按优先级,默认跳过 cninfo — 该源因 py_mini_racer dlsym 错误在 macOS Electron
    沙盒/CI 环境中必然失败,见 AGENTS.md Rule #31; 仅在 LH_MGMT_TRY_CNINFO=1 时启用):
      1. EM stock_hold_management_detail_em (169k records, 董监高交易 - primary)
      2. EM stock_ggcg_em (290 pages, all shareholder changes - filter 增持)
      3. cninfo stock_hold_management_detail_cninfo (opt-in,已知不可靠)
    """
    cache_path = _CACHE_FILES["mgmt"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["mgmt"], cached, cache_path) and len(cached) > 10:
        logger.info(f"[Mgmt] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)

    import akshare as ak
    result = {}
    # 如果缓存已有数据先加载,防止外部数据源全部失败时丢失历史
    if cached and isinstance(cached, dict):
        result.update(cached)

    # Source 1 (primary): EM stock_hold_management_detail_em (董监高交易 - 含成交均价)
    # 该接口覆盖近 1 年所有董监高交易明细,在沙盒/CI 上仍可访问
    # 只保留增持/买入方向，排除减持/卖出（否则减持高价会误导选股）
    try:
        df_em_detail = ak.stock_hold_management_detail_em()
        count_before = len(result)
        for _, r in df_em_detail.iterrows():
            code = str(r.get("代码", "")).strip()
            if len(code) != 6 or not code.isdigit():
                continue
            # 过滤方向：只保留增持/买入
            direction = str(r.get("变动方向", "")).strip()
            if direction and direction not in ("增持", "买入", "新增", "净增持"):
                continue
            price = _safe_float(r.get("成交均价", None))
            if code and price and price > 0:
                last_price = result.get(code, 0)
                # 保留最高价作为管理层增持参考
                if price > last_price:
                    result[code] = price
        logger.info(
            f"[Mgmt] EM mgmt_detail (primary): {len(result)} stocks "
            f"(added {len(result) - count_before})"
        )
        # 中间保存一次 (防止后续 Source 全部失败时丢失)
        if len(result) > 100:
            _save_cache(cache_path, result)
    except Exception as e_em_detail:
        logger.warning(
            f"[Mgmt] EM mgmt_detail (primary) failed: {type(e_em_detail).__name__}: "
            f"{str(e_em_detail)[:100]}"
        )

    # Source 2 (fallback): EM stock_ggcg_em (股东增减持变动,用最新价作为参考)
    if len(result) < 200:
        try:
            # stock_ggcg_em 可能拉取 290 页数据极慢，加 timeout 保护
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(ak.stock_ggcg_em, symbol="全部")
                df_ggcg = future.result(timeout=60)
            if df_ggcg is None:
                raise TimeoutError("stock_ggcg_em returned None")
            count_before = len(result)
            for _, r in df_ggcg.iterrows():
                code = str(r.get("代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                direction = str(r.get("持股变动信息-增减", "")).strip()
                # 只采用增持方向
                if direction != "增持":
                    continue
                # 用变动期间均价 (如果有), 否则用最新价
                price = _safe_float(r.get("成交均价", None))
                if not price:
                    price = _safe_float(r.get("最新价", None))
                if code and price and price > 0:
                    last_price = result.get(code, 0)
                    if price > last_price:
                        result[code] = price
            logger.info(
                f"[Mgmt] EM ggcg (增持 only, fallback): {len(result)} stocks "
                f"(added {len(result) - count_before})"
            )
        except Exception as e_ggcg:
            logger.warning(
                f"[Mgmt] EM ggcg (fallback) failed: {type(e_ggcg).__name__}: "
                f"{str(e_ggcg)[:100]}"
            )

    # Source 3 (opt-in): cninfo stock_hold_management_detail_cninfo
    # ⚠️ 该源因 py_mini_racer dlsym 错误在 macOS Electron 沙盒中必失败,默认不调用。
    # 如确需启用,设 LH_MGMT_TRY_CNINFO=1 (开发/测试环境用)
    if os.environ.get("LH_MGMT_TRY_CNINFO", "").lower() in ("1", "true", "yes"):
        try:
            df_cninfo = ak.stock_hold_management_detail_cninfo(symbol="增持")
            count_before = len(result)
            for _, r in df_cninfo.iterrows():
                code = str(r.get("证券代码", "")).strip()
                price = _safe_float(r.get("成交均价", None))
                if code and price and price > 0:
                    last_price = result.get(code, 0)
                    if price > last_price:
                        result[code] = price
            logger.info(f"[Mgmt] cninfo (opt-in): added {len(result) - count_before}")
        except Exception as e_cninfo:
            logger.info(
                f"[Mgmt] cninfo (opt-in) skipped as expected: "
                f"{type(e_cninfo).__name__}: {str(e_cninfo)[:80]}"
            )

    if result:
        _save_cache(cache_path, result)
        logger.info(f"[Mgmt] Final: {len(result)} stocks")
        return len(result)
    logger.warning("[Mgmt] No data from any source, keeping existing")
    return len(cached) if cached else 0


# ============================================================
# Data source: Bond outstanding cache (剩余规模)
# ============================================================
def _refresh_bond_outstanding_cache():
    """刷新债券剩余规模(outstanding_scale)缓存
    数据源: bond_cb_redeem_jsl (集思录强赎数据，含剩余规模)
    备用源: bond_zh_cov (东方财富全量转债数据，含发行规模)
    """
    cache_path = _CACHE_FILES["outstanding"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["outstanding"], cached, cache_path):
        logger.info(f"[Outstanding] Cache fresh ({len(cached)} bonds), skipping")
        return len(cached)
    try:
        import akshare as ak
        logger.info("[Outstanding] Refreshing bond outstanding scale from JSL...")
        df = ak.bond_cb_redeem_jsl()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("代码", "")).strip()
            remaining = _safe_float(r.get("剩余规模", 0))
            if code and remaining and remaining > 0:
                result[code] = remaining
        if result:
            logger.info(f"[Outstanding] JSL: {len(result)} bonds")
        else:
            logger.warning("[Outstanding] JSL empty")

        # 备用：bond_zh_cov 提供所有1022只转债的发行规模
        try:
            df2 = ak.bond_zh_cov()
            if df2 is not None and not df2.empty:
                count_added = 0
                for _, r in df2.iterrows():
                    code = str(r.get("债券代码", "")).strip()
                    if not code:
                        continue
                    if code not in result:
                        issue_scale = _safe_float(r.get("发行规模", 0))
                        if issue_scale > 0:
                            result[code] = round(issue_scale, 2)
                            count_added += 1
                logger.info(f"[Outstanding] Added {count_added} bonds from bond_zh_cov fallback")
        except Exception as e2:
            logger.warning(f"[Outstanding] bond_zh_cov fallback failed: {e2}")

        if result:
            _save_cache(cache_path, result)
            logger.info(f"[Outstanding] Updated: {len(result)} bonds total")
            return len(result)
        else:
            logger.warning("[Outstanding] All sources empty, keeping existing")
            return len(cached) if cached else 0
    except Exception as e:
        logger.warning(f"[Outstanding] Fetch failed: {e}")
        return 0


# ============================================================
# Data source: Call status cache (强赎状态)
# ============================================================
def _refresh_call_status_cache():
    """刷新强赎状态缓存：覆盖全部1022只转债

    策略：
      1. 从 bond_zh_cov() 获取全部转债代码（~1022只）
      2. 从 bond_cb_redeem_jsl() 获取当前在强赎流程中的转债（~68只）
      3. 未在JSL中的转债标记为 "未触发"
    """
    cache_path = _CACHE_FILES["call_status"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["call_status"], cached, cache_path) and len(cached or {}) > 500:
        logger.info(f"[CallStatus] Cache fresh ({len(cached)} bonds), skipping")
        return len(cached)
    try:
        import akshare as ak

        # Step 1: Get ALL bonds from bond_zh_cov (~1022)
        # 带重试：首次失败后等5s重试一次
        all_bonds: dict[str, str] = {}
        for _attempt in range(2):
            try:
                df_all = ak.bond_zh_cov()
                for _, r in df_all.iterrows():
                    code = str(r.get("债券代码", "")).strip()
                    if code and len(code) == 6 and code.isdigit():
                        all_bonds[code] = "未触发"
                logger.info(f"[CallStatus] bond_zh_cov: {len(all_bonds)} total bonds")
                break
            except Exception as e_all:
                if _attempt == 0:
                    logger.warning(f"[CallStatus] bond_zh_cov attempt 1 failed: {e_all}, retrying in 5s...")
                    import time as _retry_t; _retry_t.sleep(5)
                else:
                    logger.warning(f"[CallStatus] bond_zh_cov attempt 2 failed: {e_all}, using existing+JSL")
                    if cached:
                        all_bonds = dict(cached)

        # Step 2: Overlay JSL redemption status
        logger.info("[CallStatus] Fetching JSL redemption status...")
        df = ak.bond_cb_redeem_jsl()
        jsl_count = 0
        for _, r in df.iterrows():
            code = str(r.get("代码", "")).strip()
            status = str(r.get("强赎状态", "")).strip()
            if code and status and status != "":
                all_bonds[code] = status
                jsl_count += 1
        logger.info(f"[CallStatus] JSL overlay: {jsl_count} bonds with active status")

        if all_bonds:
            _save_cache(cache_path, all_bonds)
            logger.info(f"[CallStatus] Updated: {len(all_bonds)} bonds total (JSL={jsl_count}, default=未触发={len(all_bonds)-jsl_count})")
            return len(all_bonds)
        else:
            logger.warning("[CallStatus] All sources empty, keeping existing")
            return len(cached) if cached else 0
    except Exception as e:
        logger.warning(f"[CallStatus] Fetch failed: {e}")
        return 0


# ============================================================
def _refresh_bond_price_cache():
    """刷新债券实时价格缓存
    数据源1: bond_zh_hs_cov_spot (东方财富实时行情) — 主数据源，覆盖~300+债券
    数据源2: bond_cb_jsl (集思录) — 补充数据源，覆盖~30债券
    包含: 现价, 涨跌幅, 成交额, 转股价, 转股价值, 转股溢价率, 双低, 到期税前收益, 换手率, 剩余规模, 债券评级, 剩余年限
    """
    cache_path = _CACHE_FILES["bond_price"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["bond_price"], cached, cache_path):
        logger.info(f"[BondPrice] Cache fresh ({len(cached)} bonds), skipping")
        return len(cached)
    try:
        import akshare as ak
        result = {}

        # ── Primary: East Money real-time spot quotes (东方财富实时行情) ──
        try:
            logger.info("[BondPrice] Fetching East Money bond spot quotes...")
            df_em = ak.bond_zh_hs_cov_spot()
            if df_em is not None and not df_em.empty:
                for _, r in df_em.iterrows():
                    code = str(r.get("code", "")).strip()
                    if not code or not code.isdigit() or len(code) != 6:
                        continue
                    entry = {}
                    price = _safe_float(r.get("trade", 0))
                    if price and price > 0 and abs(price - 100.0) > 0.01:
                        entry["price"] = price
                    change_pct = _safe_float(r.get("changepercent", 0))
                    if change_pct is not None:
                        entry["change_pct"] = change_pct
                    volume = _safe_float(r.get("amount", 0))
                    if volume and volume > 0:
                        entry["volume"] = volume
                    if entry:
                        result[code] = entry
                logger.info(f"[BondPrice] EM spot: {len(result)} bonds")
            else:
                logger.warning("[BondPrice] EM spot returned empty")
        except Exception as em_err:
            logger.warning(f"[BondPrice] EM spot failed: {em_err}")

        # ── Secondary: JISILU enriched data (集思录补充数据) ──
        try:
            logger.info("[BondPrice] Fetching JISILU bond data...")
            df_jsl = ak.bond_cb_jsl()
            if df_jsl is not None and not df_jsl.empty:
                for _, r in df_jsl.iterrows():
                    code = str(r.get("代码", "")).strip()
                    if not code:
                        continue
                    if code not in result:
                        result[code] = {}
                    entry = result[code]

                    # Price: only override if not already set by EM
                    if "price" not in entry:
                        price = _safe_float(r.get("现价", 0))
                        if price and price > 0 and abs(price - 100.0) > 0.01:
                            entry["price"] = price
                    # Change pct: only override if not already set
                    if "change_pct" not in entry:
                        change_pct = _safe_float(r.get("涨跌幅", 0))
                        if change_pct is not None:
                            entry["change_pct"] = change_pct
                    # Volume: only override if not already set
                    if "volume" not in entry:
                        volume = _safe_float(r.get("成交额", 0))
                        if volume and volume > 0:
                            entry["volume"] = volume

                    # Always add enriched fields from JISILU
                    stock_price = _safe_float(r.get("正股价", 0))
                    if stock_price and stock_price > 0:
                        entry["stock_price"] = stock_price
                    stock_change = _safe_float(r.get("正股涨跌", 0))
                    if stock_change is not None:
                        entry["stock_change_pct"] = stock_change
                    conv_price = _safe_float(r.get("转股价", 0))
                    if conv_price and conv_price > 0:
                        entry["conversion_price"] = conv_price
                    conv_value = _safe_float(r.get("转股价值", 0))
                    if conv_value and conv_value > 0:
                        entry["conversion_value"] = conv_value
                    premium = _safe_float(r.get("转股溢价率", 0))
                    if premium is not None:
                        entry["premium_ratio"] = premium
                    dual_low = _safe_float(r.get("双低", 0))
                    if dual_low and dual_low > 0:
                        entry["dual_low"] = dual_low
                    ytm = _safe_float(r.get("到期税前收益", 0))
                    if ytm is not None:
                        entry["ytm"] = ytm
                    remaining = _safe_float(r.get("剩余规模", 0))
                    if remaining and remaining > 0:
                        entry["outstanding_scale"] = remaining
                    turnover = _safe_float(r.get("换手率", 0))
                    if turnover and turnover > 0:
                        entry["turnover_rate"] = turnover
                    rating = r.get("债券评级", "")
                    if rating:
                        entry["bond_rating"] = str(rating).strip()
                    remaining_years = _safe_float(r.get("剩余年限", 0))
                    if remaining_years and remaining_years > 0:
                        entry["remaining_years"] = remaining_years
                    stock_pb = _safe_float(r.get("正股PB", 0))
                    if stock_pb and stock_pb > 0:
                        entry["stock_pb"] = stock_pb
                    if not entry.get("stock_price") and r.get("正股价"):
                        entry["stock_price"] = _safe_float(r.get("正股价", 0))
                logger.info(f"[BondPrice] JISILU merged: {len(result)} total bonds (JISILU contributed to JSL bonds)")
            else:
                logger.warning("[BondPrice] bond_cb_jsl returned empty")
        except Exception as jsl_err:
            logger.warning(f"[BondPrice] JISILU fetch failed: {jsl_err}")

        # TDX fallback: 补充缺失的债券价格
        if _TRY_TDX_IMPORTED:
            try:
                from app.adapters.tdx_adapter import get_tdx_adapter
                adapter = get_tdx_adapter()
                missing_codes = [c for c in result if not result[c].get("price")]
                if missing_codes:
                    tdx_q = adapter.fetch_quotes(missing_codes)
                    filled = 0
                    for code, q in tdx_q.items():
                        price = q.get("price")
                        if price and price > 0 and code in result and not result[code].get("price"):
                            result[code]["price"] = price
                            if q.get("change_pct") is not None and "change_pct" not in result[code]:
                                result[code]["change_pct"] = q.get("change_pct")
                            filled += 1
                    if filled:
                        logger.info(f"[BondPrice] TDX: filled {filled} bond prices")
            except Exception:
                pass

        # ── Fetch coupon rates from EM bond detail ──
        # bond_zh_cov_info provides COUPON_IR per bond — critical for bond_value computation
        # 同时写入独立缓存文件 bond_coupon_rate.json（防止被主进程 bond_price refresh 覆盖）
        try:
            import time as _bp_time
            coupon_codes = [c for c in result if not result[c].get("coupon_rate")]
            if coupon_codes:
                logger.info(f"[BondPrice] Fetching coupon rates for {len(coupon_codes)} bonds...")
                coupon_count = 0
                coupon_map = {}  # 独立缓存
                for code in coupon_codes[:400]:  # limit to avoid too many requests
                    try:
                        df_detail = ak.bond_zh_cov_info(symbol=code, indicator="基本信息")
                        if df_detail is not None and not df_detail.empty:
                            cr = _safe_float(df_detail["COUPON_IR"].iloc[0]) if "COUPON_IR" in df_detail.columns else None
                            if cr is not None and cr > 0:
                                result[code]["coupon_rate"] = cr
                                coupon_map[code] = cr
                                coupon_count += 1
                    except Exception:
                        pass
                    _bp_time.sleep(0.2)  # rate limit
                if coupon_count:
                    logger.info(f"[BondPrice] Coupon rates: {coupon_count}/{len(coupon_codes)} bonds")
                    # 写入独立缓存文件
                    coupon_cache_path = _CACHE_DIR / "bond_coupon_rate.json"
                    _save_cache(coupon_cache_path, coupon_map)
                    logger.info(f"[BondPrice] Saved coupon_rate cache: {len(coupon_map)} bonds")
        except Exception as coupon_err:
            logger.warning(f"[BondPrice] Coupon rate fetch failed: {coupon_err}")

        if result:
            _save_cache(cache_path, result)
            logger.info(f"[BondPrice] Updated: {len(result)} bonds with real prices")
            return len(result)
        else:
            logger.warning("[BondPrice] No valid bond data from any source")
            return 0
    except Exception as e:
        logger.warning(f"[BondPrice] Global fetch failed: {e}")
        return 0


# ============================================================
# Data source: Pledge ratio cache (质押比例)
# ============================================================
def _refresh_pledge_cache():
    """刷新质押比例缓存"""
    cache_path = _CACHE_FILES["pledge"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["pledge"], cached, cache_path):
        logger.info(f"[Pledge] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)
    try:
        import akshare as ak
        logger.info("[Pledge] Refreshing pledge ratio...")
        df = ak.stock_gpzy_pledge_ratio_em()
        result = {}
        for _, r in df.iterrows():
            try:
                code = str(r.get("股票代码", "")).strip()
                ratio = _safe_float(r.get("质押比例"), default=None)
                if code and ratio is not None:
                    result[code] = ratio
            except Exception as row_err:
                logger.debug(f"[Pledge] Row skipped: {row_err}")
                continue
        if len(result) > 100:
            _save_cache(cache_path, result)
            logger.info(f"[Pledge] Updated: {len(result)} stocks")
            return len(result)
        else:
            logger.warning(f"[Pledge] Only {len(result)} stocks, keeping existing")
            return len(cached) if cached else 0
    except Exception as e:
        logger.warning(f"[Pledge] Fetch failed: {e}")
        return 0


# ============================================================
# Data source: Momentum cache (多周期动量)
# ============================================================
def _refresh_momentum_cache():
    """从 TDX + Sina hist API 计算多周期动量 - 覆盖全市场A股
    策略: 优先使用TDX(快速,可靠), Sina作为备用"""
    cache_path = _CACHE_FILES["momentum"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["momentum"], cached, cache_path):
        logger.info(f"[Momentum] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)
    try:
        import time as _time
        import json as _json
        from concurrent.futures import ThreadPoolExecutor, as_completed
        logger.info("[Momentum] Computing from TDX kline (primary) + Sina hist (fallback)...")

        # 获取所有股票代码
        bond_codes = set()
        try:
            import akshare as ak
            df_bond = ak.bond_zh_cov()
            for _, r in df_bond.iterrows():
                code = str(r.get("正股代码", "")).strip()
                if code and len(code) == 6 and code.isdigit():
                    bond_codes.add(code)
        except Exception:
            pass

        # 从name_map获取全市场股票(5534只)
        stock_names_path = _CACHE_FILES.get("stock_names")
        name_codes = set()
        if stock_names_path and stock_names_path.exists():
            try:
                names = _json.loads(stock_names_path.read_text())
                name_codes = {k for k in names if not k.startswith("_") and len(k) == 6 and k.isdigit()}
            except Exception:
                pass

        all_codes = list(bond_codes | name_codes)
        if not all_codes and _TRY_TDX_IMPORTED:
            from app.adapters.tdx_adapter import get_tdx_adapter
            tdx_securities = get_tdx_adapter().fetch_all_securities(stock_only=True)
            all_codes = list(tdx_securities.keys())

        logger.info(f"[Momentum] Will process {len(all_codes)} stocks")

        def _compute_mom_from_closes(closes: list[float]) -> dict | None:
            if len(closes) < 10:
                return None
            today = closes[-1]
            if today <= 0:
                return None
            mom = {}
            for label, n in {"5d": 5, "10d": 10, "20d": 20, "60d": 60}.items():
                if len(closes) > n:
                    prev = closes[-(n + 1)]
                    if prev > 0:
                        mom[label] = round((today - prev) / prev * 100, 2)
            return mom if mom else None

        result = {}
        
        # Source 1: TDX kline (primary, parallel with per-thread adapter)
        if _TRY_TDX_IMPORTED and all_codes:
            from app.adapters.tdx_adapter import get_tdx_adapter
            
            def _fetch_tdx_kline(code: str) -> tuple[str, dict | None]:
                try:
                    # Each thread gets its own adapter to avoid connection racing
                    from app.adapters.tdx_adapter import TdxAdapter
                    _adapter = TdxAdapter(connect_timeout=2.0)
                    bars = _adapter.fetch_kline(code, days=65)
                    closes = [b.get("close", 0) for b in bars if b.get("close", 0) > 0]
                    return (code, _compute_mom_from_closes(closes))
                except Exception:
                    return (code, None)

            tdx_found = 0
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = {ex.submit(_fetch_tdx_kline, c): c for c in all_codes}
                for i, fut in enumerate(as_completed(futures)):
                    try:
                        code, mom = fut.result(timeout=10)
                        if mom:
                            result[code] = mom
                            tdx_found += 1
                    except Exception:
                        pass
                    if (i + 1) % 200 == 0:
                        _save_cache(cache_path, result)
                        logger.info(f"[Momentum][TDX] {i+1}/{len(all_codes)} processed ({tdx_found} found)")
            logger.info(f"[Momentum][TDX] Primary: {tdx_found}/{len(all_codes)} stocks")

        # Source 2: Sina hist fallback for missing stocks
        missing_mom = [c for c in all_codes if c not in result]
        if missing_mom:
            import requests
            logger.info(f"[Momentum][Sina] Fallback for {len(missing_mom)} stocks...")
            
            def _fetch_sina(code: str) -> tuple[str, dict | None]:
                try:
                    symbol = f"sh{code}" if code.startswith("6") else f"sz{code}"
                    url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
                    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": "65"}
                    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
                    r = requests.get(url, params=params, headers=headers, timeout=8)
                    if r.status_code != 200:
                        return (code, None)
                    text = r.text.strip()
                    if "=(" in text:
                        text = text.split("=(", 1)[1]
                        if text.endswith(";"):
                            text = text[:-1]
                        if text.endswith(")"):
                            text = text[:-1]
                    if not text or text == "null":
                        return (code, None)
                    klines = _json.loads(text)
                    if not klines or len(klines) < 10:
                        return (code, None)
                    closes = []
                    for k in klines:
                        try:
                            c = float(k.get("close", 0))
                            if c > 0:
                                closes.append(c)
                        except Exception:
                            continue
                    if len(closes) < 10:
                        return (code, None)
                    today = closes[-1]
                    if today <= 0:
                        return (code, None)
                    mom = _compute_mom_from_closes(closes)
                    return (code, mom)
                except Exception:
                    return (code, None)

            sina_found = 0
            with ThreadPoolExecutor(max_workers=6) as ex:
                futures = {ex.submit(_fetch_sina, c): c for c in missing_mom}
                for i, fut in enumerate(as_completed(futures)):
                    try:
                        code, mom = fut.result(timeout=15)
                        if mom and code not in result:
                            result[code] = mom
                            sina_found += 1
                    except Exception:
                        pass
                    if (i + 1) % 100 == 0:
                        _save_cache(cache_path, result)
                        _time.sleep(0.5)
                        logger.info(f"[Momentum][Sina] {i+1}/{len(missing_mom)} processed ({sina_found} found, total={len(result)})")
            logger.info(f"[Momentum][Sina] Fallback: {sina_found} more stocks")

        if len(result) > 100:
            _save_cache(cache_path, result)
            logger.info(f"[Momentum] Updated: {len(result)} stocks (TDX+Sina)")
            return len(result)
        else:
            logger.warning(f"[Momentum] Only {len(result)} stocks, keeping existing")
            return len(cached) if cached else 0
    except Exception as e:
        logger.warning(f"[Momentum] Fetch failed: {e}")
        return 0


# ============================================================
# Data source: Event cache (到期事件评分)
# ============================================================
def _refresh_event_cache():
    """从 THS 可转债信息推算到期事件评分"""
    cache_path = _CACHE_FILES["event"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["event"], cached, cache_path):
        logger.info(f"[Event] Cache fresh ({len(cached)} bonds), skipping")
        return len(cached)
    try:
        import akshare as ak
        from datetime import datetime
        logger.info("[Event] Refreshing bond event data from THS...")
        df = ak.bond_zh_cov_info_ths()
        now_ts = datetime.now()
        result = {}
        for _, r in df.iterrows():
            bc = str(r.get("债券代码", "")).strip()
            if not bc or len(bc) != 6:
                continue
            score = 0.5
            action = "watch"
            title = "正常"
            et = r.get("到期时间")
            if et and str(et) not in ("", "NaT", "None", "nan"):
                try:
                    mdt = datetime.strptime(str(et)[:10], "%Y-%m-%d")
                    days = (mdt - now_ts).days
                    if days < 30:
                        score = 0.95
                        action = "urgent"
                        title = f"即将到期 ({days}天)"
                    elif days < 90:
                        score = 0.85
                        action = "warning"
                        title = f"临近到期 ({days}天)"
                    elif days < 180:
                        score = 0.7
                        title = f"半年内到期 ({days}天)"
                    else:
                        score = 0.4
                        title = f"正常 (剩余{days}天)"
                except Exception:
                    pass
            result[bc] = {
                "score": score,
                "action": action,
                "title": title,
                "date": now_ts.strftime("%Y%m%d"),
            }
        if len(result) > 100:
            _save_cache(cache_path, result)
            logger.info(f"[Event] Updated: {len(result)} bonds")
            return len(result)
        else:
            logger.warning(f"[Event] Only {len(result)} bonds, keeping existing")
            return len(cached) if cached else 0
    except Exception as e:
        logger.warning(f"[Event] Fetch failed: {e}")
        return 0


# ============================================================
# Data source: Stock names cache
# ============================================================
def _refresh_stock_name_cache():
    """刷新正股名称缓存"""
    cache_path = _CACHE_FILES["stock_names"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["stock_names"], cached, cache_path):
        logger.info(f"[StockNames] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)
    try:
        import akshare as ak
        logger.info("[StockNames] Refreshing from ak.stock_info_a_code_name...")
        df = ak.stock_info_a_code_name()
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("code", "")).strip().zfill(6)
            name = str(r.get("name", "")).strip()
            if code and name:
                result[code] = name
        # 补充分 THS 转债正股名称
        try:
            df_ths = ak.bond_zh_cov_info_ths()
            if df_ths is not None and not df_ths.empty:
                for _, r in df_ths.iterrows():
                    sc = str(r.get("正股代码", "")).strip()
                    sn = str(r.get("正股简称", "")).strip()
                    if sc and sn and sc not in result:
                        result[sc] = sn
        except Exception:
            pass
        # TDX fallback: 补充缺失的股票名称
        if _TRY_TDX_IMPORTED:
            try:
                from app.adapters.tdx_adapter import get_tdx_adapter
                adapter = get_tdx_adapter()
                tdx_names = adapter.fetch_all_securities()
                added = 0
                for code, name in tdx_names.items():
                    if code not in result and name and len(code) == 6 and code.isdigit():
                        result[code] = name
                        added += 1
                if added:
                    logger.info(f"[StockNames] TDX: added {added} names")
            except Exception:
                pass
        if result:
            _save_cache(cache_path, result)
            logger.info(f"[StockNames] Updated: {len(result)} stocks")
            return len(result)
        else:
            logger.warning("[StockNames] Empty result")
            return 0
    except Exception as e:
        logger.warning(f"[StockNames] Fetch failed: {e}")
        return 0


# ── TDX 概念关键词扩展映射 ──
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
    "3D": ["3D"], "5G": ["5G"], "6G": ["6G"], "ST": ["ST"],
    "中字头": ["中"], "含H股": ["H股"], "含可转债": ["转债"],
    "破净": ["破净"], "举牌": ["举牌"], "股权转让": ["股权"],
    "一带一路": ["一带"], "雄安": ["雄安"], "大湾区": ["湾区"],
    "央企": ["央企"], "国企": ["国企"],
    "跨境电商": ["跨境"], "数字经济": ["数字"],
    "元宇宙": ["元宇"], "氢能": ["氢"], "中药": ["中药"],
    "创新药": ["创新药"], "医美": ["医美"], "预制菜": ["预制"],
    "养鸡": ["养鸡"], "猪肉": ["猪肉"], "白酒": ["白酒"],
}

# ── TDX 概念板块数据 ──
_TDX_CONCEPT_CACHE: dict[str, list[str]] | None = None
_TDX_CONCEPT_CACHE_FILE = _CACHE_DIR / "tdx_concepts.json"


def _load_tdx_concept_boards() -> dict[str, list[str]]:
    """从 TDX block_gn.dat 下载并解析概念板块数据
    返回: {board_name: [stock_code, ...]}
    """
    global _TDX_CONCEPT_CACHE
    if _TDX_CONCEPT_CACHE is not None:
        return _TDX_CONCEPT_CACHE

    # 尝试从本地缓存加载
    if _TDX_CONCEPT_CACHE_FILE.exists():
        try:
            data = json.loads(_TDX_CONCEPT_CACHE_FILE.read_text())
            if data and len(data) > 5:
                cache_ts = data.get("_ts", 0)
                if time.time() - cache_ts < 86400 * 7:  # 7天缓存
                    data.pop("_ts", None)
                    _TDX_CONCEPT_CACHE = data
                    logger.info(f"[TDX] Loaded {len(data)} concept boards from cache")
                    return data
        except Exception:
            pass

    if not _TRY_TDX_IMPORTED:
        logger.warning("[TDX] pytdx not available, skipping TDX concept boards")
        _TDX_CONCEPT_CACHE = {}
        return {}

    try:
        from pytdx.hq import TdxHq_API
        from pytdx.reader.block_reader import BlockReader, BlockReader_TYPE_GROUP

        api = TdxHq_API()
        ok = api.connect("180.153.18.170", 7709, time_out=3.0)
        if not ok:
            logger.warning("[TDX] Cannot connect for concept boards")
            _TDX_CONCEPT_CACHE = {}
            return {}

        # 下载 block_gn.dat (概念板块)
        meta = api.get_block_info_meta(b"block_gn.dat")
        if not meta or not meta.get("size"):
            api.disconnect()
            _TDX_CONCEPT_CACHE = {}
            return {}

        size = meta["size"]
        one_chunk = 0x7530
        chunks = size // one_chunk + (1 if size % one_chunk else 0)
        file_content = bytearray()
        for seg in range(chunks):
            start = seg * one_chunk
            piece_data = api.get_block_info(b"block_gn.dat", start, size)
            file_content.extend(piece_data)
        api.disconnect()

        blocks = BlockReader().get_data(file_content, BlockReader_TYPE_GROUP)

        # 只取 type 2 的概念板块（有中文名称的真正的概念板块）
        result: dict[str, list[str]] = {}
        for b in blocks:
            block_type = b.get("block_type", 0)
            name = b.get("blockname", "").strip()
            codes_str = b.get("code_list", "")
            if block_type != 2 or not name:
                continue
            valid_codes = []
            for c in codes_str.split(","):
                c = c.strip()
                if c and len(c) == 6 and c.isdigit():
                    # 排除指数代码
                    if not c.startswith(("399", "880", "950")):
                        valid_codes.append(c)
            if valid_codes:
                result[name] = valid_codes

        # 保存到本地缓存
        cache_data = dict(result)
        _save_cache(_TDX_CONCEPT_CACHE_FILE, cache_data)
        _TDX_CONCEPT_CACHE = result
        logger.info(f"[TDX] Concept boards: {len(result)} boards, {sum(len(v) for v in result.values())} stock-board pairs")
        return result
    except Exception as e:
        logger.warning(f"[TDX] Failed to download concept boards: {e}")
        _TDX_CONCEPT_CACHE = {}
        return {}


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



# ============================================================
# Main entry point
# ============================================================
def _build_concept_cache():
    """Build concept board cache from THS (东方财富因 IP 封禁不可用).
    Uses AKShare first for board list, then HTTP pagination for constituents.
    Includes proper rate limiting (2-5s between concepts, 1-2s between pages),
    403 detection with exponential backoff, and retry for failed concepts.
    Also writes stock_concept_source.json with per-concept source attribution."""
    # ── 保护：如果现有缓存足够大（已由 patch 脚本合并了 EM+THS），跳过重建 ──
    cached = _load_cache(_CACHE_FILES["concept"])
    if cached:
        real = {k: v for k, v in cached.items() if k != '_ts'}
        from collections import defaultdict
        _rev = defaultdict(int)
        for scodes in real.values():
            if isinstance(scodes, list):
                for cn in scodes:
                    _rev[cn] += 1
        total_pairs = sum(len(scodes) for scodes in real.values() if isinstance(scodes, list))
        if len(_rev) >= 300 and (max(_rev.values()) > 100 or total_pairs > 50000):
            logger.info(f'[Concept] Cache already patched ({len(_rev)} concepts, {total_pairs} pairs), skipping')
            return
    import requests as _req
    import time as _t
    import random as _rnd
    result: dict[str, list[str]] = {}
    source_map: dict[str, dict[str, bool]] = {}
    total_ths = 0
    total_em = 0
    failed_boards: list[tuple[str, str]] = []

    _THS_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "http://q.10jqka.com.cn/"
    }

    def _is_rate_limited(text: str) -> bool:
        """Check if THS response indicates rate limiting (403 or captcha page)."""
        if not text:
            return True
        low = text.lower()
        # THS returns '访问被拒绝' or redirects to verify page when rate-limited
        if len(text) < 100 and ('403' in text or 'denied' in low or 'verify' in low):
            return True
        if '访问被拒绝' in text or '验证' in text[:500]:
            return True
        return False

    def _fetch_ths_concept_list():
        """Fetch THS concept board list via HTTP (AKShare THS functions crash on macOS)."""
        import re as _re
        boards = []
        _seen_names: set[str] = set()
        
        for attempt in range(3):
            try:
                r = _req.get("http://q.10jqka.com.cn/gn/", headers=_THS_HEADERS, timeout=(5, 10))
                r.encoding = "gbk"
                if r.status_code == 200 and not _is_rate_limited(r.text):
                    for match in _re.finditer(
                        r'href="http://q\.10jqka\.com\.cn/gn/detail/code/(\d+)/"[^>]* target="_blank">([^<]+)</a>',
                        r.text
                    ):
                        code = match.group(1).strip()
                        name = match.group(2).strip()
                        if code and name and name not in _seen_names:
                            _seen_names.add(name)
                            boards.append((code, name))
                    if boards:
                        logger.info(f"[Concept] THS boards from HTTP: {len(boards)}")
                        return boards
            except Exception as exc:
                logger.warning(f"[Concept] THS HTTP board list attempt {attempt+1} failed: {exc}")
            _t.sleep(2 + _rnd.random() * 2)
        
        # Fallback: letter-based pagination
        try:
            for letter in [chr(c) for c in range(ord('A'), ord('Z')+1)] + ['0']:
                for attempt2 in range(2):
                    try:
                        r = _req.get("http://q.10jqka.com.cn/gn/",
                                     params={"pageNo": 1, "category": letter},
                                     headers=_THS_HEADERS, timeout=(5, 8))
                        if r.status_code == 200:
                            for match in _re.finditer(
                                r'href="http://q\.10jqka\.com\.cn/gn/detail/code/(\d+)/"[^>]* target="_blank">([^<]+)</a>',
                                r.text
                            ):
                                code = match.group(1).strip()
                                name = match.group(2).strip()
                                if code and name and name not in _seen_names:
                                    _seen_names.add(name)
                                    boards.append((code, name))
                            break
                    except Exception:
                        pass
                    _t.sleep(1 + _rnd.random())
                _t.sleep(0.3 + _rnd.random() * 0.5)
        except Exception:
            pass
        return boards

    def _fetch_ths_concept_cons(bcode: str, bname: str) -> list[str]:
        """Fetch THS concept board constituents via 10jqka /gn/detail/ page.
        Uses gentle rate limiting: 0.3-0.8s between pages, max 15 pages.
        Returns list of 6-digit stock codes."""
        import re as _re
        all_codes = []
        seen = set()
        consecutive_empty = 0
        for page in range(1, 16):  # Max 15 pages (most concepts < 800 stocks)
            for attempt in range(3):
                try:
                    if page == 1:
                        url = f"http://q.10jqka.com.cn/gn/detail/code/{bcode}/"
                    else:
                        url = f"http://q.10jqka.com.cn/gn/detail/code/{bcode}/page/{page}/"
                    r = _req.get(url, headers=_THS_HEADERS, timeout=5)
                    if r.status_code == 429:
                        _t.sleep(5 + _rnd.random() * 5)
                        continue
                    if r.status_code != 200:
                        if attempt < 2:
                            _t.sleep(2 + _rnd.random() * 3 * (attempt + 1))
                            continue
                        return all_codes
                    if _is_rate_limited(text := r.text):
                        _t.sleep(5 + _rnd.random() * 5)
                        continue
                    # Check if page has stock codes
                    page_codes = []
                    for match in _re.finditer(r'target="_blank">(\d{6})</a>', text):
                        code = match.group(1).strip().zfill(6)
                        if code and code not in seen:
                            seen.add(code)
                            page_codes.append(code)
                    all_codes.extend(page_codes)
                    if len(page_codes) < 10:  # No more pages
                        return all_codes
                    consecutive_empty = 0
                    break
                except Exception:
                    if attempt < 2:
                        _t.sleep(2 + _rnd.random() * 3 * (attempt + 1))
                    else:
                        return all_codes
            # Gentle delay between pages (0.3-0.8 seconds)
            _t.sleep(0.3 + _rnd.random() * 0.5)
        return all_codes

    # ======== Source 1: THS concept board names (仅名称，不拉取成分股) ========
    # AKShare中的 stock_board_concept_cons_ths 已不存在(py_mini_racer dlsym 错误)
    # EM push2 API 被 IP 封禁；此处仅保留概念名称列表，成分股通过 TDX 关键词匹配补充
    ths_boards = _fetch_ths_concept_list()
    # ======== Source 1: THS concept boards (主数据源) - 获取所有成分股 ========
    total_concepts = len(ths_boards)
    failed_boards: list[tuple[str, str]] = []
    total_ths = 0

    for idx, (bcode, bname) in enumerate(ths_boards):
        delay = 0.5 + _rnd.random() * 0.5  # 0.5-1 seconds between concepts
        if idx > 0 and idx % 50 == 0:
            delay += 3  # Small cooldown every 50 concepts
            logger.info(f"[Concept] Cooldown break after board {idx}/{total_concepts}...")

        cons = _fetch_ths_concept_cons(bcode, bname)

        if cons:
            for scode in cons:
                result.setdefault(scode, []).append(bname)
            source_map.setdefault(bname, {"em": False, "ths": True, "tdx": False})
            total_ths += 1
        else:
            failed_boards.append((bcode, bname))
            logger.warning(f"[Concept] THS board '{bname}' ({bcode}) returned 0 stocks")

        if idx % 10 == 0 and idx > 0:
            _save_cache(_CACHE_FILES["concept"], result)
            logger.info(f"[Concept] THS progress: board {idx}/{total_concepts} ({bname}), {len(result)} stocks covered so far, {total_ths} boards OK")

        if idx < total_concepts - 1:
            _t.sleep(delay)

    logger.info(f"[Concept] THS done: {total_ths} boards, {len(result)} stocks, {len(failed_boards)} failed")

    # ======== Retry failed boards ========
    if failed_boards:
        logger.info(f"[Concept] Retrying {len(failed_boards)} failed boards with longer delays...")
        retry_success = 0
        for idx, (bcode, bname) in enumerate(failed_boards):
            _t.sleep(3 + _rnd.random() * 5)
            cons = _fetch_ths_concept_cons(bcode, bname)
            if cons:
                for scode in cons:
                    result.setdefault(scode, []).append(bname)
                source_map.setdefault(bname, {"em": False, "ths": True, "tdx": False})
                retry_success += 1
                total_ths += 1
        logger.info(f"[Concept] Retry done: {retry_success}/{len(failed_boards)} success")

    # ======== Source 2: EastMoney concept boards (if proxy works) ========
    # EM is IP-banned; try once via AKShare (which may use proxy) and move on
    em_boards = []
    try:
        df = ak.stock_board_concept_name_em()
        for _, board in df.iterrows():
            bcode = str(board.get("板块代码", "")).strip()
            bname = str(board.get("板块名称", "")).strip()
            if bcode and bname:
                em_boards.append((bcode, bname))
        logger.info(f"[Concept] EM boards from AKShare: {len(em_boards)}")
    except Exception as e:
        logger.info(f"[Concept] EM AKShare failed (expected if IP-banned): {e}")

    if not em_boards:
        logger.info("[Concept] EM data unavailable (IP banned), skipping")
        em_boards = []

    def _normalize_cname(name: str) -> str:
        """归一化概念名称: 去除'概念'/'板块'后缀，方便 EM ↔ THS 匹配"""
        return name.replace("概念", "").replace("板块", "").strip()

    # name mapping: {normalized_name: [em_bcode, em_bname]}
    em_name_map: dict[str, tuple[str, str]] = {}
    for bcode, bname in em_boards:
        em_name_map[_normalize_cname(bname)] = (bcode, bname)

    for bcode, bname in em_boards:
        norm = _normalize_cname(bname)

        # 检查已存在的 THS 概念（归一化名称匹配）
        matched_ths_name = None
        for sn in source_map:
            if _normalize_cname(sn) == norm:
                matched_ths_name = sn
                break

        cons = []
        try:
            df_cons = ak.stock_board_concept_cons_em(symbol=bcode)
            for _, c in df_cons.iterrows():
                scode = str(c.get("代码", "")).strip()
                if scode:
                    cons.append(scode.zfill(6))
        except Exception:
            pass

        if matched_ths_name:
            # Merge EM constituents into the existing THS concept
            source_map[matched_ths_name]["em"] = True
            for scode in cons:
                if matched_ths_name not in result.get(scode, []):
                    result.setdefault(scode, []).append(matched_ths_name)
            total_em += 1
        else:
            # New concept from EM only
            for scode in cons:
                target_name = bname
                if target_name not in result.get(scode, []):
                    result.setdefault(scode, []).append(target_name)
            source_map.setdefault(bname, {"em": False, "ths": False, "tdx": False})["em"] = True
            total_em += 1

    # ======== Source 3: TDX 通达信概念板块（block_gn.dat） ========
    try:
        tdx_boards = _load_tdx_concept_boards()
        if tdx_boards:
            tdx_added = 0
            tdx_new_stocks = 0
            for board_name, stock_codes in tdx_boards.items():
                # 归一化匹配：查找已存在的同根概念（EM 或 THS）
                tdx_norm = _normalize_cname(board_name)
                matched_name = None
                for sn in source_map:
                    if _normalize_cname(sn) == tdx_norm:
                        matched_name = sn
                        break

                if matched_name:
                    # Merge TDX stocks into existing concept
                    source_map[matched_name]["tdx"] = True
                    for code in stock_codes:
                        if matched_name not in result.get(code, []):
                            result.setdefault(code, []).append(matched_name)
                            tdx_added += 1
                else:
                    # New concept from TDX only
                    for code in stock_codes:
                        if board_name not in result.get(code, []):
                            result.setdefault(code, []).append(board_name)
                            tdx_added += 1
                    source_map.setdefault(board_name, {"em": False, "ths": False, "tdx": False})["tdx"] = True
                    tdx_new_stocks += len(stock_codes)
            
            logger.info(f"[Concept][TDX] Added {len(tdx_boards)} concept boards ({tdx_added} stock-board pairs, {tdx_new_stocks} unique assignments)")
    except Exception as tdx_e:
        logger.warning(f"[Concept][TDX] board loading failed: {tdx_e}")

    # ======== Source 4: TDX keyword expansion for THS/EM concepts ========
    if _TRY_TDX_IMPORTED:
        try:
            from app.adapters.tdx_adapter import get_tdx_adapter
            adapter = get_tdx_adapter()
            all_concept_names = list(source_map.keys())
            tdx_total_added = 0
            tdx_concepts_filled = 0

            tdx_securities = adapter.fetch_all_securities(stock_only=True)
            if tdx_securities:
                logger.info(f"[Concept][TDX] expanding {len(all_concept_names)} concepts with keyword search ({len(tdx_securities)} securities)")

                for idx, cname in enumerate(sorted(all_concept_names)):
                    keywords = _extract_concept_keywords(cname)
                    if not keywords:
                        continue

                    added_for_concept = 0
                    for kw in keywords:
                        for code, name in tdx_securities.items():
                            if not code or len(code) != 6 or not code.isdigit():
                                continue
                            if not name:
                                continue
                            if code.startswith(('399', '880', '950')):
                                continue
                            if kw.lower() in name.lower():
                                if code in result:
                                    if cname not in result[code]:
                                        result[code].append(cname)
                                        added_for_concept += 1
                                else:
                                    result[code] = [cname]
                                    added_for_concept += 1

                    if added_for_concept > 0:
                        source_map.setdefault(cname, {"em": False, "ths": False, "tdx": False})['tdx'] = True
                        tdx_total_added += added_for_concept
                        tdx_concepts_filled += 1

                if tdx_total_added:
                    logger.info(f"[Concept][TDX] expanded {tdx_concepts_filled} concepts, added {tdx_total_added} stock-concept pairs")

        except Exception as tdx_e:
            logger.warning(f"[Concept][TDX] keyword expansion failed: {tdx_e}")

    # ======== Source 5: 名称推断概念（补全未覆盖的股票） ========
    try:
        covered_stocks = set(result.keys())
        stock_names_path = _CACHE_FILES.get("stock_names")
        all_stocks: dict[str, str] = {}
        if stock_names_path and stock_names_path.exists():
            try:
                names_data = json.loads(stock_names_path.read_text())
                names_data.pop("_ts", None)
                all_stocks = {k: (v if isinstance(v, str) else "") for k, v in names_data.items() if k != "_ts" and len(k) == 6 and k.isdigit()}
                all_stocks = {k: v for k, v in all_stocks.items() if v}
            except Exception:
                pass

        if not all_stocks and _TRY_TDX_IMPORTED:
            try:
                from app.adapters.tdx_adapter import get_tdx_adapter
                tdx_securities = get_tdx_adapter().fetch_all_securities(stock_only=True)
                all_stocks.update(tdx_securities)
            except Exception:
                pass

        if all_stocks:
            name_inferred = 0
            name_new_stocks = 0
            for code, stock_name in all_stocks.items():
                if code in covered_stocks:
                    continue
                if not stock_name or len(stock_name) < 2:
                    continue
                inferred = _infer_concepts_from_name(stock_name, code)
                if inferred:
                    result[code] = inferred
                    name_inferred += 1
                    name_new_stocks += len(inferred)

            half_covered = 0
            for code in covered_stocks:
                if code in all_stocks and len(result.get(code, [])) <= 2:
                    existing = set(result.get(code, []))
                    stock_name = all_stocks.get(code, "")
                    inferred = _infer_concepts_from_name(stock_name, code)
                    for c in inferred:
                        if c not in existing:
                            result.setdefault(code, []).append(c)
                            half_covered += 1

            if name_inferred:
                logger.info(f"[Concept][Name] Inferred concepts for {name_inferred} new stocks ({name_new_stocks} concepts), supplemented {half_covered} for thinly-covered stocks")
    except Exception as name_e:
        logger.warning(f"[Concept][Name] inference failed: {name_e}")

    # ======== Source 6: 行业推断概念（确保100%覆盖） ========
    try:
        # 从行业缓存加载行业数据
        industry_path = _CACHE_FILES.get("industry")
        if industry_path and industry_path.exists():
            import json as _jj
            ind_data = _jj.loads(industry_path.read_text())
            ind_data.pop("_ts", None)
            
            # 建立行业→概念映射
            INDUSTRY_CONCEPT_MAP = {
                "银行": ["银行"],
                "保险": ["保险"],
                "证券": ["券商"],
                "房地产": ["房地产"],
                "半导体": ["芯片概念", "半导体"],
                "白酒": ["白酒"],
                "煤炭": ["稀缺资源", "煤炭"],
                "钢铁": ["钢铁"],
                "有色": ["有色金属"],
                "黄金": ["黄金概念"],
                "电力": ["电力"],
                "医药": ["医药"],
                "医疗": ["医疗器械"],
                "汽车": ["新能源汽车", "汽车"],
                "化工": ["化工"],
                "建材": ["建材"],
                "建筑": ["建筑"],
                "工程": ["工程"],
                "机械": ["机械设备"],
                "电气": ["电气设备"],
                "食品": ["食品"],
                "饮料": ["食品"],
                "农业": ["农业"],
                "环保": ["环保"],
                "通信": ["5G", "通信"],
                "计算机": ["信创", "数字经济"],
                "软件": ["软件"],
                "传媒": ["文化传媒"],
                "纺织": ["纺织"],
                "服装": ["服装"],
                "零售": ["电子商务"],
                "物流": ["物流"],
                "港口": ["港口"],
                "航空": ["航空"],
                "国防": ["军工"],
                "军工": ["军工"],
                "电子": ["消费电子"],
                "新能源": ["新能源"],
                "光伏": ["光伏"],
                "风电": ["风电"],
                "水务": ["水务"],
                "燃气": ["燃气"],
                "高速": ["高速公路"],
                "综合": [],
            }
            
            industry_inferred = 0
            missing_stocks = [c for c in all_stocks if c not in result]
            for code in missing_stocks:
                industry = ind_data.get(code, "")
                if isinstance(industry, str) and industry:
                    for ind_kw, concepts in INDUSTRY_CONCEPT_MAP.items():
                        if ind_kw in industry:
                            if concepts:
                                result[code] = [c for c in concepts]
                                industry_inferred += 1
                            break
            
            if industry_inferred:
                logger.info(f"[Concept][Industry] Inferred concepts for {industry_inferred} stocks from industry data")
    except Exception as ind_e:
        logger.warning(f"[Concept][Industry] inference failed: {ind_e}")
    # ======== Source 7: 已知东方财富概念板块手工映射（EM API被封，通过名称推断补全） ========
    try:
        # 更新 covered_stocks 反映 Sources 5+6 的添加
        covered_stocks = set(result.keys())
        # 定义 EM 特有概念的关键词映射（这些概念在THS中不存在）
        EM_CONCEPT_KEYWORDS: dict[str, list[str]] = {
            "GPU": ["GPU", "gpu", "图形处理", "显存"],
            "CPU": ["CPU", "cpu", "中央处理器", "处理器"],
            "HBM": ["HBM", "hbm", "高带宽存储"],
            "智能驾驶": ["智能驾驶", "自动驾驶", "无人驾驶", "ADAS"],
            "电子布": ["电子布", "电子纱", "玻纤布"],
            "复合铜箔": ["复合铜箔", "PET铜箔", "铜箔"],
            "光通信": ["光通信", "光模块", "光器件", "光迅", "光芯片"],
            "光刻机": ["光刻机", "光刻", "光刻胶"],
            "先进封装": ["先进封装", "封装", "Chiplet"],
            "CPO": ["CPO", "cpo", "共封装", "硅光"],
            "存储芯片": ["存储芯片", "存储器", "内存", "闪存", "DRAM", "NAND"],
            "算力": ["算力", "算力租赁", "智算"],
            "液冷服务器": ["液冷", "冷却", "散热"],
            "AI服务器": ["AI服务器", "服务器"],
            "交换机": ["交换机", "路由"],
            "卫星通信": ["卫星通信", "卫星", "星链"],
            "量子计算": ["量子", "量子计算", "量子通信"],
            "低空经济": ["低空经济", "飞行汽车", "eVTOL"],
            "碳化硅": ["碳化硅", "SiC", "碳化硅衬底"],
            "氮化镓": ["氮化镓", "GaN"],
            "固态电池": ["固态电池", "固态"],
            "钠电池": ["钠离子", "钠电池", "钠"],
            "钙钛矿": ["钙钛矿", "钙钛矿电池"],
            "BC电池": ["BC电池"],
            "HJT电池": ["HJT", "异质结"],
            "TOPCON电池": ["TOPCON", "TopCon"],
            "换电": ["换电", "换电站"],
            "高压快充": ["高压快充", "快充", "充电桩"],
            "飞行汽车": ["飞行汽车", "eVTOL"],
            "减速器": ["减速器", "减速"],
            "人形机器人": ["人形机器人", "人形"],
            "工业母机": ["工业母机", "数控", "机床"],
            "信创": ["信创", "国产软件", "国产替代"],
            "东数西算": ["东数西算", "算力"],
            "AI大模型": ["大模型", "AI大模型", "ChatGPT"],
            "数据要素": ["数据要素", "数据确权"],
            "数据安全": ["数据安全", "网络安全"],
            "华为概念": ["华为", "昇腾", "鲲鹏", "鸿蒙"],
            "特斯拉概念": ["特斯拉", "Tesla"],
            "比亚迪概念": ["比亚迪"],
            "小米概念": ["小米", "Xiaomi"],
            "苹果概念": ["苹果", "Apple"],
        }
        
        # ======== Source 7a: THS概念→EM概念同义词映射 ========
        # 利用已有的THS概念，为已有概念的股票添加EM风格的同类概念
        CONCEPT_SYNONYM_MAP = {
            "共封装光学(CPO)": ["CPO", "共封装光学"],
            "CPO": ["共封装光学"],
            "无人驾驶": ["智能驾驶", "自动驾驶"],
            "PET铜箔": ["复合铜箔", "铜箔"],
            "钠离子电池": ["钠电池"],
            "人形机器人": ["人形机器人"],
            "机器人概念": ["机器人"],
            "飞行汽车(eVTOL)": ["飞行汽车", "低空经济"],
            "低空经济": ["飞行汽车(eVTOL)"],
            "东数西算(算力)": ["算力", "东数西算"],
            "共封装光学": ["CPO"],
            "固态电池": ["固态电池"],
            "先进封装": ["先进封装"],
            "存储芯片": ["存储芯片"],
            "减速器": ["减速器"],
            "换电概念": ["换电"],
            "信创": ["信创"],
            "大模型": ["AI大模型"],
            "算力租赁": ["算力", "算力租赁"],
        }
        synonym_added = 0
        for code, existing_concepts in list(result.items()):
            if not isinstance(existing_concepts, list):
                continue
            for existing_c in existing_concepts:
                extra = CONCEPT_SYNONYM_MAP.get(existing_c, [])
                for syn in extra:
                    if syn not in existing_concepts:
                        result[code].append(syn)
                        synonym_added += 1
        if synonym_added:
            logger.info(f"[Concept][Synonym] Added {synonym_added} EM-style concept synonyms from THS concepts")

        # ======== Source 7b: GPU/CPU/HBM/电子布 手工已知股票代码列表 ========
        # THS/EM都不提供这些概念，只能手工维护已知成分股
        MANUAL_CONCEPT_STOCKS = {
            "GPU": [
                "300474",  # 景嘉微 - GPU芯片
                "688041",  # 海光信息 - GPU(DCU)
                "688256",  # 寒武纪 - AI芯片(GPU替代)
                "688047",  # 龙芯中科 - GPU
                "002156",  # 通富微电 - GPU封装
                "300223",  # 北京君正 - GPU
                "300458",  # 全志科技 - GPU
                "603893",  # 瑞芯微 - GPU
                "300672",  # 国科微 - GPU
                "688018",  # 乐鑫科技 - Wi-Fi+GPU
                "688052",  # 纳芯微 - GPU
                "688595",  # 芯海科技 - GPU
                "300661",  # 圣邦股份 - GPU
                "688099",  # 晶晨股份 - GPU
            ],
            "CPU": [
                "688041",  # 海光信息 - CPU(x86)
                "688047",  # 龙芯中科 - CPU(龙架构)
                "688256",  # 寒武纪 - CPU
                "603986",  # 兆易创新 - MCU/CPU
                "300223",  # 北京君正 - CPU
                "688521",  # 芯原股份 - CPU IP
                "688508",  # 芯朋微 - CPU
                "300474",  # 景嘉微 - CPU
                "688595",  # 芯海科技 - CPU
                "688018",  # 乐鑫科技 - CPU
                "300458",  # 全志科技 - CPU
                "603893",  # 瑞芯微 - CPU
                "688262",  # 国芯科技 - CPU
                "688385",  # 复旦微电 - CPU
            ],
            "HBM": [
                "300475",  # 香农芯创 - HBM代理商
                "002156",  # 通富微电 - HBM封装
                "688012",  # 中微公司 - HBM设备
                "300567",  # 精测电子 - HBM测试
                "688037",  # 芯源微 - HBM设备
                "688126",  # 沪硅产业 - HBM硅片
                "002409",  # 雅克科技 - HBM材料
                "300236",  # 上海新阳 - HBM材料
                "001309",  # 德明利 - 存储
                "688525",  # 佰维存储 - HBM
                "688110",  # 东芯股份 - HBM
                "300042",  # 朗科科技 - HBM
            ],
            "电子布": [
                "300196",  # 长海股份 - 电子布
                "600176",  # 中国巨石 - 电子布
                "002080",  # 中材科技 - 电子布
                "300160",  # 秀强股份 - 电子布
                "600529",  # 山东药玻 - 电子布
                "300217",  # 东方电热 - 电子布
                "002585",  # 双星新材 - 电子布
                "002729",  # 好利科技 - 电子布
                "300709",  # 精研科技 - 电子布
                "603005",  # 晶方科技 - 电子布
                "002916",  # 深南电路 - 电子布基材
                "603228",  # 景旺电子 - 电子布基材
                "300476",  # 胜宏科技 - 电子布基材
                "002938",  # 鹏鼎控股 - 电子布基材
                "603920",  # 世运电路 - 电子布
                "603328",  # 依顿电子 - 电子布
            ],
        }
        manual_added = 0
        for concept, stock_codes in MANUAL_CONCEPT_STOCKS.items():
            for code in stock_codes:
                if code in result:
                    existing = result[code]
                    if concept not in existing:
                        result[code].append(concept)
                        manual_added += 1
        if manual_added:
            logger.info(f"[Concept][Manual] Added {manual_added} manual concept assignments (GPU/CPU/HBM/电子布)")

        # ======== Source 7c: 股票名称关键词匹配 ========
        em_added = 0
        em_new_stocks = 0
        for code, stock_name in all_stocks.items():
            if not stock_name:
                continue
            name_lower = stock_name.lower()
            for concept_name, keywords in EM_CONCEPT_KEYWORDS.items():
                matched = any(kw.lower() in name_lower for kw in keywords)
                if matched:
                    existing = result.get(code, [])
                    if concept_name not in existing:
                        result.setdefault(code, []).append(concept_name)
                        em_added += 1
                        if code not in covered_stocks:
                            em_new_stocks += 1
        
        # ======== Source 7d: 行业数据补充匹配 ========
        # 加载行业数据，用于未覆盖的股票的补充
        try:
            industry_path = _CACHE_FILES.get("industry")
            if industry_path and industry_path.exists():
                ind_data = json.loads(industry_path.read_text())
                ind_data.pop("_ts", None)
                for code, industry_name in ind_data.items():
                    if not isinstance(industry_name, str) or not industry_name:
                        continue
                    ind_lower = industry_name.lower()
                    for concept_name, keywords in EM_CONCEPT_KEYWORDS.items():
                        matched = any(kw.lower() in ind_lower for kw in keywords)
                        if matched:
                            existing = result.get(code, [])
                            if concept_name not in existing:
                                result.setdefault(code, []).append(concept_name)
                                em_added += 1
        except Exception as ind_match_e:
            pass

        if em_added:
            logger.info(f"[Concept][EM-Simulated] Added {em_added} EM-style concept assignments ({em_new_stocks} new stocks from name match)")
    except Exception as em_sim_e:
        logger.warning(f"[Concept][EM-Simulated] failed: {em_sim_e}")


    # ======== Final save ========
    if result:
        _save_cache(_CACHE_FILES["concept"], result)
        if source_map:
            source_path = _CACHE_FILES["concept"].parent / "stock_concept_source.json"
            _save_cache(source_path, source_map)
        em_only = sum(1 for v in source_map.values() if v.get("em") and not v.get("ths") and not v.get("tdx"))
        ths_only = sum(1 for v in source_map.values() if v.get("ths") and not v.get("em") and not v.get("tdx"))
        em_ths = sum(1 for v in source_map.values() if v.get("em") and v.get("ths") and not v.get("tdx"))
        with_tdx = sum(1 for v in source_map.values() if v.get("tdx"))
        logger.info(
            f"[Concept] Final: {len(result)} stocks (EM={total_em}, THS={total_ths}), "
            f"{len(source_map)} concepts (EM-only={em_only}, THS-only={ths_only}, "
            f"EM+THS={em_ths}, TDX-expanded={with_tdx})"
        )
    return len(result)


# ============================================================
# Data source: North-bound capital (北向资金) cache
# ============================================================
def _refresh_north_cache():
    """北向资金：个股北向持仓数据

    数据源 (按可靠性排序):
      1. ak.stock_hsgt_fund_flow_summary_em (汇总 - market summary)
      2. ak.stock_hsgt_hold_stock_em (个股北向持仓 TOP 排行)
      3. EM datacenter RPT_MUTUAL_STOCK_NORTHSTA (HTTP - 个股排行)
      4. EM datacenter RPT_MUTUAL_STOCK_HOLDRANKS (HTTP - 持股排行)
      5. ak.stock_hsgt_individual_detail_em (逐股详情)
      6. 北向持股估算 (从 spot 缓存流通市值 * 平均北向占比估算)

    注: 2026-06 起, EM 北向持股相关 API 可能从某些 IP 段返回空数据,
    需要多层 fallback 策略确保覆盖率。
    """
    cache_path = _CACHE_FILES["north"]
    cached = _load_cache(cache_path)
    # 检查是否有个股数据
    if _fresh(_TTL["north"], cached, cache_path):
        indiv_count = sum(1 for k in (cached or {}) if len(k) == 6 and k.isdigit())
        if indiv_count > 10:
            logger.info(f"[North] Cache fresh ({indiv_count} stocks), skipping")
            return len(cached)
    try:
        import akshare as ak
        import time as _time_n
        result = {}

        def _merge_individual(code: str, payload: dict):
            if not code or len(code) != 6 or not code.isdigit():
                return
            existing = result.get(code)
            if not existing or existing.get("_summary"):
                result[code] = payload
            else:
                for k, v in payload.items():
                    if not existing.get(k) and v is not None:
                        existing[k] = v

        # 1. 沪深港通 资金流向汇总 (北向/南向)
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            for _, r in df.iterrows():
                type_s = str(r.get("类型", "")).strip()
                bk = str(r.get("板块", "")).strip()
                key = f"summary_{type_s}_{bk}" if bk else f"summary_{type_s}"
                if type_s:
                    result[key] = {
                        "type": type_s, "board": bk,
                        "direction": str(r.get("资金方向", "")).strip(),
                        "status": str(r.get("交易状态", "")).strip(),
                        "net_buy": _safe_float(r.get("成交净买额", None)),
                        "fund_flow": _safe_float(r.get("资金净流入", None)),
                        "fund_balance": _safe_float(r.get("当日资金余额", None)),
                        "up_count": _safe_int(r.get("上涨数", None)),
                        "down_count": _safe_int(r.get("下跌数", None)),
                        "index_change": _safe_float(r.get("指数涨跌幅", None)),
                        "_summary": True,
                    }
            logger.info(f"[North] summary: {sum(1 for k in result if k.startswith('summary_'))} entries")
        except Exception as e:
            logger.warning(f"[North] summary failed: {e}")

        # 2. 个股北向持股 — ak.stock_hsgt_hold_stock_em (今日排行 TOP)
        try:
            df_top = ak.stock_hsgt_hold_stock_em(market="北向", indicator="今日排行")
            count_top = 0
            for _, r in df_top.iterrows():
                code = str(r.get("代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                _merge_individual(code, {
                    "code": code, "name": str(r.get("名称", "")).strip(),
                    "type": "北向",
                    "hold_shares": _safe_float(r.get("持股数量", None)),
                    "hold_market_cap": _safe_float(r.get("持股市值", None)),
                    "hold_ratio": _safe_float(r.get("持股占流通股比例", None)),
                    "close": _safe_float(r.get("收盘价", None)),
                    "change_pct": _safe_float(r.get("涨跌幅", None)),
                    "add_shares": _safe_float(r.get("增减持股数量", None)),
                    "add_market_cap": _safe_float(r.get("增减持股市值", None)),
                    "industry": "",
                })
                count_top += 1
            logger.info(f"[North] hold_stock_em(今日排行): {count_top} stocks")
        except Exception as e:
            logger.warning(f"[North] hold_stock_em failed: {e}")

        # 2b. 个股北向持股 — ak.stock_hsgt_hold_stock_em (3日排行)
        try:
            df_3d = ak.stock_hsgt_hold_stock_em(market="北向", indicator="3日排行")
            count_3d = 0
            for _, r in df_3d.iterrows():
                code = str(r.get("代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                _merge_individual(code, {
                    "code": code, "name": str(r.get("名称", "")).strip(),
                    "type": "北向",
                    "add_shares_3d": _safe_float(r.get("增减持股数量", None)),
                    "add_market_cap_3d": _safe_float(r.get("增减持股市值", None)),
                    "industry": "",
                })
                count_3d += 1
            logger.info(f"[North] hold_stock_em(3日排行): {count_3d} stocks")
        except Exception as e:
            logger.warning(f"[North] hold_stock_em(3日) failed: {e}")

        # 3. 个股北向持股 — EM datacenter RPT_MUTUAL_STOCK_NORTHSTA
        try:
            import requests as _req
            from datetime import datetime, timedelta
            _north_api = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            _trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            for _ in range(7):
                _params = {
                    "reportName": "RPT_MUTUAL_STOCK_NORTHSTA",
                    "columns": "ALL",
                    "pageNumber": 1,
                    "pageSize": 5000,
                    "sortColumns": "HOLD_MARKET_CAP",
                    "sortTypes": "-1",
                    "filter": f"(TRADE_DATE='{_trade_date}')(INTERVAL_TYPE=\"3\")",
                    "source": "WEB", "client": "WEB",
                }
                try:
                    _r = _req.get(_north_api, params=_params, timeout=30,
                        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})
                    if _r.status_code == 200:
                        _j = _r.json()
                        if _j.get("success") and _j.get("result") and _j["result"].get("data"):
                            n_before = sum(1 for k in result if not k.startswith("summary_"))
                            for _item in _j["result"]["data"]:
                                _c = str(_item.get("SECURITY_CODE", "")).strip()
                                if not _c or len(_c) != 6 or not _c.isdigit():
                                    continue
                                _merge_individual(_c, {
                                    "code": _c,
                                    "name": str(_item.get("SECURITY_NAME", "")).strip(),
                                    "type": "北向",
                                    "hold_date": str(_item.get("TRADE_DATE", "")).strip(),
                                    "close": _safe_float(_item.get("CLOSE_PRICE", None)),
                                    "change_pct": _safe_float(_item.get("CHANGE_RATE", None)),
                                    "hold_shares": _safe_float(_item.get("HOLD_SHARES", None)),
                                    "hold_market_cap": _safe_float(_item.get("HOLD_MARKET_CAP", None)),
                                    "hold_ratio": _safe_float(_item.get("HOLD_SHARES_RATIO", None)),
                                    "add_shares": _safe_float(_item.get("HOLD_SHARES_CHANGE", None)),
                                    "add_market_cap": _safe_float(_item.get("ADD_MARKET_CAP", None)),
                                    "industry": str(_item.get("INDUSTRY", "")).strip(),
                                })
                            individual_count = sum(1 for k in result if not k.startswith("summary_"))
                            logger.info(f"[North] NorthSTA: +{individual_count - n_before} new (total {individual_count}, date={_trade_date})")
                            break
                except Exception:
                    pass
                _trade_date = (datetime.strptime(_trade_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"[North] NorthSTA failed: {e}")

        # 4. 逐股补全 — ak.stock_hsgt_individual_detail_em
        _actual_indiv = sum(1 for k in result if not k.startswith('summary_'))
        all_a_codes: list[str] = []
        try:
            spot_cache_path = _CACHE_FILES.get("spot")
            if spot_cache_path and spot_cache_path.exists():
                spot_data = _load_cache(spot_cache_path) or {}
                for code, val in spot_data.items():
                    if code.startswith("_") or not isinstance(val, dict):
                        continue
                    if len(code) == 6 and code.isdigit():
                        all_a_codes.append(code)
        except Exception:
            pass
        if not all_a_codes:
            try:
                df_all = ak.stock_info_a_code_name()
                for _, r in df_all.iterrows():
                    c = str(r.get("code", "")).strip()
                    if len(c) == 6 and c.isdigit():
                        all_a_codes.append(c)
            except Exception:
                pass
        missing_codes = [c for c in all_a_codes if c not in result]
        MAX_PER_RUN = int(os.environ.get("LH_NORTH_MAX_PER_RUN", "500"))
        if len(missing_codes) > MAX_PER_RUN:
            missing_codes = missing_codes[:MAX_PER_RUN]
        # 只在前面几层都失败时才尝试 individual_detail_em (很慢)
        if missing_codes and _actual_indiv < 500:
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                from datetime import datetime, timedelta
                end_d = datetime.now().strftime("%Y%m%d")
                start_d = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
                logger.info(f"[North] individual_detail_em: {len(missing_codes)} stocks missing, fetching in parallel...")

                def _fetch_one(code: str):
                    for attempt in range(2):
                        try:
                            df_i = ak.stock_hsgt_individual_detail_em(
                                symbol=code, start_date=start_d, end_date=end_d
                            )
                            if df_i is not None and not df_i.empty:
                                last = df_i.iloc[-1]
                                return (code, {
                                    "code": code, "name": "", "type": "北向",
                                    "hold_date": str(last.get("持股日期", "") or last.get("日期", "")).strip(),
                                    "hold_shares": _safe_float(last.get("持股数量", None)),
                                    "hold_market_cap": _safe_float(last.get("持股市值", None)),
                                    "hold_ratio": _safe_float(last.get("持股占流通股比例", None) or last.get("持股比例", None)),
                                    "close": _safe_float(last.get("收盘价", None)),
                                    "change_pct": _safe_float(last.get("涨跌幅", None)),
                                    "industry": "",
                                })
                        except Exception:
                            if attempt == 0:
                                _time_n.sleep(0.3)
                    return None

                added = 0
                with ThreadPoolExecutor(max_workers=5) as pool:
                    futures = {pool.submit(_fetch_one, c): c for c in missing_codes}
                    done_count = 0
                    for f in as_completed(futures):
                        done_count += 1
                        try:
                            r = f.result()
                            if r:
                                code, data = r
                                _merge_individual(code, data)
                                added += 1
                        except Exception:
                            pass
                        if done_count % 100 == 0:
                            n_now = sum(1 for k in result if not k.startswith("summary_"))
                            logger.info(f"[North] individual_detail_em progress: {done_count}/{len(missing_codes)}, individual={n_now}")
                            _save_cache(cache_path, result)
                n_indiv = sum(1 for k in result if not k.startswith("summary_"))
                logger.info(f"[North] individual_detail_em: added {added} new, total individual={n_indiv}")
            except Exception as e:
                logger.warning(f"[North] individual_detail_em batch failed: {e}")

        # 5. 终极备用 — EM datacenter RPT_MUTUAL_STOCK_HOLDRANKS
        _actual_indiv = sum(1 for k in result if not k.startswith('summary_'))
        if _actual_indiv < 500:
            try:
                import requests
                from datetime import datetime, timedelta
                api_url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
                trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                for _ in range(7):
                    params = {
                        "reportName": "RPT_MUTUAL_STOCK_HOLDRANKS",
                        "columns": "ALL",
                        "pageNumber": 1,
                        "pageSize": 5000,
                        "sortColumns": "HOLD_MARKET_CAP",
                        "sortTypes": "-1",
                        "filter": f"(TRADE_DATE='{trade_date}')",
                        "source": "WEB", "client": "WEB",
                    }
                    try:
                        r = requests.get(api_url, params=params, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})
                        if r.status_code == 200:
                            j = r.json()
                            if j.get("success") and j.get("result") and j["result"].get("data"):
                                n_before = sum(1 for k in result if not k.startswith("summary_"))
                                for item in j["result"]["data"]:
                                    code = str(item.get("SECURITY_CODE", "")).strip()
                                    if len(code) != 6 or not code.isdigit():
                                        continue
                                    _merge_individual(code, {
                                        "code": code,
                                        "name": str(item.get("SECURITY_NAME", "")).strip(),
                                        "type": "北向",
                                        "hold_date": str(item.get("HOLD_DATE", "")).strip(),
                                        "close": _safe_float(item.get("CLOSE_PRICE", None)),
                                        "change_pct": _safe_float(item.get("CHANGE_RATE", None)),
                                        "hold_shares": _safe_float(item.get("HOLD_SHARES", None)),
                                        "hold_market_cap": _safe_float(item.get("HOLD_MARKET_CAP", None)),
                                        "hold_ratio": _safe_float(item.get("HOLD_SHARES_RATIO", None)),
                                        "add_shares": _safe_float(item.get("HOLD_SHARES_CHANGE", None)),
                                        "add_market_cap": _safe_float(item.get("ADD_MARKET_CAP", None)),
                                        "industry": str(item.get("INDUSTRY", "")).strip(),
                                    })
                                n = sum(1 for k in result if not k.startswith("summary_"))
                                logger.info(f"[North] HOLDRANKS: +{n - n_before} new (total {n}, date={trade_date})")
                                break
                    except Exception:
                        pass
                    trade_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            except Exception as e:
                logger.warning(f"[North] HOLDRANKS fallback failed: {e}")

        # 6. 北向持股估算 — 对于仍无个股数据的,从 spot 缓存流通市值估算
        # 使用已获取的实际 hold_ratio 中位数替代硬编码 3%，提高估算准确性
        _actual_indiv = sum(1 for k in result if not k.startswith('summary_'))
        if _actual_indiv < 200 and all_a_codes:
            # 从已有个股数据中计算实际持股比例中位数
            _actual_ratios = [v.get("hold_ratio", 0) for v in result.values()
                              if isinstance(v, dict) and v.get("hold_ratio") and not v.get("_estimated")]
            _median_ratio = 3.0  # 默认保守值
            if _actual_ratios:
                import statistics
                _median_ratio = statistics.median(_actual_ratios)
                logger.info(f"[North] Using actual hold_ratio median: {_median_ratio:.2f}% (from {len(_actual_ratios)} stocks)")
            else:
                logger.info(f"[North] No actual hold_ratio data, using default {_median_ratio}%")

            spot_data = _load_cache(_CACHE_FILES.get("spot", "")) or {}
            for code in all_a_codes:
                if code in result and not result[code].get("_summary"):
                    continue
                sp = spot_data.get(code, {})
                if not isinstance(sp, dict):
                    continue
                # 估算: hold_market_cap ≈ 流通市值 * 实际中位数持股比例
                vol = sp.get("volume")
                tr = sp.get("turnover_rate")
                price = sp.get("price")
                if vol and tr and tr > 0 and price:
                    circ_mv = vol / (tr / 100)
                    est_hold_cap = circ_mv * (_median_ratio / 100)
                    est_shares = est_hold_cap / price / 10000  # 万股
                    result[code] = {
                        "code": code, "type": "北向",
                        "hold_shares": round(est_shares, 2),
                        "hold_market_cap": round(est_hold_cap, 2),
                        "hold_ratio": round(_median_ratio, 2),
                        "_estimated": True,
                    }
            est_count = sum(1 for k, v in result.items() if isinstance(v, dict) and v.get("_estimated"))
            logger.info(f"[North] Estimated: {est_count} stocks from circulation market value")

        if result:
            _save_cache(cache_path, result)
            total_indiv = sum(1 for k in result if not k.startswith("summary_"))
            total_a = len(all_a_codes) or "?"
            coverage = (total_indiv / len(all_a_codes) * 100) if all_a_codes else 0
            logger.info(
                f"[North] Total: {len(result)} entries ({total_indiv} individual, "
                f"coverage={coverage:.1f}% of {total_a} A-shares)"
            )
            return len(result)
        logger.warning("[North] No data from any source, keeping existing")
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[North] Fetch failed: {e}")
        return len(cached or {})


# ============================================================
# Data source: Margin trading (融资融券) cache
# ============================================================
def _refresh_margin_cache():
    """融资融券汇总 + 个股融资融券
    数据源: ak.stock_margin_sse (上交所汇总) + stock_margin_detail_sse (个股)
            ak.stock_margin_ratio_pa (融资融券比例)
            EM datacenter 直接HTTP (个股融资余额 fallback)
            估算: rz_ratio * 流通市值 (终极 fallback)
    """
    cache_path = _CACHE_FILES["margin"]
    cached = _load_cache(cache_path)
    # 检查是否有个股融资余额数据 (rzye > 0)
    if _fresh(_TTL["margin"], cached, cache_path):
        with_rzye = sum(1 for k, v in (cached or {}).items()
                       if len(k) == 6 and k.isdigit() and isinstance(v, dict)
                       and v.get("rzye") is not None and v["rzye"] > 0)
        if with_rzye > 100:
            logger.info(f"[Margin] Cache fresh ({with_rzye} stocks with rzye), skipping")
            return len(cached)
    try:
        import akshare as ak
        result = {}

        # 1. 上交所融资融券汇总 (趋势)
        try:
            df_summary = ak.stock_margin_sse()
            for _, r in df_summary.head(30).iterrows():
                date_s = str(r.get("信用交易日期", "")).strip()
                if not date_s:
                    continue
                result[f"summary_SSE_{date_s}"] = {
                    "_summary": True, "exchange": "SSE",
                    "rzye": _safe_float(r.get("融资余额", None)),
                    "rzmre": _safe_float(r.get("融资买入额", None)),
                    "rqyl": _safe_float(r.get("融券余量", None)),
                    "rqye": _safe_float(r.get("融券余量金额", None)),
                    "rqsl": _safe_float(r.get("融券卖出量", None)),
                    "rzrqye": _safe_float(r.get("融资融券余额", None)),
                    "date": date_s,
                }
            logger.info(f"[Margin] SSE summary: {sum(1 for k in result if k.startswith('summary_'))} dates")
        except Exception as e:
            logger.warning(f"[Margin] SSE summary failed: {e}")

        # 2. 上交所个股融资融券明细 (最新一天) — 尝试最近7天
        try:
            from datetime import datetime, timedelta
            for days_back in range(1, 8):
                d = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
                try:
                    df_detail = ak.stock_margin_detail_sse(date=d)
                    if df_detail is not None and not df_detail.empty:
                        count = 0
                        for _, r in df_detail.iterrows():
                            code = str(r.get("标的证券代码", "")).strip()
                            if len(code) != 6 or not code.isdigit():
                                continue
                            rzye = _safe_float(r.get("融资余额", None))
                            if rzye is None or rzye == 0:
                                continue
                            if code not in result or not isinstance(result.get(code), dict) or result[code].get("_summary"):
                                result[code] = {
                                    "code": code,
                                    "name": str(r.get("标的证券简称", "")).strip(),
                                    "rzye": rzye,
                                    "rzmre": _safe_float(r.get("融资买入额", None)),
                                    "rzchl": _safe_float(r.get("融资偿还额", None)),
                                    "rqyl": _safe_float(r.get("融券余量", None)),
                                    "rqsl": _safe_float(r.get("融券卖出量", None)),
                                    "rqchl": _safe_float(r.get("融券偿还量", None)),
                                    "date": str(r.get("信用交易日期", "")).strip(),
                                }
                            count += 1
                        if count > 0:
                            logger.info(f"[Margin] SSE detail {d}: {count} stocks")
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[Margin] SSE detail failed: {e}")

        # 3. 深交所个股融资融券明细 — 尝试最近7天
        try:
            from datetime import datetime, timedelta
            for days_back in range(1, 8):
                d = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
                try:
                    df_sz = ak.stock_margin_detail_szse(date=d)
                    if df_sz is not None and not df_sz.empty:
                        count = 0
                        for _, r in df_sz.iterrows():
                            code = str(r.get("证券代码", "")).strip()
                            if len(code) != 6 or not code.isdigit():
                                continue
                            rzye = _safe_float(r.get("融资余额", None))
                            if rzye is None or rzye == 0:
                                continue
                            if code not in result or not isinstance(result.get(code), dict) or result[code].get("_summary"):
                                result[code] = {
                                    "code": code,
                                    "name": str(r.get("证券简称", "")).strip(),
                                    "rzye": rzye,
                                    "rzmre": _safe_float(r.get("融资买入额", None)),
                                    "rzchl": _safe_float(r.get("融资偿还额", None)),
                                    "rqye": _safe_float(r.get("融券余额", None)),
                                    "rqsl": _safe_float(r.get("融券卖出量", None)),
                                    "date": d,
                                }
                            count += 1
                        if count > 0:
                            logger.info(f"[Margin] SZSE detail {d}: {count} stocks")
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[Margin] SZSE detail failed: {e}")

        # 4. EM datacenter 直接HTTP获取个股融资余额 (fallback)
        _with_rzye = sum(1 for k, v in result.items()
                        if len(k) == 6 and k.isdigit() and isinstance(v, dict)
                        and v.get("rzye") is not None and v["rzye"] > 0)
        if _with_rzye < 500:
            try:
                import requests
                from datetime import datetime, timedelta
                api_url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
                for days_back in range(1, 8):
                    trade_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
                    for page in range(1, 6):
                        params = {
                            "reportName": "RPT_RZRQ_LSHJ",
                            "columns": "ALL",
                            "pageNumber": page,
                            "pageSize": 5000,
                            "sortColumns": "RZYE",
                            "sortTypes": "-1",
                            "filter": f"(TRADE_DATE='{trade_date}')",
                            "source": "WEB", "client": "WEB",
                        }
                        try:
                            r = requests.get(api_url, params=params, timeout=30,
                                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})
                            if r.status_code == 200:
                                j = r.json()
                                if j.get("success") and j.get("result") and j["result"].get("data"):
                                    for item in j["result"]["data"]:
                                        code = str(item.get("SECURITY_CODE", "")).strip()
                                        if len(code) != 6 or not code.isdigit():
                                            continue
                                        rzye = _safe_float(item.get("RZYE", None))
                                        if rzye is None or rzye <= 0:
                                            continue
                                        if code not in result or not isinstance(result.get(code), dict) or result[code].get("_summary") or not result[code].get("rzye"):
                                            if code not in result or not isinstance(result.get(code), dict):
                                                result[code] = {"code": code, "name": str(item.get("SECURITY_NAME", "")).strip()}
                                            result[code]["rzye"] = rzye
                                            result[code]["rzmre"] = _safe_float(item.get("RZMRE", None))
                                            result[code]["rqye"] = _safe_float(item.get("RQYE", None))
                                            result[code]["date"] = trade_date
                                else:
                                    break
                            else:
                                break
                        except Exception:
                            break
                    # Check if we got data for this date
                    _with_rzye_now = sum(1 for k, v in result.items()
                                        if len(k) == 6 and k.isdigit() and isinstance(v, dict)
                                        and v.get("rzye") is not None and v["rzye"] > 0)
                    if _with_rzye_now > 100:
                        logger.info(f"[Margin] EM datacenter: {_with_rzye_now} stocks with rzye (date={trade_date})")
                        break
            except Exception as e:
                logger.warning(f"[Margin] EM datacenter fallback failed: {e}")

        # 5. 融资融券比例 (全局) — 补充 rz_ratio/rq_ratio
        try:
            df_ratio = ak.stock_margin_ratio_pa()
            count_added = 0
            for _, r in df_ratio.iterrows():
                code = str(r.get("证券代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                if code not in result:
                    result[code] = {
                        "code": code,
                        "name": str(r.get("证券简称", "")).strip(),
                        "rzye": None,
                        "rz_ratio": _safe_float(r.get("融资比例", None)),
                        "rq_ratio": _safe_float(r.get("融券比例", None)),
                    }
                    count_added += 1
                else:
                    result[code]["rz_ratio"] = _safe_float(r.get("融资比例", None))
                    result[code]["rq_ratio"] = _safe_float(r.get("融券比例", None))
            logger.info(f"[Margin] ratio: {count_added} added")
        except Exception as e:
            logger.warning(f"[Margin] ratio failed: {e}")

        # 6. 对于仍无 rzye 的股票,从 rz_ratio + 流通市值估算
        _with_rzye = sum(1 for k, v in result.items()
                        if len(k) == 6 and k.isdigit() and isinstance(v, dict)
                        and v.get("rzye") is not None and v["rzye"] > 0)
        if _with_rzye < 500:
            logger.info(f"[Margin] Estimating rzye for stocks without data (current: {_with_rzye} with rzye)")
            spot_data = _load_cache(_CACHE_FILES.get("spot", "")) or {}
            est_count = 0
            for code, v in result.items():
                if len(code) != 6 or not code.isdigit() or not isinstance(v, dict):
                    continue
                if v.get("rzye") is not None and v["rzye"] > 0:
                    continue
                rz_ratio = v.get("rz_ratio")
                if rz_ratio is None or rz_ratio <= 0:
                    continue
                sp = spot_data.get(code, {})
                if not isinstance(sp, dict):
                    continue
                vol = sp.get("volume")
                tr = sp.get("turnover_rate")
                if vol and tr and tr > 0:
                    circ_mv = vol / (tr / 100)
                    est_rzye = circ_mv * rz_ratio / 100
                    if est_rzye > 0:
                        v["rzye"] = round(est_rzye, 2)
                        v["_rzye_estimated"] = True
                        est_count += 1
            logger.info(f"[Margin] Estimated rzye: {est_count} stocks")

        if result:
            _save_cache(cache_path, result)
            with_rzye = sum(1 for k, v in result.items()
                           if len(k) == 6 and k.isdigit() and isinstance(v, dict)
                           and v.get("rzye") is not None and v["rzye"] > 0)
            logger.info(f"[Margin] Total: {len(result)} entries ({with_rzye} with rzye)")
            return len(result)
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[Margin] Fetch failed: {e}")
        return len(cached or {})


# ============================================================
# Data source: Long-Hu-Bang (龙虎榜) cache
# ============================================================
def _refresh_lhb_cache():
    """龙虎榜：个股龙虎榜统计 (净买额/买入额/卖出额/机构动向)
    数据源: ak.stock_lhb_stock_statistic_em (个股本期所有上榜统计)
            ak.stock_lhb_jgstatistic_em (机构买卖统计)
    """
    cache_path = _CACHE_FILES["lhb"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["lhb"], cached, cache_path) and len(cached or {}) > 10:
        logger.info(f"[LHB] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)
    try:
        import akshare as ak
        result = {}

        # 1. 个股龙虎榜统计 (近三个月)
        try:
            df = ak.stock_lhb_stock_statistic_em()
            count = 0
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                result[code] = {
                    "code": code,
                    "name": str(r.get("名称", "")).strip(),
                    "last_date": str(r.get("最近上榜日", "")).strip(),
                    "close": _safe_float(r.get("收盘价", None)),
                    "change_pct": _safe_float(r.get("涨跌幅", None)),
                    "times": _safe_int(r.get("上榜次数", None)),
                    "net_buy_amt": _safe_float(r.get("龙虎榜净买额", None)),
                    "buy_amt": _safe_float(r.get("龙虎榜买入额", None)),
                    "sell_amt": _safe_float(r.get("龙虎榜卖出额", None)),
                    "total_amt": _safe_float(r.get("龙虎榜总成交额", None)),
                    "buy_org_times": _safe_int(r.get("买方机构次数", None)),
                    "sell_org_times": _safe_int(r.get("卖方机构次数", None)),
                    "org_net_buy": _safe_float(r.get("机构买入净额", None)),
                    "org_buy_amt": _safe_float(r.get("机构买入总额", None)),
                    "org_sell_amt": _safe_float(r.get("机构卖出总额", None)),
                    "mom_1m": _safe_float(r.get("近1个月涨跌幅", None)),
                    "mom_3m": _safe_float(r.get("近3个月涨跌幅", None)),
                    "mom_6m": _safe_float(r.get("近6个月涨跌幅", None)),
                    "mom_1y": _safe_float(r.get("近1年涨跌幅", None)),
                }
                count += 1
            logger.info(f"[LHB] stock_statistic: {count} stocks")
        except Exception as e:
            logger.warning(f"[LHB] stock_statistic failed: {e}")

        # 2. 机构买卖统计（补充视角：按机构维度汇总）
        try:
            df_jg = ak.stock_lhb_jgstatistic_em()
            # 首次运行时记录样本列名，便于调试列名变化
            if len(df_jg) > 0:
                logger.info(f"[LHB] jg_statistic columns: {list(df_jg.columns)}")
                sample = df_jg.iloc[0].to_dict()
                logger.debug(f"[LHB] jg_statistic sample: {sample}")
            jg_count = 0
            for _, r in df_jg.iterrows():
                code = str(r.get("代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                if code in result:
                    # 合并机构维度数据到已有记录
                    result[code]["jg_net_buy"] = _safe_float(r.get("机构净买入", None))
                    result[code]["jg_buy_amt"] = _safe_float(r.get("机构买入", None))
                    result[code]["jg_sell_amt"] = _safe_float(r.get("机构卖出", None))
                else:
                    result[code] = {
                        "code": code,
                        "name": str(r.get("名称", "")).strip(),
                        "times": _safe_int(r.get("上榜次数", None)),
                        "jg_net_buy": _safe_float(r.get("机构净买入", None)),
                        "jg_buy_amt": _safe_float(r.get("机构买入", None)),
                        "jg_sell_amt": _safe_float(r.get("机构卖出", None)),
                    }
                jg_count += 1
            logger.info(f"[LHB] jg_statistic: {jg_count} entries merged")
        except Exception as e_jg:
            logger.debug(f"[LHB] jg_statistic failed (non-critical): {e_jg}")

        if result:
            _save_cache(cache_path, result)
            logger.info(f"[LHB] Total: {len(result)} stocks")
            return len(result)
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[LHB] Fetch failed: {e}")
        return len(cached or {})


# ============================================================
# Data source: Block trade (大宗交易) cache
# ============================================================
def _refresh_block_trade_cache():
    """大宗交易：近 N 个交易日 大宗交易汇总 按股票聚合

    数据源 (按 A 股覆盖率排序):
      1. ak.stock_dzjy_mrtj (每日汇总 - 含 A 股代码/成交额/折溢价率, 推荐)
      2. ak.stock_dzjy_mrmx (每日明细 - 主要是 ETF/基金代码, A 股少)
      3. ak.stock_dzjy_sctj (市场统计 - 按日期)
      4. ak.stock_dzjy_yybph (营业部排行 - 近一月)

    注: stock_dzjy_mrmx 返回的主要是 ETF/基金代码(159xxx/50xxx/51xxx),
    而 stock_dzjy_mrtj 返回的才是 A 股股票代码(0xxx/3xxx/6xxx)。
    因此优先使用 mrtj 作为 A 股大宗交易数据源。
    """
    cache_path = _CACHE_FILES["block_trade"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["block_trade"], cached, cache_path) and len(cached or {}) > 10:
        a_count = sum(1 for k in (cached or {}) if len(k) == 6 and k.isdigit() and k[0] in '036')
        if a_count > 10:
            logger.info(f"[BlockTrade] Cache fresh ({a_count} A-share stocks), skipping")
            return len(cached)
    try:
        import akshare as ak
        from datetime import datetime, timedelta
        result = {}

        # 1. 主要数据源: stock_dzjy_mrtj (每日汇总 - 含 A 股代码)
        end_d = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        start_d = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
        try:
            df = ak.stock_dzjy_mrtj(start_date=start_d, end_date=end_d)
            count = 0
            total_amt = 0.0
            for _, r in df.iterrows():
                code = str(r.get("证券代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                # 只保留 A 股代码 (0xxx/3xxx/6xxx)
                if code[0] not in '036':
                    continue
                amt = _safe_float(r.get("成交总额", None))
                vol = _safe_float(r.get("成交总量", None))
                price = _safe_float(r.get("成交价", None))
                close = _safe_float(r.get("收盘价", None))
                trade_date = str(r.get("交易日期", "")).strip()
                premium_rate = _safe_float(r.get("折溢率", None))
                trade_count_val = _safe_int(r.get("成交笔数", None))
                name = str(r.get("证券简称", "")).strip()

                if code not in result:
                    result[code] = {
                        "code": code, "name": name,
                        "total_amt": 0.0, "total_vol": 0.0,
                        "trade_count": 0, "latest_trade_date": "",
                        "latest_premium_rate": None, "latest_close": None,
                    }
                if amt:
                    result[code]["total_amt"] += amt
                    total_amt += amt
                if vol:
                    result[code]["total_vol"] += vol
                if trade_count_val:
                    result[code]["trade_count"] += trade_count_val
                if trade_date and trade_date > result[code]["latest_trade_date"]:
                    result[code]["latest_trade_date"] = trade_date
                    result[code]["latest_premium_rate"] = premium_rate
                    result[code]["latest_close"] = close
                count += 1

            logger.info(
                f"[BlockTrade] mrtj: {count} trades, {len(result)} A-share stocks, "
                f"total_amt={round(total_amt/1e8, 2)}亿"
            )
        except Exception as e:
            logger.warning(f"[BlockTrade] mrtj failed: {e}")

        # 2. 补充: stock_dzjy_mrmx (逐笔数据 - 仅补充 mrtj 未覆盖的 A 股)
        try:
            df2 = ak.stock_dzjy_mrmx(start_date=start_d, end_date=end_d)
            added = 0
            for _, r in df2.iterrows():
                code = str(r.get("证券代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                if code[0] not in '036':
                    continue
                amt = _safe_float(r.get("成交额", None))
                if code in result:
                    if amt:
                        result[code]["total_amt"] += amt
                        result[code]["trade_count"] += 1
                else:
                    result[code] = {
                        "code": code,
                        "name": str(r.get("证券简称", "")).strip(),
                        "total_amt": amt or 0.0,
                        "total_vol": _safe_float(r.get("成交量", None)) or 0.0,
                        "trade_count": 1,
                        "latest_trade_date": str(r.get("成交日期", "")).strip(),
                        "latest_premium_rate": _safe_float(r.get("折溢价率", None)),
                        "latest_close": None,
                    }
                    added += 1
            if added > 0:
                logger.info(f"[BlockTrade] mrmx补充: {added} new A-share stocks")
        except Exception as e:
            logger.warning(f"[BlockTrade] mrmx failed: {e}")

        # 3. 营业部排行 (近一月)
        try:
            df_yyb = ak.stock_dzjy_yybph(symbol="近一月")
            broker_rank = []
            for _, r in df_yyb.head(50).iterrows():
                buy_amt = _safe_float(r.get("买入金额", None)) or 0.0
                sell_amt = _safe_float(r.get("卖出金额", None)) or 0.0
                broker_rank.append({
                    "broker": str(r.get("营业部名称", "")).strip(),
                    "buy_amt": buy_amt, "sell_amt": sell_amt,
                    "net_amt": round(buy_amt - sell_amt, 2),
                    "trade_count": _safe_int(r.get("成交笔数", None)),
                })
            if broker_rank:
                broker_path = cache_path.parent / "stock_block_trade_brokers.json"
                _save_cache(broker_path, {"_brokers": True, "data": broker_rank})
                logger.info(f"[BlockTrade] brokers: {len(broker_rank)} active brokers (近一月)")
        except Exception as e:
            logger.warning(f"[BlockTrade] yybph failed: {e}")

        if result:
            _save_cache(cache_path, result)
            a_count = sum(1 for k in result if k[0] in '036')
            logger.info(f"[BlockTrade] Total: {len(result)} stocks ({a_count} A-share)")
            return len(result)
        logger.warning("[BlockTrade] No per-stock data, keeping existing")
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[BlockTrade] Fetch failed: {e}")
        return len(cached or {})

def _infer_concepts_from_name(stock_name: str, stock_code: str) -> list[str]:
    """根据股票名称推断所属概念"""
    if not stock_name:
        return []
    inferred = []
    name_lower = stock_name.lower()

    NAME_CONCEPT_MAP = {
        "半导体": ["芯片概念", "半导体"],
        "芯片": ["芯片概念"],
        "集成": ["芯片概念"],
        "微": ["芯片概念"],
        "AI": ["人工智能", "AI"],
        "智能": ["人工智能", "智能"],
        "人工": ["人工智能"],
        "机器": ["机器人概念"],
        "数字": ["数字经济"],
        "数据": ["数据要素"],
        "算力": ["算力"],
        "云": ["云计算"],
        "软件": ["软件"],
        "信息": ["信息技术"],
        "互联": ["互联网"],
        "通信": ["5G", "通信"],
        "光": ["光通信"],
        "5G": ["5G"],
        "汽车": ["新能源汽车", "汽车"],
        "新能源": ["新能源"],
        "光伏": ["光伏"],
        "风电": ["风电"],
        "电池": ["锂电池", "电池"],
        "锂": ["锂电池"],
        "钠": ["钠电池"],
        "固态": ["固态电池"],
        "氢": ["氢能源"],
        "储能": ["储能"],
        "充电": ["充电桩"],
        "军工": ["军工"],
        "国防": ["军工"],
        "航天": ["军工"],
        "航空": ["军工"],
        "医药": ["医药"],
        "医疗": ["医药", "医疗器械"],
        "药": ["医药"],
        "银行": ["银行"],
        "证券": ["券商"],
        "保险": ["保险"],
        "地产": ["房地产"],
        "机器人": ["机器人概念", "人形机器人"],
        "减速": ["减速器"],
        "激光": ["激光"],
        "雷达": ["毫米波雷达"],
        "无人": ["无人驾驶", "智能驾驶"],
        "驾驶": ["智能驾驶"],
        "飞行": ["飞行汽车(eVTOL)"],
        "低空": ["低空经济"],
        "电子": ["消费电子"],
        "显示": ["OLED"],
        "面板": ["OLED"],
        "铜箔": ["PET铜箔", "复合铜箔", "铜箔"],
        "PCB": ["PCB概念"],
        "封": ["先进封装"],
        "液": ["液冷服务器"],
        "存": ["存储芯片"],
        "MCU": ["MCU芯片"],
        "服务器": ["算力"],
        "核": ["核电"],
        "碳": ["碳中和"],
        "环保": ["环保"],
        "电商": ["电子商务"],
        "游戏": ["网络游戏"],
        "传媒": ["文化传媒"],
        "影视": ["影视"],
        "酒店": ["酒店"],
        "旅游": ["旅游"],
        "食": ["食品"],
        "酒": ["白酒"],
        "矿": ["稀缺资源"],
        "黄金": ["黄金概念"],
        "有色": ["有色金属"],
        "钢铁": ["钢铁"],
        "化工": ["化工"],
        "纺织": ["纺织"],
        "服装": ["服装"],
        "建材": ["建材"],
        "建筑": ["建筑"],
        "工程": ["工程"],
        "机械": ["机械设备"],
        "装备": ["军工"],
        "电力": ["电力"],
        "电气": ["电气设备"],
        "高速": ["高速公路"],
        "路桥": ["基建"],
        "水务": ["水务"],
        "燃气": ["燃气"],
        "物流": ["物流"],
        "航运": ["航运"],
        "港口": ["港口"],
        "国企": ["国企改革"],
        "央企": ["中字头"],
        "中字头": ["中字头"],
        "北交": ["北交所"],
        "科创": ["科创板"],
        "专精特新": ["专精特新"],
        "光电": ["光通信", "CPO"],
        "CPO": ["共封装光学(CPO)"],
        "GPU": ["GPU"],
        "CPU": ["CPU"],
        "HBM": ["HBM"],
        "存储": ["存储芯片"],
        "算": ["算力租赁"],
        "模": ["大模型"],
        "互联": ["互联网"],
        "信创": ["信创"],
        "卫星": ["卫星"],
        "导航": ["卫星导航"],
        "物联": ["物联网"],
        "网联": ["车联网(车路协同)"],
        "机器": ["机器人概念", "人形机器人"],
        "导体": ["半导体"],
        "材料": ["新材料"],
        "光刻": ["光刻机", "光刻胶"],
        "量子": ["量子计算"],
        "刹车": ["制动"],
        "3D": ["3D打印"],
        "免税": ["免税店"],
        "机器人": ["机器人概念", "人形机器人"],
        "元宇宙": ["元宇宙"],
        "虚拟": ["虚拟现实", "元宇宙"],
        "增强": ["虚拟现实"],
        "数字货币": ["数字货币"],
        "区块链": ["区块链"],
        "白酒": ["白酒"],
        "啤酒": ["啤酒"],
        "科技": ["科技"],
    }

    for keyword, concepts in NAME_CONCEPT_MAP.items():
        if keyword.lower() in name_lower:
            for c in concepts:
                if c not in inferred:
                    inferred.append(c)

    return inferred






# ============================================================
# Data source: Shareholder change (股东户数变动) cache
# ============================================================
def _refresh_holder_num_cache():
    """股东户数：EM F10 ShareholderResearch API
    逐股拉取，需要产业缓存中的股票列表

    优化：随机User-Agent + 随机延迟 + 重试 + 备用API
    """
    cache_path = _CACHE_FILES["holder_num"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["holder_num"], cached, cache_path) and len(cached or {}) > 100:
        logger.info(f"[HolderNum] Cache fresh ({len(cached)} stocks), skipping")
        return len(cached)
    try:
        import requests
        import random
        result = {}

        _UAS = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Gecko/20100101 Firefox/115.0",
        ]
        def _random_headers():
            return {
                "User-Agent": random.choice(_UAS),
                "Referer": "https://emweb.securities.eastmoney.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            }

        # 从产业缓存拿股票列表 (限于可转债正股 + A股)
        industry_path = _CACHE_FILES.get("industry")
        all_codes = []
        if industry_path and industry_path.exists():
            try:
                ind = json.loads(industry_path.read_text())
                ind.pop("_ts", None)
                all_codes = [c for c in ind.keys() if c and len(c) == 6 and c.isdigit()]
            except Exception:
                pass
        if not all_codes:
            all_codes = list(cached.keys()) if cached else []
        # 优先处理可转债正股 (从bond_zh_cov 或 bond_outstanding 加载)
        bond_stocks = set()
        try:
            import akshare as ak
            df_b = ak.bond_zh_cov()
            bond_stocks = set(str(r.get("正股代码", "")).strip() for _, r in df_b.iterrows())
            bond_stocks = {c for c in bond_stocks if len(c) == 6 and c.isdigit()}
        except Exception:
            pass
        # 如果 bond_zh_cov 失败, 从 bond_outstanding 缓存获取正股代码
        if not bond_stocks:
            try:
                out_path = _CACHE_FILES.get("outstanding")
                if out_path and out_path.exists():
                    out_data = json.loads(out_path.read_text())
                    out_data.pop("_ts", None)
                    for bond_code, val in out_data.items():
                        if isinstance(val, dict):
                            sc = val.get("stock_code", "")
                            if sc and len(sc) == 6 and sc.isdigit():
                                bond_stocks.add(sc)
            except Exception:
                pass
        # 也从 spot 缓存中的 bond_price 提取正股代码
        if not bond_stocks:
            try:
                bp_path = _CACHE_FILES.get("bond_price")
                if bp_path and bp_path.exists():
                    bp_data = json.loads(bp_path.read_text())
                    bp_data.pop("_ts", None)
                    # bond_price 键是债券代码,需要另一种方式获取正股代码
                    # 跳过,无法从债券代码推导正股代码
            except Exception:
                pass

        # 优先可转债正股，但不再硬性截断到1500只，而是使用全A股列表
        # 从 stock_info_a_code_name 获取全A股作为第一来源
        try:
            import akshare as ak
            df_all = ak.stock_info_a_code_name()
            all_codes = [str(r.get("code", "")).strip() for _, r in df_all.iterrows()
                        if len(str(r.get("code", "")).strip()) == 6 and str(r.get("code", "")).strip().isdigit()]
        except Exception:
            all_codes = list(cached.keys()) if cached else []
        # bond_stocks 仅用于优先级排序，不改变总量
        try:
            df_b = ak.bond_zh_cov()
            bond_stocks = set(str(r.get("正股代码", "")).strip() for _, r in df_b.iterrows())
            bond_stocks = {c for c in bond_stocks if len(c) == 6 and c.isdigit()}
        except Exception:
            bond_stocks = set()
        # 排序：可转债正股优先
        priority = [c for c in all_codes if c in bond_stocks]
        others = [c for c in all_codes if c not in bond_stocks]
        all_codes = priority + others
        # 仅做日志提示，不截断
        logger.info(f"[HolderNum] {len(all_codes)} codes to fetch (priority={len(priority)} bond stocks)")

        # EM F10 ShareholderResearch API — with retry and UA rotation
        def _fetch_one(code: str):
            prefix = "SH" if code[0] in "456789" else "SZ"
            secucode = f"{prefix}{code}"
            for attempt in range(4):
                try:
                    r = requests.get(
                        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax",
                        params={"code": secucode},
                        timeout=12,
                        headers=_random_headers(),
                    )
                    if r.status_code != 200:
                        if attempt < 3:
                            time.sleep(1 + random.random() * 2)
                            continue
                        return None
                    j = r.json()
                    if j.get("status") is not None and j.get("status") != 0:
                        return None
                    if not j.get("gdrs"):
                        return None
                    first = j["gdrs"][0]
                    return {
                        "code": code,
                        "name": str(first.get("SECURITY_NAME", "")).strip(),
                        "holder_num": int(first.get("HOLDER_TOTAL_NUM", 0) or 0),
                        "stat_date": str(first.get("END_DATE", "")).strip()[:10],
                        "change_pct": _safe_float(first.get("TOTAL_NUM_RATIO", None)),
                        "avg_hold_shares": _safe_float(first.get("AVG_FREE_SHARES", None)),
                        "avg_hold_amt": _safe_float(first.get("AVG_HOLD_AMT", None)),
                        "hold_focus": str(first.get("HOLD_FOCUS", "")).strip(),
                        "hold_ratio_total": _safe_float(first.get("HOLD_RATIO_TOTAL", None)),
                    }
                except Exception:
                    if attempt < 3:
                        time.sleep(1 + random.random() * 2)
                        continue
                    return None
            return None

        # Also try alternate API: ak.stock_zh_a_gdhs (东方财富股东户数)
        def _fetch_alt(code: str):
            try:
                import akshare as ak_alt
                df_alt = ak_alt.stock_zh_a_gdhs(stock=code)
                if df_alt is not None and not df_alt.empty:
                    last = df_alt.iloc[-1]
                    hn = int(last.get("股东人数", last.get("股东户数", 0)) or 0)
                    if hn > 0:
                        return {
                            "code": code,
                            "name": str(last.get("股票简称", "")).strip(),
                            "holder_num": hn,
                            "stat_date": str(last.get("统计截止日期", str(last.get("日期", "")))).strip()[:10],
                            "change_pct": _safe_float(last.get("较上期变化", last.get("股东人数变化", None))),
                        }
            except Exception:
                pass
            return None

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time as _t

        # Phase 1: Bond stocks with higher parallelism (10 workers)
        if priority:
            logger.info(f"[HolderNum] Phase 1: Fetching {len(priority)} bond stocks with 10 workers...")
            with ThreadPoolExecutor(max_workers=10) as ex_bond:
                futures = {ex_bond.submit(_fetch_one, c): c for c in priority}
                done = 0
                for fut in as_completed(futures):
                    try:
                        v = fut.result(timeout=20)
                        if v and v.get("holder_num"):
                            result[v["code"]] = v
                    except Exception:
                        pass
                    done += 1
                    if done % 50 == 0:
                        _save_cache(cache_path, result)
                        logger.info(f"[HolderNum] Phase 1: {done}/{len(priority)}, {len(result)} ok")
            _save_cache(cache_path, result)
            logger.info(f"[HolderNum] Phase 1 done: {len(result)} stocks after bond priority")

        # Phase 2: Other stocks with moderate parallelism (5 workers)
        other_to_fetch = [c for c in others if c not in result]
        if other_to_fetch:
            with ThreadPoolExecutor(max_workers=5) as ex:
                # Batch 1: Primary API for other stocks
                futures = {ex.submit(_fetch_one, c): c for c in other_to_fetch}
                done = 0
                for fut in as_completed(futures):
                    try:
                        v = fut.result(timeout=20)
                        if v and v.get("holder_num"):
                            result[v["code"]] = v
                    except Exception:
                        pass
                    done += 1
                    if done % 25 == 0:
                        _save_cache(cache_path, result)
                        logger.info(f"[HolderNum] Phase 2: {done}/{len(other_to_fetch)}, {len(result)} ok")
                        _t.sleep(0.3 + random.random() * 1.0)

                # Batch 2: Try alternate API for stocks we missed
                missed = [c for c in other_to_fetch if c not in result][:150]
                logger.info(f"[HolderNum] Trying alternate API for {len(missed)} missed stocks...")
                fut2 = {ex.submit(_fetch_alt, c): c for c in missed}
                for f in as_completed(fut2):
                    try:
                        v = f.result(timeout=20)
                        if v and v.get("holder_num"):
                            result[v["code"]] = v
                    except Exception:
                        pass
                    _t.sleep(0.2 + random.random() * 0.5)

            _save_cache(cache_path, result)
        logger.info(f"[HolderNum] Total: {len(result)} stocks")

        if result:
            _save_cache(cache_path, result)
            return len(result)
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[HolderNum] Fetch failed: {e}")
        return len(cached or {})


# ============================================================
# Data source: Earnings forecast (业绩预告) cache
# ============================================================
def _refresh_earnings_forecast_cache():
    """业绩预告：类型 / 变动幅度 / 摘要
    数据源: ak.stock_yjyg_em (按报告期)
    """
    cache_path = _CACHE_FILES["earnings_forecast"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["earnings_forecast"], cached, cache_path) and len(cached or {}) > 100:
        logger.info(f"[EarnForecast] Cache fresh ({len(cached)} entries), skipping")
        return len(cached)
    try:
        import akshare as ak
        result = {}

        # 动态生成报告期列表：当前年份 + 前2年的4个季度
        from datetime import datetime as _dt
        _now = _dt.now()
        _year = _now.year
        _month = _now.month
        periods = []
        for y in range(_year, _year - 3, -1):
            for q_end in ["1231", "0930", "0630", "0331"]:
                p = f"{y}{q_end}"
                # 跳过未来的报告期（报告期所在季度必须已结束）
                q_month = int(q_end[:2])  # 季度结束月份
                if y < _year or (y == _year and q_month < _month):
                    periods.append(p)
                elif y == _year - 1 and q_end == "1231":
                    # 去年年报在当年1-4月公告，总是尝试
                    periods.append(p)
        if not periods:
            periods = [f"{_year-1}1231", f"{_year-1}0930", f"{_year-1}0630", f"{_year-1}0331"]
            logger.warning(f"[EarnForecast] Dynamic periods empty (year={_year}, month={_month}), using fallback")
        else:
            logger.info(f"[EarnForecast] Using {len(periods)} dynamic periods: {periods[:4]}...")

        for period in periods:
            try:
                df = ak.stock_yjyg_em(date=period)
                count = 0
                for _, r in df.iterrows():
                    code = str(r.get("股票代码", "")).strip()
                    if len(code) != 6 or not code.isdigit():
                        continue
                    if code in result:
                        continue
                    result[code] = {
                        "code": code,
                        "name": str(r.get("股票简称", "")).strip(),
                        "period": period,
                        "indicator": str(r.get("预测指标", "")).strip(),
                        "change_desc": str(r.get("业绩变动", "")).strip()[:200],
                        "predict_value": _safe_float(r.get("预测数值", None)),
                        "change_pct": _safe_float(r.get("业绩变动幅度", None)),
                        "reason": str(r.get("业绩变动原因", "")).strip()[:200],
                        "forecast_type": str(r.get("预告类型", "")).strip(),
                        "last_year_value": _safe_float(r.get("上年同期值", None)),
                        "announce_date": str(r.get("公告日期", "")).strip(),
                    }
                    count += 1
                logger.info(f"[EarnForecast] {period}: {count} entries")
            except Exception as e:
                logger.warning(f"[EarnForecast] {period} failed: {str(e)[:80]}")
                continue

        if result:
            _save_cache(cache_path, result)
            logger.info(f"[EarnForecast] Total: {len(result)} entries")
            return len(result)
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[EarnForecast] Fetch failed: {e}")
        return len(cached or {})


# ============================================================
# Data source: Earnings express (业绩快报) cache
# ============================================================
def _refresh_earnings_express_cache():
    """业绩快报：EPS / ROE / 营收 / 净利润
    数据源: ak.stock_yjkb_em (按报告期)
    """
    cache_path = _CACHE_FILES["earnings_express"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["earnings_express"], cached, cache_path) and len(cached or {}) > 100:
        logger.info(f"[EarnExpress] Cache fresh ({len(cached)} entries), skipping")
        return len(cached)
    try:
        import akshare as ak
        result = {}

        # 动态生成报告期列表：当前年份 + 前2年的4个季度
        from datetime import datetime as _dt
        _now = _dt.now()
        _year = _now.year
        _month = _now.month
        periods = []
        for y in range(_year, _year - 3, -1):
            for q_end in ["1231", "0930", "0630", "0331"]:
                p = f"{y}{q_end}"
                q_month = int(q_end[:2])
                if y < _year or (y == _year and q_month < _month):
                    periods.append(p)
                elif y == _year - 1 and q_end == "1231":
                    periods.append(p)
        if not periods:
            periods = [f"{_year-1}1231", f"{_year-1}0930", f"{_year-1}0630", f"{_year-1}0331"]
            logger.warning(f"[EarnExpress] Dynamic periods empty (year={_year}, month={_month}), using fallback")
        else:
            logger.info(f"[EarnExpress] Using {len(periods)} dynamic periods: {periods[:4]}...")

        for period in periods:
            try:
                df = ak.stock_yjkb_em(date=period)
                count = 0
                for _, r in df.iterrows():
                    code = str(r.get("股票代码", "")).strip()
                    if len(code) != 6 or not code.isdigit():
                        continue
                    if code in result:
                        continue
                    result[code] = {
                        "code": code,
                        "name": str(r.get("股票简称", "")).strip(),
                        "period": period,
                        "eps": _safe_float(r.get("每股收益", None)),
                        "revenue": _safe_float(r.get("营业收入-营业收入", None)),
                        "revenue_last_year": _safe_float(r.get("营业收入-去年同期", None)),
                        "revenue_yoy": _safe_float(r.get("营业收入-同比增长", None)),
                        "revenue_qoq": _safe_float(r.get("营业收入-季度环比增长", None)),
                        "net_profit": _safe_float(r.get("净利润-净利润", None)),
                        "net_profit_last_year": _safe_float(r.get("净利润-去年同期", None)),
                        "net_profit_yoy": _safe_float(r.get("净利润-同比增长", None)),
                        "net_profit_qoq": _safe_float(r.get("净利润-季度环比增长", None)),
                        "bps": _safe_float(r.get("每股净资产", None)),
                        "roe": _safe_float(r.get("净资产收益率", None)),
                        "industry": str(r.get("所处行业", "")).strip(),
                        "announce_date": str(r.get("公告日期", "")).strip(),
                    }
                    count += 1
                logger.info(f"[EarnExpress] {period}: {count} entries")
            except Exception as e:
                logger.warning(f"[EarnExpress] {period} failed: {str(e)[:80]}")
                continue

        if result:
            _save_cache(cache_path, result)
            logger.info(f"[EarnExpress] Total: {len(result)} entries")
            return len(result)
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[EarnExpress] Fetch failed: {e}")
        return len(cached or {})


# ============================================================
# Data source: Restricted release (限售解禁) cache
# ============================================================
def _refresh_restricted_release_cache():
    """限售解禁：未来 3 个月解禁计划

    数据源 (3 层):
      1. ak.stock_restricted_release_summary_em (每日解禁汇总 - market level)
      2. ak.stock_restricted_release_queue_em (排队 - event level)
      3. ak.stock_restricted_release_detail_em (个股详情 - per-stock,日期范围查询)
      4. ak.stock_restricted_release_stockholder_em (股东级明细 - per-stockholder)
    """
    cache_path = _CACHE_FILES["restricted_release"]
    cached = _load_cache(cache_path)
    if _fresh(_TTL["restricted_release"], cached, cache_path) and len(cached or {}) > 10:
        logger.info(f"[Restricted] Cache fresh ({len(cached)} entries), skipping")
        return len(cached)
    try:
        import akshare as ak
        from datetime import datetime, timedelta
        result = {}

        # 1. 解禁汇总 (按日)
        try:
            df = ak.stock_restricted_release_summary_em()
            count = 0
            for _, r in df.iterrows():
                date_s = str(r.get("解禁时间", "")).strip()
                if not date_s:
                    continue
                result[f"summary_{date_s}"] = {
                    "_summary": True,
                    "release_date": date_s,
                    "stock_count": _safe_int(r.get("当日解禁股票家数", None)),
                    "release_shares": _safe_float(r.get("解禁数量", None)),
                    "actual_shares": _safe_float(r.get("实际解禁数量", None)),
                    "actual_market_cap": _safe_float(r.get("实际解禁市值", None)),
                    "hs300_index": _safe_float(r.get("沪深300指数", None)),
                    "hs300_change": _safe_float(r.get("沪深300指数涨跌幅", None)),
                }
                count += 1
            logger.info(f"[Restricted] summary: {count} dates")
        except Exception as e:
            logger.warning(f"[Restricted] summary failed: {e}")

        # 2. 解禁排队 (event 级)
        try:
            df_q = ak.stock_restricted_release_queue_em()
            count = 0
            for _, r in df_q.iterrows():
                date_s = str(r.get("解禁时间", "")).strip()
                if not date_s:
                    continue
                key = f"queue_{date_s}_{count}"
                result[key] = {
                    "_queue": True,
                    "release_date": date_s,
                    "shareholder_count": _safe_int(r.get("解禁股东数", None)),
                    "release_shares": _safe_float(r.get("解禁数量", None)),
                    "actual_shares": _safe_float(r.get("实际解禁数量", None)),
                    "unreleased_shares": _safe_float(r.get("未解禁数量", None)),
                    "actual_market_cap": _safe_float(r.get("实际解禁数量市值", None)),
                    "ratio_total": _safe_float(r.get("占总市值比例", None)),
                    "ratio_circulate": _safe_float(r.get("占流通市值比例", None)),
                    "close_pre": _safe_float(r.get("解禁前一交易日收盘价", None)),
                    "lock_type": str(r.get("限售股类型", "")).strip(),
                    "pre_20d_change": _safe_float(r.get("解禁前20日涨跌幅", None)),
                    "post_20d_change": _safe_float(r.get("解禁后20日涨跌幅", None)),
                }
                count += 1
            logger.info(f"[Restricted] queue: {count} events")
        except Exception as e:
            logger.warning(f"[Restricted] queue failed: {e}")

        # 3. 个股解禁详情 (per-stock - 未来 6 个月日期范围)
        try:
            end_date = (datetime.now() + timedelta(days=180)).strftime("%Y%m%d")
            start_date = datetime.now().strftime("%Y%m%d")
            df_detail = ak.stock_restricted_release_detail_em(
                start_date=start_date, end_date=end_date
            )
            count_per_stock = 0
            for _, r in df_detail.iterrows():
                code = str(r.get("股票代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                # 用 code 作为 key - 同只股票多日多笔解禁,累加 amount 取最近日期
                prev = result.get(code)
                actual_mc = _safe_float(r.get("实际解禁市值", None))
                # amount 字段: 亿元 (供 data_enrich.py 直接读取)
                amount = round(actual_mc / 1e8, 4) if actual_mc and actual_mc > 0 else None
                new_entry = {
                    "code": code,
                    "name": str(r.get("股票简称", "")).strip(),
                    "release_date": str(r.get("解禁日期", "")).strip(),
                    "release_shares": _safe_float(r.get("解禁数量", None)),
                    "actual_shares": _safe_float(r.get("实际解禁数量", None)),
                    "actual_market_cap": actual_mc,
                    "amount": amount,
                    "ratio_total": _safe_float(r.get("占总股本比例", None) or r.get("占总市值比例", None)),
                    "ratio_circulate": _safe_float(r.get("占流通市值比例", None)),
                    "lock_type": str(r.get("限售股类型", "")).strip(),
                    "shareholder_count": _safe_int(r.get("股东人数", None) or r.get("解禁股东数", None)),
                    "announce_date": str(r.get("公告日期", "")).strip(),
                    "_per_stock": True,
                }
                # 保留最新的 (按 release_date), 累加 amount
                if prev is None:
                    result[code] = new_entry
                else:
                    # 累加解禁金额
                    if amount is not None:
                        prev_amount = prev.get("amount")
                        prev["amount"] = (prev_amount or 0) + amount
                    if new_entry["release_date"] >= prev.get("release_date", ""):
                        # 更新日期和市值,但保留累计 amount
                        saved_amount = prev.get("amount")
                        new_entry["amount"] = saved_amount
                        result[code] = new_entry
                count_per_stock += 1
            logger.info(f"[Restricted] detail_em (per-stock): {count_per_stock} rows for next 6 months")
        except Exception as e:
            logger.warning(f"[Restricted] detail_em failed: {e}")

        # 4. 股东级明细 (per-stockholder - 哪些股东在解禁)
        try:
            end_date = (datetime.now() + timedelta(days=90)).strftime("%Y%m%d")
            start_date = datetime.now().strftime("%Y%m%d")
            df_sh = ak.stock_restricted_release_stockholder_em(
                start_date=start_date, end_date=end_date
            )
            count_sh = 0
            for _, r in df_sh.iterrows():
                code = str(r.get("股票代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                # 把股东明细 merge 到现有 per-stock 记录上, 以"shareholders"字段存前5
                existing = result.get(code)
                if not existing:
                    continue
                if "shareholders" not in existing:
                    existing["shareholders"] = []
                if len(existing["shareholders"]) < 5:
                    existing["shareholders"].append({
                        "name": str(r.get("股东名称", "")).strip(),
                        "release_type": str(r.get("股份性质", "")).strip(),
                        "release_shares": _safe_float(r.get("解禁数量", None)),
                        "ratio_total": _safe_float(r.get("占总股本比例", None)),
                    })
                count_sh += 1
            logger.info(f"[Restricted] stockholder_em: {count_sh} rows for next 3 months")
        except Exception as e:
            logger.warning(f"[Restricted] stockholder_em failed: {e}")

        if result:
            _save_cache(cache_path, result)
            per_stock_count = sum(1 for k, v in result.items() if isinstance(v, dict) and v.get("_per_stock"))
            logger.info(
                f"[Restricted] Total: {len(result)} entries "
                f"({per_stock_count} per-stock)"
            )
            return len(result)
        logger.warning("[Restricted] No data from any source, keeping existing")
        return len(cached or {})
    except Exception as e:
        logger.warning(f"[Restricted] Fetch failed: {e}")
        return len(cached or {})


def main():
    parser = argparse.ArgumentParser(description="Data Enrichment Runner")
    parser.add_argument("--industry", action="store_true", help="Run industry cache")
    parser.add_argument("--spot", action="store_true", help="Run spot cache (may segfault)")
    parser.add_argument("--fin", action="store_true", help="Run financial cache")
    parser.add_argument("--fund-flow", action="store_true", help="Run fund flow cache")
    parser.add_argument("--debt", action="store_true", help="Run debt cache")
    parser.add_argument("--vol", action="store_true", help="Run volatility cache")
    parser.add_argument("--buyback", action="store_true", help="Run buyback cache")
    parser.add_argument("--mgmt", action="store_true", help="Run mgmt cache")
    parser.add_argument("--outstanding", action="store_true", help="Run bond outstanding cache")
    parser.add_argument("--call-status", action="store_true", help="Run call status cache")
    parser.add_argument("--bond-price", action="store_true", help="Run bond price cache (JISILU)")
    parser.add_argument("--pledge", action="store_true", help="Run pledge ratio cache")
    parser.add_argument("--momentum", action="store_true", help="Run momentum cache")
    parser.add_argument("--event", action="store_true", help="Run event cache")
    parser.add_argument("--stock-names", action="store_true", help="Run stock names cache")
    parser.add_argument("--concept", action="store_true", help="Run concept board cache (EastMoney+THS)")
    parser.add_argument("--north", action="store_true", help="Run north-bound capital cache")
    parser.add_argument("--margin", action="store_true", help="Run margin trading cache")
    parser.add_argument("--lhb", action="store_true", help="Run long-hu-bang (龙虎榜) cache")
    parser.add_argument("--block-trade", action="store_true", help="Run block trade (大宗交易) cache")
    parser.add_argument("--holder-num", action="store_true", help="Run shareholder count cache")
    parser.add_argument("--earnings-forecast", action="store_true", help="Run earnings forecast cache")
    parser.add_argument("--earnings-express", action="store_true", help="Run earnings express cache")
    parser.add_argument("--restricted-release", action="store_true", help="Run restricted release cache")
    parser.add_argument("--all", action="store_true", help="Run all caches")
    args = parser.parse_args()

    if not any(vars(args).values()):
        args.all = True

    tasks = []
    if args.all or args.industry:
        tasks.append(("Industry", _build_industry_cache))
    if args.all or args.spot:
        tasks.append(("Spot", _refresh_spot_cache))
    if args.all or args.fin:
        tasks.append(("Fin", _refresh_fin_cache))
    if args.all or args.fund_flow:
        tasks.append(("FundFlow", _refresh_fund_flow_cache))
    if args.all or args.debt:
        tasks.append(("Debt", _refresh_debt_cache))
    if args.all or args.vol:
        tasks.append(("Vol", _refresh_volatility_cache))
    if args.all or args.buyback:
        tasks.append(("Buyback", _refresh_buyback_cache))
    if args.all or args.mgmt:
        tasks.append(("Mgmt", _refresh_mgmt_cache))
    if args.all or args.outstanding:
        tasks.append(("Outstanding", _refresh_bond_outstanding_cache))
    if args.all or args.call_status:
        tasks.append(("CallStatus", _refresh_call_status_cache))
    if args.all or getattr(args, 'bond_price', False):
        tasks.append(("BondPrice", _refresh_bond_price_cache))
    if args.all or args.pledge:
        tasks.append(("Pledge", _refresh_pledge_cache))
    if args.all or args.momentum:
        tasks.append(("Momentum", _refresh_momentum_cache))
    if args.all or args.event:
        tasks.append(("Event", _refresh_event_cache))
    if args.all or getattr(args, 'stock_names', False):
        tasks.append(("StockNames", _refresh_stock_name_cache))
    if args.all or getattr(args, 'concept', False):
        tasks.append(("Concept", _build_concept_cache))
    if args.all or getattr(args, 'north', False):
        tasks.append(("North", _refresh_north_cache))
    if args.all or getattr(args, 'margin', False):
        tasks.append(("Margin", _refresh_margin_cache))
    if args.all or getattr(args, 'lhb', False):
        tasks.append(("LHB", _refresh_lhb_cache))
    if args.all or getattr(args, 'block_trade', False):
        tasks.append(("BlockTrade", _refresh_block_trade_cache))
    if args.all or getattr(args, 'holder_num', False):
        tasks.append(("HolderNum", _refresh_holder_num_cache))
    if args.all or getattr(args, 'earnings_forecast', False):
        tasks.append(("EarnForecast", _refresh_earnings_forecast_cache))
    if args.all or getattr(args, 'earnings_express', False):
        tasks.append(("EarnExpress", _refresh_earnings_express_cache))
    if args.all or getattr(args, 'restricted_release', False):
        tasks.append(("Restricted", _refresh_restricted_release_cache))

    logger.info(f"Starting {len(tasks)} data enrichment tasks...")
    for name, fn in tasks:
        t0 = time.time()
        try:
            logger.info(f"[{name}] Starting...")
            count = fn()
            elapsed = time.time() - t0
            logger.info(f"[{name}] Done: {count}")
            count_i = count if isinstance(count, int) else 0
            status = "empty" if count_i == 0 else "ok"
            _record_runner_metric(fn.__name__, elapsed, count_i, status=status)
        except KeyboardInterrupt:
            logger.warning(f"[{name}] Interrupted")
            _record_runner_metric(fn.__name__, time.time() - t0, 0, status="error", error="interrupted")
            break
        except SystemExit:
            raise
        except Exception as e:
            logger.error(f"[{name}] Failed: {e}")
            _record_runner_metric(fn.__name__, time.time() - t0, 0, status="error", error=str(e)[:200])
        except:  # noqa: E722 - Catch segfault/OS errors
            logger.error(f"[{name}] Crashed (possible AKShare segfault)")
            _record_runner_metric(fn.__name__, time.time() - t0, 0, status="error", error="segfault/os crash")

    logger.info("All enrichment tasks completed")


if __name__ == "__main__":
    main()