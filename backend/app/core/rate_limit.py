"""
API限流中间件

支持多种限流策略：
- IP级别限流
- 用户级别限流
- 端点级别限流
- 滑动窗口算法
"""

import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from collections import defaultdict
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """限流配置"""
    requests_per_second: float = 10.0
    requests_per_minute: int = 100
    requests_per_hour: int = 1000
    burst_size: int = 20  # 突发请求容量
    enabled: bool = True


@dataclass
class ClientState:
    """客户端状态"""
    tokens: float = 0.0  # 令牌桶当前令牌数
    last_update: float = 0.0  # 上次更新时间
    minute_count: int = 0  # 分钟计数
    minute_reset: float = 0.0  # 分钟重置时间
    hour_count: int = 0  # 小时计数
    hour_reset: float = 0.0  # 小时重置时间
    blocked_until: float = 0.0  # 阻塞截止时间


class TokenBucket:
    """令牌桶算法实现"""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # 每秒生成令牌数
        self.capacity = capacity  # 桶容量
        self._buckets: Dict[str, ClientState] = defaultdict(ClientState)

    def _init_client(self, client_id: str) -> ClientState:
        """初始化客户端状态"""
        now = time.time()
        state = self._buckets[client_id]
        if state.last_update == 0:
            state.tokens = self.capacity
            state.last_update = now
            state.minute_reset = now + 60
            state.hour_reset = now + 3600
        return state

    def consume(self, client_id: str, tokens: int = 1) -> bool:
        """尝试消费令牌"""
        now = time.time()
        state = self._init_client(client_id)

        # 检查是否被阻塞
        if now < state.blocked_until:
            return False

        # 更新令牌
        elapsed = now - state.last_update
        state.tokens = min(
            self.capacity,
            state.tokens + elapsed * self.rate
        )
        state.last_update = now

        # 更新分钟/小时计数
        if now >= state.minute_reset:
            state.minute_count = 0
            state.minute_reset = now + 60
        if now >= state.hour_reset:
            state.hour_count = 0
            state.hour_reset = now + 3600

        # 检查限流
        if state.tokens < tokens:
            return False

        if state.minute_count >= 100:  # 每分钟限制
            return False

        if state.hour_count >= 1000:  # 每小时限制
            return False

        # 消费令牌
        state.tokens -= tokens
        state.minute_count += 1
        state.hour_count += 1

        return True

    def get_wait_time(self, client_id: str) -> float:
        """获取需要等待的时间"""
        state = self._buckets.get(client_id)
        if not state:
            return 0.0

        if state.blocked_until > time.time():
            return state.blocked_until - time.time()

        needed = 1 - state.tokens
        if needed <= 0:
            return 0.0

        return needed / self.rate


class RateLimiter:
    """API限流器"""

    def __init__(self, config: RateLimitConfig = None):
        self.config = config or RateLimitConfig()
        self._bucket = TokenBucket(
            rate=self.config.requests_per_second,
            capacity=self.config.burst_size,
        )
        self._whitelist: set = set()
        self._endpoint_limits: Dict[str, RateLimitConfig] = {}

    def add_to_whitelist(self, client_id: str) -> None:
        """添加到白名单"""
        self._whitelist.add(client_id)

    def remove_from_whitelist(self, client_id: str) -> None:
        """从白名单移除"""
        self._whitelist.discard(client_id)

    def set_endpoint_limit(self, path: str, config: RateLimitConfig) -> None:
        """设置特定端点的限流配置"""
        self._endpoint_limits[path] = config

    def _get_client_id(self, request: Request) -> str:
        """获取客户端标识"""
        # 优先使用用户ID
        user = getattr(request.state, 'user', None)
        if user and hasattr(user, 'user_id'):
            return f"user:{user.user_id}"

        # 其次使用IP地址
        forwarded = request.headers.get('X-Forwarded-For')
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"

        client_host = request.client.host if request.client else 'unknown'
        return f"ip:{client_host}"

    def check(self, request: Request) -> bool:
        """检查是否允许请求"""
        if not self.config.enabled:
            return True

        client_id = self._get_client_id(request)

        # 白名单检查
        if client_id in self._whitelist:
            return True

        # 端点特定限流
        path = request.url.path
        if path in self._endpoint_limits:
            return self._check_endpoint(path, client_id)

        return self._bucket.consume(client_id)

    def _check_endpoint(self, path: str, client_id: str) -> bool:
        """检查端点特定限流"""
        config = self._endpoint_limits.get(path)
        if not config:
            return True

        # 使用端点特定的桶（可以用独立的前缀区分）
        endpoint_client_id = f"{path}:{client_id}"
        bucket = TokenBucket(
            rate=config.requests_per_second,
            capacity=config.burst_size,
        )
        return bucket.consume(endpoint_client_id)

    def get_retry_after(self, request: Request) -> int:
        """获取重试等待时间（秒）"""
        client_id = self._get_client_id(request)
        return max(1, int(self._bucket.get_wait_time(client_id)))


# 全局限流器实例
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """获取全局限流器"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def rate_limit_middleware(request: Request, call_next):
    """限流中间件"""
    limiter = get_rate_limiter()

    # 跳过健康检查等端点
    if request.url.path in ['/api/v1/health', '/', '/docs', '/openapi.json']:
        return await call_next(request)

    if not limiter.check(request):
        retry_after = limiter.get_retry_after(request)
        logger.warning(
            f"Rate limit exceeded for {request.client.host if request.client else 'unknown'} "
            f"on {request.url.path}"
        )
        return JSONResponse(
            status_code=429,
            content={
                'detail': 'Too many requests',
                'retry_after': retry_after,
            },
            headers={'Retry-After': str(retry_after)},
        )

    return await call_next(request)


# 装饰器形式的限流
def rate_limit(
    requests_per_second: float = 10.0,
    burst_size: int = 20,
):
    """限流装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # 查找request参数
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if request:
                client_id = f"endpoint:{request.url.path}:{request.client.host if request.client else 'unknown'}"
                bucket = TokenBucket(rate=requests_per_second, capacity=burst_size)
                if not bucket.consume(client_id):
                    raise HTTPException(
                        status_code=429,
                        detail='Too many requests',
                        headers={'Retry-After': '1'},
                    )

            return await func(*args, **kwargs)
        return wrapper
    return decorator
