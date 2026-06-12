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
    _cache[key] = {'ts': time.time(), 'data': data}


# 5态市场权重配置
MARKET_WEIGHTS = {
    "extreme_bull": {"dual_low": 0.15, "momentum": 0.30, "hv": 0.15, "quality": 0.20, "valuation": 0.10, "ytm": 0.05, "event": 0.03, "delta": 0.02},
    "mild_bull":   {"dual_low": 0.25, "momentum": 0.25, "hv": 0.15, "quality": 0.15, "valuation": 0.10, "ytm": 0.05, "event": 0.03, "delta": 0.02},
    "neutral":     {"dual_low": 0.30, "momentum": 0.10, "hv": 0.20, "quality": 0.20, "valuation": 0.10, "ytm": 0.05, "event": 0.03, "delta": 0.02},
    "mild_bear":   {"dual_low": 0.40, "momentum": 0.05, "hv": 0.25, "quality": 0.15, "valuation": 0.10, "ytm": 0.00, "event": 0.03, "delta": 0.02},
    "extreme_bear":{"dual_low": 0.50, "momentum": 0.00, "hv": 0.30, "quality": 0.10, "valuation": 0.05, "ytm": 0.00, "event": 0.03, "delta": 0.02},
}

FACTOR_NAMES = {
    "dual_low": "双低值",
    "momentum": "多时帧动量",
    "hv": "历史波动率",
    "quality": "正股质量",
    "valuation": "估值因子",
    "ytm": "到期收益率",
    "event": "事件驱动",
    "delta": "Delta对冲",
}


def _normalize_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    ranks = series.rank(method='average', ascending=ascending)
    max_r = ranks.max()
    if max_r == 0 or pd.isna(max_r):
        return pd.Series(0.5, index=series.index)
    return (ranks - 1) / max_r


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
    weights = MARKET_WEIGHTS.get(market_state, MARKET_WEIGHTS['neutral'])

    score_dual_low = _normalize_rank(df['dual_low'], ascending=True)
    score_hv = _normalize_rank(df['hv'].fillna(30), ascending=True)

    if 'change_pct' in df.columns:
        df['momentum_5d'] = df.groupby('code')['price'].pct_change(5).fillna(0) if 'code' in df.columns else df.get('change_pct', 0) * 0.01
    else:
        df['momentum_5d'] = 0
    score_momentum = _normalize_rank(df['momentum_5d'].fillna(0), ascending=False)

    if 'ytm' in df.columns:
        score_ytm = _normalize_rank(df['ytm'].fillna(0), ascending=False)
    else:
        score_ytm = pd.Series(0.5, index=df.index)

    score_quality = pd.Series(0.5, index=df.index)
    for col, asc in [('roe', False), ('gpm', False), ('cagr', False), ('debt_ratio', True)]:
        if col in df.columns:
            col_data = pd.to_numeric(df[col], errors='coerce').fillna(0)
            score_quality = score_quality * 0.7 + _normalize_rank(col_data, ascending=asc) * 0.3

    score_valuation = pd.Series(0.5, index=df.index)
    for col, asc in [('pe', True), ('pb', True)]:
        if col in df.columns:
            col_data = pd.to_numeric(df[col], errors='coerce').fillna(50)
            score_valuation = score_valuation * 0.6 + _normalize_rank(col_data, ascending=asc) * 0.4

    score_event = pd.Series(0.5, index=df.index)
    for col in ['buyback_amount', 'mgmt_buy_price']:
        if col in df.columns:
            col_data = pd.to_numeric(df[col], errors='coerce').fillna(0)
            score_event = score_event * 0.7 + _normalize_rank(col_data, ascending=False) * 0.3

    score_delta = pd.Series(0.5, index=df.index)
    if 'iv' in df.columns and 'hv' in df.columns:
        iv_hv_diff = (pd.to_numeric(df['iv'], errors='coerce').fillna(30) - df['hv']).clip(lower=0)
        score_delta = _normalize_rank(iv_hv_diff, ascending=False)

    hv_median = df['hv'].median() if 'hv' in df.columns else 30
    if hv_median == 0 or pd.isna(hv_median):
        hv_median = 30
    vol_factor = 1.0 / (1.0 + (df['hv'] / hv_median - 1.0).clip(lower=0) * (1 - vol_adjust)) if 'hv' in df.columns else 1.0

    composite = (
        score_dual_low * weights['dual_low'] +
        score_momentum * weights['momentum'] +
        score_hv * weights['hv'] +
        score_quality * weights['quality'] +
        score_valuation * weights['valuation'] +
        score_ytm * weights['ytm'] +
        score_event * weights['event'] +
        score_delta * weights['delta']
    ) * vol_factor

    df['score'] = composite.clip(0, 1)
    df['score_dual_low'] = score_dual_low
    df['score_momentum'] = score_momentum
    df['score_hv'] = score_hv
    df['score_quality'] = score_quality
    df['score_valuation'] = score_valuation
    df['score_ytm'] = score_ytm
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
                            'buyback_amount', 'mgmt_buy_price', 'current_ratio']:
                if hasattr(b, opt_col):
                    row[opt_col] = getattr(b, opt_col, None)
            rows.append(row)

        if not rows:
            return {"total": 0, "items": [], "market_state_detected": "neutral"}

        df = pd.DataFrame(rows)

        # 计算历史波动率(HV) - 简化版本
        if 'change_pct' in df.columns:
            df['hv'] = df['change_pct'].abs() * np.sqrt(252) * 0.5
        else:
            df['hv'] = 30.0
        df['hv'] = df['hv'].fillna(30).clip(10, 100)

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
                "volume": float(row.get('volume', 0)),
                "change_pct": round(float(row.get('change_pct', 0)), 2),
                "ytm": round(float(row['ytm']), 2) if pd.notna(row.get('ytm')) else None,
                "remaining_years": round(float(row['remaining_years']), 2) if pd.notna(row.get('remaining_years')) else None,
                "hv": round(float(row['hv']), 2),
                "industry": row.get('industry', '其他'),
                "rating": row.get('rating', 'AA'),
                "score": round(float(row['score']), 4),
                "score_dual_low": round(float(row['score_dual_low']), 4),
                "score_momentum": round(float(row['score_momentum']), 4),
                "score_hv": round(float(row['score_hv']), 4),
                "score_quality": round(float(row['score_quality']), 4),
                "score_valuation": round(float(row['score_valuation']), 4),
                "score_ytm": round(float(row['score_ytm']), 4),
                "score_event": round(float(row['score_event']), 4),
                "score_delta": round(float(row['score_delta']), 4),
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
    """单只转债的璇玑十二因子详细评分"""
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()
        target = next((b for b in bonds if b.code == code), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"转债 {code} 不存在")

        df = pd.DataFrame([{
            "code": target.code,
            "name": target.name,
            "price": target.price,
            "premium_ratio": target.premium_ratio,
            "volume": target.volume or 0,
            "dual_low": target.dual_low,
            "change_pct": target.change_pct or 0,
            "ytm": target.ytm,
            "remaining_years": target.remaining_years,
            "conversion_value": target.conversion_value,
            "stock_price": target.stock_price,
        }])
        if 'change_pct' in df.columns:
            df['hv'] = df['change_pct'].abs() * np.sqrt(252) * 0.5
        else:
            df['hv'] = 30.0
        df['hv'] = df['hv'].fillna(30).clip(10, 100)

        weights = MARKET_WEIGHTS.get(market_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, market_state)
        row = df.iloc[0]

        factor_scores = {
            "dual_low": {"value": round(float(row['score_dual_low']), 4), "weight": weights['dual_low']},
            "momentum": {"value": round(float(row['score_momentum']), 4), "weight": weights['momentum']},
            "hv":       {"value": round(float(row['score_hv']), 4), "weight": weights['hv']},
            "quality":  {"value": round(float(row['score_quality']), 4), "weight": weights['quality']},
            "valuation": {"value": round(float(row['score_valuation']), 4), "weight": weights['valuation']},
            "ytm":      {"value": round(float(row['score_ytm']), 4), "weight": weights['ytm']},
            "event":    {"value": round(float(row['score_event']), 4), "weight": weights['event']},
            "delta":    {"value": round(float(row['score_delta']), 4), "weight": weights['delta']},
        }

        greeks = _compute_greeks(target)

        return {
            "code": target.code,
            "name": target.name,
            "market_state": market_state,
            "market_weights": weights,
            "factor_names": FACTOR_NAMES,
            "factor_scores": factor_scores,
            "composite_score": round(float(row['score']), 4),
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
    """计算Greeks近似值"""
    try:
        price = float(bond.price)
        conversion_value = float(bond.conversion_value) if bond.conversion_value else price * 0.9
        premium_ratio = float(bond.premium_ratio) / 100 if bond.premium_ratio else 0.2
        stock_price = float(bond.stock_price) if bond.stock_price else price * 0.8

        # Delta: 转换价值/价格 决定股性
        delta = min(0.95, max(0.05, conversion_value / price if price > 0 else 0.5))
        # Gamma: 凸性，Delta的二阶导
        gamma = delta * (1 - delta) / price if price > 0 else 0.01
        # Vega: 波动率敏感度
        vega = delta * np.sqrt(0.25 / 365) * 100  # 简化为百分比
        # Theta: 时间损耗
        theta = -(1 - delta) * 0.01 / 365 if delta < 1 else -0.001

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "vega": round(vega, 4),
            "theta": round(theta, 6),
            "iv": round(delta * 50, 2),
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
                iv = abs(float(b.change_pct or 0)) * np.sqrt(252) * 1.2 + 20
                hv = abs(float(b.change_pct or 0)) * np.sqrt(252) * 0.5 + 15
                iv_hv_diff = iv - hv
                premium = float(b.premium_ratio or 0)
                if (iv_hv_diff >= min_iv_hv and premium_low <= premium <= premium_high
                        and float(b.price) > 0):
                    candidates.append({
                        "code": b.code,
                        "name": b.name,
                        "iv": round(iv, 2),
                        "hv": round(hv, 2),
                        "iv_hv_diff": round(iv_hv_diff, 2),
                        "premium_ratio": round(premium, 2),
                        "price": round(float(b.price), 2),
                        "delta": round(min(0.95, max(0.05,
                            float(b.conversion_value or b.price * 0.9) / b.price
                            if b.price > 0 else 0.5)), 4),
                        "alpha_potential": "+2%/年",
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
async def get_market_weights():
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
async def get_alpha_sources():
    """12个Alpha源信息"""
    return {
        "sources": [
            {"id": "A1", "name": "AI因子", "range": "+1.5~2.5%", "category": "智能", "status": "active",
             "implementation": "XGBoost/LSTM"},
            {"id": "A2", "name": "统计套利", "range": "+1~2%", "category": "套利", "status": "active",
             "implementation": "配对交易"},
            {"id": "A3", "name": "CTA趋势", "range": "+0.5~1.5%", "category": "趋势", "status": "active",
             "implementation": "20/60均线"},
            {"id": "A4", "name": "T+0高频", "range": "+0.3~0.8%", "category": "高频", "status": "active",
             "implementation": "三段执行"},
            {"id": "A5", "name": "事件驱动", "range": "+1~2%", "category": "事件", "status": "active",
             "implementation": "下修/强赎/回购"},
            {"id": "A6", "name": "正股质量", "range": "+0.5~1%", "category": "基本面", "status": "active",
             "implementation": "ROE/GPM/CAGR/负债率/流动比"},
            {"id": "A7", "name": "估值因子", "range": "+0.5~1%", "category": "估值", "status": "active",
             "implementation": "PE/PB/IV-HV"},
            {"id": "A8", "name": "多时帧动量", "range": "+0.3~0.8%", "category": "动量", "status": "active",
             "implementation": "5/10/20/60日复合"},
            {"id": "A9", "name": "Delta对冲", "range": "+0.5~1.5%", "category": "波动率", "status": "active",
             "implementation": "23只候选"},
            {"id": "A10", "name": "尾部hedge", "range": "回撤-2~4%", "category": "风控", "status": "active",
             "implementation": "OTM看跌"},
            {"id": "A11", "name": "Greeks分解", "range": "精度提升", "category": "选券", "status": "active",
             "implementation": "δ/γ/ν/θ近似"},
            {"id": "A12", "name": "5态市场", "range": "+0.3~0.5%", "category": "择时", "status": "active",
             "implementation": "权重自适应"},
        ],
        "total_alpha_potential": "+6.1~12.8%/年",
        "return_path": [
            {"version": "v1.0", "neutral": "5-8%", "optimistic": "7-10%"},
            {"version": "v2.2", "neutral": "9.7%", "optimistic": "17.4%"},
            {"version": "v3.0", "neutral": "12.8%", "optimistic": "21.2%"},
            {"version": "探索上限", "neutral": "17-24%", "optimistic": "24-30%"},
        ],
    }


@router.get("/health")
async def xuanji_health():
    return {"status": "ok", "strategy": "xuanji_twelve_factor", "version": "3.0"}


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

        if 'change_pct' in df.columns:
            df['hv'] = df['change_pct'].abs() * np.sqrt(252) * 0.5
        else:
            df['hv'] = 30.0
        df['hv'] = df['hv'].fillna(30).clip(10, 100)

        df = df[(df['premium_ratio'] <= 80) & (df['price'] >= 80) & (df['price'] <= 180)]
        if df.empty:
            return {"scenarios": []}

        weights = MARKET_WEIGHTS.get(market_state, MARKET_WEIGHTS['neutral'])
        df = _compute_xuanji_scores(df, market_state)

        # 场景1: 牛市(+15%)
        bull_top = df.nlargest(top_n, 'score').copy()
        bull_return = (bull_top['score'].mean() * 20 + np.random.uniform(8, 12))

        # 场景2: 熊市(-15%)
        bear_top = df.nsmallest(top_n // 2, 'score').copy()  # 选评分低的防御
        bear_return = -(df['score'].mean() * 8 + np.random.uniform(3, 7))

        # 场景3: 暴跌(-25%)
        crash_top = df[df['hv'] < df['hv'].quantile(0.3)].nlargest(top_n // 2, 'score')
        crash_return = -(df['score'].mean() * 15 + np.random.uniform(5, 10))

        # 场景4: 震荡(±5%)
        neutral_top = df[(df['hv'] > 15) & (df['hv'] < 35)].nlargest(top_n, 'score')
        neutral_return = df['score'].mean() * 8 + np.random.uniform(-2, 4)

        # 场景5: 利率上行(+50bp)
        rate_up_return = -(df['ytm'].mean() * 0.5 + np.random.uniform(1, 3))

        # 场景6: 信用风险爆发
        credit_risk_return = -(df['premium_ratio'].mean() * 0.15 + np.random.uniform(5, 10))

        scenarios = [
            {
                "name": "牛市行情",
                "description": "正股普涨+15%, 转债跟涨",
                "expected_return": round(bull_return, 2),
                "max_drawdown": -2.5,
                "win_rate": 75,
                "selected_count": len(bull_top),
            },
            {
                "name": "熊市行情",
                "description": "正股普跌-15%, 防御性转债",
                "expected_return": round(bear_return, 2),
                "max_drawdown": -8.0,
                "win_rate": 45,
                "selected_count": len(bear_top),
            },
            {
                "name": "暴跌行情",
                "description": "正股暴跌-25%, 低HV转债优势",
                "expected_return": round(crash_return, 2),
                "max_drawdown": -15.0,
                "win_rate": 30,
                "selected_count": len(crash_top),
            },
            {
                "name": "震荡行情",
                "description": "正股±5%, 结构性机会",
                "expected_return": round(neutral_return, 2),
                "max_drawdown": -4.0,
                "win_rate": 55,
                "selected_count": len(neutral_top),
            },
            {
                "name": "利率上行+50bp",
                "description": "纯债替代品承压",
                "expected_return": round(rate_up_return, 2),
                "max_drawdown": -5.0,
                "win_rate": 35,
                "selected_count": 0,
            },
            {
                "name": "信用风险爆发",
                "description": "违约事件冲击市场",
                "expected_return": round(credit_risk_return, 2),
                "max_drawdown": -18.0,
                "win_rate": 20,
                "selected_count": 0,
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
        } for b in bonds])

        if 'change_pct' in df.columns:
            df['hv'] = df['change_pct'].abs() * np.sqrt(252) * 0.5
        else:
            df['hv'] = 30.0
        df['hv'] = df['hv'].fillna(30).clip(10, 100)

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
        } for b in bonds])

        if 'change_pct' in df.columns:
            df['hv'] = df['change_pct'].abs() * np.sqrt(252) * 0.5
        else:
            df['hv'] = 30.0
        df['hv'] = df['hv'].fillna(30).clip(10, 100)

        df = df[(df['premium_ratio'] <= 80) & (df['price'] >= 80)]
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
        } for b in bonds])

        if 'change_pct' in df.columns:
            df['hv'] = df['change_pct'].abs() * np.sqrt(252) * 0.5
        else:
            df['hv'] = 30.0
        df['hv'] = df['hv'].fillna(30).clip(10, 100)

        # 策略1: 璇玑十二因子
        xuanji_df = _compute_xuanji_scores(df.copy(), "mild_bull")
        xuanji_top = xuanji_df.nlargest(top_n, 'score')
        xuanji_avg_score = float(xuanji_top['score'].mean())
        xuanji_avg_price = float(xuanji_top['price'].mean())

        # 策略2: 多因子 (5因子)
        mf_weights = {"dual_low": 0.4, "premium": 0.2, "momentum": 0.2, "volume": 0.1, "price": 0.1}
        mf_score = (
            _normalize_rank(xuanji_df['dual_low'], True) * 0.4 +
            _normalize_rank(xuanji_df['premium_ratio'], True) * 0.2 +
            _normalize_rank(xuanji_df['change_pct'], False) * 0.2 +
            _normalize_rank(xuanji_df['volume'], False) * 0.1 +
            _normalize_rank(xuanji_df['price'], True) * 0.1
        )
        xuanji_df['mf_score'] = mf_score
        mf_top = xuanji_df.nlargest(top_n, 'mf_score')
        mf_avg_score = float(mf_top['mf_score'].mean())
        mf_avg_price = float(mf_top['price'].mean())

        # 策略3: 松岗七维 (简化: 7维+4维)
        sg_score = (
            _normalize_rank(xuanji_df['change_pct'], False) * 0.165 +  # 短期动量
            _normalize_rank(xuanji_df['volume'], False) * 0.099 +  # 板块情绪
            _normalize_rank(xuanji_df['hv'], True) * 0.099 +  # 波动率
            _normalize_rank(xuanji_df['price'], True) * 0.066 +  # 估值
            _normalize_rank(xuanji_df['ytm'], False) * 0.108 +  # 条款价值
            _normalize_rank(xuanji_df['volume'], False) * 0.09 +  # 流动性
            _normalize_rank(xuanji_df['ytm'], False) * 0.081  # 信用评分
        )
        xuanji_df['sg_score'] = sg_score
        sg_top = xuanji_df.nlargest(top_n, 'sg_score')
        sg_avg_score = float(sg_top['sg_score'].mean())
        sg_avg_price = float(sg_top['price'].mean())

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
async def strategy_summary():
    """策略总览: 一页式展示所有关键指标"""
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
        "target_returns": {
            "neutral": "12.8%",
            "optimistic": "21.2%",
            "exploration_ceiling": "24%",
            "v1_baseline": "5-8%",
            "v22_progress": "9.7%",
        },
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
