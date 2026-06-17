from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, date
from collections import defaultdict
import statistics

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
#  Module-level helpers — shared by all aggregation endpoints
# ═══════════════════════════════════════════════════════════════════════════════

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
    If nonzero_only, also skip values == 0 (for YTM where 0 = no data)."""
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
    return sum(vals) / max(len(vals), 1)


def _safe_sum(items: list, attr: str) -> float:
    """Sum an attribute across items, treating None as 0."""
    return sum((_val(q, attr, 0) or 0) for q in items)


def _count_valid(items: list, attr: str) -> int:
    """Count items where attribute is not None."""
    return sum(1 for q in items if _val(q, attr) is not None)


def _count_positive(items: list, attr: str) -> int:
    """Count items where attribute > 0."""
    return sum(1 for q in items if (_val(q, attr, 0) or 0) > 0)


def _count_negative(items: list, attr: str) -> int:
    """Count items where attribute < 0."""
    return sum(1 for q in items if (_val(q, attr, 0) or 0) < 0)


def _momentum_dispersion(items: list, attr: str = "momentum_20d") -> float:
    """Compute stdev of momentum values within a group. Returns 0 if < 2 values."""
    vals = [_val(q, attr, 0) for q in items if _val(q, attr) is not None]
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
            "restricted_release_amount": getattr(q, "restricted_release_amount", None),
        }

    def row_to_dict(r: dict) -> dict:
        return {
            "code": r.get("code", ""),
            "name": r.get("name", ""),
            "stock_code": r.get("stock_code", ""),
            "price": float(r.get("price", 0)),
            "change_pct": float(r.get("change_pct", 0)),
            "stock_price": float(r.get("stock_price", 0)),
            "stock_change_pct": float(r.get("stock_change_pct", 0)),
            "conversion_price": float(r.get("conversion_price", 0)),
            "conversion_value": float(r.get("conversion_value", 0)),
            "premium_ratio": float(r.get("premium_ratio", 0)),
            "dual_low": float(r.get("dual_low", 0)),
            "ytm": float(r.get("ytm", 0)),
            "volume": float(r.get("volume", 0)) if r.get("volume") else 0,
            "remaining_years": float(r.get("remaining_years", 0)),
            "forced_call_days": int(r.get("forced_call_days", 0)),
            "is_called": bool(r.get("is_called") or False),
            "stock_name": r.get("stock_name", ""),
                        "call_status": str(r.get("call_status", "") or ""),
            "last_trade_date": _iso(r.get("last_trade_date")),
            "maturity_date": _iso(r.get("maturity_date")),
            "redemption_price": float(r.get("redemption_price", 0) or 0.0),
            "rating": str(r.get("rating", "") or "") or None,
            "concepts": r.get("concepts", None),
            "industry": r.get("industry"),
            "concepts": r.get("concepts") or [],
            "roe": r.get("roe"),
            "gpm": r.get("gpm"),
            "cagr": r.get("cagr"),
            "debt_ratio": r.get("debt_ratio"),
            "current_ratio": r.get("current_ratio"),
            "pe": r.get("pe"),
            "pb": r.get("pb"),
            "iv": r.get("iv"),
            "buyback_amount": r.get("buyback_amount"),
            "mgmt_buy_price": r.get("mgmt_buy_price"),
            "outstanding_scale": r.get("outstanding_scale"),
        }

    if engine:
        quotes = await engine.get_all_quotes()
        result = [quote_to_dict(q) for q in quotes if not symbol_list or q.code in symbol_list]
        if not symbol_list:
            return {
                "total": len(result),
                "bonds": result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        return result

    if storage:
        rows = storage.get_latest_quotes()
        result = [row_to_dict(r) for r in rows if not symbol_list or r.get("code") in symbol_list]
        if not symbol_list:
            return {
                "total": len(result),
                "bonds": result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        return result

    if not symbol_list:
        return {"total": 0, "bonds": [], "updated_at": ""}
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def row_to_dict(r: dict) -> dict:
        return {
            "code": r.get("code", ""),
            "name": r.get("name", ""),
            "price": float(r.get("price", 0)),
            "change_pct": float(r.get("change_pct", 0)),
            "stock_price": float(r.get("stock_price", 0)),
            "stock_change_pct": float(r.get("stock_change_pct", 0)),
            "conversion_price": float(r.get("conversion_price", 0)),
            "conversion_value": float(r.get("conversion_value", 0)),
            "premium_ratio": float(r.get("premium_ratio", 0)),
            "dual_low": float(r.get("dual_low", 0)),
            "ytm": float(r.get("ytm", 0)),
            "volume": float(r.get("volume", 0)) if r.get("volume") else 0,
            "remaining_years": float(r.get("remaining_years", 0)),
            "forced_call_days": int(r.get("forced_call_days", 0)),
            "is_called": bool(r.get("is_called") or False),
            "call_status": str(r.get("call_status", "") or ""),
            "last_trade_date": _iso(r.get("last_trade_date")),
            "maturity_date": _iso(r.get("maturity_date")),
            "redemption_price": float(r.get("redemption_price", 0) or 0.0),
            "rating": str(r.get("rating", "") or "") or None,
            "stock_code": r.get("stock_code", ""),
            "industry": r.get("industry"),
            "roe": r.get("roe"),
            "gpm": r.get("gpm"),
            "cagr": r.get("cagr"),
            "debt_ratio": r.get("debt_ratio"),
            "current_ratio": r.get("current_ratio"),
            "pe": r.get("pe"),
            "pb": r.get("pb"),
            "iv": r.get("iv"),
            "buyback_amount": r.get("buyback_amount"),
            "mgmt_buy_price": r.get("mgmt_buy_price"),
            "outstanding_scale": r.get("outstanding_scale"),
            "timestamp": str(r.get("timestamp", "")),
        }

    if engine:
        quote = await engine.get_quote(code)
        if quote:
            return quote_to_dict(quote)

    if storage:
        for row in storage.get_latest_quotes():
            if row.get("code") == code:
                return row_to_dict(row)

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
    except Exception:
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
            "concepts": (concepts or [])[:8],
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
    for scode, stock_dict in all_stocks.items():
        concepts = stock_dict.get("concepts", [])
        if not concepts:
            continue
        for cname in concepts:
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

        # Top 300 stocks by momentum_20d
        sorted_stocks = sorted(stocks_map.values(), key=lambda s: abs(s.get("momentum_20d", 0) or 0), reverse=True)
        top_stocks = [dict(s) for s in sorted_stocks[:300]]

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
    if not flow:
        flow = data_enrich._fund_flow_map.get(f"sh{stock_code}", {}) or {}
    if not flow:
        flow = data_enrich._fund_flow_map.get(f"sz{stock_code}", {}) or {}
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
        "net_capital_flow": flow.get("net_main", 0) or 0,
        "net_capital_flow_pct": flow.get("net_main_pct", 0) or 0,
        "net_super_flow": flow.get("net_super", 0) or 0,
        "net_big_flow": flow.get("net_big", 0) or 0,
        "volume": spot.get("volume", 0) or 0,
        "debt_ratio": debt.get("debt_ratio", 0) if isinstance(debt, dict) else 0,
        "iv": volatility or 0,
        "pledge_ratio": pledge or 0,
        "cagr": fin.get("cagr", 0) or 0,
        "industry": industry,
        "concepts": concepts[:8],
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
                "net_capital_flow": _val(q, "net_capital_flow", 0),
                "net_capital_flow_pct": _val(q, "net_capital_flow_pct", 0),
                "net_super_flow": _val(q, "net_super_flow", 0) or data_enrich._fund_flow_map.get(stock_code, {}).get("net_super", 0) or 0,
                "net_big_flow": _val(q, "net_big_flow", 0) or data_enrich._fund_flow_map.get(stock_code, {}).get("net_big", 0) or 0,
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

    return {
        "industries": industries,
        "total_stocks": len(all_stocks),
        "total_industries": len(industries),
    }


# ════════════════════════════════════════════════════════════════════════════
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

    summary = [v for k, v in raw.items() if isinstance(v, dict) and v.get("_summary")]
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

    summary = [v for k, v in raw.items() if isinstance(v, dict) and v.get("_summary")]
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
    stocks = sorted(stocks, key=lambda s: abs(s.get("net_buy_amt") or 0), reverse=True)[:300]
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
    stocks = sorted(stocks, key=lambda s: s.get("total_amt") or 0, reverse=True)[:300]
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

    stocks = [
        {**v, "code": k}
        for k, v in raw.items()
        if isinstance(v, dict) and len(k) == 6
    ]
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
        key=lambda e: e.get("release_market_cap") or 0,
        reverse=True,
    )[:300]
    return {"events": events, "total": len(events)}


@router.get("/data-sources")
async def get_data_sources_status(request: Request):
    """所有数据源刷新状态(提供给前端检查)"""
    try:
        from pathlib import Path as _P
        from app.engine.data_enrich import (
            _NORTH_CACHE, _MARGIN_CACHE, _LHB_CACHE, _BLOCK_TRADE_CACHE,
            _HOLDER_NUM_CACHE, _EARNINGS_FORECAST_CACHE, _EARNINGS_EXPRESS_CACHE,
            _RESTRICTED_RELEASE_CACHE,
        )
        cache_dir = _NORTH_CACHE.parent
        sources = {
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
