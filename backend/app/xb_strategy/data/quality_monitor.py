"""西部量化可转债策略 V3.0 数据质量监控模块

功能:
- 数据完整性检查
- 异常值检测
- 数据延迟监控
- 自动修复机制
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import math
import threading
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class QualityDimension(str, Enum):
    """质量维度"""
    COMPLETENESS = "completeness"     # 完整性
    ACCURACY = "accuracy"             # 准确性
    TIMELINESS = "timeliness"         # 及时性
    CONSISTENCY = "consistency"       # 一致性
    VALIDITY = "validity"             # 有效性


class QualityStatus(str, Enum):
    """质量状态"""
    GOOD = "good"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AnomalyType(str, Enum):
    """异常类型"""
    MISSING = "missing"               # 缺失
    OUTLIER = "outlier"               # 离群值
    STALE = "stale"                   # 过时
    FORMAT_ERROR = "format_error"     # 格式错误
    LOGICAL_ERROR = "logical_error"   # 逻辑错误
    DUPLICATE = "duplicate"           # 重复


class RepairAction(str, Enum):
    """修复动作"""
    DROP = "drop"                     # 删除
    FILL_FORWARD = "fill_forward"     # 前向填充
    FILL_BACKWARD = "fill_backward"   # 后向填充
    INTERPOLATE = "interpolate"       # 插值
    REPLACE_MEAN = "replace_mean"     # 均值替换
    REPLACE_MEDIAN = "replace_median" # 中位数替换
    FLAG = "flag"                     # 标记


# ============ 数据模型 ============

@dataclass
class QualityMetric:
    """质量指标"""
    dimension: QualityDimension
    score: float  # 0-100
    status: QualityStatus
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension.value,
            "score": round(self.score, 2),
            "status": self.status.value,
            "details": self.details,
        }


@dataclass
class DataAnomaly:
    """数据异常"""
    anomaly_id: str
    data_source: str
    field_name: str
    anomaly_type: AnomalyType
    severity: str  # low, medium, high
    description: str
    detected_at: datetime
    affected_records: int
    sample_values: List[Any] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "anomaly_id": self.anomaly_id,
            "data_source": self.data_source,
            "field_name": self.field_name,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity,
            "description": self.description,
            "detected_at": self.detected_at.isoformat(),
            "affected_records": self.affected_records,
        }


@dataclass
class QualityReport:
    """质量报告"""
    report_id: str
    data_source: str
    timestamp: datetime
    overall_score: float
    metrics: List[QualityMetric]
    anomalies: List[DataAnomaly]
    status: QualityStatus
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "data_source": self.data_source,
            "timestamp": self.timestamp.isoformat(),
            "overall_score": round(self.overall_score, 2),
            "metrics": [m.to_dict() for m in self.metrics],
            "anomaly_count": len(self.anomalies),
            "status": self.status.value,
            "recommendations": self.recommendations,
        }


@dataclass
class LatencyMetric:
    """延迟指标"""
    source: str
    expected_time: datetime
    actual_time: datetime
    latency_seconds: float
    is_delayed: bool

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "latency_seconds": round(self.latency_seconds, 2),
            "is_delayed": self.is_delayed,
            "expected_time": self.expected_time.isoformat(),
            "actual_time": self.actual_time.isoformat(),
        }


# ============ 数据完整性检查器 ============

class CompletenessChecker:
    """数据完整性检查器"""

    def __init__(self):
        self._expected_fields: Dict[str, List[str]] = {}
        self._expected_records: Dict[str, int] = {}

    def set_expectations(self, source: str, fields: List[str], expected_records: int = None):
        """设置期望"""
        self._expected_fields[source] = fields
        if expected_records:
            self._expected_records[source] = expected_records

    def check(
        self,
        source: str,
        records: List[Dict],
    ) -> QualityMetric:
        """检查完整性"""
        expected_fields = self._expected_fields.get(source, [])
        expected_count = self._expected_records.get(source, len(records))

        if not records:
            return QualityMetric(
                dimension=QualityDimension.COMPLETENESS,
                score=0,
                status=QualityStatus.CRITICAL,
                details={"error": "no_records"},
            )

        # 字段完整性
        field_scores = []
        missing_fields = []

        for field in expected_fields:
            present_count = sum(1 for r in records if field in r and r[field] is not None)
            field_score = present_count / len(records) * 100 if records else 0
            field_scores.append(field_score)

            if field_score < 100:
                missing_fields.append(field)

        # 记录数量完整性
        count_score = min(100, len(records) / expected_count * 100) if expected_count > 0 else 100

        # 综合评分
        overall_score = (sum(field_scores) / len(field_scores) * 0.7 + count_score * 0.3) if field_scores else count_score

        # 确定状态
        if overall_score >= 95:
            status = QualityStatus.GOOD
        elif overall_score >= 80:
            status = QualityStatus.WARNING
        elif overall_score >= 50:
            status = QualityStatus.ERROR
        else:
            status = QualityStatus.CRITICAL

        return QualityMetric(
            dimension=QualityDimension.COMPLETENESS,
            score=overall_score,
            status=status,
            details={
                "field_completeness": dict(zip(expected_fields, field_scores)),
                "missing_fields": missing_fields,
                "record_count": len(records),
                "expected_count": expected_count,
            },
        )


# ============ 异常值检测器 ============

class AnomalyDetector:
    """异常值检测器"""

    def __init__(self):
        self._rules: Dict[str, Dict] = {}
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

    def add_rule(
        self,
        field: str,
        min_value: float = None,
        max_value: float = None,
        std_threshold: float = 3.0,
        iqr_threshold: float = 1.5,
    ):
        """添加规则"""
        self._rules[field] = {
            "min_value": min_value,
            "max_value": max_value,
            "std_threshold": std_threshold,
            "iqr_threshold": iqr_threshold,
        }

    def detect(
        self,
        source: str,
        records: List[Dict],
    ) -> List[DataAnomaly]:
        """检测异常"""
        anomalies = []

        for field, rule in self._rules.items():
            values = [r.get(field) for r in records if r.get(field) is not None]

            if not values:
                continue

            # 数值检查
            if all(isinstance(v, (int, float)) for v in values):
                # 范围检查
                if rule.get("min_value") is not None:
                    outliers = [v for v in values if v < rule["min_value"]]
                    if outliers:
                        anomalies.append(self._create_anomaly(
                            source, field, AnomalyType.OUTLIER,
                            f"值低于最小值 {rule['min_value']}",
                            len(outliers), outliers[:5]
                        ))

                if rule.get("max_value") is not None:
                    outliers = [v for v in values if v > rule["max_value"]]
                    if outliers:
                        anomalies.append(self._create_anomaly(
                            source, field, AnomalyType.OUTLIER,
                            f"值高于最大值 {rule['max_value']}",
                            len(outliers), outliers[:5]
                        ))

                # 统计检查
                mean = sum(values) / len(values)
                std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))

                if std > 0:
                    std_outliers = [
                        v for v in values
                        if abs(v - mean) > rule["std_threshold"] * std
                    ]
                    if std_outliers:
                        anomalies.append(self._create_anomaly(
                            source, field, AnomalyType.OUTLIER,
                            f"超过{rule['std_threshold']}倍标准差",
                            len(std_outliers), std_outliers[:5]
                        ))

                # IQR检查
                sorted_values = sorted(values)
                n = len(sorted_values)
                q1 = sorted_values[n // 4]
                q3 = sorted_values[3 * n // 4]
                iqr = q3 - q1

                if iqr > 0:
                    lower = q1 - rule["iqr_threshold"] * iqr
                    upper = q3 + rule["iqr_threshold"] * iqr
                    iqr_outliers = [v for v in values if v < lower or v > upper]
                    if iqr_outliers:
                        anomalies.append(self._create_anomaly(
                            source, field, AnomalyType.OUTLIER,
                            f"IQR离群值",
                            len(iqr_outliers), iqr_outliers[:5]
                        ))

        return anomalies

    def _create_anomaly(
        self,
        source: str,
        field: str,
        anomaly_type: AnomalyType,
        description: str,
        count: int,
        samples: List,
    ) -> DataAnomaly:
        """创建异常记录"""
        return DataAnomaly(
            anomaly_id=f"anomaly_{int(datetime.now().timestamp() * 1000)}",
            data_source=source,
            field_name=field,
            anomaly_type=anomaly_type,
            severity="high" if count > 100 else "medium" if count > 10 else "low",
            description=description,
            detected_at=datetime.now(),
            affected_records=count,
            sample_values=samples,
        )


# ============ 数据延迟监控器 ============

class LatencyMonitor:
    """数据延迟监控器"""

    def __init__(self):
        self._expected_arrivals: Dict[str, Dict] = {}
        self._actual_arrivals: Dict[str, datetime] = {}
        self._latency_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._thresholds: Dict[str, float] = {}  # 秒

    def set_expected_arrival(
        self,
        source: str,
        schedule: str,  # cron-like
        threshold_seconds: float = 60,
    ):
        """设置期望到达时间"""
        self._expected_arrivals[source] = {
            "schedule": schedule,
            "threshold": threshold_seconds,
        }
        self._thresholds[source] = threshold_seconds

    def record_arrival(self, source: str, actual_time: datetime = None):
        """记录到达时间"""
        actual_time = actual_time or datetime.now()
        self._actual_arrivals[source] = actual_time

    def check_latency(self, source: str) -> Optional[LatencyMetric]:
        """检查延迟"""
        if source not in self._expected_arrivals:
            return None

        if source not in self._actual_arrivals:
            return LatencyMetric(
                source=source,
                expected_time=datetime.now(),
                actual_time=datetime.now(),
                latency_seconds=float('inf'),
                is_delayed=True,
            )

        expected = self._expected_arrivals[source]
        actual = self._actual_arrivals[source]

        # 简化: 计算与当前时间的差
        latency = (datetime.now() - actual).total_seconds()

        threshold = self._thresholds.get(source, 60)
        is_delayed = latency > threshold

        self._latency_history[source].append(latency)

        return LatencyMetric(
            source=source,
            expected_time=datetime.now() - timedelta(seconds=latency),
            actual_time=actual,
            latency_seconds=latency,
            is_delayed=is_delayed,
        )

    def get_latency_stats(self, source: str) -> Dict:
        """获取延迟统计"""
        history = list(self._latency_history.get(source, []))

        if not history:
            return {}

        return {
            "avg_latency": sum(history) / len(history),
            "max_latency": max(history),
            "p99_latency": sorted(history)[int(len(history) * 0.99)] if len(history) >= 10 else max(history),
            "delay_rate": sum(1 for h in history if h > self._thresholds.get(source, 60)) / len(history),
        }


# ============ 自动修复器 ============

class AutoRepairer:
    """自动修复器"""

    def __init__(self):
        self._repair_rules: Dict[str, Dict] = {}
        self._repair_history: Dict[str, List[Dict]] = defaultdict(list)

    def add_repair_rule(
        self,
        field: str,
        anomaly_type: AnomalyType,
        action: RepairAction,
        parameters: Dict = None,
    ):
        """添加修复规则"""
        key = f"{field}_{anomaly_type.value}"
        self._repair_rules[key] = {
            "action": action,
            "parameters": parameters or {},
        }

    def repair(
        self,
        records: List[Dict],
        anomalies: List[DataAnomaly],
    ) -> Tuple[List[Dict], List[Dict]]:
        """修复数据"""
        repaired_records = records.copy()
        repair_log = []

        for anomaly in anomalies:
            key = f"{anomaly.field_name}_{anomaly.anomaly_type.value}"
            rule = self._repair_rules.get(key)

            if not rule:
                continue

            action = rule["action"]
            params = rule["parameters"]

            for i, record in enumerate(repaired_records):
                if anomaly.field_name not in record:
                    continue

                original_value = record.get(anomaly.field_name)
                repaired_value = self._apply_repair(
                    original_value, action, params, repaired_records, i, anomaly.field_name
                )

                if repaired_value != original_value:
                    repaired_records[i][anomaly.field_name] = repaired_value
                    repair_log.append({
                        "record_index": i,
                        "field": anomaly.field_name,
                        "original": original_value,
                        "repaired": repaired_value,
                        "action": action.value,
                    })

        return repaired_records, repair_log

    def _apply_repair(
        self,
        value: Any,
        action: RepairAction,
        params: Dict,
        records: List[Dict],
        index: int,
        field: str,
    ) -> Any:
        """应用修复"""
        if action == RepairAction.DROP:
            return None

        elif action == RepairAction.FILL_FORWARD:
            for i in range(index - 1, -1, -1):
                if field in records[i] and records[i][field] is not None:
                    return records[i][field]
            return value

        elif action == RepairAction.FILL_BACKWARD:
            for i in range(index + 1, len(records)):
                if field in records[i] and records[i][field] is not None:
                    return records[i][field]
            return value

        elif action == RepairAction.INTERPOLATE:
            prev_val = None
            next_val = None

            for i in range(index - 1, -1, -1):
                if field in records[i] and records[i][field] is not None:
                    prev_val = records[i][field]
                    break

            for i in range(index + 1, len(records)):
                if field in records[i] and records[i][field] is not None:
                    next_val = records[i][field]
                    break

            if prev_val is not None and next_val is not None:
                return (prev_val + next_val) / 2
            return value

        elif action == RepairAction.REPLACE_MEAN:
            values = [r.get(field) for r in records if r.get(field) is not None]
            return sum(values) / len(values) if values else value

        elif action == RepairAction.REPLACE_MEDIAN:
            values = sorted([r.get(field) for r in records if r.get(field) is not None])
            if values:
                return values[len(values) // 2]
            return value

        elif action == RepairAction.FLAG:
            # 添加标记但不修改
            return value

        return value


# ============ 数据质量监控服务 ============

class DataQualityMonitor:
    """数据质量监控服务"""

    def __init__(self):
        self.completeness_checker = CompletenessChecker()
        self.anomaly_detector = AnomalyDetector()
        self.latency_monitor = LatencyMonitor()
        self.auto_repairer = AutoRepairer()

        self._quality_handlers: List[Callable] = []
        self._lock = threading.Lock()

    def check_quality(
        self,
        source: str,
        records: List[Dict],
        auto_repair: bool = False,
    ) -> QualityReport:
        """检查数据质量"""
        report_id = f"quality_{int(datetime.now().timestamp() * 1000)}"

        # 完整性检查
        completeness_metric = self.completeness_checker.check(source, records)

        # 异常检测
        anomalies = self.anomaly_detector.detect(source, records)

        # 延迟检查
        latency_metric = self.latency_monitor.check_latency(source)

        # 构建指标列表
        metrics = [completeness_metric]

        if latency_metric:
            metrics.append(QualityMetric(
                dimension=QualityDimension.TIMELINESS,
                score=100 if not latency_metric.is_delayed else max(0, 100 - latency_metric.latency_seconds),
                status=QualityStatus.GOOD if not latency_metric.is_delayed else QualityStatus.WARNING,
                details=latency_metric.to_dict(),
            ))

        # 计算总体评分
        overall_score = sum(m.score for m in metrics) / len(metrics) if metrics else 0

        # 确定状态
        if overall_score >= 90:
            status = QualityStatus.GOOD
        elif overall_score >= 70:
            status = QualityStatus.WARNING
        elif overall_score >= 50:
            status = QualityStatus.ERROR
        else:
            status = QualityStatus.CRITICAL

        # 自动修复
        if auto_repair and anomalies:
            records, repair_log = self.auto_repairer.repair(records, anomalies)
            logger.info(f"[DataQualityMonitor] 自动修复 {len(repair_log)} 条记录")

        # 生成建议
        recommendations = self._generate_recommendations(metrics, anomalies)

        report = QualityReport(
            report_id=report_id,
            data_source=source,
            timestamp=datetime.now(),
            overall_score=overall_score,
            metrics=metrics,
            anomalies=anomalies,
            status=status,
            recommendations=recommendations,
        )

        # 触发处理器
        for handler in self._quality_handlers:
            try:
                handler(report)
            except Exception as e:
                logger.error(f"[DataQualityMonitor] 处理器执行失败: {e}")

        return report

    def _generate_recommendations(
        self,
        metrics: List[QualityMetric],
        anomalies: List[DataAnomaly],
    ) -> List[str]:
        """生成建议"""
        recommendations = []

        for metric in metrics:
            if metric.score < 80:
                if metric.dimension == QualityDimension.COMPLETENESS:
                    recommendations.append("检查数据源连接状态, 确认数据采集正常")
                elif metric.dimension == QualityDimension.TIMELINESS:
                    recommendations.append("优化数据处理流程, 减少延迟")

        if len(anomalies) > 10:
            recommendations.append("异常值较多, 建议检查数据源质量")

        high_severity = [a for a in anomalies if a.severity == "high"]
        if high_severity:
            recommendations.append(f"发现{len(high_severity)}个高严重度异常, 需要立即处理")

        return recommendations

    def register_handler(self, handler: Callable):
        """注册处理器"""
        self._quality_handlers.append(handler)

    def get_quality_dashboard(self) -> Dict:
        """获取质量仪表盘"""
        # 汇总统计
        return {
            "sources_monitored": len(self.latency_monitor._expected_arrivals),
            "rules_configured": len(self.anomaly_detector._rules),
            "repair_rules": len(self.auto_repairer._repair_rules),
        }


# ============ 便捷函数 ============

def create_quality_monitor() -> DataQualityMonitor:
    """创建质量监控器"""
    return DataQualityMonitor()


def check_data_quality(
    source: str,
    records: List[Dict],
) -> QualityReport:
    """检查数据质量"""
    monitor = DataQualityMonitor()
    return monitor.check_quality(source, records)


def detect_anomalies(
    records: List[Dict],
    field: str,
    threshold: float = 3.0,
) -> List[Any]:
    """检测异常值"""
    values = [r.get(field) for r in records if r.get(field) is not None]

    if not values:
        return []

    mean = sum(values) / len(values)
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))

    if std == 0:
        return []

    return [v for v in values if abs(v - mean) > threshold * std]
