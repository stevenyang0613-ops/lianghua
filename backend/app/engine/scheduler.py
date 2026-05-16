import asyncio
import logging
from datetime import datetime, time, date
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


class Scheduler:
    """定时任务调度器"""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._callbacks: dict[str, Callable[[], Awaitable[None]]] = {}

    async def start(self):
        """启动调度器"""
        self._running = True
        for name in self._callbacks:
            if name not in self._tasks:
                self._tasks[name] = asyncio.create_task(self._run_periodic(name))
        logger.info(f"[Scheduler] Started with {len(self._callbacks)} tasks")

    async def stop(self):
        """停止调度器"""
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("[Scheduler] Stopped")

    def add_daily_task(self, name: str, callback: Callable[[], Awaitable[None]], run_time: time = time(16, 0)):
        """
        添加每日定时任务
        Args:
            name: 任务名称
            callback: 异步回调函数
            run_time: 执行时间（默认16:00）
        """
        self._callbacks[name] = callback
        self._run_times = getattr(self, '_run_times', {})
        self._run_times[name] = run_time
        logger.info(f"[Scheduler] Added daily task '{name}' at {run_time}")

    def add_interval_task(self, name: str, callback: Callable[[], Awaitable[None]], interval_seconds: int):
        """
        添加间隔任务
        Args:
            name: 任务名称
            callback: 异步回调函数
            interval_seconds: 间隔秒数
        """
        self._callbacks[name] = callback
        self._intervals = getattr(self, '_intervals', {})
        self._intervals[name] = interval_seconds
        logger.info(f"[Scheduler] Added interval task '{name}' every {interval_seconds}s")

    async def _run_periodic(self, name: str):
        """运行定时任务"""
        while self._running:
            try:
                callback = self._callbacks.get(name)
                if not callback:
                    break

                # 检查是否是每日任务
                run_times = getattr(self, '_run_times', {})
                intervals = getattr(self, '_intervals', {})

                if name in run_times:
                    await self._run_daily(name, callback, run_times[name])
                elif name in intervals:
                    await self._run_interval(name, callback, intervals[name])
                else:
                    break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Scheduler] Task '{name}' error: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再重试

    async def _run_daily(self, name: str, callback: Callable[[], Awaitable[None]], run_time: time):
        """运行每日任务"""
        last_run_date: Optional[date] = None

        while self._running:
            now = datetime.now()
            target_time = datetime.combine(now.date(), run_time)

            # 如果今天还没执行且已过目标时间
            if last_run_date != now.date() and now >= target_time:
                logger.info(f"[Scheduler] Running daily task '{name}'")
                try:
                    await callback()
                    last_run_date = now.date()
                    logger.info(f"[Scheduler] Daily task '{name}' completed")
                except Exception as e:
                    logger.error(f"[Scheduler] Daily task '{name}' failed: {e}")

            # 计算下次检查时间（每分钟检查一次）
            await asyncio.sleep(60)

    async def _run_interval(self, name: str, callback: Callable[[], Awaitable[None]], interval_seconds: int):
        """运行间隔任务"""
        while self._running:
            try:
                await callback()
            except Exception as e:
                logger.error(f"[Scheduler] Interval task '{name}' failed: {e}")
            await asyncio.sleep(interval_seconds)

    async def run_now(self, name: str):
        """立即执行指定任务"""
        callback = self._callbacks.get(name)
        if callback:
            logger.info(f"[Scheduler] Running task '{name}' now")
            try:
                await callback()
            except Exception as e:
                logger.error(f"[Scheduler] Task '{name}' failed: {e}")
        else:
            logger.warning(f"[Scheduler] Task '{name}' not found")


# 全局调度器实例
scheduler = Scheduler()
