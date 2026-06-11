"""
Prometheus监控配置

提供：
- 指标导出端点
- 自定义指标定义
- 监控中间件
"""

from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

# 创建独立的注册表
REGISTRY = CollectorRegistry()

# ==================== 系统指标 ====================

SYSTEM_INFO = Info(
    'lianghua_system',
    '系统信息',
    registry=REGISTRY,
)
SYSTEM_INFO.info({
    'version': '3.0.0',
    'service': 'lianghua-backend',
})

# CPU和内存
CPU_USAGE = Gauge(
    'lianghua_cpu_usage_percent',
    'CPU使用率',
    registry=REGISTRY,
)

MEMORY_USAGE = Gauge(
    'lianghua_memory_usage_mb',
    '内存使用量(MB)',
    registry=REGISTRY,
)

MEMORY_PERCENT = Gauge(
    'lianghua_memory_usage_percent',
    '内存使用率',
    registry=REGISTRY,
)

ACTIVE_THREADS = Gauge(
    'lianghua_active_threads',
    '活跃线程数',
    registry=REGISTRY,
)

# ==================== HTTP请求指标 ====================

HTTP_REQUESTS_TOTAL = Counter(
    'lianghua_http_requests_total',
    'HTTP请求总数',
    ['method', 'endpoint', 'status'],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    'lianghua_http_request_duration_seconds',
    'HTTP请求耗时',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    'lianghua_http_requests_in_progress',
    '正在处理的请求数',
    ['method', 'endpoint'],
    registry=REGISTRY,
)

# ==================== 策略指标 ====================

STRATEGY_EXECUTIONS = Counter(
    'lianghua_strategy_executions_total',
    '策略执行次数',
    ['strategy', 'status'],
    registry=REGISTRY,
)

STRATEGY_DURATION = Histogram(
    'lianghua_strategy_execution_duration_seconds',
    '策略执行耗时',
    ['strategy'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    registry=REGISTRY,
)

STRATEGY_SIGNALS = Counter(
    'lianghua_strategy_signals_total',
    '策略信号数',
    ['strategy', 'action'],
    registry=REGISTRY,
)

# ==================== 交易指标 ====================

TRADES_TOTAL = Counter(
    'lianghua_trades_total',
    '交易总数',
    ['action', 'status'],
    registry=REGISTRY,
)

TRADE_AMOUNT = Counter(
    'lianghua_trade_amount_total',
    '交易金额',
    ['action'],
    registry=REGISTRY,
)

TRADE_LATENCY = Histogram(
    'lianghua_trade_latency_seconds',
    '交易延迟',
    ['action'],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
    registry=REGISTRY,
)

POSITION_COUNT = Gauge(
    'lianghua_position_count',
    '持仓数量',
    registry=REGISTRY,
)

ACCOUNT_VALUE = Gauge(
    'lianghua_account_value',
    '账户价值',
    registry=REGISTRY,
)

# ==================== 回测指标 ====================

BACKTEST_RUNS = Counter(
    'lianghua_backtest_runs_total',
    '回测运行次数',
    ['strategy'],
    registry=REGISTRY,
)

BACKTEST_DURATION = Histogram(
    'lianghua_backtest_duration_seconds',
    '回测耗时',
    ['strategy'],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
    registry=REGISTRY,
)

BACKTEST_RETURN = Histogram(
    'lianghua_backtest_return_percent',
    '回测收益率',
    ['strategy'],
    buckets=[-50, -30, -20, -10, -5, 0, 5, 10, 20, 30, 50, 100],
    registry=REGISTRY,
)

# ==================== 数据源指标 ====================

DATASOURCE_REQUESTS = Counter(
    'lianghua_datasource_requests_total',
    '数据源请求数',
    ['source', 'status'],
    registry=REGISTRY,
)

DATASOURCE_LATENCY = Histogram(
    'lianghua_datasource_latency_seconds',
    '数据源延迟',
    ['source'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    registry=REGISTRY,
)

DATASOURCE_CONNECTED = Gauge(
    'lianghua_datasource_connected',
    '数据源连接状态',
    ['source'],
    registry=REGISTRY,
)

# ==================== 缓存指标 ====================

CACHE_HITS = Counter(
    'lianghua_cache_hits_total',
    '缓存命中次数',
    ['cache_name'],
    registry=REGISTRY,
)

CACHE_MISSES = Counter(
    'lianghua_cache_misses_total',
    '缓存未命中次数',
    ['cache_name'],
    registry=REGISTRY,
)

CACHE_SIZE = Gauge(
    'lianghua_cache_size',
    '缓存大小',
    ['cache_name'],
    registry=REGISTRY,
)

# ==================== WebSocket指标 ====================

WS_CONNECTIONS = Gauge(
    'lianghua_websocket_connections',
    'WebSocket连接数',
    registry=REGISTRY,
)

WS_MESSAGES = Counter(
    'lianghua_websocket_messages_total',
    'WebSocket消息数',
    ['type'],
    registry=REGISTRY,
)

# ==================== 导出函数 ====================

def get_metrics() -> bytes:
    """获取Prometheus格式指标"""
    return generate_latest(REGISTRY)


def metrics_endpoint() -> Response:
    """FastAPI指标端点"""
    return Response(
        content=get_metrics(),
        media_type=CONTENT_TYPE_LATEST,
    )


def record_http_request(method: str, endpoint: str, status: int, duration: float) -> None:
    """记录HTTP请求"""
    HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)


def record_strategy_execution(strategy: str, duration: float, success: bool, signals: int = 0) -> None:
    """记录策略执行"""
    status = 'success' if success else 'failure'
    STRATEGY_EXECUTIONS.labels(strategy=strategy, status=status).inc()
    STRATEGY_DURATION.labels(strategy=strategy).observe(duration)
    if signals > 0:
        STRATEGY_SIGNALS.labels(strategy=strategy, action='generated').inc(signals)


def record_trade(action: str, amount: float, latency: float, success: bool) -> None:
    """记录交易"""
    status = 'success' if success else 'failure'
    TRADES_TOTAL.labels(action=action, status=status).inc()
    if success:
        TRADE_AMOUNT.labels(action=action).inc(amount)
    TRADE_LATENCY.labels(action=action).observe(latency)


def update_system_metrics(cpu: float, memory_mb: float, memory_percent: float, threads: int) -> None:
    """更新系统指标"""
    CPU_USAGE.set(cpu)
    MEMORY_USAGE.set(memory_mb)
    MEMORY_PERCENT.set(memory_percent)
    ACTIVE_THREADS.set(threads)


def update_datasource_status(source: str, connected: bool) -> None:
    """更新数据源状态"""
    DATASOURCE_CONNECTED.labels(source=source).set(1 if connected else 0)


def record_cache_operation(cache_name: str, hit: bool) -> None:
    """记录缓存操作"""
    if hit:
        CACHE_HITS.labels(cache_name=cache_name).inc()
    else:
        CACHE_MISSES.labels(cache_name=cache_name).inc()
