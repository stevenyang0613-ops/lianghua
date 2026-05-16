from fastapi import APIRouter, Query
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
async def get_quotes(symbols: str = Query(...)):
    symbol_list = symbols.split(",")
    return [Quote(
        symbol=s, name=f"转债{s}", price=100.0,
        change=1.5, changePercent=1.5, volume=1000000,
        timestamp=datetime.now(timezone.utc)
    ) for s in symbol_list]

@router.get("/kline")
async def get_kline(symbol: str, period: str = "1d", limit: int = 100):
    from datetime import timedelta
    import random
    klines = []
    base = 100.0
    for i in range(limit):
        t = datetime.now(timezone.utc) - timedelta(days=limit - i - 1)
        o = base + random.uniform(-5, 5)
        c = o + random.uniform(-2, 2)
        h = max(o, c) + random.uniform(0, 2)
        l = min(o, c) - random.uniform(0, 2)
        klines.append({"time": t.isoformat(), "open": round(o, 2), "high": round(h, 2),
                       "low": round(l, 2), "close": round(c, 2), "volume": random.randint(100000, 1000000)})
        base = c
    return klines

@router.get("/search")
async def search(keyword: str, limit: int = 20):
    return [{"code": f"128{i:03d}", "name": f"转债{i}"} for i in range(min(limit, 10))]
