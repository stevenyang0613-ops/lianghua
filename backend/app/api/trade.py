from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from enum import Enum

router = APIRouter()

class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"

class OrderType(str, Enum):
    limit = "limit"
    market = "market"

class OrderStatus(str, Enum):
    pending = "pending"
    filled = "filled"
    cancelled = "cancelled"

class OrderCreate(BaseModel):
    accountId: str
    symbol: str
    side: OrderSide
    type: OrderType
    price: Optional[float] = None
    quantity: int

class Order(BaseModel):
    id: str
    accountId: str
    symbol: str
    side: OrderSide
    type: OrderType
    price: float
    quantity: int
    filledQuantity: int
    status: OrderStatus
    createdAt: datetime

orders_db = {}

@router.post("/order", response_model=Order)
async def create_order(order: OrderCreate):
    import uuid
    new_order = Order(
        id=str(uuid.uuid4()), accountId=order.accountId, symbol=order.symbol,
        side=order.side, type=order.type, price=order.price or 0, quantity=order.quantity,
        filledQuantity=0, status=OrderStatus.pending, createdAt=datetime.now(timezone.utc)
    )
    orders_db[new_order.id] = new_order
    return new_order

@router.get("/orders", response_model=List[Order])
async def get_orders(accountId: Optional[str] = None, page: int = 1, pageSize: int = 50):
    results = list(orders_db.values())
    if accountId:
        results = [o for o in results if o.accountId == accountId]
    start = (page - 1) * pageSize
    return results[start:start + pageSize]

@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str):
    if order_id not in orders_db:
        raise HTTPException(status_code=404, detail="Not found")
    orders_db[order_id].status = OrderStatus.cancelled
    return orders_db[order_id]
