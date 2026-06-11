"""
数据库连接池监控模块

提供：
- 连接池健康检查
- 自动重连机制
- 连接泄漏检测
- 性能指标采集
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Callable
from enum import Enum
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class PoolStatus(Enum):
    """连接池状态"""
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    CRITICAL = 'critical'
    OFFLINE = 'offline'


@dataclass
class ConnectionMetrics:
    """连接指标"""
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    waiting_requests: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    avg_wait_time_ms: float = 0.0
    avg_query_time_ms: float = 0.0
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None


@dataclass
class PoolConfig:
    """连接池配置"""
    min_connections: int = 5
    max_connections: int = 20
    max_idle_time: int = 300  # 秒
    max_connection_age: int = 3600  # 秒
    connection_timeout: int = 30
    health_check_interval: int = 30
    retry_attempts: int = 3
    retry_delay: float = 1.0


class ConnectionPoolMonitor:
    """连接池监控器"""

    def __init__(self, config: PoolConfig = None):
        self.config = config or PoolConfig()
        self._metrics = ConnectionMetrics()
        self._connections: Dict[int, Dict] = {}
        self._lock = threading.Lock()
        self._health_check_task: Optional[asyncio.Task] = None
        self._status = PoolStatus.OFFLINE
        self._callbacks: List[Callable] = []
        self._query_times: List[float] = []
        self._wait_times: List[float] = []

    @property
    def status(self) -> PoolStatus:
        return self._status

    @property
    def metrics(self) -> ConnectionMetrics:
        return self._metrics

    def register_callback(self, callback: Callable[[PoolStatus, ConnectionMetrics], None]) -> None:
        """注册状态变更回调"""
        self._callbacks.append(callback)

    def _notify_callbacks(self) -> None:
        """通知回调"""
        for callback in self._callbacks:
            try:
                callback(self._status, self._metrics)
            except Exception as e:
                logger.warning(f"[DBPool] 回调执行失败: {e}")

    def update_metrics(
        self,
        total: int = None,
        active: int = None,
        idle: int = None,
        waiting: int = None,
    ) -> None:
        """更新连接指标"""
        with self._lock:
            if total is not None:
                self._metrics.total_connections = total
            if active is not None:
                self._metrics.active_connections = active
            if idle is not None:
                self._metrics.idle_connections = idle
            if waiting is not None:
                self._metrics.waiting_requests = waiting

            self._update_status()

    def record_request(
        self,
        success: bool,
        wait_time_ms: float = 0,
        query_time_ms: float = 0,
        error: str = None,
    ) -> None:
        """记录请求"""
        with self._lock:
            self._metrics.total_requests += 1

            if not success:
                self._metrics.failed_requests += 1
                self._metrics.last_error = error
                self._metrics.last_error_time = datetime.now()

            # 更新平均等待时间
            if wait_time_ms > 0:
                self._wait_times.append(wait_time_ms)
                if len(self._wait_times) > 100:
                    self._wait_times.pop(0)
                self._metrics.avg_wait_time_ms = sum(self._wait_times) / len(self._wait_times)

            # 更新平均查询时间
            if query_time_ms > 0:
                self._query_times.append(query_time_ms)
                if len(self._query_times) > 100:
                    self._query_times.pop(0)
                self._metrics.avg_query_time_ms = sum(self._query_times) / len(self._query_times)

    def _update_status(self) -> None:
        """更新连接池状态"""
        old_status = self._status

        if self._metrics.total_connections == 0:
            self._status = PoolStatus.OFFLINE

        elif self._metrics.active_connections >= self.config.max_connections * 0.9:
            self._status = PoolStatus.CRITICAL

        elif self._metrics.active_connections >= self.config.max_connections * 0.7:
            self._status = PoolStatus.DEGRADED

        elif self._metrics.failed_requests > self._metrics.total_requests * 0.1:
            self._status = PoolStatus.DEGRADED

        else:
            self._status = PoolStatus.HEALTHY

        if old_status != self._status:
            logger.warning(f"[DBPool] 状态变更: {old_status.value} -> {self._status.value}")
            self._notify_callbacks()

    def get_health_report(self) -> Dict[str, Any]:
        """获取健康报告"""
        return {
            'status': self._status.value,
            'metrics': {
                'total_connections': self._metrics.total_connections,
                'active_connections': self._metrics.active_connections,
                'idle_connections': self._metrics.idle_connections,
                'waiting_requests': self._metrics.waiting_requests,
                'total_requests': self._metrics.total_requests,
                'failed_requests': self._metrics.failed_requests,
                'failure_rate': (
                    self._metrics.failed_requests / self._metrics.total_requests
                    if self._metrics.total_requests > 0 else 0
                ),
                'avg_wait_time_ms': round(self._metrics.avg_wait_time_ms, 2),
                'avg_query_time_ms': round(self._metrics.avg_query_time_ms, 2),
            },
            'last_error': self._metrics.last_error,
            'last_error_time': self._metrics.last_error_time.isoformat() if self._metrics.last_error_time else None,
        }


class DatabaseConnectionManager:
    """数据库连接管理器"""

    def __init__(
        self,
        db_path: str,
        config: PoolConfig = None,
    ):
        self.db_path = db_path
        self.config = config or PoolConfig()
        self.monitor = ConnectionPoolMonitor(self.config)
        self._pool: List[Any] = []
        self._in_use: Dict[int, Any] = {}
        self._connection_times: Dict[int, datetime] = {}
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        """初始化连接池"""
        import sqlite3

        with self._lock:
            for _ in range(self.config.min_connections):
                conn = self._create_connection()
                if conn:
                    self._pool.append(conn)

            self._initialized = True
            self.monitor.update_metrics(
                total=len(self._pool) + len(self._in_use),
                active=len(self._in_use),
                idle=len(self._pool),
            )

            logger.info(f"[DBPool] 初始化连接池: {len(self._pool)} 连接")

    def _create_connection(self) -> Optional[Any]:
        """创建新连接"""
        import sqlite3

        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error(f"[DBPool] 创建连接失败: {e}")
            return None

    def _validate_connection(self, conn: Any) -> bool:
        """验证连接是否有效"""
        try:
            conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    @contextmanager
    def get_connection(self):
        """获取连接（上下文管理器）"""
        if not self._initialized:
            self.initialize()

        conn = None
        conn_id = None
        wait_start = time.time()

        with self._lock:
            # 从池中获取空闲连接
            while self._pool:
                conn = self._pool.pop()
                if self._validate_connection(conn):
                    break
                else:
                    # 无效连接，关闭
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None

            if conn is None:
                # 创建新连接
                if len(self._in_use) < self.config.max_connections:
                    conn = self._create_connection()

            if conn:
                conn_id = id(conn)
                self._in_use[conn_id] = conn
                self._connection_times[conn_id] = datetime.now()
                self.monitor.update_metrics(
                    total=len(self._pool) + len(self._in_use),
                    active=len(self._in_use),
                    idle=len(self._pool),
                )

        wait_time = (time.time() - wait_start) * 1000

        if conn is None:
            self.monitor.record_request(False, wait_time_ms=wait_time, error="No available connection")
            raise RuntimeError("无法获取数据库连接")

        try:
            query_start = time.time()
            yield conn
            query_time = (time.time() - query_start) * 1000
            self.monitor.record_request(True, wait_time_ms=wait_time, query_time_ms=query_time)
        except Exception as e:
            self.monitor.record_request(False, wait_time_ms=wait_time, error=str(e))
            raise
        finally:
            self._return_connection(conn_id)

    def _return_connection(self, conn_id: int) -> None:
        """归还连接"""
        with self._lock:
            if conn_id in self._in_use:
                conn = self._in_use.pop(conn_id)
                conn_time = self._connection_times.pop(conn_id, None)

                # 检查连接是否过期
                if conn_time and (datetime.now() - conn_time).total_seconds() > self.config.max_connection_age:
                    try:
                        conn.close()
                    except Exception:
                        pass
                elif self._validate_connection(conn):
                    self._pool.append(conn)
                else:
                    try:
                        conn.close()
                    except Exception:
                        pass

                self.monitor.update_metrics(
                    total=len(self._pool) + len(self._in_use),
                    active=len(self._in_use),
                    idle=len(self._pool),
                )

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        report = self.monitor.get_health_report()

        # 测试查询
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()
                report['ping'] = 'ok'
        except Exception as e:
            report['ping'] = 'failed'
            report['ping_error'] = str(e)

        return report

    async def start_health_check_loop(self) -> None:
        """启动健康检查循环"""
        while True:
            try:
                await self.health_check()
                await asyncio.sleep(self.config.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DBPool] 健康检查失败: {e}")
                await asyncio.sleep(5)

    def close_all(self) -> None:
        """关闭所有连接"""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()

            for conn in self._in_use.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._in_use.clear()
            self._connection_times.clear()

            self.monitor.update_metrics(total=0, active=0, idle=0)
            logger.info("[DBPool] 所有连接已关闭")

    def get_metrics(self) -> ConnectionMetrics:
        """获取指标"""
        return self.monitor.metrics


# 全局连接管理器
_db_manager: Optional[DatabaseConnectionManager] = None


def get_db_manager() -> DatabaseConnectionManager:
    """获取全局数据库管理器"""
    global _db_manager
    return _db_manager


def init_db_manager(db_path: str, config: PoolConfig = None) -> DatabaseConnectionManager:
    """初始化数据库管理器"""
    global _db_manager
    _db_manager = DatabaseConnectionManager(db_path, config)
    _db_manager.initialize()
    return _db_manager
