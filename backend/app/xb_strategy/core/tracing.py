"""西部量化可转债策略 V3.0 分布式追踪模块

功能:
- OpenTelemetry集成
- 请求追踪
- 性能分析
- 链路监控
- Span管理
- 追踪上下文
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import time
import functools
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 检查OpenTelemetry是否可用
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from opentelemetry.trace import Status, StatusCode, SpanKind
    from opentelemetry.context import Context
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False

# 检查导出器
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    OTLP_EXPORTER_AVAILABLE = True
except ImportError:
    OTLP_EXPORTER_AVAILABLE = False

try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    JAEGER_EXPORTER_AVAILABLE = True
except ImportError:
    JAEGER_EXPORTER_AVAILABLE = False


# ============ 枚举类型 ============

class SpanKind(str, Enum):
    """Span类型"""
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class TraceStatus(str, Enum):
    """追踪状态"""
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


# ============ 配置类 ============

@dataclass
class TracingConfig:
    """追踪配置"""
    # 服务信息
    service_name: str = "xb_strategy"
    service_version: str = "3.0.0"
    environment: str = "production"

    # 导出器配置
    exporter_type: str = "console"  # console, jaeger, otlp
    jaeger_host: str = "localhost"
    jaeger_port: int = 6831
    otlp_endpoint: str = "localhost:4317"

    # 采样配置
    sampling_rate: float = 1.0  # 采样率 0.0-1.0

    # 批处理配置
    batch_export: bool = True
    export_timeout: int = 30000  # 毫秒


# ============ 追踪管理器 ============

class TracingManager:
    """追踪管理器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.config = TracingConfig()
        self._tracer = None
        self._provider = None

        if OPENTELEMETRY_AVAILABLE:
            self._init_tracer()

        self._initialized = True

    def _init_tracer(self):
        """初始化追踪器"""
        # 创建资源
        resource = Resource.create({
            SERVICE_NAME: self.config.service_name,
            "service.version": self.config.service_version,
            "deployment.environment": self.config.environment,
        })

        # 创建TracerProvider
        self._provider = TracerProvider(resource=resource)

        # 添加导出器
        self._add_exporter()

        # 设置全局TracerProvider
        trace.set_tracer_provider(self._provider)

        # 获取Tracer
        self._tracer = trace.get_tracer(
            self.config.service_name,
            self.config.service_version,
        )

        logger.info(f"[Tracing] 追踪器初始化完成: {self.config.service_name}")

    def _add_exporter(self):
        """添加导出器"""
        if self.config.exporter_type == "jaeger" and JAEGER_EXPORTER_AVAILABLE:
            exporter = JaegerExporter(
                agent_host_name=self.config.jaeger_host,
                agent_port=self.config.jaeger_port,
            )
            processor = BatchSpanProcessor(exporter)
            self._provider.add_span_processor(processor)
            logger.info(f"[Tracing] 使用Jaeger导出器: {self.config.jaeger_host}:{self.config.jaeger_port}")

        elif self.config.exporter_type == "otlp" and OTLP_EXPORTER_AVAILABLE:
            exporter = OTLPSpanExporter(
                endpoint=self.config.otlp_endpoint,
            )
            processor = BatchSpanProcessor(exporter)
            self._provider.add_span_processor(processor)
            logger.info(f"[Tracing] 使用OTLP导出器: {self.config.otlp_endpoint}")

        else:
            # 控制台导出器
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            exporter = ConsoleSpanExporter()
            processor = SimpleSpanProcessor(exporter)
            self._provider.add_span_processor(processor)
            logger.info("[Tracing] 使用控制台导出器")

    @property
    def tracer(self):
        """获取追踪器"""
        return self._tracer

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Dict[str, Any] = None,
    ):
        """开始Span"""
        if not OPENTELEMETRY_AVAILABLE or not self._tracer:
            return NoOpSpan()

        span_kind_map = {
            SpanKind.INTERNAL: trace.SpanKind.INTERNAL,
            SpanKind.SERVER: trace.SpanKind.SERVER,
            SpanKind.CLIENT: trace.SpanKind.CLIENT,
            SpanKind.PRODUCER: trace.SpanKind.PRODUCER,
            SpanKind.CONSUMER: trace.SpanKind.CONSUMER,
        }

        span = self._tracer.start_as_current_span(
            name,
            kind=span_kind_map.get(kind, trace.SpanKind.INTERNAL),
        )

        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        return SpanWrapper(span)

    @contextmanager
    def span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Dict[str, Any] = None,
    ):
        """Span上下文管理器"""
        span = self.start_span(name, kind, attributes)
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        finally:
            span.end()

    def inject_context(self, carrier: Dict[str, str] = None) -> Dict[str, str]:
        """注入追踪上下文"""
        if not OPENTELEMETRY_AVAILABLE:
            return {}

        carrier = carrier or {}
        propagator = TraceContextTextMapPropagator()
        propagator.inject(carrier)
        return carrier

    def extract_context(self, carrier: Dict[str, str]):
        """提取追踪上下文"""
        if not OPENTELEMETRY_AVAILABLE:
            return None

        propagator = TraceContextTextMapPropagator()
        return propagator.extract(carrier)

    def record_event(
        self,
        name: str,
        attributes: Dict[str, Any] = None,
    ):
        """记录事件"""
        if not OPENTELEMETRY_AVAILABLE:
            return

        current_span = trace.get_current_span()
        if current_span:
            current_span.add_event(name, attributes or {})


# ============ Span包装器 ============

class SpanWrapper:
    """Span包装器"""

    def __init__(self, span):
        self._span = span

    def set_attribute(self, key: str, value: Any):
        """设置属性"""
        if self._span:
            self._span.set_attribute(key, value)

    def set_attributes(self, attributes: Dict[str, Any]):
        """批量设置属性"""
        if self._span:
            for key, value in attributes.items():
                self._span.set_attribute(key, value)

    def add_event(self, name: str, attributes: Dict[str, Any] = None):
        """添加事件"""
        if self._span:
            self._span.add_event(name, attributes or {})

    def record_exception(self, exception: Exception, attributes: Dict[str, Any] = None):
        """记录异常"""
        if self._span:
            self._span.record_exception(exception, attributes or {})

    def set_status(self, status: TraceStatus, description: str = ""):
        """设置状态"""
        if not self._span:
            return

        status_map = {
            TraceStatus.UNSET: StatusCode.UNSET,
            TraceStatus.OK: StatusCode.OK,
            TraceStatus.ERROR: StatusCode.ERROR,
        }
        self._span.set_status(Status(status_map.get(status, StatusCode.UNSET), description))

    def end(self):
        """结束Span"""
        if self._span:
            self._span.end()

    @property
    def context(self):
        """获取Span上下文"""
        if self._span:
            return self._span.get_span_context()
        return None

    @property
    def trace_id(self) -> str:
        """获取Trace ID"""
        if self._span:
            ctx = self._span.get_span_context()
            return format(ctx.trace_id, '032x')
        return ""

    @property
    def span_id(self) -> str:
        """获取Span ID"""
        if self._span:
            ctx = self._span.get_span_context()
            return format(ctx.span_id, '016x')
        return ""


class NoOpSpan:
    """空操作Span"""

    def set_attribute(self, key: str, value: Any):
        pass

    def set_attributes(self, attributes: Dict[str, Any]):
        pass

    def add_event(self, name: str, attributes: Dict[str, Any] = None):
        pass

    def record_exception(self, exception: Exception, attributes: Dict[str, Any] = None):
        pass

    def set_status(self, status: TraceStatus, description: str = ""):
        pass

    def end(self):
        pass

    @property
    def context(self):
        return None

    @property
    def trace_id(self) -> str:
        return ""

    @property
    def span_id(self) -> str:
        return ""


# ============ 追踪装饰器 ============

def traced(
    name: str = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Dict[str, Any] = None,
):
    """追踪装饰器"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            manager = get_tracing_manager()
            span_name = name or f"{func.__module__}.{func.__name__}"

            with manager.span(span_name, kind, attributes):
                return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            manager = get_tracing_manager()
            span_name = name or f"{func.__module__}.{func.__name__}"

            with manager.span(span_name, kind, attributes):
                return await func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def traced_async(
    name: str = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Dict[str, Any] = None,
):
    """异步追踪装饰器"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            manager = get_tracing_manager()
            span_name = name or f"{func.__module__}.{func.__name__}"

            with manager.span(span_name, kind, attributes):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


# ============ FastAPI中间件 ============

class TracingMiddleware:
    """追踪中间件"""

    def __init__(self, app, tracing_manager: TracingManager = None):
        self.app = app
        self.tracing = tracing_manager or get_tracing_manager()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 提取追踪上下文
        headers = dict(scope.get("headers", []))
        carrier = {k.decode(): v.decode() for k, v in headers.items()}
        ctx = self.tracing.extract_context(carrier)

        # 开始Span
        method = scope["method"]
        path = scope["path"]

        with self.tracing.span(
            f"HTTP {method} {path}",
            kind=SpanKind.SERVER,
            attributes={
                "http.method": method,
                "http.url": str(scope.get("query_string", b"").decode()),
                "http.route": path,
            },
        ) as span:
            # 设置Span上下文
            span.set_attribute("http.status_code", 200)

            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    status = message["status"]
                    span.set_attribute("http.status_code", status)

                    if status >= 400:
                        span.set_status(TraceStatus.ERROR)

                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                span.record_exception(e)
                span.set_status(TraceStatus.ERROR)
                raise


# ============ 便捷函数 ============

def get_tracing_manager() -> TracingManager:
    """获取追踪管理器"""
    return TracingManager()


def init_tracing(
    service_name: str = "xb_strategy",
    exporter_type: str = "console",
    jaeger_host: str = "localhost",
    jaeger_port: int = 6831,
    otlp_endpoint: str = "localhost:4317",
) -> TracingManager:
    """初始化追踪"""
    manager = TracingManager()
    manager.config.service_name = service_name
    manager.config.exporter_type = exporter_type
    manager.config.jaeger_host = jaeger_host
    manager.config.jaeger_port = jaeger_port
    manager.config.otlp_endpoint = otlp_endpoint

    if OPENTELEMETRY_AVAILABLE and manager._provider:
        manager._init_tracer()

    return manager


def get_current_trace_id() -> str:
    """获取当前Trace ID"""
    if not OPENTELEMETRY_AVAILABLE:
        return ""

    span = trace.get_current_span()
    if span:
        ctx = span.get_span_context()
        return format(ctx.trace_id, '032x')
    return ""


def get_current_span_id() -> str:
    """获取当前Span ID"""
    if not OPENTELEMETRY_AVAILABLE:
        return ""

    span = trace.get_current_span()
    if span:
        ctx = span.get_span_context()
        return format(ctx.span_id, '016x')
    return ""
