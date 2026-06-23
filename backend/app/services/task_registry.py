"""
轻量后台任务注册表

设计目标:
- 不引入 Redis/Celery 等外部依赖, 适合 Electron 桌面打包环境。
- 为 /data-sources-v2/* 与 /extra/* 中的长耗时批量接口提供“提交任务 -> 轮询状态”模式,
  避免同步调用阻塞 FastAPI 主事件循环。
- 任务在独立线程池中运行, 通过线程安全的状态字典暴露进度与结果。
"""
from __future__ import annotations

import enum
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskInfo:
    task_id: str
    name: str
    status: TaskStatus
    created_at: float
    updated_at: float
    progress: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[str] = None


class TaskRegistry:
    def __init__(self, max_workers: int = 4):
        self._lock = threading.RLock()
        self._tasks: dict[str, TaskInfo] = {}
        self._futures: dict[str, Future] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="bg_task_",
        )

    def submit(
        self,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        task_id = str(uuid.uuid4())
        now = time.time()
        info = TaskInfo(
            task_id=task_id,
            name=name,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._tasks[task_id] = info

        def _run() -> Any:
            self._set_status(task_id, TaskStatus.RUNNING)
            try:
                result = fn(*args, **kwargs)
                self._set_done(task_id, result)
                return result
            except Exception as exc:
                logger.exception(f"[TaskRegistry] task {task_id} ({name}) failed")
                self._set_failed(task_id, exc)
                raise

        future = self._executor.submit(_run)
        with self._lock:
            self._futures[task_id] = future
        return task_id

    def get(self, task_id: str) -> Optional[TaskInfo]:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                return None
            return TaskInfo(
                task_id=info.task_id,
                name=info.name,
                status=info.status,
                created_at=info.created_at,
                updated_at=info.updated_at,
                progress=dict(info.progress),
                result=info.result,
                error=info.error,
            )

    def update_progress(self, task_id: str, **kwargs: Any) -> None:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                return
            info.progress.update(kwargs)
            info.updated_at = time.time()

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 50,
    ) -> list[TaskInfo]:
        with self._lock:
            items = list(self._tasks.values())
        if status:
            items = [t for t in items if t.status == status]
        items.sort(key=lambda t: t.created_at, reverse=True)
        return items[:limit]

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            info = self._tasks.get(task_id)
            future = self._futures.get(task_id)
        if info is None:
            return False
        if info.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return False
        if future and not future.done():
            future.cancel()
        with self._lock:
            info.status = TaskStatus.CANCELLED
            info.updated_at = time.time()
        return True

    def _set_status(self, task_id: str, status: TaskStatus) -> None:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                return
            info.status = status
            info.updated_at = time.time()

    def _set_done(self, task_id: str, result: Any) -> None:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                return
            info.status = TaskStatus.SUCCESS
            info.result = result
            info.updated_at = time.time()

    def _set_failed(self, task_id: str, exc: Exception) -> None:
        with self._lock:
            info = self._tasks.get(task_id)
            if info is None:
                return
            info.status = TaskStatus.FAILED
            info.error = f"{type(exc).__name__}: {exc}"
            info.updated_at = time.time()


# 全局单例
_registry = TaskRegistry(max_workers=4)


def get_registry() -> TaskRegistry:
    return _registry
