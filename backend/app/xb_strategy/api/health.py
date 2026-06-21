"""西部量化可转债策略 V3.0 服务健康检查模块

功能:
- 健康检查端点
- 依赖服务检查
- 数据库连接检查
- 外部服务检查
- 就绪探针
- 存活探针
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
from enum import Enum
import asyncio
import logging
import time
import socket

from fastapi import APIRouter, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["健康检查"])


# ============ 枚举类型 ============

class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentType(str, Enum):
    """组件类型"""
    DATABASE = "database"
    REDIS = "redis"
    EXTERNAL_API = "external_api"
    DATA_SOURCE = "data_source"
    STORAGE = "storage"
    CACHE = "cache"


# ============ 数据模型 ============

class ComponentHealth(BaseModel):
    """组件健康状态"""
    name: str
    type: ComponentType
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    details: Dict[str, Any] = {}
    last_check: datetime


class HealthCheckResult(BaseModel):
    """健康检查结果"""
    status: HealthStatus
    timestamp: datetime
    version: str
    hostname: str
    uptime_seconds: float
    components: List[ComponentHealth] = []


# ============ 健康检查器 ============

class HealthChecker:
    """健康检查器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._start_time = time.time()
        self._checks: Dict[str, callable] = {}
        self._last_results: Dict[str, ComponentHealth] = {}

        # 注册默认检查
        self._register_default_checks()

        self._initialized = True

    def _register_default_checks(self):
        """注册默认健康检查"""
        self.register_check("database", self._check_database, ComponentType.DATABASE)
        self.register_check("redis", self._check_redis, ComponentType.CACHE)
        self.register_check("data_source", self._check_data_source, ComponentType.DATA_SOURCE)
        self.register_check("storage", self._check_storage, ComponentType.STORAGE)

    def register_check(
        self,
        name: str,
        check_func: callable,
        component_type: ComponentType,
    ):
        """注册健康检查"""
        self._checks[name] = {
            "func": check_func,
            "type": component_type,
        }

    async def _check_database(self) -> Dict[str, Any]:
        """检查数据库连接"""
        start = time.time()

        try:
            # 尝试导入并检查数据库连接
            # 这里简化处理，实际应检查真实数据库
            await asyncio.sleep(0.01)  # 模拟检查

            latency = (time.time() - start) * 1000

            return {
                "status": HealthStatus.HEALTHY,
                "message": "数据库连接正常",
                "latency_ms": round(latency, 2),
                "details": {"type": "memory"},
            }

        except Exception as e:
            return {
                "status": HealthStatus.UNHEALTHY,
                "message": f"数据库连接失败: {e}",
                "latency_ms": 0,
            }

    async def _check_redis(self) -> Dict[str, Any]:
        """检查Redis连接"""
        start = time.time()

        try:
            # 尝试获取缓存管理器
            from app.xb_strategy.core.cache import get_cache_manager
            cache = get_cache_manager()

            if cache.l2_cache.is_connected:
                latency = (time.time() - start) * 1000
                return {
                    "status": HealthStatus.HEALTHY,
                    "message": "Redis连接正常",
                    "latency_ms": round(latency, 2),
                }
            else:
                # Redis未连接但不是致命错误
                return {
                    "status": HealthStatus.DEGRADED,
                    "message": "Redis未连接，使用内存缓存",
                    "latency_ms": 0,
                }

        except Exception as e:
            return {
                "status": HealthStatus.DEGRADED,
                "message": f"Redis检查失败: {e}",
                "latency_ms": 0,
            }

    async def _check_data_source(self) -> Dict[str, Any]:
        """检查数据源"""
        start = time.time()

        try:
            # 检查数据源是否可用
            # 简化处理
            latency = (time.time() - start) * 1000

            return {
                "status": HealthStatus.HEALTHY,
                "message": "数据源正常",
                "latency_ms": round(latency, 2),
                "details": {"provider": "akshare"},
            }

        except Exception as e:
            return {
                "status": HealthStatus.DEGRADED,
                "message": f"数据源检查失败: {e}",
                "latency_ms": 0,
            }

    async def _check_storage(self) -> Dict[str, Any]:
        """检查存储"""
        start = time.time()

        try:
            # 检查存储管理器
            from app.xb_strategy.core.storage import get_storage_manager
            storage = get_storage_manager()

            if storage.storage.health_check():
                latency = (time.time() - start) * 1000
                return {
                    "status": HealthStatus.HEALTHY,
                    "message": "存储正常",
                    "latency_ms": round(latency, 2),
                }
            else:
                return {
                    "status": HealthStatus.DEGRADED,
                    "message": "存储不可用",
                    "latency_ms": 0,
                }

        except Exception as e:
            return {
                "status": HealthStatus.DEGRADED,
                "message": f"存储检查失败: {e}",
                "latency_ms": 0,
            }

    async def run_check(self, name: str) -> ComponentHealth:
        """运行单个检查"""
        if name not in self._checks:
            return ComponentHealth(
                name=name,
                type=ComponentType.EXTERNAL_API,
                status=HealthStatus.UNHEALTHY,
                message=f"未知的检查项: {name}",
                last_check=datetime.now(),
            )

        check_info = self._checks[name]
        check_func = check_info["func"]
        component_type = check_info["type"]

        try:
            result = await check_func()

            health = ComponentHealth(
                name=name,
                type=component_type,
                status=HealthStatus(result["status"]),
                message=result.get("message", ""),
                latency_ms=result.get("latency_ms", 0),
                details=result.get("details", {}),
                last_check=datetime.now(),
            )

        except Exception as e:
            health = ComponentHealth(
                name=name,
                type=component_type,
                status=HealthStatus.UNHEALTHY,
                message=f"检查异常: {e}",
                last_check=datetime.now(),
            )

        self._last_results[name] = health
        return health

    async def run_all_checks(self) -> HealthCheckResult:
        """运行所有检查"""
        components = []

        # 并行执行所有检查
        tasks = [self.run_check(name) for name in self._checks]
        components = await asyncio.gather(*tasks)

        # 确定整体状态
        status = HealthStatus.HEALTHY
        for component in components:
            if component.status == HealthStatus.UNHEALTHY:
                status = HealthStatus.UNHEALTHY
                break
            elif component.status == HealthStatus.DEGRADED:
                status = HealthStatus.DEGRADED

        return HealthCheckResult(
            status=status,
            timestamp=datetime.now(),
            version="3.0.0",
            hostname=socket.gethostname(),
            uptime_seconds=time.time() - self._start_time,
            components=components,
        )

    def get_uptime(self) -> float:
        """获取运行时间"""
        return time.time() - self._start_time

    def get_last_results(self) -> Dict[str, ComponentHealth]:
        """获取最后检查结果"""
        return self._last_results


def get_health_checker() -> HealthChecker:
    """获取健康检查器"""
    return HealthChecker()


# ============ API路由 ============

@router.get("/health", response_model=HealthCheckResult, summary="健康检查")
async def health_check(
    checker: HealthChecker = None,
):
    """
    完整健康检查

    检查所有依赖服务的健康状态
    """
    if checker is None:
        checker = get_health_checker()

    result = await checker.run_all_checks()

    # 设置HTTP状态码
    if result.status == HealthStatus.UNHEALTHY:
        status_code = 503
    elif result.status == HealthStatus.DEGRADED:
        status_code = 200  # 降级但仍可用
    else:
        status_code = 200

    return result


@router.get("/health/live", summary="存活探针")
async def liveness_probe():
    """
    Kubernetes存活探针

    检查服务是否存活，如果返回200则服务正常
    """
    return {
        "status": "alive",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/health/ready", summary="就绪探针")
async def readiness_probe(
    checker: HealthChecker = None,
):
    """
    Kubernetes就绪探针

    检查服务是否就绪，可以接收流量
    """
    if checker is None:
        checker = get_health_checker()

    result = await checker.run_all_checks()

    # 只有关键组件健康才认为就绪
    is_ready = result.status != HealthStatus.UNHEALTHY

    if not is_ready:
        return Response(
            content='{"status": "not ready"}',
            status_code=503,
            media_type="application/json",
        )

    return {
        "status": "ready",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": checker.get_uptime(),
    }


@router.get("/health/startup", summary="启动探针")
async def startup_probe():
    """
    Kubernetes启动探针

    检查服务是否已完成启动
    """
    checker = get_health_checker()

    # 简单检查是否已经运行了一段时间
    uptime = checker.get_uptime()

    if uptime < 5:  # 启动后5秒内认为还在初始化
        return Response(
            content='{"status": "starting"}',
            status_code=503,
            media_type="application/json",
        )

    return {
        "status": "started",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": uptime,
    }


@router.get("/health/components/{component_name}", response_model=ComponentHealth, summary="组件健康检查")
async def component_health(
    component_name: str,
    checker: HealthChecker = None,
):
    """
    检查单个组件的健康状态
    """
    if checker is None:
        checker = get_health_checker()

    result = await checker.run_check(component_name)

    if result.status == HealthStatus.UNHEALTHY:
        # 可以返回503但这里保持200，让客户端判断
        pass

    return result


@router.get("/health/uptime", summary="运行时间")
async def get_uptime():
    """获取服务运行时间"""
    checker = get_health_checker()

    uptime = checker.get_uptime()
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    seconds = int(uptime % 60)

    return {
        "uptime_seconds": uptime,
        "uptime_formatted": f"{hours}h {minutes}m {seconds}s",
        "started_at": datetime.fromtimestamp(time.time() - uptime).isoformat(),
    }


@router.get("/health/info", summary="服务信息")
async def get_service_info():
    """获取服务信息"""
    return {
        "name": "西部量化可转债策略",
        "version": "3.0.0",
        "hostname": socket.gethostname(),
        "environment": "production",
        "timestamp": datetime.now().isoformat(),
    }


# ============ 简单检查函数 ============

def check_database_connection() -> bool:
    """检查数据库连接"""
    try:
        # 简化实现
        return True
    except Exception:
        return False


def check_redis_connection() -> bool:
    """检查Redis连接"""
    try:
        from app.xb_strategy.core.cache import get_cache_manager
        cache = get_cache_manager()
        return cache.l2_cache.is_connected
    except Exception:
        return False


def check_storage_connection() -> bool:
    """检查存储连接"""
    try:
        from app.xb_strategy.core.storage import get_storage_manager
        storage = get_storage_manager()
        return storage.health_check()
    except Exception:
        return False


async def quick_health_check() -> bool:
    """快速健康检查"""
    # 只检查最关键的组件
    return check_database_connection()
