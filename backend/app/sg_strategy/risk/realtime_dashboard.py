"""松岗量化可转债策略 V3.0 实时风控仪表盘模块

功能:
- WebSocket实时推送
- 风险指标可视化
- 预警阈值触发
- 仪表盘数据聚合
- 历史数据对比
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Set
from enum import Enum
import logging
import asyncio
import json
import threading
from collections import deque, defaultdict
import numpy as np

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AlertLevel(str, Enum):
    """预警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class MetricType(str, Enum):
    """指标类型"""
    VALUE = "value"
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    CURRENCY = "currency"
    COUNT = "count"


class ChartType(str, Enum):
    """图表类型"""
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    GAUGE = "gauge"
    HEATMAP = "heatmap"
    SCATTER = "scatter"


# ============ 数据模型 ============

@dataclass
class RiskMetric:
    """风险指标"""
    name: str
    code: str
    value: float
    unit: MetricType
    threshold_warning: float
    threshold_critical: float
    timestamp: datetime
    trend: str = "stable"  # up, down, stable
    change_pct: float = 0

    @property
    def alert_level(self) -> AlertLevel:
        """预警级别"""
        if self.value >= self.threshold_critical:
            return AlertLevel.CRITICAL
        elif self.value >= self.threshold_warning:
            return AlertLevel.WARNING
        return AlertLevel.INFO

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "code": self.code,
            "value": round(self.value, 4),
            "unit": self.unit.value,
            "alert_level": self.alert_level.value,
            "trend": self.trend,
            "change_pct": round(self.change_pct, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Alert:
    """预警信息"""
    alert_id: str
    level: AlertLevel
    metric_code: str
    message: str
    value: float
    threshold: float
    timestamp: datetime
    acknowledged: bool = False
    resolved_at: datetime = None

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "level": self.level.value,
            "metric_code": self.metric_code,
            "message": self.message,
            "value": round(self.value, 4),
            "threshold": round(self.threshold, 4),
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
            "resolved": self.resolved_at is not None,
        }


@dataclass
class DashboardWidget:
    """仪表盘组件"""
    widget_id: str
    title: str
    chart_type: ChartType
    metrics: List[str]
    refresh_interval: int = 5  # 秒
    position: Tuple[int, int] = (0, 0)  # (row, col)
    size: Tuple[int, int] = (1, 1)  # (height, width)
    config: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "widget_id": self.widget_id,
            "title": self.title,
            "chart_type": self.chart_type.value,
            "metrics": self.metrics,
            "refresh_interval": self.refresh_interval,
            "position": self.position,
            "size": self.size,
        }


@dataclass
class DashboardLayout:
    """仪表盘布局"""
    layout_id: str
    name: str
    widgets: List[DashboardWidget]
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "layout_id": self.layout_id,
            "name": self.name,
            "widgets": [w.to_dict() for w in self.widgets],
            "created_at": self.created_at.isoformat(),
        }


# ============ 指标计算器 ============

class MetricCalculator:
    """指标计算器"""

    def __init__(self):
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

    def calculate_var(
        self,
        returns: List[float],
        confidence: float = 0.95,
        method: str = "historical",
    ) -> float:
        """计算VaR"""
        if not returns:
            return 0

        returns = np.array(returns)

        if method == "historical":
            return -np.percentile(returns, (1 - confidence) * 100)
        elif method == "parametric":
            mu = np.mean(returns)
            sigma = np.std(returns)
            z_score = -1.645 if confidence == 0.95 else -2.326
            return -(mu + z_score * sigma)
        else:
            return -np.percentile(returns, (1 - confidence) * 100)

    def calculate_cvar(
        self,
        returns: List[float],
        confidence: float = 0.95,
    ) -> float:
        """计算CVaR/ES"""
        if not returns:
            return 0

        returns = np.array(returns)
        var = self.calculate_var(returns, confidence)

        return -np.mean(returns[returns <= -var])

    def calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """计算最大回撤"""
        if not equity_curve:
            return 0

        peak = equity_curve[0]
        max_dd = 0

        for value in equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            max_dd = max(max_dd, dd)

        return max_dd

    def calculate_sharpe_ratio(
        self,
        returns: List[float],
        risk_free_rate: float = 0.03,
    ) -> float:
        """计算夏普比率"""
        if len(returns) < 2:
            return 0

        returns = np.array(returns)
        excess_returns = returns - risk_free_rate / 252

        if np.std(excess_returns) == 0:
            return 0

        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)

    def calculate_beta(
        self,
        portfolio_returns: List[float],
        benchmark_returns: List[float],
    ) -> float:
        """计算Beta"""
        if len(portfolio_returns) < 2 or len(benchmark_returns) < 2:
            return 1.0

        min_len = min(len(portfolio_returns), len(benchmark_returns))
        portfolio_returns = np.array(portfolio_returns[:min_len])
        benchmark_returns = np.array(benchmark_returns[:min_len])

        covariance = np.cov(portfolio_returns, benchmark_returns)[0, 1]
        benchmark_variance = np.var(benchmark_returns)

        return covariance / benchmark_variance if benchmark_variance > 0 else 1.0

    def calculate_tracking_error(
        self,
        portfolio_returns: List[float],
        benchmark_returns: List[float],
    ) -> float:
        """计算跟踪误差"""
        if len(portfolio_returns) < 2 or len(benchmark_returns) < 2:
            return 0

        min_len = min(len(portfolio_returns), len(benchmark_returns))
        portfolio_returns = np.array(portfolio_returns[:min_len])
        benchmark_returns = np.array(benchmark_returns[:min_len])

        active_returns = portfolio_returns - benchmark_returns

        return np.std(active_returns) * np.sqrt(252)

    def calculate_concentration_risk(self, weights: List[float]) -> float:
        """计算集中度风险（赫芬达尔指数）"""
        if not weights:
            return 0

        weights = np.array([w for w in weights if w > 0])

        return np.sum(weights ** 2)


# ============ 预警管理器 ============

class AlertManager:
    """预警管理器"""

    def __init__(self):
        self._alerts: Dict[str, Alert] = {}
        self._alert_handlers: List[Callable] = []
        self._alert_counter = 0
        self._lock = threading.Lock()

    def check_threshold(
        self,
        metric: RiskMetric,
    ) -> Optional[Alert]:
        """检查阈值"""
        if metric.alert_level == AlertLevel.INFO:
            return None

        with self._lock:
            self._alert_counter += 1
            alert_id = f"alert_{self._alert_counter}"

            threshold = (
                metric.threshold_critical
                if metric.alert_level == AlertLevel.CRITICAL
                else metric.threshold_warning
            )

            alert = Alert(
                alert_id=alert_id,
                level=metric.alert_level,
                metric_code=metric.code,
                message=f"{metric.name} 超过阈值: {metric.value:.4f} > {threshold:.4f}",
                value=metric.value,
                threshold=threshold,
                timestamp=datetime.now(),
            )

            self._alerts[alert_id] = alert

            # 触发处理器
            for handler in self._alert_handlers:
                try:
                    handler(alert)
                except Exception as e:
                    logger.error(f"[AlertManager] 处理器执行失败: {e}")

            return alert

    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认预警"""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert:
                alert.acknowledged = True
                return True
            return False

    def resolve_alert(self, alert_id: str) -> bool:
        """解决预警"""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert:
                alert.resolved_at = datetime.now()
                return True
            return False

    def get_active_alerts(self) -> List[Alert]:
        """获取活跃预警"""
        with self._lock:
            return [
                a for a in self._alerts.values()
                if a.resolved_at is None
            ]

    def get_alerts_by_level(self, level: AlertLevel) -> List[Alert]:
        """按级别获取预警"""
        with self._lock:
            return [a for a in self._alerts.values() if a.level == level]

    def register_handler(self, handler: Callable):
        """注册处理器"""
        self._alert_handlers.append(handler)


# ============ WebSocket推送器 ============

class WebSocketPusher:
    """WebSocket推送器"""

    def __init__(self):
        self._clients: Set = set()
        self._subscribers: Dict[str, Set] = defaultdict(set)
        self._lock = threading.Lock()

    async def connect(self, client_id: str, websocket: Any):
        """连接客户端"""
        with self._lock:
            self._clients.add(client_id)

        logger.info(f"[WebSocketPusher] 客户端连接: {client_id}")

    async def disconnect(self, client_id: str):
        """断开客户端"""
        with self._lock:
            self._clients.discard(client_id)
            for subscribers in self._subscribers.values():
                subscribers.discard(client_id)

        logger.info(f"[WebSocketPusher] 客户端断开: {client_id}")

    async def subscribe(self, client_id: str, channel: str):
        """订阅频道"""
        with self._lock:
            self._subscribers[channel].add(client_id)

    async def unsubscribe(self, client_id: str, channel: str):
        """取消订阅"""
        with self._lock:
            self._subscribers[channel].discard(client_id)

    async def push(self, channel: str, data: Dict):
        """推送数据"""
        message = json.dumps({
            "channel": channel,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })

        with self._lock:
            subscribers = self._subscribers.get(channel, set()).copy()

        # 这里应该实际推送，简化处理
        logger.debug(f"[WebSocketPusher] 推送消息到 {len(subscribers)} 个客户端")

    async def broadcast(self, data: Dict):
        """广播数据"""
        message = json.dumps({
            "channel": "broadcast",
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })

        with self._lock:
            client_count = len(self._clients)

        logger.debug(f"[WebSocketPusher] 广播消息到 {client_count} 个客户端")


# ============ 仪表盘数据聚合器 ============

class DashboardAggregator:
    """仪表盘数据聚合器"""

    def __init__(self):
        self._metrics: Dict[str, RiskMetric] = {}
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._lock = threading.Lock()

    def update_metric(self, metric: RiskMetric):
        """更新指标"""
        with self._lock:
            # 计算趋势
            if metric.code in self._metrics:
                prev_value = self._metrics[metric.code].value
                if prev_value > 0:
                    metric.change_pct = (metric.value - prev_value) / prev_value
                    if metric.change_pct > 0.01:
                        metric.trend = "up"
                    elif metric.change_pct < -0.01:
                        metric.trend = "down"
                    else:
                        metric.trend = "stable"

            self._metrics[metric.code] = metric
            self._history[metric.code].append({
                "value": metric.value,
                "timestamp": metric.timestamp.isoformat(),
            })

    def get_metric(self, code: str) -> Optional[RiskMetric]:
        """获取指标"""
        return self._metrics.get(code)

    def get_all_metrics(self) -> List[RiskMetric]:
        """获取所有指标"""
        return list(self._metrics.values())

    def get_metric_history(
        self,
        code: str,
        start_time: datetime = None,
        end_time: datetime = None,
    ) -> List[Dict]:
        """获取指标历史"""
        history = list(self._history.get(code, []))

        if start_time or end_time:
            filtered = []
            for item in history:
                ts = datetime.fromisoformat(item["timestamp"])
                if start_time and ts < start_time:
                    continue
                if end_time and ts > end_time:
                    continue
                filtered.append(item)
            history = filtered

        return history

    def get_aggregated_data(
        self,
        metrics: List[str],
        aggregation: str = "latest",
    ) -> Dict:
        """获取聚合数据"""
        result = {}

        for code in metrics:
            metric = self._metrics.get(code)
            if metric:
                if aggregation == "latest":
                    result[code] = metric.to_dict()
                elif aggregation == "history":
                    result[code] = {
                        "current": metric.to_dict(),
                        "history": self.get_metric_history(code),
                    }

        return result

    def compare_with_history(
        self,
        code: str,
        comparison_period: timedelta = timedelta(days=7),
    ) -> Dict:
        """与历史对比"""
        metric = self._metrics.get(code)
        if not metric:
            return {}

        history = self.get_metric_history(code)
        if not history:
            return {"current": metric.to_dict()}

        # 计算历史统计
        values = [h["value"] for h in history]
        hist_mean = np.mean(values)
        hist_std = np.std(values)
        hist_max = max(values)
        hist_min = min(values)

        return {
            "current": metric.to_dict(),
            "history_stats": {
                "mean": round(hist_mean, 4),
                "std": round(hist_std, 4),
                "max": round(hist_max, 4),
                "min": round(hist_min, 4),
                "percentile": round(
                    (metric.value - hist_min) / (hist_max - hist_min) * 100, 2
                ) if hist_max > hist_min else 50,
            },
        }


# ============ 实时风控仪表盘服务 ============

class RealtimeRiskDashboard:
    """实时风控仪表盘服务"""

    def __init__(self):
        self.metric_calculator = MetricCalculator()
        self.alert_manager = AlertManager()
        self.websocket_pusher = WebSocketPusher()
        self.aggregator = DashboardAggregator()

        self._layouts: Dict[str, DashboardLayout] = {}
        self._update_handlers: List[Callable] = []
        self._running = False

        self._initialize_default_metrics()
        self._initialize_default_layout()

    def _initialize_default_metrics(self):
        """初始化默认指标"""
        default_metrics = [
            ("var_95", "VaR (95%)", 0.05, 0.10),
            ("cvar_95", "CVaR (95%)", 0.07, 0.12),
            ("max_drawdown", "最大回撤", 0.10, 0.20),
            ("sharpe_ratio", "夏普比率", 1.0, 0.5),
            ("beta", "Beta", 1.2, 1.5),
            ("tracking_error", "跟踪误差", 0.05, 0.10),
            ("concentration", "集中度", 0.25, 0.40),
            ("leverage", "杠杆率", 1.5, 2.0),
        ]

        for code, name, warning, critical in default_metrics:
            self.aggregator.update_metric(RiskMetric(
                name=name,
                code=code,
                value=0,
                unit=MetricType.RATIO if code != "sharpe_ratio" else MetricType.VALUE,
                threshold_warning=warning,
                threshold_critical=critical,
                timestamp=datetime.now(),
            ))

    def _initialize_default_layout(self):
        """初始化默认布局"""
        widgets = [
            DashboardWidget(
                widget_id="risk_overview",
                title="风险概览",
                chart_type=ChartType.GAUGE,
                metrics=["var_95", "max_drawdown"],
                position=(0, 0),
                size=(2, 2),
            ),
            DashboardWidget(
                widget_id="performance_metrics",
                title="绩效指标",
                chart_type=ChartType.BAR,
                metrics=["sharpe_ratio", "beta", "tracking_error"],
                position=(0, 2),
                size=(1, 2),
            ),
            DashboardWidget(
                widget_id="concentration_heatmap",
                title="持仓集中度",
                chart_type=ChartType.HEATMAP,
                metrics=["concentration", "leverage"],
                position=(1, 2),
                size=(1, 2),
            ),
        ]

        self._layouts["default"] = DashboardLayout(
            layout_id="default",
            name="默认风控仪表盘",
            widgets=widgets,
        )

    def update_risk_metrics(
        self,
        portfolio_data: Dict,
        market_data: Dict = None,
    ):
        """更新风险指标"""
        timestamp = datetime.now()

        # 计算VaR
        if "returns" in portfolio_data:
            var_95 = self.metric_calculator.calculate_var(
                portfolio_data["returns"], confidence=0.95
            )
            self._update_single_metric("var_95", var_95, timestamp)

            cvar_95 = self.metric_calculator.calculate_cvar(
                portfolio_data["returns"], confidence=0.95
            )
            self._update_single_metric("cvar_95", cvar_95, timestamp)

            sharpe = self.metric_calculator.calculate_sharpe_ratio(
                portfolio_data["returns"]
            )
            self._update_single_metric("sharpe_ratio", sharpe, timestamp)

        # 计算最大回撤
        if "equity_curve" in portfolio_data:
            max_dd = self.metric_calculator.calculate_max_drawdown(
                portfolio_data["equity_curve"]
            )
            self._update_single_metric("max_drawdown", max_dd, timestamp)

        # 计算Beta
        if market_data and "benchmark_returns" in market_data:
            if "returns" in portfolio_data:
                beta = self.metric_calculator.calculate_beta(
                    portfolio_data["returns"],
                    market_data["benchmark_returns"],
                )
                self._update_single_metric("beta", beta, timestamp)

                te = self.metric_calculator.calculate_tracking_error(
                    portfolio_data["returns"],
                    market_data["benchmark_returns"],
                )
                self._update_single_metric("tracking_error", te, timestamp)

        # 计算集中度
        if "weights" in portfolio_data:
            concentration = self.metric_calculator.calculate_concentration_risk(
                portfolio_data["weights"]
            )
            self._update_single_metric("concentration", concentration, timestamp)

        # 计算杠杆
        if "leverage" in portfolio_data:
            self._update_single_metric("leverage", portfolio_data["leverage"], timestamp)

    def _update_single_metric(self, code: str, value: float, timestamp: datetime):
        """更新单个指标"""
        current = self.aggregator.get_metric(code)
        if current:
            metric = RiskMetric(
                name=current.name,
                code=code,
                value=value,
                unit=current.unit,
                threshold_warning=current.threshold_warning,
                threshold_critical=current.threshold_critical,
                timestamp=timestamp,
            )
            self.aggregator.update_metric(metric)

            # 检查预警
            alert = self.alert_manager.check_threshold(metric)
            if alert:
                logger.warning(f"[RealtimeRiskDashboard] 预警触发: {alert.message}")

    async def push_update(self, channel: str = "risk_metrics"):
        """推送更新"""
        metrics = self.aggregator.get_all_metrics()
        data = {"metrics": [m.to_dict() for m in metrics]}
        await self.websocket_pusher.push(channel, data)

    def get_layout(self, layout_id: str = "default") -> Optional[DashboardLayout]:
        """获取布局"""
        return self._layouts.get(layout_id)

    def create_layout(
        self,
        layout_id: str,
        name: str,
        widgets: List[DashboardWidget],
    ) -> DashboardLayout:
        """创建布局"""
        layout = DashboardLayout(
            layout_id=layout_id,
            name=name,
            widgets=widgets,
        )
        self._layouts[layout_id] = layout
        return layout

    def get_alerts(self, level: AlertLevel = None) -> List[Alert]:
        """获取预警"""
        if level:
            return self.alert_manager.get_alerts_by_level(level)
        return self.alert_manager.get_active_alerts()

    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认预警"""
        return self.alert_manager.acknowledge_alert(alert_id)

    def get_metric_comparison(self, code: str) -> Dict:
        """获取指标对比"""
        return self.aggregator.compare_with_history(code)


# ============ 便捷函数 ============

def create_risk_dashboard() -> RealtimeRiskDashboard:
    """创建风控仪表盘"""
    return RealtimeRiskDashboard()


def calculate_portfolio_risk(
    returns: List[float],
    equity_curve: List[float] = None,
    weights: List[float] = None,
) -> Dict:
    """计算组合风险"""
    calculator = MetricCalculator()

    result = {
        "var_95": calculator.calculate_var(returns, confidence=0.95),
        "cvar_95": calculator.calculate_cvar(returns, confidence=0.95),
        "sharpe_ratio": calculator.calculate_sharpe_ratio(returns),
    }

    if equity_curve:
        result["max_drawdown"] = calculator.calculate_max_drawdown(equity_curve)

    if weights:
        result["concentration"] = calculator.calculate_concentration_risk(weights)

    return result
