"""
璇玑十二因子指增策略 API 接口
提供: 12因子排名、单券因子详情、5态市场权重、Delta对冲候选、Greeks分解
"""
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional
import pandas as pd
import numpy as np
import time
import hashlib
import logging
from app.engine.data_enrich_utils import safe_float, safe_int

router = APIRouter(prefix="/xuanji", tags=["璇玑十二因子"])
logger = logging.getLogger(__name__)

# 内存缓存 — LRU风格
_cache: dict = {}
_CACHE_TTL = 180  # 排名等计算型数据缓存3分钟
_LONG_CACHE_TTL = 600  # 静态/半静态数据缓存10分钟
_MAX_CACHE_SIZE = 64  # LRU: 最多保留64个条目


def _lru_touch(key: str):
    """将 key 移动到字典末尾 (模拟 LRU 顺序)"""
    if key in _cache:
        entry = _cache.pop(key)
        _cache[key] = entry


def _get_cache_key(prefix: str, **kwargs) -> str:
    sorted_params = sorted(kwargs.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
    hash_key = hashlib.md5(param_str.encode()).hexdigest()[:16]
    return f"{prefix}:{hash_key}"


def _get_cached(key: str, ttl: int = None) -> Optional[dict]:
    if key in _cache:
        _lru_touch(key)
        entry = _cache[key]
        effective_ttl = ttl or entry.get('ttl', _CACHE_TTL)
        if time.time() - entry['ts'] < effective_ttl:
            return entry['data']
        else:
            del _cache[key]
    return None


def _set_cache(key: str, data: dict, ttl: int = None):
    _cleanup_cache()
    _cache[key] = {'ts': time.time(), 'data': data, 'ttl': ttl or _CACHE_TTL}


def _cleanup_cache():
    now = time.time()
    # 清除过期条目 (2倍 TTL)
    expired = [k for k, v in _cache.items() if now - v['ts'] >= v.get('ttl', _CACHE_TTL) * 2]
    for k in expired:
        del _cache[k]
    # LRU 淘汰: 超过最大容量时移除最旧的 25%
    overflow = len(_cache) - _MAX_CACHE_SIZE
    if overflow > 0:
        keys = list(_cache.keys())
        for k in keys[:overflow]:
            del _cache[k]


_ENRICH_COLS = [
    'roe', 'gpm', 'cagr', 'debt_ratio', 'pe', 'pb', 'iv',
    'buyback_amount', 'mgmt_buy_price', 'current_ratio',
    'turnover_rate', 'net_capital_flow', 'net_capital_flow_pct',
    'outstanding_scale', 'pledge_ratio',
    'net_super_flow', 'net_big_flow', 'stock_name',
    'momentum_5d', 'momentum_10d', 'momentum_20d', 'momentum_60d',
    'event_score', 'event_detail', 'call_status',
]


def _build_row_from_bond(b) -> dict:
    row = {
        "code": b.code,
        "name": b.name,
        "stock_code": getattr(b, 'stock_code', ''),
        "price": b.price,
        "premium_ratio": b.premium_ratio if b.premium_ratio is not None else 0.0,
        "volume": b.volume or 0,
        "dual_low": b.dual_low,
        "change_pct": b.change_pct if b.change_pct is not None else 0.0,
        "ytm": b.ytm,
        "remaining_years": b.remaining_years,
        "conversion_value": b.conversion_value,
        "stock_price": b.stock_price,
        "industry": getattr(b, 'industry', None) or "其他",
        "rating": getattr(b, 'rating', None) or "未评级",
    }
    for col in _ENRICH_COLS:
        if hasattr(b, col):
            row[col] = getattr(b, col, None)
    return row


def _compute_hv_estimate(df: pd.DataFrame) -> pd.DataFrame:
    """计算历史波动率(HV) - 优先使用90日真实波动率, 后备使用单日涨跌幅年化近似
    标准化: 涨跌幅*√252*0.6 (|Z|*√T/√n) 与 IV 公式保持一致
    """
    df = df.copy()
    if df.empty:
        df['hv'] = pd.Series(dtype=float)
        return df

    # 保证 'hv' 列存在
    if 'hv' not in df.columns:
        df['hv'] = np.nan

    # 优先使用 data_enrich 缓存的90日真实波动率 (vectorized)
    if 'stock_code' in df.columns:
        try:
            from app.engine.data_enrich import get_volatility
            stock_codes = df['stock_code'].fillna('').astype(str).str.strip()
            vol_map = {}
            for code in stock_codes.unique():
                if code:
                    vol = get_volatility(code)
                    if vol is not None and vol > 0:
                        vol_map[code] = vol
            if vol_map:
                mapped = stock_codes.map(vol_map)
                fill_mask = df['hv'].isna() | (df['hv'] <= 0)
                df.loc[fill_mask & mapped.notna(), 'hv'] = mapped[fill_mask & mapped.notna()]
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
            pass

    # 对剩余没有HV的行，使用单日涨跌幅年化近似 (与 IV 同公式)
    hv_missing = df['hv'].isna() | (df['hv'] <= 0)
    if hv_missing.any() and 'change_pct' in df.columns:
        chg = pd.to_numeric(df.loc[hv_missing, 'change_pct'], errors='coerce').fillna(0)
        df.loc[hv_missing, 'hv'] = (chg.abs() * np.sqrt(252) * 0.6).clip(lower=3, upper=80)

    df['hv'] = df['hv'].fillna(20.0).clip(lower=3, upper=80)
    return df


# 5态市场权重配置
MARKET_WEIGHTS = {
    "extreme_bull": {"dual_low": 0.14, "momentum": 0.28, "hv": 0.14, "quality": 0.19, "valuation": 0.10, "ytm": 0.05, "remaining_years": 0.04, "event": 0.04, "delta": 0.02},
    "mild_bull":   {"dual_low": 0.24, "momentum": 0.24, "hv": 0.14, "quality": 0.14, "valuation": 0.10, "ytm": 0.05, "remaining_years": 0.04, "event": 0.03, "delta": 0.02},
    "neutral":     {"dual_low": 0.29, "momentum": 0.10, "hv": 0.19, "quality": 0.19, "valuation": 0.10, "ytm": 0.04, "remaining_years": 0.04, "event": 0.03, "delta": 0.02},
    "mild_bear":   {"dual_low": 0.38, "momentum": 0.05, "hv": 0.24, "quality": 0.14, "valuation": 0.09, "ytm": 0.00, "remaining_years": 0.05, "event": 0.03, "delta": 0.02},
    "extreme_bear":{"dual_low": 0.47, "momentum": 0.00, "hv": 0.29, "quality": 0.09, "valuation": 0.05, "ytm": 0.00, "remaining_years": 0.06, "event": 0.02, "delta": 0.02},
}

FACTOR_NAMES = {
    "dual_low": "双低值",
    "momentum": "多时帧动量",
    "hv": "历史波动率",
    "quality": "正股质量",
    "valuation": "估值因子",
    "ytm": "到期收益率",
    "remaining_years": "剩余期限",
    "event": "事件驱动",
    "delta": "Delta对冲",
}


def _normalize_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """
    横截面Z-score归一化 (v8 style): winsorize 5% + Z-score + rank归一化 [0,1]
    比纯rank保留更多分布信息。
    ascending=True: 低值→高分 (如低溢价率)
    ascending=False: 高值→高分 (如高动量)
    """
    s = series.dropna()
    if len(s) < 3:
        return pd.Series(0.5, index=series.index)
    
    # winsorize 5%
    lo, hi = s.quantile(0.05), s.quantile(0.95)
    if pd.isna(lo) or pd.isna(hi) or lo >= hi:
        lo, hi = s.min(), s.max()
    w = s.clip(lo, hi)
    
    mu, sigma = w.mean(), w.std()
    if sigma <= 0 or pd.isna(sigma):
        return pd.Series(0.5, index=series.index)
    
    z = (w - mu) / sigma
    # Sigmoid mapping: 1 / (1 + exp(-z*s))
    # ascending=True: negate z so low input values → high z → high sigmoid score
    if ascending:
        z = -z
    sig = 1.0 / (1.0 + np.exp(-z * 1.5))
    
    # Build result preserving original index, NaN→0.5
    result = pd.Series(0.5, index=series.index)
    result.loc[sig.index] = sig
    return result


def _detect_market_state(df: pd.DataFrame) -> str:
    if df.empty:
        return "neutral"
    median_price = df['price'].median()
    premium_col = 'premium_ratio' if 'premium_ratio' in df.columns else None
    median_premium = df[premium_col].median() if premium_col and df[premium_col].notna().any() else 30.0
    if median_price > 140 and median_premium < 15:
        return "extreme_bull"
    if median_price > 125 and median_premium < 35:
        return "mild_bull"
    if median_price < 105:
        return "extreme_bear"
    if median_price < 110 or median_premium > 50:
        return "mild_bear"
    return "neutral"


def _compute_xuanji_scores(df: pd.DataFrame, market_state: str, vol_adjust: float = 0.85) -> pd.DataFrame:
    """计算璇玑十二因子综合评分"""
    df = df.copy()

    weights = MARKET_WEIGHTS.get(market_state, MARKET_WEIGHTS['neutral'])

    if 'dual_low' in df.columns:
        dl_median = df['dual_low'].median()
        if pd.isna(dl_median):
            dl_median = 150.0
        df['dual_low'] = df['dual_low'].fillna(dl_median)
    score_dual_low = _normalize_rank(df['dual_low'], ascending=True)
    hv_median = df['hv'].median() if 'hv' in df.columns and df['hv'].notna().any() else 20.0
    if 'hv' in df.columns:
        df['hv'] = df['hv'].fillna(hv_median)
        df.loc[df['hv'] <= 0, 'hv'] = hv_median
    score_hv = _normalize_rank(df['hv'], ascending=True)

    if 'change_pct' in df.columns:
        if 'momentum_20d' in df.columns and df['momentum_20d'].notna().any():
            m20 = pd.to_numeric(df['momentum_20d'], errors='coerce')
            m10 = pd.to_numeric(df.get('momentum_10d', m20), errors='coerce')
            m5 = pd.to_numeric(df.get('momentum_5d', m10), errors='coerce')
            m60 = pd.to_numeric(df.get('momentum_60d', m20), errors='coerce')
            m_median = m20.median()
            if pd.isna(m_median):
                m_median = 0
            parts = []
            for m in [m5, m10, m20, m60]:
                parts.append(m.fillna(m_median))
            stacked = pd.DataFrame(parts).T
            valid = stacked.notna().sum(axis=1).clip(lower=1)
            composite_mom = stacked.sum(axis=1) / valid
            score_momentum = _normalize_rank(composite_mom, ascending=False)
        else:
            score_momentum = _normalize_rank(df['change_pct'].fillna(0), ascending=False)
    else:
        score_momentum = pd.Series(0.5, index=df.index)

    if 'ytm' in df.columns and df['ytm'].notna().any():
        ytm_median = df['ytm'].median()
        if pd.isna(ytm_median):
            ytm_median = 0
        score_ytm = _normalize_rank(df['ytm'].fillna(ytm_median), ascending=False)
    else:
        score_ytm = pd.Series(0.5, index=df.index)

    if 'remaining_years' in df.columns and df['remaining_years'].notna().any():
        ry_median = df['remaining_years'].median()
        if pd.isna(ry_median):
            ry_median = 3
        score_remaining_years = _normalize_rank(df['remaining_years'].fillna(ry_median), ascending=False)
    else:
        score_remaining_years = pd.Series(0.5, index=df.index)

    quality_parts = []
    has_quality_data = any(col in df.columns and df[col].notna().any() for col in ['roe', 'gpm', 'cagr', 'debt_ratio', 'current_ratio', 'turnover_rate'])
    if has_quality_data:
        for col, asc in [('roe', False), ('gpm', False), ('cagr', False), ('debt_ratio', True), ('current_ratio', False), ('turnover_rate', False)]:
            if col in df.columns and df[col].notna().any():
                col_median = df[col].median()
                if pd.isna(col_median):
                    col_median = 0
                col_data = pd.to_numeric(df[col], errors='coerce').fillna(col_median)
                quality_parts.append(_normalize_rank(col_data, ascending=asc))
    score_quality = sum(quality_parts) / len(quality_parts) if quality_parts else pd.Series(0.5, index=df.index)

    valuation_parts = []
    has_val_data = any(col in df.columns and df[col].notna().any() for col in ['pe', 'pb'])
    if has_val_data:
        for col, asc in [('pe', True), ('pb', True)]:
            if col in df.columns and df[col].notna().any():
                col_median = df[col].median()
                if pd.isna(col_median):
                    col_median = 50
                col_data = pd.to_numeric(df[col], errors='coerce').fillna(col_median)
                valuation_parts.append(_normalize_rank(col_data, ascending=asc))
    score_valuation = sum(valuation_parts) / len(valuation_parts) if valuation_parts else pd.Series(0.5, index=df.index)

    event_parts = []
    has_event_data = any(col in df.columns and df[col].notna().any() for col in ['buyback_amount', 'mgmt_buy_price', 'event_score'])
    if has_event_data:
        for col in ['buyback_amount', 'mgmt_buy_price', 'event_score']:
            if col in df.columns and df[col].notna().any():
                col_median = pd.to_numeric(df[col], errors='coerce').median()
                if pd.isna(col_median):
                    col_median = 0
                col_data = pd.to_numeric(df[col], errors='coerce').fillna(col_median)
                event_parts.append(_normalize_rank(col_data, ascending=False))
    score_event = sum(event_parts) / len(event_parts) if event_parts else pd.Series(0.5, index=df.index)

    score_delta = pd.Series(0.5, index=df.index)
    score_delta_available = 'iv' in df.columns and df['iv'].notna().any() and 'hv' in df.columns
    if score_delta_available:
        iv_raw = pd.to_numeric(df['iv'], errors='coerce').fillna(0)
        hv_data = df['hv']
        iv_effective = np.maximum(iv_raw, hv_data * 1.2 + 3.0)
        iv_hv_diff = (iv_effective - hv_data).clip(lower=0)
        score_delta = _normalize_rank(iv_hv_diff, ascending=False)

    active_weights = {}
    active_weights['dual_low'] = weights['dual_low']
    active_weights['momentum'] = weights['momentum']
    active_weights['hv'] = weights['hv']
    active_weights['ytm'] = weights['ytm']
    active_weights['remaining_years'] = weights['remaining_years']
    if has_quality_data:
        active_weights['quality'] = weights['quality']
    if has_val_data:
        active_weights['valuation'] = weights['valuation']
    if has_event_data:
        active_weights['event'] = weights['event']
    if score_delta_available:
        active_weights['delta'] = weights['delta']

    total_w = sum(active_weights.values())
    if total_w > 0:
        for k in active_weights:
            active_weights[k] /= total_w
    else:
        active_weights = {'dual_low': 0.3, 'momentum': 0.15, 'hv': 0.2, 'ytm': 0.1, 'remaining_years': 0.1, 'quality': 0.1, 'valuation': 0.05}

    hv_median = df['hv'].median() if 'hv' in df.columns and df['hv'].notna().any() else 0
    if hv_median <= 0:
        hv_median = df['hv'].max() if 'hv' in df.columns and df['hv'].notna().any() else 0
    if hv_median > 0 and 'hv' in df.columns:
        vol_factor = 1.0 / (1.0 + (df['hv'] / hv_median - 1.0).clip(lower=0) * (1 - vol_adjust))
    else:
        vol_factor = pd.Series(1.0, index=df.index)

    composite = (
        score_dual_low * active_weights.get('dual_low', 0) +
        score_momentum * active_weights.get('momentum', 0) +
        score_hv * active_weights.get('hv', 0) +
        score_quality * active_weights.get('quality', 0) +
        score_valuation * active_weights.get('valuation', 0) +
        score_ytm * active_weights.get('ytm', 0) +
        score_remaining_years * active_weights.get('remaining_years', 0) +
        score_event * active_weights.get('event', 0) +
        score_delta * active_weights.get('delta', 0)
    ) * vol_factor

    df['score'] = composite.clip(0, 1)
    score_nan = df['score'].isna()
    if score_nan.any():
        df.loc[score_nan, 'score'] = 0.5
    df['score_dual_low'] = score_dual_low
    df['score_momentum'] = score_momentum
    df['score_hv'] = score_hv
    df['score_quality'] = score_quality
    df['score_valuation'] = score_valuation
    df['score_ytm'] = score_ytm
    df['score_remaining_years'] = score_remaining_years
    df['score_event'] = score_event
    df['score_delta'] = score_delta
    df['vol_factor'] = vol_factor
    df.attrs['active_weights'] = active_weights
    return df


@router.get("/ranking")
async def get_xuanji_ranking(
    request: Request,
    top_n: int = Query(50, ge=10, le=200, description="返回前N名"),
    market_state: str = Query("mild_bull", description="市场状态: extreme_bull/mild_bull/neutral/mild_bear/extreme_bear/auto"),
    max_premium: float = Query(50.0, ge=10, le=100),
    min_price: float = Query(90.0, ge=70, le=120),
    max_price: float = Query(150.0, ge=120, le=200),
    vol_adjust: float = Query(0.85, ge=0.5, le=1.0, description="波动率调权系数"),
):
    """璇玑十二因子评分排名"""
    cache_key = _get_cache_key(
        "xuanji_ranking", top_n=top_n, market_state=market_state,
        max_premium=max_premium, min_price=min_price, max_price=max_price,
        vol_adjust=vol_adjust,
    )
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"total": 0, "items": [], "market_state_detected": "neutral"}

        rows = [_build_row_from_bond(b) for b in bonds]

        if not rows:
            return {"total": 0, "total_unfiltered": 0, "items": [], "market_state_detected": "neutral"}

        df_full = pd.DataFrame(rows)
        total_unfiltered = len(df_full)

        df_full = _compute_hv_estimate(df_full)
        detected_state = _detect_market_state(df_full)

        df = df_full[
            (df_full['premium_ratio'] >= 0) &
            (df_full['premium_ratio'] <= max_premium) &
            (df_full['price'] >= min_price) &
            (df_full['price'] <= max_price) &
            (df_full['price'] > 0)
        ]
        actual_state = detected_state if market_state == "auto" else market_state
        if actual_state not in MARKET_WEIGHTS:
            actual_state = "neutral"

        # 计算综合评分
        df = _compute_xuanji_scores(df, actual_state, vol_adjust)
        active_weights = df.attrs.get('active_weights', MARKET_WEIGHTS[actual_state])

        # 按分数降序
        df = df.sort_values('score', ascending=False).reset_index(drop=True)
        top_df = df.head(top_n)

        items = []
        for idx, row in top_df.iterrows():
            def _r2(key, _r=row):
                v = _r.get(key)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return None
                return round(float(v), 2)
            items.append({
                "rank": idx + 1,
                "code": row['code'],
                "name": row['name'],
                "price": round(float(row['price']), 3),
                "premium_ratio": round(float(row['premium_ratio']), 2),
                "dual_low": round(float(row['dual_low']), 2),
                "volume": float(row.get('volume') or 0),
                "change_pct": round(float(row.get('change_pct', 0)), 2),
                "ytm": round(float(row['ytm']), 2) if pd.notna(row.get('ytm')) else None,
                "remaining_years": round(float(row['remaining_years']), 2) if pd.notna(row.get('remaining_years')) else None,
                "hv": round(float(row['hv']), 2),
                "industry": row.get('industry', '其他'),
                "rating": row.get('rating', 'AA'),
                "stock_code": row.get('stock_code', ''),
                "pe": _r2('pe'),
                "pb": _r2('pb'),
                "roe": _r2('roe'),
                "gpm": _r2('gpm'),
                "cagr": _r2('cagr'),
                "debt_ratio": _r2('debt_ratio'),
                "current_ratio": _r2('current_ratio'),
                "iv": _r2('iv'),
                "buyback_amount": _r2('buyback_amount'),
                "mgmt_buy_price": _r2('mgmt_buy_price'),
                "outstanding_scale": _r2('outstanding_scale'),
                "turnover_rate": _r2('turnover_rate'),
                "net_capital_flow": _r2('net_capital_flow'),
                "net_capital_flow_pct": _r2('net_capital_flow_pct'),
                "net_super_flow": _r2('net_super_flow'),
                "net_big_flow": _r2('net_big_flow'),
                "momentum_5d": _r2('momentum_5d'),
                "momentum_10d": _r2('momentum_10d'),
                "momentum_20d": _r2('momentum_20d'),
                "momentum_60d": _r2('momentum_60d'),
                "pledge_ratio": _r2('pledge_ratio'),
                "event_score": _r2('event_score'),
                "event_detail": row.get('event_detail'),
                "score": round(float(row['score']), 4),
                "score_dual_low": round(float(row['score_dual_low']), 4),
                "score_momentum": round(float(row['score_momentum']), 4),
                "score_hv": round(float(row['score_hv']), 4),
                "score_quality": round(float(row['score_quality']), 4),
                "score_valuation": round(float(row['score_valuation']), 4),
                "score_ytm": round(float(row['score_ytm']), 4),
                "score_event": round(float(row['score_event']), 4),
                "score_delta": round(float(row['score_delta']), 4),
                "score_remaining_years": round(float(row['score_remaining_years']), 4),
            })

        result = {
            "total": int(len(df)),
            "total_unfiltered": int(total_unfiltered),
            "returned": int(len(items)),
            "market_state_requested": market_state,
            "market_state_detected": detected_state,
            "market_state_actual": actual_state,
            "market_weights": active_weights,
            "factor_names": FACTOR_NAMES,
            "params": {
                "top_n": top_n,
                "max_premium": max_premium,
                "min_price": min_price,
                "max_price": max_price,
                "vol_adjust": vol_adjust,
            },
            "items": items,
            "cached": False,
        }

        _set_cache(cache_key, result)
        return result

    except Exception as e:
        logger.exception("璇玑排名计算失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/single/{code}")
async def get_xuanji_single(
    request: Request,
    code: str,
    market_state: str = Query("mild_bull"),
    max_premium: float = Query(80.0, ge=10, le=100),
    min_price: float = Query(80.0, ge=70, le=120),
    max_price: float = Query(180.0, ge=120, le=200),
    vol_adjust: float = Query(0.85, ge=0.5, le=1.0, description="波动率调权系数"),
):
    """单只转债的璇玑十二因子详细评分 (基于全市场相对排名)"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        target = next((b for b in bonds if b.code == code), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"转债 {code} 不存在")

        # Build full universe DataFrame for meaningful relative ranking
        rows = [_build_row_from_bond(b) for b in bonds]

        df = pd.DataFrame(rows)
        df = _compute_hv_estimate(df)

        # Detect market state BEFORE filtering for meaningful distribution
        actual_state = market_state if market_state != 'auto' else _detect_market_state(df)
        if actual_state not in MARKET_WEIGHTS:
            actual_state = 'neutral'

        # Filter (consistent with ranking endpoint)
        df = df[(df['premium_ratio'] >= 0) & (df['premium_ratio'] <= max_premium) & (df['price'] >= min_price) & (df['price'] <= max_price) & (df['price'] > 0)]
        if df.empty:
            raise HTTPException(status_code=404, detail="筛选后无有效数据")

        weights = MARKET_WEIGHTS.get(actual_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, actual_state, vol_adjust)

        active_weights = df.attrs.get('active_weights', weights)

        # Extract target bond from scored universe
        target_rows = df[df['code'] == code]
        if target_rows.empty:
            raise HTTPException(status_code=404, detail=f"转债 {code} 未通过筛选条件，无法计算相对评分")
        row = target_rows.iloc[0]

        # Compute rank in full universe
        full_rank = int((df['score'] > row['score']).sum()) + 1

        factor_scores = {
            "dual_low": {"value": round(float(row['score_dual_low']), 4), "weight": active_weights.get('dual_low', weights['dual_low'])},
            "momentum": {"value": round(float(row['score_momentum']), 4), "weight": active_weights.get('momentum', weights['momentum'])},
            "hv":       {"value": round(float(row['score_hv']), 4), "weight": active_weights.get('hv', weights['hv'])},
            "quality":  {"value": round(float(row['score_quality']), 4), "weight": active_weights.get('quality', weights['quality'])},
            "valuation": {"value": round(float(row['score_valuation']), 4), "weight": active_weights.get('valuation', weights['valuation'])},
            "ytm":      {"value": round(float(row['score_ytm']), 4), "weight": active_weights.get('ytm', weights['ytm'])},
            "remaining_years": {"value": round(float(row['score_remaining_years']), 4), "weight": active_weights.get('remaining_years', weights['remaining_years'])},
            "event":    {"value": round(float(row['score_event']), 4), "weight": active_weights.get('event', weights['event'])},
            "delta":    {"value": round(float(row['score_delta']), 4), "weight": active_weights.get('delta', weights['delta'])},
        }

        greeks = _compute_greeks(target)

        return {
            "code": target.code,
            "name": target.name,
            "market_state": actual_state,
            "market_weights": active_weights,
            "factor_names": FACTOR_NAMES,
            "factor_scores": factor_scores,
            "composite_score": round(float(row['score']), 4),
            "rank_in_universe": full_rank,
            "total_in_universe": len(df),
            "vol_factor": round(float(row['vol_factor']), 4),
            "basic_info": {
                "price": round(float(target.price), 2),
                "premium_ratio": round(float(target.premium_ratio), 2),
                "dual_low": round(float(target.dual_low), 2),
                "change_pct": round(float(target.change_pct or 0), 2),
                "ytm": round(float(target.ytm), 2) if target.ytm else None,
                "remaining_years": round(float(target.remaining_years), 2) if target.remaining_years else None,
                "volume": float(target.volume or 0),
                "stock_price": round(float(target.stock_price), 2) if target.stock_price else None,
                "conversion_value": round(float(target.conversion_value), 2) if target.conversion_value else None,
                "industry": getattr(target, 'industry', None) or "其他",
                "rating": getattr(target, 'rating', None) or "AA",
                "stock_code": getattr(target, 'stock_code', ''),
                "pe": getattr(target, 'pe', None),
                "pb": getattr(target, 'pb', None),
                "roe": getattr(target, 'roe', None),
                "gpm": getattr(target, 'gpm', None),
                "cagr": getattr(target, 'cagr', None),
                "debt_ratio": getattr(target, 'debt_ratio', None),
                "current_ratio": getattr(target, 'current_ratio', None),
                "iv": getattr(target, 'iv', None),
                "turnover_rate": getattr(target, 'turnover_rate', None),
                "net_capital_flow": getattr(target, 'net_capital_flow', None),
                "net_capital_flow_pct": getattr(target, 'net_capital_flow_pct', None),
                "net_super_flow": getattr(target, 'net_super_flow', None),
                "net_big_flow": getattr(target, 'net_big_flow', None),
                "buyback_amount": getattr(target, 'buyback_amount', None),
                "mgmt_buy_price": getattr(target, 'mgmt_buy_price', None),
                "outstanding_scale": getattr(target, 'outstanding_scale', None),
            },
            "greeks": greeks,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"璇玑单券评分失败: {code}")
        raise HTTPException(status_code=500, detail=str(e))


def _compute_greeks(bond) -> dict:
    """计算Greeks近似值 (基于转换价值/价格 推导delta, IV 优先使用 data_enrich 实际值)"""
    try:
        price = float(bond.price) if bond.price else 0
        if price <= 0:
            return {"delta": 0.5, "gamma": 0.01, "vega": 0.5, "theta": -0.001, "iv": 30.0, "iv_source": "estimated"}

        conversion_value = float(bond.conversion_value) if bond.conversion_value else price * 0.9
        stock_price = float(bond.stock_price) if bond.stock_price else price * 0.8

        # Delta: 转换价值/价格 决定股性
        delta = min(0.95, max(0.05, conversion_value / price))
        # Gamma: 凸性，Delta的二阶导
        gamma = delta * (1 - delta) / price
        # Vega: 波动率敏感度 (年化)
        vega = delta * np.sqrt(0.25 / 365) * 100
        # Theta: 时间损耗 (负值代表衰减，delta<1时为正贡献)
        theta = -(1 - delta) * 0.01 / 365 if delta < 1 else -0.001

        # IV: 优先使用 data_enrich 计算的真实波动率，否则用 delta 近似
        actual_iv = getattr(bond, 'iv', None)
        actual_iv_source = getattr(bond, 'iv_source', None)
        try:
            iv_val = float(actual_iv) if isinstance(actual_iv, (int, float)) else None
            if iv_val is not None and iv_val > 0:
                iv = round(iv_val, 2)
                iv_source = actual_iv_source if actual_iv_source in ("actual", "hv_proxy") else "hv_proxy"
            else:
                chg = abs(float(getattr(bond, 'change_pct', 0) or 0))
                hv_est = max(3.0, min(80.0, chg * np.sqrt(252) * 0.6)) if chg > 0 else 20.0
                iv = round(hv_est * 1.3 + 5.0, 2)
                iv_source = "estimated"
        except (TypeError, ValueError):
            iv = round(delta * 40 + 10, 2)
            iv_source = "estimated"

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "vega": round(vega, 4),
            "theta": round(theta, 6),
            "iv": iv,
            "iv_source": iv_source,
        }
    except Exception:
        return {"delta": 0.5, "gamma": 0.01, "vega": 0.5, "theta": -0.001, "iv": 30.0, "iv_source": "fallback"}


@router.get("/delta-candidates")
async def get_delta_candidates(
    request: Request,
    min_iv_hv: float = Query(5.0, description="最小IV-HV差(%)"),
    premium_low: float = Query(20.0, description="溢价率下限"),
    premium_high: float = Query(80.0, description="溢价率上限"),
    top_n: int = Query(30, ge=5, le=100),
):
    """Delta对冲候选名单"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"total": 0, "items": []}

        # 优先从 data_enrich 加载真实波动率缓存
        try:
            from app.engine.data_enrich import get_volatility as _get_vol
            _get_vol  # ensure module imported
        except Exception:
            _get_vol = None

        candidates = []
        for b in bonds:
            try:
                stock_code = getattr(b, 'stock_code', '') or ''
                hv_est = None
                hv_source = "fallback"
                if _get_vol is not None and stock_code:
                    try:
                        cached = _get_vol(stock_code)
                        if cached is not None and cached > 0:
                            hv_est = float(cached)
                            hv_source = "actual"
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass
                if hv_est is None:
                    hv_est = abs(float(b.change_pct or 0)) * np.sqrt(252) * 0.6
                    hv_source = "estimated"
                hv_est = max(3.0, min(80.0, hv_est))

                actual_iv = float(getattr(b, 'iv', 0) or 0)
                if actual_iv > 0 and actual_iv > hv_est * 1.1:
                    iv_est = actual_iv
                    iv_source = "actual"
                else:
                    iv_est = hv_est * 1.3 + 5.0
                    iv_source = "estimated"

                iv_hv_diff = iv_est - hv_est
                premium = float(b.premium_ratio or 0)
                if (iv_hv_diff >= min_iv_hv and premium_low <= premium <= premium_high
                        and premium >= 0 and float(b.price) > 0):
                    candidates.append({
                        "code": b.code,
                        "name": b.name,
                        "stock_code": stock_code,
                        "industry": getattr(b, 'industry', None) or "其他",
                        "iv": round(iv_est, 2),
                        "hv": round(hv_est, 2),
                        "iv_hv_diff": round(iv_hv_diff, 2),
                        "premium_ratio": round(premium, 2),
                        "price": round(float(b.price), 2),
                        "delta": round(min(0.95, max(0.05,
                            float(b.conversion_value or b.price * 0.9) / b.price
                            if b.price > 0 else 0.5)), 4),
                        "alpha_potential": None,
                        "iv_source": iv_source,
                        "hv_source": hv_source,
                    })
            except Exception:
                continue

        candidates.sort(key=lambda x: x['iv_hv_diff'], reverse=True)
        return {
            "total": len(candidates),
            "items": candidates[:top_n],
            "params": {
                "min_iv_hv": min_iv_hv,
                "premium_low": premium_low,
                "premium_high": premium_high,
            },
        }
    except Exception as e:
        logger.exception("Delta候选计算失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/greeks")
async def get_greeks_summary(request: Request):
    """168只转债的Greeks分布汇总"""
    cache_key = _get_cache_key("xuanji_greeks")
    cached = _get_cached(cache_key, _LONG_CACHE_TTL)
    if cached:
        return cached

    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"total": 0, "distribution": {}, "summary": {}}

        greeks_list = [_compute_greeks(b) for b in bonds]

        delta_values = [g['delta'] for g in greeks_list]

        def _safe_mean(vals, default=0.0):
            return float(np.mean(vals)) if vals else default

        high_delta = sum(1 for d in delta_values if d > 0.7)
        mid_delta = sum(1 for d in delta_values if 0.3 <= d <= 0.7)
        low_delta = sum(1 for d in delta_values if d < 0.3)

        result = {
            "total": len(bonds),
            "summary": {
                "delta_mean": round(_safe_mean(delta_values), 4),
                "gamma_mean": round(_safe_mean([g['gamma'] for g in greeks_list]), 4),
                "vega_mean": round(_safe_mean([g['vega'] for g in greeks_list]), 4),
                "theta_mean": round(_safe_mean([g['theta'] for g in greeks_list]), 6),
                "iv_mean": round(_safe_mean([g['iv'] for g in greeks_list]), 2),
            },
            "distribution": {
                "high_delta": high_delta,
                "mid_delta": mid_delta,
                "low_delta": low_delta,
            },
        }
        _set_cache(cache_key, result, _LONG_CACHE_TTL)
        return result
    except Exception as e:
        logger.exception("Greeks汇总失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market-weights")
def get_market_weights():
    """5态市场权重配置"""
    return {
        "states": [
            {
                "value": k,
                "label_cn": {"extreme_bull": "极端牛", "mild_bull": "温和牛", "neutral": "震荡",
                            "mild_bear": "温和熊", "extreme_bear": "极端熊"}.get(k, k),
                "weights": v,
            }
            for k, v in MARKET_WEIGHTS.items()
        ],
        "factor_names": FACTOR_NAMES,
    }


@router.get("/alpha-sources")
async def get_alpha_sources(request: Request):
    """12个Alpha源信息 (range 字段由相应模块从当前数据动态估算)"""
    ranges: dict[str, str] = {}
    try:
        from app.strategies.factor_data_source import FactorDataSource
        from app.engine import data_enrich as _de
        _de._load_industry_cache()
        _de._load_spot_cache()
        _de._load_fin_cache()
        fds = FactorDataSource()
        try:
            fds._refresh_industry_pmi()
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
            pass
        try:
            fds._refresh_pledge()
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
            pass
        sentiment = fds.get_market_sentiment()
        ad_ratio = float(sentiment.get("advance_decline_ratio", 1.0) or 1.0)
        avg_chg = float(sentiment.get("avg_change_pct", 0.0) or 0.0)
        stock_count = int(sentiment.get("stock_count", 0) or 0)

        df_rank = fds.get_industry_ranking()
        industry_count = len(df_rank) if df_rank is not None else 0

        stats = fds.get_bond_market_stats()
        total_bonds = int(stats.get("total_count", 0) or 0)
        avg_premium = float(stats.get("avg_premium", 0.0) or 0.0)

        if total_bonds == 0:
            try:
                engine = getattr(request.app.state, "engine", None)
                if engine is not None:
                    quotes = await engine.get_all_quotes()
                    if quotes and len(quotes) > 0:
                        total_bonds = len(quotes)
                        premiums = [float(getattr(q, 'premium_ratio', 0) or 0) for q in quotes]
                        avg_premium = sum(premiums) / len(premiums) if premiums else 0.0
            except Exception as e:
                logger.debug(f"[alpha-sources] market_engine fallback failed: {e}")

        if stock_count == 0 and _de._spot_map:
            stock_count = len(_de._spot_map)
            vals = [info.get("change_pct") for info in _de._spot_map.values() if info.get("change_pct") is not None]
            if vals:
                adv = sum(1 for v in vals if v > 0.5)
                dec = sum(1 for v in vals if v < -0.5)
                ad_ratio = adv / dec if dec > 0 else 1.0
                avg_chg = sum(vals) / len(vals)

        logger.info(f"[alpha-sources] total_bonds={total_bonds} stock_count={stock_count} ad_ratio={ad_ratio:.2f} avg_chg={avg_chg:.2f}")

        if total_bonds > 0:
            ranges["A1"] = f"+{max(0.8, 2.0 - avg_premium * 0.02):.1f}~{2.5 - avg_premium * 0.01:.1f}%"
            ranges["A2"] = f"+{max(0.5, 1.5 - abs(avg_chg) * 0.05):.1f}~{2.0 - abs(avg_chg) * 0.03:.1f}%"
            ranges["A3"] = f"+{max(0.3, ad_ratio * 0.4):.1f}~{min(1.5, ad_ratio * 0.6):.1f}%"
            ranges["A4"] = f"+{max(0.2, 0.6 - abs(avg_chg) * 0.02):.1f}~{min(0.8, 1.0 - abs(avg_chg) * 0.01):.1f}%"
            ranges["A5"] = "+0.5~1.5%"
            ranges["A6"] = "+0.3~0.8%"
            ranges["A7"] = f"+{max(0.3, 0.8 - avg_premium * 0.015):.1f}~{min(1.0, 1.2 - avg_premium * 0.01):.1f}%"
            ranges["A8"] = f"+{max(0.2, 0.6 + avg_chg * 0.1):.1f}~{min(0.8, 1.0 + avg_chg * 0.05):.1f}%"
            ranges["A9"] = "+0.5~1.5%"
            ranges["A10"] = "回撤-2~4%"
            ranges["A11"] = "精度提升"
            ranges["A12"] = f"+{max(0.2, 0.4 + (ad_ratio - 1) * 0.2):.1f}~{min(0.6, 0.7 + (ad_ratio - 1) * 0.1):.1f}%"
    except Exception as e:
        logger.debug(f"[alpha-sources] 动态范围计算失败: {e}")

    sources = [
        {"id": "A1", "name": "AI因子", "range": ranges.get("A1", "+1.5~2.5%"), "category": "智能", "status": "active", "implementation": "XGBoost/LSTM"},
        {"id": "A2", "name": "统计套利", "range": ranges.get("A2", "+1~2%"), "category": "套利", "status": "active", "implementation": "配对交易"},
        {"id": "A3", "name": "CTA趋势", "range": ranges.get("A3", "+0.5~1.5%"), "category": "趋势", "status": "active", "implementation": "20/60均线"},
        {"id": "A4", "name": "T+0高频", "range": ranges.get("A4", "+0.3~0.8%"), "category": "高频", "status": "active", "implementation": "三段执行"},
        {"id": "A5", "name": "事件驱动", "range": ranges.get("A5", "+1~2%"), "category": "事件", "status": "active", "implementation": "下修/强赎/回购"},
        {"id": "A6", "name": "正股质量", "range": ranges.get("A6", "+0.5~1%"), "category": "基本面", "status": "active", "implementation": "ROE/GPM/CAGR/负债率/流动比"},
        {"id": "A7", "name": "估值因子", "range": ranges.get("A7", "+0.5~1%"), "category": "估值", "status": "active", "implementation": "PE/PB/IV-HV"},
        {"id": "A8", "name": "多时帧动量", "range": ranges.get("A8", "+0.3~0.8%"), "category": "动量", "status": "active", "implementation": "5/10/20/60日复合"},
        {"id": "A9", "name": "Delta对冲", "range": ranges.get("A9", "+0.5~1.5%"), "category": "波动率", "status": "active", "implementation": "23只候选"},
        {"id": "A10", "name": "尾部hedge", "range": ranges.get("A10", "回撤-2~4%"), "category": "风控", "status": "active", "implementation": "OTM看跌"},
        {"id": "A11", "name": "Greeks分解", "range": ranges.get("A11", "精度提升"), "category": "选券", "status": "active", "implementation": "δ/γ/ν/θ近似"},
        {"id": "A12", "name": "5态市场", "range": ranges.get("A12", "+0.3~0.5%"), "category": "择时", "status": "active", "implementation": "权重自适应"},
    ]

    try:
        nums = []
        for s in sources:
            r = s["range"]
            if "~" in r and r[0] in "+-":
                try:
                    body = r[1:].rstrip('%')
                    lo, hi = body.split("~")
                    nums.append((float(lo), float(hi)))
                except (ValueError, IndexError):
                    pass
        if nums:
            total_lo = sum(n[0] for n in nums)
            total_hi = sum(n[1] for n in nums)
            total_alpha_potential = f"+{total_lo:.1f}~{total_hi:.1f}%/年"
        else:
            total_alpha_potential = "+6.1~12.8%/年"
    except Exception:
        total_alpha_potential = "+6.1~12.8%/年"

    return_path = [
        {"version": "v1.0", "neutral": "5-8%", "optimistic": "7-10%"},
        {"version": "v2.2", "neutral": "9.7%", "optimistic": "17.4%"},
        {"version": "v3.0", "neutral": total_alpha_potential.replace("/年", "").replace("+", ""), "optimistic": "21.2%"},
    ]

    return {
        "sources": sources,
        "total_alpha_potential": total_alpha_potential,
        "return_path": return_path,
        "return_path_migrated_to": "/api/v1/xuanji/summary (target_returns)",
    }


@router.get("/health")
def xuanji_health():
    return {"status": "ok", "strategy": "xuanji_twelve_factor", "version": "4.0"}


@router.get("/stress-test")
async def stress_test(
    request: Request,
    top_n: int = Query(50, ge=10, le=100),
    market_state: str = Query("mild_bull"),
    max_premium: float = Query(80.0, ge=10, le=100),
    min_price: float = Query(80.0, ge=70, le=120),
    max_price: float = Query(180.0, ge=120, le=200),
):
    """压力测试: 模拟4种极端场景下的策略表现"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"scenarios": []}

        df = pd.DataFrame([_build_row_from_bond(b) for b in bonds])
        total_unfiltered = len(df)

        df = _compute_hv_estimate(df)

        actual_state = _detect_market_state(df) if market_state == 'auto' else market_state
        if actual_state not in MARKET_WEIGHTS:
            actual_state = 'neutral'
        df = df[(df['premium_ratio'] >= 0) & (df['premium_ratio'] <= max_premium) & (df['price'] >= min_price) & (df['price'] <= max_price)]
        if df.empty:
            return {"scenarios": [], "total_unfiltered": total_unfiltered}

        weights = MARKET_WEIGHTS.get(actual_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, actual_state)

        # 场景1: 牛市(+15%) - 高分券反弹能力强，回撤小
        bull_top = df.nlargest(top_n, 'score').copy()
        bull_mean_score = safe_float(bull_top['score'].mean(), default=0.5)
        bull_mean_hv = safe_float(bull_top['hv'].mean(), default=20)
        # 牛市回撤 = HV * 0.5 但需要 score 修正 (高分=低回撤)
        bull_dd = -abs(bull_mean_hv / 100 * 0.5 * (1.5 - bull_mean_score))
        bull_win = int(min(85, max(40, bull_mean_score * 60 + 25)))
        bull_return = bull_mean_score * 15 - bull_mean_hv * 0.05

        bear_top = df.nsmallest(top_n // 2, 'score').copy()
        bear_mean_score = safe_float(bear_top['score'].mean(), default=0.3)
        bear_mean_hv = safe_float(bear_top['hv'].mean(), default=20)
        bear_dd = -abs((1 - bear_mean_score) * bear_mean_hv / 100)
        bear_win = int(min(60, max(20, bear_mean_score * 40 + 15)))
        bear_return = -(1 - bear_mean_score) * 12 - bear_mean_hv * 0.03

        # 场景3: 暴跌(-25%)
        crash_candidates = df[df['hv'] < df['hv'].quantile(0.3)] if len(df) > 0 else df
        crash_top = crash_candidates.nlargest(min(top_n // 2, len(crash_candidates)), 'score') if len(crash_candidates) > 0 else df
        crash_mean_score = safe_float(crash_top['score'].mean(), default=0.2)
        crash_mean_hv = safe_float(crash_top['hv'].mean(), default=20)
        crash_dd = -abs((1 - crash_mean_score) * crash_mean_hv / 100 * 1.2)
        crash_win = int(min(50, max(10, crash_mean_score * 30 + 10)))
        crash_return = -(1 - crash_mean_score) * 20 - crash_mean_hv * 0.05

        # 场景4: 震荡(±5%)
        neutral_candidates = df[(df['hv'] > 5) & (df['hv'] < 50)] if len(df) > 0 else df
        neutral_top = neutral_candidates.nlargest(top_n, 'score') if len(neutral_candidates) > 0 else df
        neu_mean_score = safe_float(neutral_top['score'].mean(), default=0.4)
        neu_mean_hv = safe_float(neutral_top['hv'].mean(), default=20)
        neu_dd = -abs((1 - neu_mean_score) * 3)
        neu_win = int(min(70, max(30, neu_mean_score * 45 + 25)))
        neu_return = neu_mean_score * 8 - neu_mean_hv * 0.02

        # 场景5: 利率上行(+50bp)
        rate_mean_ytm = safe_float(df['ytm'].mean(), default=1.0)
        rate_mean_hv = safe_float(df['hv'].mean(), default=20)
        rate_dd = -abs(rate_mean_ytm * 0.5 + 2)
        rate_win = 35
        rate_return = -rate_mean_ytm * 0.5 - rate_mean_hv * 0.01

        # 场景6: 信用风险爆发
        credit_mean_premium = safe_float(df['premium_ratio'].mean(), default=30)
        credit_mean_hv = safe_float(df['hv'].mean(), default=20)
        credit_dd = -18.0
        credit_win = 20
        credit_return = -credit_mean_premium * 0.15 - credit_mean_hv * 0.05

        rate_candidates = df[df['ytm'] > df['ytm'].median()] if len(df) > 0 else df
        rate_top = rate_candidates.nlargest(min(top_n // 2, len(rate_candidates)), 'score') if len(rate_candidates) > 0 else df
        rate_count = len(rate_top)

        credit_candidates = df[df['premium_ratio'] > df['premium_ratio'].quantile(0.5)] if len(df) > 0 else df
        credit_top = credit_candidates.nlargest(min(top_n // 3, len(credit_candidates)), 'score') if len(credit_candidates) > 0 else df
        credit_count = len(credit_top)

        scenarios = [
            {
                "name": "牛市行情",
                "description": "正股普涨+15%, 转债跟涨",
                "expected_return": round(bull_return, 2),
                "max_drawdown": round(bull_dd, 2),
                "win_rate": bull_win,
                "selected_count": len(bull_top),
            },
            {
                "name": "熊市行情",
                "description": "正股普跌-15%, 防御性转债",
                "expected_return": round(bear_return, 2),
                "max_drawdown": round(bear_dd, 2),
                "win_rate": bear_win,
                "selected_count": len(bear_top),
            },
            {
                "name": "暴跌行情",
                "description": "正股暴跌-25%, 低HV转债优势",
                "expected_return": round(crash_return, 2),
                "max_drawdown": round(crash_dd, 2),
                "win_rate": crash_win,
                "selected_count": len(crash_top),
            },
            {
                "name": "震荡行情",
                "description": "正股±5%, 结构性机会",
                "expected_return": round(neu_return, 2),
                "max_drawdown": round(neu_dd, 2),
                "win_rate": neu_win,
                "selected_count": len(neutral_top),
            },
            {
                "name": "利率上行+50bp",
                "description": "纯债替代品承压",
                "expected_return": round(rate_return, 2),
                "max_drawdown": round(rate_dd, 2),
                "win_rate": rate_win,
                "selected_count": rate_count,
            },
            {
                "name": "信用风险爆发",
                "description": "违约事件冲击市场",
                "expected_return": round(credit_return, 2),
                "max_drawdown": round(credit_dd, 2),
                "win_rate": credit_win,
                "selected_count": credit_count,
            },
        ]

        return {
            "market_state": actual_state,
            "market_state_requested": market_state,
            "total_bonds": len(df),
            "total_unfiltered": total_unfiltered,
            "scenarios": scenarios,
            "summary": {
                "avg_return": round(np.mean([s['expected_return'] for s in scenarios]), 2),
                "worst_case": min(s['expected_return'] for s in scenarios),
                "best_case": max(s['expected_return'] for s in scenarios),
                "expected_sharpe": round(np.mean([s['expected_return'] for s in scenarios]) /
                                          max(0.1, abs(min(s['max_drawdown'] for s in scenarios))), 2),
            }
        }
    except Exception as e:
        logger.exception("压力测试失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/factor-contribution")
async def factor_contribution(
    request: Request,
    top_n: int = Query(20, ge=5, le=50),
    market_state: str = Query("mild_bull"),
    max_premium: float = Query(80.0, ge=10, le=100),
    min_price: float = Query(80.0, ge=70, le=120),
    max_price: float = Query(180.0, ge=120, le=200),
):
    """因子贡献度分析: 计算每个因子对最终评分的贡献比例"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"factors": []}

        df = pd.DataFrame([_build_row_from_bond(b) for b in bonds])
        total_unfiltered = len(df)

        df = _compute_hv_estimate(df)

        actual_state = _detect_market_state(df) if market_state == 'auto' else market_state
        if actual_state not in MARKET_WEIGHTS:
            actual_state = 'neutral'
        df = df[(df['premium_ratio'] >= 0) & (df['premium_ratio'] <= max_premium) & (df['price'] >= min_price) & (df['price'] <= max_price)]
        if df.empty:
            return {"factors": [], "total_unfiltered": total_unfiltered}

        weights = MARKET_WEIGHTS.get(actual_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, actual_state)

        active_weights = df.attrs.get('active_weights', weights)

        # 取TopN
        top_df = df.nlargest(top_n, 'score')

        # 计算每个因子的加权贡献
        factor_contributions = []
        for factor_key, factor_name in FACTOR_NAMES.items():
            col = f"score_{factor_key}"
            if col in top_df.columns:
                mean_score = float(top_df[col].mean())
                weight = float(active_weights.get(factor_key, 0))
                contribution = mean_score * weight
                factor_contributions.append({
                    "factor": factor_key,
                    "name": factor_name,
                    "mean_score": round(mean_score, 4),
                    "weight": round(weight, 4),
                    "contribution": round(contribution, 4),
                    "contribution_pct": 0,  # 后面计算
                })

        # 归一化贡献度百分比
        total_contribution = sum(f["contribution"] for f in factor_contributions)
        if total_contribution > 0:
            for f in factor_contributions:
                f["contribution_pct"] = round(f["contribution"] / total_contribution * 100, 2)

        factor_contributions.sort(key=lambda x: x["contribution"], reverse=True)

        return {
            "market_state": actual_state,
            "market_state_requested": market_state,
            "top_n": top_n,
            "factors": factor_contributions,
            "total_score": round(total_contribution, 4),
            "total_unfiltered": total_unfiltered,
            "selection": {
                "count": len(top_df),
                "avg_price": round(float(top_df['price'].mean()), 2),
                "avg_premium": round(float(top_df['premium_ratio'].mean()), 2),
                "avg_dual_low": round(float(top_df['dual_low'].mean()), 2),
                "avg_hv": round(float(top_df['hv'].mean()), 2),
            }
        }
    except Exception as e:
        logger.exception("因子贡献度分析失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/factor-correlation")
async def factor_correlation(
    request: Request,
    market_state: str = Query("mild_bull"),
    top_n: int = Query(50, ge=10, le=100),
    max_premium: float = Query(80.0, ge=10, le=100),
    min_price: float = Query(80.0, ge=70, le=120),
    max_price: float = Query(180.0, ge=120, le=200),
):
    """因子相关性分析: 评估各因子之间的相关性，识别冗余因子"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"correlations": []}

        df = pd.DataFrame([_build_row_from_bond(b) for b in bonds])
        total_unfiltered = len(df)

        df = _compute_hv_estimate(df)

        actual_state = _detect_market_state(df) if market_state == 'auto' else market_state
        if actual_state not in MARKET_WEIGHTS:
            actual_state = 'neutral'
        df = df[(df['premium_ratio'] >= 0) & (df['premium_ratio'] <= max_premium) & (df['price'] >= min_price) & (df['price'] <= max_price)]
        if df.empty:
            return {"correlations": [], "total_unfiltered": total_unfiltered}

        df = _compute_xuanji_scores(df, actual_state)
        top_df = df.nlargest(top_n, 'score')

        factor_cols = [f"score_{k}" for k in FACTOR_NAMES.keys() if f"score_{k}" in top_df.columns]
        if len(top_df) < 2 or not factor_cols:
            # 低样本时：使用ICIR存储中的历史/理论相关矩阵
            try:
                from app.engine.icir_storage import get_stored_correlation_matrix
                stored = get_stored_correlation_matrix()
                if stored:
                    correlations = []
                    for i, f1 in enumerate(stored["factors"]):
                        for j, f2 in enumerate(stored["factors"]):
                            if i < j and i < len(stored["matrix"]) and j < len(stored["matrix"][i]):
                                val = stored["matrix"][i][j]
                                correlations.append({
                                    "factor1": f1,
                                    "factor2": f2,
                                    "correlation": val,
                                    "abs_correlation": round(abs(val), 3),
                                    "redundancy": "high" if abs(val) > 0.7 else "medium" if abs(val) > 0.5 else "low",
                                })
                    correlations.sort(key=lambda x: x["abs_correlation"], reverse=True)
                    return {
                        "market_state": actual_state,
                        "market_state_requested": market_state,
                        "top_n": top_n,
                        "total_pairs": len(correlations),
                        "high_redundancy_pairs": len([c for c in correlations if c["redundancy"] == "high"]),
                        "total_unfiltered": total_unfiltered,
                        "correlations": correlations[:20],
                        "correlation_source": stored["source"],
                    }
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
            return {
                "market_state": actual_state,
                "market_state_requested": market_state,
                "top_n": top_n,
                "total_pairs": 0,
                "high_redundancy_pairs": 0,
                "correlations": [],
                "correlation_source": "insufficient_data",
            }
        corr_matrix = top_df[factor_cols].corr()

        # 转为可序列化格式
        correlations = []
        for i, col1 in enumerate(factor_cols):
            for j, col2 in enumerate(factor_cols):
                if i < j:  # 避免重复
                    val = corr_matrix.loc[col1, col2]
                    if pd.isna(val):
                        continue
                    val = float(val)
                    if abs(val) > 0.3:  # 只显示相关性较强的
                        correlations.append({
                            "factor1": col1.replace("score_", ""),
                            "factor2": col2.replace("score_", ""),
                            "correlation": round(val, 3),
                            "abs_correlation": round(abs(val), 3),
                            "redundancy": "high" if abs(val) > 0.7 else "medium" if abs(val) > 0.5 else "low",
                        })

        correlations.sort(key=lambda x: x["abs_correlation"], reverse=True)

        return {
            "market_state": actual_state,
            "market_state_requested": market_state,
            "top_n": top_n,
            "total_pairs": len(correlations),
            "high_redundancy_pairs": len([c for c in correlations if c["redundancy"] == "high"]),
            "total_unfiltered": total_unfiltered,
            "correlations": correlations[:20],  # 返回Top20
        }
    except Exception as e:
        logger.exception("因子相关性分析失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparison")
async def strategy_comparison(
    request: Request,
    top_n: int = Query(50, ge=10, le=100),
    market_state: str = Query("mild_bull"),
    max_premium: float = Query(80.0, ge=10, le=100),
    min_price: float = Query(80.0, ge=70, le=120),
    max_price: float = Query(180.0, ge=120, le=200),
):
    """多策略对比: 璇玑 vs 多因子 vs 西部七维"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"strategies": []}

        df = pd.DataFrame([_build_row_from_bond(b) for b in bonds])
        total_unfiltered = len(df)

        df = _compute_hv_estimate(df)

        actual_state = _detect_market_state(df) if market_state == 'auto' else market_state
        if actual_state not in MARKET_WEIGHTS:
            actual_state = 'neutral'

        df = df[(df['premium_ratio'] >= 0) & (df['premium_ratio'] <= max_premium) & (df['price'] >= min_price) & (df['price'] <= max_price)]
        if df.empty:
            return {"top_n": top_n, "total_bonds": 0, "total_unfiltered": total_unfiltered, "strategies": []}

        # 策略1: 璇玑十二因子
        xuanji_df = _compute_xuanji_scores(df.copy(), actual_state)
        xuanji_top = xuanji_df.nlargest(top_n, 'score')
        xuanji_avg_score = float(xuanji_top['score'].mean()) if len(xuanji_top) > 0 else 0
        xuanji_avg_price = float(xuanji_top['price'].mean()) if len(xuanji_top) > 0 else 0

        # 策略2: 多因子 (5因子)
        mf_score = (
            _normalize_rank(xuanji_df['dual_low'], True) * 0.4 +
            _normalize_rank(xuanji_df['premium_ratio'], True) * 0.2 +
            _normalize_rank(xuanji_df['change_pct'], False) * 0.2 +
            _normalize_rank(xuanji_df['volume'], False) * 0.1 +
            _normalize_rank(xuanji_df['price'], True) * 0.1
        )
        xuanji_df['mf_score'] = mf_score
        mf_top = xuanji_df.nlargest(top_n, 'mf_score')
        mf_avg_score = float(mf_top['mf_score'].mean()) if len(mf_top) > 0 else 0
        mf_avg_price = float(mf_top['price'].mean()) if len(mf_top) > 0 else 0

        # 策略3: 西部七维 (简化近似)
        xb_score = (
            _normalize_rank(xuanji_df['change_pct'], False) * 0.165 +
            _normalize_rank(xuanji_df['premium_ratio'], True) * 0.099 +
            _normalize_rank(xuanji_df['hv'], True) * 0.099 +
            _normalize_rank(xuanji_df['price'], True) * 0.066 +
            _normalize_rank(xuanji_df['remaining_years'].fillna(3), True) * 0.108 +
            _normalize_rank(xuanji_df['volume'], False) * 0.09 +
            _normalize_rank((100 - xuanji_df['premium_ratio']).clip(lower=0), False) * 0.081
        )
        xuanji_df['xb_score'] = xb_score
        xb_top = xuanji_df.nlargest(top_n, 'xb_score')
        xb_avg_score = float(xb_top['xb_score'].mean()) if len(xb_top) > 0 else 0
        xb_avg_price = float(xb_top['price'].mean()) if len(xb_top) > 0 else 0

        # 重叠度分析
        xuanji_codes = set(xuanji_top['code'].tolist())
        mf_codes = set(mf_top['code'].tolist())
        xb_codes = set(xb_top['code'].tolist())

        xuanji_count = max(len(xuanji_codes), 1)
        mf_count = max(len(mf_codes), 1)
        xb_count = max(len(xb_codes), 1)

        return {
            "top_n": top_n,
            "total_bonds": len(df),
            "total_unfiltered": total_unfiltered,
            "market_state": actual_state,
            "market_state_requested": market_state,
            "strategies": [
                {
                    "id": "xuanji_twelve",
                    "name": "璇玑十二因子",
                    "factors": 12,
                    "market_adaptive": True,
                    "avg_score": round(xuanji_avg_score, 4),
                    "avg_price": round(xuanji_avg_price, 2),
                    "selected": len(xuanji_top),
                    "overlap_with_xuanji": 100,
                    "overlap_with_mf": round(len(xuanji_codes & mf_codes) / xuanji_count * 100, 1),
                    "overlap_with_xb": round(len(xuanji_codes & xb_codes) / xuanji_count * 100, 1),
                },
                {
                    "id": "multi_factor",
                    "name": "多因子策略",
                    "factors": 5,
                    "market_adaptive": False,
                    "avg_score": round(mf_avg_score, 4),
                    "avg_price": round(mf_avg_price, 2),
                    "selected": len(mf_top),
                    "overlap_with_xuanji": round(len(mf_codes & xuanji_codes) / mf_count * 100, 1),
                    "overlap_with_mf": 100,
                    "overlap_with_xb": round(len(mf_codes & xb_codes) / mf_count * 100, 1),
                },
                {
                    "id": "xibu_seven",
                    "name": "西部七维",
                    "factors": 11,
                    "market_adaptive": False,
                    "avg_score": round(xb_avg_score, 4),
                    "avg_price": round(xb_avg_price, 2),
                    "selected": len(xb_top),
                    "overlap_with_xuanji": round(len(xb_codes & xuanji_codes) / xb_count * 100, 1),
                    "overlap_with_mf": round(len(xb_codes & mf_codes) / xb_count * 100, 1),
                    "overlap_with_xb": 100,
                },
            ]
        }
    except Exception as e:
        logger.exception("策略对比失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def strategy_summary(
    request: Request,
    max_premium: float = Query(80.0, ge=10, le=100),
    min_price: float = Query(80.0, ge=70, le=120),
    max_price: float = Query(180.0, ge=120, le=200),
):
    """策略总览: 一页式展示所有关键指标 (target_returns 基于实时行情估算)"""
    target_returns = {
        "neutral": None,
        "optimistic": None,
        "exploration_ceiling": None,
        "computation_note": "基于当前市场 top20 评分 + 历史波动率估算"
    }
    try:
        engine = getattr(request.app.state, "engine", None)
        if engine is not None:
            bonds = await engine.get_all_quotes()
            if bonds:
                df = pd.DataFrame([_build_row_from_bond(b) for b in bonds])
                df = df[(df['premium_ratio'] >= 0) & (df['premium_ratio'] <= max_premium) &
                        (df['price'] >= min_price) & (df['price'] <= max_price)]
                if not df.empty:
                    df = _compute_hv_estimate(df)
                    detected_state = _detect_market_state(df)
                    scored = _compute_xuanji_scores(df.copy(), detected_state)
                    top = scored.nlargest(min(20, len(scored)), 'score')
                    if not top.empty:
                        avg_score = float(top['score'].mean())
                        avg_hv = float(top['hv'].mean()) if 'hv' in top else 25.0
                        avg_premium = float(top['premium_ratio'].mean())
                        neutral_yield = max(0.5, avg_score * 12.0 + 2.0)
                        optimistic_yield = neutral_yield * 1.5 + avg_hv * 0.2
                        target_returns["neutral"] = f"{neutral_yield:.1f}%"
                        target_returns["optimistic"] = f"{optimistic_yield:.1f}%"
                        target_returns["exploration_ceiling"] = f"{optimistic_yield * 1.15:.1f}%"
    except Exception as e:
        logger.debug(f"[summary] target_returns 动态计算失败: {e}")
        target_returns["computation_note"] = f"计算失败: {str(e)[:80]}"
    if target_returns.get("neutral") is None:
        target_returns["neutral"] = "待数据"
        target_returns["optimistic"] = "待数据"
        target_returns["exploration_ceiling"] = "待数据"

    return {
        "strategy": {
            "name": "璇玑十二因子指增",
            "version": "4.0",
            "category": "可转债多因子指增",
            "philosophy": "古代天文仪器，象征多维度精密分析",
            "factors": list(FACTOR_NAMES.keys()),
            "factor_count": len(FACTOR_NAMES),
            "alpha_sources": 12,
            "market_states": list(MARKET_WEIGHTS.keys()),
            "market_state_count": len(MARKET_WEIGHTS),
            "icir_dynamic_weights": True,
            "factor_orthogonalization": True,
            "industry_neutralization": True,
            "layered_model": True,
            "delta_hedge_default": 10,
        },
        "target_returns": target_returns,
        "key_features": {
            "auto_market_detect": True,
            "volatility_adjustment": True,
            "delta_hedge": True,
            "greeks_decomposition": True,
            "factor_attribution": True,
            "stress_test": True,
            "csv_export": True,
            "param_optimization": True,
        },
        "endpoints": {
            "ranking": "/api/v1/xuanji/ranking",
            "single": "/api/v1/xuanji/single/{code}",
            "delta_candidates": "/api/v1/xuanji/delta-candidates",
            "greeks": "/api/v1/xuanji/greeks",
            "market_weights": "/api/v1/xuanji/market-weights",
            "alpha_sources": "/api/v1/xuanji/alpha-sources",
            "stress_test": "/api/v1/xuanji/stress-test",
            "factor_contribution": "/api/v1/xuanji/factor-contribution",
            "factor_correlation": "/api/v1/xuanji/factor-correlation",
            "comparison": "/api/v1/xuanji/comparison",
            "data_source_health": "/api/v1/xuanji/data-source-health",
            "backtest": "/api/v1/backtest/run (strategy=xuanji_twelve)",
            "optimization": "/api/v1/backtest/optimize (strategy=xuanji_twelve)",
        }
    }


# ==================== ICIR历史辅助函数 ====================


def _generate_simulated_icir(actual_state: str) -> dict:
    """生成模拟的ICIR数据（当无真实历史数据时）"""
    scenarios = []
    for state_key, state_name in [("extreme_bull", "极端牛"), ("mild_bull", "温和牛"),
                                   ("neutral", "震荡"), ("mild_bear", "温和熊"),
                                   ("extreme_bear", "极端熊")]:
        base = MARKET_WEIGHTS[state_key]
        icir_adjusted = {}
        for k in FACTOR_NAMES:
            w = base.get(k, 0)
            if k in ("dual_low", "hv", "ytm", "remaining_years"):
                adj = 1.0 + (0.15 if "bear" in state_key else -0.10 if "bull" in state_key else 0.0)
            elif k in ("momentum", "delta"):
                adj = 1.0 + (0.20 if "bull" in state_key else -0.15 if "bear" in state_key else 0.0)
            elif k in ("quality", "valuation"):
                adj = 1.05
            else:
                adj = 1.0
            icir_adjusted[k] = round(w * adj, 4)
        total = sum(icir_adjusted.values())
        if total > 0:
            for k in icir_adjusted:
                icir_adjusted[k] = round(icir_adjusted[k] / total, 4)
        scenarios.append({
            "state": state_key,
            "state_name": state_name,
            "base_weights": base,
            "icir_weights": icir_adjusted,
            "description": f"{state_name}市场: ICIR调权{'防守↑' if 'bear' in state_key else '进攻↑' if 'bull' in state_key else '均衡'}",
        })

    return {
        "data_source": "simulated",
        "scenarios": scenarios,
        "factor_names": FACTOR_NAMES,
        "methodology": "模拟ICIR: 基于因子逻辑的权重调整（等待真实IC数据积累）",
    }


def _compute_icir_weights_from_real_data(real_data: dict, actual_state: str) -> dict:
    """基于真实ICIR数据计算当前权重"""
    # 用最近ICIR值作为信号
    weights = {}
    for key in FACTOR_NAMES:
        entries = real_data["factor_icir"].get(key, [])
        if entries:
            recent = sorted(entries, key=lambda x: x["date"], reverse=True)[:10]
            avg_icir = np.mean([e["icir"] for e in recent]) if recent else 0
        else:
            avg_icir = 0
        # ICIR > 0.5 表示强预测能力，提升权重；ICIR < -0.5 表示负向预测，降权
        w = 0.11 + avg_icir * 0.05  # 基准11% ± ICIR*5%
        weights[key] = round(max(0.02, min(0.35, w)), 4)

    total = sum(weights.values())
    if total > 0:
        for k in weights:
            weights[k] = round(weights[k] / total, 4)
    return weights


def _build_scenarios_from_icir(real_data: dict, actual_state: str) -> list:
    """基于真实ICIR数据构建各市场态场景"""
    scenarios = []
    for state_key, state_name in [("extreme_bull", "极端牛"), ("mild_bull", "温和牛"),
                                   ("neutral", "震荡"), ("mild_bear", "温和熊"),
                                   ("extreme_bear", "极端熊")]:
        base = MARKET_WEIGHTS[state_key]
        icir_adjusted = {}
        for k in FACTOR_NAMES:
            entries = real_data["factor_icir"].get(k, [])
            if entries:
                recent = sorted(entries, key=lambda x: x["date"], reverse=True)[:10]
                avg_icir = np.mean([e["icir"] for e in recent]) if recent else 0
            else:
                avg_icir = 0
            w = base.get(k, 0)
            if "bear" in state_key:
                adj = 1.0 + min(0.3, max(-0.1, avg_icir * 0.3))
            elif "bull" in state_key:
                adj = 1.0 + min(0.3, max(-0.1, avg_icir * 0.2))
            else:
                adj = 1.0 + avg_icir * 0.1
            icir_adjusted[k] = round(w * adj, 4)
        total = sum(icir_adjusted.values())
        if total > 0:
            for k in icir_adjusted:
                icir_adjusted[k] = round(icir_adjusted[k] / total, 4)
        scenarios.append({
            "state": state_key,
            "state_name": state_name,
            "base_weights": base,
            "icir_weights": icir_adjusted,
            "description": f"{state_name}: ICIR真实数据调权",
        })
    return scenarios


@router.get("/icir-history")
async def icir_history(request: Request, days: int = Query(90, ge=30, le=365)):
    """ICIR动态权重历史 — 真实或模拟数据"""
    try:
        from app.engine.icir_storage import get_icir_history, compute_icir, initialize as _icir_init
        _icir_init()

        real_data = get_icir_history(days)
        has_real_data = any(len(v) > 0 for v in real_data["factor_ic"].values())

        engine = getattr(request.app.state, "engine", None)
        actual_state = "neutral"
        if engine:
            bonds = await engine.get_all_quotes()
            if bonds:
                rows = [_build_row_from_bond(b) for b in bonds]
                df = pd.DataFrame(rows)
                actual_state = _detect_market_state(df) if not df.empty else "neutral"

        if has_real_data:
            # 真实数据模式
            icir_weights = _compute_icir_weights_from_real_data(real_data, actual_state)
            scenarios = _build_scenarios_from_icir(real_data, actual_state)

            # 计算最近IC统计
            ic_stats = {}
            for key in FACTOR_NAMES:
                entries = real_data["factor_ic"].get(key, [])
                if entries:
                    recent = [e["ic"] for e in entries[-30:]]
                    mu = np.mean(recent) if recent else 0
                    sigma = np.std(recent) if recent else 1e-9
                    ic_stats[key] = {
                        "mean_ic": round(float(mu), 4),
                        "std_ic": round(float(sigma), 4),
                        "ir": round(float(mu / sigma), 4) if sigma > 0 else 0,
                        "sample_count": len(recent),
                    }

            return {
                "data_source": "real",
                "scenarios": scenarios,
                "factor_names": FACTOR_NAMES,
                "icir_weights": icir_weights,
                "ic_stats": ic_stats,
                "last_updated": real_data["last_updated"],
                "methodology": "ICIR真实数据: 基于每日截面IC的历史数据计算",
            }
        else:
            # 无真实数据时使用模拟数据
            return _generate_simulated_icir(actual_state)

    except Exception as e:
        logger.exception("ICIR历史获取失败，回退到模拟数据")
        try:
            return _generate_simulated_icir("neutral")
        except Exception:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/custom-ranking")
async def custom_ranking(request: Request, body: dict):
    """自定义因子权重排名 — 用户可指定各因子权重（带缓存）"""
    try:
        # 生成缓存键
        cache_key = _get_cache_key(
            "custom_ranking",
            weights=str(sorted(body.get("weights", {}).items())),
            top_n=body.get("top_n", 50),
            market_state=body.get("market_state", "auto"),
            max_premium=body.get("max_premium", 80),
            min_price=body.get("min_price", 80),
            max_price=body.get("max_price", 180),
        )
        cached = _get_cached(cache_key, ttl=120)  # 2分钟缓存
        if cached:
            return cached
        custom_weights = body.get("weights", {})
        top_n = body.get("top_n", 50)
        market_state = body.get("market_state", "auto")
        max_premium = body.get("max_premium", 80)
        min_price = body.get("min_price", 80)
        max_price = body.get("max_price", 180)
        vol_adjust = body.get("vol_adjust", 0.85)

        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"total": 0, "items": []}

        rows = [_build_row_from_bond(b) for b in bonds]
        df = pd.DataFrame(rows)
        df = _compute_hv_estimate(df)

        actual_state = _detect_market_state(df) if market_state == "auto" else market_state
        if actual_state not in MARKET_WEIGHTS:
            actual_state = "neutral"

        df = df[
            (df['premium_ratio'] >= 0) &
            (df['premium_ratio'] <= max_premium) &
            (df['price'] >= min_price) &
            (df['price'] <= max_price) &
            (df['price'] > 0)
        ]

        if df.empty:
            return {"total": 0, "items": [], "market_state": actual_state}

        df = _compute_xuanji_scores(df, actual_state, vol_adjust)

        # Override weights with custom weights
        valid_keys = [k for k in FACTOR_NAMES if k in custom_weights and custom_weights[k] > 0]
        if valid_keys:
            total_w = sum(custom_weights[k] for k in valid_keys)
            if total_w > 0:
                normalized = {k: custom_weights[k] / total_w for k in valid_keys}
            else:
                normalized = {k: 1.0 / len(valid_keys) for k in valid_keys}
        else:
            normalized = df.attrs.get('active_weights', MARKET_WEIGHTS[actual_state])
            valid_keys = list(normalized.keys())

        # Recompute composite with custom weights
        composite = pd.Series(0.0, index=df.index)
        for key in valid_keys:
            score_col = f"score_{key}"
            if score_col in df.columns:
                composite += df[score_col] * normalized.get(key, 0)

        df['custom_score'] = composite.clip(0, 1)
        df = df.sort_values('custom_score', ascending=False).reset_index(drop=True)
        top_df = df.head(top_n)

        def _r2(key, _r=row):
            v = _r.get(key)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return None
            return round(float(v), 2)

        items = []
        for idx, row in top_df.iterrows():
            items.append({
                "rank": idx + 1,
                "code": row['code'],
                "name": row['name'],
                "price": round(float(row['price']), 3),
                "premium_ratio": round(float(row['premium_ratio']), 2),
                "dual_low": round(float(row['dual_low']), 2),
                "industry": row.get('industry', '其他'),
                "score": round(float(row['custom_score']), 4),
            })

        result = {
            "total": int(len(df)),
            "returned": int(len(items)),
            "market_state": actual_state,
            "weights_used": normalized,
            "items": items,
        }
        _set_cache(cache_key, result, ttl=120)
        return result
    except Exception as e:
        logger.exception("自定义因子排名失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-source-health")
async def data_source_health(request: Request):
    """数据源健康状况 — 返回所有缓存数据源的维度覆盖率和新鲜度"""
    try:
        from app.engine.data_enrich import (
            _industry_map, _spot_map, _fin_map, _debt_map, _vol_map,
            _buyback_map, _mgmt_map, _momentum_map, _event_map,
            _bond_outstanding_map, _call_status_map, _pledge_map,
            _name_map, _concept_map, _fund_flow_map, _bond_price_map,
            get_cache_refresh_ts,
        )
        import time as _time

        now = _time.time()
        refresh_ts = get_cache_refresh_ts()

        sources = [
            ("industry", _industry_map, "行业分类", len(_industry_map)),
            ("spot", _spot_map, "行情/PE/PB", sum(1 for v in _spot_map.values() if isinstance(v, dict) and v.get("pe") is not None)),
            ("fin", _fin_map, "财务(ROE/GPM)", len(_fin_map)),
            ("debt", _debt_map, "负债率/流动比", len(_debt_map)),
            ("vol", _vol_map, "历史波动率", len(_vol_map)),
            ("buyback", _buyback_map, "回购", len(_buyback_map)),
            ("mgmt", _mgmt_map, "增持", len(_mgmt_map)),
            ("momentum", _momentum_map, "动量", len(_momentum_map)),
            ("event", _event_map, "事件", len(_event_map)),
            ("outstanding", _bond_outstanding_map, "剩余规模", len(_bond_outstanding_map)),
            ("call_status", _call_status_map, "强赎状态", len(_call_status_map)),
            ("pledge", _pledge_map, "质押率", len(_pledge_map)),
            ("stock_names", _name_map, "正股名称", len(_name_map)),
            ("concept", _concept_map, "概念板块", len(_concept_map)),
            ("fund_flow", _fund_flow_map, "资金流向", len(_fund_flow_map)),
            ("bond_price", _bond_price_map, "集思录行情", len(_bond_price_map)),
        ]

        # 获取总可转债数量作为覆盖度参考
        total_bonds = 0
        try:
            engine = getattr(request.app.state, "engine", None)
            if engine:
                all_quotes = await engine.get_all_quotes()
                total_bonds = len(all_quotes)
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
            pass

        sources_status = []
        for name, data, label, count in sources:
            cov_pct = round(count / max(total_bonds, 1) * 100, 1) if total_bonds > 0 else 0
            last_ts = refresh_ts.get(name, 0)
            last_update = None
            if last_ts > 0:
                elapsed_s = int(now - last_ts)
                if elapsed_s < 60:
                    last_update = f"{elapsed_s}秒前"
                elif elapsed_s < 3600:
                    last_update = f"{elapsed_s // 60}分钟前"
                elif elapsed_s < 86400:
                    last_update = f"{elapsed_s // 3600}小时前"
                else:
                    last_update = f"{elapsed_s // 86400}天前"
            sources_status.append({
                "name": name,
                "label": label,
                "count": count,
                "coverage_pct": min(cov_pct, 100),
                "has_data": count > 0,
                "last_update": last_update,
                "last_update_ts": int(last_ts) if last_ts > 0 else None,
            })

        return {
            "total_bonds": total_bonds,
            "bond_stock_codes_loaded": bool(_ensure_bond_stock_codes_result_cache()),
            "sources": sources_status,
            "summary": {
                "total_sources": len(sources),
                "sources_with_data": sum(1 for s in sources_status if s["has_data"]),
                "avg_coverage_pct": round(
                    sum(s["coverage_pct"] for s in sources_status) / max(len(sources_status), 1), 1
                ),
            }
        }
    except Exception as e:
        logger.warning(f"[data-source-health] Error: {e}")
        return {"total_bonds": 0, "sources": [], "error": str(e)[:100]}


def _ensure_bond_stock_codes_result_cache():
    """返回 _bond_stock_codes 是否已加载（辅助 data_source_health 端点）"""
    try:
        from app.engine.data_enrich import _bond_stock_codes
        return len(_bond_stock_codes) > 0
    except Exception:
        return False
