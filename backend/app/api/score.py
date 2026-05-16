from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Any
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np
import time
import hashlib
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# 内存缓存
_cache: dict = {}
_CACHE_TTL = 60  # 缓存60秒
_LONG_CACHE_TTL = 300  # 长缓存5分钟（用于历史数据）


def _get_cache_key(prefix: str, **kwargs) -> str:
    """生成缓存key"""
    sorted_params = sorted(kwargs.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
    hash_key = hashlib.md5(param_str.encode()).hexdigest()[:16]
    return f"{prefix}:{hash_key}"


def _get_cached(key: str, ttl: int = None) -> Optional[dict]:
    """获取缓存"""
    ttl = ttl or _CACHE_TTL
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry['ts'] < ttl:
            logger.debug(f"[Cache] Hit: {key}")
            return entry['data']
        else:
            del _cache[key]
            logger.debug(f"[Cache] Expired: {key}")
    return None


def _set_cache(key: str, data: dict, ttl: int = None) -> None:
    """设置缓存"""
    _cache[key] = {'ts': time.time(), 'data': data, 'ttl': ttl or _CACHE_TTL}
    logger.debug(f"[Cache] Set: {key}")
    # 清理过期缓存
    _cleanup_cache()


def _cleanup_cache():
    """清理过期缓存"""
    global _cache
    now = time.time()
    expired = [k for k, v in _cache.items() if now - v['ts'] >= v.get('ttl', _CACHE_TTL) * 2]
    for k in expired:
        del _cache[k]
    if expired:
        logger.debug(f"[Cache] Cleaned {len(expired)} expired entries")


def _get_cache_stats() -> dict:
    """获取缓存统计信息"""
    now = time.time()
    valid = 0
    expired = 0
    for k, v in _cache.items():
        if now - v['ts'] < v.get('ttl', _CACHE_TTL):
            valid += 1
        else:
            expired += 1
    return {
        "total_entries": len(_cache),
        "valid_entries": valid,
        "expired_entries": expired,
        "cache_keys": list(_cache.keys())[:20],  # 返回前20个key
    }


def _clear_cache():
    """清空缓存"""
    global _cache
    count = len(_cache)
    _cache = {}
    return count


class ScoreRankingParams(BaseModel):
    weight_dual_low: float = 0.4
    weight_premium: float = 0.2
    weight_momentum: float = 0.2
    weight_volume: float = 0.1
    weight_price: float = 0.1
    max_premium: float = 50.0


# ── 响应模型 ──

class BacktestResultItem(BaseModel):
    id: int
    run_ts: Optional[str] = None
    start_date: str = ""
    end_date: str = ""
    top_n: int = 20
    hold_days: int = 5
    avg_return_pct: float = 0
    win_rate: float = 0
    total_periods: int = 0
    params_json: Optional[str] = None

class BacktestHistoryResponse(BaseModel):
    results: list[BacktestResultItem]
    total: int

class BacktestDetailItem(BaseModel):
    backtest_id: int
    date: str = ""
    end_date: str = ""
    top_n: int = 0
    avg_return_pct: float = 0
    win_rate: float = 0
    max_return: float = 0
    min_return: float = 0
    max_drawdown: float = 0

class BacktestDetailResponse(BaseModel):
    summary: BacktestResultItem
    details: list[BacktestDetailItem]

class BacktestDeleteResponse(BaseModel):
    deleted: bool
    backtest_id: int

class BacktestCleanupResponse(BaseModel):
    deleted_count: int
    keep_days: int

class ScoreBacktestSummary(BaseModel):
    total_periods: int
    avg_return_pct: float
    avg_win_rate: float

class ScoreBacktestDetail(BaseModel):
    date: str
    end_date: str
    top_n: int
    avg_return_pct: float
    win_rate: float
    max_return: float
    min_return: float

class ScoreBacktestResponse(BaseModel):
    period: dict[str, Any]
    top_n: int
    summary: ScoreBacktestSummary
    details: list[ScoreBacktestDetail]


def _normalize_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """将 Series 转换为 0~1 的排名分数"""
    ranks = series.rank(method='average', ascending=ascending)
    max_r = ranks.max()
    if max_r == 0 or pd.isna(max_r):
        return pd.Series(0.5, index=series.index)
    return (ranks - 1) / max_r


def _compute_scores(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """计算评分"""
    score_dual_low = _normalize_rank(df['dual_low'], ascending=True)
    score_premium = _normalize_rank(df['premium_ratio'], ascending=True)
    score_momentum = _normalize_rank(df['change_pct'], ascending=False)
    score_volume = _normalize_rank(df['volume'], ascending=False)
    score_price = _normalize_rank(df['price'], ascending=True)

    total_w = sum(weights.values())
    if total_w == 0:
        total_w = 1.0

    df['score'] = (
        score_dual_low * weights['dual_low'] +
        score_premium * weights['premium'] +
        score_momentum * weights['momentum'] +
        score_volume * weights['volume'] +
        score_price * weights['price']
    ) / total_w

    df['score_dual_low'] = score_dual_low
    df['score_premium'] = score_premium
    df['score_momentum'] = score_momentum
    df['score_volume'] = score_volume
    df['score_price'] = score_price

    return df


@router.get("/score-ranking")
async def get_score_ranking(
    request: Request,
    top_n: int = Query(60, ge=10, le=200, description="返回前N名"),
    max_premium: float = Query(50.0, ge=10, le=100, description="溢价率上限"),
    min_price: float = Query(80.0, ge=50, le=150, description="最低价格"),
    weight_dual_low: float = Query(0.4, ge=0, le=1),
    weight_premium: float = Query(0.2, ge=0, le=1),
    weight_momentum: float = Query(0.2, ge=0, le=1),
    weight_volume: float = Query(0.1, ge=0, le=1),
    weight_price: float = Query(0.1, ge=0, le=1),
):
    """
    多因子评分排名 - 返回所有公司的综合评分排名
    """
    # 检查缓存
    cache_key = _get_cache_key(
        "score_ranking",
        top_n=top_n,
        max_premium=max_premium,
        min_price=min_price,
        w1=weight_dual_low,
        w2=weight_premium,
        w3=weight_momentum,
        w4=weight_volume,
        w5=weight_price,
    )
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"total": 0, "items": []}

        # 转换为DataFrame
        rows = []
        for b in bonds:
            rows.append({
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
            })

        if not rows:
            return {"total": 0, "items": []}

        df = pd.DataFrame(rows)

        # 过滤条件：只过滤无效数据，不过滤 volume=0 的债券
        # （akshare 的 bond_zh_cov 接口不返回成交量，volume=0 是正常情况）
        df = df[
            (df['premium_ratio'] <= max_premium) &
            (df['price'] >= min_price) &
            (df['price'] > 0)
        ]

        if df.empty:
            return {"total": 0, "items": []}

        # 计算评分
        weights = {
            'dual_low': weight_dual_low,
            'premium': weight_premium,
            'momentum': weight_momentum,
            'volume': weight_volume,
            'price': weight_price,
        }
        df = _compute_scores(df, weights)

        # 按分数降序排序
        df = df.sort_values('score', ascending=False).reset_index(drop=True)

        # 取前N名
        top_df = df.head(top_n)

        items = []
        for idx, row in top_df.iterrows():
            items.append({
                "rank": idx + 1,
                "code": row['code'],
                "name": row['name'],
                "price": round(row['price'], 3),
                "premium_ratio": round(row['premium_ratio'], 2),
                "dual_low": round(row['dual_low'], 2),
                "volume": int(row['volume']),
                "change_pct": round(row['change_pct'], 2),
                "ytm": round(row['ytm'], 2) if row['ytm'] else None,
                "remaining_years": round(row['remaining_years'], 2) if row['remaining_years'] else None,
                "conversion_value": round(row['conversion_value'], 2) if row['conversion_value'] else None,
                "stock_price": round(row['stock_price'], 2) if row['stock_price'] else None,
                "score": round(row['score'], 4),
                "score_dual_low": round(row['score_dual_low'], 4),
                "score_premium": round(row['score_premium'], 4),
                "score_momentum": round(row['score_momentum'], 4),
                "score_volume": round(row['score_volume'], 4),
                "score_price": round(row['score_price'], 4),
            })

        result = {
            "total": len(df),
            "returned": len(items),
            "params": {
                "max_premium": max_premium,
                "min_price": min_price,
                "weights": weights,
            },
            "items": items,
            "cached": False,
        }

        # 设置缓存
        _set_cache(cache_key, result)
        result["cached"] = False

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-ranking/full")
async def get_full_score_ranking(request: Request):
    """
    返回完整的评分排名（所有公司，不过滤）
    """
    # 检查缓存 - 使用长缓存
    cache_key = _get_cache_key("score_ranking_full")
    cached = _get_cached(cache_key, ttl=_LONG_CACHE_TTL)
    if cached:
        cached["cached"] = True
        return cached

    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"total": 0, "items": []}

        rows = []
        for b in bonds:
            rows.append({
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
            })

        if not rows:
            return {"total": 0, "items": []}

        df = pd.DataFrame(rows)

        # 只过滤有效数据
        df = df[(df['price'] > 0) & (df['dual_low'] > 0)]

        if df.empty:
            return {"total": 0, "items": []}

        # 使用默认权重计算
        weights = {'dual_low': 0.4, 'premium': 0.2, 'momentum': 0.2, 'volume': 0.1, 'price': 0.1}
        df = _compute_scores(df, weights)

        df = df.sort_values('score', ascending=False).reset_index(drop=True)

        items = []
        for idx, row in df.iterrows():
            items.append({
                "rank": idx + 1,
                "code": row['code'],
                "name": row['name'],
                "price": round(row['price'], 3),
                "premium_ratio": round(row['premium_ratio'], 2),
                "dual_low": round(row['dual_low'], 2),
                "volume": int(row['volume']),
                "change_pct": round(row['change_pct'], 2),
                "score": round(row['score'], 4),
            })

        result = {"total": len(items), "items": items, "cached": False}

        # 设置缓存 - 使用长缓存
        _set_cache(cache_key, result, ttl=_LONG_CACHE_TTL)
        result["cached"] = False

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-ranking/stats")
async def get_score_stats(request: Request):
    """
    获取评分统计信息
    """
    cache_key = _get_cache_key("score_stats")
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"total": 0}

        scores = []
        for b in bonds:
            if b.price > 0 and b.dual_low > 0:
                scores.append({
                    "score": b.dual_low,
                    "premium": b.premium_ratio,
                    "price": b.price,
                })

        if not scores:
            return {"total": 0}

        df = pd.DataFrame(scores)

        result = {
            "total": len(scores),
            "avg_dual_low": round(df['score'].mean(), 2),
            "avg_premium": round(df['premium'].mean(), 2),
            "avg_price": round(df['price'].mean(), 2),
            "min_dual_low": round(df['score'].min(), 2),
            "max_dual_low": round(df['score'].max(), 2),
            "distribution": {
                "dual_low_130": len(df[df['score'] < 130]),
                "dual_low_150": len(df[(df['score'] >= 130) & (df['score'] < 150)]),
                "dual_low_180": len(df[(df['score'] >= 150) & (df['score'] < 180)]),
                "dual_low_high": len(df[df['score'] >= 180]),
            }
        }

        _set_cache(cache_key, result)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 评分历史API ──

@router.post("/score-ranking/save-snapshot")
async def save_score_snapshot(request: Request):
    """保存当日评分快照"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"status": "ok", "saved": 0}

        # 转换为DataFrame并计算评分
        rows = []
        for b in bonds:
            rows.append({
                "code": b.code,
                "name": b.name,
                "price": b.price,
                "premium_ratio": b.premium_ratio,
                "volume": b.volume or 0,
                "dual_low": b.dual_low,
                "change_pct": b.change_pct or 0,
            })

        df = pd.DataFrame(rows)
        df = df[(df['price'] > 0) & (df['dual_low'] > 0)]

        if df.empty:
            return {"status": "ok", "saved": 0}

        weights = {'dual_low': 0.4, 'premium': 0.2, 'momentum': 0.2, 'volume': 0.1, 'price': 0.1}
        df = _compute_scores(df, weights)

        scores = []
        for _, row in df.iterrows():
            scores.append({
                'code': row['code'],
                'name': row['name'],
                'score': row['score'],
                'score_dual_low': row['score_dual_low'],
                'score_premium': row['score_premium'],
                'score_momentum': row['score_momentum'],
                'score_volume': row['score_volume'],
                'score_price': row['score_price'],
                'price': row['price'],
                'premium_ratio': row['premium_ratio'],
                'dual_low': row['dual_low'],
                'volume': row['volume'],
            })

        storage.save_score_snapshot(scores)
        return {"status": "ok", "saved": len(scores)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-ranking/history/{code}")
async def get_score_history(
    request: Request,
    code: str,
    days: int = Query(30, ge=1, le=365, description="查询天数"),
):
    """获取某只转债的评分历史"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        history = storage.get_score_history(code, days)
        return {"code": code, "days": days, "items": history}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-ranking/history-batch")
async def get_score_history_batch(
    request: Request,
    codes: str = Query(..., description="转债代码列表，逗号分隔"),
    days: int = Query(30, ge=1, le=365, description="查询天数"),
):
    """批量获取多只转债的评分历史"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        history = storage.get_score_history_batch(code_list, days)
        return {"codes": code_list, "days": days, "data": history}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-ranking/dates")
async def get_score_dates(request: Request, limit: int = Query(30, ge=1, le=365)):
    """获取有评分数据的日期列表"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        dates = storage.get_score_dates(limit)
        return {"dates": dates}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-ranking/daily/{snapshot_date}")
async def get_daily_score_ranking(
    request: Request,
    snapshot_date: str,
    top_n: int = Query(60, ge=10, le=200, description="返回前N名"),
):
    """获取某日的评分排名"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        try:
            query_date = date.fromisoformat(snapshot_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

        ranking = storage.get_daily_score_ranking(query_date, top_n)
        return {"date": snapshot_date, "top_n": top_n, "items": ranking}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 评分预警API ──

class ScoreAlertRequest(BaseModel):
    code: str
    name: str = ""
    alert_type: str = "score"  # score, price, dual_low, premium
    threshold: float
    direction: str = "above"  # above, below
    enabled: bool = True


@router.post("/score-alerts")
async def add_score_alert(req: ScoreAlertRequest, request: Request):
    """添加评分预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        alert_id = storage.add_score_alert(req.model_dump())
        return {"status": "ok", "id": alert_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-alerts")
async def get_score_alerts(request: Request, enabled_only: bool = False):
    """获取所有评分预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        alerts = storage.get_score_alerts(enabled_only)
        return {"alerts": alerts}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/score-alerts/{alert_id}")
async def remove_score_alert(alert_id: int, request: Request):
    """删除评分预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        storage.remove_score_alert(alert_id)
        return {"status": "ok"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/score-alerts/check")
async def check_score_alerts(request: Request):
    """检查评分预警并返回触发的预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"triggered": []}

        # 获取当前行情数据
        bond_map = {b.code: b for b in bonds}

        # 获取所有启用的预警
        alerts = storage.get_score_alerts(enabled_only=True)

        triggered = []
        for alert in alerts:
            code = alert['code']
            if code not in bond_map:
                continue

            bond = bond_map[code]

            # 根据预警类型获取当前值
            if alert['alert_type'] == 'score':
                # 需要计算评分，这里简化使用dual_low
                current_value = bond.dual_low
            elif alert['alert_type'] == 'price':
                current_value = bond.price
            elif alert['alert_type'] == 'dual_low':
                current_value = bond.dual_low
            elif alert['alert_type'] == 'premium':
                current_value = bond.premium_ratio
            else:
                continue

            threshold = alert['threshold']
            direction = alert['direction']

            # 检查是否触发
            is_triggered = False
            if direction == 'above' and current_value >= threshold:
                is_triggered = True
            elif direction == 'below' and current_value <= threshold:
                is_triggered = True

            if is_triggered:
                triggered.append({
                    "code": code,
                    "name": alert.get('name', bond.name),
                    "alert_type": alert['alert_type'],
                    "direction": direction,
                    "threshold": threshold,
                    "current_value": current_value,
                    "triggered_at": datetime.now().isoformat(),
                })
                storage.update_alert_triggered(alert['id'])
                # 记录预警历史
                storage.add_alert_history({
                    'alert_id': alert['id'],
                    'alert_type': alert['alert_type'],
                    'code': code,
                    'name': alert.get('name', bond.name),
                    'threshold': threshold,
                    'current_value': current_value,
                })

        return {"triggered": triggered, "total_alerts": len(alerts)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 评分回测API ──

@router.get("/score-backtest/accuracy", response_model=ScoreBacktestResponse)
async def get_score_accuracy(
    request: Request,
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    top_n: int = Query(20, ge=5, le=100, description="Top N排名"),
    hold_days: int = Query(5, ge=1, le=30, description="持有天数"),
):
    """
    评分预测准确率回测
    分析历史Top N评分的公司在持有期内的收益率
    """
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")

        # 获取日期范围内的评分数据
        result = storage.conn.execute("""
            SELECT DISTINCT snapshot_date FROM score_history
            WHERE snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY snapshot_date
        """, (start, end)).fetchall()

        if not result:
            return {"error": "No score history data in the specified range"}

        dates = [r[0] for r in result]

        # 按日期分组分析
        analysis_results = []

        for i, snap_date in enumerate(dates[:-hold_days]):
            # 获取当日Top N
            top_scores = storage.conn.execute("""
                SELECT code, name, score, price FROM score_history
                WHERE snapshot_date = ?
                ORDER BY score DESC
                LIMIT ?
            """, (snap_date, top_n)).fetchall()

            if not top_scores:
                continue

            # 计算持有期结束日期
            end_idx = min(i + hold_days, len(dates) - 1)
            end_date_val = dates[end_idx]

            # 获取持有期末的价格
            end_prices = storage.conn.execute("""
                SELECT code, price FROM score_history
                WHERE snapshot_date = ? AND code IN ({})
            """.format(",".join(["?" for _ in top_scores])), [end_date_val] + [t[0] for t in top_scores]).fetchall()

            end_price_map = {r[0]: r[1] for r in end_prices}

            # 计算收益率
            returns = []
            for code, name, score, start_price in top_scores:
                end_price = end_price_map.get(code)
                if end_price and start_price and start_price > 0:
                    ret = (end_price - start_price) / start_price * 100
                    returns.append({
                        "code": code,
                        "name": name,
                        "score": round(score, 4),
                        "start_price": round(start_price, 3),
                        "end_price": round(end_price, 3),
                        "return_pct": round(ret, 2),
                    })

            if returns:
                avg_return = sum(r["return_pct"] for r in returns) / len(returns)
                win_rate = len([r for r in returns if r["return_pct"] > 0]) / len(returns) * 100
                analysis_results.append({
                    "date": str(snap_date),
                    "end_date": str(end_date_val),
                    "top_n": len(returns),
                    "avg_return_pct": round(avg_return, 2),
                    "win_rate": round(win_rate, 1),
                    "max_return": round(max(r["return_pct"] for r in returns), 2),
                    "min_return": round(min(r["return_pct"] for r in returns), 2),
                })

        if not analysis_results:
            return {"error": "Insufficient data for backtest"}

        # 汇总统计
        total_avg_return = sum(r["avg_return_pct"] for r in analysis_results) / len(analysis_results)
        total_win_rate = sum(r["win_rate"] for r in analysis_results) / len(analysis_results)

        # 持久化回测结果
        try:
            storage.save_backtest_result(
                summary={"total_periods": len(analysis_results), "avg_return_pct": round(total_avg_return, 2), "avg_win_rate": round(total_win_rate, 1)},
                details=analysis_results,
                params={"startDate": start_date, "endDate": end_date, "topN": top_n, "holdDays": hold_days},
            )
        except Exception:
            logger.debug("Failed to persist backtest result", exc_info=True)

        return {
            "period": {"start": start_date, "end": end_date, "hold_days": hold_days},
            "top_n": top_n,
            "summary": {
                "total_periods": len(analysis_results),
                "avg_return_pct": round(total_avg_return, 2),
                "avg_win_rate": round(total_win_rate, 1),
            },
            "details": analysis_results,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backtest-history", response_model=BacktestHistoryResponse)
async def get_backtest_history(
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """获取回测历史结果列表"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        results, total = storage.get_backtest_results(limit=limit, offset=offset)
        return {"results": results, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backtest-history/{backtest_id}", response_model=BacktestDetailResponse)
async def get_backtest_detail(
    request: Request,
    backtest_id: int,
):
    """获取某次回测的详细结果"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        summary = storage.get_backtest_result(backtest_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Backtest result not found")

        details = storage.get_backtest_details(backtest_id)
        return {"summary": summary, "details": details}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/backtest-history/{backtest_id}", response_model=BacktestDeleteResponse)
async def delete_backtest_result(
    request: Request,
    backtest_id: int,
):
    """删除某次回测结果"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        deleted = storage.delete_backtest_result(backtest_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Backtest result not found")
        return {"deleted": True, "backtest_id": backtest_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backtest-history/cleanup", response_model=BacktestCleanupResponse)
async def cleanup_backtest_history(
    request: Request,
    keep_days: int = Query(90, ge=1, le=365, description="保留天数"),
):
    """清理过期的回测历史"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        deleted = storage.cleanup_backtest_results(keep_days=keep_days)
        return {"deleted_count": deleted, "keep_days": keep_days}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-backtest/top-performers")
async def get_top_performers(
    request: Request,
    snapshot_date: str = Query(..., description="评分日期 YYYY-MM-DD"),
    top_n: int = Query(20, ge=5, le=100),
    hold_days: int = Query(5, ge=1, le=30),
):
    """
    获取某日Top N评分的公司在持有期内的表现
    """
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        try:
            start = date.fromisoformat(snapshot_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")

        # 获取评分日期后的N个交易日
        dates = storage.conn.execute("""
            SELECT DISTINCT snapshot_date FROM score_history
            WHERE snapshot_date >= ?
            ORDER BY snapshot_date
            LIMIT ?
        """, (start, hold_days + 1)).fetchall()

        if len(dates) < 2:
            return {"error": "Insufficient data after the specified date"}

        end_date = dates[-1][0]

        # 获取当日Top N
        top_scores = storage.conn.execute("""
            SELECT code, name, score, price FROM score_history
            WHERE snapshot_date = ?
            ORDER BY score DESC
            LIMIT ?
        """, (start, top_n)).fetchall()

        if not top_scores:
            return {"error": "No data for the specified date"}

        # 获取持有期末价格
        end_prices = storage.conn.execute("""
            SELECT code, name, price FROM score_history
            WHERE snapshot_date = ? AND code IN ({})
        """.format(",".join(["?" for _ in top_scores])), [end_date] + [t[0] for t in top_scores]).fetchall()

        end_price_map = {r[0]: (r[1], r[2]) for r in end_prices}

        # 计算结果
        results = []
        for code, name, score, start_price in top_scores:
            end_data = end_price_map.get(code)
            if end_data and start_price and start_price > 0:
                end_name, end_price = end_data
                ret = (end_price - start_price) / start_price * 100
                results.append({
                    "rank": len(results) + 1,
                    "code": code,
                    "name": name,
                    "score": round(score, 4),
                    "start_price": round(start_price, 3),
                    "end_price": round(end_price, 3),
                    "return_pct": round(ret, 2),
                    "is_winner": ret > 0,
                })

        winners = [r for r in results if r["is_winner"]]
        avg_return = sum(r["return_pct"] for r in results) / len(results) if results else 0

        return {
            "start_date": snapshot_date,
            "end_date": str(end_date),
            "hold_days": hold_days,
            "summary": {
                "total": len(results),
                "winners": len(winners),
                "win_rate": round(len(winners) / len(results) * 100, 1) if results else 0,
                "avg_return_pct": round(avg_return, 2),
                "max_return": round(max(r["return_pct"] for r in results), 2) if results else 0,
                "min_return": round(min(r["return_pct"] for r in results), 2) if results else 0,
            },
            "performers": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score-backtest/ranking-comparison")
async def compare_rankings(
    request: Request,
    date1: str = Query(..., description="第一个日期"),
    date2: str = Query(..., description="第二个日期"),
    top_n: int = Query(30, ge=10, le=100),
):
    """
    对比两个日期的评分排名变化
    """
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        try:
            d1 = date.fromisoformat(date1)
            d2 = date.fromisoformat(date2)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")

        # 获取两个日期的排名
        def get_ranking(d):
            result = storage.conn.execute("""
                SELECT code, name, score, rank FROM (
                    SELECT code, name, score, ROW_NUMBER() OVER (ORDER BY score DESC) as rank
                    FROM score_history WHERE snapshot_date = ?
                ) WHERE rank <= ?
            """, (d, top_n)).fetchall()
            return {r[0]: {"name": r[1], "score": r[2], "rank": r[3]} for r in result}

        ranking1 = get_ranking(d1)
        ranking2 = get_ranking(d2)

        if not ranking1 or not ranking2:
            return {"error": "No data for one or both dates"}

        # 计算排名变化
        comparison = []
        for code, data1 in ranking1.items():
            if code in ranking2:
                data2 = ranking2[code]
                comparison.append({
                    "code": code,
                    "name": data1["name"],
                    "score1": round(data1["score"], 4),
                    "score2": round(data2["score"], 4),
                    "score_change": round(data2["score"] - data1["score"], 4),
                    "rank1": data1["rank"],
                    "rank2": data2["rank"],
                    "rank_change": data1["rank"] - data2["rank"],  # 正数表示排名上升
                    "status": "both",
                })
            else:
                comparison.append({
                    "code": code,
                    "name": data1["name"],
                    "score1": round(data1["score"], 4),
                    "score2": None,
                    "score_change": None,
                    "rank1": data1["rank"],
                    "rank2": None,
                    "rank_change": None,
                    "status": "dropped",
                })

        # 新进入排名的
        for code, data2 in ranking2.items():
            if code not in ranking1:
                comparison.append({
                    "code": code,
                    "name": data2["name"],
                    "score1": None,
                    "score2": round(data2["score"], 4),
                    "score_change": None,
                    "rank1": None,
                    "rank2": data2["rank"],
                    "rank_change": None,
                    "status": "new",
                })

        # 排序
        comparison.sort(key=lambda x: x["rank1"] or 999)

        return {
            "date1": date1,
            "date2": date2,
            "top_n": top_n,
            "comparison": comparison,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 松岗七维打分API (V3.0)
# ═══════════════════════════════════════════════════════════════════════════════

from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy


@router.get("/songgang-ranking")
async def get_songgang_ranking(
    request: Request,
    top_n: int = Query(60, ge=10, le=200, description="返回前N名"),
    aum_level: str = Query("small", description="AUM规模等级: small/medium/large"),
    market_env: str = Query("neutral", description="市场环境: bull/bear/neutral"),
):
    """
    松岗七维打分排名 - V3.0

    七维评分体系:
    - 正股七维（55分）：短期动量、板块情绪、技术面、筹码面、波动率、消息面、基本面
    - 转债自身（45分）：估值指标、条款价值、流动性、信用评分

    包含一票否决制和缓冲带机制
    """
    cache_key = _get_cache_key("songgang_ranking", top_n=top_n, aum=aum_level, market=market_env)
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"total": 0, "items": [], "vetoed": [], "buffer_status": []}

        # 转换为DataFrame
        rows = []
        for b in bonds:
            rows.append({
                "code": b.code,
                "name": b.name,
                "price": b.price,
                "premium_ratio": b.premium_ratio,
                "volume": b.volume or 0,
                "dual_low": b.dual_low,
                "change_pct": b.change_pct or 0,
                "ytm": b.ytm or 0,
                "remaining_years": b.remaining_years or 0,
                "conversion_value": b.conversion_value or 0,
                "stock_price": b.stock_price or 0,
                "stock_change_pct": b.stock_change_pct or 0,
                "forced_call_days": b.forced_call_days or 0,
                "date": datetime.now().date(),
            })

        if not rows:
            return {"total": 0, "items": [], "vetoed": [], "buffer_status": []}

        df = pd.DataFrame(rows)

        # 创建策略实例
        strategy = SonggangSevenDimensionStrategy(
            hold_count=top_n,
            aum_level=aum_level,
            market_env=market_env,
        )
        strategy.on_init(df)

        # 执行打分
        scores_list = []
        vetoed_list = []

        for i, row in df.iterrows():
            # 一票否决检查
            veto = strategy._check_veto(row)
            if not veto.passed:
                vetoed_list.append({
                    "code": row['code'],
                    "name": row.get('name', ''),
                    "reasons": veto.reasons,
                    "credit_score": round(veto.score, 1),
                })
                continue

            # 计算七维评分
            score_dict = strategy._calc_total_score(row, df)
            score_dict['code'] = row['code']
            score_dict['name'] = row.get('name', '')
            score_dict['price'] = row['price']
            score_dict['premium_ratio'] = row['premium_ratio']
            score_dict['dual_low'] = row['dual_low']
            score_dict['volume'] = row['volume']
            score_dict['change_pct'] = row['change_pct']
            score_dict['ytm'] = row['ytm']
            score_dict['remaining_years'] = row['remaining_years']
            scores_list.append(score_dict)

        if not scores_list:
            return {
                "total": 0,
                "items": [],
                "vetoed": vetoed_list,
                "buffer_status": [],
                "market_env": market_env,
            }

        scores_df = pd.DataFrame(scores_list)
        scores_df = scores_df.sort_values('total', ascending=False).reset_index(drop=True)

        # 更新缓冲带状态
        buffer_status_list = []
        for rank, (_, row) in enumerate(scores_df.iterrows(), 1):
            code = row['code']
            status = strategy._update_buffer_status(code, rank)
            if status.in_buffer or rank <= top_n + 5:
                buffer_status_list.append({
                    "code": code,
                    "name": row['name'],
                    "rank": rank,
                    "score": row['total'],
                    "in_buffer": status.in_buffer,
                    "days_in_buffer": status.days_in_buffer,
                    "days_above_60": status.days_above_60,
                    "days_below_60": status.days_below_60,
                })

        # 取前N名
        top_df = scores_df.head(top_n)

        items = []
        for idx, row in top_df.iterrows():
            items.append({
                "rank": idx + 1,
                "code": row['code'],
                "name": row['name'],
                "price": round(row['price'], 3),
                "premium_ratio": round(row['premium_ratio'], 2),
                "dual_low": round(row['dual_low'], 2),
                "volume": round(row['volume'], 2),
                "change_pct": round(row['change_pct'], 2),
                "ytm": round(row['ytm'], 2) if row['ytm'] else None,
                "remaining_years": round(row['remaining_years'], 2) if row['remaining_years'] else None,
                "total_score": round(row['total'], 2),
                "stock_score": round(row['stock_score'], 2),
                "bond_score": round(row['bond_score'], 2),
                "score_details": row['stock_details'],
                "bond_details": row['bond_details'],
            })

        result = {
            "total": len(scores_df),
            "returned": len(items),
            "market_env": market_env,
            "aum_level": aum_level,
            "params": {
                "top_n": top_n,
                "buffer_size": 5,
                "buffer_days": 3,
            },
            "items": items,
            "vetoed": vetoed_list[:20],  # 只返回前20个被否决的
            "vetoed_count": len(vetoed_list),
            "buffer_status": buffer_status_list[:20],
            "cached": False,
        }

        _set_cache(cache_key, result)
        return result

    except Exception as e:
        logger.exception("Songgang ranking error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/songgang-ranking/{code}")
async def get_songgang_single_score(
    request: Request,
    code: str,
    aum_level: str = Query("small", description="AUM规模等级"),
):
    """
    获取单只转债的松岗七维详细评分
    """
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            raise HTTPException(status_code=404, detail="No data available")

        # 找到目标转债
        target_bond = None
        for b in bonds:
            if b.code == code:
                target_bond = b
                break

        if not target_bond:
            raise HTTPException(status_code=404, detail=f"Bond {code} not found")

        # 构建DataFrame
        rows = []
        for b in bonds:
            rows.append({
                "code": b.code,
                "name": b.name,
                "price": b.price,
                "premium_ratio": b.premium_ratio,
                "volume": b.volume or 0,
                "dual_low": b.dual_low,
                "change_pct": b.change_pct or 0,
                "ytm": b.ytm or 0,
                "remaining_years": b.remaining_years or 0,
                "conversion_value": b.conversion_value or 0,
                "stock_price": b.stock_price or 0,
                "stock_change_pct": b.stock_change_pct or 0,
                "forced_call_days": b.forced_call_days or 0,
                "date": datetime.now().date(),
            })

        df = pd.DataFrame(rows)
        strategy = SonggangSevenDimensionStrategy(aum_level=aum_level)
        strategy.on_init(df)

        target_row = df[df['code'] == code].iloc[0]

        # 一票否决检查
        veto = strategy._check_veto(target_row)

        # 计算详细评分
        score_dict = strategy._calc_total_score(target_row, df)

        result = {
            "code": code,
            "name": target_row['name'],
            "price": target_row['price'],
            "premium_ratio": target_row['premium_ratio'],
            "dual_low": target_row['dual_low'],
            "volume": target_row['volume'],
            "ytm": target_row['ytm'],
            "remaining_years": target_row['remaining_years'],
            "veto_check": {
                "passed": veto.passed,
                "reasons": veto.reasons,
                "credit_score": round(veto.score, 1),
            },
            "total_score": score_dict['total'],
            "stock_score": score_dict['stock_score'],
            "bond_score": score_dict['bond_score'],
            "stock_details": score_dict['stock_details'],
            "bond_details": score_dict['bond_details'],
            "weights": {
                "stock_weights": strategy.STOCK_WEIGHTS,
                "bond_weights": strategy.BOND_WEIGHTS,
            },
        }

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/songgang-ranking/veto/{code}")
async def check_songgang_veto(
    request: Request,
    code: str,
):
    """
    检查单只转债的一票否决状态
    """
    try:
        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            raise HTTPException(status_code=404, detail="No data available")

        target_bond = None
        for b in bonds:
            if b.code == code:
                target_bond = b
                break

        if not target_bond:
            raise HTTPException(status_code=404, detail=f"Bond {code} not found")

        rows = []
        for b in bonds:
            rows.append({
                "code": b.code,
                "name": b.name,
                "price": b.price,
                "premium_ratio": b.premium_ratio,
                "volume": b.volume or 0,
                "dual_low": b.dual_low,
                "change_pct": b.change_pct or 0,
                "ytm": b.ytm or 0,
                "remaining_years": b.remaining_years or 0,
                "forced_call_days": b.forced_call_days or 0,
            })

        df = pd.DataFrame(rows)
        strategy = SonggangSevenDimensionStrategy()
        target_row = df[df['code'] == code].iloc[0]

        veto = strategy._check_veto(target_row)

        return {
            "code": code,
            "name": target_row['name'],
            "passed": veto.passed,
            "reasons": veto.reasons,
            "credit_score": round(veto.score, 1),
            "checks": {
                "premium_ratio": {
                    "value": target_row['premium_ratio'],
                    "threshold": 100,
                    "passed": target_row['premium_ratio'] <= 100,
                },
                "remaining_months": {
                    "value": target_row['remaining_years'] * 12,
                    "threshold": 6,
                    "passed": target_row['remaining_years'] * 12 >= 6,
                },
                "forced_call": {
                    "value": target_row['forced_call_days'],
                    "passed": target_row['forced_call_days'] == 0 or target_row['forced_call_days'] >= 15,
                },
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 组合预警API ──

class ComboCondition(BaseModel):
    field: str  # score, price, dual_low, premium, volume
    operator: str  # gt, lt, gte, lte, eq
    value: float

class ComboAlertRequest(BaseModel):
    name: str
    description: str = ""
    conditions: list[ComboCondition]
    logic: str = "AND"  # AND, OR
    enabled: bool = True


@router.post("/combo-alerts")
async def add_combo_alert(req: ComboAlertRequest, request: Request):
    """添加组合预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        alert_id = storage.add_combo_alert({
            'name': req.name,
            'description': req.description,
            'conditions': [c.model_dump() for c in req.conditions],
            'logic': req.logic,
            'enabled': req.enabled,
        })
        return {"status": "ok", "id": alert_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/combo-alerts")
async def get_combo_alerts(request: Request, enabled_only: bool = False):
    """获取所有组合预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        alerts = storage.get_combo_alerts(enabled_only)
        return {"alerts": alerts}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/combo-alerts/{alert_id}")
async def remove_combo_alert(alert_id: int, request: Request):
    """删除组合预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        storage.remove_combo_alert(alert_id)
        return {"status": "ok"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/combo-alerts/check")
async def check_combo_alerts(request: Request):
    """检查组合预警"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        engine = request.app.state.engine
        bonds = await engine.get_all_quotes()

        if not bonds:
            return {"triggered": []}

        # 获取所有启用的组合预警
        alerts = storage.get_combo_alerts(enabled_only=True)

        triggered = []
        for alert in alerts:
            conditions = alert.get('conditions', [])
            logic = alert.get('logic', 'AND')

            # 对所有转债检查条件
            matching_bonds = []
            for bond in bonds:
                results = []
                for cond in conditions:
                    field = cond['field']
                    op = cond['operator']
                    val = cond['value']

                    # 获取字段值
                    if field == 'price':
                        current = bond.price
                    elif field == 'dual_low':
                        current = bond.dual_low
                    elif field == 'premium':
                        current = bond.premium_ratio
                    elif field == 'volume':
                        current = bond.volume or 0
                    else:
                        continue

                    # 检查条件
                    if op == 'gt':
                        results.append(current > val)
                    elif op == 'lt':
                        results.append(current < val)
                    elif op == 'gte':
                        results.append(current >= val)
                    elif op == 'lte':
                        results.append(current <= val)
                    elif op == 'eq':
                        results.append(abs(current - val) < 0.01)

                # 根据逻辑判断是否满足
                if logic == 'AND':
                    if all(results):
                        matching_bonds.append(bond)
                else:  # OR
                    if any(results):
                        matching_bonds.append(bond)

            if matching_bonds:
                triggered.append({
                    "alert": alert,
                    "matching_count": len(matching_bonds),
                    "matching_bonds": [{"code": b.code, "name": b.name} for b in matching_bonds[:10]],
                    "triggered_at": datetime.now().isoformat(),
                })
                storage.update_combo_alert_triggered(alert['id'])

        return {"triggered": triggered, "total_alerts": len(alerts)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 预警历史API ──

@router.get("/alert-history")
async def get_alert_history(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    code: str = Query("", description="转债代码（可选）"),
):
    """获取预警历史记录"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        history = storage.get_alert_history(days, code)
        return {"history": history, "total": len(history)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alert-history/{history_id}/acknowledge")
async def acknowledge_alert(history_id: int, request: Request):
    """确认预警记录"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        storage.acknowledge_alert(history_id)
        return {"status": "ok"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 数据清理API ──

@router.post("/cleanup")
async def cleanup_data(
    request: Request,
    keep_days: int = Query(90, ge=30, le=365),
):
    """执行数据清理"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        results = storage.cleanup_all(keep_days)
        return {"status": "ok", "results": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 缓存管理API ──

@router.get("/cache/stats")
async def get_cache_stats():
    """获取缓存统计信息"""
    return _get_cache_stats()


@router.post("/cache/clear")
async def clear_cache():
    """清空缓存"""
    count = _clear_cache()
    return {"status": "ok", "cleared_entries": count}


@router.get("/health")
async def health_check(request: Request):
    """健康检查"""
    storage = getattr(request.app.state, "storage", None)
    engine = getattr(request.app.state, "engine", None)

    storage_ok = False
    if storage:
        try:
            storage.conn.execute("SELECT 1")
            storage_ok = True
        except Exception:
            pass

    cache_stats = _get_cache_stats()

    return {
        "status": "ok",
        "storage_ok": storage_ok,
        "market_running": engine.is_running if engine else False,
        "cache": {
            "entries": cache_stats["total_entries"],
            "valid": cache_stats["valid_entries"],
        },
    }


# ── 策略对比API ──

class StrategyConfig(BaseModel):
    name: str
    weights: dict[str, float]  # dual_low, premium, momentum, volume, price

class StrategyCompareRequest(BaseModel):
    strategies: list[StrategyConfig]
    start_date: str
    end_date: str
    top_n: int = 20
    hold_days: int = 5


@router.post("/strategy-compare")
async def compare_strategies(req: StrategyCompareRequest, request: Request):
    """
    对比多个评分策略的回测表现
    """
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        try:
            start = date.fromisoformat(req.start_date)
            end = date.fromisoformat(req.end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")

        # 获取日期范围内的评分数据
        result = storage.conn.execute("""
            SELECT DISTINCT snapshot_date FROM score_history
            WHERE snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY snapshot_date
        """, (start, end)).fetchall()

        if not result:
            return {"error": "No score history data in the specified range"}

        dates = [r[0] for r in result]

        # 对每个策略进行回测
        strategy_results = []
        for strategy in req.strategies:
            weights = strategy.weights
            results = []

            for i, snap_date in enumerate(dates[:-req.hold_days]):
                # 获取当日数据
                day_data = storage.conn.execute("""
                    SELECT code, name, score_dual_low, score_premium, score_momentum,
                           score_volume, score_price, price
                    FROM score_history WHERE snapshot_date = ?
                """, (snap_date,)).fetchall()

                if not day_data:
                    continue

                # 使用策略权重重新计算评分
                scored_data = []
                for row in day_data:
                    code, name, s_dual_low, s_premium, s_momentum, s_volume, s_price, price = row
                    score = (
                        (s_dual_low or 0) * weights.get('dual_low', 0.4) +
                        (s_premium or 0) * weights.get('premium', 0.2) +
                        (s_momentum or 0) * weights.get('momentum', 0.2) +
                        (s_volume or 0) * weights.get('volume', 0.1) +
                        (s_price or 0) * weights.get('price', 0.1)
                    )
                    scored_data.append((code, name, score, price))

                # 排序取Top N
                scored_data.sort(key=lambda x: x[2], reverse=True)
                top_items = scored_data[:req.top_n]

                if not top_items:
                    continue

                # 获取持有期末价格
                end_idx = min(i + req.hold_days, len(dates) - 1)
                end_date_val = dates[end_idx]

                end_prices = storage.conn.execute("""
                    SELECT code, price FROM score_history
                    WHERE snapshot_date = ? AND code IN ({})
                """.format(",".join(["?" for _ in top_items])), [end_date_val] + [t[0] for t in top_items]).fetchall()

                end_price_map = {r[0]: r[1] for r in end_prices}

                # 计算收益
                returns = []
                for code, name, score, start_price in top_items:
                    end_price = end_price_map.get(code)
                    if end_price and start_price and start_price > 0:
                        ret = (end_price - start_price) / start_price * 100
                        returns.append(ret)

                if returns:
                    avg_return = sum(returns) / len(returns)
                    win_rate = len([r for r in returns if r > 0]) / len(returns) * 100
                    results.append({
                        "date": str(snap_date),
                        "avg_return": avg_return,
                        "win_rate": win_rate,
                    })

            # 计算策略汇总
            if results:
                total_avg_return = sum(r["avg_return"] for r in results) / len(results)
                total_win_rate = sum(r["win_rate"] for r in results) / len(results)
                # 计算累计收益
                cumulative_return = sum(r["avg_return"] for r in results)

                strategy_results.append({
                    "name": strategy.name,
                    "weights": weights,
                    "total_periods": len(results),
                    "avg_return_pct": round(total_avg_return, 2),
                    "avg_win_rate": round(total_win_rate, 1),
                    "cumulative_return": round(cumulative_return, 2),
                    "details": results[:10],  # 只返回前10期详情
                })

        # 排序策略结果
        strategy_results.sort(key=lambda x: x["cumulative_return"], reverse=True)

        return {
            "strategies": strategy_results,
            "period": {
                "start": req.start_date,
                "end": req.end_date,
                "hold_days": req.hold_days,
                "top_n": req.top_n,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 风险指标分析API ──

@router.get("/risk-metrics")
async def get_risk_metrics(
    request: Request,
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    top_n: int = Query(20, ge=5, le=100),
    hold_days: int = Query(5, ge=1, le=30),
):
    """
    计算回测期间的风险指标：最大回撤、夏普比率、波动率等
    """
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")

        # 获取日期范围内的评分数据
        result = storage.conn.execute("""
            SELECT DISTINCT snapshot_date FROM score_history
            WHERE snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY snapshot_date
        """, (start, end)).fetchall()

        if not result:
            return {"error": "No score history data in the specified range"}

        dates = [r[0] for r in result]

        # 计算每期收益
        returns = []
        cumulative_returns = [0]  # 累计收益序列
        current_cumulative = 0

        for i, snap_date in enumerate(dates[:-hold_days]):
            top_scores = storage.conn.execute("""
                SELECT code, name, score, price FROM score_history
                WHERE snapshot_date = ?
                ORDER BY score DESC
                LIMIT ?
            """, (snap_date, top_n)).fetchall()

            if not top_scores:
                continue

            end_idx = min(i + hold_days, len(dates) - 1)
            end_date_val = dates[end_idx]

            end_prices = storage.conn.execute("""
                SELECT code, price FROM score_history
                WHERE snapshot_date = ? AND code IN ({})
            """.format(",".join(["?" for _ in top_scores])), [end_date_val] + [t[0] for t in top_scores]).fetchall()

            end_price_map = {r[0]: r[1] for r in end_prices}

            period_returns = []
            for code, name, score, start_price in top_scores:
                end_price = end_price_map.get(code)
                if end_price and start_price and start_price > 0:
                    ret = (end_price - start_price) / start_price * 100
                    period_returns.append(ret)

            if period_returns:
                avg_ret = sum(period_returns) / len(period_returns)
                returns.append(avg_ret)
                current_cumulative += avg_ret
                cumulative_returns.append(current_cumulative)

        if not returns:
            return {"error": "Insufficient data for risk metrics"}

        # 计算风险指标
        import statistics

        # 最大回撤
        peak = cumulative_returns[0]
        max_drawdown = 0
        for value in cumulative_returns:
            if value > peak:
                peak = value
            drawdown = peak - value
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # 年化收益率（假设每期hold_days天）
        total_days = len(returns) * hold_days
        annualized_return = (cumulative_returns[-1] / total_days * 252) if total_days > 0 else 0

        # 波动率
        if len(returns) > 1:
            volatility = statistics.stdev(returns)
            annualized_volatility = volatility * (252 / hold_days) ** 0.5
        else:
            volatility = 0
            annualized_volatility = 0

        # 夏普比率（假设无风险利率为3%）
        risk_free_rate = 3.0
        if annualized_volatility > 0:
            sharpe_ratio = (annualized_return - risk_free_rate) / annualized_volatility
        else:
            sharpe_ratio = 0

        # 卡玛比率
        if max_drawdown > 0:
            calmar_ratio = annualized_return / max_drawdown
        else:
            calmar_ratio = 0

        # 胜率
        winning_periods = len([r for r in returns if r > 0])
        win_rate = winning_periods / len(returns) * 100 if returns else 0

        # 盈亏比
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        return {
            "period": {
                "start": start_date,
                "end": end_date,
                "total_periods": len(returns),
                "total_days": total_days,
            },
            "return_metrics": {
                "total_return": round(cumulative_returns[-1], 2),
                "annualized_return": round(annualized_return, 2),
                "avg_period_return": round(sum(returns) / len(returns), 2),
            },
            "risk_metrics": {
                "max_drawdown": round(max_drawdown, 2),
                "volatility": round(volatility, 2),
                "annualized_volatility": round(annualized_volatility, 2),
            },
            "risk_adjusted_metrics": {
                "sharpe_ratio": round(sharpe_ratio, 2),
                "calmar_ratio": round(calmar_ratio, 2),
            },
            "trade_metrics": {
                "win_rate": round(win_rate, 1),
                "profit_loss_ratio": round(profit_loss_ratio, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
            },
            "cumulative_returns": cumulative_returns,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 通知渠道配置API ──

class NotificationChannel(BaseModel):
    channel_type: str  # email, webhook, dingtalk, wechat
    name: str
    config: dict  # 渠道特定配置
    enabled: bool = True


@router.post("/notification-channels")
async def add_notification_channel(req: NotificationChannel, request: Request):
    """添加通知渠道"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        # 存储通知渠道配置
        with storage._write_lock:
            storage.conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_channels (
                    id INTEGER PRIMARY KEY,
                    channel_type VARCHAR,
                    name VARCHAR,
                    config VARCHAR,
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP
                )
            """)
            storage.conn.execute("""
                INSERT INTO notification_channels (channel_type, name, config, enabled, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (req.channel_type, req.name, str(req.config), req.enabled, datetime.now()))
            channel_id = storage.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        return {"status": "ok", "id": channel_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notification-channels")
async def get_notification_channels(request: Request):
    """获取所有通知渠道"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        result = storage.conn.execute("SELECT * FROM notification_channels WHERE enabled = TRUE").fetchall()
        channels = []
        for row in result:
            channels.append({
                "id": row[0],
                "channel_type": row[1],
                "name": row[2],
                "config": eval(row[3]) if row[3] else {},
                "enabled": row[4],
                "created_at": str(row[5]),
            })

        return {"channels": channels}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/notification-channels/{channel_id}")
async def remove_notification_channel(channel_id: int, request: Request):
    """删除通知渠道"""
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        storage.conn.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))
        return {"status": "ok"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 评分趋势预测API ──

@router.get("/score-prediction/{code}")
async def predict_score_trend(
    code: str,
    request: Request,
    days: int = Query(30, ge=7, le=90),
):
    """
    预测单个转债的评分趋势
    使用简单的线性回归进行预测
    """
    try:
        storage = getattr(request.app.state, "storage", None)
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not available")

        # 获取历史评分数据
        result = storage.conn.execute("""
            SELECT snapshot_date, score, score_dual_low, score_premium
            FROM score_history
            WHERE code = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (code, days)).fetchall()

        if len(result) < 7:
            return {"error": "Insufficient historical data for prediction"}

        # 反转使时间顺序正确
        result = list(reversed(result))

        # 简单线性回归预测
        dates_numeric = list(range(len(result)))
        scores = [r[1] for r in result]

        # 计算线性回归参数
        n = len(scores)
        sum_x = sum(dates_numeric)
        sum_y = sum(scores)
        sum_xy = sum(x * y for x, y in zip(dates_numeric, scores))
        sum_xx = sum(x * x for x in dates_numeric)

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x) if n * sum_xx != sum_x * sum_x else 0
        intercept = (sum_y - slope * sum_x) / n

        # 预测未来5天
        predictions = []
        for i in range(1, 6):
            pred_score = intercept + slope * (len(result) + i - 1)
            pred_score = max(0, min(1, pred_score))  # 限制在0-1范围内
            predictions.append({
                "day": i,
                "predicted_score": round(pred_score, 4),
            })

        # 计算趋势方向
        trend = "上升" if slope > 0.001 else "下降" if slope < -0.001 else "平稳"

        # 计算置信度（基于历史波动）
        if len(scores) > 1:
            import statistics
            volatility = statistics.stdev(scores)
            confidence = max(0, min(100, 100 - volatility * 200))
        else:
            confidence = 50

        # 当前状态
        current_score = scores[-1] if scores else 0
        score_5d_ago = scores[-5] if len(scores) >= 5 else scores[0]
        score_10d_ago = scores[-10] if len(scores) >= 10 else scores[0]

        return {
            "code": code,
            "current_score": round(current_score, 4),
            "trend": trend,
            "slope": round(slope, 6),
            "confidence": round(confidence, 1),
            "predictions": predictions,
            "change_5d": round(current_score - score_5d_ago, 4),
            "change_10d": round(current_score - score_10d_ago, 4),
            "volatility": round(volatility if len(scores) > 1 else 0, 4),
            "historical_data": [
                {"date": str(r[0]), "score": round(r[1], 4)}
                for r in result[-14:]  # 返回最近14天数据
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
