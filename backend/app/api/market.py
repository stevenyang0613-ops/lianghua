from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, date

router = APIRouter()


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
            "call_status": str(r.get("call_status", "") or ""),
            "last_trade_date": _iso(r.get("last_trade_date")),
            "maturity_date": _iso(r.get("maturity_date")),
            "redemption_price": float(r.get("redemption_price", 0) or 0.0),
            "rating": str(r.get("rating", "") or "") or None,
            "industry": r.get("industry"),
            "roe": r.get("roe"),
            "gpm": r.get("gpm"),
            "cagr": r.get("cagr"),
            "debt_ratio": r.get("debt_ratio"),
            "current_ratio": r.get("current_ratio"),
            "pe": r.get("pe"),
            "pb": r.get("pb"),
            "iv": r.get("iv"),
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
    engine = getattr(request.app.state, "engine", None)

    if engine and symbol:
        quote = await engine.get_quote(symbol)
        if quote and quote.price > 0:
            return [{
                "time": datetime.now(timezone.utc).isoformat(),
                "open": quote.price,
                "high": quote.price * 1.02,
                "low": quote.price * 0.98,
                "close": quote.price,
                "volume": int(quote.volume) if quote.volume else 0
            }]

    storage = getattr(request.app.state, "storage", None)
    if storage and symbol:
        if period == "1d":
            klines = storage.get_daily_history(symbol, limit)
        else:
            klines = storage.get_quote_history(symbol, limit)
        if klines:
            return [{
                "time": k.get("snapshot_date") or k.get("timestamp", ""),
                "open": float(k.get("price", 0)),
                "high": float(k.get("price", 0)) * 1.01,
                "low": float(k.get("price", 0)) * 0.99,
                "close": float(k.get("price", 0)),
                "volume": int(k.get("volume", 0)) if k.get("volume") else 0
            } for k in klines]

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
