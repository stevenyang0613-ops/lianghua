"""
数据库持久化配置
支持 PostgreSQL / MySQL / SQLite
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, Text, JSON
from datetime import datetime, timezone
from typing import Optional
import os

# 数据库 URL 配置
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite")

if DATABASE_TYPE == "postgresql":
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/lianghua"
    )
elif DATABASE_TYPE == "mysql":
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "mysql+aiomysql://root:root@localhost:3306/lianghua"
    )
else:
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./lianghua.db"
    )

# 创建引擎
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("DEBUG", "false").lower() == "true",
    future=True,
    pool_size=20 if DATABASE_TYPE != "sqlite" else None,
    max_overflow=10 if DATABASE_TYPE != "sqlite" else None,
    pool_pre_ping=True if DATABASE_TYPE != "sqlite" else False,
)

# 会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# 基类
Base = declarative_base()


# ==================== 数据模型 ====================

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(50))
    avatar = Column(String(500))
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class Strategy(Base):
    """策略表"""
    __tablename__ = "strategies"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text)
    type = Column(String(20), index=True)
    code = Column(Text, nullable=False)
    config = Column(JSON)
    visibility = Column(String(20), default="private")
    price = Column(Float, default=0)
    tags = Column(JSON)
    author_id = Column(String(36), index=True)
    version = Column(String(20), default="1.0.0")
    status = Column(String(20), default="draft")
    stats = Column(JSON)
    ratings = Column(JSON)
    backtest_result = Column(JSON)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    published_at = Column(DateTime)


class StrategySubscription(Base):
    """策略订阅表"""
    __tablename__ = "strategy_subscriptions"

    id = Column(String(36), primary_key=True)
    strategy_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, index=True)
    status = Column(String(20), default="active")
    settings = Column(JSON)
    subscribed_at = Column(DateTime, default=datetime.now(timezone.utc))
    expires_at = Column(DateTime)


class StrategyComment(Base):
    """策略评论表"""
    __tablename__ = "strategy_comments"

    id = Column(String(36), primary_key=True)
    strategy_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False)
    content = Column(Text, nullable=False)
    parent_id = Column(String(36))
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime)


class Account(Base):
    """账户表"""
    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    broker = Column(String(20), nullable=False)
    account_number = Column(String(50), nullable=False)
    api_key = Column(String(255))
    api_secret = Column(String(255))
    trading_password = Column(String(255))
    status = Column(String(20), default="active")
    tags = Column(JSON)
    risk_config = Column(JSON)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class AccountBalance(Base):
    """账户资金表"""
    __tablename__ = "account_balances"

    id = Column(String(36), primary_key=True)
    account_id = Column(String(36), nullable=False, index=True)
    total_asset = Column(Float, default=0)
    available_cash = Column(Float, default=0)
    market_value = Column(Float, default=0)
    frozen_cash = Column(Float, default=0)
    margin_used = Column(Float, default=0)
    margin_available = Column(Float, default=0)
    profit_today = Column(Float, default=0)
    profit_total = Column(Float, default=0)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class Position(Base):
    """持仓表"""
    __tablename__ = "positions"

    id = Column(String(36), primary_key=True)
    account_id = Column(String(36), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(50))
    quantity = Column(Integer, default=0)
    available_quantity = Column(Integer, default=0)
    cost_price = Column(Float, default=0)
    current_price = Column(Float, default=0)
    market_value = Column(Float, default=0)
    profit = Column(Float, default=0)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class Order(Base):
    """订单表"""
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True)
    account_id = Column(String(36), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    order_type = Column(String(10), nullable=False)
    price = Column(Float, default=0)
    quantity = Column(Integer, nullable=False)
    filled_quantity = Column(Integer, default=0)
    status = Column(String(20), default="pending", index=True)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class AlertRule(Base):
    """告警规则表"""
    __tablename__ = "alert_rules"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    level = Column(String(20), nullable=False)
    enabled = Column(Boolean, default=True)
    condition = Column(JSON, nullable=False)
    channels = Column(JSON)
    suppress_duration = Column(Integer, default=300)
    recipients = Column(JSON)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class AlertEvent(Base):
    """告警事件表"""
    __tablename__ = "alert_events"

    id = Column(String(36), primary_key=True)
    rule_id = Column(String(36), nullable=False, index=True)
    rule_name = Column(String(100))
    level = Column(String(20), nullable=False)
    message = Column(Text)
    details = Column(JSON)
    status = Column(String(20), default="firing", index=True)
    fired_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)
    resolved_at = Column(DateTime)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(String(36))


class LogEntry(Base):
    """日志表"""
    __tablename__ = "logs"

    id = Column(String(36), primary_key=True)
    level = Column(String(10), nullable=False, index=True)
    category = Column(String(50), index=True)
    message = Column(Text, nullable=False)
    user_id = Column(String(36), index=True)
    session_id = Column(String(50))
    context = Column(JSON)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)


class CacheEntry(Base):
    """缓存表"""
    __tablename__ = "cache"

    key = Column(String(255), primary_key=True)
    value = Column(Text)
    expiry = Column(DateTime, index=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


# 初始化数据库
async def init_db():
    """初始化数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# 获取数据库会话
async def get_db():
    """获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
