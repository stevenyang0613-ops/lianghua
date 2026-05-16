from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone

router = APIRouter()

class Quote(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    changePercent: float
    volume: int
    timestamp: datetime

@router.get("/quotes", response_model=List[Quote])
async def get_quotes(request: Request, symbols: str = Query(...)):
    engine = getattr(request.app.state, "engine", None)
    storage = getattr(request.app.state, "storage", None)

    symbol_list = symbols.split(",") if symbols else []
    if not symbol_list:
        return []

    if engine:
        quotes = await engine.get_all_quotes()
        result = []
        for q in quotes:
            if q.code in symbol_list:
                result.append(Quote(
                    symbol=q.code,
                    name=q.name,
                    price=q.price,
                    change=q.change_pct,
                    changePercent=q.change_pct,
                    volume=int(q.volume) if q.volume else 0,
                    timestamp=datetime.now(timezone.utc)
                ))
        if result:
            return result

    if storage:
        rows = storage.get_latest_quotes()
        result = []
        for r in rows:
            if r.get("code") in symbol_list:
                result.append(Quote(
                    symbol=r.get("code", ""),
                    name=r.get("name", ""),
                    price=float(r.get("price", 0)),
                    change=float(r.get("change_pct", 0)),
                    changePercent=float(r.get("change_pct", 0)),
                    volume=int(r.get("volume", 0)) if r.get("volume") else 0,
                    timestamp=datetime.now(timezone.utc)
                ))
        if result:
            return result

    return []

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
