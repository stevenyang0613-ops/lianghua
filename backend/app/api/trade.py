from fastapi import APIRouter, Request, HTTPException
from app.models.trade import OrderSide, OrderType

router = APIRouter()


def _get_engine(request: Request):
    return request.app.state.trade_engine


@router.get("/account")
async def get_account(request: Request):
    engine = _get_engine(request)
    return engine.account.model_dump()


@router.get("/positions")
async def get_positions(request: Request):
    engine = _get_engine(request)
    return {"positions": [p.model_dump() for p in engine.positions]}


@router.get("/orders")
async def get_orders(request: Request):
    engine = _get_engine(request)
    return {"orders": [o.model_dump() for o in engine.orders]}


from pydantic import BaseModel


class PlaceOrderRequest(BaseModel):
    code: str
    name: str = ""
    side: OrderSide
    price: float
    volume: int
    order_type: OrderType = OrderType.MARKET


@router.post("/order")
async def place_order(req: PlaceOrderRequest, request: Request):
    engine = _get_engine(request)
    try:
        order = engine._broker.place_order(
            code=req.code, name=req.name,
            side=req.side, price=req.price,
            volume=req.volume, order_type=req.order_type
        )
        return order.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/order/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request):
    engine = _get_engine(request)
    ok = engine._broker.cancel_order(order_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Order not found or already filled")
    return {"status": "cancelled"}


@router.post("/reset")
async def reset_account(request: Request):
    engine = _get_engine(request)
    engine._broker.reset()
    return {"status": "ok"}


# Fund curve tracking
import json
from datetime import datetime
from pathlib import Path
from app.config import settings

FUND_CURVE_FILE = Path(settings.db_path).parent / "fund_curve.json"


@router.get("/fund-curve")
async def get_fund_curve(request: Request):
    if FUND_CURVE_FILE.exists():
        data = json.loads(FUND_CURVE_FILE.read_text())
        return {"points": data[-500:]}  # last 500 points
    return {"points": []}


@router.post("/fund-curve/record")
async def record_fund_curve(request: Request):
    engine = _get_engine(request)
    acct = engine.account
    point = {
        "ts": datetime.now().isoformat(),
        "total_asset": round(acct.total_asset, 2),
        "cash": round(acct.cash, 2),
        "market_value": round(acct.market_value, 2),
        "total_profit": round(acct.total_profit, 2),
    }
    points = []
    if FUND_CURVE_FILE.exists():
        points = json.loads(FUND_CURVE_FILE.read_text())
    points.append(point)
    FUND_CURVE_FILE.write_text(json.dumps(points, ensure_ascii=False, indent=2))
    return point
