"""
账户管理 API
"""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from enum import Enum

router = APIRouter()

class BrokerType(str, Enum):
    eastmoney = "eastmoney"
    huatai = "huatai"
    cicc = "cicc"
    guotaijunan = "guotaijunan"
    zhongxin = "zhongxin"
    custom = "custom"

class AccountStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    error = "error"
    maintenance = "maintenance"

class AccountCreate(BaseModel):
    name: str
    broker: BrokerType
    account: str
    apiKey: Optional[str] = None
    apiSecret: Optional[str] = None
    tradingPassword: Optional[str] = None
    tags: List[str] = []

class Account(BaseModel):
    id: str
    name: str
    broker: BrokerType
    account: str
    status: AccountStatus
    tags: List[str]
    cash: float = 0.0
    createdAt: datetime
    updatedAt: datetime

class AccountBalance(BaseModel):
    accountId: str
    totalAsset: float
    availableCash: float
    marketValue: float
    frozenCash: float
    profitToday: float
    profitTotal: float
    updatedAt: datetime

class Position(BaseModel):
    accountId: str
    symbol: str
    name: str
    quantity: int
    availableQuantity: int
    costPrice: float
    currentPrice: float
    profit: float
    profitPercent: float

class AccountGroup(BaseModel):
    id: str
    name: str
    accountIds: List[str]
    riskConfig: dict
    allocationStrategy: str
    createdAt: datetime

# 临时存储
accounts_db = {}
balances_db = {}
positions_db = {}
groups_db = {}

@router.get("/", response_model=List[Account])
async def get_accounts():
    """获取所有账户"""
    return list(accounts_db.values())

@router.post("/", response_model=Account)
async def add_account(account: AccountCreate):
    """添加账户"""
    import uuid
    now = datetime.now(timezone.utc)
    new_account = Account(
        id=str(uuid.uuid4()),
        name=account.name,
        broker=account.broker,
        account=account.account,
        status=AccountStatus.active,
        tags=account.tags,
        cash=0.0,
        createdAt=now,
        updatedAt=now,
    )
    accounts_db[new_account.id] = new_account
    return new_account

@router.put("/{account_id}", response_model=Account)
async def update_account(account_id: str, account: AccountCreate):
    """更新账户"""
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")

    existing = accounts_db[account_id]
    existing.name = account.name
    existing.updatedAt = datetime.now(timezone.utc)
    return existing

@router.delete("/{account_id}")
async def delete_account(account_id: str):
    """删除账户"""
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")
    del accounts_db[account_id]
    return {"message": "Account deleted"}

@router.post("/{account_id}/sync")
async def sync_balance(account_id: str, request: Request = None):
    """同步账户资金

    若账户有真实持仓列表（positions 字段），从 market_engine 拉取最新行情重算市值与盈亏；
    否则保持原始资金不变。
    """
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")

    account = accounts_db[account_id]
    positions = positions_db.get(account_id, [])

    engine = None
    if request is not None:
        engine = getattr(request.app.state, "engine", None)

    market_value = 0.0
    profit_today = 0.0
    profit_total = 0.0

    if engine and positions:
        for pos in positions:
            try:
                symbol = pos.symbol
                q = await engine.get_quote(symbol) if hasattr(engine, 'get_quote') else None
                if q is not None:
                    current_price = float(getattr(q, 'price', 0) or 0)
                    cost_price = float(pos.costPrice or 0)
                    qty = float(pos.quantity or 0)
                    market_value += current_price * qty
                    change_pct = float(getattr(q, 'change_pct', 0) or 0)
                    if change_pct != 0:
                        prev_price = current_price / (1 + change_pct / 100)
                        profit_today += (current_price - prev_price) * qty
                    profit_total += (current_price - cost_price) * qty
            except Exception:
                continue
    else:
        market_value = sum(
            float(p.costPrice or 0) * float(p.quantity or 0) for p in positions
        )

    available_cash = float(account.cash or 0) - market_value * 0.1
    balances_db[account_id] = AccountBalance(
        accountId=account_id,
        totalAsset=round(float(account.cash or 0) + market_value, 2),
        availableCash=round(max(0, available_cash), 2),
        marketValue=round(market_value, 2),
        frozenCash=round(market_value * 0.1, 2),
        profitToday=round(profit_today, 2),
        profitTotal=round(profit_total, 2),
        updatedAt=datetime.now(timezone.utc),
    )
    return balances_db[account_id]

@router.get("/{account_id}/positions", response_model=List[Position])
async def get_positions(account_id: str):
    """获取账户持仓"""
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")

    return list(positions_db.get(account_id, []))


@router.post("/{account_id}/positions", response_model=Position)
async def add_position(account_id: str, position: Position):
    """添加账户持仓（手动录入或券商同步后入库）"""
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")
    position.accountId = account_id
    if position.profitPercent is None and position.costPrice:
        position.profitPercent = (position.currentPrice - position.costPrice) / position.costPrice * 100
    positions_db.setdefault(account_id, []).append(position)
    return position

@router.post("/groups", response_model=AccountGroup)
async def create_group(name: str, accountIds: List[str], riskConfig: dict, allocationStrategy: str):
    """创建账户组"""
    import uuid
    group = AccountGroup(
        id=str(uuid.uuid4()),
        name=name,
        accountIds=accountIds,
        riskConfig=riskConfig,
        allocationStrategy=allocationStrategy,
        createdAt=datetime.now(timezone.utc),
    )
    groups_db[group.id] = group
    return group

@router.get("/groups", response_model=List[AccountGroup])
async def get_groups():
    """获取账户组"""
    return list(groups_db.values())

@router.delete("/groups/{group_id}")
async def delete_group(group_id: str):
    """删除账户组"""
    if group_id not in groups_db:
        raise HTTPException(status_code=404, detail="Group not found")
    del groups_db[group_id]
    return {"message": "Group deleted"}
