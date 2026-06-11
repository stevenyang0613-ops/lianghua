"""
性能监控模块

功能：
- Prometheus指标暴露
- 策略执行耗时监控
- 内存使用追踪
- API请求统计
"""

import time
import psutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable
from functools import wraps
import logging

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """指标数据点"""
    name: str
    value: float
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class PerformanceSnapshot:
    """性能快照"""
    timestamp: datetime
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    active_threads: int
    open_files: int


class MetricsCollector:
    """指标收集器"""

    def __init__(self):
        self._metrics: Dict[str, List[MetricPoint]] = {}
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, value: float = 1, labels: Dict = None) -> None:
        """计数器指标"""
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] = self._counters.get(key, 0) + value

            self._add_point(name, value, labels)

    def gauge(self, name: str, value: float, labels: Dict = None) -> None:
        """仪表盘指标"""
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value

            self._add_point(name, value, labels)

    def histogram(self, name: str, value: float, labels: Dict = None) -> None:
        """直方图指标"""
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)

            self._add_point(name, value, labels)

    def _make_key(self, name: str, labels: Dict = None) -> str:
        """生成指标键"""
        if not labels:
            return name
        label_str = ','.join(f'{k}={v}' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _add_point(self, name: str, value: float, labels: Dict = None) -> None:
        """添加数据点"""
        if name not in self._metrics:
            self._metrics[name] = []

        point = MetricPoint(
            name=name,
            value=value,
            timestamp=datetime.now(),
            labels=labels or {},
        )
        self._metrics[name].append(point)

        # 限制历史数据量
        if len(self._metrics[name]) > 10000:
            self._metrics[name] = self._metrics[name][-10000:]

    def get_counter(self, name: str, labels: Dict = None) -> float:
        """获取计数器值"""
        key = self._make_key(name, labels)
        return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: Dict = None) -> float:
        """获取仪表盘值"""
        key = self._make_key(name, labels)
        return self._gauges.get(key, 0)

    def get_histogram_stats(self, name: str, labels: Dict = None) -> Dict:
        """获取直方图统计"""
        key = self._make_key(name, labels)
        values = self._histograms.get(key, [])

        if not values:
            return {'count': 0, 'sum': 0, 'avg': 0, 'min': 0, 'max': 0}

        return {
            'count': len(values),
            'sum': sum(values),
            'avg': sum(values) / len(values),
            'min': min(values),
            'max': max(values),
            'p50': self._percentile(values, 50),
            'p90': self._percentile(values, 90),
            'p99': self._percentile(values, 99),
        }

    def _percentile(self, values: List[float], p: float) -> float:
        """计算百分位数"""
        if not values:
            return 0
        sorted_values = sorted(values)
        idx = int(len(sorted_values) * p / 100)
        return sorted_values[min(idx, len(sorted_values) - 1)]

    def export_prometheus(self) -> str:
        """导出Prometheus格式"""
        lines = []

        # 计数器
        for key, value in self._counters.items():
            lines.append(f"# TYPE {key.split('{')[0]} counter")
            lines.append(f"{key} {value}")

        # 仪表盘
        for key, value in self._gauges.items():
            lines.append(f"# TYPE {key.split('{')[0]} gauge")
            lines.append(f"{key} {value}")

        # 直方图统计
        for key, values in self._histograms.items():
            name = key.split('{')[0]
            stats = self.get_histogram_stats(name)
            lines.append(f"# TYPE {name} histogram")
            lines.append(f"{name}_count {stats['count']}")
            lines.append(f"{name}_sum {stats['sum']:.2f}")

        return '\n'.join(lines)


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self, collect_interval: int = 60):
        self._collector = MetricsCollector()
        self._collect_interval = collect_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._snapshots: List[PerformanceSnapshot] = []

    def start(self) -> None:
        """启动监控"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._collect_loop, daemon=True)
        self._thread.start()
        logger.info("[Metrics] Performance monitor started")

    def stop(self) -> None:
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[Metrics] Performance monitor stopped")

    def _collect_loop(self) -> None:
        """收集循环"""
        while self._running:
            try:
                snapshot = self._take_snapshot()
                self._snapshots.append(snapshot)

                # 限制快照数量
                if len(self._snapshots) > 1440:  # 24小时 @ 1分钟间隔
                    self._snapshots = self._snapshots[-1440:]

                # 更新指标
                self._collector.gauge('system_cpu_percent', snapshot.cpu_percent)
                self._collector.gauge('system_memory_mb', snapshot.memory_mb)
                self._collector.gauge('system_memory_percent', snapshot.memory_percent)
                self._collector.gauge('system_active_threads', snapshot.active_threads)

            except Exception as e:
                logger.error(f"[Metrics] Collection error: {e}")

            time.sleep(self._collect_interval)

    def _take_snapshot(self) -> PerformanceSnapshot:
        """获取性能快照"""
        process = psutil.Process()

        return PerformanceSnapshot(
            timestamp=datetime.now(),
            cpu_percent=process.cpu_percent(),
            memory_mb=process.memory_info().rss / 1024 / 1024,
            memory_percent=process.memory_percent(),
            active_threads=process.num_threads(),
            open_files=len(process.open_files()) if hasattr(process, 'open_files') else 0,
        )

    def get_current_snapshot(self) -> PerformanceSnapshot:
        """获取当前快照"""
        return self._take_snapshot()

    def get_snapshots(self, hours: int = 1) -> List[PerformanceSnapshot]:
        """获取历史快照"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [s for s in self._snapshots if s.timestamp >= cutoff]

    @property
    def collector(self) -> MetricsCollector:
        return self._collector


class StrategyMetrics:
    """策略执行指标"""

    def __init__(self, collector: MetricsCollector):
        self._collector = collector

    def record_execution(
        self,
        strategy_name: str,
        execution_time_ms: float,
        success: bool,
        signal_count: int = 0,
    ) -> None:
        """记录策略执行"""
        labels = {'strategy': strategy_name}

        self._collector.histogram(
            'strategy_execution_time_ms',
            execution_time_ms,
            labels,
        )

        self._collector.counter(
            'strategy_executions_total',
            labels={'strategy': strategy_name, 'status': 'success' if success else 'failure'},
        )

        if signal_count > 0:
            self._collector.gauge(
                'strategy_signal_count',
                signal_count,
                labels,
            )

    def record_signal_generated(
        self,
        strategy_name: str,
        signal_type: str,
    ) -> None:
        """记录信号生成"""
        self._collector.counter(
            'signals_generated_total',
            labels={'strategy': strategy_name, 'type': signal_type},
        )


class APIMetrics:
    """API请求指标"""

    def __init__(self, collector: MetricsCollector):
        self._collector = collector

    def record_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """记录API请求"""
        labels = {
            'endpoint': endpoint,
            'method': method,
            'status': str(status_code),
        }

        self._collector.histogram(
            'http_request_duration_ms',
            duration_ms,
            labels,
        )

        self._collector.counter(
            'http_requests_total',
            labels=labels,
        )

    def record_active_connections(self, count: int) -> None:
        """记录活跃连接数"""
        self._collector.gauge('http_active_connections', count)


def timed(metric_name: str = None):
    """执行时间装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                name = metric_name or func.__name__
                _global_collector.histogram(f'{name}_duration_ms', duration_ms)
                logger.debug(f"[Timer] {name}: {duration_ms:.2f}ms")

        return wrapper
    return decorator


def async_timed(metric_name: str = None):
    """异步执行时间装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                name = metric_name or func.__name__
                _global_collector.histogram(f'{name}_duration_ms', duration_ms)
                logger.debug(f"[Timer] {name}: {duration_ms:.2f}ms")

        return wrapper
    return decorator


# 全局实例
_global_collector = MetricsCollector()
_global_monitor: Optional[PerformanceMonitor] = None


def get_metrics_collector() -> MetricsCollector:
    """获取指标收集器"""
    return _global_collector


def get_performance_monitor() -> PerformanceMonitor:
    """获取性能监控器"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = PerformanceMonitor()
    return _global_monitor


def start_monitoring() -> None:
    """启动监控"""
    monitor = get_performance_monitor()
    monitor.start()


def stop_monitoring() -> None:
    """停止监控"""
    global _global_monitor
    if _global_monitor:
        _global_monitor.stop()


# FastAPI中间件
def metrics_middleware(request, call_next):
    """FastAPI指标中间件"""
    import time

    start = time.perf_counter()

    response = call_next(request)

    duration_ms = (time.perf_counter() - start) * 1000

    api_metrics = APIMetrics(_global_collector)
    api_metrics.record_request(
        endpoint=request.url.path,
        method=request.method,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    return response
