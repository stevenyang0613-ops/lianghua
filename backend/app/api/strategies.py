"""
策略分享 API

策略市场种子数据来自：
- 方正证券《可转债投资策略系列二：经典双低与轮动策略》
- 集思录社区《可转债双低策略的改进版》《可转债多因子平衡型策略》
- 雪球《可转债的回售博弈》
- GitHub: paulhybryant/convertible_bond / tanish35/Momentum-Investing / je-suis-tm/quant-trading
- ScienceDirect / Tilburg University / Journal of Financial Economics 可转债学术文献
- BigQuant 研报库（华泰金工、广发证券、中信建投多因子系列）
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)


class StrategyType(str, Enum):
    trend = "trend"
    meanReversion = "meanReversion"
    arbitrage = "arbitrage"
    marketMaking = "marketMaking"
    quant = "quant"
    custom = "custom"


class StrategyVisibility(str, Enum):
    public = "public"
    private = "private"
    paid = "paid"


class StrategyParam(BaseModel):
    name: str
    type: str
    default: object
    description: str


class StrategyCreate(BaseModel):
    name: str
    description: str
    type: StrategyType
    code: str
    config: dict
    visibility: StrategyVisibility
    price: float = 0
    tags: List[str] = []
    params: List[StrategyParam] = []


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
    code: str = ""
    config: dict = Field(default_factory=dict)
    params: List[StrategyParam] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime


class Comment(BaseModel):
    id: str
    strategyId: str
    userId: str
    userName: str
    content: str
    createdAt: datetime


# 内存数据库
strategies_db: dict[str, Strategy] = {}
comments_db: dict[str, List[Comment]] = {}

# 可配置的数据持久化目录；默认与模块同目录，便于测试时指向 tmp_path
_PERSISTENT_DIR: Path = Path(__file__).parent
_SEED_FILE: Path = Path(__file__).with_name("strategy_market_seed.json")


def _data_file_path() -> Path:
    return _PERSISTENT_DIR / "strategy_market_data.json"


def _normalize_strategy_item(item: dict) -> dict:
    """补齐默认值并把 ISO 时间字符串转成 datetime。"""
    item.setdefault("stats", {"views": 0, "likes": 0, "subscribers": 0, "forks": 0, "comments": 0, "downloads": 0})
    item.setdefault("ratings", {"average": 0, "count": 0, "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}})
    item.setdefault("backtestResult", None)
    item.setdefault("code", "")
    item.setdefault("config", {})
    item.setdefault("params", [])

    # stats 里可能没有 downloads（旧数据兼容）
    item["stats"].setdefault("downloads", 0)

    for key in ("createdAt", "updatedAt"):
        if isinstance(item.get(key), str):
            item[key] = datetime.fromisoformat(item[key].replace("Z", "+00:00"))
    return item


def _load_seed_data() -> None:
    """从 strategy_market_seed.json 加载策略市场种子数据。"""
    if not _SEED_FILE.exists():
        logger.warning("[StrategyMarket] Seed file not found: %s", _SEED_FILE)
        return

    try:
        raw = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[StrategyMarket] Failed to load seed file, falling back to empty: %s", exc)
        return

    for item in raw.get("strategies", []):
        try:
            strategy = Strategy(**_normalize_strategy_item(item))
            strategies_db[strategy.id] = strategy
        except Exception as exc:
            logger.warning("[StrategyMarket] Skip invalid seed strategy %s: %s", item.get("id"), exc)


def _load_persistent_data() -> None:
    """从持久化文件加载，失败时保持内存现状。"""
    data_file = _data_file_path()
    if not data_file.exists():
        return

    try:
        raw = json.loads(data_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[StrategyMarket] Failed to load persistent data, using seed/empty: %s", exc)
        return

    loaded_strategies = {}
    for item in raw.get("strategies", []):
        try:
            strategy = Strategy(**_normalize_strategy_item(item))
            loaded_strategies[strategy.id] = strategy
        except Exception as exc:
            logger.warning("[StrategyMarket] Skip invalid persisted strategy %s: %s", item.get("id"), exc)

    loaded_comments = {}
    for sid, items in raw.get("comments", {}).items():
        loaded_comments[sid] = []
        for c in items:
            try:
                if isinstance(c.get("createdAt"), str):
                    c["createdAt"] = datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00"))
                loaded_comments[sid].append(Comment(**c))
            except Exception as exc:
                logger.warning("[StrategyMarket] Skip invalid comment for %s: %s", sid, exc)

    strategies_db.update(loaded_strategies)
    comments_db.update(loaded_comments)


def _persist() -> None:
    """把当前内存数据回写到 JSON 文件。"""
    data_file = _data_file_path()
    try:
        payload = {
            "version": "1.0.0",
            "strategies": [s.model_dump(mode="json") for s in strategies_db.values()],
            "comments": {
                sid: [c.model_dump(mode="json") for c in items]
                for sid, items in comments_db.items()
            },
        }
        data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("[StrategyMarket] Failed to persist data: %s", exc)


def set_data_dir(directory: str | Path) -> None:
    """切换持久化目录并重新加载数据，供测试使用。"""
    global _PERSISTENT_DIR
    _PERSISTENT_DIR = Path(directory)
    strategies_db.clear()
    comments_db.clear()
    _load_seed_data()
    _load_persistent_data()


# 模块加载时自动初始化
def _init_storage() -> None:
    strategies_db.clear()
    comments_db.clear()
    _load_seed_data()
    _load_persistent_data()
    # 第一次启动时，若持久化文件不存在，把种子数据保存一次
    if not _data_file_path().exists() and strategies_db:
        _persist()


_init_storage()


class StrategyListResponse(BaseModel):
    strategies: List[Strategy]
    total: int
    page: int
    pageSize: int


@router.get("/", response_model=StrategyListResponse)
async def list_strategies(
    query: Optional[str] = None,
    type: Optional[StrategyType] = None,
    tags: Optional[str] = None,
    sortBy: str = "newest",
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    """获取策略列表（分页）"""
    results = list(strategies_db.values())

    if query:
        q = query.lower()
        results = [s for s in results if q in s.name.lower() or q in s.description.lower() or any(q in t.lower() for t in s.tags)]
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
    elif sortBy == "returns":
        results.sort(key=lambda x: (x.backtestResult or {}).get("totalReturn", 0), reverse=True)

    total = len(results)
    start = (page - 1) * pageSize
    end = start + pageSize
    return {"strategies": results[start:end], "total": total, "page": page, "pageSize": pageSize}


@router.post("/", response_model=Strategy)
async def create_strategy(strategy: StrategyCreate):
    """创建策略"""
    strategy_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

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
        stats={"views": 0, "likes": 0, "subscribers": 0, "forks": 0, "comments": 0, "downloads": 0},
        ratings={"average": 0, "count": 0, "distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}},
        backtestResult=None,
        code=strategy.code,
        config=strategy.config,
        params=strategy.params,
        createdAt=now,
        updatedAt=now,
    )
    strategies_db[strategy_id] = new_strategy
    _persist()
    return new_strategy


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
    existing.type = strategy.type
    existing.price = strategy.price
    existing.tags = strategy.tags
    existing.code = strategy.code
    existing.config = strategy.config
    existing.params = strategy.params
    existing.updatedAt = datetime.now(timezone.utc)
    _persist()
    return existing


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str):
    """删除策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    del strategies_db[strategy_id]
    comments_db.pop(strategy_id, None)
    _persist()
    return {"message": "Strategy deleted"}


@router.post("/{strategy_id}/download")
async def download_strategy(strategy_id: str):
    """下载/收藏策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategies_db[strategy_id].stats["downloads"] = strategies_db[strategy_id].stats.get("downloads", 0) + 1
    _persist()
    return {"downloads": strategies_db[strategy_id].stats["downloads"]}


@router.post("/{strategy_id}/subscribe")
async def subscribe_strategy(strategy_id: str):
    """订阅策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategies_db[strategy_id].stats["subscribers"] += 1
    _persist()
    return {"message": "Subscribed successfully"}


@router.post("/{strategy_id}/like")
async def like_strategy(strategy_id: str):
    """点赞策略"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategies_db[strategy_id].stats["likes"] += 1
    _persist()
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
    _persist()
    return {"average": strategy.ratings["average"]}


@router.post("/{strategy_id}/comments", response_model=Comment)
async def add_comment(strategy_id: str, content: str):
    """添加评论"""
    if strategy_id not in strategies_db:
        raise HTTPException(status_code=404, detail="Strategy not found")

    comment = Comment(
        id=str(uuid.uuid4()),
        strategyId=strategy_id,
        userId="user1",
        userName="Test User",
        content=content,
        createdAt=datetime.now(timezone.utc),
    )
    if strategy_id not in comments_db:
        comments_db[strategy_id] = []
    comments_db[strategy_id].append(comment)
    strategies_db[strategy_id].stats["comments"] += 1
    _persist()
    return comment


@router.get("/{strategy_id}/comments", response_model=List[Comment])
async def get_comments(strategy_id: str, page: int = 1, pageSize: int = 20):
    """获取评论"""
    if strategy_id not in comments_db:
        return []
    start = (page - 1) * pageSize
    return comments_db[strategy_id][start : start + pageSize]
