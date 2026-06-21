"""西部量化可转债策略 V3.0 缓存模块

功能:
- Redis缓存层
- 连接池管理
- 分布式锁
- 缓存预热
- 缓存失效策略
- 热点数据缓存
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Union, Callable
from enum import Enum
import json
import logging
import time
import hashlib
import pickle
import functools
from contextlib import contextmanager
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class CacheKeyPrefix(str, Enum):
    """缓存键前缀"""
    SCORE = "sg:score"           # 得分缓存
    WHITELIST = "sg:whitelist"   # 白名单缓存
    QUOTE = "sg:quote"           # 行情缓存
    POSITION = "sg:position"     # 持仓缓存
    PORTFOLIO = "sg:portfolio"   # 组合缓存
    SIGNAL = "sg:signal"         # 信号缓存
    FILTER = "sg:filter"         # 筛选结果缓存
    RISK = "sg:risk"             # 风控缓存
    MARKET = "sg:market"         # 市场数据缓存


class CacheLevel(str, Enum):
    """缓存级别"""
    L1_MEMORY = "l1_memory"      # 一级缓存：内存
    L2_REDIS = "l2_redis"        # 二级缓存：Redis
    L3_DB = "l3_db"              # 三级：数据库


# ============ 配置类 ============

@dataclass
class CacheConfig:
    """缓存配置"""
    # Redis连接
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0

    # 连接池
    max_connections: int = 50
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0

    # 缓存策略
    default_ttl: int = 3600           # 默认过期时间(秒)
    score_ttl: int = 300              # 得分缓存时间
    quote_ttl: int = 10               # 行情缓存时间
    whitelist_ttl: int = 1800         # 白名单缓存时间
    position_ttl: int = 60            # 持仓缓存时间

    # 内存缓存
    l1_max_size: int = 10000          # 内存缓存最大条目
    l1_ttl: int = 300                 # 内存缓存过期时间

    # 分布式锁
    lock_timeout: int = 30            # 锁超时时间(秒)
    lock_retry_interval: float = 0.1  # 锁重试间隔(秒)
    lock_max_retries: int = 100       # 最大重试次数


# ============ 内存缓存 ============

class MemoryCache:
    """内存缓存 - L1缓存"""

    def __init__(self, max_size: int = 10000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_order: List[str] = []

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key not in self._cache:
            return None

        item = self._cache[key]

        # 检查过期
        if item["expires_at"] and datetime.now() > item["expires_at"]:
            self.delete(key)
            return None

        # 更新访问顺序
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        return item["value"]

    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存"""
        # 清理过期缓存
        self._cleanup()

        # 检查容量
        while len(self._cache) >= self.max_size and self._access_order:
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                del self._cache[oldest_key]

        expires_at = None
        if ttl:
            expires_at = datetime.now() + timedelta(seconds=ttl)
        elif self.default_ttl:
            expires_at = datetime.now() + timedelta(seconds=self.default_ttl)

        self._cache[key] = {
            "value": value,
            "expires_at": expires_at,
            "created_at": datetime.now(),
        }

        if key not in self._access_order:
            self._access_order.append(key)

    def delete(self, key: str):
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]
        if key in self._access_order:
            self._access_order.remove(key)

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._access_order.clear()

    def _cleanup(self):
        """清理过期缓存"""
        now = datetime.now()
        expired_keys = [
            k for k, v in self._cache.items()
            if v["expires_at"] and now > v["expires_at"]
        ]
        for key in expired_keys:
            self.delete(key)

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "access_order_length": len(self._access_order),
        }


# ============ Redis缓存 ============

class RedisCache:
    """Redis缓存 - L2缓存"""

    def __init__(self, config: CacheConfig):
        self.config = config
        self._pool = None
        self._redis = None
        self._connected = False

    def connect(self) -> bool:
        """建立连接"""
        try:
            import redis

            self._pool = redis.ConnectionPool(
                host=self.config.host,
                port=self.config.port,
                password=self.config.password if self.config.password else None,
                db=self.config.db,
                max_connections=self.config.max_connections,
                socket_timeout=self.config.socket_timeout,
                socket_connect_timeout=self.config.socket_connect_timeout,
                decode_responses=True,
            )

            self._redis = redis.Redis(connection_pool=self._pool)

            # 测试连接
            self._redis.ping()
            self._connected = True

            logger.info(f"[RedisCache] 连接成功: {self.config.host}:{self.config.port}")
            return True

        except ImportError:
            logger.warning("[RedisCache] redis库未安装，请执行: pip install redis")
            return False
        except Exception as e:
            logger.error(f"[RedisCache] 连接失败: {e}")
            self._connected = False
            return False

    def close(self):
        """关闭连接"""
        if self._pool:
            self._pool.disconnect()
            self._pool = None
            self._redis = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if not self._connected or not self._redis:
            return None

        try:
            value = self._redis.get(key)
            if value is None:
                return None

            # 尝试JSON解析
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        except Exception as e:
            logger.error(f"[RedisCache] 获取失败: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存"""
        if not self._connected or not self._redis:
            return False

        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            elif not isinstance(value, str):
                value = str(value)

            ttl = ttl or self.config.default_ttl

            if ttl:
                self._redis.setex(key, ttl, value)
            else:
                self._redis.set(key, value)

            return True

        except Exception as e:
            logger.error(f"[RedisCache] 设置失败: {e}")
            return False

    def delete(self, key: str):
        """删除缓存"""
        if not self._connected or not self._redis:
            return

        try:
            self._redis.delete(key)
        except Exception as e:
            logger.error(f"[RedisCache] 删除失败: {e}")

    def delete_pattern(self, pattern: str):
        """删除匹配的键"""
        if not self._connected or not self._redis:
            return

        try:
            keys = self._redis.keys(pattern)
            if keys:
                self._redis.delete(*keys)
                logger.debug(f"[RedisCache] 删除{len(keys)}个键: {pattern}")
        except Exception as e:
            logger.error(f"[RedisCache] 批量删除失败: {e}")

    def mget(self, keys: List[str]) -> Dict[str, Any]:
        """批量获取"""
        if not self._connected or not self._redis or not keys:
            return {}

        try:
            values = self._redis.mget(keys)
            result = {}

            for key, value in zip(keys, values):
                if value is not None:
                    try:
                        result[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        result[key] = value

            return result

        except Exception as e:
            logger.error(f"[RedisCache] 批量获取失败: {e}")
            return {}

    def mset(self, mapping: Dict[str, Any], ttl: int = None):
        """批量设置"""
        if not self._connected or not self._redis or not mapping:
            return False

        try:
            pipe = self._redis.pipeline()

            for key, value in mapping.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False, default=str)
                elif not isinstance(value, str):
                    value = str(value)

                if ttl:
                    pipe.setex(key, ttl, value)
                else:
                    pipe.set(key, value)

            pipe.execute()
            return True

        except Exception as e:
            logger.error(f"[RedisCache] 批量设置失败: {e}")
            return False

    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if not self._connected or not self._redis:
            return False

        try:
            return self._redis.exists(key) > 0
        except Exception as e:
            logger.warning("[RedisCache] exists failed: %s", e)
            return False

    def ttl(self, key: str) -> int:
        """获取剩余过期时间"""
        if not self._connected or not self._redis:
            return -1

        try:
            return self._redis.ttl(key)
        except Exception as e:
            logger.warning("[RedisCache] ttl failed: %s", e)
            return -1

    def incr(self, key: str, amount: int = 1) -> int:
        """计数器增加"""
        if not self._connected or not self._redis:
            return 0

        try:
            return self._redis.incrby(key, amount)
        except Exception as e:
            logger.warning("[RedisCache] incr failed: %s", e)
            return 0

    def expire(self, key: str, ttl: int) -> bool:
        """设置过期时间"""
        if not self._connected or not self._redis:
            return False

        try:
            return self._redis.expire(key, ttl)
        except Exception as e:
            logger.warning("[RedisCache] expire failed: %s", e)
            return False


# ============ 分布式锁 ============

class DistributedLock:
    """分布式锁"""

    def __init__(self, redis_cache: RedisCache, config: CacheConfig):
        self.redis = redis_cache
        self.config = config

    def acquire(self, lock_name: str, timeout: int = None) -> bool:
        """获取锁

        Args:
            lock_name: 锁名称
            timeout: 锁超时时间(秒)

        Returns:
            是否获取成功
        """
        if not self.redis.is_connected:
            return False

        timeout = timeout or self.config.lock_timeout
        lock_key = f"lock:{lock_name}"
        identifier = f"{time.time()}_{id(self)}"

        for _ in range(self.config.lock_max_retries):
            try:
                result = self.redis._redis.set(lock_key, identifier, nx=True, ex=timeout)
                if result:
                    return True

            except Exception as e:
                logger.error(f"[DistributedLock] 获取锁失败: {e}")

            time.sleep(self.config.lock_retry_interval)

        return False

    def release(self, lock_name: str, identifier: str = None):
        """释放锁"""
        if not self.redis.is_connected:
            return

        lock_key = f"lock:{lock_name}"

        try:
            current = self.redis._redis.get(lock_key)
            if current and current == identifier:
                self.redis._redis.delete(lock_key)
        except Exception as e:
            logger.error(f"[DistributedLock] 释放锁失败: {e}")

    @contextmanager
    def lock(self, lock_name: str, timeout: int = None):
        """锁上下文管理器"""
        timeout = timeout or self.config.lock_timeout
        lock_key = f"lock:{lock_name}"
        identifier = f"{time.time()}_{id(self)}"
        acquired = self.acquire(lock_name, timeout)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(lock_name, identifier)


# ============ 多级缓存管理器 ============

class CacheManager:
    """多级缓存管理器"""

    _instance = None

    def __new__(cls, config: CacheConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: CacheConfig = None):
        if self._initialized:
            return

        self.config = config or CacheConfig()

        # L1内存缓存
        self.l1_cache = MemoryCache(
            max_size=self.config.l1_max_size,
            default_ttl=self.config.l1_ttl,
        )

        # L2 Redis缓存
        self.l2_cache = RedisCache(self.config)
        self._lock: Optional[DistributedLock] = None

        self._initialized = True

    def connect(self) -> bool:
        """建立连接"""
        if self.l2_cache.connect():
            self._lock = DistributedLock(self.l2_cache, self.config)
            return True
        return False

    def close(self):
        """关闭连接"""
        self.l2_cache.close()
        self.l1_cache.clear()

    def get(self, key: str, use_l1: bool = True, use_l2: bool = True) -> Optional[Any]:
        """获取缓存（多级查询）"""
        # L1缓存
        if use_l1:
            value = self.l1_cache.get(key)
            if value is not None:
                return value

        # L2缓存
        if use_l2 and self.l2_cache.is_connected:
            value = self.l2_cache.get(key)
            if value is not None:
                # 回写L1
                if use_l1:
                    self.l1_cache.set(key, value, self.config.l1_ttl)
                return value

        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: int = None,
        use_l1: bool = True,
        use_l2: bool = True,
    ):
        """设置缓存（多级写入）"""
        if use_l1:
            self.l1_cache.set(key, value, ttl or self.config.l1_ttl)

        if use_l2 and self.l2_cache.is_connected:
            self.l2_cache.set(key, value, ttl)

    def delete(self, key: str, use_l1: bool = True, use_l2: bool = True):
        """删除缓存"""
        if use_l1:
            self.l1_cache.delete(key)

        if use_l2 and self.l2_cache.is_connected:
            self.l2_cache.delete(key)

    def invalidate_pattern(self, pattern: str):
        """失效匹配的缓存"""
        # 清空L1
        self.l1_cache.clear()

        # 清空L2
        if self.l2_cache.is_connected:
            self.l2_cache.delete_pattern(pattern)

    # ============ 业务缓存方法 ============

    def cache_score(self, cb_code: str, score_data: Dict, ttl: int = None):
        """缓存得分"""
        key = f"{CacheKeyPrefix.SCORE.value}:{cb_code}"
        self.set(key, score_data, ttl or self.config.score_ttl)

    def get_score(self, cb_code: str) -> Optional[Dict]:
        """获取得分缓存"""
        key = f"{CacheKeyPrefix.SCORE.value}:{cb_code}"
        return self.get(key)

    def cache_whitelist(self, whitelist: List[str], ttl: int = None):
        """缓存白名单"""
        key = f"{CacheKeyPrefix.WHITELIST.value}:current"
        self.set(key, whitelist, ttl or self.config.whitelist_ttl)

    def get_whitelist(self) -> Optional[List[str]]:
        """获取白名单缓存"""
        key = f"{CacheKeyPrefix.WHITELIST.value}:current"
        return self.get(key)

    def cache_quote(self, cb_code: str, quote_data: Dict, ttl: int = None):
        """缓存行情"""
        key = f"{CacheKeyPrefix.QUOTE.value}:{cb_code}"
        self.set(key, quote_data, ttl or self.config.quote_ttl)

    def get_quote(self, cb_code: str) -> Optional[Dict]:
        """获取行情缓存"""
        key = f"{CacheKeyPrefix.QUOTE.value}:{cb_code}"
        return self.get(key)

    def cache_quotes_batch(self, quotes: Dict[str, Dict], ttl: int = None):
        """批量缓存行情"""
        if not quotes:
            return

        mapping = {
            f"{CacheKeyPrefix.QUOTE.value}:{code}": data
            for code, data in quotes.items()
        }

        # L1缓存
        for key, value in mapping.items():
            self.l1_cache.set(key, value, ttl or self.config.quote_ttl)

        # L2缓存
        if self.l2_cache.is_connected:
            self.l2_cache.mset(mapping, ttl or self.config.quote_ttl)

    def get_quotes_batch(self, codes: List[str]) -> Dict[str, Dict]:
        """批量获取行情缓存"""
        result = {}
        missing_codes = []

        for code in codes:
            key = f"{CacheKeyPrefix.QUOTE.value}:{code}"
            value = self.l1_cache.get(key)
            if value is not None:
                result[code] = value
            else:
                missing_codes.append(code)

        # 从L2获取缺失的
        if missing_codes and self.l2_cache.is_connected:
            keys = [f"{CacheKeyPrefix.QUOTE.value}:{code}" for code in missing_codes]
            l2_result = self.l2_cache.mget(keys)

            for key, value in l2_result.items():
                code = key.split(":")[-1]
                result[code] = value
                # 回写L1
                self.l1_cache.set(key, value, self.config.l1_ttl)

        return result

    def cache_position(self, positions: Dict[str, Dict], ttl: int = None):
        """缓存持仓"""
        key = f"{CacheKeyPrefix.POSITION.value}:current"
        self.set(key, positions, ttl or self.config.position_ttl)

    def get_position(self) -> Optional[Dict[str, Dict]]:
        """获取持仓缓存"""
        key = f"{CacheKeyPrefix.POSITION.value}:current"
        return self.get(key)

    def cache_portfolio(self, portfolio_data: Dict, ttl: int = None):
        """缓存组合信息"""
        key = f"{CacheKeyPrefix.PORTFOLIO.value}:current"
        self.set(key, portfolio_data, ttl or self.config.position_ttl)

    def get_portfolio(self) -> Optional[Dict]:
        """获取组合缓存"""
        key = f"{CacheKeyPrefix.PORTFOLIO.value}:current"
        return self.get(key)

    def invalidate_scores(self):
        """失效所有得分缓存"""
        self.invalidate_pattern(f"{CacheKeyPrefix.SCORE.value}:*")

    def invalidate_whitelist(self):
        """失效白名单缓存"""
        self.delete(f"{CacheKeyPrefix.WHITELIST.value}:current")

    def invalidate_quotes(self):
        """失效所有行情缓存"""
        self.invalidate_pattern(f"{CacheKeyPrefix.QUOTE.value}:*")

    # ============ 分布式锁 ============

    @contextmanager
    def distributed_lock(self, lock_name: str, timeout: int = None):
        """分布式锁上下文"""
        if self._lock:
            with self._lock.lock(lock_name, timeout) as acquired:
                yield acquired
        else:
            yield True

    # ============ 统计信息 ============

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "l1_cache": self.l1_cache.stats(),
            "l2_connected": self.l2_cache.is_connected,
        }


# ============ 缓存装饰器 ============

def cached(
    key_prefix: str,
    ttl: int = 300,
    key_builder: Optional[Callable] = None,
):
    """缓存装饰器

    Args:
        key_prefix: 缓存键前缀
        ttl: 过期时间
        key_builder: 自定义键构建函数

    Example:
        @cached("my_func", ttl=60)
        def expensive_function(param):
            return compute(param)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 获取缓存管理器
            cache = get_cache_manager()

            # 构建缓存键
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                # 默认键构建
                args_str = "_".join(str(a) for a in args)
                kwargs_str = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                key_content = f"{args_str}_{kwargs_str}"
                key_hash = hashlib.md5(key_content.encode()).hexdigest()[:8]
                cache_key = f"{key_prefix}:{key_hash}"

            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 执行函数
            result = func(*args, **kwargs)

            # 写入缓存
            if result is not None:
                cache.set(cache_key, result, ttl)

            return result

        return wrapper
    return decorator


# ============ 缓存预热 ============

class CacheWarmup:
    """缓存预热"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    def warmup_scores(self, scores: Dict[str, Dict]):
        """预热得分缓存"""
        for code, score_data in scores.items():
            self.cache.cache_score(code, score_data)
        logger.info(f"[CacheWarmup] 预热得分缓存: {len(scores)}条")

    def warmup_whitelist(self, whitelist: List[str]):
        """预热白名单缓存"""
        self.cache.cache_whitelist(whitelist)
        logger.info(f"[CacheWarmup] 预热白名单缓存: {len(whitelist)}只")

    def warmup_quotes(self, quotes: Dict[str, Dict]):
        """预热行情缓存"""
        self.cache.cache_quotes_batch(quotes)
        logger.info(f"[CacheWarmup] 预热行情缓存: {len(quotes)}条")


# ============ 便捷函数 ============

def get_cache_manager(config: CacheConfig = None) -> CacheManager:
    """获取缓存管理器单例"""
    return CacheManager(config)


def init_redis_cache(
    host: str = "localhost",
    port: int = 6379,
    password: str = "",
    db: int = 0,
) -> CacheManager:
    """初始化Redis缓存"""
    config = CacheConfig(
        host=host,
        port=port,
        password=password,
        db=db,
    )
    manager = CacheManager(config)
    manager.connect()
    return manager
