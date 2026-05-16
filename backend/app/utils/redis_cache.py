"""
Redis 缓存服务
"""

import redis.asyncio as redis
import json
from typing import Optional, Any
from datetime import timedelta
import os

# Redis 配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class RedisCache:
    """Redis 缓存管理器"""

    def __init__(self):
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        """连接 Redis"""
        if self.client is None:
            self.client = redis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )

    async def disconnect(self):
        """断开连接"""
        if self.client:
            await self.client.close()
            self.client = None

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if not self.client:
            await self.connect()

        value = await self.client.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """设置缓存"""
        if not self.client:
            await self.connect()

        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)

        if ttl:
            return await self.client.setex(key, ttl, value)
        return await self.client.set(key, value)

    async def delete(self, key: str) -> int:
        """删除缓存"""
        if not self.client:
            await self.connect()
        return await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """检查是否存在"""
        if not self.client:
            await self.connect()
        return await self.client.exists(key) > 0

    async def expire(self, key: str, seconds: int) -> bool:
        """设置过期时间"""
        if not self.client:
            await self.connect()
        return await self.client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """获取剩余过期时间"""
        if not self.client:
            await self.connect()
        return await self.client.ttl(key)

    async def incr(self, key: str, amount: int = 1) -> int:
        """递增"""
        if not self.client:
            await self.connect()
        return await self.client.incrby(key, amount)

    async def decr(self, key: str, amount: int = 1) -> int:
        """递减"""
        if not self.client:
            await self.connect()
        return await self.client.decrby(key, amount)

    async def hset(self, name: str, key: str, value: Any) -> int:
        """设置哈希字段"""
        if not self.client:
            await self.connect()

        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)

        return await self.client.hset(name, key, value)

    async def hget(self, name: str, key: str) -> Optional[Any]:
        """获取哈希字段"""
        if not self.client:
            await self.connect()

        value = await self.client.hget(name, key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    async def hgetall(self, name: str) -> dict:
        """获取所有哈希字段"""
        if not self.client:
            await self.connect()
        return await self.client.hgetall(name)

    async def hdel(self, name: str, *keys: str) -> int:
        """删除哈希字段"""
        if not self.client:
            await self.connect()
        return await self.client.hdel(name, *keys)

    async def lpush(self, key: str, *values: Any) -> int:
        """列表左侧插入"""
        if not self.client:
            await self.connect()

        serialized = []
        for v in values:
            if isinstance(v, (dict, list)):
                serialized.append(json.dumps(v, ensure_ascii=False))
            else:
                serialized.append(str(v))

        return await self.client.lpush(key, *serialized)

    async def rpush(self, key: str, *values: Any) -> int:
        """列表右侧插入"""
        if not self.client:
            await self.connect()

        serialized = []
        for v in values:
            if isinstance(v, (dict, list)):
                serialized.append(json.dumps(v, ensure_ascii=False))
            else:
                serialized.append(str(v))

        return await self.client.rpush(key, *serialized)

    async def lpop(self, key: str) -> Optional[Any]:
        """列表左侧弹出"""
        if not self.client:
            await self.connect()

        value = await self.client.lpop(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    async def lrange(self, key: str, start: int, end: int) -> list:
        """获取列表范围"""
        if not self.client:
            await self.connect()

        values = await self.client.lrange(key, start, end)
        result = []
        for v in values:
            try:
                result.append(json.loads(v))
            except json.JSONDecodeError:
                result.append(v)
        return result

    async def publish(self, channel: str, message: Any) -> int:
        """发布消息"""
        if not self.client:
            await self.connect()

        if isinstance(message, (dict, list)):
            message = json.dumps(message, ensure_ascii=False)

        return await self.client.publish(channel, message)

    async def subscribe(self, *channels: str):
        """订阅频道"""
        if not self.client:
            await self.connect()

        pubsub = self.client.pubsub()
        await pubsub.subscribe(*channels)
        return pubsub

    async def acquire_lock(
        self,
        lock_name: str,
        timeout: int = 10,
        blocking_timeout: int = 5
    ) -> bool:
        """获取分布式锁"""
        if not self.client:
            await self.connect()

        import time
        import uuid
        identifier = str(uuid.uuid4())
        lock_key = f"lock:{lock_name}"

        end_time = time.time() + blocking_timeout

        while time.time() < end_time:
            if await self.client.set(lock_key, identifier, nx=True, ex=timeout):
                return True
            time.sleep(0.001)

        return False

    async def release_lock(self, lock_name: str) -> bool:
        """释放分布式锁"""
        if not self.client:
            await self.connect()

        lock_key = f"lock:{lock_name}"
        await self.client.delete(lock_key)
        return True

    async def clear_pattern(self, pattern: str) -> int:
        """清除匹配的缓存"""
        if not self.client:
            await self.connect()

        keys = []
        async for key in self.client.scan_iter(match=pattern):
            keys.append(key)

        if keys:
            return await self.client.delete(*keys)
        return 0

    async def get_stats(self) -> dict:
        """获取 Redis 统计信息"""
        if not self.client:
            await self.connect()

        info = await self.client.info()
        return {
            "connected_clients": info.get("connected_clients"),
            "used_memory_human": info.get("used_memory_human"),
            "total_connections_received": info.get("total_connections_received"),
            "total_commands_processed": info.get("total_commands_processed"),
            "keyspace_hits": info.get("keyspace_hits"),
            "keyspace_misses": info.get("keyspace_misses"),
        }


# 导出单例
redis_cache = RedisCache()


# 缓存装饰器
def cache_result(ttl: int = 300, key_prefix: str = ""):
    """缓存结果装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            import hashlib
            cache_key = f"{key_prefix}:{func.__name__}:{hashlib.md5(str((args, kwargs)).encode()).hexdigest()}"

            # 尝试从缓存获取
            cached = await redis_cache.get(cache_key)
            if cached is not None:
                return cached

            # 执行函数
            result = await func(*args, **kwargs)

            # 存入缓存
            await redis_cache.set(cache_key, result, ttl)

            return result
        return wrapper
    return decorator


# 限流装饰器
def rate_limit(max_requests: int = 100, window: int = 60, key_prefix: str = "rate_limit"):
    """限流装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # 获取用户标识（假设第一个参数是 request）
            user_id = "anonymous"
            if args and hasattr(args[0], "headers"):
                user_id = args[0].headers.get("X-User-ID", "anonymous")

            rate_key = f"{key_prefix}:{user_id}:{func.__name__}"

            # 检查当前请求数
            current = await redis_cache.get(rate_key)
            if current is None:
                await redis_cache.set(rate_key, 1, window)
            elif int(current) >= max_requests:
                raise Exception(f"Rate limit exceeded: {max_requests} requests per {window} seconds")
            else:
                await redis_cache.incr(rate_key)

            return await func(*args, **kwargs)
        return wrapper
    return decorator


export = redis_cache
