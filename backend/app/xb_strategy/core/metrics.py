"""西部量化可转债策略 V3.0 Prometheus指标模块

功能:
- 自定义指标
- 性能统计
- 资源监控
- Prometheus格式导出
- 指标聚合
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import time
import threading
import os
import psutil
from collections import defaultdict

logger = logging.getLogger(__name__)

# 检查prometheus_client是否可用
try:
    from prometheus_client import Counter, Gauge, Histogram, Summary, CollectorRegistry
    from prometheus_client.core import Info
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


# ============ 枚举类型 ============

class MetricType(str, Enum):
    """指标类型"""
    COUNTER = "counter"       # 计数器
    GAUGE = "gauge"           # 仪表
    HISTOGRAM = "histogram"   # 直方图
    SUMMARY = "summary"       # 摘要
    INFO = "info"             # 信息


# ============ 指标定义 ============

@dataclass
class MetricDefinition:
    """指标定义"""
    name: str
    description: str
    metric_type: MetricType
    labels: List[str] = field(default_factory=list)
    buckets: List[float] = None  # 用于histogram


# 预定义指标
PREDEFINED_METRICS = [
    # 策略指标
    MetricDefinition("sg_nav_current", "当前净值", MetricType.GAUGE),
    MetricDefinition("sg_nav_high", "历史最高净值", MetricType.GAUGE),
    MetricDefinition("sg_drawdown_current", "当前回撤", MetricType.GAUGE),
    MetricDefinition("sg_drawdown_max", "最大回撤", MetricType.GAUGE),

    # 持仓指标
    MetricDefinition("sg_position_count", "持仓数量", MetricType.GAUGE),
    MetricDefinition("sg_position_value", "持仓市值", MetricType.GAUGE),
    MetricDefinition("sg_position_cost", "持仓成本", MetricType.GAUGE),
    MetricDefinition("sg_position_profit", "持仓收益", MetricType.GAUGE),
    MetricDefinition("sg_cash", "现金余额", MetricType.GAUGE),

    # 收益指标
    MetricDefinition("sg_return_daily", "日收益率", MetricType.GAUGE),
    MetricDefinition("sg_return_monthly", "月收益率", MetricType.GAUGE),
    MetricDefinition("sg_return_annual", "年化收益率", MetricType.GAUGE),

    # 风险指标
    MetricDefinition("sg_var_95", "VaR 95%", MetricType.GAUGE),
    MetricDefinition("sg_var_99", "VaR 99%", MetricType.GAUGE),
    MetricDefinition("sg_volatility", "波动率", MetricType.GAUGE),
    MetricDefinition("sg_sharpe_ratio", "夏普比率", MetricType.GAUGE),
    MetricDefinition("sg_concentration", "持仓集中度", MetricType.GAUGE),

    # 信号指标
    MetricDefinition("sg_signals_total", "信号总数", MetricType.COUNTER),
    MetricDefinition("sg_signals_pending", "待处理信号数", MetricType.GAUGE),
    MetricDefinition("sg_signals_executed", "已执行信号数", MetricType.COUNTER),
    MetricDefinition("sg_signals_cancelled", "已取消信号数", MetricType.COUNTER),

    # 交易指标
    MetricDefinition("sg_trades_total", "交易总数", MetricType.COUNTER),
    MetricDefinition("sg_trades_buy", "买入次数", MetricType.COUNTER),
    MetricDefinition("sg_trades_sell", "卖出次数", MetricType.COUNTER),
    MetricDefinition("sg_trade_amount", "交易金额", MetricType.GAUGE),
    MetricDefinition("sg_trade_latency", "交易延迟", MetricType.HISTOGRAM,
                     buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]),

    # 数据指标
    MetricDefinition("sg_data_update_time", "数据更新时间", MetricType.GAUGE),
    MetricDefinition("sg_data_records", "数据记录数", MetricType.GAUGE, ["type"]),
    MetricDefinition("sg_data_sync_duration", "数据同步耗时", MetricType.HISTOGRAM,
                     buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0]),

    # API指标
    MetricDefinition("sg_api_requests_total", "API请求总数", MetricType.COUNTER,
                     ["method", "endpoint", "status"]),
    MetricDefinition("sg_api_request_duration", "API请求耗时", MetricType.HISTOGRAM,
                     labels=["method", "endpoint"],
                     buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]),

    # 系统指标
    MetricDefinition("sg_process_cpu_percent", "CPU使用率", MetricType.GAUGE),
    MetricDefinition("sg_process_memory_bytes", "内存使用量", MetricType.GAUGE),
    MetricDefinition("sg_process_threads", "线程数", MetricType.GAUGE),
    MetricDefinition("sg_process_open_files", "打开文件数", MetricType.GAUGE),
]


# ============ 指标管理器 ============

class MetricsManager:
    """指标管理器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._metrics: Dict[str, Any] = {}
        self._custom_metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._registry = None

        # 初始化指标
        self._init_metrics()

        self._initialized = True

    def _init_metrics(self):
        """初始化指标"""
        if not PROMETHEUS_AVAILABLE:
            logger.warning("[Metrics] prometheus_client未安装，请执行: pip install prometheus_client")
            return

        self._registry = CollectorRegistry()

        for metric_def in PREDEFINED_METRICS:
            self._create_metric(metric_def)

    def _create_metric(self, metric_def: MetricDefinition):
        """创建指标"""
        if not PROMETHEUS_AVAILABLE:
            return

        name = metric_def.name
        desc = metric_def.description
        labels = metric_def.labels

        try:
            if metric_def.metric_type == MetricType.COUNTER:
                metric = Counter(name, desc, labels, registry=self._registry)

            elif metric_def.metric_type == MetricType.GAUGE:
                metric = Gauge(name, desc, labels, registry=self._registry)

            elif metric_def.metric_type == MetricType.HISTOGRAM:
                buckets = metric_def.buckets or [0.1, 0.5, 1.0, 5.0, 10.0]
                metric = Histogram(name, desc, labels, buckets=buckets, registry=self._registry)

            elif metric_def.metric_type == MetricType.SUMMARY:
                metric = Summary(name, desc, labels, registry=self._registry)

            elif metric_def.metric_type == MetricType.INFO:
                metric = Info(name, desc, registry=self._registry)

            else:
                return

            self._metrics[name] = {
                "metric": metric,
                "type": metric_def.metric_type,
                "labels": labels,
            }

        except Exception as e:
            logger.error(f"[Metrics] 创建指标失败 {name}: {e}")

    def create_custom_metric(
        self,
        name: str,
        description: str,
        metric_type: MetricType,
        labels: List[str] = None,
        buckets: List[float] = None,
    ):
        """创建自定义指标"""
        metric_def = MetricDefinition(
            name=name,
            description=description,
            metric_type=metric_type,
            labels=labels or [],
            buckets=buckets,
        )
        self._create_metric(metric_def)
        self._custom_metrics[name] = True

    def _get_metric(self, name: str):
        """获取指标"""
        if name in self._metrics:
            return self._metrics[name]["metric"]
        return None

    def inc_counter(self, name: str, value: float = 1, labels: Dict[str, str] = None):
        """增加计数器"""
        metric = self._get_metric(name)
        if metric is None:
            return

        try:
            if labels:
                metric.labels(**labels).inc(value)
            else:
                metric.inc(value)
        except Exception as e:
            logger.error(f"[Metrics] 增加计数器失败 {name}: {e}")

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """设置仪表值"""
        metric = self._get_metric(name)
        if metric is None:
            return

        try:
            if labels:
                metric.labels(**labels).set(value)
            else:
                metric.set(value)
        except Exception as e:
            logger.error(f"[Metrics] 设置仪表失败 {name}: {e}")

    def observe_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """记录直方图观测值"""
        metric = self._get_metric(name)
        if metric is None:
            return

        try:
            if labels:
                metric.labels(**labels).observe(value)
            else:
                metric.observe(value)
        except Exception as e:
            logger.error(f"[Metrics] 记录直方图失败 {name}: {e}")

    def observe_summary(self, name: str, value: float, labels: Dict[str, str] = None):
        """记录摘要观测值"""
        metric = self._get_metric(name)
        if metric is None:
            return

        try:
            if labels:
                metric.labels(**labels).observe(value)
            else:
                metric.observe(value)
        except Exception as e:
            logger.error(f"[Metrics] 记录摘要失败 {name}: {e}")

    def get_metrics_output(self) -> str:
        """获取Prometheus格式输出"""
        if not PROMETHEUS_AVAILABLE:
            return "# prometheus_client not installed\n"

        try:
            from prometheus_client import generate_latest
            return generate_latest(self._registry).decode('utf-8')
        except Exception as e:
            return f"# Error generating metrics: {e}\n"

    def collect_system_metrics(self):
        """收集系统指标"""
        try:
            process = psutil.Process(os.getpid())

            # CPU使用率
            self.set_gauge("sg_process_cpu_percent", process.cpu_percent())

            # 内存使用
            memory_info = process.memory_info()
            self.set_gauge("sg_process_memory_bytes", memory_info.rss)

            # 线程数
            self.set_gauge("sg_process_threads", process.num_threads())

            # 打开文件数
            try:
                self.set_gauge("sg_process_open_files", len(process.open_files()))
            except Exception:
                pass

        except Exception as e:
            logger.error(f"[Metrics] 收集系统指标失败: {e}")

    def get_all_metrics(self) -> Dict[str, Any]:
        """获取所有指标值"""
        result = {}

        for name, info in self._metrics.items():
            metric = info["metric"]
            metric_type = info["type"]

            try:
                if metric_type == MetricType.GAUGE:
                    # 简化：只获取无标签的值
                    result[name] = metric._value.get() if hasattr(metric, '_value') else None
                elif metric_type == MetricType.COUNTER:
                    result[name] = metric._value.get() if hasattr(metric, '_value') else None
            except Exception:
                pass

        return result


# ============ 指标装饰器 ============

def track_time(metric_name: str = None):
    """跟踪执行时间装饰器"""
    def decorator(func):
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.time() - start
                manager = get_metrics_manager()
                name = metric_name or f"sg_func_duration_{func.__name__}"
                manager.observe_histogram(name, duration)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = time.time() - start
                manager = get_metrics_manager()
                name = metric_name or f"sg_func_duration_{func.__name__}"
                manager.observe_histogram(name, duration)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def count_calls(metric_name: str = None):
    """计数调用装饰器"""
    def decorator(func):
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            manager = get_metrics_manager()
            name = metric_name or f"sg_func_calls_{func.__name__}"
            manager.inc_counter(name)
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            manager = get_metrics_manager()
            name = metric_name or f"sg_func_calls_{func.__name__}"
            manager.inc_counter(name)
            return await func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


# ============ 策略指标收集器 ============

class StrategyMetricsCollector:
    """策略指标收集器"""

    def __init__(self, metrics_manager: MetricsManager = None):
        self.metrics = metrics_manager or get_metrics_manager()

    def update_portfolio_metrics(
        self,
        nav: float,
        nav_high: float,
        drawdown: float,
        drawdown_max: float,
    ):
        """更新组合指标"""
        self.metrics.set_gauge("sg_nav_current", nav)
        self.metrics.set_gauge("sg_nav_high", nav_high)
        self.metrics.set_gauge("sg_drawdown_current", drawdown)
        self.metrics.set_gauge("sg_drawdown_max", drawdown_max)

    def update_position_metrics(
        self,
        position_count: int,
        position_value: float,
        position_cost: float,
        cash: float,
    ):
        """更新持仓指标"""
        self.metrics.set_gauge("sg_position_count", position_count)
        self.metrics.set_gauge("sg_position_value", position_value)
        self.metrics.set_gauge("sg_position_cost", position_cost)
        self.metrics.set_gauge("sg_cash", cash)

        profit = position_value - position_cost
        self.metrics.set_gauge("sg_position_profit", profit)

    def update_return_metrics(
        self,
        daily_return: float,
        monthly_return: float,
        annual_return: float,
    ):
        """更新收益指标"""
        self.metrics.set_gauge("sg_return_daily", daily_return)
        self.metrics.set_gauge("sg_return_monthly", monthly_return)
        self.metrics.set_gauge("sg_return_annual", annual_return)

    def update_risk_metrics(
        self,
        var_95: float,
        var_99: float,
        volatility: float,
        sharpe: float,
        concentration: float,
    ):
        """更新风险指标"""
        self.metrics.set_gauge("sg_var_95", var_95)
        self.metrics.set_gauge("sg_var_99", var_99)
        self.metrics.set_gauge("sg_volatility", volatility)
        self.metrics.set_gauge("sg_sharpe_ratio", sharpe)
        self.metrics.set_gauge("sg_concentration", concentration)

    def record_trade(
        self,
        side: str,
        amount: float,
        latency: float,
    ):
        """记录交易"""
        self.metrics.inc_counter("sg_trades_total")
        self.metrics.inc_counter(f"sg_trades_{side}")
        self.metrics.set_gauge("sg_trade_amount", amount)
        self.metrics.observe_histogram("sg_trade_latency", latency)

    def record_signal(self, status: str):
        """记录信号"""
        self.metrics.inc_counter("sg_signals_total")

        if status == "pending":
            self.metrics.inc_counter("sg_signals_pending")
        elif status == "executed":
            self.metrics.inc_counter("sg_signals_executed")
        elif status == "cancelled":
            self.metrics.inc_counter("sg_signals_cancelled")

    def record_api_request(
        self,
        method: str,
        endpoint: str,
        status: int,
        duration: float,
    ):
        """记录API请求"""
        self.metrics.inc_counter(
            "sg_api_requests_total",
            labels={"method": method, "endpoint": endpoint, "status": str(status)},
        )
        self.metrics.observe_histogram(
            "sg_api_request_duration",
            duration,
            labels={"method": method, "endpoint": endpoint},
        )


# ============ FastAPI中间件 ============

class PrometheusMiddleware:
    """Prometheus中间件"""

    def __init__(self, app, metrics_manager: MetricsManager = None):
        self.app = app
        self.metrics = metrics_manager or get_metrics_manager()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]

        start_time = time.time()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status = message["status"]
                duration = time.time() - start_time

                self.metrics.record_api_request(
                    method=method,
                    endpoint=path,
                    status=status,
                    duration=duration,
                )

            await send(message)

        await self.app(scope, receive, send_wrapper)


# ============ 便捷函数 ============

def get_metrics_manager() -> MetricsManager:
    """获取指标管理器"""
    return MetricsManager()


def get_strategy_metrics_collector() -> StrategyMetricsCollector:
    """获取策略指标收集器"""
    return StrategyMetricsCollector()


def init_metrics() -> MetricsManager:
    """初始化指标系统"""
    return MetricsManager()
