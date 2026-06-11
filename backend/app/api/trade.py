from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal
from datetime import datetime
from enum import Enum

from app.models.trade import (
    OrderSide, OrderType, OrderStatus,
    Order as EngineOrder, Position, Account as EngineAccount,
)

router = APIRouter()


def _get_engine(request: Request):
    engine = getattr(request.app.state, "trade_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="交易引擎未初始化")
    return engine


def _serialize_order(order: EngineOrder) -> dict:
    return {
        "id": order.id,
        "code": order.code,
        "name": order.name,
        "side": order.side.value if isinstance(order.side, OrderSide) else order.side,
        "type": order.type.value if isinstance(order.type, OrderType) else order.type,
        "price": order.price,
        "volume": order.volume,
        "filled_volume": order.filled_volume,
        "status": order.status.value if isinstance(order.status, OrderStatus) else order.status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "reject_reason": order.reject_reason or "",
    }


def _serialize_position(pos: Position) -> dict:
    return {
        "code": pos.code,
        "name": pos.name,
        "volume": pos.volume,
        "available_volume": pos.available_volume,
        "cost_price": pos.cost_price,
        "current_price": pos.current_price,
        "market_value": pos.market_value,
        "profit_pct": pos.profit_pct,
        "profit_amount": pos.profit_amount,
    }


def _serialize_account(acc: EngineAccount) -> dict:
    return {
        "total_asset": acc.total_asset,
        "cash": acc.cash,
        "frozen": acc.frozen,
        "market_value": acc.market_value,
        "daily_profit": acc.daily_profit,
        "total_profit": acc.total_profit,
        "updated_at": acc.updated_at.isoformat() if acc.updated_at else None,
    }


# ── 请求模型 ──

class PlaceOrderRequest(BaseModel):
    """前端默认下单格式：可转债代码 / 名称 / 价格 / 数量"""
    code: str = Field(min_length=1)
    name: str = ""
    side: Literal["buy", "sell"]
    price: float = Field(gt=0)
    volume: int = Field(gt=0)
    order_type: Literal["limit", "market"] = "limit"


class LegacyOrderRequest(BaseModel):
    """兼容老接口：accountId / symbol / quantity"""
    accountId: Optional[str] = None
    symbol: Optional[str] = None
    code: Optional[str] = None
    name: str = ""
    side: Literal["buy", "sell"]
    type: Literal["limit", "market"] = "market"
    price: float = 0.0
    quantity: Optional[int] = None
    volume: Optional[int] = None

    @field_validator("volume", "quantity")
    @classmethod
    def _validate_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("volume/quantity must be > 0")
        return v


# ── 端点 ──

@router.get("/account")
async def get_account(request: Request):
    """获取账户信息"""
    engine = _get_engine(request)
    return _serialize_account(engine.account)


@router.get("/positions")
async def get_positions(request: Request):
    """获取当前持仓列表"""
    engine = _get_engine(request)
    return {"positions": [_serialize_position(p) for p in engine.positions]}


@router.get("/orders")
async def get_orders(request: Request):
    """获取委托记录（按创建时间倒序）"""
    engine = _get_engine(request)
    orders = sorted(engine.orders, key=lambda o: o.created_at, reverse=True)
    return {"orders": [_serialize_order(o) for o in orders]}


@router.post("/order")
async def create_order(req: PlaceOrderRequest, request: Request):
    """下单（前端默认格式）"""
    engine = _get_engine(request)
    type_enum = OrderType.MARKET if req.order_type == "market" else OrderType.LIMIT
    try:
        if req.side == "buy":
            order = engine.buy(
                code=req.code, name=req.name, price=req.price,
                volume=req.volume, order_type=type_enum,
            )
        else:
            order = engine.sell(
                code=req.code, name=req.name, price=req.price,
                volume=req.volume, order_type=type_enum,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _serialize_order(order)


@router.post("/orders/legacy")
async def create_order_legacy(req: LegacyOrderRequest, request: Request):
    """兼容老格式：accountId / symbol / quantity"""
    engine = _get_engine(request)
    code = req.code or req.symbol or ""
    if not code:
        raise HTTPException(status_code=400, detail="code/symbol is required")
    volume = req.volume if req.volume is not None else (req.quantity or 0)
    type_enum = OrderType.MARKET if req.type == "market" else OrderType.LIMIT
    try:
        if req.side == "buy":
            order = engine.buy(
                code=code, name=req.name or "", price=req.price,
                volume=volume, order_type=type_enum,
            )
        else:
            order = engine.sell(
                code=code, name=req.name or "", price=req.price,
                volume=volume, order_type=type_enum,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _serialize_order(order)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request):
    """撤销委托"""
    engine = _get_engine(request)
    ok = engine.cancel_order(order_id)
    if not ok:
        raise HTTPException(status_code=404, detail="订单不存在或不可撤销")
    for o in engine.orders:
        if o.id == order_id:
            return _serialize_order(o)
    return {"status": "cancelled", "id": order_id}


@router.post("/reset")
async def reset_account(request: Request):
    """重置账户到初始状态"""
    engine = _get_engine(request)
    engine.reset()
    return {"status": "ok"}


@router.get("/fund-curve")
async def get_fund_curve(request: Request, days: int = 30):
    """获取资金曲线

    根据订单历史回放账户资产变化，返回时间序列。
    """
    engine = _get_engine(request)
    initial_cash = engine.broker.initial_cash
    orders = sorted(engine.orders, key=lambda o: o.created_at)
    filled = [o for o in orders if o.status == OrderStatus.FILLED]

    points: list[dict] = []
    if not filled:
        points.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "total_asset": initial_cash,
            "cash": initial_cash,
            "market_value": 0.0,
            "total_profit": 0.0,
        })
    else:
        cash = initial_cash
        positions: dict[str, dict] = {}
        commission_pct = engine.broker.commission_pct

        for o in filled:
            side_val = o.side.value if isinstance(o.side, OrderSide) else o.side
            if side_val == "buy":
                amount = o.price * o.volume
                commission = amount * commission_pct
                cash -= (amount + commission)
                pos = positions.get(o.code)
                if pos:
                    total_cost = pos["cost_price"] * pos["volume"] + amount
                    pos["volume"] += o.volume
                    pos["cost_price"] = round(total_cost / pos["volume"], 4)
                else:
                    positions[o.code] = {
                        "volume": o.volume, "cost_price": o.price,
                        "current_price": o.price,
                    }
            else:
                pos = positions.get(o.code)
                if not pos or pos["volume"] < o.volume:
                    continue
                amount = o.price * o.volume
                commission = amount * commission_pct
                cash += (amount - commission)
                pos["volume"] -= o.volume
                if pos["volume"] <= 0:
                    positions.pop(o.code, None)

            market_value = sum(
                p["current_price"] * p["volume"] for p in positions.values()
            )
            total_asset = cash + market_value
            points.append({
                "ts": o.created_at.isoformat(timespec="seconds") if o.created_at else datetime.now().isoformat(timespec="seconds"),
                "total_asset": round(total_asset, 2),
                "cash": round(cash, 2),
                "market_value": round(market_value, 2),
                "total_profit": round(total_asset - initial_cash, 2),
            })

    return {"points": points}
