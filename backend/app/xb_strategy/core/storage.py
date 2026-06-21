"""西部量化可转债策略 V3.0 数据持久化模块

支持:
- ClickHouse时序数据库
- TimescaleDB (PostgreSQL扩展)
- 统一存储接口
- 批量写入优化
- 数据迁移工具
- 查询优化
"""
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any, Union, Iterator
from enum import Enum
import pandas as pd
import numpy as np
import logging
import json
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class StorageBackend(str, Enum):
    """存储后端类型"""
    CLICKHOUSE = "clickhouse"
    TIMESCALEDB = "timescaledb"
    SQLITE = "sqlite"
    MEMORY = "memory"


class DataType(str, Enum):
    """数据类型"""
    CB_DAILY = "cb_daily"           # 转债日线
    STOCK_DAILY = "stock_daily"     # 正股日线
    SIGNALS = "signals"             # 交易信号
    POSITIONS = "positions"         # 持仓记录
    TRADES = "trades"               # 成交记录
    PORTFOLIO = "portfolio"         # 组合净值
    SCORES = "scores"               # 得分记录
    RISK = "risk"                   # 风控记录


# ============ 配置类 ============

@dataclass
class StorageConfig:
    """存储配置"""
    backend: StorageBackend = StorageBackend.MEMORY
    host: str = "localhost"
    port: int = 9000
    database: str = "xb_strategy"
    username: str = "default"
    password: str = ""
    # 连接池
    pool_size: int = 5
    max_overflow: int = 10
    # 批量写入
    batch_size: int = 10000
    flush_interval: float = 1.0  # 秒
    # 性能优化
    compression: bool = True
    replication: bool = False


# ============ 存储接口 ============

class DataStorage(ABC):
    """数据存储抽象接口"""

    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    def close(self):
        """关闭连接"""
        pass

    @abstractmethod
    def create_tables(self):
        """创建表结构"""
        pass

    @abstractmethod
    def insert(self, data_type: DataType, data: Union[pd.DataFrame, List[Dict]]) -> bool:
        """插入数据"""
        pass

    @abstractmethod
    def query(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """查询数据"""
        pass

    @abstractmethod
    def delete(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
    ) -> bool:
        """删除数据"""
        pass

    @abstractmethod
    def get_latest_date(self, data_type: DataType) -> Optional[date]:
        """获取最新数据日期"""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查"""
        pass


# ============ ClickHouse存储 ============

class ClickHouseStorage(DataStorage):
    """ClickHouse存储实现"""

    def __init__(self, config: StorageConfig):
        self.config = config
        self.client = None
        self._batch_buffer: Dict[DataType, List[Dict]] = {}
        self._last_flush = time.time()

    def connect(self) -> bool:
        """建立连接"""
        try:
            from clickhouse_driver import Client

            self.client = Client(
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                user=self.config.username,
                password=self.config.password,
                settings={
                    'max_execution_time': 300,
                    'send_receive_timeout': 300,
                }
            )

            # 测试连接
            self.client.execute('SELECT 1')
            logger.info(f"[ClickHouse] 连接成功: {self.config.host}:{self.config.port}")
            return True

        except ImportError:
            logger.warning("[ClickHouse] clickhouse-driver未安装，请执行: pip install clickhouse-driver")
            return False
        except Exception as e:
            logger.error(f"[ClickHouse] 连接失败: {e}")
            return False

    def close(self):
        """关闭连接"""
        if self.client:
            self._flush_all()
            self.client.disconnect()
            self.client = None

    def create_tables(self):
        """创建表结构"""
        if not self.client:
            return

        # 转债日线表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS cb_daily (
                date Date,
                code String,
                name String,
                stock_code String,
                stock_name String,

                -- 价格
                open Decimal(10, 4),
                high Decimal(10, 4),
                low Decimal(10, 4),
                close Decimal(10, 4),

                -- 成交
                volume UInt64,
                amount Decimal(18, 4),
                turnover_rate Decimal(10, 4),

                -- 转债指标
                conversion_price Decimal(10, 4),
                conversion_ratio Decimal(10, 4),
                conversion_premium Decimal(10, 4),
                pure_bond_premium Decimal(10, 4),
                ytm Decimal(10, 4),

                -- 正股
                stock_close Decimal(10, 4),
                stock_change_pct Decimal(10, 4),

                -- 其他
                remaining_years Decimal(10, 4),
                listed_date Date,
                maturity_date Date,

                -- 时间戳
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            PARTITION BY toYYYYMM(date)
            ORDER BY (code, date)
            SETTINGS index_granularity = 8192
        ''')

        # 正股日线表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS stock_daily (
                date Date,
                code String,
                name String,

                -- 价格
                open Decimal(10, 4),
                high Decimal(10, 4),
                low Decimal(10, 4),
                close Decimal(10, 4),
                change_pct Decimal(10, 4),

                -- 成交
                volume UInt64,
                amount Decimal(18, 4),
                turnover_rate Decimal(10, 4),
                volume_ratio Decimal(10, 4),

                -- 估值
                pe Decimal(10, 4),
                pb Decimal(10, 4),
                total_mv Decimal(18, 4),
                circ_mv Decimal(18, 4),

                -- 行业
                industry String,
                sector String,

                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            PARTITION BY toYYYYMM(date)
            ORDER BY (code, date)
            SETTINGS index_granularity = 8192
        ''')

        # 交易信号表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                signal_id String,
                signal_time DateTime,
                code String,
                name String,
                signal_type String,
                action String,
                quantity Int32,
                price Decimal(10, 4),
                reason String,
                score Decimal(10, 4),
                confidence Decimal(10, 4),
                metadata String,
                status String DEFAULT 'pending',
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (signal_time, code)
            SETTINGS index_granularity = 8192
        ''')

        # 持仓记录表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                snapshot_time DateTime,
                code String,
                name String,
                quantity Int32,
                cost_price Decimal(10, 4),
                market_price Decimal(10, 4),
                market_value Decimal(18, 4),
                profit_loss Decimal(18, 4),
                profit_loss_pct Decimal(10, 4),
                weight Decimal(10, 4),
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (snapshot_time, code)
            SETTINGS index_granularity = 8192
        ''')

        # 成交记录表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                trade_id String,
                trade_time DateTime,
                code String,
                name String,
                side String,
                quantity Int32,
                price Decimal(10, 4),
                amount Decimal(18, 4),
                commission Decimal(10, 4),
                slippage Decimal(10, 4),
                signal_id String,
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (trade_time, code)
            SETTINGS index_granularity = 8192
        ''')

        # 组合净值表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                date Date,
                aum Decimal(18, 4),
                total_value Decimal(18, 4),
                cash Decimal(18, 4),
                position_count UInt32,
                daily_return Decimal(10, 4),
                cumulative_return Decimal(10, 4),
                max_drawdown Decimal(10, 4),
                sharpe Decimal(10, 4),
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY date
            SETTINGS index_granularity = 8192
        ''')

        # 得分记录表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS scores (
                score_time DateTime,
                code String,
                name String,
                total_score Decimal(10, 4),
                stock_score Decimal(10, 4),
                cb_score Decimal(10, 4),
                rank UInt32,
                in_whitelist UInt8,
                factors String,
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (score_time, code)
            SETTINGS index_granularity = 8192
        ''')

        # 风控记录表
        self.client.execute('''
            CREATE TABLE IF NOT EXISTS risk (
                risk_time DateTime,
                risk_type String,
                risk_level String,
                code String,
                message String,
                value Decimal(10, 4),
                threshold Decimal(10, 4),
                action_taken String,
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (risk_time, risk_type)
            SETTINGS index_granularity = 8192
        ''')

        logger.info("[ClickHouse] 表结构创建完成")

    def insert(self, data_type: DataType, data: Union[pd.DataFrame, List[Dict]]) -> bool:
        """插入数据"""
        if not self.client:
            return False

        try:
            if isinstance(data, pd.DataFrame):
                records = data.to_dict('records')
            else:
                records = data

            if not records:
                return True

            # 添加到缓冲区
            if data_type not in self._batch_buffer:
                self._batch_buffer[data_type] = []

            self._batch_buffer[data_type].extend(records)

            # 检查是否需要刷新
            if len(self._batch_buffer[data_type]) >= self.config.batch_size:
                self._flush(data_type)
            elif time.time() - self._last_flush >= self.config.flush_interval:
                self._flush_all()

            return True

        except Exception as e:
            logger.error(f"[ClickHouse] 插入数据失败: {e}")
            return False

    def _flush(self, data_type: DataType):
        """刷新指定类型的缓冲区"""
        if data_type not in self._batch_buffer or not self._batch_buffer[data_type]:
            return

        records = self._batch_buffer[data_type]
        table_name = data_type.value

        try:
            # 获取列名
            columns = list(records[0].keys())

            # 构建INSERT语句
            sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES"

            # 准备数据
            values = []
            for record in records:
                row = []
                for col in columns:
                    val = record.get(col)
                    if isinstance(val, (datetime, date)):
                        row.append(val)
                    elif isinstance(val, (np.integer, np.floating)):
                        row.append(float(val))
                    elif pd.isna(val):
                        row.append(None)
                    else:
                        row.append(val)
                values.append(tuple(row))

            self.client.execute(sql, values)
            logger.debug(f"[ClickHouse] 插入{len(values)}条记录到{table_name}")

            # 清空缓冲区
            self._batch_buffer[data_type] = []
            self._last_flush = time.time()

        except Exception as e:
            logger.error(f"[ClickHouse] 刷新缓冲区失败: {e}")

    def _flush_all(self):
        """刷新所有缓冲区"""
        for data_type in list(self._batch_buffer.keys()):
            self._flush(data_type)

    def query(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """查询数据"""
        if not self.client:
            return pd.DataFrame()

        try:
            table_name = data_type.value
            conditions = []
            params = {}

            # 日期过滤
            if start_date:
                conditions.append("date >= %(start_date)s")
                params['start_date'] = start_date
            if end_date:
                conditions.append("date <= %(end_date)s")
                params['end_date'] = end_date

            # 代码过滤 - 使用命名占位符避免 SQL 注入
            if codes:
                code_placeholders = ','.join([f"%(code_{i})s" for i in range(len(codes))])
                conditions.append(f"code IN ({code_placeholders})")
                for i, c in enumerate(codes):
                    params[f"code_{i}"] = str(c).replace("'", "").replace('"', '')[:20]

            # 其他过滤条件 - 防止 SQL 注入
            if filters:
                _ALLOWED_FILTER_KEYS = {'date', 'code', 'name', 'price', 'volume', 'industry'}
                for key, value in filters.items():
                    if key not in _ALLOWED_FILTER_KEYS:
                        continue
                    if isinstance(value, (list, tuple)):
                        placeholders = ','.join([f"%({key}_{i})s" for i in range(len(value))])
                        conditions.append(f"{key} IN ({placeholders})")
                        for i, v in enumerate(value):
                            params[f"{key}_{i}"] = str(v)[:100]
                    else:
                        conditions.append(f"{key} = %({key}_v)s")
                        params[f"{key}_v"] = str(value)[:100]

            where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

            # 限制条数 - 强制类型安全
            try:
                safe_limit = int(limit) if limit else None
            except (TypeError, ValueError):
                safe_limit = None
            if safe_limit is not None and safe_limit < 0:
                safe_limit = None
            limit_clause = f" LIMIT {int(safe_limit)}" if safe_limit is not None and safe_limit > 0 else ""

            sql = f"SELECT * FROM {table_name}{where_clause} ORDER BY date, code{limit_clause}"

            result = self.client.execute(sql, params or None, with_column_types=True)
            columns = [col[0] for col in result[1]]
            data = result[0]

            return pd.DataFrame(data, columns=columns)

        except Exception as e:
            logger.error(f"[ClickHouse] 查询失败: {e}")
            return pd.DataFrame()

    def delete(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
    ) -> bool:
        """删除数据"""
        if not self.client:
            return False

        try:
            table_name = data_type.value
            conditions = []

            if start_date:
                conditions.append(f"date >= '{start_date}'")
            if end_date:
                conditions.append(f"date <= '{end_date}'")
            if codes:
                codes_str = ','.join([f"'{c}'" for c in codes])
                conditions.append(f"code IN ({codes_str})")

            if not conditions:
                logger.warning("[ClickHouse] 删除操作需要指定条件")
                return False

            sql = f"ALTER TABLE {table_name} DELETE WHERE {' AND '.join(conditions)}"
            self.client.execute(sql)

            logger.info(f"[ClickHouse] 删除{table_name}数据: {' AND '.join(conditions)}")
            return True

        except Exception as e:
            logger.error(f"[ClickHouse] 删除失败: {e}")
            return False

    def get_latest_date(self, data_type: DataType) -> Optional[date]:
        """获取最新数据日期"""
        if not self.client:
            return None

        try:
            table_name = data_type.value
            sql = f"SELECT max(date) FROM {table_name}"
            result = self.client.execute(sql)

            if result and result[0] and result[0][0]:
                return result[0][0]
            return None

        except Exception as e:
            logger.error(f"[ClickHouse] 获取最新日期失败: {e}")
            return None

    def health_check(self) -> bool:
        """健康检查"""
        if not self.client:
            return False

        try:
            self.client.execute('SELECT 1')
            return True
        except Exception:
            return False

    @contextmanager
    def transaction(self):
        """事务上下文"""
        try:
            yield self
            self._flush_all()
        except Exception as e:
            logger.error(f"[ClickHouse] 事务失败: {e}")
            raise


# ============ TimescaleDB存储 ============

class TimescaleDBStorage(DataStorage):
    """TimescaleDB存储实现"""

    def __init__(self, config: StorageConfig):
        self.config = config
        self.conn = None
        self._batch_buffer: Dict[DataType, List[Dict]] = {}
        self._last_flush = time.time()

        # TimescaleDB默认端口
        if config.port == 9000:
            self.config.port = 5432

    def connect(self) -> bool:
        """建立连接"""
        try:
            import psycopg2
            from psycopg2.extras import execute_batch
            from psycopg2 import pool

            self.pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=self.config.pool_size,
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                user=self.config.username,
                password=self.config.password,
            )

            # 测试连接
            conn = self.pool.getconn()
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            self.pool.putconn(conn)

            logger.info(f"[TimescaleDB] 连接成功: {self.config.host}:{self.config.port}")
            return True

        except ImportError:
            logger.warning("[TimescaleDB] psycopg2未安装，请执行: pip install psycopg2-binary")
            return False
        except Exception as e:
            logger.error(f"[TimescaleDB] 连接失败: {e}")
            return False

    def _get_connection(self):
        """获取连接"""
        return self.pool.getconn()

    def _return_connection(self, conn):
        """归还连接"""
        self.pool.putconn(conn)

    def close(self):
        """关闭连接"""
        if hasattr(self, 'pool') and self.pool:
            self._flush_all()
            self.pool.closeall()

    def create_tables(self):
        """创建表结构"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # 转债日线表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cb_daily (
                    date DATE NOT NULL,
                    code VARCHAR(20) NOT NULL,
                    name VARCHAR(50),
                    stock_code VARCHAR(20),
                    stock_name VARCHAR(50),

                    open NUMERIC(10, 4),
                    high NUMERIC(10, 4),
                    low NUMERIC(10, 4),
                    close NUMERIC(10, 4),

                    volume BIGINT,
                    amount NUMERIC(18, 4),
                    turnover_rate NUMERIC(10, 4),

                    conversion_price NUMERIC(10, 4),
                    conversion_ratio NUMERIC(10, 4),
                    conversion_premium NUMERIC(10, 4),
                    pure_bond_premium NUMERIC(10, 4),
                    ytm NUMERIC(10, 4),

                    stock_close NUMERIC(10, 4),
                    stock_change_pct NUMERIC(10, 4),

                    remaining_years NUMERIC(10, 4),
                    listed_date DATE,
                    maturity_date DATE,

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (date, code)
                )
            ''')

            # 正股日线表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_daily (
                    date DATE NOT NULL,
                    code VARCHAR(20) NOT NULL,
                    name VARCHAR(50),

                    open NUMERIC(10, 4),
                    high NUMERIC(10, 4),
                    low NUMERIC(10, 4),
                    close NUMERIC(10, 4),
                    change_pct NUMERIC(10, 4),

                    volume BIGINT,
                    amount NUMERIC(18, 4),
                    turnover_rate NUMERIC(10, 4),
                    volume_ratio NUMERIC(10, 4),

                    pe NUMERIC(10, 4),
                    pb NUMERIC(10, 4),
                    total_mv NUMERIC(18, 4),
                    circ_mv NUMERIC(18, 4),

                    industry VARCHAR(50),
                    sector VARCHAR(50),

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (date, code)
                )
            ''')

            # 交易信号表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id VARCHAR(50) PRIMARY KEY,
                    signal_time TIMESTAMP NOT NULL,
                    code VARCHAR(20) NOT NULL,
                    name VARCHAR(50),
                    signal_type VARCHAR(20),
                    action VARCHAR(20),
                    quantity INTEGER,
                    price NUMERIC(10, 4),
                    reason TEXT,
                    score NUMERIC(10, 4),
                    confidence NUMERIC(10, 4),
                    metadata JSONB,
                    status VARCHAR(20) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 持仓记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    snapshot_time TIMESTAMP NOT NULL,
                    code VARCHAR(20) NOT NULL,
                    name VARCHAR(50),
                    quantity INTEGER,
                    cost_price NUMERIC(10, 4),
                    market_price NUMERIC(10, 4),
                    market_value NUMERIC(18, 4),
                    profit_loss NUMERIC(18, 4),
                    profit_loss_pct NUMERIC(10, 4),
                    weight NUMERIC(10, 4),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (snapshot_time, code)
                )
            ''')

            # 成交记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id VARCHAR(50) PRIMARY KEY,
                    trade_time TIMESTAMP NOT NULL,
                    code VARCHAR(20) NOT NULL,
                    name VARCHAR(50),
                    side VARCHAR(10),
                    quantity INTEGER,
                    price NUMERIC(10, 4),
                    amount NUMERIC(18, 4),
                    commission NUMERIC(10, 4),
                    slippage NUMERIC(10, 4),
                    signal_id VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 组合净值表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfolio (
                    date DATE PRIMARY KEY,
                    aum NUMERIC(18, 4),
                    total_value NUMERIC(18, 4),
                    cash NUMERIC(18, 4),
                    position_count INTEGER,
                    daily_return NUMERIC(10, 4),
                    cumulative_return NUMERIC(10, 4),
                    max_drawdown NUMERIC(10, 4),
                    sharpe NUMERIC(10, 4),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 得分记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scores (
                    score_time TIMESTAMP NOT NULL,
                    code VARCHAR(20) NOT NULL,
                    name VARCHAR(50),
                    total_score NUMERIC(10, 4),
                    stock_score NUMERIC(10, 4),
                    cb_score NUMERIC(10, 4),
                    rank INTEGER,
                    in_whitelist BOOLEAN,
                    factors JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (score_time, code)
                )
            ''')

            # 风控记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS risk (
                    risk_time TIMESTAMP NOT NULL,
                    risk_type VARCHAR(30),
                    risk_level VARCHAR(20),
                    code VARCHAR(20),
                    message TEXT,
                    value NUMERIC(10, 4),
                    threshold NUMERIC(10, 4),
                    action_taken VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建TimescaleDB hypertable (时序表)
            try:
                cursor.execute("SELECT create_hypertable('cb_daily', 'date', if_not_exists => TRUE)")
                cursor.execute("SELECT create_hypertable('stock_daily', 'date', if_not_exists => TRUE)")
                cursor.execute("SELECT create_hypertable('positions', 'snapshot_time', if_not_exists => TRUE)")
                cursor.execute("SELECT create_hypertable('portfolio', 'date', if_not_exists => TRUE)")
                cursor.execute("SELECT create_hypertable('scores', 'score_time', if_not_exists => TRUE)")
                cursor.execute("SELECT create_hypertable('risk', 'risk_time', if_not_exists => TRUE)")
            except Exception as e:
                logger.debug(f"[TimescaleDB] hypertable可能已存在: {e}")

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cb_daily_code ON cb_daily(code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(signal_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(trade_time)")

            conn.commit()
            logger.info("[TimescaleDB] 表结构创建完成")

        except Exception as e:
            conn.rollback()
            logger.error(f"[TimescaleDB] 创建表失败: {e}")
        finally:
            self._return_connection(conn)

    def insert(self, data_type: DataType, data: Union[pd.DataFrame, List[Dict]]) -> bool:
        """插入数据"""
        if not hasattr(self, 'pool') or not self.pool:
            return False

        try:
            if isinstance(data, pd.DataFrame):
                records = data.to_dict('records')
            else:
                records = data

            if not records:
                return True

            # 添加到缓冲区
            if data_type not in self._batch_buffer:
                self._batch_buffer[data_type] = []

            self._batch_buffer[data_type].extend(records)

            # 检查是否需要刷新
            if len(self._batch_buffer[data_type]) >= self.config.batch_size:
                self._flush(data_type)
            elif time.time() - self._last_flush >= self.config.flush_interval:
                self._flush_all()

            return True

        except Exception as e:
            logger.error(f"[TimescaleDB] 插入数据失败: {e}")
            return False

    def _flush(self, data_type: DataType):
        """刷新指定类型的缓冲区"""
        if data_type not in self._batch_buffer or not self._batch_buffer[data_type]:
            return

        records = self._batch_buffer[data_type]
        table_name = data_type.value

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # 获取列名
            columns = list(records[0].keys())
            placeholders = ','.join(['%s'] * len(columns))
            columns_str = ','.join(columns)

            sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

            # 准备数据
            values_list = []
            for record in records:
                row = []
                for col in columns:
                    val = record.get(col)
                    if isinstance(val, (datetime, date)):
                        row.append(val)
                    elif isinstance(val, (np.integer, np.floating)):
                        row.append(float(val))
                    elif pd.isna(val):
                        row.append(None)
                    elif isinstance(val, (dict, list)):
                        row.append(json.dumps(val))
                    else:
                        row.append(val)
                values_list.append(tuple(row))

            from psycopg2.extras import execute_batch
            execute_batch(cursor, sql, values_list)

            conn.commit()
            logger.debug(f"[TimescaleDB] 插入{len(values_list)}条记录到{table_name}")

            # 清空缓冲区
            self._batch_buffer[data_type] = []
            self._last_flush = time.time()

        except Exception as e:
            conn.rollback()
            logger.error(f"[TimescaleDB] 刷新缓冲区失败: {e}")
        finally:
            self._return_connection(conn)

    def _flush_all(self):
        """刷新所有缓冲区"""
        for data_type in list(self._batch_buffer.keys()):
            self._flush(data_type)

    def query(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """查询数据"""
        if not hasattr(self, 'pool') or not self.pool:
            return pd.DataFrame()

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            table_name = data_type.value
            conditions = []
            params = []

            if start_date:
                conditions.append("date >= %s")
                params.append(start_date)
            if end_date:
                conditions.append("date <= %s")
                params.append(end_date)

            if codes:
                placeholders = ','.join(['%s'] * len(codes))
                conditions.append(f"code IN ({placeholders})")
                params.extend(codes)

            if filters:
                for key, value in filters.items():
                    if isinstance(value, (list, tuple)):
                        placeholders = ','.join(['%s'] * len(value))
                        conditions.append(f"{key} IN ({placeholders})")
                        params.extend(value)
                    else:
                        conditions.append(f"{key} = %s")
                        params.append(value)

            where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            limit_clause = f" LIMIT {limit}" if limit else ""

            sql = f"SELECT * FROM {table_name}{where_clause} ORDER BY date, code{limit_clause}"

            cursor.execute(sql, params)
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()

            return pd.DataFrame(data, columns=columns)

        except Exception as e:
            logger.error(f"[TimescaleDB] 查询失败: {e}")
            return pd.DataFrame()
        finally:
            self._return_connection(conn)

    def delete(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
    ) -> bool:
        """删除数据"""
        if not hasattr(self, 'pool') or not self.pool:
            return False

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            table_name = data_type.value
            conditions = []
            params = []

            if start_date:
                conditions.append("date >= %s")
                params.append(start_date)
            if end_date:
                conditions.append("date <= %s")
                params.append(end_date)
            if codes:
                placeholders = ','.join(['%s'] * len(codes))
                conditions.append(f"code IN ({placeholders})")
                params.extend(codes)

            if not conditions:
                logger.warning("[TimescaleDB] 删除操作需要指定条件")
                return False

            sql = f"DELETE FROM {table_name} WHERE {' AND '.join(conditions)}"
            cursor.execute(sql, params)
            conn.commit()

            logger.info(f"[TimescaleDB] 删除{table_name}数据")
            return True

        except Exception as e:
            conn.rollback()
            logger.error(f"[TimescaleDB] 删除失败: {e}")
            return False
        finally:
            self._return_connection(conn)

    def get_latest_date(self, data_type: DataType) -> Optional[date]:
        """获取最新数据日期"""
        if not hasattr(self, 'pool') or not self.pool:
            return None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            table_name = data_type.value
            sql = f"SELECT MAX(date) FROM {table_name}"
            cursor.execute(sql)
            result = cursor.fetchone()

            if result and result[0]:
                return result[0]
            return None

        except Exception as e:
            logger.error(f"[TimescaleDB] 获取最新日期失败: {e}")
            return None
        finally:
            self._return_connection(conn)

    def health_check(self) -> bool:
        """健康检查"""
        if not hasattr(self, 'pool') or not self.pool:
            return False

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            return True
        except Exception:
            return False
        finally:
            self._return_connection(conn)


# ============ 内存存储(测试用) ============

class MemoryStorage(DataStorage):
    """内存存储实现 - 用于测试"""

    def __init__(self, config: StorageConfig = None):
        self.config = config or StorageConfig()
        self._data: Dict[DataType, pd.DataFrame] = {}

    def connect(self) -> bool:
        return True

    def close(self):
        self._data.clear()

    def create_tables(self):
        pass

    def insert(self, data_type: DataType, data: Union[pd.DataFrame, List[Dict]]) -> bool:
        try:
            if isinstance(data, list):
                df = pd.DataFrame(data)
            else:
                df = data.copy()

            if data_type in self._data:
                self._data[data_type] = pd.concat([self._data[data_type], df], ignore_index=True)
            else:
                self._data[data_type] = df

            return True
        except Exception as e:
            logger.error(f"[MemoryStorage] 插入失败: {e}")
            return False

    def query(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        if data_type not in self._data:
            return pd.DataFrame()

        df = self._data[data_type].copy()

        if start_date and 'date' in df.columns:
            df = df[df['date'] >= start_date]
        if end_date and 'date' in df.columns:
            df = df[df['date'] <= end_date]
        if codes and 'code' in df.columns:
            df = df[df['code'].isin(codes)]
        if filters:
            for key, value in filters.items():
                if key in df.columns:
                    if isinstance(value, (list, tuple)):
                        df = df[df[key].isin(value)]
                    else:
                        df = df[df[key] == value]

        if limit:
            df = df.head(limit)

        return df

    def delete(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
    ) -> bool:
        if data_type not in self._data:
            return True

        df = self._data[data_type]
        mask = pd.Series([True] * len(df))

        if start_date and 'date' in df.columns:
            mask &= (df['date'] >= start_date)
        if end_date and 'date' in df.columns:
            mask &= (df['date'] <= end_date)
        if codes and 'code' in df.columns:
            mask &= (df['code'].isin(codes))

        self._data[data_type] = df[~mask]
        return True

    def get_latest_date(self, data_type: DataType) -> Optional[date]:
        if data_type not in self._data or self._data[data_type].empty:
            return None

        df = self._data[data_type]
        if 'date' in df.columns:
            return df['date'].max()
        return None

    def health_check(self) -> bool:
        return True


# ============ 存储管理器 ============

class StorageManager:
    """存储管理器 - 统一管理数据存储"""

    _instance = None

    def __new__(cls, config: StorageConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: StorageConfig = None):
        if self._initialized:
            return

        self.config = config or StorageConfig()
        self.storage = self._create_storage()
        self._initialized = True

    def _create_storage(self) -> DataStorage:
        """创建存储实例"""
        if self.config.backend == StorageBackend.CLICKHOUSE:
            return ClickHouseStorage(self.config)
        elif self.config.backend == StorageBackend.TIMESCALEDB:
            return TimescaleDBStorage(self.config)
        else:
            return MemoryStorage(self.config)

    def connect(self) -> bool:
        """建立连接"""
        result = self.storage.connect()
        if result:
            self.storage.create_tables()
        return result

    def close(self):
        """关闭连接"""
        self.storage.close()

    def save_daily_data(
        self,
        cb_data: pd.DataFrame,
        stock_data: Optional[pd.DataFrame] = None,
    ) -> bool:
        """保存日线数据"""
        success = self.storage.insert(DataType.CB_DAILY, cb_data)

        if stock_data is not None:
            success &= self.storage.insert(DataType.STOCK_DAILY, stock_data)

        return success

    def save_signals(self, signals: List[Dict]) -> bool:
        """保存交易信号"""
        return self.storage.insert(DataType.SIGNALS, signals)

    def save_positions(self, positions: List[Dict]) -> bool:
        """保存持仓快照"""
        return self.storage.insert(DataType.POSITIONS, positions)

    def save_trades(self, trades: List[Dict]) -> bool:
        """保存成交记录"""
        return self.storage.insert(DataType.TRADES, trades)

    def save_portfolio(self, portfolio_data: Dict) -> bool:
        """保存组合净值"""
        return self.storage.insert(DataType.PORTFOLIO, [portfolio_data])

    def save_scores(self, scores: List[Dict]) -> bool:
        """保存得分记录"""
        return self.storage.insert(DataType.SCORES, scores)

    def save_risk_alerts(self, alerts: List[Dict]) -> bool:
        """保存风控记录"""
        return self.storage.insert(DataType.RISK, alerts)

    def get_cb_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取转债数据"""
        return self.storage.query(DataType.CB_DAILY, start_date, end_date, codes)

    def get_stock_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        codes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取正股数据"""
        return self.storage.query(DataType.STOCK_DAILY, start_date, end_date, codes)

    def get_signals(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """获取交易信号"""
        return self.storage.query(DataType.SIGNALS, start_date, end_date)

    def get_portfolio_history(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """获取净值曲线"""
        return self.storage.query(DataType.PORTFOLIO, start_date, end_date)

    def get_latest_cb_date(self) -> Optional[date]:
        """获取转债数据最新日期"""
        return self.storage.get_latest_date(DataType.CB_DAILY)

    def health_check(self) -> bool:
        """健康检查"""
        return self.storage.health_check()


# ============ 便捷函数 ============

def get_storage_manager(config: StorageConfig = None) -> StorageManager:
    """获取存储管理器单例"""
    return StorageManager(config)


def init_clickhouse(
    host: str = "localhost",
    port: int = 9000,
    database: str = "xb_strategy",
    username: str = "default",
    password: str = "",
) -> StorageManager:
    """初始化ClickHouse存储"""
    config = StorageConfig(
        backend=StorageBackend.CLICKHOUSE,
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )
    manager = StorageManager(config)
    manager.connect()
    return manager


def init_timescaledb(
    host: str = "localhost",
    port: int = 5432,
    database: str = "xb_strategy",
    username: str = "postgres",
    password: str = "",
) -> StorageManager:
    """初始化TimescaleDB存储"""
    config = StorageConfig(
        backend=StorageBackend.TIMESCALEDB,
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )
    manager = StorageManager(config)
    manager.connect()
    return manager


# ============ 数据迁移工具 ============

class DataMigrator:
    """数据迁移工具"""

    def __init__(self, source: DataStorage, target: DataStorage):
        self.source = source
        self.target = target

    def migrate(
        self,
        data_type: DataType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        batch_size: int = 50000,
    ) -> int:
        """迁移数据

        Args:
            data_type: 数据类型
            start_date: 开始日期
            end_date: 结束日期
            batch_size: 批次大小

        Returns:
            迁移记录数
        """
        total_count = 0
        offset = 0

        while True:
            # 分批读取
            df = self.source.query(
                data_type,
                start_date,
                end_date,
                limit=batch_size,
            )

            if df.empty:
                break

            # 写入目标
            records = df.to_dict('records')
            self.target.insert(data_type, records)

            total_count += len(records)
            offset += batch_size

            logger.info(f"[Migration] 已迁移{total_count}条{data_type.value}记录")

            if len(records) < batch_size:
                break

        logger.info(f"[Migration] 完成，共迁移{total_count}条记录")
        return total_count

    def migrate_all(self) -> Dict[DataType, int]:
        """迁移所有数据"""
        results = {}

        for data_type in DataType:
            count = self.migrate(data_type)
            results[data_type] = count

        return results
