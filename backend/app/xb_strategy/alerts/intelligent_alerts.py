"""西部量化可转债策略 V3.0 智能预警系统模块

功能:
- 异常检测算法
- 多维度预警规则
- 预警优先级排序
- 自动处理建议
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import math
import threading
from collections import deque, defaultdict
import json

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AlertType(str, Enum):
    """预警类型"""
    RISK = "risk"               # 风险预警
    PERFORMANCE = "performance" # 业绩预警
    POSITION = "position"       # 持仓预警
    MARKET = "market"           # 市场预警
    SYSTEM = "system"           # 系统预警
    SIGNAL = "signal"           # 信号预警
    EXECUTION = "execution"     # 执行预警
    DATA = "data"               # 数据预警


class AlertSeverity(str, Enum):
    """预警严重程度"""
    INFO = "info"               # 信息
    WARNING = "warning"         # 警告
    ERROR = "error"             # 错误
    CRITICAL = "critical"       # 严重


class AlertStatus(str, Enum):
    """预警状态"""
    ACTIVE = "active"           # 活跃
    ACKNOWLEDGED = "acknowledged"  # 已确认
    RESOLVED = "resolved"       # 已解决
    IGNORED = "ignored"         # 已忽略


class AnomalyType(str, Enum):
    """异常类型"""
    SPIKE = "spike"             # 突发异常
    TREND = "trend"             # 趋势异常
    OUTLIER = "outlier"         # 离群点
    PATTERN = "pattern"         # 模式异常
    THRESHOLD = "threshold"     # 阈值突破


# ============ 数据模型 ============

@dataclass
class AlertRule:
    """预警规则"""
    rule_id: str
    name: str
    alert_type: AlertType
    severity: AlertSeverity
    condition: str              # 条件表达式
    threshold: float
    comparison: str             # gt, lt, eq, etc.
    lookback_periods: int = 1
    cooldown_minutes: int = 60
    enabled: bool = True
    auto_resolve: bool = False
    auto_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "condition": self.condition,
            "threshold": self.threshold,
            "comparison": self.comparison,
            "enabled": self.enabled,
        }


@dataclass
class Alert:
    """预警"""
    alert_id: str
    rule_id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    current_value: float
    threshold: float
    timestamp: datetime
    status: AlertStatus = AlertStatus.ACTIVE
    acknowledged_by: str = None
    acknowledged_at: datetime = None
    resolved_at: datetime = None
    actions_taken: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "current_value": round(self.current_value, 4),
            "threshold": round(self.threshold, 4),
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "acknowledged_by": self.acknowledged_by,
            "actions_taken": self.actions_taken,
        }


@dataclass
class AnomalyDetection:
    """异常检测结果"""
    metric_name: str
    timestamp: datetime
    value: float
    expected_value: float
    deviation: float
    anomaly_type: AnomalyType
    confidence: float
    context: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "timestamp": self.timestamp.isoformat(),
            "value": round(self.value, 4),
            "expected_value": round(self.expected_value, 4),
            "deviation": round(self.deviation, 4),
            "anomaly_type": self.anomaly_type.value,
            "confidence": round(self.confidence, 4),
        }


# ============ 异常检测器 ============

class AnomalyDetector:
    """异常检测器"""

    def __init__(
        self,
        history_size: int = 1000,
        z_threshold: float = 3.0,
        iqr_multiplier: float = 1.5,
    ):
        self.history_size = history_size
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier

        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=history_size))
        self._lock = threading.Lock()

    def update(self, metric_name: str, value: float, timestamp: datetime = None):
        """更新指标"""
        timestamp = timestamp or datetime.now()

        with self._lock:
            self._history[metric_name].append({
                "value": value,
                "timestamp": timestamp,
            })

    def detect(self, metric_name: str, value: float) -> Optional[AnomalyDetection]:
        """检测异常"""
        history = list(self._history.get(metric_name, []))

        if len(history) < 10:
            return None

        values = [h["value"] for h in history]
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))

        if std == 0:
            return None

        # Z-score检测
        z_score = abs(value - mean) / std

        if z_score > self.z_threshold:
            return AnomalyDetection(
                metric_name=metric_name,
                timestamp=datetime.now(),
                value=value,
                expected_value=mean,
                deviation=z_score,
                anomaly_type=AnomalyType.OUTLIER,
                confidence=min(1.0, z_score / self.z_threshold),
                context={"z_score": z_score, "std": std},
            )

        # IQR检测
        sorted_values = sorted(values)
        n = len(sorted_values)
        q1 = sorted_values[n // 4]
        q3 = sorted_values[3 * n // 4]
        iqr = q3 - q1

        lower_bound = q1 - self.iqr_multiplier * iqr
        upper_bound = q3 + self.iqr_multiplier * iqr

        if value < lower_bound or value > upper_bound:
            return AnomalyDetection(
                metric_name=metric_name,
                timestamp=datetime.now(),
                value=value,
                expected_value=mean,
                deviation=abs(value - mean) / iqr if iqr > 0 else 0,
                anomaly_type=AnomalyType.SPIKE,
                confidence=min(1.0, abs(value - mean) / (iqr * 2) if iqr > 0 else 0),
                context={"iqr": iqr, "bounds": (lower_bound, upper_bound)},
            )

        # 趋势检测 (简化)
        recent = values[-10:]
        older = values[-20:-10] if len(values) >= 20 else values[:len(values)//2]

        recent_mean = sum(recent) / len(recent)
        older_mean = sum(older) / len(older)

        trend_change = abs(recent_mean - older_mean) / older_mean if older_mean != 0 else 0

        if trend_change > 0.1:  # 10%变化
            return AnomalyDetection(
                metric_name=metric_name,
                timestamp=datetime.now(),
                value=value,
                expected_value=older_mean,
                deviation=trend_change,
                anomaly_type=AnomalyType.TREND,
                confidence=min(1.0, trend_change * 5),
                context={"trend_change": trend_change},
            )

        return None

    def detect_batch(self, metrics: Dict[str, float]) -> List[AnomalyDetection]:
        """批量检测"""
        anomalies = []

        for name, value in metrics.items():
            anomaly = self.detect(name, value)
            if anomaly:
                anomalies.append(anomaly)

        return anomalies


# ============ 预警规则引擎 ============

class AlertRuleEngine:
    """预警规则引擎"""

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._last_triggered: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def add_rule(self, rule: AlertRule):
        """添加规则"""
        with self._lock:
            self._rules[rule.rule_id] = rule
            logger.info(f"[AlertRuleEngine] 添加规则: {rule.name}")

    def remove_rule(self, rule_id: str):
        """移除规则"""
        with self._lock:
            self._rules.pop(rule_id, None)

    def evaluate(
        self,
        rule_id: str,
        value: float,
        context: Dict = None,
    ) -> Optional[Alert]:
        """评估规则"""
        rule = self._rules.get(rule_id)
        if not rule or not rule.enabled:
            return None

        # 检查冷却期
        last_triggered = self._last_triggered.get(rule_id)
        if last_triggered:
            cooldown = timedelta(minutes=rule.cooldown_minutes)
            if datetime.now() - last_triggered < cooldown:
                return None

        # 评估条件
        triggered = False

        if rule.comparison == "gt":
            triggered = value > rule.threshold
        elif rule.comparison == "lt":
            triggered = value < rule.threshold
        elif rule.comparison == "eq":
            triggered = value == rule.threshold
        elif rule.comparison == "gte":
            triggered = value >= rule.threshold
        elif rule.comparison == "lte":
            triggered = value <= rule.threshold
        elif rule.comparison == "ne":
            triggered = value != rule.threshold

        if not triggered:
            return None

        # 创建预警
        alert_id = f"alert_{int(datetime.now().timestamp() * 1000)}"

        alert = Alert(
            alert_id=alert_id,
            rule_id=rule_id,
            alert_type=rule.alert_type,
            severity=rule.severity,
            title=f"[{rule.name}] 预警触发",
            message=f"当前值: {value:.4f}, 阈值: {rule.threshold:.4f}",
            current_value=value,
            threshold=rule.threshold,
            timestamp=datetime.now(),
        )

        self._last_triggered[rule_id] = datetime.now()

        return alert

    def evaluate_all(self, values: Dict[str, float]) -> List[Alert]:
        """评估所有规则"""
        alerts = []

        for rule_id, rule in self._rules.items():
            # 假设规则ID与指标名对应
            metric_name = rule.condition.split(".")[0] if "." in rule.condition else rule_id
            value = values.get(metric_name)

            if value is not None:
                alert = self.evaluate(rule_id, value)
                if alert:
                    alerts.append(alert)

        return alerts


# ============ 预警优先级管理器 ============

class AlertPriorityManager:
    """预警优先级管理器"""

    def __init__(self):
        # 权重配置
        self._severity_weights = {
            AlertSeverity.CRITICAL: 100,
            AlertSeverity.ERROR: 75,
            AlertSeverity.WARNING: 50,
            AlertSeverity.INFO: 25,
        }

        self._type_weights = {
            AlertType.RISK: 1.5,
            AlertType.POSITION: 1.3,
            AlertType.PERFORMANCE: 1.2,
            AlertType.MARKET: 1.1,
            AlertType.EXECUTION: 1.0,
            AlertType.SIGNAL: 0.9,
            AlertType.SYSTEM: 0.8,
            AlertType.DATA: 0.7,
        }

    def calculate_priority(self, alert: Alert) -> float:
        """计算优先级"""
        severity_score = self._severity_weights.get(alert.severity, 0)
        type_multiplier = self._type_weights.get(alert.alert_type, 1.0)

        # 时间衰减 (越新的预警优先级越高)
        age_minutes = (datetime.now() - alert.timestamp).total_seconds() / 60
        time_decay = math.exp(-age_minutes / 60)  # 1小时半衰期

        # 偏离程度
        if alert.threshold != 0:
            deviation = abs(alert.current_value - alert.threshold) / abs(alert.threshold)
        else:
            deviation = abs(alert.current_value)

        deviation_score = min(20, deviation * 100)

        priority = (severity_score + deviation_score) * type_multiplier * time_decay

        return round(priority, 2)

    def sort_alerts(self, alerts: List[Alert]) -> List[Alert]:
        """排序预警"""
        return sorted(alerts, key=lambda a: self.calculate_priority(a), reverse=True)

    def get_top_alerts(self, alerts: List[Alert], n: int = 10) -> List[Alert]:
        """获取Top N预警"""
        sorted_alerts = self.sort_alerts(alerts)
        return sorted_alerts[:n]


# ============ 自动处理建议器 ============

class AutoActionRecommender:
    """自动处理建议器"""

    def __init__(self):
        self._action_templates: Dict[str, Dict] = {
            # 风险预警处理
            "risk_drawdown": {
                "actions": [
                    "降低仓位至安全水平",
                    "检查持仓集中度",
                    "评估止损策略",
                ],
                "severity_threshold": 0.1,
            },
            "risk_var": {
                "actions": [
                    "增加对冲头寸",
                    "降低杠杆",
                    "调整持仓结构",
                ],
                "severity_threshold": 0.05,
            },
            # 业绩预警处理
            "performance_underperform": {
                "actions": [
                    "回顾近期交易决策",
                    "检查信号有效性",
                    "评估市场环境变化",
                ],
                "severity_threshold": -0.05,
            },
            # 持仓预警处理
            "position_overweight": {
                "actions": [
                    "分批减仓",
                    "设置止损位",
                    "监控相关新闻",
                ],
                "severity_threshold": 0.3,
            },
            # 市场预警处理
            "market_volatility": {
                "actions": [
                    "增加现金比例",
                    "使用期权对冲",
                    "等待市场企稳",
                ],
                "severity_threshold": 0.3,
            },
        }

    def recommend(self, alert: Alert) -> List[Dict]:
        """推荐处理方案"""
        recommendations = []

        # 基于预警类型推荐
        key = f"{alert.alert_type.value}_{alert.metadata.get('sub_type', '')}"
        template = self._action_templates.get(key)

        if template:
            for i, action in enumerate(template["actions"]):
                recommendations.append({
                    "priority": i + 1,
                    "action": action,
                    "reason": f"基于{alert.alert_type.value}类型预警的标准处理流程",
                })

        # 基于严重程度推荐
        if alert.severity == AlertSeverity.CRITICAL:
            recommendations.insert(0, {
                "priority": 0,
                "action": "立即通知风控主管",
                "reason": "严重预警需要人工介入",
            })

        # 基于偏离程度推荐
        if alert.threshold != 0:
            deviation = abs(alert.current_value - alert.threshold) / abs(alert.threshold)

            if deviation > 0.5:
                recommendations.append({
                    "priority": 1,
                    "action": "紧急处理: 大幅偏离阈值",
                    "reason": f"偏离程度: {deviation:.1%}",
                })

        return recommendations

    def auto_execute(self, alert: Alert) -> List[str]:
        """自动执行 (返回执行的动作列表)"""
        executed = []

        if alert.severity not in [AlertSeverity.CRITICAL, AlertSeverity.ERROR]:
            return executed

        # 检查是否配置了自动动作
        # 实际实现需要与交易系统对接

        if alert.alert_type == AlertType.RISK:
            if alert.current_value > alert.threshold * 1.5:
                executed.append("已自动降低仓位10%")

        if alert.alert_type == AlertType.POSITION:
            if alert.current_value > alert.threshold * 1.2:
                executed.append("已触发止损委托")

        return executed


# ============ 智能预警系统 ============

class IntelligentAlertSystem:
    """智能预警系统"""

    def __init__(self):
        self.anomaly_detector = AnomalyDetector()
        self.rule_engine = AlertRuleEngine()
        self.priority_manager = AlertPriorityManager()
        self.recommender = AutoActionRecommender()

        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: deque = deque(maxlen=10000)
        self._handlers: List[Callable] = []

        self._lock = threading.Lock()

        # 初始化默认规则
        self._init_default_rules()

    def _init_default_rules(self):
        """初始化默认规则"""
        default_rules = [
            AlertRule(
                rule_id="max_drawdown",
                name="最大回撤预警",
                alert_type=AlertType.RISK,
                severity=AlertSeverity.WARNING,
                condition="max_drawdown",
                threshold=0.05,
                comparison="gt",
            ),
            AlertRule(
                rule_id="daily_loss",
                name="日内亏损预警",
                alert_type=AlertType.RISK,
                severity=AlertSeverity.ERROR,
                condition="daily_pnl",
                threshold=-0.02,
                comparison="lt",
            ),
            AlertRule(
                rule_id="position_concentration",
                name="持仓集中度预警",
                alert_type=AlertType.POSITION,
                severity=AlertSeverity.WARNING,
                condition="max_position_weight",
                threshold=0.15,
                comparison="gt",
            ),
            AlertRule(
                rule_id="var_breach",
                name="VaR突破预警",
                alert_type=AlertType.RISK,
                severity=AlertSeverity.ERROR,
                condition="var_99",
                threshold=0.03,
                comparison="gt",
            ),
            AlertRule(
                rule_id="market_volatility",
                name="市场波动预警",
                alert_type=AlertType.MARKET,
                severity=AlertSeverity.WARNING,
                condition="market_volatility",
                threshold=0.02,
                comparison="gt",
            ),
        ]

        for rule in default_rules:
            self.rule_engine.add_rule(rule)

    def process_metrics(self, metrics: Dict[str, float]) -> List[Alert]:
        """处理指标"""
        alerts = []

        # 更新异常检测器
        for name, value in metrics.items():
            self.anomaly_detector.update(name, value)

        # 检测异常
        anomalies = self.anomaly_detector.detect_batch(metrics)
        for anomaly in anomalies:
            alert = self._create_alert_from_anomaly(anomaly)
            if alert:
                alerts.append(alert)

        # 评估规则
        rule_alerts = self.rule_engine.evaluate_all(metrics)
        alerts.extend(rule_alerts)

        # 处理预警
        for alert in alerts:
            self._handle_alert(alert)

        return alerts

    def _create_alert_from_anomaly(self, anomaly: AnomalyDetection) -> Optional[Alert]:
        """从异常创建预警"""
        if anomaly.confidence < 0.7:
            return None

        severity = AlertSeverity.WARNING if anomaly.confidence < 0.9 else AlertSeverity.ERROR

        alert = Alert(
            alert_id=f"anomaly_{int(datetime.now().timestamp() * 1000)}",
            rule_id="anomaly_detection",
            alert_type=AlertType.SYSTEM,
            severity=severity,
            title=f"异常检测: {anomaly.metric_name}",
            message=f"检测到{anomaly.anomaly_type.value}异常, 偏离度: {anomaly.deviation:.2f}",
            current_value=anomaly.value,
            threshold=anomaly.expected_value,
            timestamp=anomaly.timestamp,
            metadata={"anomaly": anomaly.to_dict()},
        )

        return alert

    def _handle_alert(self, alert: Alert):
        """处理预警"""
        with self._lock:
            self._active_alerts[alert.alert_id] = alert
            self._alert_history.append(alert)

        # 获取推荐
        recommendations = self.recommender.recommend(alert)
        alert.metadata["recommendations"] = recommendations

        # 触发处理器
        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"[IntelligentAlertSystem] 处理器执行失败: {e}")

        logger.info(f"[IntelligentAlertSystem] 预警: {alert.title} [{alert.severity.value}]")

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = "user") -> bool:
        """确认预警"""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if not alert:
                return False

            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_by = acknowledged_by
            alert.acknowledged_at = datetime.now()

        return True

    def resolve_alert(self, alert_id: str) -> bool:
        """解决预警"""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if not alert:
                return False

            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = datetime.now()

            del self._active_alerts[alert_id]

        return True

    def get_active_alerts(self, severity: AlertSeverity = None) -> List[Alert]:
        """获取活跃预警"""
        alerts = list(self._active_alerts.values())

        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        return self.priority_manager.sort_alerts(alerts)

    def get_top_alerts(self, n: int = 10) -> List[Alert]:
        """获取优先级最高的预警"""
        return self.priority_manager.get_top_alerts(list(self._active_alerts.values()), n)

    def register_handler(self, handler: Callable):
        """注册处理器"""
        self._handlers.append(handler)

    def get_statistics(self) -> Dict:
        """获取统计"""
        history = list(self._alert_history)

        severity_counts = defaultdict(int)
        type_counts = defaultdict(int)

        for alert in history:
            severity_counts[alert.severity.value] += 1
            type_counts[alert.alert_type.value] += 1

        return {
            "total_alerts": len(history),
            "active_alerts": len(self._active_alerts),
            "by_severity": dict(severity_counts),
            "by_type": dict(type_counts),
        }


# ============ 便捷函数 ============

def create_alert_system() -> IntelligentAlertSystem:
    """创建预警系统"""
    return IntelligentAlertSystem()


def detect_anomaly(values: List[float], new_value: float, threshold: float = 3.0) -> bool:
    """检测异常"""
    if len(values) < 10:
        return False

    mean = sum(values) / len(values)
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))

    if std == 0:
        return False

    z_score = abs(new_value - mean) / std
    return z_score > threshold
