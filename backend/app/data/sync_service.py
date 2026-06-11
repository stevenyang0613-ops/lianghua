"""
数据同步服务

定时同步转债数据：
- 行情数据同步
- 公告数据同步
- 财务数据同步
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable, List
import pandas as pd
import logging

from .manager import get_data_source_manager, DataType

logger = logging.getLogger(__name__)


@dataclass
class SyncTask:
    """同步任务"""
    name: str
    data_type: DataType
    interval_seconds: int
    last_sync: Optional[datetime]
    last_count: int
    status: str  # idle/running/success/failed


class DataSyncService:
    """数据同步服务"""

    def __init__(self):
        self._tasks: dict[str, SyncTask] = {}
        self._running = False
        self._callbacks: dict[str, List[Callable]] = {}
        self._sync_data: dict[str, pd.DataFrame] = {}

    def register_task(
        self,
        name: str,
        data_type: DataType,
        interval_seconds: int = 60,
    ) -> None:
        """注册同步任务"""
        self._tasks[name] = SyncTask(
            name=name,
            data_type=data_type,
            interval_seconds=interval_seconds,
            last_sync=None,
            last_count=0,
            status='idle',
        )
        self._callbacks[name] = []
        logger.info(f"[DataSync] Registered task: {name}")

    def add_callback(self, task_name: str, callback: Callable) -> None:
        """添加回调函数"""
        if task_name not in self._callbacks:
            self._callbacks[task_name] = []
        self._callbacks[task_name].append(callback)

    async def start(self) -> None:
        """启动同步服务"""
        if self._running:
            return

        self._running = True
        logger.info("[DataSync] Service started")

        # 启动所有任务
        tasks = [self._run_task(name) for name in self._tasks]
        await asyncio.gather(*tasks)

    async def stop(self) -> None:
        """停止同步服务"""
        self._running = False
        logger.info("[DataSync] Service stopped")

    async def _run_task(self, task_name: str) -> None:
        """运行单个同步任务"""
        task = self._tasks[task_name]
        manager = get_data_source_manager()

        while self._running:
            try:
                task.status = 'running'
                start_time = datetime.now()

                # 执行数据同步
                data = await manager.query(task.data_type)

                # 存储数据
                self._sync_data[task_name] = data

                # 更新任务状态
                task.last_sync = datetime.now()
                task.last_count = len(data) if not data.empty else 0
                task.status = 'success'

                # 触发回调
                for callback in self._callbacks.get(task_name, []):
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(data)
                        else:
                            callback(data)
                    except Exception as e:
                        logger.warning(f"[DataSync] Callback error: {e}")

                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"[DataSync] {task_name}: synced {task.last_count} records in {elapsed:.2f}s")

            except Exception as e:
                task.status = 'failed'
                logger.error(f"[DataSync] {task_name} error: {e}")

            # 等待下次同步
            await asyncio.sleep(task.interval_seconds)

    def get_data(self, task_name: str) -> Optional[pd.DataFrame]:
        """获取同步的数据"""
        return self._sync_data.get(task_name)

    def get_task_status(self) -> dict:
        """获取所有任务状态"""
        return {
            name: {
                'last_sync': task.last_sync.isoformat() if task.last_sync else None,
                'last_count': task.last_count,
                'status': task.status,
            }
            for name, task in self._tasks.items()
        }

    async def sync_now(self, task_name: str) -> pd.DataFrame:
        """立即同步指定任务"""
        task = self._tasks.get(task_name)
        if not task:
            return pd.DataFrame()

        manager = get_data_source_manager()
        data = await manager.query(task.data_type, use_cache=False)
        self._sync_data[task_name] = data

        task.last_sync = datetime.now()
        task.last_count = len(data) if not data.empty else 0

        return data


# 全局单例
_sync_service: Optional[DataSyncService] = None


def get_sync_service() -> DataSyncService:
    """获取同步服务"""
    global _sync_service
    if _sync_service is None:
        _sync_service = DataSyncService()
        # 注册默认任务
        _sync_service.register_task('quotes', DataType.QUOTE, 60)
        _sync_service.register_task('convertibles', DataType.CONVERTIBLE, 300)
        _sync_service.register_task('announcements', DataType.ANNOUNCEMENT, 300)
    return _sync_service
