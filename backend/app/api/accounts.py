"""
账户管理 API
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
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
    now = datetime.utcnow()
    new_account = Account(
        id=str(uuid.uuid4()),
        name=account.name,
        broker=account.broker,
        account=account.account,
        status=AccountStatus.active,
        tags=account.tags,
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
    existing.updatedAt = datetime.utcnow()
    return existing

@router.delete("/{account_id}")
async def delete_account(account_id: str):
    """删除账户"""
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")
    del accounts_db[account_id]
    return {"message": "Account deleted"}

@router.post("/{account_id}/sync")
async def sync_balance(account_id: str):
    """同步账户资金"""
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")

    # 模拟同步
    balances_db[account_id] = AccountBalance(
        accountId=account_id,
        totalAsset=100000.0 + (hash(account_id) % 100000),
        availableCash=50000.0,
        marketValue=40000.0,
        frozenCash=10000.0,
        profitToday=1000.0,
        profitTotal=5000.0,
        updatedAt=datetime.utcnow(),
    )
    return balances_db[account_id]

@router.get("/{account_id}/positions", response_model=List[Position])
async def get_positions(account_id: str):
    """获取账户持仓"""
    if account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found")

    # 模拟持仓数据
    return [
        Position(
            accountId=account_id,
            symbol="128001",
            name="测试转债",
            quantity=1000,
            availableQuantity=1000,
            costPrice=100.5,
            currentPrice=105.2,
            profit=4700.0,
            profitPercent=4.67,
        )
    ]

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
        createdAt=datetime.utcnow(),
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
