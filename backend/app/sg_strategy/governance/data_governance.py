"""松岗量化可转债策略 V3.0 数据治理模块

功能:
- 数据血缘追踪
- 数据质量监控
- 异常检测
- 数据溯源
- 数据生命周期管理
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Set, Tuple
from enum import Enum
import logging
import json
import hashlib
import threading
from collections import defaultdict
import numpy as np

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class DataQualityLevel(str, Enum):
    """数据质量等级"""
    EXCELLENT = "excellent"  # > 95%
    GOOD = "good"           # 80-95%
    FAIR = "fair"           # 60-80%
    POOR = "poor"           # < 60%


class DataSource(str, Enum):
    """数据来源"""
    AKSHARE = "akshare"
    WIND = "wind"
    TUSHARE = "tushare"
    JOINQUANT = "joinquant"
    RICEQUANT = "ricequant"
    MANUAL = "manual"
    DERIVED = "derived"


class AnomalyType(str, Enum):
    """异常类型"""
    MISSING = "missing"
    OUTLIER = "outlier"
    DUPLICATE = "duplicate"
    INCONSISTENT = "inconsistent"
    STALE = "stale"
    FORMAT_ERROR = "format_error"


# ============ 数据模型 ============

@dataclass
class DataLineage:
    """数据血缘"""
    data_id: str
    source: DataSource
    source_table: str
    source_fields: List[str]
    transformations: List[Dict]
    target_table: str
    target_fields: List[str]
    created_at: datetime
    created_by: str = "system"

    def to_dict(self) -> dict:
        return {
            "data_id": self.data_id,
            "source": self.source.value,
            "source_table": self.source_table,
            "source_fields": self.source_fields,
            "transformations": self.transformations,
            "target_table": self.target_table,
            "target_fields": self.target_fields,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass
class QualityMetric:
    """质量指标"""
    name: str
    value: float
    threshold: float
    passed: bool
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "threshold": self.threshold,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass
class QualityReport:
    """质量报告"""
    table_name: str
    check_time: datetime
    total_records: int
    valid_records: int
    quality_score: float
    quality_level: DataQualityLevel
    metrics: List[QualityMetric]
    anomalies: List[Dict]

    def to_dict(self) -> dict:
        return {
            "table_name": self.table_name,
            "check_time": self.check_time.isoformat(),
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "quality_score": round(self.quality_score, 2),
            "quality_level": self.quality_level.value,
            "metrics": [m.to_dict() for m in self.metrics],
            "anomalies": self.anomalies,
        }


@dataclass
class AnomalyRecord:
    """异常记录"""
    anomaly_id: str
    anomaly_type: AnomalyType
    table_name: str
    field_name: str
    record_id: str
    expected_value: Any
    actual_value: Any
    severity: str  # low, medium, high
    detected_at: datetime
    resolved: bool = False
    resolved_at: datetime = None

    def to_dict(self) -> dict:
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type.value,
            "table_name": self.table_name,
            "field_name": self.field_name,
            "record_id": self.record_id,
            "expected_value": str(self.expected_value),
            "actual_value": str(self.actual_value),
            "severity": self.severity,
            "detected_at": self.detected_at.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


# ============ 数据血缘追踪 ============

class LineageTracker:
    """数据血缘追踪器"""

    def __init__(self):
        self._lineages: Dict[str, DataLineage] = {}
        self._dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self._lock = threading.Lock()

    def register_lineage(
        self,
        source: DataSource,
        source_table: str,
        source_fields: List[str],
        target_table: str,
        target_fields: List[str],
        transformations: List[Dict] = None,
        created_by: str = "system",
    ) -> str:
        """注册数据血缘"""
        data_id = self._generate_id(source_table, target_table)

        lineage = DataLineage(
            data_id=data_id,
            source=source,
            source_table=source_table,
            source_fields=source_fields,
            transformations=transformations or [],
            target_table=target_table,
            target_fields=target_fields,
            created_at=datetime.now(),
            created_by=created_by,
        )

        with self._lock:
            self._lineages[data_id] = lineage
            self._dependency_graph[target_table].add(source_table)

        logger.info(f"[LineageTracker] 注册血缘: {source_table} -> {target_table}")

        return data_id

    def get_lineage(self, data_id: str) -> Optional[DataLineage]:
        """获取数据血缘"""
        return self._lineages.get(data_id)

    def get_upstream(self, table_name: str, depth: int = 10) -> List[str]:
        """获取上游数据源"""
        visited = set()
        result = []

        def dfs(table: str, level: int):
            if level > depth or table in visited:
                return
            visited.add(table)

            for source in self._dependency_graph.get(table, []):
                result.append(source)
                dfs(source, level + 1)

        dfs(table_name, 0)
        return result

    def get_downstream(self, table_name: str, depth: int = 10) -> List[str]:
        """获取下游数据"""
        visited = set()
        result = []

        def dfs(table: str, level: int):
            if level > depth or table in visited:
                return
            visited.add(table)

            for target, sources in self._dependency_graph.items():
                if table in sources:
                    result.append(target)
                    dfs(target, level + 1)

        dfs(table_name, 0)
        return result

    def get_lineage_graph(self) -> Dict[str, Any]:
        """获取血缘图谱"""
        nodes = set()
        edges = []

        for target, sources in self._dependency_graph.items():
            nodes.add(target)
            for source in sources:
                nodes.add(source)
                edges.append({"source": source, "target": target})

        return {
            "nodes": [{"id": n, "name": n} for n in nodes],
            "edges": edges,
        }

    def _generate_id(self, source: str, target: str) -> str:
        """生成ID"""
        return hashlib.md5(f"{source}_{target}_{datetime.now().isoformat()}".encode()).hexdigest()[:16]


# ============ 数据质量监控 ============

class QualityMonitor:
    """数据质量监控器"""

    # 质量检查规则
    QUALITY_RULES = {
        "completeness": {
            "description": "完整性检查",
            "threshold": 0.95,
        },
        "accuracy": {
            "description": "准确性检查",
            "threshold": 0.90,
        },
        "consistency": {
            "description": "一致性检查",
            "threshold": 0.95,
        },
        "timeliness": {
            "description": "时效性检查",
            "threshold": 0.80,
        },
        "uniqueness": {
            "description": "唯一性检查",
            "threshold": 0.99,
        },
        "validity": {
            "description": "有效性检查",
            "threshold": 0.95,
        },
    }

    def __init__(self):
        self._reports: Dict[str, List[QualityReport]] = defaultdict(list)
        self._lock = threading.Lock()

    def check_quality(
        self,
        table_name: str,
        data: List[Dict],
        rules: Dict[str, float] = None,
    ) -> QualityReport:
        """检查数据质量"""
        rules = rules or {k: v["threshold"] for k, v in self.QUALITY_RULES.items()}

        metrics = []
        total_records = len(data)

        if total_records == 0:
            return QualityReport(
                table_name=table_name,
                check_time=datetime.now(),
                total_records=0,
                valid_records=0,
                quality_score=0,
                quality_level=DataQualityLevel.POOR,
                metrics=[],
                anomalies=[],
            )

        # 完整性检查
        completeness = self._check_completeness(data)
        metrics.append(QualityMetric(
            name="completeness",
            value=completeness,
            threshold=rules.get("completeness", 0.95),
            passed=completeness >= rules.get("completeness", 0.95),
        ))

        # 唯一性检查
        uniqueness = self._check_uniqueness(data)
        metrics.append(QualityMetric(
            name="uniqueness",
            value=uniqueness,
            threshold=rules.get("uniqueness", 0.99),
            passed=uniqueness >= rules.get("uniqueness", 0.99),
        ))

        # 有效性检查
        validity = self._check_validity(data)
        metrics.append(QualityMetric(
            name="validity",
            value=validity,
            threshold=rules.get("validity", 0.95),
            passed=validity >= rules.get("validity", 0.95),
        ))

        # 异常检测
        anomalies = self._detect_anomalies(data)

        # 计算总分
        passed_count = sum(1 for m in metrics if m.passed)
        quality_score = passed_count / len(metrics) * 100 if metrics else 0

        # 确定等级
        if quality_score >= 95:
            level = DataQualityLevel.EXCELLENT
        elif quality_score >= 80:
            level = DataQualityLevel.GOOD
        elif quality_score >= 60:
            level = DataQualityLevel.FAIR
        else:
            level = DataQualityLevel.POOR

        # 有效记录数
        valid_records = int(total_records * completeness)

        report = QualityReport(
            table_name=table_name,
            check_time=datetime.now(),
            total_records=total_records,
            valid_records=valid_records,
            quality_score=quality_score,
            quality_level=level,
            metrics=metrics,
            anomalies=anomalies,
        )

        with self._lock:
            self._reports[table_name].append(report)
            # 保留最近100份报告
            if len(self._reports[table_name]) > 100:
                self._reports[table_name] = self._reports[table_name][-100:]

        return report

    def _check_completeness(self, data: List[Dict]) -> float:
        """检查完整性"""
        if not data:
            return 0.0

        total_fields = sum(len(record) for record in data)
        filled_fields = sum(
            sum(1 for v in record.values() if v is not None and v != "")
            for record in data
        )

        return filled_fields / total_fields if total_fields > 0 else 0

    def _check_uniqueness(self, data: List[Dict]) -> float:
        """检查唯一性"""
        if not data:
            return 1.0

        # 基于主键或所有字段
        seen = set()
        duplicates = 0

        for record in data:
            # 使用记录的字符串表示作为键
            key = json.dumps(record, sort_keys=True, default=str)
            if key in seen:
                duplicates += 1
            seen.add(key)

        return 1 - (duplicates / len(data)) if data else 1

    def _check_validity(self, data: List[Dict]) -> float:
        """检查有效性"""
        if not data:
            return 0.0

        valid_count = 0

        for record in data:
            is_valid = True

            # 检查数值范围
            for key, value in record.items():
                if isinstance(value, (int, float)):
                    # 价格类数据应为正数
                    if 'price' in key.lower() or 'close' in key.lower():
                        if value <= 0:
                            is_valid = False
                            break

                # 检查日期格式
                if isinstance(value, str) and 'date' in key.lower():
                    try:
                        datetime.fromisoformat(value.replace('Z', '+00:00'))
                    except Exception:
                        is_valid = False
                        break

            if is_valid:
                valid_count += 1

        return valid_count / len(data)

    def _detect_anomalies(self, data: List[Dict]) -> List[Dict]:
        """检测异常"""
        anomalies = []

        if not data:
            return anomalies

        # 数值字段的异常检测
        numeric_fields = {}
        for record in data:
            for key, value in record.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if key not in numeric_fields:
                        numeric_fields[key] = []
                    numeric_fields[key].append(value)

        # 使用IQR方法检测离群值
        for field, values in numeric_fields.items():
            if len(values) < 4:
                continue

            values_arr = np.array(values)
            q1 = np.percentile(values_arr, 25)
            q3 = np.percentile(values_arr, 75)
            iqr = q3 - q1

            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            for i, v in enumerate(values):
                if v < lower_bound or v > upper_bound:
                    anomalies.append({
                        "type": AnomalyType.OUTLIER.value,
                        "field": field,
                        "record_index": i,
                        "value": v,
                        "bounds": [lower_bound, upper_bound],
                        "severity": "medium",
                    })

        return anomalies[:100]  # 限制返回数量

    def get_report(self, table_name: str) -> Optional[QualityReport]:
        """获取最新报告"""
        reports = self._reports.get(table_name, [])
        return reports[-1] if reports else None

    def get_history(self, table_name: str, limit: int = 10) -> List[QualityReport]:
        """获取历史报告"""
        return self._reports.get(table_name, [])[-limit:]


# ============ 数据异常检测 ============

class AnomalyDetector:
    """数据异常检测器"""

    def __init__(self):
        self._anomalies: Dict[str, List[AnomalyRecord]] = defaultdict(list)
        self._lock = threading.Lock()

    def detect_missing(
        self,
        data: List[Dict],
        required_fields: List[str],
        table_name: str,
    ) -> List[AnomalyRecord]:
        """检测缺失值"""
        anomalies = []

        for i, record in enumerate(data):
            for field in required_fields:
                if field not in record or record[field] is None:
                    anomaly = AnomalyRecord(
                        anomaly_id=f"missing_{table_name}_{i}_{field}",
                        anomaly_type=AnomalyType.MISSING,
                        table_name=table_name,
                        field_name=field,
                        record_id=str(i),
                        expected_value="非空值",
                        actual_value=None,
                        severity="high",
                        detected_at=datetime.now(),
                    )
                    anomalies.append(anomaly)

        self._save_anomalies(anomalies)
        return anomalies

    def detect_outliers(
        self,
        data: List[Dict],
        field: str,
        method: str = "iqr",
        threshold: float = 1.5,
        table_name: str = "",
    ) -> List[AnomalyRecord]:
        """检测离群值"""
        anomalies = []

        values = [r.get(field) for r in data if r.get(field) is not None]
        if not values:
            return anomalies

        values_arr = np.array(values)

        if method == "iqr":
            q1 = np.percentile(values_arr, 25)
            q3 = np.percentile(values_arr, 75)
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
        elif method == "zscore":
            mean = np.mean(values_arr)
            std = np.std(values_arr)
            lower = mean - threshold * std
            upper = mean + threshold * std
        else:
            return anomalies

        for i, record in enumerate(data):
            value = record.get(field)
            if value is None:
                continue

            if value < lower or value > upper:
                anomaly = AnomalyRecord(
                    anomaly_id=f"outlier_{table_name}_{i}_{field}",
                    anomaly_type=AnomalyType.OUTLIER,
                    table_name=table_name,
                    field_name=field,
                    record_id=str(i),
                    expected_value=f"[{lower:.2f}, {upper:.2f}]",
                    actual_value=value,
                    severity="medium",
                    detected_at=datetime.now(),
                )
                anomalies.append(anomaly)

        self._save_anomalies(anomalies)
        return anomalies

    def detect_duplicates(
        self,
        data: List[Dict],
        key_fields: List[str],
        table_name: str,
    ) -> List[AnomalyRecord]:
        """检测重复数据"""
        anomalies = []
        seen = {}

        for i, record in enumerate(data):
            key = tuple(record.get(f) for f in key_fields)

            if key in seen:
                anomaly = AnomalyRecord(
                    anomaly_id=f"duplicate_{table_name}_{i}",
                    anomaly_type=AnomalyType.DUPLICATE,
                    table_name=table_name,
                    field_name=",".join(key_fields),
                    record_id=str(i),
                    expected_value="唯一值",
                    actual_value=f"与记录{seen[key]}重复",
                    severity="medium",
                    detected_at=datetime.now(),
                )
                anomalies.append(anomaly)
            else:
                seen[key] = i

        self._save_anomalies(anomalies)
        return anomalies

    def detect_stale_data(
        self,
        data: List[Dict],
        date_field: str,
        max_age_days: int,
        table_name: str,
    ) -> List[AnomalyRecord]:
        """检测过期数据"""
        anomalies = []
        cutoff = datetime.now() - timedelta(days=max_age_days)

        for i, record in enumerate(data):
            date_value = record.get(date_field)

            if date_value:
                if isinstance(date_value, str):
                    try:
                        date_value = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                    except Exception:
                        continue

                if date_value < cutoff:
                    anomaly = AnomalyRecord(
                        anomaly_id=f"stale_{table_name}_{i}",
                        anomaly_type=AnomalyType.STALE,
                        table_name=table_name,
                        field_name=date_field,
                        record_id=str(i),
                        expected_value=f"晚于{cutoff.isoformat()}",
                        actual_value=date_value.isoformat(),
                        severity="low",
                        detected_at=datetime.now(),
                    )
                    anomalies.append(anomaly)

        self._save_anomalies(anomalies)
        return anomalies

    def _save_anomalies(self, anomalies: List[AnomalyRecord]):
        """保存异常"""
        with self._lock:
            for anomaly in anomalies:
                self._anomalies[anomaly.table_name].append(anomaly)
                # 保留最近1000条
                if len(self._anomalies[anomaly.table_name]) > 1000:
                    self._anomalies[anomaly.table_name] = self._anomalies[anomaly.table_name][-1000:]

    def get_anomalies(
        self,
        table_name: str = None,
        anomaly_type: AnomalyType = None,
        resolved: bool = None,
    ) -> List[AnomalyRecord]:
        """获取异常"""
        result = []

        if table_name:
            records = self._anomalies.get(table_name, [])
        else:
            records = []
            for r in self._anomalies.values():
                records.extend(r)

        for record in records:
            if anomaly_type and record.anomaly_type != anomaly_type:
                continue
            if resolved is not None and record.resolved != resolved:
                continue
            result.append(record)

        return result

    def resolve_anomaly(self, anomaly_id: str) -> bool:
        """解决异常"""
        for table_name, records in self._anomalies.items():
            for record in records:
                if record.anomaly_id == anomaly_id:
                    record.resolved = True
                    record.resolved_at = datetime.now()
                    return True
        return False


# ============ 数据生命周期管理 ============

class DataLifecycleManager:
    """数据生命周期管理"""

    # 数据保留策略
    RETENTION_POLICIES = {
        "cb_daily_data": 3650,      # 10年
        "stock_daily_data": 3650,   # 10年
        "trading_signals": 365,     # 1年
        "positions": 3650,          # 10年
        "trades": 3650,             # 10年
        "risk_records": 365,        # 1年
        "logs": 90,                 # 90天
        "metrics": 365,             # 1年
    }

    def __init__(self):
        self._policies = self.RETENTION_POLICIES.copy()
        self._archives: Dict[str, List[Dict]] = defaultdict(list)

    def set_retention_policy(self, table_name: str, days: int):
        """设置保留策略"""
        self._policies[table_name] = days
        logger.info(f"[DataLifecycle] 设置保留策略: {table_name} = {days}天")

    def get_retention_policy(self, table_name: str) -> int:
        """获取保留策略"""
        return self._policies.get(table_name, 365)  # 默认1年

    def get_expired_records(
        self,
        table_name: str,
        date_field: str,
        data: List[Dict],
    ) -> List[Dict]:
        """获取过期数据"""
        retention_days = self.get_retention_policy(table_name)
        cutoff = datetime.now() - timedelta(days=retention_days)

        expired = []
        for record in data:
            date_value = record.get(date_field)
            if date_value:
                if isinstance(date_value, str):
                    try:
                        date_value = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                    except Exception:
                        continue

                if date_value < cutoff:
                    expired.append(record)

        return expired

    def archive_data(
        self,
        table_name: str,
        records: List[Dict],
        archive_location: str = "default",
    ) -> int:
        """归档数据"""
        archive_entry = {
            "table_name": table_name,
            "record_count": len(records),
            "archive_time": datetime.now().isoformat(),
            "archive_location": archive_location,
            "checksum": hashlib.md5(json.dumps(records, default=str).encode()).hexdigest(),
        }

        self._archives[table_name].append(archive_entry)
        logger.info(f"[DataLifecycle] 归档数据: {table_name}, {len(records)}条记录")

        return len(records)

    def get_archive_history(self, table_name: str = None) -> List[Dict]:
        """获取归档历史"""
        if table_name:
            return self._archives.get(table_name, [])

        result = []
        for archives in self._archives.values():
            result.extend(archives)

        return sorted(result, key=lambda x: x["archive_time"], reverse=True)


# ============ 数据治理服务 ============

class DataGovernanceService:
    """数据治理服务"""

    def __init__(self):
        self.lineage_tracker = LineageTracker()
        self.quality_monitor = QualityMonitor()
        self.anomaly_detector = AnomalyDetector()
        self.lifecycle_manager = DataLifecycleManager()

    def register_data_flow(
        self,
        source: DataSource,
        source_table: str,
        source_fields: List[str],
        target_table: str,
        target_fields: List[str],
        transformations: List[Dict] = None,
    ) -> str:
        """注册数据流"""
        return self.lineage_tracker.register_lineage(
            source=source,
            source_table=source_table,
            source_fields=source_fields,
            target_table=target_table,
            target_fields=target_fields,
            transformations=transformations,
        )

    def validate_data(
        self,
        table_name: str,
        data: List[Dict],
        required_fields: List[str] = None,
    ) -> Dict[str, Any]:
        """验证数据"""
        result = {
            "valid": True,
            "quality_report": None,
            "anomalies": [],
        }

        # 质量检查
        quality_report = self.quality_monitor.check_quality(table_name, data)
        result["quality_report"] = quality_report.to_dict()

        if quality_report.quality_level == DataQualityLevel.POOR:
            result["valid"] = False

        # 缺失值检测
        if required_fields:
            missing = self.anomaly_detector.detect_missing(
                data, required_fields, table_name
            )
            result["anomalies"].extend([a.to_dict() for a in missing])

        return result

    def get_data_health(self) -> Dict[str, Any]:
        """获取数据健康度"""
        # 汇总所有表的质量报告
        health = {}

        for table_name, reports in self.quality_monitor._reports.items():
            if reports:
                latest = reports[-1]
                health[table_name] = {
                    "quality_score": latest.quality_score,
                    "quality_level": latest.quality_level.value,
                    "total_records": latest.total_records,
                    "anomaly_count": len(latest.anomalies),
                    "last_check": latest.check_time.isoformat(),
                }

        return health

    def get_governance_summary(self) -> Dict[str, Any]:
        """获取治理摘要"""
        return {
            "lineage_count": len(self.lineage_tracker._lineages),
            "tables_monitored": len(self.quality_monitor._reports),
            "total_anomalies": sum(
                len(anomalies) for anomalies in self.anomaly_detector._anomalies.values()
            ),
            "unresolved_anomalies": len(
                self.anomaly_detector.get_anomalies(resolved=False)
            ),
            "retention_policies": len(self.lifecycle_manager._policies),
            "archive_count": sum(
                len(archives) for archives in self.lifecycle_manager._archives.values()
            ),
        }


# ============ 便捷函数 ============

def track_lineage(
    source: DataSource,
    source_table: str,
    target_table: str,
    fields: List[str],
) -> str:
    """追踪数据血缘"""
    tracker = LineageTracker()
    return tracker.register_lineage(
        source=source,
        source_table=source_table,
        source_fields=fields,
        target_table=target_table,
        target_fields=fields,
    )


def check_data_quality(table_name: str, data: List[Dict]) -> QualityReport:
    """检查数据质量"""
    monitor = QualityMonitor()
    return monitor.check_quality(table_name, data)


def detect_anomalies(
    data: List[Dict],
    field: str,
    table_name: str = "",
) -> List[AnomalyRecord]:
    """检测异常"""
    detector = AnomalyDetector()
    return detector.detect_outliers(data, field, table_name=table_name)


# 需要导入timedelta
from datetime import timedelta
