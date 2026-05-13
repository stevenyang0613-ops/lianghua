from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class Order(BaseModel):
    id: str = ""
    code: str
    name: str = ""
    side: OrderSide
    type: OrderType = OrderType.MARKET
    price: float = 0.0
    volume: int = 0
    filled_volume: int = 0
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    reject_reason: str = ""


class Position(BaseModel):
    code: str
    name: str = ""
    volume: int = 0
    available_volume: int = 0
    cost_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    profit_pct: float = 0.0
    profit_amount: float = 0.0


class Account(BaseModel):
    total_asset: float = 100000.0
    cash: float = 100000.0
    frozen: float = 0.0
    market_value: float = 0.0
    daily_profit: float = 0.0
    total_profit: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.now)


class TradeRecord(BaseModel):
    id: str = ""
    code: str
    name: str = ""
    side: OrderSide
    price: float
    volume: int
    amount: float
    commission: float = 0.0
    traded_at: datetime = Field(default_factory=datetime.now)
