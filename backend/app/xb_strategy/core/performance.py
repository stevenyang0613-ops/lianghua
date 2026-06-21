"""西部量化可转债策略 V3.0 性能优化模块

功能:
- 数据库索引优化
- 查询性能优化
- 批量数据处理
- 连接池管理
- 查询缓存
- 性能分析工具
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import time
import functools
import threading
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class IndexType(str, Enum):
    """索引类型"""
    BTREE = "btree"
    HASH = "hash"
    GIN = "gin"
    GIST = "gist"


class QueryType(str, Enum):
    """查询类型"""
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


# ============ 配置类 ============

@dataclass
class IndexDefinition:
    """索引定义"""
    name: str
    table: str
    columns: List[str]
    index_type: IndexType = IndexType.BTREE
    unique: bool = False
    condition: str = None  # 部分索引条件

    def to_sql(self, dialect: str = "postgresql") -> str:
        """生成SQL"""
        columns_str = ", ".join(self.columns)

        if dialect == "postgresql":
            sql = f"CREATE {'UNIQUE ' if self.unique else ''}INDEX IF NOT EXISTS {self.name} ON {self.table} USING {self.index_type.value} ({columns_str})"
            if self.condition:
                sql += f" WHERE {self.condition}"
        elif dialect == "clickhouse":
            sql = f"ALTER TABLE {self.table} ADD INDEX IF NOT EXISTS {self.name} ({columns_str}) TYPE {self.index_type.value} GRANULARITY 4"
        else:
            sql = f"CREATE {'UNIQUE ' if self.unique else ''}INDEX IF NOT EXISTS {self.name} ON {self.table} ({columns_str})"

        return sql


@dataclass
class QueryPlan:
    """查询计划"""
    query: str
    execution_time: float
    rows_examined: int
    rows_sent: int
    indexes_used: List[str]
    full_scan: bool
    suggestions: List[str]


# ============ 索引管理器 ============

class IndexManager:
    """索引管理器"""

    # 预定义索引
    DEFAULT_INDEXES = [
        # ClickHouse索引
        IndexDefinition(
            name="idx_cb_daily_date",
            table="cb_daily_data",
            columns=["trade_date"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_cb_daily_code",
            table="cb_daily_data",
            columns=["cb_code"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_cb_daily_code_date",
            table="cb_daily_data",
            columns=["cb_code", "trade_date"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_stock_daily_code_date",
            table="stock_daily_data",
            columns=["stock_code", "trade_date"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_signals_date",
            table="trading_signals",
            columns=["signal_date"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_signals_code_date",
            table="trading_signals",
            columns=["cb_code", "signal_date"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_positions_portfolio",
            table="positions",
            columns=["portfolio_id"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_trades_date",
            table="trades",
            columns=["trade_date"],
            index_type=IndexType.BTREE,
        ),
        # PostgreSQL索引
        IndexDefinition(
            name="idx_scores_code_date",
            table="cb_scores",
            columns=["cb_code", "score_date"],
            index_type=IndexType.BTREE,
        ),
        IndexDefinition(
            name="idx_risk_records_date",
            table="risk_records",
            columns=["record_date"],
            index_type=IndexType.BTREE,
        ),
        # 部分索引
        IndexDefinition(
            name="idx_active_signals",
            table="trading_signals",
            columns=["cb_code"],
            index_type=IndexType.BTREE,
            condition="status = 'active'",
        ),
    ]

    def __init__(self, db_type: str = "postgresql"):
        self.db_type = db_type
        self._created_indexes: Dict[str, bool] = {}

    def get_create_statements(self) -> List[str]:
        """获取所有创建语句"""
        return [idx.to_sql(self.db_type) for idx in self.DEFAULT_INDEXES]

    def create_index(self, conn, index: IndexDefinition) -> bool:
        """创建索引"""
        try:
            sql = index.to_sql(self.db_type)
            conn.execute(sql)
            self._created_indexes[index.name] = True
            logger.info(f"[IndexManager] 创建索引成功: {index.name}")
            return True
        except Exception as e:
            logger.error(f"[IndexManager] 创建索引失败: {index.name}, {e}")
            return False

    def create_all_indexes(self, conn) -> int:
        """创建所有索引"""
        success_count = 0
        for index in self.DEFAULT_INDEXES:
            if self.create_index(conn, index):
                success_count += 1
        return success_count

    def drop_index(self, conn, index_name: str) -> bool:
        """删除索引"""
        try:
            if self.db_type == "postgresql":
                conn.execute(f"DROP INDEX IF EXISTS {index_name}")
            elif self.db_type == "clickhouse":
                # ClickHouse索引不能直接删除
                pass
            logger.info(f"[IndexManager] 删除索引成功: {index_name}")
            return True
        except Exception as e:
            logger.error(f"[IndexManager] 删除索引失败: {index_name}, {e}")
            return False

    def analyze_index_usage(self, conn) -> Dict[str, Any]:
        """分析索引使用情况"""
        if self.db_type != "postgresql":
            return {}

        try:
            query = """
            SELECT
                schemaname,
                relname as table_name,
                indexrelname as index_name,
                idx_scan as index_scans,
                idx_tup_read as tuples_read,
                idx_tup_fetch as tuples_fetched
            FROM pg_stat_user_indexes
            ORDER BY idx_scan DESC
            """
            result = conn.execute(query).fetchall()
            return {
                row["index_name"]: {
                    "table": row["table_name"],
                    "scans": row["index_scans"],
                    "tuples_read": row["tuples_read"],
                    "tuples_fetched": row["tuples_fetched"],
                }
                for row in result
            }
        except Exception as e:
            logger.error(f"[IndexManager] 分析索引使用失败: {e}")
            return {}


# ============ 查询优化器 ============

class QueryOptimizer:
    """查询优化器"""

    def __init__(self):
        self._query_stats: Dict[str, List[float]] = defaultdict(list)
        self._slow_queries: List[Dict] = []
        self._slow_threshold = 1.0  # 秒

    def analyze_query(self, conn, query: str) -> QueryPlan:
        """分析查询计划"""
        start_time = time.time()

        # 获取执行计划
        explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
        result = conn.execute(explain_query).fetchone()

        execution_time = time.time() - start_time

        if result:
            plan_data = json.loads(result[0]) if isinstance(result[0], str) else result[0]
            return self._parse_explain(plan_data, query, execution_time)

        return QueryPlan(
            query=query,
            execution_time=execution_time,
            rows_examined=0,
            rows_sent=0,
            indexes_used=[],
            full_scan=False,
            suggestions=[],
        )

    def _parse_explain(self, plan_data: Dict, query: str, execution_time: float) -> QueryPlan:
        """解析EXPLAIN结果"""
        plan = plan_data[0] if isinstance(plan_data, list) else plan_data

        indexes_used = []
        full_scan = False
        rows_examined = 0
        rows_sent = 0
        suggestions = []

        def traverse(node):
            nonlocal full_scan, rows_examined, rows_sent

            node_type = node.get("Node Type", "")

            if node_type == "Seq Scan":
                full_scan = True
                suggestions.append(f"考虑添加索引以避免全表扫描: {node.get('Relation Name', '')}")

            elif node_type == "Index Scan":
                index_name = node.get("Index Name", "")
                if index_name:
                    indexes_used.append(index_name)

            rows_examined += node.get("Plan Rows", 0)
            rows_sent = node.get("Actual Rows", 0)

            # 遍历子节点
            if "Plans" in node:
                for child in node["Plans"]:
                    traverse(child)

        traverse(plan["Plan"])

        # 添加建议
        if full_scan:
            suggestions.append("查询执行了全表扫描，建议添加适当的索引")

        if execution_time > self._slow_threshold:
            suggestions.append(f"查询执行时间较长({execution_time:.3f}s)，考虑优化查询结构")

        return QueryPlan(
            query=query,
            execution_time=execution_time,
            rows_examined=rows_examined,
            rows_sent=rows_sent,
            indexes_used=indexes_used,
            full_scan=full_scan,
            suggestions=suggestions,
        )

    def record_query(self, query: str, execution_time: float):
        """记录查询执行时间"""
        self._query_stats[query].append(execution_time)

        if execution_time > self._slow_threshold:
            self._slow_queries.append({
                "query": query,
                "execution_time": execution_time,
                "timestamp": datetime.now().isoformat(),
            })

    def get_slow_queries(self, limit: int = 10) -> List[Dict]:
        """获取慢查询"""
        return sorted(self._slow_queries, key=lambda x: x["execution_time"], reverse=True)[:limit]

    def get_query_stats(self) -> Dict[str, Dict]:
        """获取查询统计"""
        stats = {}
        for query, times in self._query_stats.items():
            if times:
                stats[query] = {
                    "count": len(times),
                    "avg_time": sum(times) / len(times),
                    "max_time": max(times),
                    "min_time": min(times),
                }
        return stats


# ============ 批量数据处理 ============

class BatchProcessor:
    """批量数据处理器"""

    def __init__(self, batch_size: int = 1000):
        self.batch_size = batch_size
        self._buffer: List[Dict] = []
        self._lock = threading.Lock()

    def add(self, record: Dict):
        """添加记录"""
        with self._lock:
            self._buffer.append(record)

            if len(self._buffer) >= self.batch_size:
                return self._flush()
        return 0

    def add_many(self, records: List[Dict]) -> int:
        """批量添加"""
        with self._lock:
            self._buffer.extend(records)

            if len(self._buffer) >= self.batch_size:
                return self._flush()
        return 0

    def _flush(self) -> int:
        """刷新缓冲区"""
        if not self._buffer:
            return 0

        count = len(self._buffer)
        self._buffer = []
        return count

    def flush(self) -> int:
        """手动刷新"""
        with self._lock:
            return self._flush()

    def get_size(self) -> int:
        """获取缓冲区大小"""
        return len(self._buffer)


class BulkInserter:
    """批量插入器"""

    def __init__(self, conn, table: str, batch_size: int = 1000):
        self.conn = conn
        self.table = table
        self.batch_size = batch_size
        self._buffer: List[Dict] = []
        self._columns: List[str] = []

    def add(self, record: Dict):
        """添加记录"""
        if not self._columns:
            self._columns = list(record.keys())

        self._buffer.append(record)

        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self) -> int:
        """执行批量插入"""
        if not self._buffer:
            return 0

        try:
            # 构建INSERT语句
            columns = ", ".join(self._columns)
            placeholders = ", ".join(["%s"] * len(self._columns))
            sql = f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})"

            # 准备数据
            values = [[record.get(col) for col in self._columns] for record in self._buffer]

            # 执行批量插入
            self.conn.executemany(sql, values)

            count = len(self._buffer)
            self._buffer = []
            return count

        except Exception as e:
            logger.error(f"[BulkInserter] 批量插入失败: {e}")
            return 0


# ============ 连接池优化 ============

class ConnectionPoolMonitor:
    """连接池监控"""

    def __init__(self):
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "idle_connections": 0,
            "waiting_requests": 0,
        }
        self._history: List[Dict] = []

    def update(self, stats: Dict):
        """更新统计"""
        self._stats = stats
        self._history.append({
            "timestamp": datetime.now().isoformat(),
            **stats,
        })

        # 保留最近1000条记录
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

    def get_stats(self) -> Dict:
        """获取统计"""
        return self._stats.copy()

    def get_history(self, limit: int = 100) -> List[Dict]:
        """获取历史"""
        return self._history[-limit:]


# ============ 查询缓存装饰器 ============

class QueryCache:
    """查询缓存"""

    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._cache: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry["timestamp"] < self.ttl:
                    return entry["value"]
                else:
                    del self._cache[key]
        return None

    def set(self, key: str, value: Any):
        """设置缓存"""
        with self._lock:
            self._cache[key] = {
                "value": value,
                "timestamp": time.time(),
            }

    def delete(self, key: str):
        """删除缓存"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def cached(self, key_func: Callable = None):
        """缓存装饰器"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # 生成缓存键
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

                # 检查缓存
                cached_result = self.get(cache_key)
                if cached_result is not None:
                    return cached_result

                # 执行函数
                result = func(*args, **kwargs)

                # 缓存结果
                self.set(cache_key, result)

                return result

            return wrapper
        return decorator


# ============ 性能分析器 ============

class PerformanceProfiler:
    """性能分析器"""

    def __init__(self):
        self._traces: Dict[str, List[float]] = defaultdict(list)
        self._active_spans: Dict[str, float] = {}

    def start_span(self, name: str):
        """开始追踪"""
        self._active_spans[name] = time.time()

    def end_span(self, name: str) -> float:
        """结束追踪"""
        if name not in self._active_spans:
            return 0

        duration = time.time() - self._active_spans[name]
        self._traces[name].append(duration)
        del self._active_spans[name]

        return duration

    def trace(self, name: str):
        """追踪装饰器"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                self.start_span(name)
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    self.end_span(name)
            return wrapper
        return decorator

    def get_stats(self) -> Dict[str, Dict]:
        """获取统计"""
        stats = {}
        for name, durations in self._traces.items():
            if durations:
                stats[name] = {
                    "count": len(durations),
                    "total": sum(durations),
                    "avg": sum(durations) / len(durations),
                    "min": min(durations),
                    "max": max(durations),
                    "p50": sorted(durations)[len(durations) // 2],
                    "p95": sorted(durations)[int(len(durations) * 0.95)] if len(durations) >= 20 else max(durations),
                    "p99": sorted(durations)[int(len(durations) * 0.99)] if len(durations) >= 100 else max(durations),
                }
        return stats

    def get_report(self) -> str:
        """获取报告"""
        stats = self.get_stats()

        lines = ["=" * 60, "性能分析报告", "=" * 60, ""]

        for name, data in sorted(stats.items(), key=lambda x: x[1]["total"], reverse=True):
            lines.append(f"函数: {name}")
            lines.append(f"  调用次数: {data['count']}")
            lines.append(f"  总耗时: {data['total']:.3f}s")
            lines.append(f"  平均耗时: {data['avg']*1000:.2f}ms")
            lines.append(f"  P95: {data['p95']*1000:.2f}ms")
            lines.append(f"  P99: {data['p99']*1000:.2f}ms")
            lines.append("")

        return "\n".join(lines)


# ============ 全局实例 ============

_profiler = PerformanceProfiler()
_query_optimizer = QueryOptimizer()
_query_cache = QueryCache()


# ============ 便捷函数 ============

def profile(name: str):
    """性能追踪装饰器"""
    return _profiler.trace(name)


def cached_query(ttl: int = 300):
    """查询缓存装饰器"""
    cache = QueryCache(ttl)
    return cache.cached()


def optimize_indexes(conn, db_type: str = "postgresql") -> int:
    """优化索引"""
    manager = IndexManager(db_type)
    return manager.create_all_indexes(conn)


def analyze_slow_queries(limit: int = 10) -> List[Dict]:
    """分析慢查询"""
    return _query_optimizer.get_slow_queries(limit)


def get_performance_report() -> str:
    """获取性能报告"""
    return _profiler.get_report()


# ============ 预编译查询 ============

class PreparedStatement:
    """预编译语句"""

    def __init__(self, conn, query: str, name: str = None):
        self.conn = conn
        self.query = query
        self.name = name or f"stmt_{hash(query) % 10000}"
        self._prepared = False

    def prepare(self):
        """预编译"""
        try:
            if hasattr(self.conn, 'prepare'):
                self.conn.prepare(self.name, self.query)
            self._prepared = True
            logger.debug(f"[PreparedStatement] 预编译成功: {self.name}")
        except Exception as e:
            logger.warning(f"[PreparedStatement] 预编译失败: {e}")

    def execute(self, *args) -> Any:
        """执行"""
        if not self._prepared:
            self.prepare()

        if self._prepared and hasattr(self.conn, 'execute_prepared'):
            return self.conn.execute_prepared(self.name, args)
        else:
            return self.conn.execute(self.query, args)


# ============ SQL优化建议 ============

def get_sql_optimization_tips() -> Dict[str, List[str]]:
    """获取SQL优化建议"""
    return {
        "索引优化": [
            "为经常用于WHERE、JOIN、ORDER BY的列创建索引",
            "使用复合索引时，将选择性高的列放在前面",
            "避免在索引列上使用函数或计算",
            "定期使用ANALYZE更新统计信息",
            "考虑使用部分索引减少索引大小",
        ],
        "查询优化": [
            "避免SELECT *，只查询需要的列",
            "使用EXPLAIN分析查询计划",
            "合理使用LIMIT减少返回数据量",
            "使用JOIN代替子查询",
            "避免在WHERE子句中使用OR",
        ],
        "批量操作": [
            "使用批量插入代替单条插入",
            "大批量操作考虑分批处理",
            "使用COPY命令导入大量数据",
            "批量操作前禁用索引，完成后重建",
        ],
        "连接池优化": [
            "根据并发量设置合适的连接池大小",
            "设置连接超时和空闲超时",
            "使用连接池监控及时发现连接泄漏",
            "考虑使用PgBouncer等连接池中间件",
        ],
    }
