from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, date, timedelta
from collections import defaultdict
import threading
import random
from pathlib import Path
import statistics
from app.utils.data_source import DataSource

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
#  Module-level helpers — shared by all aggregation endpoints
# ═══════════════════════════════════════════════════════════════════════════════

def _row_to_dict(r: dict) -> dict:
    """将数据库行情行转换为前端行情字典"""
    return {
        "code": r.get("code", ""),
        "name": r.get("name", ""),
        "stock_code": r.get("stock_code", ""),
        "stock_name": r.get("stock_name", ""),
        "price": float(r.get("price")) if r.get("price") is not None else None,
        "change": float(r.get("change")) if r.get("change") is not None else None,
        "change_pct": float(r.get("change_pct")) if r.get("change_pct") is not None else None,
        "volume": float(r.get("volume")) if r.get("volume") is not None else None,
        "amount": float(r.get("amount")) if r.get("amount") is not None else None,
        "ytm": float(r.get("ytm")) if r.get("ytm") is not None else None,
        "premium": float(r.get("premium")) if r.get("premium") is not None else None,
        "bond_value": float(r.get("bond_value")) if r.get("bond_value") is not None else None,
        "option_value": float(r.get("option_value")) if r.get("option_value") is not None else None,
        "total_value": float(r.get("total_value")) if r.get("total_value") is not None else None,
        "implied_volatility": float(r.get("implied_volatility")) if r.get("implied_volatility") is not None else None,
        "stock_price": float(r.get("stock_price")) if r.get("stock_price") is not None else None,
        "stock_change_pct": float(r.get("stock_change_pct")) if r.get("stock_change_pct") is not None else None,
        "pe": float(r.get("pe")) if r.get("pe") is not None else None,
        "pb": float(r.get("pb")) if r.get("pb") is not None else None,
        "debt_ratio": float(r.get("debt_ratio")) if r.get("debt_ratio") is not None else None,
        "roe": float(r.get("roe")) if r.get("roe") is not None else None,
        "revenue_growth": float(r.get("revenue_growth")) if r.get("revenue_growth") is not None else None,
        "profit_growth": float(r.get("profit_growth")) if r.get("profit_growth") is not None else None,
        "industry": r.get("industry", ""),
        "market_cap": float(r.get("market_cap")) if r.get("market_cap") is not None else None,
        "circulating_cap": float(r.get("circulating_cap")) if r.get("circulating_cap") is not None else None,
        "turnover": float(r.get("turnover")) if r.get("turnover") is not None else None,
        "momentum_20": float(r.get("momentum_20")) if r.get("momentum_20") is not None else None,
        "momentum_60": float(r.get("momentum_60")) if r.get("momentum_60") is not None else None,
        "rsi": float(r.get("rsi")) if r.get("rsi") is not None else None,
        "forced_call_days": int(r.get("forced_call_days") or 0),
        "is_called": bool(r.get("is_called") or False),
        "call_status": str(r.get("call_status", "") or ""),
        "redemption_trigger": bool(r.get("redemption_trigger") or False),
        "has_major_sell": bool(r.get("has_major_sell") or False),
        "unlock_date": str(r.get("unlock_date", "")) if r.get("unlock_date") else "",
        "unlock_ratio": float(r.get("unlock_ratio")) if r.get("unlock_ratio") is not None else None,
        "north_net": float(r.get("north_net")) if r.get("north_net") is not None else None,
        "north_pct": float(r.get("north_pct")) if r.get("north_pct") is not None else None,
        "block_trade_count": int(r.get("block_trade_count") or 0),
        "block_trade_amount": float(r.get("block_trade_amount")) if r.get("block_trade_amount") is not None else None,
        "block_buy_pct": float(r.get("block_buy_pct")) if r.get("block_buy_pct") is not None else None,
        "concentration": float(r.get("concentration")) if r.get("concentration") is not None else None,
        "holder_count": int(r.get("holder_count") or 0),
        "holder_change_pct": float(r.get("holder_change_pct")) if r.get("holder_change_pct") is not None else None,
        "momentum_score": float(r.get("momentum_score")) if r.get("momentum_score") is not None else None,
        "valuation_score": float(r.get("valuation_score")) if r.get("valuation_score") is not None else None,
        "quality_score": float(r.get("quality_score")) if r.get("quality_score") is not None else None,
        "debt_score": float(r.get("debt_score")) if r.get("debt_score") is not None else None,
        "liquidity_score": float(r.get("liquidity_score")) if r.get("liquidity_score") is not None else None,
        "technical_score": float(r.get("technical_score")) if r.get("technical_score") is not None else None,
        "sentiment_score": float(r.get("sentiment_score")) if r.get("sentiment_score") is not None else None,
        "total_score": float(r.get("total_score")) if r.get("total_score") is not None else None,
        "timestamp": str(r.get("timestamp", "")),
    }


def _val(obj, attr: str, default=0):
    """Unified attribute accessor for both Pydantic models and dicts.
    Returns default if attribute is None or missing."""
    if hasattr(obj, attr):
        v = getattr(obj, attr, default)
        return v if v is not None else default
    if isinstance(obj, dict):
        v = obj.get(attr, default)
        return v if v is not None else default
    return default


def _get_industry(q) -> str:
    """Extract industry from a quote object/dict, defaulting to '其他'."""
    if hasattr(q, "industry"):
        return getattr(q, "industry", None) or "其他"
    if isinstance(q, dict):
        return q.get("industry") or "其他"
    return "其他"


def _safe_avg(items: list, attr: str, positive_only: bool = False, nonzero_only: bool = False) -> float:
    """Compute average of an attribute across items, skipping None values.
    If positive_only, also skip values <= 0 (for PE/PB where negative = N/A).
    If nonzero_only, also skip values == 0 (for YTM where 0 = no data).
    Returns NaN if all values are missing."""
    vals = []
    for q in items:
        v = _val(q, attr, None)
        if v is None or (not isinstance(v, (int, float))):
            continue
        if positive_only and v <= 0:
            continue
        if nonzero_only and v == 0:
            continue
        vals.append(v)
    return sum(vals) / len(vals) if vals else float('nan')


def _safe_sum(items: list, attr: str) -> float:
    """Sum an attribute across items, treating None as 0."""
    return sum((_val(q, attr, 0) or 0) for q in items)


def _count_valid(items: list, attr: str) -> int:
    """Count items where attribute is not None."""
    return sum(1 for q in items if _val(q, attr, None) is not None)


def _count_positive(items: list, attr: str) -> int:
    """Count items where attribute > 0."""
    return sum(1 for q in items if (_val(q, attr, 0) or 0) > 0)


def _count_negative(items: list, attr: str) -> int:
    """Count items where attribute < 0."""
    return sum(1 for q in items if (_val(q, attr, 0) or 0) < 0)


def _momentum_dispersion(items: list, attr: str = "momentum_20d") -> float:
    """Compute stdev of momentum values within a group. Returns 0 if < 2 values."""
    vals = [_val(q, attr, 0) for q in items if _val(q, attr, None) is not None]
    return round(statistics.stdev(vals), 2) if len(vals) >= 2 else 0.0


def _filter_fields(row: dict, fields: set[str] | None) -> dict:
    """If fields is None, return row as-is. Otherwise return only requested keys."""
    if fields is None:
        return row
    return {k: v for k, v in row.items() if k in fields}


# ── All possible fields for each endpoint (used by ?fields= query param) ──

_INDUSTRIES_ALL_FIELDS = {
    "industry", "bond_count",
    "avg_change_pct", "avg_stock_change_pct",
    "avg_premium_ratio", "avg_dual_low", "avg_ytm",
    "avg_roe", "avg_pe", "avg_pb",
    "avg_gpm", "avg_debt_ratio", "avg_turnover_rate", "avg_cagr", "avg_pledge_ratio",
    "avg_momentum_5d", "avg_momentum_10d", "avg_momentum_20d", "avg_momentum_60d",
    "momentum_dispersion",
    "net_capital_flow", "net_super_flow", "net_big_flow",
    "avg_iv", "total_volume", "up_count", "down_count",
}

_CONCEPTS_ALL_FIELDS = _INDUSTRIES_ALL_FIELDS | {"concept", "top_bonds"}  - {"industry"}

_STOCK_INDUSTRIES_ALL_FIELDS = {
    "industry", "stock_count",
    "avg_stock_change_pct", "avg_stock_price",
    "avg_roe", "avg_pe", "avg_pb",
    "avg_gpm", "avg_debt_ratio", "avg_turnover_rate", "avg_cagr", "avg_pledge_ratio",
    "avg_momentum_5d", "avg_momentum_10d", "avg_momentum_20d", "avg_momentum_60d",
    "momentum_dispersion",
    "net_capital_flow", "net_capital_flow_pct", "net_super_flow", "net_big_flow",
    "avg_iv", "total_volume", "up_count", "down_count", "stocks",
}


# ════════════════════════════════════════════════════════════════════════════
#  Industry layout recommendations (短期≤1周 / 中期2周 / 长期1月)
#  纯函数, 无外部依赖; 复用 /stock-industries 已聚合好的行业 dict
# ════════════════════════════════════════════════════════════════════════════

# horizon -> (核心动量权重, 各项权重, 录用阈值)
_HORIZON_WEIGHTS = {
    "short_term": {  # ≤1周: 动量为王 + 资金 + 活跃度
        "momentum": 0.60, "flow": 0.25, "quality": 0.00, "valuation": 0.00,
        "trend_confirm": 0.00, "long_trend": 0.00, "turnover": 0.15,
        "threshold": 55,
    },
    "mid_term": {  # 2周: 10日动量为主 + 20日趋势确认 + 资金 + 质地
        "momentum": 0.50, "flow": 0.20, "quality": 0.10, "valuation": 0.00,
        "trend_confirm": 0.20, "long_trend": 0.00, "turnover": 0.00,
        "threshold": 50,
    },
    "long_term": {  # 1月: 20日动量 + 60日长趋势 + ROE + 毛利率 + 估值
        "momentum": 0.40, "flow": 0.00, "quality": 0.20, "valuation": 0.05,
        "trend_confirm": 0.00, "long_trend": 0.25, "gpm": 0.10,
        "threshold": 45,
    },
}

# 每档周期对应的核心动量字段
_HORIZON_MOMENTUM_FIELD = {
    "short_term": "avg_momentum_5d",
    "mid_term": "avg_momentum_10d",
    "long_term": "avg_momentum_20d",
}


def _safe_num(v, default: float = 0.0) -> float:
    """数字兜底: None/NaN/非数 -> default"""
    try:
        if v is None:
            return default
        f = float(v)
        if f != f:  # NaN check
            return default
        return f
    except (TypeError, ValueError):
        return default


def _compute_horizon_score(ind: dict, horizon: str, custom_weights: dict | None = None) -> float:
    """计算单行业在指定周期的综合评分 (0-100).
    ind: /stock-industries 返回的单个行业 dict
    horizon: short_term | mid_term | long_term
    custom_weights: 可选的覆盖权重 (只覆盖传入的 key)
    """
    w = {**_HORIZON_WEIGHTS[horizon]}
    if custom_weights:
        w.update(custom_weights)
    mom_field = _HORIZON_MOMENTUM_FIELD[horizon]
    # 动量: -10%~+10% 映射到 0~100
    mom_score = min(100.0, max(0.0, (_safe_num(ind.get(mom_field)) + 10.0) * 5.0))
    # 资金: -5%~+5% 映射到 0~100
    flow_score = min(100.0, max(0.0, (_safe_num(ind.get("net_capital_flow_pct")) + 0.05) * 1000.0))
    # 趋势确认: 20日动量方向一致性 (-10%~+10% -> 0~100)
    trend_score = min(100.0, max(0.0, (_safe_num(ind.get("avg_momentum_20d")) + 10.0) * 5.0))
    # 长趋势: 60日动量 (-15%~+15% -> 0~100)
    long_score = min(100.0, max(0.0, (_safe_num(ind.get("avg_momentum_60d")) + 15.0) * (100.0 / 30.0)))
    # 质地: ROE+毛利率 (0~25 -> 0~100)
    quality_score = min(100.0, max(0.0, ((_safe_num(ind.get("avg_roe")) + _safe_num(ind.get("avg_gpm"))) / 5.0) * 4.0))
    # 估值: 100 - PE (PE 0~100 -> 100~0)
    valuation_score = min(100.0, max(0.0, 100.0 - _safe_num(ind.get("avg_pe"), 50.0)))
    # 毛利率单独 (0~50% -> 0~100)
    gpm_score = min(100.0, max(0.0, _safe_num(ind.get("avg_gpm")) * 2.0))
    # 活跃度: 换手率 (0~10% -> 0~100)
    turnover_score = min(100.0, max(0.0, _safe_num(ind.get("avg_turnover_rate")) * 10.0))

    score = (
        mom_score * w.get("momentum", 0)
        + flow_score * w.get("flow", 0)
        + quality_score * w.get("quality", 0)
        + valuation_score * w.get("valuation", 0)
        + trend_score * w.get("trend_confirm", 0)
        + long_score * w.get("long_trend", 0)
        + gpm_score * w.get("gpm", 0)
        + turnover_score * w.get("turnover", 0)
    )
    return round(score, 1)


def _build_reasons(ind: dict, horizon: str) -> list[str]:
    """生成中文推荐原因 (2-4 条 bullet).
    基于阈值规则, 命中信号即拼装一句话.
    """
    reasons: list[str] = []
    mom_field = _HORIZON_MOMENTUM_FIELD[horizon]
    mom_label = {"short_term": "5日", "mid_term": "10日", "long_term": "20日"}[horizon]

    m_now = _safe_num(ind.get(mom_field))
    m5 = _safe_num(ind.get("avg_momentum_5d"))
    m20 = _safe_num(ind.get("avg_momentum_20d"))
    m60 = _safe_num(ind.get("avg_momentum_60d"))
    flow_pct = _safe_num(ind.get("net_capital_flow_pct"))
    flow_abs = _safe_num(ind.get("net_capital_flow"))
    roe = _safe_num(ind.get("avg_roe"))
    gpm = _safe_num(ind.get("avg_gpm"))
    pe = _safe_num(ind.get("avg_pe"))
    disp = _safe_num(ind.get("momentum_dispersion"))
    turnover = _safe_num(ind.get("avg_turnover_rate"))

    # 1. 动量信号
    if m_now > 3.0:
        reasons.append(f"{mom_label}动量 +{m_now:.1f}%，强势上行")
    elif m_now > 0:
        reasons.append(f"{mom_label}动量 +{m_now:.1f}%，温和上行")

    # 2. 趋势加速 (短期动量 > 中期动量 > 0)
    if horizon in ("short_term", "mid_term") and m5 > m20 > 0:
        reasons.append(f"短期动量({m5:.1f}%)快于20日({m20:.1f}%)，趋势加速")
    if horizon == "long_term" and m20 > 0 and m60 > 0:
        reasons.append(f"20日({m20:.1f}%)与60日({m60:.1f}%)双周期共振向上")

    # 3. 资金信号
    if flow_pct > 0.01:
        reasons.append(f"主力资金净流入占比 +{flow_pct * 100:.2f}%")
    elif flow_abs > 0:
        yi = flow_abs / 1e8
        reasons.append(f"主力资金净流入 {yi:.2f} 亿")

    # 4. 质地信号
    if roe > 12:
        reasons.append(f"ROE {roe:.1f}%，质地优良")
    elif roe > 8:
        reasons.append(f"ROE {roe:.1f}%，盈利稳定")
    if horizon == "long_term" and gpm > 30:
        reasons.append(f"毛利率 {gpm:.1f}%，护城河较深")

    # 5. 估值信号
    if 0 < pe < 25:
        reasons.append(f"PE {pe:.1f}，估值合理")

    # 6. 风险/一致性信号
    if 0 < disp < 5:
        reasons.append(f"组内动量一致性高 (离散度 {disp:.1f})，轮动健康")
    if horizon == "short_term" and turnover > 3:
        reasons.append(f"换手率 {turnover:.1f}%，交投活跃")

    # 兜底: 若无强信号, 至少返回一句话
    if not reasons:
        reasons.append(f"综合评分靠前，{mom_label}维度相对占优")
    return reasons[:4]  # 最多 4 条


# ── 推荐结果内存缓存 (60s TTL) ──
_RECOMMEND_CACHE: dict | None = None
_RECOMMEND_CACHE_TS: float = 0.0
_RECOMMEND_CACHE_TTL: float = 60.0  # seconds

# ── 推荐准确率缓存 (60s TTL) ──
_ACCURACY_CACHE: dict | None = None
_ACCURACY_CACHE_TS: float = 0.0
_ACCURACY_CACHE_TTL: float = 60.0  # seconds
_rec_cache_lock = threading.Lock()


def _build_recommendations(industries: list[dict], top_k: int = 5, _use_cache: bool = True, horizon_weights: dict | None = None) -> dict:
    """对 /stock-industries 的 industries 列表计算三档推荐.
    返回结构: {short_term:[...], mid_term:[...], long_term:[...], generated_at}
    60s 内存缓存: 避免每次 /stock-industries 请求都重算.
    """
    global _RECOMMEND_CACHE, _RECOMMEND_CACHE_TS
    import time
    now = time.time()
    with _rec_cache_lock:
        if _use_cache and horizon_weights is None and _RECOMMEND_CACHE is not None and (now - _RECOMMEND_CACHE_TS) < _RECOMMEND_CACHE_TTL:
            return _RECOMMEND_CACHE

    now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    result: dict[str, list] = {}

    for horizon in ("short_term", "mid_term", "long_term"):
        hw = {**_HORIZON_WEIGHTS[horizon]}
        if horizon_weights and horizon in horizon_weights:
            hw.update(horizon_weights[horizon])
        min_threshold = hw.get("threshold", 45)  # 最低绝对阈值 (熊市兜底)

        # Step 1: 对所有合格行业计算评分
        all_scored = []
        for ind in industries:
            if _safe_num(ind.get("stock_count")) < 3:
                continue
            score = _compute_horizon_score(ind, horizon, custom_weights=hw)
            all_scored.append((ind, score))
        if not all_scored:
            result[horizon] = []
            continue

        # Step 2: 分位数自适应阈值 — 取评分排名前30%的行业
        all_scored.sort(key=lambda x: x[1], reverse=True)
        n = len(all_scored)
        quantile_cutoff = max(1, int(n * 0.3))
        quantile_min_score = all_scored[min(quantile_cutoff - 1, n - 1)][1]

        # Step 3: 有效阈值 = max(分位数阈值, 最低绝对阈值)
        # 牛市: 分位数阈值高 → 自然筛选; 熊市: 分位数阈值低 → 最低阈值兜底
        effective_threshold = max(quantile_min_score, min_threshold)

        scored = []
        for ind, score in all_scored:
            if score >= effective_threshold:
                scored.append({
                    "industry": ind.get("industry", ""),
                    "score": score,
                    "signal_strength": "strong" if score >= effective_threshold + 15 else "moderate",
                    "reasons": _build_reasons(ind, horizon),
                    "metrics": {
                        "momentum_5d": round(_safe_num(ind.get("avg_momentum_5d")), 2),
                        "momentum_10d": round(_safe_num(ind.get("avg_momentum_10d")), 2),
                        "momentum_20d": round(_safe_num(ind.get("avg_momentum_20d")), 2),
                        "momentum_60d": round(_safe_num(ind.get("avg_momentum_60d")), 2),
                        "net_capital_flow_pct": round(_safe_num(ind.get("net_capital_flow_pct")), 4),
                        "avg_roe": round(_safe_num(ind.get("avg_roe")), 2),
                        "avg_pe": round(_safe_num(ind.get("avg_pe")), 2),
                        "avg_gpm": round(_safe_num(ind.get("avg_gpm")), 2),
                        "stock_count": int(_safe_num(ind.get("stock_count"))),
                    },
                })
        scored.sort(key=lambda x: x["score"], reverse=True)
        result[horizon] = scored[:top_k]

    result["generated_at"] = now_iso
    if horizon_weights is None:
        with _rec_cache_lock:
            _RECOMMEND_CACHE = result
            _RECOMMEND_CACHE_TS = time.time()
        _save_rec_history(result, industries)
    return result


# ── 推荐历史记录 (JSON 文件, 每日一条快照) ──
_REC_HISTORY_DIR = Path.home() / ".lianghua" / "data_cache" / "rec_history"
_REC_HISTORY_MAX_DAYS = 90  # rolling window: delete files older than this
_REC_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _save_rec_history(recs: dict, industries: list[dict] | None = None) -> None:
    """保存当日推荐快照到 JSON 文件. 文件名: YYYY-MM-DD.json
    industries: 原始行业列表, 用于保存基线动量供回测使用.
    """
    import json as _json
    try:
        today = date.today().isoformat()
        fp = _REC_HISTORY_DIR / f"{today}.json"
        # 如果当天已保存, 跳过 (避免覆盖已有回测结果)
        if fp.exists():
            return
        data = dict(recs)
        # 保存基线动量 (供后续回测用)
        if industries:
            baseline = {}
            for ind in industries:
                name = ind.get("industry", "")
                if name:
                    baseline[name] = {
                        "momentum_5d": _safe_num(ind.get("avg_momentum_5d")),
                        "momentum_10d": _safe_num(ind.get("avg_momentum_10d")),
                        "momentum_20d": _safe_num(ind.get("avg_momentum_20d")),
                        "momentum_60d": _safe_num(ind.get("avg_momentum_60d")),
                    }
            data["_baseline"] = baseline
        with open(fp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        # Rolling window: delete history files older than _REC_HISTORY_MAX_DAYS
        cutoff = (date.today() - timedelta(days=_REC_HISTORY_MAX_DAYS)).isoformat()
        for old_fp in _REC_HISTORY_DIR.glob("*.json"):
            if old_fp.stem < cutoff:
                old_fp.unlink(missing_ok=True)
    except Exception:
        logger.debug("[Market] Failed to cleanup old rec history files")


def _load_rec_history(days: int = 30) -> list[dict]:
    """加载最近 N 天的推荐历史. 返回 [{date, short_term, mid_term, long_term}, ...]"""
    import json as _json
    result = []
    try:
        files = sorted(_REC_HISTORY_DIR.glob("*.json"), reverse=True)
        for fp in files[:days]:
            with open(fp, "r", encoding="utf-8") as f:
                data = _json.load(f)
            data["date"] = fp.stem
            result.append(data)
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
        pass
    return result


def _iso(value) -> Optional[str]:
    """将 date/datetime 序列化为 ISO 字符串;None 透传"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    return s if s else None

class Quote(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    changePercent: float
    volume: int
    timestamp: datetime

@router.get("/quotes")
async def get_quotes(request: Request, symbols: str = Query(None)):
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    symbol_list = symbols.split(",") if symbols else []

    def quote_to_dict(q) -> dict:
        return {
            "code": q.code,
            "name": getattr(q, "name", ""),
            "stock_code": getattr(q, "stock_code", ""),
            "stock_name": getattr(q, "stock_name", ""),
            "price": getattr(q, "price", 0),
            "change_pct": getattr(q, "change_pct", 0),
            "stock_price": getattr(q, "stock_price", 0),
            "stock_change_pct": getattr(q, "stock_change_pct", 0),
            "conversion_price": getattr(q, "conversion_price", 0),
            "conversion_value": getattr(q, "conversion_value", 0),
            "premium_ratio": getattr(q, "premium_ratio", 0),
            "dual_low": getattr(q, "dual_low", 0),
            "ytm": getattr(q, "ytm", 0),
            "volume": getattr(q, "volume", 0),
            "remaining_years": getattr(q, "remaining_years", 0),
            "forced_call_days": getattr(q, "forced_call_days", 0),
            "is_called": bool(getattr(q, "is_called", False)),
            "call_status": str(getattr(q, "call_status", "") or ""),
            "last_trade_date": _iso(getattr(q, "last_trade_date", None)),
            "maturity_date": _iso(getattr(q, "maturity_date", None)),
            "redemption_price": float(getattr(q, "redemption_price", 0) or 0.0),
            "rating": str(getattr(q, "rating", "") or "") or None,
            "industry": getattr(q, "industry", None),
            "concepts": getattr(q, "concepts", None) or [],
            "roe": getattr(q, "roe", None),
            "gpm": getattr(q, "gpm", None),
            "cagr": getattr(q, "cagr", None),
            "debt_ratio": getattr(q, "debt_ratio", None),
            "current_ratio": getattr(q, "current_ratio", None),
            "pe": getattr(q, "pe", None),
            "pb": getattr(q, "pb", None),
            "iv": getattr(q, "iv", None),
            "turnover_rate": getattr(q, "turnover_rate", None),
            "net_capital_flow": getattr(q, "net_capital_flow", None),
            "net_capital_flow_pct": getattr(q, "net_capital_flow_pct", None),
            "buyback_amount": getattr(q, "buyback_amount", None),
            "mgmt_buy_price": getattr(q, "mgmt_buy_price", None),
            "outstanding_scale": getattr(q, "outstanding_scale", None),
            "pledge_ratio": getattr(q, "pledge_ratio", None),
            "net_super_flow": getattr(q, "net_super_flow", None),
            "net_big_flow": getattr(q, "net_big_flow", None),
            "momentum_5d": getattr(q, "momentum_5d", None),
            "momentum_10d": getattr(q, "momentum_10d", None),
            "momentum_20d": getattr(q, "momentum_20d", None),
            "momentum_60d": getattr(q, "momentum_60d", None),
            "event_score": getattr(q, "event_score", None),
            "event_detail": getattr(q, "event_detail", None),
            "bond_value": getattr(q, "bond_value", None),
            "iv_source": getattr(q, "iv_source", None),
            "north_net": getattr(q, "north_net", None),
            "margin_balance": getattr(q, "margin_balance", None),
            "lhb_count": getattr(q, "lhb_count", None),
            "block_trade_amount": getattr(q, "block_trade_amount", None),
            "holder_num_change": getattr(q, "holder_num_change", None),
            "eps_forecast": getattr(q, "eps_forecast", None),
            "profit_yoy": getattr(q, "profit_yoy", None),
            "revenue_yoy": getattr(q, "revenue_yoy", None),
            "restricted_release_amount": getattr(q, "restricted_release_amount", None),
            "sentiment_score": getattr(q, "sentiment_score", None),
            "rating_score": getattr(q, "rating_score", None),
            "pure_bond_premium_ratio": getattr(q, "pure_bond_premium_ratio", None),
            "eps": getattr(q, "eps", None),
            "bps": getattr(q, "bps", None),
            "hv": getattr(q, "hv", None),
        }


    if engine:
        quotes = await engine.get_all_quotes()
        result = [quote_to_dict(q) for q in quotes if not symbol_list or q.code in symbol_list]
        if not symbol_list:
            return {
                "total": len(result),
                "bonds": result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "data_source": DataSource.REAL.value,
            }
        return result

    if storage:
        rows = storage.get_latest_quotes()
        result = [_row_to_dict(r) for r in rows if not symbol_list or r.get("code") in symbol_list]
        if not symbol_list:
            return {
                "total": len(result),
                "bonds": result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "data_source": DataSource.REAL.value,
            }
        return result

    if not symbol_list:
        return {"total": 0, "bonds": [], "updated_at": "", "data_source": DataSource.MISSING.value}
    return []


@router.get("/quotes/{code}")
async def get_quote_by_code(request: Request, code: str):
    """获取单个可转债的实时报价（前端 fetchQuote 使用）"""
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    def quote_to_dict(q) -> dict:
        return {
            "code": q.code,
            "name": getattr(q, "name", ""),
            "stock_code": getattr(q, "stock_code", ""),
            "stock_name": getattr(q, "stock_name", ""),
            "price": getattr(q, "price", 0),
            "change_pct": getattr(q, "change_pct", 0),
            "stock_price": getattr(q, "stock_price", 0),
            "stock_change_pct": getattr(q, "stock_change_pct", 0),
            "conversion_price": getattr(q, "conversion_price", 0),
            "conversion_value": getattr(q, "conversion_value", 0),
            "premium_ratio": getattr(q, "premium_ratio", 0),
            "dual_low": getattr(q, "dual_low", 0),
            "ytm": getattr(q, "ytm", 0),
            "volume": getattr(q, "volume", 0),
            "remaining_years": getattr(q, "remaining_years", 0),
            "forced_call_days": getattr(q, "forced_call_days", 0),
            "is_called": bool(getattr(q, "is_called", False)),
            "call_status": str(getattr(q, "call_status", "") or ""),
            "last_trade_date": _iso(getattr(q, "last_trade_date", None)),
            "maturity_date": _iso(getattr(q, "maturity_date", None)),
            "redemption_price": float(getattr(q, "redemption_price", 0) or 0.0),
            "rating": str(getattr(q, "rating", "") or "") or None,
            "industry": getattr(q, "industry", None),
            "roe": getattr(q, "roe", None),
            "gpm": getattr(q, "gpm", None),
            "cagr": getattr(q, "cagr", None),
            "debt_ratio": getattr(q, "debt_ratio", None),
            "current_ratio": getattr(q, "current_ratio", None),
            "pe": getattr(q, "pe", None),
            "pb": getattr(q, "pb", None),
            "iv": getattr(q, "iv", None),
            "turnover_rate": getattr(q, "turnover_rate", None),
            "net_capital_flow": getattr(q, "net_capital_flow", None),
            "net_capital_flow_pct": getattr(q, "net_capital_flow_pct", None),
            "buyback_amount": getattr(q, "buyback_amount", None),
            "mgmt_buy_price": getattr(q, "mgmt_buy_price", None),
            "outstanding_scale": getattr(q, "outstanding_scale", None),
            "concepts": getattr(q, "concepts", None),
            "pledge_ratio": getattr(q, "pledge_ratio", None),
            "net_super_flow": getattr(q, "net_super_flow", None),
            "net_big_flow": getattr(q, "net_big_flow", None),
            "momentum_5d": getattr(q, "momentum_5d", None),
            "momentum_10d": getattr(q, "momentum_10d", None),
            "momentum_20d": getattr(q, "momentum_20d", None),
            "momentum_60d": getattr(q, "momentum_60d", None),
            "event_score": getattr(q, "event_score", None),
            "event_detail": getattr(q, "event_detail", None),
            "bond_value": getattr(q, "bond_value", None),
            "iv_source": getattr(q, "iv_source", None),
            "north_net": getattr(q, "north_net", None),
            "margin_balance": getattr(q, "margin_balance", None),
            "lhb_count": getattr(q, "lhb_count", None),
            "block_trade_amount": getattr(q, "block_trade_amount", None),
            "holder_num_change": getattr(q, "holder_num_change", None),
            "eps_forecast": getattr(q, "eps_forecast", None),
            "profit_yoy": getattr(q, "profit_yoy", None),
            "revenue_yoy": getattr(q, "revenue_yoy", None),
            "restricted_release_amount": getattr(q, "restricted_release_amount", None),
            "sentiment_score": getattr(q, "sentiment_score", None),
            "rating_score": getattr(q, "rating_score", None),
            "pure_bond_premium_ratio": getattr(q, "pure_bond_premium_ratio", None),
            "eps": getattr(q, "eps", None),
            "bps": getattr(q, "bps", None),
            "hv": getattr(q, "hv", None),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


    if engine:
        quote = await engine.get_quote(code)
        if quote:
            out = quote_to_dict(quote)
            out["data_source"] = DataSource.REAL.value
            return out

    if storage:
        for row in storage.get_latest_quotes():
            if row.get("code") == code:
                out = _row_to_dict(row)
                out["data_source"] = DataSource.REAL.value
                return out

    raise HTTPException(status_code=404, detail=f"Quote for {code} not found")


@router.get("/exchangeable")
async def get_exchangeable_bonds(request: Request):
    """获取可交换债(EB)行情数据"""
    engine = getattr(request.app.state, "engine", None)

    def quote_to_dict(q) -> dict:
        return {
            "code": q.code,
            "name": getattr(q, "name", ""),
            "stock_code": getattr(q, "stock_code", ""),
            "stock_name": getattr(q, "stock_name", ""),
            "price": getattr(q, "price", 0),
            "change_pct": getattr(q, "change_pct", 0),
            "stock_price": getattr(q, "stock_price", 0),
            "conversion_price": getattr(q, "conversion_price", 0),
            "conversion_value": getattr(q, "conversion_value", 0),
            "premium_ratio": getattr(q, "premium_ratio", 0),
            "dual_low": getattr(q, "dual_low", 0),
            "volume": getattr(q, "volume", 0),
            "remaining_years": getattr(q, "remaining_years", 0),
            "forced_call_days": getattr(q, "forced_call_days", 0),
            "is_called": bool(getattr(q, "is_called", False)),
            "call_status": str(getattr(q, "call_status", "") or ""),
            "last_trade_date": _iso(getattr(q, "last_trade_date", None)),
            "maturity_date": _iso(getattr(q, "maturity_date", None)),
            "redemption_price": float(getattr(q, "redemption_price", 0) or 0.0),
            "rating": str(getattr(q, "rating", "") or "") or None,
            "industry": getattr(q, "industry", None),
            "pe": getattr(q, "pe", None),
            "pb": getattr(q, "pb", None),
        }

    if engine and engine.adapter:
        eb_bonds = await engine.adapter.fetch_exchangeable_bonds()
        result = [quote_to_dict(q) for q in eb_bonds]
        return {
            "total": len(result),
            "bonds": result,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    return {"total": 0, "bonds": [], "updated_at": ""}


@router.get("/kline")
async def get_kline(request: Request, symbol: str, period: str = "1d", limit: int = 100):
    """获取可转债 K 线数据（使用真实历史数据）"""
    import akshare as ak
    from datetime import timedelta

    storage = getattr(request.app.state, "storage", None)
    if storage and symbol:
        if period == "1d":
            klines = storage.get_daily_history(symbol, limit)
        else:
            klines = storage.get_quote_history(symbol, limit)
        if klines:
            return [{
                "time": k.get("snapshot_date") or k.get("timestamp", ""),
                "open": float(k.get("price", 0)) if k.get("price") else None,
                "high": float(k.get("price", 0)) if k.get("price") else None,
                "low": float(k.get("price", 0)) if k.get("price") else None,
                "close": float(k.get("price", 0)) if k.get("price") else None,
                "volume": int(k.get("volume", 0)) if k.get("volume") else 0
            } for k in klines]

    if not symbol:
        return []

    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=max(limit, 30) * 2)).strftime("%Y%m%d")
        df = ak.bond_zh_hs_cov_daily(symbol=symbol)
        if df is not None and len(df) > 0:
            df = df.tail(limit)
            return [{
                "time": str(row.get("date", "")) if hasattr(row, "get") else "",
                "open": float(row.get("open", 0)) if hasattr(row, "get") and row.get("open") else None,
                "high": float(row.get("high", 0)) if hasattr(row, "get") and row.get("high") else None,
                "low": float(row.get("low", 0)) if hasattr(row, "get") and row.get("low") else None,
                "close": float(row.get("close", 0)) if hasattr(row, "get") and row.get("close") else None,
                "volume": int(row.get("volume", 0)) if hasattr(row, "get") and row.get("volume") else 0,
            } for _, row in df.iterrows()]
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"[KLine] bond daily fetch failed: {e}")

    return []

@router.get("/search")
async def search(request: Request, keyword: str, limit: int = 20):
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    results = []

    if engine:
        quotes = await engine.get_all_quotes()
        keyword_lower = keyword.lower()
        for q in quotes:
            if keyword_lower in q.code.lower() or keyword_lower in q.name.lower():
                results.append({"code": q.code, "name": q.name})
                if len(results) >= limit:
                    break

    if not results and storage:
        rows = storage.get_latest_quotes()
        keyword_lower = keyword.lower()
        for r in rows:
            code = r.get("code", "")
            name = r.get("name", "")
            if keyword_lower in code.lower() or keyword_lower in name.lower():
                results.append({"code": code, "name": name})
                if len(results) >= limit:
                    break

    return results[:limit]


@router.get("/industries")
async def get_industries(request: Request, fields: str = Query(None, description="Comma-separated field list to include. Omit for all fields.")):
    """获取行业聚合数据: 每个行业的债券数量、平均涨跌幅、平均溢价率、
    平均双低、平均YTM、平均ROE、平均PE/PB、平均动量、
    总成交额、净资金流向等。用于行业轮动页面。
    ?fields=industry,bond_count,avg_momentum_20d to select specific fields."""
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    field_set = set(fields.split(",")) & _INDUSTRIES_ALL_FIELDS if fields else None

    data_rows = []
    if engine:
        data_rows = await engine.get_all_quotes()
    elif storage:
        data_rows = storage.get_latest_quotes()

    if not data_rows:
        return {"industries": [], "total_bonds": 0}

    groups = defaultdict(list)
    for q in data_rows:
        groups[_get_industry(q)].append(q)

    industries = []
    for ind_name, items in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True):
        n = len(items)
        row = {
            "industry": ind_name,
            "bond_count": n,
            "avg_change_pct": round(_safe_avg(items, "change_pct"), 2),
            "avg_stock_change_pct": round(_safe_avg(items, "stock_change_pct"), 2),
            "avg_premium_ratio": round(_safe_avg(items, "premium_ratio"), 2),
            "avg_dual_low": round(_safe_avg(items, "dual_low"), 2),
            "avg_ytm": round(_safe_avg(items, "ytm", nonzero_only=True), 4),
            "avg_roe": round(_safe_avg(items, "roe"), 2),
            "avg_pe": round(_safe_avg(items, "pe", positive_only=True), 2),
            "avg_pb": round(_safe_avg(items, "pb", positive_only=True), 2),
            "avg_gpm": round(_safe_avg(items, "gpm"), 2),
            "avg_debt_ratio": round(_safe_avg(items, "debt_ratio"), 2),
            "avg_turnover_rate": round(_safe_avg(items, "turnover_rate"), 2),
            "avg_cagr": round(_safe_avg(items, "cagr"), 2),
            "avg_pledge_ratio": round(_safe_avg(items, "pledge_ratio"), 2),
            "avg_momentum_5d": round(_safe_avg(items, "momentum_5d"), 2),
            "avg_momentum_10d": round(_safe_avg(items, "momentum_10d"), 2),
            "avg_momentum_20d": round(_safe_avg(items, "momentum_20d"), 2),
            "avg_momentum_60d": round(_safe_avg(items, "momentum_60d"), 2),
            "momentum_dispersion": _momentum_dispersion(items, "momentum_20d"),
            "net_capital_flow": round(_safe_sum(items, "net_capital_flow"), 2),
            "net_super_flow": round(_safe_sum(items, "net_super_flow"), 2),
            "net_big_flow": round(_safe_sum(items, "net_big_flow"), 2),
            "avg_iv": round(_safe_avg(items, "iv"), 2),
            "total_volume": round(_safe_sum(items, "volume"), 2),
            "up_count": _count_positive(items, "change_pct"),
            "down_count": _count_negative(items, "change_pct"),
        }
        industries.append(_filter_fields(row, field_set))

    return {
        "industries": industries,
        "total_bonds": sum(g["bond_count"] for g in industries),
        "total_industries": len(industries),
    }


@router.get("/concepts")
async def get_concepts(request: Request, fields: str = Query(None, description="Comma-separated field list to include. Omit for all fields.")):
    """概念板块聚合: 东方财富+同花顺概念板块，多维度统计
    ?fields=concept,bond_count,avg_momentum_20d to select specific fields."""
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    field_set = set(fields.split(",")) & _CONCEPTS_ALL_FIELDS if fields else None

    data_rows = []
    if engine:
        data_rows = await engine.get_all_quotes()
    elif storage:
        data_rows = storage.get_latest_quotes()
    if not data_rows:
        return {"concepts": [], "total_bonds": 0, "total_concepts": 0, "sources": ["eastmoney", "ths"]}

    groups = defaultdict(list)
    for q in data_rows:
        concepts = getattr(q, "concepts", None) if hasattr(q, "concepts") else (q.get("concepts") if isinstance(q, dict) else None)
        if not concepts:
            continue
        for cname in concepts:
            # ── 兜底过滤：剔除指数/通道/规模/持仓等非真正概念 ──
            from app.engine.data_enrich import _is_non_concept
            if _is_non_concept(cname):
                continue
            groups[cname].append(q)

    result = []
    for cname, items in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True):
        n = len(items)
        if n < 2:
            continue
        # Build bond list (top 5 by dual_low)
        top_bonds = sorted(items, key=lambda q: _val(q, "dual_low", 999))[:5]
        bond_list = [{
            "code": _val(b, "code", ""),
            "name": _val(b, "name", ""),
            "price": _val(b, "price", 0),
            "change_pct": _val(b, "change_pct", 0),
            "premium_ratio": _val(b, "premium_ratio", 0),
            "dual_low": _val(b, "dual_low", 0),
        } for b in top_bonds]

        row = {
            "concept": cname,
            "bond_count": n,
            "avg_change_pct": round(_safe_avg(items, "change_pct"), 2),
            "avg_stock_change_pct": round(_safe_avg(items, "stock_change_pct"), 2),
            "avg_premium_ratio": round(_safe_avg(items, "premium_ratio"), 2),
            "avg_dual_low": round(_safe_avg(items, "dual_low"), 2),
            "avg_ytm": round(_safe_avg(items, "ytm", nonzero_only=True), 4),
            "avg_roe": round(_safe_avg(items, "roe"), 2),
            "avg_pe": round(_safe_avg(items, "pe", positive_only=True), 2),
            "avg_pb": round(_safe_avg(items, "pb", positive_only=True), 2),
            "avg_gpm": round(_safe_avg(items, "gpm"), 2),
            "avg_debt_ratio": round(_safe_avg(items, "debt_ratio"), 2),
            "avg_turnover_rate": round(_safe_avg(items, "turnover_rate"), 2),
            "avg_cagr": round(_safe_avg(items, "cagr"), 2),
            "avg_pledge_ratio": round(_safe_avg(items, "pledge_ratio"), 2),
            "avg_momentum_5d": round(_safe_avg(items, "momentum_5d"), 2),
            "avg_momentum_10d": round(_safe_avg(items, "momentum_10d"), 2),
            "avg_momentum_20d": round(_safe_avg(items, "momentum_20d"), 2),
            "avg_momentum_60d": round(_safe_avg(items, "momentum_60d"), 2),
            "momentum_dispersion": _momentum_dispersion(items, "momentum_20d"),
            "net_capital_flow": round(_safe_sum(items, "net_capital_flow"), 2),
            "net_super_flow": round(_safe_sum(items, "net_super_flow"), 2),
            "net_big_flow": round(_safe_sum(items, "net_big_flow"), 2),
            "avg_iv": round(_safe_avg(items, "iv"), 2),
            "total_volume": round(_safe_sum(items, "volume"), 2),
            "up_count": _count_positive(items, "change_pct"),
            "down_count": _count_negative(items, "change_pct"),
            "top_bonds": bond_list,
        }
        result.append(_filter_fields(row, field_set))
    return {"concepts": result, "total_bonds": sum(g["bond_count"] for g in result if "bond_count" in g), "total_concepts": len(result), "sources": ["eastmoney", "ths"]}


# 概念板块的完整字段集（股票维度）
_STOCK_CONCEPTS_ALL_FIELDS = {
    "concept", "stock_count", "sources",
    "avg_stock_change_pct", "avg_stock_price",
    "avg_momentum_5d", "avg_momentum_10d", "avg_momentum_20d", "avg_momentum_60d",
    "momentum_dispersion",
    "avg_roe", "avg_pe", "avg_pb",
    "avg_gpm", "avg_debt_ratio", "avg_turnover_rate", "avg_cagr", "avg_pledge_ratio",
    "net_capital_flow", "net_super_flow", "net_big_flow",
    "avg_iv", "total_volume", "up_count", "down_count",
    "top_stocks",
}


@router.get("/stock-concepts")
async def get_stock_concepts(
    request: Request,
    source: str = Query("all", description="Filter by source: 'all' | 'em' | 'ths' | 'both' | 'em_only' | 'ths_only'"),
    min_count: int = Query(2, ge=1, le=200, description="Minimum stock count to include a concept"),
    fields: str = Query(None, description="Comma-separated field list to include. Omit for all fields."),
):
    """概念板块聚合（股票维度）: 东方财富+同花顺概念，按正股去重统计。
    与 /concepts 不同：本接口以正股 (stock_code) 为计数单位，返回该概念下涵盖的正股，
    每只正股附带动量/估值/质量/资金流等指标。
    覆盖全市场 A 股 (5000+ 只)，不仅仅是转债正股。
    ?source=em | ths | both | em_only | ths_only 过滤来源
    ?min_count=3 过滤股票数过少的概念
    ?fields=concept,stock_count,avg_momentum_20d 选择特定字段"""
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    field_set = set(fields.split(",")) & _STOCK_CONCEPTS_ALL_FIELDS if fields else None

    data_rows = []
    if engine:
        data_rows = await engine.get_all_quotes()
    elif storage:
        data_rows = storage.get_latest_quotes()

    # Load source attribution map (concept_name -> {"em": bool, "ths": bool})
    source_map: dict[str, dict[str, bool]] = {}
    try:
        from app.engine.data_enrich import get_concept_sources
        source_map = get_concept_sources()
    except Exception as e:
        logger.debug(f"[Market] get_concept_sources failed: {e}")
        source_map = {}

    # Build ALL stock map (bond-sourced + enrichment cache)
    from app.engine import data_enrich
    all_stocks: dict[str, dict] = {}
    seen_stocks: set[str] = set()

    # First: bond-sourced stocks
    for q in data_rows:
        stock_code = _val(q, "stock_code", "")
        if not stock_code or stock_code in seen_stocks:
            continue
        seen_stocks.add(stock_code)
        concepts = getattr(q, "concepts", None) if hasattr(q, "concepts") else (q.get("concepts") if isinstance(q, dict) else None)
        all_stocks[stock_code] = {
            "stock_code": stock_code,
            "stock_name": _val(q, "stock_name", ""),
            "stock_price": _val(q, "stock_price", 0),
            "stock_change_pct": _val(q, "stock_change_pct", 0),
            "pe": _val(q, "pe", 0),
            "pb": _val(q, "pb", 0),
            "roe": _val(q, "roe", 0),
            "gpm": _val(q, "gpm", 0),
            "momentum_5d": _val(q, "momentum_5d", 0),
            "momentum_10d": _val(q, "momentum_10d", 0),
            "momentum_20d": _val(q, "momentum_20d", 0),
            "momentum_60d": _val(q, "momentum_60d", 0),
            "turnover_rate": _val(q, "turnover_rate", 0),
            "net_capital_flow": _val(q, "net_capital_flow", 0),
            "net_capital_flow_pct": _val(q, "net_capital_flow_pct", 0),
            "net_super_flow": _val(q, "net_super_flow", 0),
            "net_big_flow": _val(q, "net_big_flow", 0),
            "volume": _val(q, "volume", 0),
            "debt_ratio": _val(q, "debt_ratio", 0),
            "iv": _val(q, "iv", 0) or data_enrich._vol_map.get(stock_code, 0) or 0,
            "pledge_ratio": _val(q, "pledge_ratio", 0) or data_enrich._pledge_map.get(stock_code, 0) or 0,
            "cagr": _val(q, "cagr", 0),
            "concepts": (concepts or []),
        }

    # Second: ALL A-share stocks from name map, enriched from caches
    for scode in data_enrich._name_map:
        if scode in seen_stocks:
            continue
        seen_stocks.add(scode)
        sd = _build_stock_from_cache(scode)
        sd["stock_name"] = data_enrich._name_map.get(scode, "")
        all_stocks[scode] = sd

    # Build concept -> list of stock dicts, dedup by stock_code per concept
    groups: dict[str, dict[str, object]] = {}
    # ── 兜底过滤：剔除指数/通道/规模/持仓等非真正概念 ──
    from app.engine.data_enrich import _is_non_concept as _is_non_concept_fn
    for scode, stock_dict in all_stocks.items():
        concepts = stock_dict.get("concepts", [])
        if not concepts:
            continue
        for cname in concepts:
            if _is_non_concept_fn(cname):
                continue
            entry = groups.setdefault(cname, {"stocks": {}, "items": []})  # type: ignore[var-annotated]
            stocks_map = entry["stocks"]  # type: ignore[index]
            if scode not in stocks_map:
                stocks_map[scode] = stock_dict  # type: ignore[index]
            entry["items"].append(stock_dict)  # type: ignore[index]

    # Apply source filter
    def _concept_passes(cname: str) -> bool:
        if source == "all":
            return True
        info = source_map.get(cname, {})
        em = bool(info.get("em"))
        ths = bool(info.get("ths"))
        if source == "em":
            return em
        if source == "ths":
            return ths
        if source == "both":
            return em and ths
        if source == "em_only":
            return em and not ths
        if source == "ths_only":
            return ths and not em
        return True

    result = []
    for cname, entry in sorted(groups.items(), key=lambda x: len(x[1]["stocks"]), reverse=True):  # type: ignore[arg-type]
        if not _concept_passes(cname):
            continue
        stocks_map = entry["stocks"]  # type: ignore[index]
        items = list(entry["items"])  # type: ignore[index]
        n = len(stocks_map)
        if n < min_count:
            continue

        # Top 20 stocks by net_capital_flow_pct (资金流入占比), fallback to momentum_20d
        sorted_stocks = sorted(stocks_map.values(), key=lambda s: abs(s.get("net_capital_flow_pct", 0) or 0), reverse=True)
        if all((s.get("net_capital_flow_pct") or 0) == 0 for s in sorted_stocks):
            sorted_stocks = sorted(stocks_map.values(), key=lambda s: abs(s.get("momentum_20d", 0) or 0), reverse=True)
        top_stocks = [dict(s) for s in sorted_stocks[:20]]

        info = source_map.get(cname, {})
        sources_list = []
        if info.get("em"):
            sources_list.append("eastmoney")
        if info.get("ths"):
            sources_list.append("ths")
        if not sources_list:
            sources_list = ["eastmoney", "ths"]

        row = {
            "concept": cname,
            "stock_count": n,
            "sources": sources_list,
            "avg_stock_change_pct": round(_safe_avg(items, "stock_change_pct"), 2),
            "avg_stock_price": round(_safe_avg(items, "stock_price"), 2),
            "avg_momentum_5d": round(_safe_avg(items, "momentum_5d"), 2),
            "avg_momentum_10d": round(_safe_avg(items, "momentum_10d"), 2),
            "avg_momentum_20d": round(_safe_avg(items, "momentum_20d"), 2),
            "avg_momentum_60d": round(_safe_avg(items, "momentum_60d"), 2),
            "momentum_dispersion": _momentum_dispersion(items, "momentum_20d"),
            "avg_roe": round(_safe_avg(items, "roe"), 2),
            "avg_pe": round(_safe_avg(items, "pe", positive_only=True), 2),
            "avg_pb": round(_safe_avg(items, "pb", positive_only=True), 2),
            "avg_gpm": round(_safe_avg(items, "gpm"), 2),
            "avg_debt_ratio": round(_safe_avg(items, "debt_ratio"), 2),
            "avg_turnover_rate": round(_safe_avg(items, "turnover_rate"), 2),
            "avg_pledge_ratio": round(_safe_avg(items, "pledge_ratio"), 2),
            "avg_cagr": round(_safe_avg(items, "cagr"), 2),
            "net_capital_flow": round(_safe_sum(items, "net_capital_flow"), 2),
            "net_super_flow": round(_safe_sum(items, "net_super_flow"), 2),
            "net_big_flow": round(_safe_sum(items, "net_big_flow"), 2),
            "avg_iv": round(_safe_avg(items, "iv"), 2),
            "total_volume": round(_safe_sum(items, "volume"), 2),
            "up_count": _count_positive(items, "stock_change_pct"),
            "down_count": _count_negative(items, "stock_change_pct"),
            "top_stocks": top_stocks,
        }
        result.append(_filter_fields(row, field_set))

    total_unique_stocks = set()
    for g in result:
        for s in g.get("top_stocks", []):
            if s.get("stock_code"):
                total_unique_stocks.add(s["stock_code"])

    return {
        "concepts": result,
        "total_concepts": len(result),
        "total_stocks": len(total_unique_stocks) if total_unique_stocks else sum(s.get("stock_count", 0) for s in result),
        "sources": ["eastmoney", "ths"],
        "source_filter": source,
        "min_count": min_count,
    }


def _build_stock_from_cache(stock_code: str) -> dict:
    """为给定 stock_code 从 enrichment caches 构建一个股票 dict
    用于补充不在 bond 数据中的 A 股。"""
    from app.engine import data_enrich
    name = data_enrich._name_map.get(stock_code, "")
    industry = data_enrich._industry_map.get(stock_code, "")
    spot = data_enrich._spot_map.get(stock_code, {}) or {}
    fin = data_enrich._fin_map.get(stock_code, {}) or {}
    flow = data_enrich._fund_flow_map.get(stock_code, {}) or {}
    # NOTE: _fund_flow_map keys are bare 6-digit codes (no sh/sz prefix), so prefix fallback is dead code.
    debt = data_enrich._debt_map.get(stock_code, {}) or {}
    mom = data_enrich._momentum_map.get(stock_code, {}) or {}
    volatility = data_enrich._vol_map.get(stock_code)
    pledge = data_enrich._pledge_map.get(stock_code)
    concepts = data_enrich._concept_map.get(stock_code, [])
    return {
        "stock_code": stock_code,
        "stock_name": name,
        "stock_price": spot.get("price", 0) or 0,
        "stock_change_pct": spot.get("change_pct", 0) or 0,
        "pe": spot.get("pe", 0) or 0,
        "pb": spot.get("pb", 0) or 0,
        "roe": fin.get("roe", 0) or 0,
        "gpm": fin.get("gpm", 0) or 0,
        "momentum_5d": mom.get("5d", 0) or 0,
        "momentum_10d": mom.get("10d", 0) or 0,
        "momentum_20d": mom.get("20d", 0) or 0,
        "momentum_60d": mom.get("60d", 0) or 0,
        "turnover_rate": spot.get("turnover_rate", 0) or 0,
        "net_capital_flow": flow.get("net_main") if flow.get("net_main") is not None else None,
        "net_capital_flow_pct": flow.get("net_main_pct") if flow.get("net_main_pct") is not None else None,
        "net_super_flow": flow.get("net_super") if flow.get("net_super") is not None else None,
        "net_big_flow": flow.get("net_big") if flow.get("net_big") is not None else None,
        "volume": spot.get("volume", 0) or 0,
        "debt_ratio": debt.get("debt_ratio", 0) if isinstance(debt, dict) else 0,
        "iv": volatility or 0,
        "pledge_ratio": pledge or 0,
        "cagr": fin.get("cagr", 0) or 0,
        "industry": industry,
        "concepts": concepts if isinstance(concepts, list) else [],
    }


@router.get("/stock-industries")
async def get_stock_industries(request: Request, fields: str = Query(None, description="Comma-separated field list to include. Omit for all fields.")):
    """行业轮动-股票版: 按申万行业聚合正股数据，提供股票维度的行业轮动指标。
    与 /industries 不同，此接口聚焦正股维度，展示每个行业内所有正股的
    涨跌幅、动量、资金流向、换手率、估值等细粒度数据。
    覆盖全市场 A 股 (5000+ 只)，不仅仅是转债正股。
    ?fields=industry,stock_count,avg_momentum_20d to select specific fields."""
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    field_set = set(fields.split(",")) & _STOCK_INDUSTRIES_ALL_FIELDS if fields else None

    # 1. Get bond data (may cover 900+ stocks)
    data_rows = []
    if engine:
        data_rows = await engine.get_all_quotes()
    elif storage:
        data_rows = storage.get_latest_quotes()

    # 2. Build stock list from enrichment caches (covers ALL 5000+ A-shares)
    from app.engine import data_enrich
    all_stocks: dict[str, dict] = {}
    seen_stocks: set[str] = set()

    # First: add bond-sourced stocks (they have richer data)
    for q in data_rows:
        stock_code = _val(q, "stock_code", "")
        if stock_code:
            if stock_code in seen_stocks:
                continue
            seen_stocks.add(stock_code)
            all_stocks[stock_code] = {
                "stock_code": stock_code,
                "stock_name": _val(q, "stock_name", ""),
                "stock_price": _val(q, "stock_price", 0),
                "stock_change_pct": _val(q, "stock_change_pct", 0),
                "pe": _val(q, "pe", 0),
                "pb": _val(q, "pb", 0),
                "roe": _val(q, "roe", 0),
                "gpm": _val(q, "gpm", 0),
                "momentum_5d": _val(q, "momentum_5d", 0),
                "momentum_10d": _val(q, "momentum_10d", 0),
                "momentum_20d": _val(q, "momentum_20d", 0),
                "momentum_60d": _val(q, "momentum_60d", 0),
                "turnover_rate": _val(q, "turnover_rate", 0),
                "net_capital_flow": _val(q, "net_capital_flow", None),
                "net_capital_flow_pct": _val(q, "net_capital_flow_pct", None),
                "net_super_flow": _val(q, "net_super_flow", None) if _val(q, "net_super_flow", None) is not None else data_enrich._fund_flow_map.get(stock_code, {}).get("net_super"),
                "net_big_flow": _val(q, "net_big_flow", None) if _val(q, "net_big_flow", None) is not None else data_enrich._fund_flow_map.get(stock_code, {}).get("net_big"),
                "volume": _val(q, "volume", 0),
                "debt_ratio": _val(q, "debt_ratio", 0),
                "iv": _val(q, "iv", 0) or data_enrich._vol_map.get(stock_code, 0) or 0,
                "pledge_ratio": _val(q, "pledge_ratio", 0) or data_enrich._pledge_map.get(stock_code, 0) or 0,
                "cagr": _val(q, "cagr", 0),
                "industry": _get_industry(q),
                "concepts": getattr(q, "concepts", []) or [],
            }

    # Second: add ALL A-share stocks from name map (enriched from caches)
    for scode, sname in data_enrich._name_map.items():
        if scode in seen_stocks:
            continue
        seen_stocks.add(scode)
        all_stocks[scode] = _build_stock_from_cache(scode)
        all_stocks[scode]["stock_name"] = sname

    # 3. Group by industry
    groups = defaultdict(list)
    for scode, stock_dict in all_stocks.items():
        ind = stock_dict.get("industry") or "其他"
        groups[ind].append(stock_dict)

    # 4. Build response
    industries = []
    _raw_industry_rows = []  # 未裁剪的完整 row, 供 recommendations 计算用
    for ind_name, items in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True):
        n = len(items)
        sorted_items = sorted(items, key=lambda s: abs(s.get("momentum_20d", 0) or 0), reverse=True)
        top_list = sorted_items[:20]

        row = {
            "industry": ind_name,
            "stock_count": n,
            "avg_stock_change_pct": round(_safe_avg(items, "stock_change_pct"), 2),
            "avg_stock_price": round(_safe_avg(items, "stock_price"), 2),
            "avg_momentum_5d": round(_safe_avg(items, "momentum_5d"), 2),
            "avg_momentum_10d": round(_safe_avg(items, "momentum_10d"), 2),
            "avg_momentum_20d": round(_safe_avg(items, "momentum_20d"), 2),
            "avg_momentum_60d": round(_safe_avg(items, "momentum_60d"), 2),
            "momentum_dispersion": _momentum_dispersion(items, "momentum_20d"),
            "avg_roe": round(_safe_avg(items, "roe"), 2),
            "avg_pe": round(_safe_avg(items, "pe", positive_only=True), 2),
            "avg_pb": round(_safe_avg(items, "pb", positive_only=True), 2),
            "avg_gpm": round(_safe_avg(items, "gpm"), 2),
            "avg_debt_ratio": round(_safe_avg(items, "debt_ratio"), 2),
            "avg_turnover_rate": round(_safe_avg(items, "turnover_rate"), 2),
            "net_capital_flow": round(_safe_sum(items, "net_capital_flow"), 2),
            "net_capital_flow_pct": round(_safe_avg(items, "net_capital_flow_pct"), 4),
            "net_super_flow": round(_safe_sum(items, "net_super_flow"), 2),
            "net_big_flow": round(_safe_sum(items, "net_big_flow"), 2),
            "avg_iv": round(_safe_avg(items, "iv"), 2),
            "avg_pledge_ratio": round(_safe_avg(items, "pledge_ratio"), 2),
            "avg_cagr": round(_safe_avg(items, "cagr"), 2),
            "total_volume": round(_safe_sum(items, "volume"), 2),
            "up_count": _count_positive(items, "stock_change_pct"),
            "down_count": _count_negative(items, "stock_change_pct"),
            "stocks": top_list,
        }
        industries.append(_filter_fields(row, field_set))
        _raw_industry_rows.append(row)

    # 布局推荐: 基于 (未裁剪的) 完整行业 row 计算. 注意 industries 已被 _filter_fields
    # 裁剪过, 推荐计算需要全部字段, 所以传 raw rows 给 _build_recommendations.
    try:
        recommendations = _build_recommendations([_r for _r in _raw_industry_rows])
    except Exception as e:
        logger.debug(f"[Market] _build_recommendations failed: {e}")
        recommendations = {"short_term": [], "mid_term": [], "long_term": [], "generated_at": None}

    return {
        "industries": industries,
        "total_stocks": len(all_stocks),
        "total_industries": len(industries),
        "recommendations": recommendations,
    }


@router.get("/industry-recommendations")
async def get_industry_recommendations(
    request: Request,
    horizon: str = Query("all", description="short|mid|long|all"),
    top_k: int = Query(5, ge=1, le=20, description="每档返回行业数"),
    weights_json: str = Query("", description='自定义权重 JSON, e.g. {"short_term":{"momentum":0.7}}'),
):
    """行业布局推荐: 短期(≤1周)/中期(2周)/长期(1月).
    复用 /stock-industries 的行业聚合, 但只返回推荐子集 + 中文原因.
    weights_json: 可选, 传入后覆盖默认 _HORIZON_WEIGHTS.
    """
    import json as _json
    hw = None
    if weights_json:
        try:
            hw = _json.loads(weights_json)
        except _json.JSONDecodeError:
            pass  # 忽略无效 JSON, 使用默认权重

    # 复用 /stock-industries 的行业聚合逻辑 (不传 fields, 拿全字段)
    full = await get_stock_industries(request, fields=None)
    recs = full.get("recommendations") or _build_recommendations(
        full.get("industries", []), top_k=top_k, horizon_weights=hw
    )

    # 按 horizon 过滤
    h_map = {"short": "short_term", "mid": "mid_term", "long": "long_term"}
    if horizon in h_map:
        key = h_map[horizon]
        return {"horizon": key, "recommendations": recs.get(key, [])[:top_k], "generated_at": recs.get("generated_at")}
    return {"horizon": "all", **recs}


@router.get("/industry-recommendations/history")
async def get_recommendation_history(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="查询最近 N 天的历史"),
):
    """行业推荐历史快照. 每日保存一次, 用于回测验证推荐准确性."""
    history = _load_rec_history(days)
    return {"history": history, "days": len(history)}


@router.get("/industry-recommendations/accuracy")
async def get_recommendation_accuracy(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="backtest N days"),
):
    """Recommendation accuracy backtest.
    Compares baseline momentum (at recommendation time) with current momentum.
    Hit = current momentum > baseline (industry moved in favorable direction).
    """
    global _ACCURACY_CACHE, _ACCURACY_CACHE_TS
    import time
    now = time.time()
    with _rec_cache_lock:
        if _ACCURACY_CACHE is not None and (now - _ACCURACY_CACHE_TS) < _ACCURACY_CACHE_TTL:
            return _ACCURACY_CACHE

    history = _load_rec_history(days)
    if not history:
        return {"accuracy": {}, "days_analyzed": 0}

    try:
        full = await get_stock_industries(request, fields=None)
        industries = full.get("industries", [])
    except Exception as e:
        logger.debug(f"[Market] get_stock_industries failed: {e}")
        industries = []

    ind_map = {}
    for ind in industries:
        name = ind.get("industry", "")
        if name:
            ind_map[name] = ind

    baseline_field = {"short_term": "momentum_5d", "mid_term": "momentum_10d", "long_term": "momentum_20d"}
    current_field = {"short_term": "avg_momentum_5d", "mid_term": "avg_momentum_10d", "long_term": "avg_momentum_20d"}

    accuracy = {}
    for horizon in ("short_term", "mid_term", "long_term"):
        total = 0
        hits = 0
        details = []
        bf = baseline_field[horizon]
        cf = current_field[horizon]
        for rec_day in history:
            recs = rec_day.get(horizon, [])
            rec_date = rec_day.get("date", "")
            baseline_map = rec_day.get("_baseline", {})
            # Skip days without baseline data (old format) - don't count as miss
            if not baseline_map:
                continue
            for rec in recs:
                ind_name = rec.get("industry", "")
                rec_score = rec.get("score", 0)
                bl = _safe_num(baseline_map.get(ind_name, {}).get(bf))
                # Skip if no baseline for this industry - can't evaluate
                if bl == 0 and not baseline_map.get(ind_name, {}).get(bf):
                    continue
                cur = _safe_num(ind_map.get(ind_name, {}).get(cf))
                actual = round(cur - bl, 2)
                is_hit = actual > 0
                total += 1
                if is_hit:
                    hits += 1
                details.append({"date": rec_date, "industry": ind_name, "score": rec_score, "baseline": bl, "current": cur, "actual": actual, "hit": is_hit})
        accuracy[horizon] = {"total": total, "hits": hits, "hit_rate": round(hits / total * 100, 1) if total > 0 else 0, "details": details[:100]}

    # Random baseline: Monte Carlo simulation
    # Instead of simple up-ratio, simulate randomly picking top_k=5 industries 1000 times
    random_baseline = {}
    for horizon in ("short_term", "mid_term", "long_term"):
        cf = current_field[horizon]
        up_list = [1 if _safe_num(ind.get(cf, 0)) > 0 else 0 for ind in industries]
        n_ind = len(up_list)
        if n_ind < 5:
            random_baseline[horizon] = round(sum(up_list) / max(n_ind, 1) * 100, 1)
        else:
            trials = 1000
            total_hits = 0
            for _ in range(trials):
                picks = random.sample(up_list, 5)
                total_hits += sum(picks)
            random_baseline[horizon] = round(total_hits / (trials * 5) * 100, 1)

    # Daily alpha trend: group details by date, compute per-day alpha
    daily_alpha = {}
    for horizon in ("short_term", "mid_term", "long_term"):
        day_stats = {}
        for d in accuracy[horizon].get("details", []):
            dt = d.get("date", "")
            if dt not in day_stats:
                day_stats[dt] = {"hits": 0, "total": 0}
            day_stats[dt]["total"] += 1
            if d.get("hit"):
                day_stats[dt]["hits"] += 1
        rb = random_baseline.get(horizon, 0)
        for dt, st in day_stats.items():
            if st["total"] > 0:
                daily_hr = round(st["hits"] / st["total"] * 100, 1)
                daily_alpha.setdefault(dt, {})[horizon] = round(daily_hr - rb, 1)

    # Add alpha (information increment): hit_rate - random_baseline
    for k in accuracy:
        rb = random_baseline.get(k, 0)
        hr = accuracy[k].get("hit_rate", 0)
        accuracy[k]["alpha"] = round(hr - rb, 1)
    random_baseline["alpha_msg"] = "信息增量(α)=命中率-随机基线，正值表示推荐优于随机"

    result = {"accuracy": accuracy, "random_baseline": random_baseline, "daily_alpha": daily_alpha, "days_analyzed": len(history)}
    with _rec_cache_lock:
        _ACCURACY_CACHE = result
        _ACCURACY_CACHE_TS = time.time()
    return result


#  Extended data source endpoints (北向资金/融资融券/龙虎榜/大宗/股东/业绩/解禁)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/north-capital")
async def get_north_capital(request: Request):
    """北向资金：沪股通/深股通资金流向 + 个股北向持仓变化"""
    try:
        from app.engine import data_enrich
        data_enrich._load_north_cache()
        raw = data_enrich.get_north_map()
    except Exception as e:
        return {"summary": [], "stocks": [], "total": 0, "error": str(e)}

    summary = [v for k, v in raw.items() if k == "_summary"]
    stocks = [
        {**v, "code": k}
        for k, v in raw.items()
        if isinstance(v, dict) and not v.get("_summary") and len(k) == 6
    ]
    stocks = sorted(stocks, key=lambda s: s.get("hold_market_cap") or 0, reverse=True)[:500]
    return {"summary": summary, "stocks": stocks, "total": len(stocks)}


@router.get("/margin-stocks")
async def get_margin_stocks(request: Request):
    """融资融券：个股融资余额/买入额 + 上交所汇总"""
    try:
        from app.engine import data_enrich
        data_enrich._load_margin_cache()
        raw = data_enrich.get_margin_map()
    except Exception as e:
        return {"stocks": [], "summary": [], "total": 0, "error": str(e)}

    summary = [v for k, v in raw.items() if k == "_summary"]
    stocks = [
        {**v, "code": k}
        for k, v in raw.items()
        if isinstance(v, dict) and not v.get("_summary") and len(k) == 6
    ]
    stocks = sorted(stocks, key=lambda s: s.get("rzye") or 0, reverse=True)[:500]
    return {"stocks": stocks, "summary": summary, "total": len(stocks)}


@router.get("/lhb")
async def get_lhb(request: Request):
    """龙虎榜：个股上榜统计 + 席位"""
    try:
        from app.engine import data_enrich
        data_enrich._load_lhb_cache()
        raw = data_enrich.get_lhb_map()
    except Exception as e:
        return {"stocks": [], "total": 0, "error": str(e)}

    stocks = [
        {**v, "code": k}
        for k, v in raw.items()
        if isinstance(v, dict) and len(k) == 6
    ]
    stocks = sorted(stocks, key=lambda s: abs(s.get("lhb_count") or 0), reverse=True)[:300]
    return {"stocks": stocks, "total": len(stocks)}


@router.get("/block-trade")
async def get_block_trade(request: Request):
    """大宗交易：近 30 个交易日个股大宗交易汇总"""
    try:
        from app.engine import data_enrich
        data_enrich._load_block_trade_cache()
        raw = data_enrich.get_block_trade_map()
    except Exception as e:
        return {"stocks": [], "total": 0, "error": str(e)}

    stocks = [
        {**v, "code": k}
        for k, v in raw.items()
        if isinstance(v, dict) and len(k) == 6
    ]
    stocks = sorted(stocks, key=lambda s: s.get("block_trade_amount") or 0, reverse=True)[:300]
    return {"stocks": stocks, "total": len(stocks)}


@router.get("/holder-num")
async def get_holder_num(request: Request):
    """股东户数：最新报告期股东户数 + 变动"""
    try:
        from app.engine import data_enrich
        data_enrich._load_holder_num_cache()
        raw = data_enrich.get_holder_num_map()
    except Exception as e:
        return {"stocks": [], "total": 0, "error": str(e)}

    stocks = [
        {**v, "code": k}
        for k, v in raw.items()
        if isinstance(v, dict) and len(k) == 6
    ]
    return {"stocks": stocks, "total": len(stocks)}


@router.get("/earnings-forecast")
async def get_earnings_forecast(request: Request):
    """业绩预告：类型 / 变动幅度 / 摘要"""
    try:
        from app.engine import data_enrich
        data_enrich._load_earnings_forecast_cache()
        raw = data_enrich.get_earnings_forecast_map()
    except Exception as e:
        return {"stocks": [], "total": 0, "error": str(e)}

    stocks = []
    for k, v in raw.items():
        if not isinstance(v, dict) or len(k) != 6:
            continue
        # 字段适配: change_pct -> change_pct_min, change_pct_max
        item = {**v, "code": k}
        # 如果有 change_pct 但没有 min/max，用同一个值填充
        if "change_pct" in v and "change_pct_min" not in v:
            pct = v["change_pct"]
            if pct is not None:
                # 变动幅度可能是范围或单值，这里简化为 min=max
                item["change_pct_min"] = pct
                item["change_pct_max"] = pct
        # 摘要字段: change_desc 或 reason -> summary
        if "summary" not in item:
            item["summary"] = v.get("change_desc") or v.get("reason") or ""
        stocks.append(item)
    return {"stocks": stocks, "total": len(stocks)}


@router.get("/earnings-express")
async def get_earnings_express(request: Request):
    """业绩快报：EPS / ROE / 营收 / 净利润"""
    try:
        from app.engine import data_enrich
        data_enrich._load_earnings_express_cache()
        raw = data_enrich.get_earnings_express_map()
    except Exception as e:
        return {"stocks": [], "total": 0, "error": str(e)}

    stocks = [
        {**v, "code": k}
        for k, v in raw.items()
        if isinstance(v, dict) and len(k) == 6
    ]
    return {"stocks": stocks, "total": len(stocks)}


@router.get("/restricted-release")
async def get_restricted_release(request: Request):
    """限售解禁：未来 90 天解禁计划"""
    try:
        from app.engine import data_enrich
        data_enrich._load_restricted_release_cache()
        raw = data_enrich.get_restricted_release_map()
    except Exception as e:
        return {"events": [], "total": 0, "error": str(e)}

    events = list(raw.values()) if isinstance(raw, dict) else []
    events = sorted(
        [e for e in events if isinstance(e, dict)],
        key=lambda e: e.get("restricted_release_amount") or 0,
        reverse=True,
    )[:300]
    return {"events": events, "total": len(events)}


@router.get("/data-sources")
async def get_data_sources_status(request: Request):
    """所有数据源刷新状态(提供给前端检查)"""
    try:
        from pathlib import Path as _P
        from app.engine.data_enrich import (
            _INDUSTRY_CACHE, _SPOT_CACHE, _FIN_CACHE, _FUND_FLOW_CACHE,
            _DEBT_CACHE, _VOL_CACHE, _BUYBACK_CACHE, _MGMT_CACHE,
            _PLEDGE_CACHE, _MOMENTUM_CACHE, _EVENT_CACHE, _CONCEPT_CACHE,
            _BOND_OUTSTANDING_CACHE, _CALL_STATUS_CACHE, _STOCK_NAME_CACHE,
            _BOND_PRICE_CACHE, _COUPON_RATE_CACHE,
            _NORTH_CACHE, _MARGIN_CACHE, _LHB_CACHE, _BLOCK_TRADE_CACHE,
            _HOLDER_NUM_CACHE, _EARNINGS_FORECAST_CACHE, _EARNINGS_EXPRESS_CACHE,
            _RESTRICTED_RELEASE_CACHE,
            _MAIN_BIZ_CACHE, _ANALYST_RANK_CACHE, _MACRO_CPI_CACHE,
            _MACRO_PPI_CACHE, _MACRO_M2_CACHE, _MACRO_LPR_CACHE,
        )
        cache_dir = _INDUSTRY_CACHE.parent
        sources = {
            # 第一批：核心 enrichment (13)
            "industry": _INDUSTRY_CACHE,
            "spot": _SPOT_CACHE,
            "fin": _FIN_CACHE,
            "fund_flow": _FUND_FLOW_CACHE,
            "debt": _DEBT_CACHE,
            "volatility": _VOL_CACHE,
            "buyback": _BUYBACK_CACHE,
            "mgmt": _MGMT_CACHE,
            "pledge": _PLEDGE_CACHE,
            "momentum": _MOMENTUM_CACHE,
            "event": _EVENT_CACHE,
            "concept": _CONCEPT_CACHE,
            "bond_outstanding": _BOND_OUTSTANDING_CACHE,
            "call_status": _CALL_STATUS_CACHE,
            "stock_name": _STOCK_NAME_CACHE,
            "bond_price": _BOND_PRICE_CACHE,
            "coupon_rate": _COUPON_RATE_CACHE,
            "main_business": _MAIN_BIZ_CACHE,
            "analyst_rank": _ANALYST_RANK_CACHE,
            "macro_cpi": _MACRO_CPI_CACHE,
            "macro_ppi": _MACRO_PPI_CACHE,
            "macro_m2": _MACRO_M2_CACHE,
            "macro_lpr": _MACRO_LPR_CACHE,
            # 第二批：扩展 (8)
            "north": _NORTH_CACHE,
            "margin": _MARGIN_CACHE,
            "lhb": _LHB_CACHE,
            "block_trade": _BLOCK_TRADE_CACHE,
            "holder_num": _HOLDER_NUM_CACHE,
            "earnings_forecast": _EARNINGS_FORECAST_CACHE,
            "earnings_express": _EARNINGS_EXPRESS_CACHE,
            "restricted_release": _RESTRICTED_RELEASE_CACHE,
        }
        result = {}
        import time as _time
        for name, path in sources.items():
            if path.exists():
                import json as _json
                try:
                    with open(path, "r") as f:
                        data = _json.load(f)
                    real = [k for k in data if not k.startswith("_")]
                    result[name] = {
                        "path": str(path),
                        "exists": True,
                        "size": path.stat().st_size,
                        "entries": len(real),
                        "ts": data.get("_ts", 0),
                        "age_seconds": round(_time.time() - data.get("_ts", 0), 1) if data.get("_ts") else None,
                    }
                except Exception as e:
                    result[name] = {"path": str(path), "exists": True, "error": str(e)}
            else:
                result[name] = {"path": str(path), "exists": False, "entries": 0}
        return {"sources": result, "cache_dir": str(cache_dir)}
    except Exception as e:
        return {"sources": {}, "error": str(e)}
