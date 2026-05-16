"""
策略分享 API
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from enum import Enum

router = APIRouter()

class StrategyType(str, Enum):
    trend = "trend"
    meanReversion = "meanReversion"
    arbitrage = "arbitrage"
    marketMaking = "marketMaking"
    custom = "custom"

class StrategyVisibility(str, Enum):
    public = "public"
    private = "private"
    paid = "paid"

class StrategyCreate(BaseModel):
    name: str
    description: str
    type: StrategyType
    code: str
    config: dict
    visibility: StrategyVisibility
    price: float = 0
    tags: List[str] = []

class Strategy(BaseModel):
    id: str
    name: str
    description: str
    type: StrategyType
    visibility: StrategyVisibility
    author: dict
    version: str
    status: str
    price: float
    tags: List[str]
    stats: dict
    ratings: dict
    backtestResult: Optional[dict]
    createdAt: datetime
    updatedAt: datetime

class Comment(BaseModel):
    id: str
    strategyId: str
    userId: str
    userName: str
    content: str
    createdAt: datetime

# 临时存储
strategies_db = {}
comments_db = {}

@router.get("/", response_model=List[Strategy])
async def list_strategies(
    query: Optional[str] = None,
    type: Optional[StrategyType] = None,
    tags: Optional[str] = None,
    sortBy: str = "newest",
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100)
):
    """获取策略列表"""
    results = list(strategies_db.values())

    if query:
        results = [s for s in results if query.lower() in s.name.lower() or query.lower() in s.description.lower()]
    if type:
        results = [s for s in results if s.type == type]
    if tags:
        tag_list = tags.split(",")
        results = [s for s in results if any(t in s.tags for t in tag_list)]

    # 排序
    if sortBy == "newest":
        results.sort(key=lambda x: x.createdAt, reverse=True)
    elif sortBy == "rating":
        results.sort(key=lambda x: x.ratings.get("average", 0), reverse=True)
    elif sortBy == "popularity":
        results.sort(key=lambda x: x.stats.get("subscribers", 0), reverse=True)

    start = (page - 1) * pageSize
    return results[start:start + pageSize]

@router.post("/", response_model=Strategy)
async def create_strategy(strategy: StrategyCreate):
    """创建策略"""
    import uuid
    strategy_id = str(uuid.uuid4())
    now = datetime.utcnow()

    new_strategy = Strategy(
        id=strategy_id,
        name=strategy.name,
        description=strategy.description,
        type=strategy.type,
        visibility=strategy.visibility,
        author={"id": "user1", "name": "Test User"},
        version="1.0.0",
        status="published",
        price=strategy.price,
        tags=strategy.tags,
        stats={"views": 0, "likes": 0, "subscribers": 0, "forks": 0, "comments": 0},
        ratings={"average": 0, "count": 0, "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}},
        backtestResult=None,
        createdAt=now,
        updatedAt=now,
    )
    strategies_db[strategy_id] = new_strategy
    return new_strategy

@router.get("/{strategy_id}", response_model=Strategy)
async def get_strategy(strategy_id: str):
    """获取策略详情"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategies_db[strategy_id]

@router.put("/{strategy_id}", response_model=Strategy)
async def update_strategy(strategy_id: str, strategy: StrategyCreate):
    """更新策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")

    existing = strategies_db[strategy_id]
    existing.name = strategy.name
    existing.description = strategy.description
    existing.updatedAt = datetime.utcnow()
    return existing

@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str):
    """删除策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    del strategies_db[strategy_id]
    return {"message": "Strategy deleted"}

@router.post("/{strategy_id}/subscribe")
async def subscribe_strategy(strategy_id: str):
    """订阅策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategies_db[strategy_id].stats["subscribers"] += 1
    return {"message": "Subscribed successfully"}

@router.post("/{strategy_id}/like")
async def like_strategy(strategy_id: str):
    """点赞策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategies_db[strategy_id].stats["likes"] += 1
    return {"likes": strategies_db[strategy_id].stats["likes"]}

@router.post("/{strategy_id}/rate")
async def rate_strategy(strategy_id: str, rating: int = Query(..., ge=1, le=5), review: Optional[str] = None):
    """评分策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")

    strategy = strategies_db[strategy_id]
    strategy.ratings["distribution"][str(rating)] = strategy.ratings["distribution"].get(str(rating), 0) + 1
    strategy.ratings["count"] += 1
    # 重新计算平均分
    total = sum(int(k) * v for k, v in strategy.ratings["distribution"].items())
    strategy.ratings["average"] = total / strategy.ratings["count"]
    return {"average": strategy.ratings["average"]}

@router.post("/{strategy_id}/comments", response_model=Comment)
async def add_comment(strategy_id: str, content: str):
    """添加评论"""
    import uuid
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")

    comment = Comment(
        id=str(uuid.uuid4()),
        strategyId=strategy_id,
        userId="user1",
        userName="Test User",
        content=content,
        createdAt=datetime.utcnow(),
    )
    if strategy_id not in comments_db:
        comments_db[strategy_id] = []
    comments_db[strategy_id].append(comment)
    strategies_db[strategy_id].stats["comments"] += 1
    return comment

@router.get("/{strategy_id}/comments", response_model=List[Comment])
async def get_comments(strategy_id: str, page: int = 1, pageSize: int = 20):
    """获取评论"""
    if strategy_id not in comments_db:
        return []
    start = (page - 1) * pageSize
    return comments_db[strategy_id][start:start + pageSize]

@router.get("/recommended", response_model=List[Strategy])
async def get_recommended(limit: int = 10):
    """获取推荐策略"""
    results = list(strategies_db.values())
    results.sort(key=lambda x: x.ratings.get("average", 0), reverse=True)
    return results[:limit]

@router.get("/tags")
async def get_popular_tags(limit: int = 20):
    """获取热门标签"""
    from collections import Counter
    tags = Counter()
    for strategy in strategies_db.values():
        for tag in strategy.tags:
            tags[tag] += 1
    return [{"tag": tag, "count": count} for tag, count in tags.most_common(limit)]
