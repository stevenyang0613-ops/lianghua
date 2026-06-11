"""松岗量化可转债策略 V3.0 实时风控仪表盘模块

功能:
- 可视化风控指标
- 实时预警
- 交互式仪表盘
- 风险热力图
- 历史追溯
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import json
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AlertLevel(str, Enum):
    """预警级别"""
    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"
    CRITICAL = "critical"


class MetricType(str, Enum):
    """指标类型"""
    GAUGE = "gauge"       # 仪表盘
    LINE = "line"         # 折线图
    BAR = "bar"           # 柱状图
    PIE = "pie"           # 饼图
    HEATMAP = "heatmap"   # 热力图
    TREEMAP = "treemap"   # 树状图


class RefreshRate(str, Enum):
    """刷新频率"""
    REALTIME = "realtime"  # 实时
    SECOND_5 = "5s"
    SECOND_10 = "10s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"


# ============ 数据模型 ============

@dataclass
class DashboardMetric:
    """仪表盘指标"""
    metric_id: str
    name: str
    value: float
    unit: str
    threshold_warning: float
    threshold_danger: float
    trend: float = 0  # 趋势
    history: List[float] = field(default_factory=list)
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def get_status(self) -> AlertLevel:
        """获取状态"""
        if self.value >= self.threshold_danger:
            return AlertLevel.DANGER
        elif self.value >= self.threshold_warning:
            return AlertLevel.WARNING
        return AlertLevel.INFO

    def to_dict(self) -> dict:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "value": round(self.value, 4),
            "unit": self.unit,
            "status": self.get_status().value,
            "trend": round(self.trend, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class DashboardWidget:
    """仪表盘组件"""
    widget_id: str
    title: str
    metric_type: MetricType
    metrics: List[DashboardMetric]
    position: Dict[str, int] = field(default_factory=dict)
    size: Dict[str, int] = field(default_factory=lambda: {"width": 4, "height": 3})
    refresh_rate: RefreshRate = RefreshRate.SECOND_10
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "widget_id": self.widget_id,
            "title": self.title,
            "metric_type": self.metric_type.value,
            "metrics": [m.to_dict() for m in self.metrics],
            "position": self.position,
            "size": self.size,
            "refresh_rate": self.refresh_rate.value,
            "config": self.config,
        }


@dataclass
class AlertEvent:
    """预警事件"""
    alert_id: str
    level: AlertLevel
    title: str
    message: str
    source: str
    timestamp: datetime
    acknowledged: bool = False
    acknowledged_by: str = None
    acknowledged_at: datetime = None

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
        }


# ============ 风控指标收集器 ============

class RiskMetricsCollector:
    """风控指标收集器"""

    def __init__(self, history_size: int = 1000):
        self.history_size = history_size
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=history_size))
        self._current_values: Dict[str, float] = {}
        self._lock = threading.Lock()

    def update_metric(self, metric_id: str, value: float, timestamp: datetime = None):
        """更新指标"""
        timestamp = timestamp or datetime.now()

        with self._lock:
            self._current_values[metric_id] = value
            self._metrics[metric_id].append({
                "value": value,
                "timestamp": timestamp.isoformat(),
            })

    def get_current_value(self, metric_id: str) -> Optional[float]:
        """获取当前值"""
        return self._current_values.get(metric_id)

    def get_history(self, metric_id: str, limit: int = 100) -> List[Dict]:
        """获取历史"""
        history = list(self._metrics.get(metric_id, []))
        return history[-limit:]

    def get_trend(self, metric_id: str, window: int = 10) -> float:
        """获取趋势"""
        history = list(self._metrics.get(metric_id, []))[-window:]
        if len(history) < 2:
            return 0

        values = [h["value"] for h in history]
        first_half = sum(values[:len(values)//2]) / (len(values)//2)
        second_half = sum(values[len(values)//2:]) / (len(values) - len(values)//2)

        return (second_half - first_half) / first_half if first_half != 0 else 0

    def get_all_metrics(self) -> Dict[str, float]:
        """获取所有指标"""
        return self._current_values.copy()


# ============ 预警管理器 ============

class AlertManager:
    """预警管理器"""

    def __init__(self, max_alerts: int = 1000):
        self.max_alerts = max_alerts
        self._alerts: deque = deque(maxlen=max_alerts)
        self._active_alerts: Dict[str, AlertEvent] = {}
        self._alert_handlers: List[Callable] = []
        self._lock = threading.Lock()

    def create_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        source: str = "system",
    ) -> str:
        """创建预警"""
        alert_id = f"alert_{int(time.time() * 1000)}"

        alert = AlertEvent(
            alert_id=alert_id,
            level=level,
            title=title,
            message=message,
            source=source,
            timestamp=datetime.now(),
        )

        with self._lock:
            self._alerts.append(alert)
            self._active_alerts[alert_id] = alert

        # 触发处理器
        for handler in self._alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"[AlertManager] 处理器执行失败: {e}")

        logger.info(f"[AlertManager] 创建预警: {title} [{level.value}]")

        return alert_id

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = "user") -> bool:
        """确认预警"""
        with self._lock:
            if alert_id not in self._active_alerts:
                return False

            alert = self._active_alerts[alert_id]
            alert.acknowledged = True
            alert.acknowledged_by = acknowledged_by
            alert.acknowledged_at = datetime.now()

            del self._active_alerts[alert_id]

        return True

    def get_active_alerts(self, level: AlertLevel = None) -> List[AlertEvent]:
        """获取活跃预警"""
        alerts = list(self._active_alerts.values())

        if level:
            alerts = [a for a in alerts if a.level == level]

        return sorted(alerts, key=lambda x: x.timestamp, reverse=True)

    def get_alert_history(self, limit: int = 100) -> List[AlertEvent]:
        """获取预警历史"""
        return list(self._alerts)[-limit:]

    def register_handler(self, handler: Callable):
        """注册处理器"""
        self._alert_handlers.append(handler)


# ============ 仪表盘构建器 ============

class DashboardBuilder:
    """仪表盘构建器"""

    def __init__(
        self,
        collector: RiskMetricsCollector,
        alert_manager: AlertManager,
    ):
        self.collector = collector
        self.alert_manager = alert_manager
        self._widgets: Dict[str, DashboardWidget] = {}
        self._layouts: Dict[str, Dict] = {}

        # 初始化默认仪表盘
        self._init_default_widgets()

    def _init_default_widgets(self):
        """初始化默认组件"""
        # 组合净值
        self.add_widget(DashboardWidget(
            widget_id="portfolio_nav",
            title="组合净值",
            metric_type=MetricType.LINE,
            metrics=[DashboardMetric(
                metric_id="nav",
                name="净值",
                value=1.0,
                unit="",
                threshold_warning=0.95,
                threshold_danger=0.90,
            )],
            position={"x": 0, "y": 0},
            size={"width": 6, "height": 3},
            refresh_rate=RefreshRate.SECOND_10,
        ))

        # 组合收益
        self.add_widget(DashboardWidget(
            widget_id="portfolio_return",
            title="组合收益",
            metric_type=MetricType.GAUGE,
            metrics=[DashboardMetric(
                metric_id="return_ytd",
                name="年初至今收益",
                value=0,
                unit="%",
                threshold_warning=-5,
                threshold_danger=-10,
            )],
            position={"x": 6, "y": 0},
            size={"width": 3, "height": 3},
        ))

        # 最大回撤
        self.add_widget(DashboardWidget(
            widget_id="max_drawdown",
            title="最大回撤",
            metric_type=MetricType.GAUGE,
            metrics=[DashboardMetric(
                metric_id="drawdown",
                name="回撤",
                value=0,
                unit="%",
                threshold_warning=5,
                threshold_danger=10,
            )],
            position={"x": 9, "y": 0},
            size={"width": 3, "height": 3},
        ))

        # VaR
        self.add_widget(DashboardWidget(
            widget_id="var_metrics",
            title="VaR指标",
            metric_type=MetricType.BAR,
            metrics=[
                DashboardMetric("var_95", "VaR 95%", 0, "%", 5, 10),
                DashboardMetric("var_99", "VaR 99%", 0, "%", 7, 15),
                DashboardMetric("cvar", "CVaR", 0, "%", 10, 20),
            ],
            position={"x": 0, "y": 3},
            size={"width": 4, "height": 3},
        ))

        # 持仓分布
        self.add_widget(DashboardWidget(
            widget_id="position_distribution",
            title="持仓分布",
            metric_type=MetricType.PIE,
            metrics=[],
            position={"x": 4, "y": 3},
            size={"width": 4, "height": 3},
        ))

        # 风险热力图
        self.add_widget(DashboardWidget(
            widget_id="risk_heatmap",
            title="风险热力图",
            metric_type=MetricType.HEATMAP,
            metrics=[],
            position={"x": 8, "y": 3},
            size={"width": 4, "height": 3},
        ))

        # 活跃预警
        self.add_widget(DashboardWidget(
            widget_id="active_alerts",
            title="活跃预警",
            metric_type=MetricType.BAR,
            metrics=[],
            position={"x": 0, "y": 6},
            size={"width": 12, "height": 2},
            refresh_rate=RefreshRate.SECOND_5,
        ))

    def add_widget(self, widget: DashboardWidget):
        """添加组件"""
        self._widgets[widget.widget_id] = widget

    def get_widget(self, widget_id: str) -> Optional[DashboardWidget]:
        """获取组件"""
        return self._widgets.get(widget_id)

    def update_widget_data(self, widget_id: str, data: Dict[str, float]):
        """更新组件数据"""
        widget = self._widgets.get(widget_id)
        if not widget:
            return

        for metric in widget.metrics:
            if metric.metric_id in data:
                value = data[metric.metric_id]
                metric.value = value
                metric.trend = self.collector.get_trend(metric.metric_id)
                metric.timestamp = datetime.now()

                # 更新收集器
                self.collector.update_metric(metric.metric_id, value)

                # 检查预警
                status = metric.get_status()
                if status in [AlertLevel.WARNING, AlertLevel.DANGER]:
                    self.alert_manager.create_alert(
                        level=status,
                        title=f"{metric.name}预警",
                        message=f"{metric.name}当前值: {value:.2f}{metric.unit}",
                        source="dashboard",
                    )

    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表盘数据"""
        return {
            "widgets": [w.to_dict() for w in self._widgets.values()],
            "active_alerts": [a.to_dict() for a in self.alert_manager.get_active_alerts()],
            "last_update": datetime.now().isoformat(),
        }

    def export_layout(self) -> Dict[str, Any]:
        """导出布局"""
        return {
            "widgets": [
                {
                    "widget_id": w.widget_id,
                    "position": w.position,
                    "size": w.size,
                }
                for w in self._widgets.values()
            ],
        }

    def import_layout(self, layout: Dict[str, Any]):
        """导入布局"""
        for widget_config in layout.get("widgets", []):
            widget_id = widget_config.get("widget_id")
            if widget_id in self._widgets:
                self._widgets[widget_id].position = widget_config.get("position", {})
                self._widgets[widget_id].size = widget_config.get("size", {})


# ============ 实时数据推送 ============

class RealtimeDataPusher:
    """实时数据推送"""

    def __init__(self, builder: DashboardBuilder):
        self.builder = builder
        self._subscribers: List[Callable] = []
        self._running = False
        self._push_thread: threading.Thread = None

    def subscribe(self, callback: Callable):
        """订阅"""
        self._subscribers.append(callback)

    def start(self):
        """启动"""
        self._running = True
        self._push_thread = threading.Thread(target=self._push_loop, daemon=True)
        self._push_thread.start()

    def stop(self):
        """停止"""
        self._running = False
        if self._push_thread:
            self._push_thread.join(timeout=5)

    def _push_loop(self):
        """推送循环"""
        while self._running:
            try:
                data = self.builder.get_dashboard_data()

                for callback in self._subscribers:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"[RealtimeDataPusher] 推送失败: {e}")

                time.sleep(1)  # 每秒推送一次

            except Exception as e:
                logger.error(f"[RealtimeDataPusher] 推送异常: {e}")


# ============ 风控仪表盘服务 ============

class RiskDashboardService:
    """风控仪表盘服务"""

    def __init__(self):
        self.collector = RiskMetricsCollector()
        self.alert_manager = AlertManager()
        self.builder = DashboardBuilder(self.collector, self.alert_manager)
        self.pusher = RealtimeDataPusher(self.builder)

    def start(self):
        """启动服务"""
        self.pusher.start()
        logger.info("[RiskDashboardService] 服务启动")

    def stop(self):
        """停止服务"""
        self.pusher.stop()
        logger.info("[RiskDashboardService] 服务停止")

    def update_metrics(self, metrics: Dict[str, float]):
        """更新指标"""
        for metric_id, value in metrics.items():
            self.collector.update_metric(metric_id, value)

    def update_widget(self, widget_id: str, data: Dict[str, float]):
        """更新组件"""
        self.builder.update_widget_data(widget_id, data)

    def get_dashboard(self) -> Dict[str, Any]:
        """获取仪表盘"""
        return self.builder.get_dashboard_data()

    def get_alerts(self, level: str = None) -> List[Dict]:
        """获取预警"""
        level_enum = AlertLevel(level) if level else None
        return [a.to_dict() for a in self.alert_manager.get_active_alerts(level_enum)]

    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认预警"""
        return self.alert_manager.acknowledge_alert(alert_id)

    def subscribe_updates(self, callback: Callable):
        """订阅更新"""
        self.pusher.subscribe(callback)


# ============ 便捷函数 ============

def create_risk_dashboard() -> RiskDashboardService:
    """创建风控仪表盘"""
    return RiskDashboardService()


def get_default_dashboard_config() -> Dict[str, Any]:
    """获取默认仪表盘配置"""
    return {
        "title": "松岗量化策略风控仪表盘",
        "refresh_rate": "10s",
        "widgets": [
            {
                "id": "portfolio_nav",
                "title": "组合净值",
                "type": "line",
                "position": {"x": 0, "y": 0, "w": 6, "h": 3},
            },
            {
                "id": "portfolio_return",
                "title": "组合收益",
                "type": "gauge",
                "position": {"x": 6, "y": 0, "w": 3, "h": 3},
            },
            {
                "id": "max_drawdown",
                "title": "最大回撤",
                "type": "gauge",
                "position": {"x": 9, "y": 0, "w": 3, "h": 3},
            },
            {
                "id": "risk_heatmap",
                "title": "风险热力图",
                "type": "heatmap",
                "position": {"x": 0, "y": 3, "w": 12, "h": 3},
            },
        ],
    }
