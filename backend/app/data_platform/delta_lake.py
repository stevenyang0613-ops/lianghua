"""Delta Lake实时数据湖"""
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import json

try:
    from delta.tables import DeltaTable
    import pyspark
    from pyspark.sql import SparkSession, DataFrame
    from pyspark.sql.functions import col, lit, current_timestamp
    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False

import pandas as pd


@dataclass
class TableConfig:
    """表配置"""
    table_name: str
    path: str
    partition_columns: List[str] = None
    zorder_columns: List[str] = None
    retention_hours: int = 168  # 7天
    optimize_interval: str = "1 day"
    
    # Schema变更
    merge_schema: bool = True
    overwrite_schema: bool = False


class DeltaLakeManager:
    """Delta Lake管理器"""
    
    def __init__(self, spark: 'SparkSession' = None, base_path: str = "/data/delta"):
        self.base_path = base_path
        self.tables: Dict[str, TableConfig] = {}
        
        if SPARK_AVAILABLE:
            self.spark = spark or self._create_spark_session()
        else:
            self.spark = None
    
    def _create_spark_session(self) -> 'SparkSession':
        """创建Spark会话"""
        if not SPARK_AVAILABLE:
            return None
        
        return SparkSession.builder \
            .appName("LianghuaDeltaLake") \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
            .config("spark.delta.logStore.class", "org.apache.spark.sql.delta.storage.S3SingleDriverLogStore") \
            .getOrCreate()
    
    def create_table(
        self,
        table_name: str,
        schema: Dict,
        partition_columns: List[str] = None,
        properties: Dict = None
    ) -> bool:
        """创建Delta表"""
        if not self.spark:
            return False
        
        table_path = os.path.join(self.base_path, table_name)
        
        # 构建DDL
        columns_ddl = ", ".join([f"{name} {dtype}" for name, dtype in schema.items()])
        
        if partition_columns:
            partition_ddl = f"PARTITIONED BY ({', '.join(partition_columns)})"
        else:
            partition_ddl = ""
        
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            {columns_ddl}
        )
        USING DELTA
        {partition_ddl}
        LOCATION '{table_path}'
        """
        
        self.spark.sql(ddl)
        
        # 设置表属性
        if properties:
            for key, value in properties.items():
                self.spark.sql(f"ALTER TABLE {table_name} SET TBLPROPERTIES ({key} = '{value}')")
        
        # 注册表配置
        self.tables[table_name] = TableConfig(
            table_name=table_name,
            path=table_path,
            partition_columns=partition_columns
        )
        
        return True
    
    def write_data(
        self,
        table_name: str,
        data: pd.DataFrame,
        mode: str = "append",
        partition_values: Dict = None
    ) -> bool:
        """写入数据"""
        if not self.spark:
            return False
        
        df = self.spark.createDataFrame(data)
        
        if partition_values:
            for col_name, value in partition_values.items():
                df = df.withColumn(col_name, lit(value))
        
        df.write \
            .format("delta") \
            .mode(mode) \
            .partitionBy(self.tables[table_name].partition_columns or []) \
            .saveAsTable(table_name)
        
        return True
    
    def merge_data(
        self,
        table_name: str,
        data: pd.DataFrame,
        merge_condition: str,
        when_matched_update: str = None,
        when_not_matched_insert: str = None
    ) -> Dict:
        """合并数据（UPSERT）"""
        if not self.spark:
            return {}
        
        delta_table = DeltaTable.forName(self.spark, table_name)
        source_df = self.spark.createDataFrame(data)
        
        # 构建合并操作
        merge_builder = delta_table.alias("target").merge(
            source_df.alias("source"),
            merge_condition
        )
        
        if when_matched_update:
            merge_builder = merge_builder.whenMatchedUpdate(set=when_matched_update)
        
        if when_not_matched_insert:
            merge_builder = merge_builder.whenNotMatchedInsert(values=when_not_matched_insert)
        else:
            merge_builder = merge_builder.whenNotMatchedInsertAll()
        
        result = merge_builder.execute()
        
        return {
            'num_affected_rows': result.num_affected_rows,
            'num_inserted_rows': result.num_inserted_rows,
            'num_updated_rows': result.num_updated_rows,
            'num_deleted_rows': result.num_deleted_rows
        }
    
    def read_data(
        self,
        table_name: str,
        filters: Dict = None,
        columns: List[str] = None,
        version: int = None,
        timestamp: datetime = None
    ) -> pd.DataFrame:
        """读取数据"""
        if not self.spark:
            return pd.DataFrame()
        
        reader = self.spark.read.format("delta")
        
        if version is not None:
            reader = reader.option("versionAsOf", version)
        elif timestamp:
            reader = reader.option("timestampAsOf", timestamp.isoformat())
        
        df = reader.table(table_name)
        
        # 应用过滤
        if filters:
            for col_name, value in filters.items():
                df = df.filter(col(col_name) == value)
        
        # 选择列
        if columns:
            df = df.select(*columns)
        
        return df.toPandas()
    
    def time_travel(
        self,
        table_name: str,
        timestamp: datetime = None,
        version: int = None
    ) -> pd.DataFrame:
        """时间旅行"""
        return self.read_data(table_name, version=version, timestamp=timestamp)
    
    def get_table_history(self, table_name: str) -> pd.DataFrame:
        """获取表历史"""
        if not self.spark:
            return pd.DataFrame()
        
        history = self.spark.sql(f"DESCRIBE HISTORY {table_name}")
        return history.toPandas()
    
    def vacuum_table(
        self,
        table_name: str,
        retention_hours: int = None,
        dry_run: bool = True
    ) -> Dict:
        """清理旧文件"""
        if not self.spark:
            return {}
        
        retention = retention_hours or self.tables[table_name].retention_hours
        
        delta_table = DeltaTable.forName(self.spark, table_name)
        
        result = delta_table.vacuum(retention_hours=retention, dry_run=dry_run)
        
        return {
            'retention_hours': retention,
            'dry_run': dry_run,
            'result': str(result)
        }
    
    def optimize_table(
        self,
        table_name: str,
        zorder_columns: List[str] = None
    ) -> Dict:
        """优化表"""
        if not self.spark:
            return {}
        
        # 压缩
        self.spark.sql(f"OPTIMIZE {table_name}")
        
        # Z-Order
        zorder = zorder_columns or self.tables[table_name].zorder_columns
        if zorder:
            self.spark.sql(f"OPTIMIZE {table_name} ZORDER BY ({', '.join(zorder)})")
        
        return {'optimized': True, 'zorder_columns': zorder}
    
    def create_stream(
        self,
        table_name: str,
        checkpoint_location: str,
        processing_time: str = "10 seconds"
    ):
        """创建流式写入"""
        if not self.spark:
            return None
        
        return self.spark.readStream \
            .format("delta") \
            .table(table_name) \
            .writeStream \
            .format("delta") \
            .outputMode("append") \
            .option("checkpointLocation", checkpoint_location) \
            .trigger(processingTime=processing_time) \
            .start(table_name)
    
    def get_table_stats(self, table_name: str) -> Dict:
        """获取表统计"""
        if not self.spark:
            return {}
        
        detail = self.spark.sql(f"DESCRIBE DETAIL {table_name}").first()
        
        return {
            'table_name': table_name,
            'location': detail.location,
            'current_version': detail.currentVersion,
            'num_files': detail.numFiles,
            'size_in_bytes': detail.sizeInBytes,
            'created_at': detail.createdAt,
            'last_modified': detail.lastModified
        }


class DataLakeIngestion:
    """数据湖入湖"""
    
    def __init__(self, delta_manager: DeltaLakeManager):
        self.delta = delta_manager
    
    def ingest_quotes(self, quotes_data: pd.DataFrame) -> bool:
        """入湖行情数据"""
        quotes_data['ingestion_time'] = datetime.now()
        quotes_data['date'] = pd.to_datetime(quotes_data['date'])
        
        return self.delta.write_data(
            table_name="quotes",
            data=quotes_data,
            mode="append"
        )
    
    def ingest_bonds(self, bonds_data: pd.DataFrame) -> bool:
        """入湖转债数据"""
        bonds_data['ingestion_time'] = datetime.now()
        
        return self.delta.merge_data(
            table_name="bonds",
            data=bonds_data,
            merge_condition="target.bond_code = source.bond_code"
        )
    
    def ingest_trades(self, trades_data: pd.DataFrame) -> bool:
        """入湖交易数据"""
        trades_data['ingestion_time'] = datetime.now()
        trades_data['trade_date'] = pd.to_datetime(trades_data['trade_date'])
        
        return self.delta.write_data(
            table_name="trades",
            data=trades_data,
            mode="append"
        )
