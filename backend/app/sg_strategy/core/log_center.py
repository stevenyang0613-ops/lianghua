"""松岗量化可转债策略 V3.0 日志中心模块

功能:
- 结构化JSON日志
- Logstash输出
- 日志聚合
- 告警集成
- 日志查询
- 日志分析
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import json
import logging
import socket
import threading
import time
import traceback
from queue import Queue
from logging.handlers import RotatingFileHandler, Handler
from contextvars import ContextVar

# 请求上下文
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


# ============ 枚举类型 ============

class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogCategory(str, Enum):
    """日志类别"""
    SYSTEM = "system"
    TRADE = "trade"
    DATA = "data"
    RISK = "risk"
    API = "api"
    BACKTEST = "backtest"
    SIGNAL = "signal"


# ============ 配置类 ============

@dataclass
class LogConfig:
    """日志配置"""
    # 基础配置
    app_name: str = "sg_strategy"
    environment: str = "production"
    version: str = "3.0.0"

    # 文件日志
    log_dir: str = "logs"
    log_file: str = "strategy.log"
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    backup_count: int = 10

    # Logstash配置
    logstash_host: str = "localhost"
    logstash_port: int = 5000
    logstash_enabled: bool = False

    # 日志格式
    json_format: bool = True
    include_trace: bool = True
    include_context: bool = True

    # 性能
    buffer_size: int = 1000
    flush_interval: float = 1.0

    # 告警
    alert_on_error: bool = True
    alert_on_critical: bool = True


# ============ 结构化日志格式化器 ============

class StructuredLogFormatter(logging.Formatter):
    """结构化日志格式化器"""

    def __init__(
        self,
        config: LogConfig = None,
        include_extra: bool = True,
    ):
        self.config = config or LogConfig()
        self.include_extra = include_extra
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录"""
        # 基础字段
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "app": self.config.app_name,
            "env": self.config.environment,
            "version": self.config.version,
            "host": socket.gethostname(),
        }

        # 请求ID
        request_id = request_id_var.get()
        if request_id:
            log_data["request_id"] = request_id

        # 位置信息
        log_data["location"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }

        # 异常信息
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info) if self.config.include_trace else None,
            }

        # 额外字段
        if self.include_extra:
            extra_fields = {}
            for key, value in record.__dict__.items():
                if key not in [
                    "name", "msg", "args", "created", "filename", "funcName",
                    "levelname", "levelno", "lineno", "module", "msecs",
                    "pathname", "process", "processName", "relativeCreated",
                    "stack_info", "exc_info", "exc_text", "thread", "threadName",
                    "message", "asctime",
                ]:
                    try:
                        json.dumps(value)  # 检查是否可序列化
                        extra_fields[key] = value
                    except (TypeError, ValueError):
                        extra_fields[key] = str(value)

            if extra_fields:
                log_data["extra"] = extra_fields

        return json.dumps(log_data, ensure_ascii=False, default=str)


class PlainLogFormatter(logging.Formatter):
    """普通文本格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        # 获取基础格式
        base = super().format(record)

        # 添加额外字段
        extra = []
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime",
            ]:
                continue
            extra.append(f"{key}={value}")

        if extra:
            base += f" | {' '.join(extra)}"

        return base


# ============ Logstash处理器 ============

class LogstashHandler(Handler):
    """Logstash日志处理器"""

    def __init__(
        self,
        host: str,
        port: int,
        config: LogConfig = None,
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.config = config or LogConfig()

        self._buffer: Queue = Queue(maxsize=10000)
        self._socket = None
        self._running = False
        self._worker_thread = None

        # 启动后台线程
        self._start_worker()

    def _start_worker(self):
        """启动后台工作线程"""
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def _worker(self):
        """后台工作线程"""
        while self._running:
            try:
                # 获取日志
                try:
                    log_entry = self._buffer.get(timeout=1.0)
                except Exception:
                    continue

                # 发送
                self._send(log_entry)

            except Exception as e:
                # 避免日志循环
                print(f"LogstashHandler error: {e}")

    def _send(self, log_entry: str):
        """发送日志到Logstash"""
        try:
            if self._socket is None:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.connect((self.host, self.port))

            self._socket.sendall((log_entry + "\n").encode("utf-8"))

        except Exception as e:
            # 连接失败，重置socket
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
            self._socket = None
            print(f"Logstash connection error: {e}")

    def emit(self, record: logging.LogRecord):
        """发送日志"""
        try:
            log_entry = self.format(record)
            self._buffer.put_nowait(log_entry)
        except Exception:
            self.handleError(record)

    def close(self):
        """关闭处理器"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)

        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass

        super().close()


# ============ 日志聚合器 ============

class LogAggregator:
    """日志聚合器"""

    def __init__(self, config: LogConfig = None):
        self.config = config or LogConfig()
        self._counts: Dict[str, int] = {}
        self._errors: List[Dict] = []
        self._lock = threading.Lock()
        self._last_flush = time.time()

    def aggregate(self, log_record: Dict):
        """聚合日志"""
        with self._lock:
            # 计数
            level = log_record.get("level", "UNKNOWN")
            key = f"{level}"
            self._counts[key] = self._counts.get(key, 0) + 1

            # 记录错误
            if level in ["ERROR", "CRITICAL"]:
                self._errors.append({
                    "timestamp": log_record.get("timestamp"),
                    "message": log_record.get("message"),
                    "exception": log_record.get("exception"),
                    "location": log_record.get("location"),
                })

                # 限制数量
                if len(self._errors) > 100:
                    self._errors = self._errors[-100:]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        with self._lock:
            return {
                "counts": dict(self._counts),
                "error_count": len(self._errors),
                "recent_errors": self._errors[-10:],
            }

    def reset(self):
        """重置统计"""
        with self._lock:
            self._counts.clear()
            self._errors.clear()


# ============ 告警日志处理器 ============

class AlertLogHandler(Handler):
    """告警日志处理器"""

    def __init__(
        self,
        config: LogConfig = None,
        alert_callback: Callable[[Dict], None] = None,
    ):
        super().__init__()
        self.config = config or LogConfig()
        self.alert_callback = alert_callback
        self._alert_counts: Dict[str, int] = {}
        self._last_alert: Dict[str, float] = {}
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord):
        """处理日志"""
        try:
            # 只处理ERROR和CRITICAL
            if record.levelno < logging.ERROR:
                return

            # 检查是否启用告警
            if record.levelname == "ERROR" and not self.config.alert_on_error:
                return
            if record.levelname == "CRITICAL" and not self.config.alert_on_critical:
                return

            # 去重：同一错误5分钟内只告警一次
            error_key = f"{record.name}:{record.getMessage()[:100]}"
            now = time.time()

            with self._lock:
                last_time = self._last_alert.get(error_key, 0)
                if now - last_time < 300:  # 5分钟
                    return

                self._last_alert[error_key] = now
                self._alert_counts[error_key] = self._alert_counts.get(error_key, 0) + 1

            # 构建告警
            alert = {
                "timestamp": datetime.now().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "location": {
                    "file": record.filename,
                    "line": record.lineno,
                    "function": record.funcName,
                },
                "count": self._alert_counts.get(error_key, 1),
            }

            if record.exc_info:
                alert["exception"] = {
                    "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                    "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                    "traceback": traceback.format_exception(*record.exc_info) if self.config.include_trace else None,
                }

            # 调用告警回调
            if self.alert_callback:
                try:
                    self.alert_callback(alert)
                except Exception as e:
                    print(f"Alert callback error: {e}")

        except Exception:
            self.handleError(record)


# ============ 日志管理器 ============

class LogManager:
    """日志管理器"""

    _instance = None

    def __new__(cls, config: LogConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: LogConfig = None):
        if self._initialized:
            return

        self.config = config or LogConfig()
        self.aggregator = LogAggregator(self.config)

        # 设置根日志器
        self._setup_root_logger()

        self._initialized = True

    def _setup_root_logger(self):
        """设置根日志器"""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # 清除现有处理器
        root_logger.handlers.clear()

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(PlainLogFormatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
        ))
        root_logger.addHandler(console_handler)

        # 文件处理器
        try:
            import os
            os.makedirs(self.config.log_dir, exist_ok=True)

            file_handler = RotatingFileHandler(
                f"{self.config.log_dir}/{self.config.log_file}",
                maxBytes=self.config.max_file_size,
                backupCount=self.config.backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)

            if self.config.json_format:
                file_handler.setFormatter(StructuredLogFormatter(self.config))
            else:
                file_handler.setFormatter(PlainLogFormatter(
                    "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
                ))

            root_logger.addHandler(file_handler)

        except Exception as e:
            print(f"Failed to setup file handler: {e}")

        # Logstash处理器
        if self.config.logstash_enabled:
            try:
                logstash_handler = LogstashHandler(
                    self.config.logstash_host,
                    self.config.logstash_port,
                    self.config,
                )
                logstash_handler.setLevel(logging.INFO)
                logstash_handler.setFormatter(StructuredLogFormatter(self.config))
                root_logger.addHandler(logstash_handler)

            except Exception as e:
                print(f"Failed to setup Logstash handler: {e}")

    def get_logger(self, name: str) -> logging.Logger:
        """获取日志器"""
        return logging.getLogger(name)

    def add_alert_handler(self, callback: Callable[[Dict], None]):
        """添加告警处理器"""
        root_logger = logging.getLogger()

        alert_handler = AlertLogHandler(self.config, callback)
        alert_handler.setLevel(logging.ERROR)
        root_logger.addHandler(alert_handler)

    def get_stats(self) -> Dict[str, Any]:
        """获取日志统计"""
        return self.aggregator.get_stats()

    def set_request_id(self, request_id: str):
        """设置请求ID"""
        request_id_var.set(request_id)


# ============ 便捷函数 ============

def get_log_manager(config: LogConfig = None) -> LogManager:
    """获取日志管理器"""
    return LogManager(config)


def get_logger(name: str) -> logging.Logger:
    """获取日志器"""
    return logging.getLogger(name)


def init_logging(
    app_name: str = "sg_strategy",
    environment: str = "production",
    log_dir: str = "logs",
    json_format: bool = True,
    logstash_host: str = None,
    logstash_port: int = 5000,
) -> LogManager:
    """初始化日志"""
    config = LogConfig(
        app_name=app_name,
        environment=environment,
        log_dir=log_dir,
        json_format=json_format,
        logstash_host=logstash_host or "localhost",
        logstash_port=logstash_port,
        logstash_enabled=logstash_host is not None,
    )
    return LogManager(config)


# ============ 日志装饰器 ============

def log_execution(logger_name: str = None, level: str = "INFO"):
    """执行日志装饰器"""
    def decorator(func):
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name or func.__module__)

            func_name = func.__qualname__
            logger.log(
                getattr(logging, level.upper()),
                f"[{func_name}] 开始执行",
                extra={"function": func_name, "phase": "start"},
            )

            try:
                result = func(*args, **kwargs)
                logger.log(
                    getattr(logging, level.upper()),
                    f"[{func_name}] 执行成功",
                    extra={"function": func_name, "phase": "end", "status": "success"},
                )
                return result

            except Exception as e:
                logger.error(
                    f"[{func_name}] 执行失败: {e}",
                    extra={"function": func_name, "phase": "end", "status": "failed"},
                    exc_info=True,
                )
                raise

        return wrapper
    return decorator


def log_performance(logger_name: str = None):
    """性能日志装饰器"""
    def decorator(func):
        import functools
        import time

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name or func.__module__)
            func_name = func.__qualname__

            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time

                logger.info(
                    f"[{func_name}] 执行完成",
                    extra={
                        "function": func_name,
                        "elapsed_ms": round(elapsed * 1000, 2),
                        "status": "success",
                    },
                )
                return result

            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"[{func_name}] 执行失败: {e}",
                    extra={
                        "function": func_name,
                        "elapsed_ms": round(elapsed * 1000, 2),
                        "status": "failed",
                    },
                    exc_info=True,
                )
                raise

        return wrapper
    return decorator


# ============ 业务日志助手 ============

class TradeLogger:
    """交易日志助手"""

    def __init__(self):
        self.logger = get_logger("trade")

    def log_signal(self, signal: Dict):
        """记录交易信号"""
        self.logger.info(
            f"交易信号: {signal.get('action')} {signal.get('code')}",
            extra={
                "category": LogCategory.TRADE.value,
                "signal": signal,
            },
        )

    def log_order(self, order: Dict):
        """记录订单"""
        self.logger.info(
            f"下单: {order.get('side')} {order.get('code')} x {order.get('quantity')}@{order.get('price')}",
            extra={
                "category": LogCategory.TRADE.value,
                "order": order,
            },
        )

    def log_trade(self, trade: Dict):
        """记录成交"""
        self.logger.info(
            f"成交: {trade.get('side')} {trade.get('code')} x {trade.get('quantity')}@{trade.get('price')}",
            extra={
                "category": LogCategory.TRADE.value,
                "trade": trade,
            },
        )


class RiskLogger:
    """风控日志助手"""

    def __init__(self):
        self.logger = get_logger("risk")

    def log_alert(self, alert: Dict):
        """记录风险预警"""
        level = alert.get("level", "warning")
        log_level = logging.WARNING if level == "warning" else logging.ERROR

        self.logger.log(
            log_level,
            f"风险预警: {alert.get('message')}",
            extra={
                "category": LogCategory.RISK.value,
                "alert": alert,
            },
        )

    def log_check(self, check_result: Dict):
        """记录风控检查"""
        self.logger.info(
            f"风控检查: {check_result.get('type')} - {check_result.get('result')}",
            extra={
                "category": LogCategory.RISK.value,
                "check": check_result,
            },
        )
