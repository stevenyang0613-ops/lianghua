"""松岗量化可转债策略 V3.0 数据同步模块

功能:
- 增量数据更新
- 定时任务调度
- 数据校验
- 数据修复
- 同步状态监控
"""
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import asyncio
import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class SyncStatus(str, Enum):
    """同步状态"""
    PENDING = "pending"       # 待执行
    RUNNING = "running"       # 执行中
    SUCCESS = "success"       # 成功
    FAILED = "failed"         # 失败
    PARTIAL = "partial"       # 部分成功


class SyncType(str, Enum):
    """同步类型"""
    FULL = "full"             # 全量同步
    INCREMENTAL = "incremental"  # 增量同步
    REPAIR = "repair"         # 修复同步


class DataType(str, Enum):
    """数据类型"""
    CB_DAILY = "cb_daily"
    CB_INFO = "cb_info"
    STOCK_DAILY = "stock_daily"
    STOCK_INFO = "stock_info"
    MARKET_INDEX = "market_index"


# ============ 配置类 ============

@dataclass
class SyncConfig:
    """同步配置"""
    # 同步时间
    sync_start_time: str = "09:00"       # 开始时间
    sync_end_time: str = "15:30"         # 结束时间
    sync_interval: int = 300              # 同步间隔(秒)

    # 重试配置
    max_retries: int = 3
    retry_interval: int = 60

    # 数据校验
    enable_validation: bool = True
    validation_tolerance: float = 0.01   # 数据校验容忍度

    # 增量同步
    incremental_lookback_days: int = 5   # 增量回溯天数
    max_missing_days: int = 30           # 最大缺失天数

    # 并发控制
    max_concurrent_tasks: int = 5
    task_timeout: int = 600              # 任务超时(秒)


@dataclass
class SyncResult:
    """同步结果"""
    sync_type: SyncType
    data_type: DataType
    status: SyncStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    records_processed: int = 0
    records_added: int = 0
    records_updated: int = 0
    records_failed: int = 0
    error_message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sync_type": self.sync_type.value,
            "data_type": self.data_type.value,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "records_processed": self.records_processed,
            "records_added": self.records_added,
            "records_updated": self.records_updated,
            "records_failed": self.records_failed,
            "error_message": self.error_message,
            "details": self.details,
        }


@dataclass
class DataGap:
    """数据缺口"""
    data_type: DataType
    code: str
    start_date: date
    end_date: date
    missing_days: int

    def to_dict(self) -> dict:
        return {
            "data_type": self.data_type.value,
            "code": self.code,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "missing_days": self.missing_days,
        }


# ============ 数据校验器 ============

class DataValidator:
    """数据校验器"""

    def __init__(self, tolerance: float = 0.01):
        self.tolerance = tolerance

    def validate_cb_daily(self, data: Dict) -> bool:
        """校验转债日线数据"""
        required_fields = ["date", "code", "close"]

        # 检查必需字段
        for field in required_fields:
            if field not in data or data[field] is None:
                return False

        # 检查数值合理性
        close = data.get("close", 0)
        if close <= 0 or close > 1000:  # 转债价格合理范围
            return False

        # 检查涨跌幅
        change_pct = data.get("change_pct")
        if change_pct is not None and abs(change_pct) > 30:  # 单日涨跌幅不超过30%
            return False

        # 检查成交量
        volume = data.get("volume")
        if volume is not None and volume < 0:
            return False

        return True

    def validate_stock_daily(self, data: Dict) -> bool:
        """校验正股日线数据"""
        required_fields = ["date", "code", "close"]

        for field in required_fields:
            if field not in data or data[field] is None:
                return False

        close = data.get("close", 0)
        if close <= 0:
            return False

        change_pct = data.get("change_pct")
        if change_pct is not None and abs(change_pct) > 20:  # 涨跌停限制
            return False

        return True

    def validate_batch(
        self,
        data_list: List[Dict],
        data_type: DataType,
    ) -> Dict[str, Any]:
        """批量校验数据"""
        total = len(data_list)
        valid = 0
        invalid_records = []

        validate_func = {
            DataType.CB_DAILY: self.validate_cb_daily,
            DataType.STOCK_DAILY: self.validate_stock_daily,
        }.get(data_type)

        if not validate_func:
            return {"total": total, "valid": total, "invalid": 0}

        for i, data in enumerate(data_list):
            if validate_func(data):
                valid += 1
            else:
                invalid_records.append({
                    "index": i,
                    "code": data.get("code"),
                    "date": data.get("date"),
                })

        return {
            "total": total,
            "valid": valid,
            "invalid": total - valid,
            "valid_rate": valid / total if total > 0 else 0,
            "invalid_records": invalid_records[:100],  # 只保留前100条
        }


# ============ 增量数据检测 ============

class GapDetector:
    """数据缺口检测器"""

    def __init__(self, config: SyncConfig):
        self.config = config

    def detect_gaps(
        self,
        existing_dates: List[date],
        start_date: date,
        end_date: date,
        data_type: DataType,
        code: str = None,
    ) -> List[DataGap]:
        """检测数据缺口"""
        gaps = []
        existing_set = set(existing_dates)

        # 生成交易日列表（简化处理，实际应考虑节假日）
        current = start_date
        all_dates = []
        while current <= end_date:
            if current.weekday() < 5:  # 周一到周五
                all_dates.append(current)
            current += timedelta(days=1)

        # 找出缺失日期
        missing_dates = sorted(set(all_dates) - existing_set)

        if not missing_dates:
            return gaps

        # 合并连续的缺失日期
        gap_start = missing_dates[0]
        gap_end = missing_dates[0]

        for i in range(1, len(missing_dates)):
            if (missing_dates[i] - gap_end).days == 1:
                gap_end = missing_dates[i]
            else:
                gaps.append(DataGap(
                    data_type=data_type,
                    code=code,
                    start_date=gap_start,
                    end_date=gap_end,
                    missing_days=(gap_end - gap_start).days + 1,
                ))
                gap_start = missing_dates[i]
                gap_end = missing_dates[i]

        # 添加最后一个缺口
        gaps.append(DataGap(
            data_type=data_type,
            code=code,
            start_date=gap_start,
            end_date=gap_end,
            missing_days=(gap_end - gap_start).days + 1,
        ))

        return gaps


# ============ 数据同步任务 ============

class SyncTask(ABC):
    """同步任务抽象类"""

    def __init__(self, data_type: DataType, config: SyncConfig):
        self.data_type = data_type
        self.config = config
        self.validator = DataValidator(config.validation_tolerance)

    @abstractmethod
    def fetch_data(
        self,
        start_date: date,
        end_date: date,
        codes: List[str] = None,
    ) -> List[Dict]:
        """获取数据"""
        pass

    @abstractmethod
    def save_data(self, data: List[Dict]) -> int:
        """保存数据"""
        pass

    @abstractmethod
    def get_existing_dates(
        self,
        start_date: date,
        end_date: date,
        code: str = None,
    ) -> List[date]:
        """获取已有数据日期"""
        pass

    def execute(
        self,
        sync_type: SyncType,
        start_date: date = None,
        end_date: date = None,
        codes: List[str] = None,
    ) -> SyncResult:
        """执行同步"""
        result = SyncResult(
            sync_type=sync_type,
            data_type=self.data_type,
            status=SyncStatus.RUNNING,
            start_time=datetime.now(),
        )

        try:
            # 确定日期范围
            end_date = end_date or date.today()
            if sync_type == SyncType.INCREMENTAL:
                start_date = start_date or (end_date - timedelta(days=self.config.incremental_lookback_days))
            else:
                start_date = start_date or (end_date - timedelta(days=365))

            # 获取数据
            logger.info(f"[SyncTask] 开始{sync_type.value}同步: {self.data_type.value}, {start_date} ~ {end_date}")
            data = self.fetch_data(start_date, end_date, codes)

            if not data:
                result.status = SyncStatus.SUCCESS
                result.end_time = datetime.now()
                return result

            result.records_processed = len(data)

            # 数据校验
            if self.config.enable_validation:
                validation = self.validator.validate_batch(data, self.data_type)
                if validation["invalid"] > 0:
                    logger.warning(f"[SyncTask] 数据校验: {validation['invalid']}条无效")
                    result.details["validation"] = validation
                    # 过滤无效数据
                    data = [d for i, d in enumerate(data) if i not in [r["index"] for r in validation["invalid_records"]]]

            # 保存数据
            saved = self.save_data(data)
            result.records_added = saved
            result.status = SyncStatus.SUCCESS

            logger.info(f"[SyncTask] 同步完成: 处理{result.records_processed}条, 新增{result.records_added}条")

        except Exception as e:
            result.status = SyncStatus.FAILED
            result.error_message = str(e)
            logger.error(f"[SyncTask] 同步失败: {e}")

        result.end_time = datetime.now()
        return result


class CBDataSyncTask(SyncTask):
    """转债数据同步任务"""

    def __init__(self, data_source, storage, config: SyncConfig):
        super().__init__(DataType.CB_DAILY, config)
        self.data_source = data_source
        self.storage = storage

    def fetch_data(self, start_date: date, end_date: date, codes: List[str] = None) -> List[Dict]:
        """获取转债数据"""
        try:
            df = self.data_source.get_cb_daily(start_date, end_date, codes)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.error(f"[CBDataSync] 获取数据失败: {e}")
            return []

    def save_data(self, data: List[Dict]) -> int:
        """保存转债数据"""
        try:
            import pandas as pd
            df = pd.DataFrame(data)
            if not df.empty:
                self.storage.insert(DataType.CB_DAILY, df)
            return len(data)
        except Exception as e:
            logger.error(f"[CBDataSync] 保存数据失败: {e}")
            return 0

    def get_existing_dates(self, start_date: date, end_date: date, code: str = None) -> List[date]:
        """获取已有数据日期"""
        try:
            df = self.storage.query(DataType.CB_DAILY, start_date, end_date, [code] if code else None)
            if df.empty:
                return []
            return sorted(df['date'].unique().tolist())
        except Exception as e:
            logger.warning("[CBDataSync] get_existing_dates failed: %s", e)
            return []


class StockDataSyncTask(SyncTask):
    """正股数据同步任务"""

    def __init__(self, data_source, storage, config: SyncConfig):
        super().__init__(DataType.STOCK_DAILY, config)
        self.data_source = data_source
        self.storage = storage

    def fetch_data(self, start_date: date, end_date: date, codes: List[str] = None) -> List[Dict]:
        """获取正股数据"""
        try:
            df = self.data_source.get_stock_daily(start_date, end_date, codes)
            return df.to_dict('records') if not df.empty else []
        except Exception as e:
            logger.error(f"[StockDataSync] 获取数据失败: {e}")
            return []

    def save_data(self, data: List[Dict]) -> int:
        """保存正股数据"""
        try:
            import pandas as pd
            df = pd.DataFrame(data)
            if not df.empty:
                self.storage.insert(DataType.STOCK_DAILY, df)
            return len(data)
        except Exception as e:
            logger.error(f"[StockDataSync] 保存数据失败: {e}")
            return 0

    def get_existing_dates(self, start_date: date, end_date: date, code: str = None) -> List[date]:
        """获取已有数据日期"""
        try:
            df = self.storage.query(DataType.STOCK_DAILY, start_date, end_date, [code] if code else None)
            if df.empty:
                return []
            return sorted(df['date'].unique().tolist())
        except Exception as e:
            logger.warning("[StockDataSync] get_existing_dates failed: %s", e)
            return []


# ============ 同步调度器 ============

class SyncScheduler:
    """同步调度器"""

    def __init__(self, config: SyncConfig):
        self.config = config
        self._tasks: Dict[str, SyncTask] = {}
        self._running = False
        self._last_sync: Dict[str, datetime] = {}
        self._sync_history: List[SyncResult] = []

    def register_task(self, name: str, task: SyncTask):
        """注册同步任务"""
        self._tasks[name] = task
        logger.info(f"[SyncScheduler] 注册任务: {name}")

    def run_sync(
        self,
        task_name: str,
        sync_type: SyncType = SyncType.INCREMENTAL,
        start_date: date = None,
        end_date: date = None,
        codes: List[str] = None,
    ) -> SyncResult:
        """执行同步"""
        if task_name not in self._tasks:
            return SyncResult(
                sync_type=sync_type,
                data_type=DataType.CB_DAILY,
                status=SyncStatus.FAILED,
                start_time=datetime.now(),
                error_message=f"任务不存在: {task_name}",
            )

        task = self._tasks[task_name]
        result = task.execute(sync_type, start_date, end_date, codes)

        # 记录历史
        self._sync_history.append(result)
        if len(self._sync_history) > 100:
            self._sync_history = self._sync_history[-100:]

        # 更新最后同步时间
        if result.status == SyncStatus.SUCCESS:
            self._last_sync[task_name] = datetime.now()

        return result

    async def run_sync_async(
        self,
        task_name: str,
        sync_type: SyncType = SyncType.INCREMENTAL,
        start_date: date = None,
        end_date: date = None,
        codes: List[str] = None,
    ) -> SyncResult:
        """异步执行同步"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.run_sync(task_name, sync_type, start_date, end_date, codes),
        )

    async def start(self):
        """启动调度器"""
        self._running = True
        logger.info("[SyncScheduler] 调度器启动")

        while self._running:
            try:
                # 检查是否在同步时间窗口内
                now = datetime.now()
                current_time = now.strftime("%H:%M")

                if self.config.sync_start_time <= current_time <= self.config.sync_end_time:
                    # 执行增量同步
                    for task_name in self._tasks:
                        last_sync = self._last_sync.get(task_name)
                        if last_sync is None or (now - last_sync).total_seconds() >= self.config.sync_interval:
                            logger.info(f"[SyncScheduler] 执行定时同步: {task_name}")
                            await self.run_sync_async(task_name)

                await asyncio.sleep(60)  # 每分钟检查一次

            except Exception as e:
                logger.error(f"[SyncScheduler] 调度异常: {e}")
                await asyncio.sleep(60)

    def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("[SyncScheduler] 调度器停止")

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "running": self._running,
            "tasks": list(self._tasks.keys()),
            "last_sync": {k: v.isoformat() for k, v in self._last_sync.items()},
            "history_count": len(self._sync_history),
        }

    def get_history(self, limit: int = 10) -> List[Dict]:
        """获取同步历史"""
        return [r.to_dict() for r in self._sync_history[-limit:]]


# ============ 数据修复器 ============

class DataRepairer:
    """数据修复器"""

    def __init__(self, config: SyncConfig):
        self.config = config
        self.gap_detector = GapDetector(config)

    def repair_gaps(
        self,
        task: SyncTask,
        gaps: List[DataGap],
    ) -> List[SyncResult]:
        """修复数据缺口"""
        results = []

        for gap in gaps:
            if gap.missing_days > self.config.max_missing_days:
                logger.warning(f"[DataRepairer] 缺口过大，跳过: {gap.code} {gap.start_date} ~ {gap.end_date}")
                continue

            result = task.execute(
                sync_type=SyncType.REPAIR,
                start_date=gap.start_date,
                end_date=gap.end_date,
                codes=[gap.code] if gap.code else None,
            )
            results.append(result)

        return results

    def detect_and_repair(
        self,
        task: SyncTask,
        start_date: date,
        end_date: date,
        codes: List[str] = None,
    ) -> Dict[str, Any]:
        """检测并修复数据缺口"""
        all_gaps = []

        if codes:
            for code in codes:
                existing = task.get_existing_dates(start_date, end_date, code)
                gaps = self.gap_detector.detect_gaps(
                    existing, start_date, end_date, task.data_type, code
                )
                all_gaps.extend(gaps)
        else:
            existing = task.get_existing_dates(start_date, end_date)
            gaps = self.gap_detector.detect_gaps(
                existing, start_date, end_date, task.data_type
            )
            all_gaps.extend(gaps)

        # 修复缺口
        results = self.repair_gaps(task, all_gaps)

        return {
            "gaps_detected": len(all_gaps),
            "gaps_repaired": sum(1 for r in results if r.status == SyncStatus.SUCCESS),
            "gaps": [g.to_dict() for g in all_gaps],
            "results": [r.to_dict() for r in results],
        }


# ============ 便捷函数 ============

def create_sync_scheduler(
    data_source,
    storage,
    config: SyncConfig = None,
) -> SyncScheduler:
    """创建同步调度器"""
    config = config or SyncConfig()
    scheduler = SyncScheduler(config)

    # 注册任务
    cb_task = CBDataSyncTask(data_source, storage, config)
    scheduler.register_task("cb_daily", cb_task)

    stock_task = StockDataSyncTask(data_source, storage, config)
    scheduler.register_task("stock_daily", stock_task)

    return scheduler
