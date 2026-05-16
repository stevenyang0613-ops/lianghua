"""松岗量化可转债策略 V3.0 数据湖模块

功能:
- Delta Lake支持
- 数据湖写入
- 时间旅行
- Schema演进
- 数据版本管理
- 批量读写优化
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Iterator
from enum import Enum
import logging
import os
import json
import time

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 检查Delta Lake是否可用
try:
    from delta import DeltaTable
    from delta.tables import DeltaTable as DeltaTableAPI
    import pyspark
    from pyspark.sql import SparkSession
    from pyspark.sql.types import StructType, StructField
    DELTA_AVAILABLE = True
except ImportError:
    DELTA_AVAILABLE = False

# 检查PyArrow是否可用(轻量级替代)
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False


# ============ 枚举类型 ============

class DataLakeFormat(str, Enum):
    """数据湖格式"""
    DELTA = "delta"
    PARQUET = "parquet"
    ICEBERG = "iceberg"


class WriteMode(str, Enum):
    """写入模式"""
    APPEND = "append"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    UPSERT = "upsert"


# ============ 配置类 ============

@dataclass
class DataLakeConfig:
    """数据湖配置"""
    # 存储路径
    root_path: str = "data/lake"

    # 格式
    format: DataLakeFormat = DataLakeFormat.PARQUET

    # 分区配置
    partition_by: List[str] = field(default_factory=lambda: ["date"])
    partition_granularity: str = "day"  # day, month, year

    # 压缩配置
    compression: str = "snappy"  # snappy, gzip, zstd

    # 版本管理
    retain_versions: int = 30  # 保留版本数
    vacuum_older_than: int = 7  # 清理多少天前的文件

    # 写入优化
    optimize_batch_size: int = 100000
    optimize_file_size_mb: int = 128

    # Spark配置(如果使用Delta)
    spark_app_name: str = "sg_strategy"
    spark_master: str = "local[*]"


# ============ Schema定义 ============

CB_DAILY_SCHEMA = {
    "date": "date",
    "code": "string",
    "name": "string",
    "stock_code": "string",
    "open": "double",
    "high": "double",
    "low": "double",
    "close": "double",
    "volume": "int64",
    "amount": "double",
    "turnover_rate": "double",
    "conversion_premium": "double",
    "ytm": "double",
    "remaining_years": "double",
}

STOCK_DAILY_SCHEMA = {
    "date": "date",
    "code": "string",
    "name": "string",
    "open": "double",
    "high": "double",
    "low": "double",
    "close": "double",
    "change_pct": "double",
    "volume": "int64",
    "amount": "double",
    "turnover_rate": "double",
    "volume_ratio": "double",
    "pe": "double",
    "pb": "double",
}

SIGNAL_SCHEMA = {
    "signal_id": "string",
    "signal_time": "timestamp",
    "code": "string",
    "name": "string",
    "action": "string",
    "quantity": "int32",
    "price": "double",
    "reason": "string",
    "score": "double",
    "status": "string",
}

PORTFOLIO_SCHEMA = {
    "date": "date",
    "aum": "double",
    "total_value": "double",
    "cash": "double",
    "position_count": "int32",
    "daily_return": "double",
    "cumulative_return": "double",
    "max_drawdown": "double",
    "sharpe": "double",
}


# ============ 数据湖管理器 ============

class DataLakeManager:
    """数据湖管理器"""

    _instance = None

    def __new__(cls, config: DataLakeConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: DataLakeConfig = None):
        if self._initialized:
            return

        self.config = config or DataLakeConfig()
        self._spark = None
        self._tables: Dict[str, Any] = {}

        # 初始化
        self._init_storage()

        self._initialized = True

    def _init_storage(self):
        """初始化存储"""
        # 创建根目录
        os.makedirs(self.config.root_path, exist_ok=True)

        # 创建表目录
        for table_name in ["cb_daily", "stock_daily", "signals", "portfolio", "scores"]:
            table_path = os.path.join(self.config.root_path, table_name)
            os.makedirs(table_path, exist_ok=True)

        logger.info(f"[DataLake] 初始化完成: {self.config.root_path}")

    def _get_table_path(self, table_name: str) -> str:
        """获取表路径"""
        return os.path.join(self.config.root_path, table_name)

    def write(
        self,
        table_name: str,
        df: pd.DataFrame,
        mode: WriteMode = WriteMode.APPEND,
        partition_values: Dict[str, Any] = None,
    ) -> bool:
        """写入数据"""
        if df.empty:
            return True

        table_path = self._get_table_path(table_name)

        try:
            if self.config.format == DataLakeFormat.DELTA and DELTA_AVAILABLE:
                return self._write_delta(table_path, df, mode, partition_values)
            else:
                return self._write_parquet(table_path, df, mode, partition_values)

        except Exception as e:
            logger.error(f"[DataLake] 写入失败: {e}")
            return False

    def _write_delta(
        self,
        table_path: str,
        df: pd.DataFrame,
        mode: WriteMode,
        partition_values: Dict[str, Any],
    ) -> bool:
        """写入Delta表"""
        if not DELTA_AVAILABLE:
            return False

        # 初始化Spark
        if self._spark is None:
            self._spark = SparkSession.builder \
                .appName(self.config.spark_app_name) \
                .master(self.config.spark_master) \
                .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
                .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
                .getOrCreate()

        # 转换为Spark DataFrame
        spark_df = self._spark.createDataFrame(df)

        # 写入
        if mode == WriteMode.MERGE or mode == WriteMode.UPSERT:
            # 检查表是否存在
            if DeltaTable.isDeltaTable(self._spark, table_path):
                delta_table = DeltaTable.forPath(self._spark, table_path)

                # 定义合并条件
                merge_condition = " AND ".join([
                    f"target.{col} = source.{col}"
                    for col in ["date", "code"]
                ])

                delta_table.alias("target").merge(
                    spark_df.alias("source"),
                    merge_condition
                ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
            else:
                spark_df.write.format("delta").mode("overwrite").save(table_path)
        else:
            spark_df.write.format("delta").mode(mode.value).save(table_path)

        logger.info(f"[DataLake] Delta写入成功: {table_path}")
        return True

    def _write_parquet(
        self,
        table_path: str,
        df: pd.DataFrame,
        mode: WriteMode,
        partition_values: Dict[str, Any],
    ) -> bool:
        """写入Parquet文件"""
        # 分区写入
        if partition_values:
            partition_path = table_path
            for key, value in partition_values.items():
                partition_path = os.path.join(partition_path, f"{key}={value}")
            os.makedirs(partition_path, exist_ok=True)
        else:
            partition_path = table_path

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        file_name = f"data_{timestamp}.parquet"
        file_path = os.path.join(partition_path, file_name)

        # 写入
        if mode == WriteMode.OVERWRITE:
            # 清空目录
            for f in os.listdir(partition_path):
                fpath = os.path.join(partition_path, f)
                if os.path.isfile(fpath):
                    os.remove(fpath)

        df.to_parquet(
            file_path,
            compression=self.config.compression,
            index=False,
        )

        logger.info(f"[DataLake] Parquet写入成功: {file_path}")
        return True

    def read(
        self,
        table_name: str,
        start_date: date = None,
        end_date: date = None,
        columns: List[str] = None,
        filters: Dict[str, Any] = None,
        version: int = None,
    ) -> pd.DataFrame:
        """读取数据"""
        table_path = self._get_table_path(table_name)

        if not os.path.exists(table_path):
            return pd.DataFrame()

        try:
            if self.config.format == DataLakeFormat.DELTA and DELTA_AVAILABLE:
                return self._read_delta(table_path, start_date, end_date, columns, filters, version)
            else:
                return self._read_parquet(table_path, start_date, end_date, columns, filters)

        except Exception as e:
            logger.error(f"[DataLake] 读取失败: {e}")
            return pd.DataFrame()

    def _read_delta(
        self,
        table_path: str,
        start_date: date,
        end_date: date,
        columns: List[str],
        filters: Dict[str, Any],
        version: int,
    ) -> pd.DataFrame:
        """读取Delta表"""
        if not DELTA_AVAILABLE:
            return pd.DataFrame()

        if self._spark is None:
            self._init_spark()

        # 构建读取选项
        reader = self._spark.read.format("delta")

        if version is not None:
            reader = reader.option("versionAsOf", version)

        df = reader.load(table_path)

        # 过滤
        if start_date:
            df = df.filter(f"date >= '{start_date}'")
        if end_date:
            df = df.filter(f"date <= '{end_date}'")

        if filters:
            for col, value in filters.items():
                if isinstance(value, list):
                    df = df.filter(f"{col} in ({','.join(repr(v) for v in value)})")
                else:
                    df = df.filter(f"{col} = {repr(value)}")

        # 选择列
        if columns:
            df = df.select(*columns)

        return df.toPandas()

    def _read_parquet(
        self,
        table_path: str,
        start_date: date,
        end_date: date,
        columns: List[str],
        filters: Dict[str, Any],
    ) -> pd.DataFrame:
        """读取Parquet文件"""
        # 收集所有parquet文件
        parquet_files = []
        for root, dirs, files in os.walk(table_path):
            for f in files:
                if f.endswith(".parquet"):
                    parquet_files.append(os.path.join(root, f))

        if not parquet_files:
            return pd.DataFrame()

        # 读取所有文件
        dfs = []
        for f in parquet_files:
            try:
                df = pd.read_parquet(f, columns=columns)

                # 过滤日期
                if start_date and "date" in df.columns:
                    df = df[df["date"] >= start_date]
                if end_date and "date" in df.columns:
                    df = df[df["date"] <= end_date]

                # 过滤其他条件
                if filters:
                    for col, value in filters.items():
                        if col in df.columns:
                            if isinstance(value, list):
                                df = df[df[col].isin(value)]
                            else:
                                df = df[df[col] == value]

                dfs.append(df)

            except Exception as e:
                logger.warning(f"[DataLake] 读取文件失败: {f}, {e}")

        if not dfs:
            return pd.DataFrame()

        return pd.concat(dfs, ignore_index=True)

    def time_travel(
        self,
        table_name: str,
        version: int = None,
        timestamp: datetime = None,
    ) -> pd.DataFrame:
        """时间旅行"""
        table_path = self._get_table_path(table_name)

        if self.config.format == DataLakeFormat.DELTA and DELTA_AVAILABLE:
            return self._read_delta(table_path, None, None, None, None, version)
        else:
            logger.warning("[DataLake] 时间旅行仅支持Delta格式")
            return pd.DataFrame()

    def get_versions(self, table_name: str) -> List[Dict]:
        """获取版本历史"""
        table_path = self._get_table_path(table_name)

        versions = []

        if self.config.format == DataLakeFormat.DELTA and DELTA_AVAILABLE:
            if DeltaTable.isDeltaTable(self._spark, table_path):
                delta_table = DeltaTable.forPath(self._spark, table_path)
                history = delta_table.history().collect()

                for row in history:
                    versions.append({
                        "version": row.version,
                        "timestamp": row.timestamp.isoformat(),
                        "operation": row.operation,
                    })

        return versions

    def vacuum(self, table_name: str = None, older_than_days: int = None):
        """清理旧文件"""
        older_than_days = older_than_days or self.config.vacuum_older_than

        if table_name:
            tables = [table_name]
        else:
            tables = ["cb_daily", "stock_daily", "signals", "portfolio", "scores"]

        for table in tables:
            table_path = self._get_table_path(table)

            if self.config.format == DataLakeFormat.DELTA and DELTA_AVAILABLE:
                if DeltaTable.isDeltaTable(self._spark, table_path):
                    delta_table = DeltaTable.forPath(self._spark, table_path)
                    delta_table.vacuum(older_than_days * 24 * 3600)  # 转换为秒

            logger.info(f"[DataLake] 清理完成: {table}")

    def optimize(self, table_name: str):
        """优化表"""
        table_path = self._get_table_path(table_name)

        if self.config.format == DataLakeFormat.DELTA and DELTA_AVAILABLE:
            if DeltaTable.isDeltaTable(self._spark, table_path):
                delta_table = DeltaTable.forPath(self._spark, table_path)
                delta_table.optimize().executeCompaction()

        logger.info(f"[DataLake] 优化完成: {table_name}")

    def get_stats(self, table_name: str) -> Dict[str, Any]:
        """获取表统计"""
        table_path = self._get_table_path(table_name)

        stats = {
            "table_name": table_name,
            "path": table_path,
            "format": self.config.format.value,
        }

        if not os.path.exists(table_path):
            stats["exists"] = False
            return stats

        # 计算文件数和大小
        total_size = 0
        file_count = 0

        for root, dirs, files in os.walk(table_path):
            for f in files:
                if f.endswith((".parquet", ".json", ".checkpoint")):
                    file_count += 1
                    total_size += os.path.getsize(os.path.join(root, f))

        stats.update({
            "exists": True,
            "file_count": file_count,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        })

        return stats


# ============ 便捷函数 ============

def get_data_lake(config: DataLakeConfig = None) -> DataLakeManager:
    """获取数据湖管理器"""
    return DataLakeManager(config)


def init_data_lake(
    root_path: str = "data/lake",
    format: DataLakeFormat = DataLakeFormat.PARQUET,
) -> DataLakeManager:
    """初始化数据湖"""
    config = DataLakeConfig(
        root_path=root_path,
        format=format,
    )
    return DataLakeManager(config)


def write_to_lake(
    table_name: str,
    df: pd.DataFrame,
    mode: WriteMode = WriteMode.APPEND,
) -> bool:
    """写入数据湖"""
    lake = get_data_lake()
    return lake.write(table_name, df, mode)


def read_from_lake(
    table_name: str,
    start_date: date = None,
    end_date: date = None,
    **kwargs,
) -> pd.DataFrame:
    """从数据湖读取"""
    lake = get_data_lake()
    return lake.read(table_name, start_date, end_date, **kwargs)
