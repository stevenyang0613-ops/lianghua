"""多层缓存管理器"""
import json
import hashlib
import asyncio
from typing import Optional, Any, Dict, List
from functools import wraps
from collections import OrderedDict
import time
import logging
logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class MemoryCache:
    """内存缓存（LRU淘汰）"""
    
    def __init__(self, max_size: int = 1000, max_memory_mb: int = 256):
        self.max_size = max_size
        self.max_memory = max_memory_mb * 1024 * 1024
        self.cache: OrderedDict = OrderedDict()
        self.current_memory = 0
        self.stats = {"hits": 0, "misses": 0}
    
    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            self.cache.move_to_end(key)
            self.stats["hits"] += 1
            return self.cache[key]["value"]
        self.stats["misses"] += 1
        return None
    
    def set(self, key: str, value: Any, ttl: int = None):
        size = len(json.dumps(value)) if isinstance(value, (dict, list)) else len(str(value))
        
        # 淘汰旧数据
        while (len(self.cache) >= self.max_size or 
               self.current_memory + size > self.max_memory):
            if not self.cache:
                break
            old_key, old_value = self.cache.popitem(last=False)
            self.current_memory -= old_value["size"]
        
        self.cache[key] = {
            "value": value,
            "size": size,
            "created_at": time.time(),
            "ttl": ttl
        }
        self.current_memory += size
    
    def delete(self, key: str):
        if key in self.cache:
            self.current_memory -= self.cache[key]["size"]
            del self.cache[key]
    
    def clear(self):
        self.cache.clear()
        self.current_memory = 0
    
    def get_stats(self) -> Dict:
        return {
            **self.stats,
            "size": len(self.cache),
            "memory_bytes": self.current_memory
        }


class CacheManager:
    """多层缓存管理器"""
    
    def __init__(self, redis_url: str = None):
        self.memory_cache = MemoryCache()
        self.redis_client = None
        self._connected = False
        
        if redis_url and REDIS_AVAILABLE:
            self.redis_client = aioredis.from_url(redis_url, decode_responses=True)
            self._connected = True
    
    async def get(self, key: str) -> Optional[Any]:
        # L1: 内存缓存
        value = self.memory_cache.get(key)
        if value is not None:
            return value
        
        # L2: Redis缓存
        if self.redis_client:
            try:
                value = await self.redis_client.get(key)
                if value:
                    parsed = json.loads(value)
                    # 回写内存缓存
                    self.memory_cache.set(key, parsed)
                    return parsed
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
        
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        # 写入内存
        self.memory_cache.set(key, value, ttl)
        
        # 写入Redis
        if self.redis_client:
            try:
                await self.redis_client.setex(key, ttl, json.dumps(value))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
    
    async def delete(self, key: str):
        self.memory_cache.delete(key)
        if self.redis_client:
            try:
                await self.redis_client.delete(key)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
    
    async def delete_pattern(self, pattern: str):
        """删除匹配模式的所有key"""
        # 删除内存缓存
        keys_to_delete = [k for k in self.memory_cache.cache if pattern.replace('*', '') in k]
        for k in keys_to_delete:
            self.memory_cache.delete(k)
        
        # 删除Redis缓存
        if self.redis_client:
            try:
                keys = await self.redis_client.keys(pattern)
                if keys:
                    await self.redis_client.delete(*keys)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
    
    async def get_stats(self) -> Dict:
        stats = {
            "memory": self.memory_cache.get_stats(),
            "redis": "connected" if self._connected else "disconnected"
        }
        return stats
    
    async def close(self):
        if self.redis_client:
            await self.redis_client.close()


def generate_cache_key(
    path: str,
    params: Dict = None,
    headers: Dict = None,
    user_id: str = None
) -> str:
    """生成缓存key"""
    key_parts = [path]
    
    if params:
        sorted_params = sorted(params.items())
        params_hash = hashlib.md5(str(sorted_params).encode()).hexdigest()[:8]
        key_parts.append(params_hash)
    
    if headers:
        relevant_headers = {k: v for k, v in headers.items() 
                          if k.lower() in ['accept-encoding', 'accept-language']}
        if relevant_headers:
            headers_hash = hashlib.md5(str(relevant_headers).encode()).hexdigest()[:8]
            key_parts.append(headers_hash)
    
    if user_id:
        key_parts.append(f"user:{user_id}")
    
    return ":".join(key_parts)


def match_cache_policy(path: str, policies: List[Dict]) -> Optional[Dict]:
    """匹配缓存策略"""
    import fnmatch
    
    for policy in policies:
        if fnmatch.fnmatch(path, policy["path"]):
            return policy
    
    return None


def cache_response(
    key_template: str,
    ttl: int = 300,
    cache_stale: bool = True
):
    """缓存装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存key
            key = key_template.format(*args, **kwargs)
            
            # 获取缓存管理器
            cache = get_global_cache_manager()
            
            # 尝试从缓存获取
            cached = await cache.get(key)
            if cached is not None:
                return cached
            
            # 执行函数
            result = await func(*args, **kwargs)
            
            # 写入缓存
            await cache.set(key, result, ttl)
            
            return result
        
        return wrapper
    return decorator


# 全局缓存管理器实例
_cache_manager: Optional[CacheManager] = None


def get_global_cache_manager() -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


def init_cache(redis_url: str = None):
    global _cache_manager
    _cache_manager = CacheManager(redis_url)
    return _cache_manager
