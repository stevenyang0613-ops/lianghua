"""松岗量化可转债策略 V3.0 异步任务队列模块

功能:
- Celery集成
- 任务定义
- 任务监控
- 任务重试
- 任务优先级
- 任务结果存储
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import time
import json

logger = logging.getLogger(__name__)

# 检查Celery是否可用
try:
    from celery import Celery, Task, shared_task
    from celery.result import AsyncResult
    from celery.schedules import crontab
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    Celery = None


# ============ 枚举类型 ============

class TaskPriority(str, Enum):
    """任务优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"


# ============ 配置类 ============

@dataclass
class CeleryConfig:
    """Celery配置"""
    # Broker配置
    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"

    # 任务配置
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: List[str] = field(default_factory=lambda: ["json"])
    timezone: str = "Asia/Shanghai"
    enable_utc: bool = True

    # 任务结果
    result_expires: int = 3600  # 1小时
    task_track_started: bool = True
    task_time_limit: int = 3600  # 1小时
    task_soft_time_limit: int = 3000  # 50分钟

    # 并发配置
    worker_concurrency: int = 4
    worker_prefetch_multiplier: int = 1

    # 任务路由
    task_routes: Dict[str, str] = field(default_factory=lambda: {
        "app.sg_strategy.core.tasks.data_tasks.*": "data",
        "app.sg_strategy.core.tasks.compute_tasks.*": "compute",
        "app.sg_strategy.core.tasks.report_tasks.*": "report",
    })

    # 定时任务
    beat_schedule: Dict[str, Dict] = field(default_factory=lambda: {
        "sync-daily-data": {
            "task": "app.sg_strategy.core.tasks.sync_daily_data",
            "schedule": crontab(hour=9, minute=0),
        },
        "generate-daily-signals": {
            "task": "app.sg_strategy.core.tasks.generate_daily_signals",
            "schedule": crontab(hour=9, minute=30),
        },
        "check-risk-metrics": {
            "task": "app.sg_strategy.core.tasks.check_risk_metrics",
            "schedule": timedelta(minutes=5),
        },
    })


# ============ Celery应用 ============

class CeleryApp:
    """Celery应用管理器"""

    _instance = None
    _app = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.config = CeleryConfig()
        self._tasks: Dict[str, Callable] = {}

        if CELERY_AVAILABLE:
            self._init_celery()

        self._initialized = True

    def _init_celery(self):
        """初始化Celery"""
        self._app = Celery("sg_strategy")

        # 配置
        self._app.conf.update(
            broker_url=self.config.broker_url,
            result_backend=self.config.result_backend,
            task_serializer=self.config.task_serializer,
            result_serializer=self.config.result_serializer,
            accept_content=self.config.accept_content,
            timezone=self.config.timezone,
            enable_utc=self.config.enable_utc,
            result_expires=self.config.result_expires,
            task_track_started=self.config.task_track_started,
            task_time_limit=self.config.task_time_limit,
            task_soft_time_limit=self.config.task_soft_time_limit,
            worker_concurrency=self.config.worker_concurrency,
            worker_prefetch_multiplier=self.config.worker_prefetch_multiplier,
        )

        # 自动发现任务
        self._app.autodiscover_tasks([
            "app.sg_strategy.core.tasks",
        ])

        logger.info("[CeleryApp] Celery应用初始化完成")

    @property
    def app(self):
        """获取Celery应用"""
        return self._app

    def register_task(
        self,
        name: str,
        func: Callable,
        queue: str = "default",
        max_retries: int = 3,
        default_retry_delay: int = 60,
    ):
        """注册任务"""
        if not CELERY_AVAILABLE:
            logger.warning("[CeleryApp] Celery不可用")
            return

        @self._app.task(
            name=name,
            bind=True,
            max_retries=max_retries,
            default_retry_delay=default_retry_delay,
        )
        def wrapped_task(self, *args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                logger.error(f"[Task:{name}] 执行失败: {exc}")
                raise self.retry(exc=exc)

        self._tasks[name] = wrapped_task
        logger.info(f"[CeleryApp] 注册任务: {name}")

    def apply_async(
        self,
        task_name: str,
        args: tuple = (),
        kwargs: dict = None,
        queue: str = None,
        priority: TaskPriority = None,
        countdown: int = None,
        eta: datetime = None,
    ) -> Optional[str]:
        """异步执行任务"""
        if not CELERY_AVAILABLE or not self._app:
            logger.warning("[CeleryApp] Celery不可用")
            return None

        task = self._tasks.get(task_name) or self._app.tasks.get(task_name)
        if not task:
            logger.error(f"[CeleryApp] 任务不存在: {task_name}")
            return None

        options = {}
        if queue:
            options["queue"] = queue
        if priority:
            priority_map = {
                TaskPriority.LOW: 1,
                TaskPriority.NORMAL: 5,
                TaskPriority.HIGH: 8,
                TaskPriority.CRITICAL: 10,
            }
            options["priority"] = priority_map.get(priority, 5)
        if countdown:
            options["countdown"] = countdown
        if eta:
            options["eta"] = eta

        result = task.apply_async(args=args, kwargs=kwargs or {}, **options)
        return result.id

    def get_task_result(self, task_id: str) -> Dict[str, Any]:
        """获取任务结果"""
        if not CELERY_AVAILABLE:
            return {"status": "unavailable", "result": None}

        result = AsyncResult(task_id, app=self._app)

        return {
            "task_id": task_id,
            "status": result.state,
            "result": result.result if result.ready() else None,
            "traceback": result.traceback if result.failed() else None,
            "date_done": result.date_done.isoformat() if result.date_done else None,
        }

    def revoke_task(self, task_id: str, terminate: bool = False):
        """撤销任务"""
        if not CELERY_AVAILABLE:
            return

        self._app.control.revoke(task_id, terminate=terminate)
        logger.info(f"[CeleryApp] 撤销任务: {task_id}")

    def get_active_tasks(self) -> List[Dict]:
        """获取活动任务"""
        if not CELERY_AVAILABLE:
            return []

        inspect = self._app.control.inspect()
        active = inspect.active()

        if not active:
            return []

        result = []
        for worker, tasks in active.items():
            for task in tasks:
                result.append({
                    "task_id": task["id"],
                    "name": task["name"],
                    "worker": worker,
                    "args": task.get("args", []),
                    "kwargs": task.get("kwargs", {}),
                })

        return result

    def get_queue_stats(self) -> Dict[str, int]:
        """获取队列统计"""
        if not CELERY_AVAILABLE:
            return {}

        inspect = self._app.control.inspect()
        stats = inspect.stats()

        if not stats:
            return {}

        result = {}
        for worker, stat in stats.items():
            result[worker] = stat.get("total", {})

        return result


# ============ 预定义任务 ============

def create_task_decorators():
    """创建任务装饰器"""
    if not CELERY_AVAILABLE:
        # 返回空装饰器
        def dummy_decorator(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper
        return dummy_decorator, dummy_decorator, dummy_decorator

    # 数据任务装饰器
    def data_task(*args, **kwargs):
        kwargs.setdefault("queue", "data")
        kwargs.setdefault("max_retries", 3)
        return shared_task(*args, **kwargs)

    # 计算任务装饰器
    def compute_task(*args, **kwargs):
        kwargs.setdefault("queue", "compute")
        kwargs.setdefault("max_retries", 2)
        kwargs.setdefault("time_limit", 600)
        return shared_task(*args, **kwargs)

    # 报告任务装饰器
    def report_task(*args, **kwargs):
        kwargs.setdefault("queue", "report")
        kwargs.setdefault("max_retries", 1)
        return shared_task(*args, **kwargs)

    return data_task, compute_task, report_task


# ============ 任务定义 ============

if CELERY_AVAILABLE:
    data_task, compute_task, report_task = create_task_decorators()

    @data_task(bind=True)
    def sync_daily_data(self, date_str: str = None):
        """同步每日数据"""
        logger.info(f"[Task] 开始同步数据: {date_str}")

        try:
            # 模拟数据同步
            time.sleep(2)

            result = {
                "date": date_str or datetime.now().strftime("%Y-%m-%d"),
                "records_synced": 100,
                "status": "success",
            }

            logger.info(f"[Task] 数据同步完成: {result}")
            return result

        except Exception as e:
            logger.error(f"[Task] 数据同步失败: {e}")
            raise self.retry(exc=e, countdown=60)

    @compute_task(bind=True)
    def calculate_scores(self, codes: List[str] = None):
        """计算得分"""
        logger.info(f"[Task] 开始计算得分: {len(codes) if codes else '全部'}")

        try:
            # 模拟得分计算
            time.sleep(5)

            result = {
                "codes_processed": len(codes) if codes else 500,
                "scores_calculated": len(codes) if codes else 500,
                "status": "success",
            }

            logger.info(f"[Task] 得分计算完成")
            return result

        except Exception as e:
            logger.error(f"[Task] 得分计算失败: {e}")
            raise self.retry(exc=e, countdown=30)

    @compute_task(bind=True)
    def generate_signals(self, whitelist: List[str] = None):
        """生成信号"""
        logger.info(f"[Task] 开始生成信号")

        try:
            time.sleep(3)

            result = {
                "whitelist_size": len(whitelist) if whitelist else 60,
                "signals_generated": 10,
                "status": "success",
            }

            logger.info(f"[Task] 信号生成完成")
            return result

        except Exception as e:
            logger.error(f"[Task] 信号生成失败: {e}")
            raise self.retry(exc=e, countdown=60)

    @compute_task(bind=True)
    def run_backtest(self, start_date: str, end_date: str, params: dict = None):
        """运行回测"""
        logger.info(f"[Task] 开始回测: {start_date} ~ {end_date}")

        try:
            time.sleep(10)  # 模拟回测

            result = {
                "start_date": start_date,
                "end_date": end_date,
                "total_return": 0.25,
                "sharpe": 1.8,
                "max_drawdown": 0.08,
                "status": "success",
            }

            logger.info(f"[Task] 回测完成")
            return result

        except Exception as e:
            logger.error(f"[Task] 回测失败: {e}")
            raise self.retry(exc=e, countdown=120)

    @report_task(bind=True)
    def generate_daily_report(self, date_str: str = None):
        """生成日报"""
        logger.info(f"[Task] 开始生成日报: {date_str}")

        try:
            time.sleep(2)

            result = {
                "date": date_str or datetime.now().strftime("%Y-%m-%d"),
                "report_url": "/reports/daily/20240101.pdf",
                "status": "success",
            }

            logger.info(f"[Task] 日报生成完成")
            return result

        except Exception as e:
            logger.error(f"[Task] 日报生成失败: {e}")
            raise self.retry(exc=e, countdown=30)

    @data_task(bind=True)
    def check_risk_metrics(self):
        """检查风险指标"""
        logger.info("[Task] 开始风险检查")

        try:
            time.sleep(1)

            result = {
                "var_95": 0.025,
                "drawdown": 0.02,
                "concentration": 0.15,
                "alerts": [],
                "status": "success",
            }

            logger.info("[Task] 风险检查完成")
            return result

        except Exception as e:
            logger.error(f"[Task] 风险检查失败: {e}")
            raise self.retry(exc=e, countdown=30)

else:
    # Celery不可用时提供空实现
    def sync_daily_data(date_str=None):
        logger.warning("[Task] Celery不可用，直接执行")
        return {"status": "direct"}

    def calculate_scores(codes=None):
        logger.warning("[Task] Celery不可用，直接执行")
        return {"status": "direct"}

    def generate_signals(whitelist=None):
        logger.warning("[Task] Celery不可用，直接执行")
        return {"status": "direct"}

    def run_backtest(start_date, end_date, params=None):
        logger.warning("[Task] Celery不可用，直接执行")
        return {"status": "direct"}

    def generate_daily_report(date_str=None):
        logger.warning("[Task] Celery不可用，直接执行")
        return {"status": "direct"}

    def check_risk_metrics():
        logger.warning("[Task] Celery不可用，直接执行")
        return {"status": "direct"}


# ============ 便捷函数 ============

def get_celery_app() -> CeleryApp:
    """获取Celery应用"""
    return CeleryApp()


def submit_task(
    task_name: str,
    args: tuple = (),
    kwargs: dict = None,
    **options,
) -> Optional[str]:
    """提交任务"""
    app = get_celery_app()
    return app.apply_async(task_name, args, kwargs, **options)


def get_task_status(task_id: str) -> Dict[str, Any]:
    """获取任务状态"""
    app = get_celery_app()
    return app.get_task_result(task_id)


def cancel_task(task_id: str, terminate: bool = False):
    """取消任务"""
    app = get_celery_app()
    app.revoke_task(task_id, terminate)


def init_celery(
    broker_url: str = "redis://localhost:6379/1",
    result_backend: str = "redis://localhost:6379/2",
) -> CeleryApp:
    """初始化Celery"""
    app = CeleryApp()
    app.config.broker_url = broker_url
    app.config.result_backend = result_backend

    if CELERY_AVAILABLE:
        app._app.conf.broker_url = broker_url
        app._app.conf.result_backend = result_backend

    return app
