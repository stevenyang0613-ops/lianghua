"""松岗量化可转债策略 V3.0 定时任务调度模块

功能:
- APScheduler集成
- 定时任务管理
- 任务监控
- 失败重试
- 任务历史
- 分布式锁
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import asyncio
import traceback

logger = logging.getLogger(__name__)

# 检查APScheduler是否可用
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.jobstores.memory import MemoryJobStore
    from apscheduler.executors.pool import ThreadPoolExecutor
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False


# ============ 枚举类型 ============

class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"         # 待执行
    RUNNING = "running"         # 执行中
    SUCCESS = "success"         # 成功
    FAILED = "failed"           # 失败
    RETRYING = "retrying"       # 重试中
    CANCELLED = "cancelled"     # 已取消


class TaskType(str, Enum):
    """任务类型"""
    DATA_SYNC = "data_sync"         # 数据同步
    SCORING = "scoring"             # 打分计算
    SIGNAL_GEN = "signal_gen"       # 信号生成
    RISK_CHECK = "risk_check"       # 风险检查
    REPORT = "report"               # 报告生成
    CLEANUP = "cleanup"             # 清理任务
    BACKUP = "backup"               # 备份任务
    CUSTOM = "custom"               # 自定义任务


class TriggerType(str, Enum):
    """触发器类型"""
    CRON = "cron"           # Cron表达式
    INTERVAL = "interval"   # 间隔执行
    DATE = "date"           # 指定时间执行


# ============ 数据模型 ============

@dataclass
class TaskConfig:
    """任务配置"""
    task_id: str
    name: str
    task_type: TaskType
    trigger_type: TriggerType
    trigger_config: Dict[str, Any]
    func: Callable
    args: tuple = ()
    kwargs: Dict = field(default_factory=dict)

    # 重试配置
    max_retries: int = 3
    retry_interval: int = 60  # 秒

    # 超时配置
    timeout: int = 300  # 秒

    # 并发控制
    max_instances: int = 1
    coalesce: bool = True  # 合并错过的执行

    # 描述
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "task_type": self.task_type.value,
            "trigger_type": self.trigger_type.value,
            "trigger_config": self.trigger_config,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "description": self.description,
        }


@dataclass
class TaskExecution:
    """任务执行记录"""
    execution_id: str
    task_id: str
    status: TaskStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: float = 0.0
    result: Any = None
    error: str = ""
    retry_count: int = 0
    traceback: str = ""

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": round(self.duration, 2),
            "error": self.error,
            "retry_count": self.retry_count,
        }


# ============ 任务调度器 ============

class TaskScheduler:
    """任务调度器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._scheduler = None
        self._tasks: Dict[str, TaskConfig] = {}
        self._executions: List[TaskExecution] = []
        self._running_tasks: Dict[str, datetime] = {}
        self._lock = asyncio.Lock() if APSCHEDULER_AVAILABLE else None

        self._initialized = True

    def start(self):
        """启动调度器"""
        if not APSCHEDULER_AVAILABLE:
            logger.warning("[TaskScheduler] APScheduler未安装")
            return

        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler(
                jobstores={
                    'default': MemoryJobStore()
                },
                executors={
                    'default': ThreadPoolExecutor(10)
                },
                job_defaults={
                    'coalesce': True,
                    'max_instances': 1,
                }
            )

        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("[TaskScheduler] 调度器已启动")

    def stop(self):
        """停止调度器"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("[TaskScheduler] 调度器已停止")

    def add_task(self, config: TaskConfig) -> bool:
        """添加任务"""
        if not APSCHEDULER_AVAILABLE:
            logger.warning("[TaskScheduler] APScheduler未安装")
            return False

        if config.task_id in self._tasks:
            logger.warning(f"[TaskScheduler] 任务已存在: {config.task_id}")
            return False

        # 创建触发器
        trigger = self._create_trigger(config)
        if trigger is None:
            return False

        # 包装任务函数
        wrapped_func = self._wrap_task(config)

        # 添加任务
        try:
            self._scheduler.add_job(
                wrapped_func,
                trigger=trigger,
                id=config.task_id,
                name=config.name,
                max_instances=config.max_instances,
                coalesce=config.coalesce,
                replace_existing=True,
            )

            self._tasks[config.task_id] = config
            logger.info(f"[TaskScheduler] 添加任务: {config.task_id}")
            return True

        except Exception as e:
            logger.error(f"[TaskScheduler] 添加任务失败: {e}")
            return False

    def _create_trigger(self, config: TaskConfig):
        """创建触发器"""
        if config.trigger_type == TriggerType.CRON:
            return CronTrigger(**config.trigger_config)
        elif config.trigger_type == TriggerType.INTERVAL:
            return IntervalTrigger(**config.trigger_config)
        elif config.trigger_type == TriggerType.DATE:
            return DateTrigger(**config.trigger_config)
        else:
            logger.error(f"[TaskScheduler] 未知触发器类型: {config.trigger_type}")
            return None

    def _wrap_task(self, config: TaskConfig):
        """包装任务函数"""
        async def wrapped():
            execution_id = f"{config.task_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            execution = TaskExecution(
                execution_id=execution_id,
                task_id=config.task_id,
                status=TaskStatus.RUNNING,
                start_time=datetime.now(),
            )

            self._executions.append(execution)
            self._running_tasks[config.task_id] = datetime.now()

            try:
                # 执行任务
                result = await asyncio.wait_for(
                    self._execute_task(config),
                    timeout=config.timeout,
                )

                execution.status = TaskStatus.SUCCESS
                execution.result = result
                logger.info(f"[TaskScheduler] 任务执行成功: {config.task_id}")

            except asyncio.TimeoutError:
                execution.status = TaskStatus.FAILED
                execution.error = f"任务超时 ({config.timeout}秒)"
                logger.error(f"[TaskScheduler] 任务超时: {config.task_id}")

            except Exception as e:
                execution.error = str(e)
                execution.traceback = traceback.format_exc()

                # 重试逻辑
                if execution.retry_count < config.max_retries:
                    execution.status = TaskStatus.RETRYING
                    execution.retry_count += 1
                    logger.warning(f"[TaskScheduler] 任务重试: {config.task_id}, 第{execution.retry_count}次")

                    # 延迟重试
                    await asyncio.sleep(config.retry_interval)

                    try:
                        result = await asyncio.wait_for(
                            self._execute_task(config),
                            timeout=config.timeout,
                        )
                        execution.status = TaskStatus.SUCCESS
                        execution.result = result
                        logger.info(f"[TaskScheduler] 任务重试成功: {config.task_id}")

                    except Exception as retry_error:
                        execution.status = TaskStatus.FAILED
                        execution.error = str(retry_error)
                        logger.error(f"[TaskScheduler] 任务重试失败: {config.task_id}")
                else:
                    execution.status = TaskStatus.FAILED
                    logger.error(f"[TaskScheduler] 任务执行失败: {config.task_id}, {e}")

            finally:
                execution.end_time = datetime.now()
                execution.duration = (execution.end_time - execution.start_time).total_seconds()
                self._running_tasks.pop(config.task_id, None)

        return wrapped

    async def _execute_task(self, config: TaskConfig):
        """执行任务"""
        if asyncio.iscoroutinefunction(config.func):
            return await config.func(*config.args, **config.kwargs)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: config.func(*config.args, **config.kwargs)
            )

    def remove_task(self, task_id: str) -> bool:
        """移除任务"""
        if task_id not in self._tasks:
            return False

        try:
            self._scheduler.remove_job(task_id)
            del self._tasks[task_id]
            logger.info(f"[TaskScheduler] 移除任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"[TaskScheduler] 移除任务失败: {e}")
            return False

    def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        if task_id not in self._tasks:
            return False

        try:
            self._scheduler.pause_job(task_id)
            logger.info(f"[TaskScheduler] 暂停任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"[TaskScheduler] 暂停任务失败: {e}")
            return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        if task_id not in self._tasks:
            return False

        try:
            self._scheduler.resume_job(task_id)
            logger.info(f"[TaskScheduler] 恢复任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"[TaskScheduler] 恢复任务失败: {e}")
            return False

    def run_task_now(self, task_id: str) -> bool:
        """立即执行任务"""
        if task_id not in self._tasks:
            return False

        try:
            self._scheduler.modify_job(task_id, next_run_time=datetime.now())
            logger.info(f"[TaskScheduler] 立即执行任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"[TaskScheduler] 立即执行失败: {e}")
            return False

    def get_task(self, task_id: str) -> Optional[TaskConfig]:
        """获取任务配置"""
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[Dict]:
        """列出所有任务"""
        result = []
        for task_id, config in self._tasks.items():
            job = self._scheduler.get_job(task_id) if self._scheduler else None
            next_run = job.next_run_time if job else None

            task_info = config.to_dict()
            task_info["next_run_time"] = next_run.isoformat() if next_run else None
            task_info["is_running"] = task_id in self._running_tasks

            result.append(task_info)

        return result

    def get_executions(self, task_id: str = None, limit: int = 50) -> List[Dict]:
        """获取执行历史"""
        executions = self._executions

        if task_id:
            executions = [e for e in executions if e.task_id == task_id]

        return [e.to_dict() for e in executions[-limit:]]

    def get_running_tasks(self) -> List[Dict]:
        """获取正在运行的任务"""
        return [
            {
                "task_id": task_id,
                "start_time": start_time.isoformat(),
                "duration": (datetime.now() - start_time).total_seconds(),
            }
            for task_id, start_time in self._running_tasks.items()
        ]

    def clear_history(self):
        """清空历史"""
        self._executions.clear()


# ============ 预定义任务 ============

def create_data_sync_task(
    task_id: str = "data_sync",
    cron: str = "0 9 * * 1-5",  # 工作日9点
    sync_func: Callable = None,
) -> TaskConfig:
    """创建数据同步任务"""
    return TaskConfig(
        task_id=task_id,
        name="数据同步",
        task_type=TaskType.DATA_SYNC,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron_expression": cron},
        func=sync_func or (lambda: logger.info("执行数据同步")),
        description="每日数据同步任务",
    )


def create_scoring_task(
    task_id: str = "scoring",
    cron: str = "30 9 * * 1-5",  # 工作日9:30
    scoring_func: Callable = None,
) -> TaskConfig:
    """创建打分任务"""
    return TaskConfig(
        task_id=task_id,
        name="打分计算",
        task_type=TaskType.SCORING,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron_expression": cron},
        func=scoring_func or (lambda: logger.info("执行打分计算")),
        description="每日打分计算任务",
    )


def create_signal_task(
    task_id: str = "signal_gen",
    cron: str = "35 9 * * 1-5",  # 工作日9:35
    signal_func: Callable = None,
) -> TaskConfig:
    """创建信号生成任务"""
    return TaskConfig(
        task_id=task_id,
        name="信号生成",
        task_type=TaskType.SIGNAL_GEN,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron_expression": cron},
        func=signal_func or (lambda: logger.info("执行信号生成")),
        description="每日信号生成任务",
    )


def create_risk_check_task(
    task_id: str = "risk_check",
    interval_minutes: int = 5,
    risk_func: Callable = None,
) -> TaskConfig:
    """创建风险检查任务"""
    return TaskConfig(
        task_id=task_id,
        name="风险检查",
        task_type=TaskType.RISK_CHECK,
        trigger_type=TriggerType.INTERVAL,
        trigger_config={"minutes": interval_minutes},
        func=risk_func or (lambda: logger.info("执行风险检查")),
        description="定时风险检查任务",
    )


def create_report_task(
    task_id: str = "daily_report",
    cron: str = "0 17 * * 1-5",  # 工作日17点
    report_func: Callable = None,
) -> TaskConfig:
    """创建日报任务"""
    return TaskConfig(
        task_id=task_id,
        name="每日报告",
        task_type=TaskType.REPORT,
        trigger_type=TriggerType.CRON,
        trigger_config={"cron_expression": cron},
        func=report_func or (lambda: logger.info("生成每日报告")),
        description="每日报告生成任务",
    )


# ============ 便捷函数 ============

def get_task_scheduler() -> TaskScheduler:
    """获取任务调度器"""
    return TaskScheduler()


def init_scheduler() -> TaskScheduler:
    """初始化并启动调度器"""
    scheduler = TaskScheduler()
    scheduler.start()
    return scheduler
