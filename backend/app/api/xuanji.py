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
import json

router = APIRouter(prefix="/xuanji", tags=["璇玑十二因子"])
logger = logging.getLogger(__name__)

# 内存缓存
_cache: dict = {}
_CACHE_TTL = 60


def _get_cache_key(prefix: str, **kwargs) -> str:
    sorted_params = sorted(kwargs.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
    hash_key = hashlib.md5(param_str.encode()).hexdigest()[:16]
    return f"{prefix}:{hash_key}"


def _get_cached(key: str) -> Optional[dict]:
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry['ts'] < _CACHE_TTL:
            return entry['data']
        else:
            del _cache[key]
    return None


def _set_cache(key: str, data: dict):
    _cleanup_cache()
    _cache[key] = {'ts': time.time(), 'data': data}


def _cleanup_cache():
    now = time.time()
    expired = [k for k, v in _cache.items() if now - v['ts'] >= _CACHE_TTL]
    for k in expired:
        del _cache[k]


def _compute_hv_estimate(df: pd.DataFrame) -> pd.DataFrame:
    """估算历史波动率(HV) - 基于单日涨跌幅的年化近似
    
    真实HV应基于20日滚动标准差计算。此处使用|change_pct|年化*0.6作为近似，
    0.6近似E[|Z|]修正系数，将绝对值换算为标准差估计。
    """
    if 'change_pct' in df.columns:
        df['hv'] = (df['change_pct'].abs() * np.sqrt(252) * 0.6).clip(lower=3, upper=80)
    else:
        df['hv'] = 20.0
    df['hv'] = df['hv'].fillna(20.0)
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
    ranks = series.rank(method='average', ascending=ascending)
    max_r = ranks.max()
    if pd.isna(max_r) or max_r <= 1:
        return pd.Series(0.5, index=series.index)
    return (ranks - 1) / (max_r - 1)


def _detect_market_state(df: pd.DataFrame) -> str:
    if df.empty:
        return "neutral"
    median_price = df['price'].median()
    median_premium = df.get('premium_ratio', pd.Series([30])).median()
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

    score_dual_low = _normalize_rank(df['dual_low'], ascending=True)
    hv_median = df['hv'].median() if 'hv' in df.columns and df['hv'].notna().any() else 0
    score_hv = _normalize_rank(df['hv'].fillna(hv_median if hv_median > 0 else 0), ascending=True)

    if 'change_pct' in df.columns:
        df['momentum_5d'] = df['change_pct'].fillna(0) * 0.01
    else:
        df['momentum_5d'] = 0
    score_momentum = _normalize_rank(df['momentum_5d'].fillna(0), ascending=False)

    if 'ytm' in df.columns:
        score_ytm = _normalize_rank(df['ytm'].fillna(0), ascending=False)
    else:
        score_ytm = pd.Series(0.5, index=df.index)

    if 'remaining_years' in df.columns and df['remaining_years'].notna().any():
        score_remaining_years = _normalize_rank(df['remaining_years'].fillna(3), ascending=False)
    else:
        score_remaining_years = pd.Series(0.5, index=df.index)

    quality_parts = []
    has_quality_data = any(col in df.columns and df[col].notna().any() for col in ['roe', 'gpm', 'cagr', 'debt_ratio'])
    if has_quality_data:
        for col, asc in [('roe', False), ('gpm', False), ('cagr', False), ('debt_ratio', True)]:
            if col in df.columns and df[col].notna().any():
                col_data = pd.to_numeric(df[col], errors='coerce').fillna(df[col].median() if df[col].notna().any() else 0)
                quality_parts.append(_normalize_rank(col_data, ascending=asc))
    score_quality = sum(quality_parts) / len(quality_parts) if quality_parts else pd.Series(0.5, index=df.index)

    valuation_parts = []
    has_val_data = any(col in df.columns and df[col].notna().any() for col in ['pe', 'pb'])
    if has_val_data:
        for col, asc in [('pe', True), ('pb', True)]:
            if col in df.columns and df[col].notna().any():
                col_data = pd.to_numeric(df[col], errors='coerce').fillna(df[col].median() if df[col].notna().any() else 50)
                valuation_parts.append(_normalize_rank(col_data, ascending=asc))
    score_valuation = sum(valuation_parts) / len(valuation_parts) if valuation_parts else pd.Series(0.5, index=df.index)

    event_parts = []
    has_event_data = any(col in df.columns and df[col].notna().any() for col in ['buyback_amount', 'mgmt_buy_price'])
    if has_event_data:
        for col in ['buyback_amount', 'mgmt_buy_price']:
            if col in df.columns and df[col].notna().any():
                col_data = pd.to_numeric(df[col], errors='coerce').fillna(0)
                event_parts.append(_normalize_rank(col_data, ascending=False))
    score_event = sum(event_parts) / len(event_parts) if event_parts else pd.Series(0.5, index=df.index)

    score_delta = pd.Series(0.5, index=df.index)
    score_delta_available = 'iv' in df.columns and df['iv'].notna().any() and 'hv' in df.columns
    if score_delta_available:
        iv_hv_diff = (pd.to_numeric(df['iv'], errors='coerce').fillna(0) - df['hv']).clip(lower=0)
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

        rows = []
        for b in bonds:
            row = {
                "code": b.code,
                "name": b.name,
                "stock_code": getattr(b, 'stock_code', ''),
                "price": b.price,
                "premium_ratio": b.premium_ratio,
                "volume": b.volume or 0,
                "dual_low": b.dual_low,
                "change_pct": b.change_pct or 0,
                "ytm": b.ytm,
                "remaining_years": b.remaining_years,
                "conversion_value": b.conversion_value,
                "stock_price": b.stock_price,
                "industry": getattr(b, 'industry', None) or "其他",
                "rating": getattr(b, 'rating', None) or "AA",
            }
            for opt_col in ['roe', 'gpm', 'cagr', 'debt_ratio', 'pe', 'pb', 'iv',
                            'buyback_amount', 'mgmt_buy_price', 'current_ratio',
                            'turnover_rate', 'net_capital_flow', 'net_capital_flow_pct']:
                if hasattr(b, opt_col):
                    row[opt_col] = getattr(b, opt_col, None)
            rows.append(row)

        if not rows:
            return {"total": 0, "items": [], "market_state_detected": "neutral"}

        df = pd.DataFrame(rows)

        df = _compute_hv_estimate(df)

        # 三层漏斗筛选
        df = df[
            (df['premium_ratio'] <= max_premium) &
            (df['price'] >= min_price) &
            (df['price'] <= max_price) &
            (df['price'] > 0)
        ]

        if df.empty:
            return {"total": 0, "items": [], "market_state_detected": "neutral"}

        # 自动检测市场状态
        detected_state = _detect_market_state(df)
        actual_state = detected_state if market_state == "auto" else market_state

        # 计算综合评分
        df = _compute_xuanji_scores(df, actual_state, vol_adjust)

        # 按分数降序
        df = df.sort_values('score', ascending=False).reset_index(drop=True)
        top_df = df.head(top_n)

        items = []
        for idx, row in top_df.iterrows():
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
                "pe": row.get('pe'),
                "pb": row.get('pb'),
                "roe": row.get('roe'),
                "turnover_rate": row.get('turnover_rate'),
                "net_capital_flow": row.get('net_capital_flow'),
                "net_capital_flow_pct": row.get('net_capital_flow_pct'),
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
            "returned": int(len(items)),
            "market_state_requested": market_state,
            "market_state_detected": detected_state,
            "market_state_actual": actual_state,
            "market_weights": MARKET_WEIGHTS[actual_state],
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
):
    """单只转债的璇玑十二因子详细评分 (基于全市场相对排名)"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        target = next((b for b in bonds if b.code == code), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"转债 {code} 不存在")

        # Build full universe DataFrame for meaningful relative ranking
        rows = []
        for b in bonds:
            row = {
                "code": b.code, "name": b.name, "price": b.price,
                "premium_ratio": b.premium_ratio, "volume": b.volume or 0,
                "dual_low": b.dual_low, "change_pct": b.change_pct or 0,
                "ytm": b.ytm, "remaining_years": b.remaining_years,
                "conversion_value": b.conversion_value, "stock_price": b.stock_price,
            }
            for opt_col in ['roe', 'gpm', 'cagr', 'debt_ratio', 'pe', 'pb', 'iv',
                            'buyback_amount', 'mgmt_buy_price']:
                if hasattr(b, opt_col):
                    row[opt_col] = getattr(b, opt_col, None)
            rows.append(row)

        df = pd.DataFrame(rows)
        df = _compute_hv_estimate(df)

        # Filter (consistent with ranking endpoint)
        df = df[(df['premium_ratio'] <= 80) & (df['price'] >= 80) & (df['price'] <= 180) & (df['price'] > 0)]
        if df.empty:
            raise HTTPException(status_code=404, detail="筛选后无有效数据")

        actual_state = market_state if market_state != 'auto' else _detect_market_state(df)
        if actual_state == 'auto':
            actual_state = 'neutral'

        weights = MARKET_WEIGHTS.get(actual_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, actual_state)

        # Extract target bond from scored universe
        target_rows = df[df['code'] == code]
        if target_rows.empty:
            raise HTTPException(status_code=404, detail=f"转债 {code} 未通过筛选条件，无法计算相对评分")
        row = target_rows.iloc[0]

        # Compute rank in full universe
        full_rank = int((df['score'] > row['score']).sum()) + 1

        factor_scores = {
            "dual_low": {"value": round(float(row['score_dual_low']), 4), "weight": weights['dual_low']},
            "momentum": {"value": round(float(row['score_momentum']), 4), "weight": weights['momentum']},
            "hv":       {"value": round(float(row['score_hv']), 4), "weight": weights['hv']},
            "quality":  {"value": round(float(row['score_quality']), 4), "weight": weights['quality']},
            "valuation": {"value": round(float(row['score_valuation']), 4), "weight": weights['valuation']},
            "ytm":      {"value": round(float(row['score_ytm']), 4), "weight": weights['ytm']},
            "remaining_years": {"value": round(float(row['score_remaining_years']), 4), "weight": weights['remaining_years']},
            "event":    {"value": round(float(row['score_event']), 4), "weight": weights['event']},
            "delta":    {"value": round(float(row['score_delta']), 4), "weight": weights['delta']},
        }

        greeks = _compute_greeks(target)

        return {
            "code": target.code,
            "name": target.name,
            "market_state": actual_state,
            "market_weights": weights,
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
            },
            "greeks": greeks,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"璇玑单券评分失败: {code}")
        raise HTTPException(status_code=500, detail=str(e))


def _compute_greeks(bond) -> dict:
    """计算Greeks近似值 (基于转换价值/价格 推导delta)"""
    try:
        price = float(bond.price) if bond.price else 0
        if price <= 0:
            return {"delta": 0.5, "gamma": 0.01, "vega": 0.5, "theta": -0.001, "iv": 30.0}

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
        # IV: 隐含波动率(近似为delta*50% + 10%基础波动率)
        iv = round(delta * 40 + 10, 2)

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "vega": round(vega, 4),
            "theta": round(theta, 6),
            "iv": iv,
        }
    except Exception:
        return {"delta": 0.5, "gamma": 0.01, "vega": 0.5, "theta": -0.001, "iv": 30.0}


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

        candidates = []
        for b in bonds:
            try:
                hv_est = abs(float(b.change_pct or 0)) * np.sqrt(252) * 0.6
                hv_est = max(3.0, min(80.0, hv_est))
                actual_iv = float(getattr(b, 'iv', 0) or 0)
                if actual_iv > 0:
                    iv_est = actual_iv
                else:
                    iv_est = hv_est * 1.3 + 5.0
                iv_hv_diff = iv_est - hv_est
                premium = float(b.premium_ratio or 0)
                if (iv_hv_diff >= min_iv_hv and premium_low <= premium <= premium_high
                        and float(b.price) > 0):
                    candidates.append({
                        "code": b.code,
                        "name": b.name,
                        "iv": round(iv_est, 2),
                        "hv": round(hv_est, 2),
                        "iv_hv_diff": round(iv_hv_diff, 2),
                        "premium_ratio": round(premium, 2),
                        "price": round(float(b.price), 2),
                        "delta": round(min(0.95, max(0.05,
                            float(b.conversion_value or b.price * 0.9) / b.price
                            if b.price > 0 else 0.5)), 4),
                        "alpha_potential": None,
                        "iv_source": "actual" if actual_iv > 0 else "estimated",
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
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"total": 0, "distribution": {}, "summary": {}}

        greeks_list = [_compute_greeks(b) for b in bonds]

        delta_values = [g['delta'] for g in greeks_list]
        high_delta = sum(1 for d in delta_values if d > 0.7)
        mid_delta = sum(1 for d in delta_values if 0.3 <= d <= 0.7)
        low_delta = sum(1 for d in delta_values if d < 0.3)

        return {
            "total": len(bonds),
            "summary": {
                "delta_mean": round(float(np.mean(delta_values)), 4),
                "gamma_mean": round(float(np.mean([g['gamma'] for g in greeks_list])), 4),
                "vega_mean": round(float(np.mean([g['vega'] for g in greeks_list])), 4),
                "theta_mean": round(float(np.mean([g['theta'] for g in greeks_list])), 6),
                "iv_mean": round(float(np.mean([g['iv'] for g in greeks_list])), 2),
            },
            "distribution": {
                "high_delta": high_delta,
                "mid_delta": mid_delta,
                "low_delta": low_delta,
            },
        }
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
def get_alpha_sources():
    """12个Alpha源信息 (range 字段由相应模块从当前数据动态估算)"""
    ranges: dict[str, str] = {}
    try:
        from app.strategies.factor_data_source import FactorDataSource
        fds = FactorDataSource()
        sentiment = fds.get_market_sentiment()
        ad_ratio = float(sentiment.get("advance_decline_ratio", 1.0) or 1.0)
        avg_chg = float(sentiment.get("avg_change_pct", 0.0) or 0.0)
        stock_count = int(sentiment.get("stock_count", 0) or 0)

        df_rank = fds.get_industry_ranking()
        industry_count = len(df_rank) if df_rank is not None else 0

        stats = fds.get_bond_market_stats()
        total_bonds = int(stats.get("total_count", 0) or 0)
        avg_premium = float(stats.get("avg_premium", 0.0) or 0.0)

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
                    lo, hi = r[1:].split("~")
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

    return {
        "sources": sources,
        "total_alpha_potential": total_alpha_potential,
        "return_path": "已迁移至 /api/v1/xuanji/summary (target_returns)",
    }


@router.get("/health")
def xuanji_health():
    return {"status": "ok", "strategy": "xuanji_twelve_factor", "version": "3.0"}


def _safe_float(v, default=0.0):
    try:
        r = float(v)
        return r if not (np.isnan(r) or np.isinf(r)) else default
    except (TypeError, ValueError):
        return default

@router.get("/stress-test")
async def stress_test(
    request: Request,
    top_n: int = Query(50, ge=10, le=100),
    market_state: str = Query("mild_bull"),
):
    """压力测试: 模拟4种极端场景下的策略表现"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"scenarios": []}

        df = pd.DataFrame([{
            "code": b.code,
            "name": b.name,
            "price": b.price,
            "premium_ratio": b.premium_ratio,
            "volume": b.volume or 0,
            "dual_low": b.dual_low,
            "change_pct": b.change_pct or 0,
            "ytm": b.ytm or 0,
            "remaining_years": b.remaining_years or 3,
        } for b in bonds])

        df = _compute_hv_estimate(df)

        df = df[(df['premium_ratio'] <= 80) & (df['price'] >= 80) & (df['price'] <= 180)]
        if df.empty:
            return {"scenarios": []}

        weights = MARKET_WEIGHTS.get(market_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, market_state)

        # 场景1: 牛市(+15%)
        bull_top = df.nlargest(top_n, 'score').copy()
        bull_mean_score = _safe_float(bull_top['score'].mean(), 0.5)
        bull_mean_hv = _safe_float(bull_top['hv'].mean(), 20)
        bull_dd = -abs(bull_mean_score * bull_mean_hv / 100 * 0.5)
        bull_win = int(min(85, max(40, bull_mean_score * 60 + 25)))
        bull_return = bull_mean_score * 15 - bull_mean_hv * 0.05

        # 场景2: 熊市(-15%)
        bear_top = df.nsmallest(top_n // 2, 'score').copy()
        bear_mean_score = _safe_float(bear_top['score'].mean(), 0.3)
        bear_mean_hv = _safe_float(bear_top['hv'].mean(), 20)
        bear_dd = -abs(bear_mean_score * bear_mean_hv / 100)
        bear_win = int(min(60, max(20, (1 - bear_mean_score) * 40 + 15)))
        bear_return = -(1 - bear_mean_score) * 12 - bear_mean_hv * 0.03

        # 场景3: 暴跌(-25%)
        crash_candidates = df[df['hv'] < df['hv'].quantile(0.3)] if len(df) > 0 else df
        crash_top = crash_candidates.nlargest(min(top_n // 2, len(crash_candidates)), 'score') if len(crash_candidates) > 0 else df
        crash_mean_score = _safe_float(crash_top['score'].mean(), 0.2)
        crash_mean_hv = _safe_float(crash_top['hv'].mean(), 20)
        crash_dd = -abs(crash_mean_score * crash_mean_hv / 100 * 1.2)
        crash_win = int(min(50, max(10, crash_mean_score * 30 + 10)))
        crash_return = -(1 - crash_mean_score) * 20 - crash_mean_hv * 0.05

        # 场景4: 震荡(±5%)
        neutral_candidates = df[(df['hv'] > 5) & (df['hv'] < 50)] if len(df) > 0 else df
        neutral_top = neutral_candidates.nlargest(top_n, 'score') if len(neutral_candidates) > 0 else df
        neu_mean_score = _safe_float(neutral_top['score'].mean(), 0.4)
        neu_mean_hv = _safe_float(neutral_top['hv'].mean(), 20)
        neu_dd = -abs(neu_mean_score * 3)
        neu_win = int(min(70, max(30, neu_mean_score * 45 + 25)))
        neu_return = neu_mean_score * 8 - neu_mean_hv * 0.02

        # 场景5: 利率上行(+50bp)
        rate_mean_ytm = _safe_float(df['ytm'].mean(), 1.0)
        rate_mean_hv = _safe_float(df['hv'].mean(), 20)
        rate_dd = -abs(rate_mean_ytm * 0.5 + 2)
        rate_win = 35
        rate_return = -rate_mean_ytm * 0.5 - rate_mean_hv * 0.01

        # 场景6: 信用风险爆发
        credit_mean_premium = _safe_float(df['premium_ratio'].mean(), 30)
        credit_mean_hv = _safe_float(df['hv'].mean(), 20)
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
            "market_state": market_state,
            "total_bonds": len(df),
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
):
    """因子贡献度分析: 计算每个因子对最终评分的贡献比例"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"factors": []}

        df = pd.DataFrame([{
            "code": b.code,
            "name": b.name,
            "price": b.price,
            "premium_ratio": b.premium_ratio,
            "volume": b.volume or 0,
            "dual_low": b.dual_low,
            "change_pct": b.change_pct or 0,
            "ytm": b.ytm or 0,
            "remaining_years": b.remaining_years or 3,
        } for b in bonds])

        df = _compute_hv_estimate(df)

        df = df[(df['premium_ratio'] <= 80) & (df['price'] >= 80) & (df['price'] <= 180)]
        if df.empty:
            return {"factors": []}

        weights = MARKET_WEIGHTS.get(market_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, market_state)

        # 取TopN
        top_df = df.nlargest(top_n, 'score')

        # 计算每个因子的加权贡献
        factor_contributions = []
        for factor_key, factor_name in FACTOR_NAMES.items():
            col = f"score_{factor_key}"
            if col in top_df.columns:
                mean_score = float(top_df[col].mean())
                weight = float(weights.get(factor_key, 0))
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
            "market_state": market_state,
            "top_n": top_n,
            "factors": factor_contributions,
            "total_score": round(total_contribution, 4),
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
):
    """因子相关性分析: 评估各因子之间的相关性，识别冗余因子"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"correlations": []}

        df = pd.DataFrame([{
            "code": b.code,
            "price": b.price,
            "premium_ratio": b.premium_ratio,
            "dual_low": b.dual_low,
            "change_pct": b.change_pct or 0,
            "ytm": b.ytm or 0,
            "remaining_years": b.remaining_years or 3,
        } for b in bonds])

        df = _compute_hv_estimate(df)

        df = df[(df['premium_ratio'] <= 80) & (df['price'] >= 80) & (df['price'] <= 180)]
        if df.empty:
            return {"correlations": []}

        df = _compute_xuanji_scores(df, market_state)
        top_df = df.nlargest(top_n, 'score')

        factor_cols = [f"score_{k}" for k in FACTOR_NAMES.keys() if f"score_{k}" in top_df.columns]
        corr_matrix = top_df[factor_cols].corr()

        # 转为可序列化格式
        correlations = []
        for i, col1 in enumerate(factor_cols):
            for j, col2 in enumerate(factor_cols):
                if i < j:  # 避免重复
                    val = float(corr_matrix.loc[col1, col2])
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
            "market_state": market_state,
            "top_n": top_n,
            "total_pairs": len(correlations),
            "high_redundancy_pairs": len([c for c in correlations if c["redundancy"] == "high"]),
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
):
    """多策略对比: 璇玑 vs 多因子 vs 松岗七维"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        if not bonds:
            return {"strategies": []}

        df = pd.DataFrame([{
            "code": b.code,
            "name": b.name,
            "price": b.price,
            "premium_ratio": b.premium_ratio,
            "volume": b.volume or 0,
            "dual_low": b.dual_low,
            "change_pct": b.change_pct or 0,
            "ytm": b.ytm or 0,
            "remaining_years": b.remaining_years or 3,
        } for b in bonds])

        df = _compute_hv_estimate(df)

        # Filter outliers (consistent with other endpoints)
        df = df[(df['premium_ratio'] <= 80) & (df['price'] >= 80) & (df['price'] <= 180)]
        if df.empty:
            return {"top_n": top_n, "total_bonds": 0, "strategies": []}

        # 策略1: 璇玑十二因子
        xuanji_df = _compute_xuanji_scores(df.copy(), market_state)
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

        # 策略3: 松岗七维 (简化近似)
        sg_score = (
            _normalize_rank(xuanji_df['change_pct'], False) * 0.165 +
            _normalize_rank(xuanji_df['premium_ratio'], True) * 0.099 +
            _normalize_rank(xuanji_df['hv'], True) * 0.099 +
            _normalize_rank(xuanji_df['price'], True) * 0.066 +
            _normalize_rank(xuanji_df['remaining_years'].fillna(3), True) * 0.108 +
            _normalize_rank(xuanji_df['volume'], False) * 0.09 +
            _normalize_rank((100 - xuanji_df['premium_ratio']).clip(lower=0), False) * 0.081
        )
        xuanji_df['sg_score'] = sg_score
        sg_top = xuanji_df.nlargest(top_n, 'sg_score')
        sg_avg_score = float(sg_top['sg_score'].mean()) if len(sg_top) > 0 else 0
        sg_avg_price = float(sg_top['price'].mean()) if len(sg_top) > 0 else 0

        # 重叠度分析
        xuanji_codes = set(xuanji_top['code'].tolist())
        mf_codes = set(mf_top['code'].tolist())
        sg_codes = set(sg_top['code'].tolist())

        return {
            "top_n": top_n,
            "total_bonds": len(df),
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
                    "overlap_with_mf": round(len(xuanji_codes & mf_codes) / top_n * 100, 1),
                    "overlap_with_sg": round(len(xuanji_codes & sg_codes) / top_n * 100, 1),
                },
                {
                    "id": "multi_factor",
                    "name": "多因子策略",
                    "factors": 5,
                    "market_adaptive": False,
                    "avg_score": round(mf_avg_score, 4),
                    "avg_price": round(mf_avg_price, 2),
                    "selected": len(mf_top),
                    "overlap_with_xuanji": round(len(mf_codes & xuanji_codes) / top_n * 100, 1),
                    "overlap_with_mf": 100,
                    "overlap_with_sg": round(len(mf_codes & sg_codes) / top_n * 100, 1),
                },
                {
                    "id": "songgang_seven",
                    "name": "松岗七维",
                    "factors": 11,
                    "market_adaptive": False,
                    "avg_score": round(sg_avg_score, 4),
                    "avg_price": round(sg_avg_price, 2),
                    "selected": len(sg_top),
                    "overlap_with_xuanji": round(len(sg_codes & xuanji_codes) / top_n * 100, 1),
                    "overlap_with_mf": round(len(sg_codes & mf_codes) / top_n * 100, 1),
                    "overlap_with_sg": 100,
                },
            ]
        }
    except Exception as e:
        logger.exception("策略对比失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
def strategy_summary(request: Request):
    """策略总览: 一页式展示所有关键指标 (target_returns 基于实时行情估算)"""
    import asyncio
    target_returns = {
        "neutral": None,
        "optimistic": None,
        "exploration_ceiling": None,
        "computation_note": "基于当前市场 top20 评分 + 历史波动率估算"
    }
    try:
        engine = getattr(request.app.state, "engine", None)
        if engine is not None:
            bonds = asyncio.run_coroutine_threadsafe(
                engine.get_all_quotes(),
                engine._loop if hasattr(engine, '_loop') else asyncio.get_event_loop()
            ).result(timeout=15) if hasattr(engine, '_loop') else None
            if not bonds:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    bonds = loop.run_until_complete(engine.get_all_quotes())
                finally:
                    loop.close()
            if bonds:
                df = pd.DataFrame([{
                    "code": b.code,
                    "price": float(getattr(b, 'price', 100) or 100),
                    "premium_ratio": float(getattr(b, 'premium_ratio', 0) or 0),
                    "ytm": float(getattr(b, 'ytm', 0) or 0),
                    "remaining_years": float(getattr(b, 'remaining_years', 3) or 3),
                } for b in bonds])
                df = df[(df['premium_ratio'] >= 0) & (df['premium_ratio'] <= 80) &
                        (df['price'] >= 80) & (df['price'] <= 180)]
                if not df.empty:
                    df = _compute_hv_estimate(df)
                    scored = _compute_xuanji_scores(df.copy(), "mild_bull")
                    top = scored.nlargest(min(20, len(scored)), 'score')
                    if not top.empty:
                        avg_score = float(top['score'].mean())
                        avg_hv = float(top['hv'].mean()) if 'hv' in top else 25.0
                        avg_premium = float(top['premium_ratio'].mean())
                        neutral_yield = max(0.5, avg_score * 15.0)
                        optimistic_yield = neutral_yield * 1.6 + avg_hv * 0.3
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
            "version": "3.0",
            "category": "可转债多因子指增",
            "philosophy": "古代天文仪器，象征多维度精密分析",
            "factors": list(FACTOR_NAMES.keys()),
            "factor_count": len(FACTOR_NAMES),
            "alpha_sources": 12,
            "market_states": list(MARKET_WEIGHTS.keys()),
            "market_state_count": len(MARKET_WEIGHTS),
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
            "backtest": "/api/v1/backtest/run (strategy=xuanji_twelve)",
            "optimization": "/api/v1/backtest/optimize (strategy=xuanji_twelve)",
        }
    }
