"""
Prometheus 监控指标
"""

from prometheus_client import Counter, Histogram, Gauge, Info
from functools import wraps
import time

# ==================== HTTP 指标 ====================

HTTP_REQUESTS_TOTAL = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

HTTP_REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    'http_requests_in_progress',
    'HTTP requests currently in progress',
    ['method', 'endpoint']
)

# ==================== 业务指标 ====================

TRADES_TOTAL = Counter(
    'trades_total',
    'Total number of trades',
    ['account_id', 'symbol', 'side']
)

TRADE_VALUE = Counter(
    'trade_value_total',
    'Total trade value',
    ['account_id', 'symbol']
)

ORDERS_TOTAL = Counter(
    'orders_total',
    'Total number of orders',
    ['account_id', 'status']
)

ORDER_DURATION = Histogram(
    'order_duration_seconds',
    'Order processing duration',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)

# ==================== 市场数据指标 ====================

QUOTES_RECEIVED = Counter(
    'quotes_received_total',
    'Total quotes received',
    ['symbol']
)

QUOTES_LATENCY = Histogram(
    'quotes_latency_seconds',
    'Quote latency',
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

KLINE_UPDATES = Counter(
    'kline_updates_total',
    'Total K-line updates',
    ['symbol', 'period']
)

# ==================== 策略指标 ====================

STRATEGY_RUNS = Counter(
    'strategy_runs_total',
    'Total strategy runs',
    ['strategy_id', 'status']
)

STRATEGY_DURATION = Histogram(
    'strategy_duration_seconds',
    'Strategy execution duration',
    ['strategy_id'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0]
)

BACKTEST_DURATION = Histogram(
    'backtest_duration_seconds',
    'Backtest duration',
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
)

# ==================== 系统指标 ====================

DB_CONNECTIONS = Gauge(
    'db_connections',
    'Database connections'
)

DB_QUERY_DURATION = Histogram(
    'db_query_duration_seconds',
    'Database query duration',
    ['operation'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

CACHE_HITS = Counter(
    'cache_hits_total',
    'Cache hits'
)

CACHE_MISSES = Counter(
    'cache_misses_total',
    'Cache misses'
)

WEBSOCKET_CONNECTIONS = Gauge(
    'websocket_connections',
    'Active WebSocket connections'
)

# ==================== 应用信息 ====================

APP_INFO = Info(
    'app_info',
    'Application information'
)
APP_INFO.info({
    'version': '1.0.0',
    'name': 'lianghua',
})


# ==================== 装饰器 ====================

def track_http_request(method: str, endpoint: str):
    """HTTP 请求追踪装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()

            start_time = time.time()
            status = 200

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = 500
                raise
            finally:
                duration = time.time() - start_time

                HTTP_REQUESTS_TOTAL.labels(
                    method=method,
                    endpoint=endpoint,
                    status=status
                ).inc()

                HTTP_REQUEST_DURATION.labels(
                    method=method,
                    endpoint=endpoint
                ).observe(duration)

                HTTP_REQUESTS_IN_PROGRESS.labels(
                    method=method,
                    endpoint=endpoint
                ).dec()

        return wrapper
    return decorator


def track_db_query(operation: str):
    """数据库查询追踪装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                DB_QUERY_DURATION.labels(operation=operation).observe(duration)

        return wrapper
    return decorator


def track_strategy(strategy_id: str):
    """策略执行追踪装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time

                STRATEGY_RUNS.labels(
                    strategy_id=strategy_id,
                    status=status
                ).inc()

                STRATEGY_DURATION.labels(
                    strategy_id=strategy_id
                ).observe(duration)

        return wrapper
    return decorator


# ==================== 指标记录函数 ====================

def record_trade(account_id: str, symbol: str, side: str, value: float):
    """记录交易"""
    TRADES_TOTAL.labels(
        account_id=account_id,
        symbol=symbol,
        side=side
    ).inc()

    TRADE_VALUE.labels(
        account_id=account_id,
        symbol=symbol
    ).inc(value)


def record_order(account_id: str, status: str):
    """记录订单"""
    ORDERS_TOTAL.labels(
        account_id=account_id,
        status=status
    ).inc()


def record_quote(symbol: str, latency: float):
    """记录行情"""
    QUOTES_RECEIVED.labels(symbol=symbol).inc()
    QUOTES_LATENCY.observe(latency)


def record_kline_update(symbol: str, period: str):
    """记录 K 线更新"""
    KLINE_UPDATES.labels(symbol=symbol, period=period).inc()


def record_cache_hit():
    """记录缓存命中"""
    CACHE_HITS.inc()


def record_cache_miss():
    """记录缓存未命中"""
    CACHE_MISSES.inc()


def set_db_connections(count: int):
    """设置数据库连接数"""
    DB_CONNECTIONS.set(count)


def set_websocket_connections(count: int):
    """设置 WebSocket 连接数"""
    WEBSOCKET_CONNECTIONS.set(count)


# ==================== Prometheus 中间件 ====================

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Prometheus 监控中间件"""

    async def dispatch(self, request: Request, call_next):
        method = request.method
        endpoint = request.url.path

        # 排除 metrics 端点
        if endpoint == "/metrics":
            return await call_next(request)

        HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()

        start_time = time.time()
        status = 200

        try:
            response: Response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            status = 500
            raise
        finally:
            duration = time.time() - start_time

            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                endpoint=endpoint,
                status=status
            ).inc()

            HTTP_REQUEST_DURATION.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)

            HTTP_REQUESTS_IN_PROGRESS.labels(
                method=method,
                endpoint=endpoint
            ).dec()
