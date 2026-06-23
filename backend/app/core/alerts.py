"""
系统监控告警配置

定义告警规则和通知渠道
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """告警级别"""
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'


class AlertType(Enum):
    """告警类型"""
    SYSTEM = 'system'
    PERFORMANCE = 'performance'
    TRADING = 'trading'
    DATA_SOURCE = 'data_source'
    STRATEGY = 'strategy'


@dataclass
class Alert:
    """告警"""
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    source: str
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    resolved_at: Optional[datetime] = None


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    alert_type: AlertType
    condition: Callable[[Dict], bool]
    severity: AlertSeverity
    message_template: str
    cooldown_seconds: int = 300  # 冷却时间
    enabled: bool = True


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self._alerts: List[Alert] = []
        self._rules: Dict[str, AlertRule] = {}
        self._callbacks: List[Callable] = []
        self._last_triggered: Dict[str, datetime] = {}
        self._max_alerts = 1000

    def register_rule(self, rule: AlertRule) -> None:
        """注册告警规则"""
        self._rules[rule.name] = rule
        logger.info(f"[Alert] Registered rule: {rule.name}")

    def add_callback(self, callback: Callable) -> None:
        """添加告警回调"""
        self._callbacks.append(callback)

    async def check_and_alert(
        self,
        rule_name: str,
        metrics: Dict[str, Any],
        source: str = 'system',
    ) -> Optional[Alert]:
        """检查规则并触发告警"""
        rule = self._rules.get(rule_name)
        if not rule or not rule.enabled:
            return None

        # 检查冷却时间
        last = self._last_triggered.get(rule_name)
        if last:
            elapsed = (datetime.now() - last).total_seconds()
            if elapsed < rule.cooldown_seconds:
                return None

        # 检查条件
        try:
            if rule.condition(metrics):
                alert = await self._create_alert(rule, metrics, source)
                return alert
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[Alert] Rule check error: {e}")

        return None

    async def _create_alert(
        self,
        rule: AlertRule,
        metrics: Dict,
        source: str,
    ) -> Alert:
        """创建告警"""
        import secrets

        alert = Alert(
            alert_id=f"alert_{secrets.token_hex(8)}",
            alert_type=rule.alert_type,
            severity=rule.severity,
            title=rule.name,
            message=rule.message_template.format(**metrics),
            source=source,
            timestamp=datetime.now(),
            details=metrics,
        )

        self._alerts.append(alert)
        self._last_triggered[rule.name] = datetime.now()

        # 限制告警数量
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

        # 触发回调
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[Alert] Callback error: {e}")

        logger.warning(f"[Alert] {rule.severity.value.upper()}: {alert.message}")
        return alert

    def get_alerts(
        self,
        severity: AlertSeverity = None,
        alert_type: AlertType = None,
        acknowledged: bool = None,
        limit: int = 100,
    ) -> List[Alert]:
        """获取告警列表"""
        alerts = self._alerts.copy()

        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        if acknowledged is not None:
            alerts = [a for a in alerts if a.acknowledged == acknowledged]

        return alerts[-limit:]

    def acknowledge(self, alert_id: str) -> bool:
        """确认告警"""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def resolve(self, alert_id: str) -> bool:
        """解决告警"""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.resolved_at = datetime.now()
                return True
        return False


# 预定义告警规则
def get_default_rules() -> List[AlertRule]:
    """获取默认告警规则"""
    return [
        # CPU告警
        AlertRule(
            name='high_cpu_usage',
            alert_type=AlertType.SYSTEM,
            condition=lambda m: m.get('cpu_percent', 0) > 80,
            severity=AlertSeverity.WARNING,
            message_template='CPU使用率过高: {cpu_percent:.1f}%',
            cooldown_seconds=300,
        ),
        AlertRule(
            name='critical_cpu_usage',
            alert_type=AlertType.SYSTEM,
            condition=lambda m: m.get('cpu_percent', 0) > 95,
            severity=AlertSeverity.CRITICAL,
            message_template='CPU使用率严重过高: {cpu_percent:.1f}%',
            cooldown_seconds=60,
        ),

        # 内存告警
        AlertRule(
            name='high_memory_usage',
            alert_type=AlertType.SYSTEM,
            condition=lambda m: m.get('memory_percent', 0) > 80,
            severity=AlertSeverity.WARNING,
            message_template='内存使用率过高: {memory_percent:.1f}%',
            cooldown_seconds=300,
        ),

        # 数据源告警
        AlertRule(
            name='datasource_disconnected',
            alert_type=AlertType.DATA_SOURCE,
            condition=lambda m: not m.get('datasource_connected', True),
            severity=AlertSeverity.ERROR,
            message_template='数据源断开连接: {datasource_name}',
            cooldown_seconds=60,
        ),
        AlertRule(
            name='datasource_high_latency',
            alert_type=AlertType.DATA_SOURCE,
            condition=lambda m: m.get('datasource_latency_ms', 0) > 5000,
            severity=AlertSeverity.WARNING,
            message_template='数据源延迟过高: {datasource_latency_ms:.0f}ms',
            cooldown_seconds=300,
        ),

        # 策略告警
        AlertRule(
            name='strategy_execution_failed',
            alert_type=AlertType.STRATEGY,
            condition=lambda m: m.get('strategy_failed', False),
            severity=AlertSeverity.ERROR,
            message_template='策略执行失败: {strategy_name} - {error_message}',
            cooldown_seconds=60,
        ),
        AlertRule(
            name='strategy_slow_execution',
            alert_type=AlertType.PERFORMANCE,
            condition=lambda m: m.get('strategy_duration_ms', 0) > 30000,
            severity=AlertSeverity.WARNING,
            message_template='策略执行超时: {strategy_name} 耗时 {strategy_duration_ms:.0f}ms',
            cooldown_seconds=300,
        ),

        # 交易告警
        AlertRule(
            name='trade_failed',
            alert_type=AlertType.TRADING,
            condition=lambda m: m.get('trade_failed', False),
            severity=AlertSeverity.ERROR,
            message_template='交易失败: {code} {action} - {error}',
            cooldown_seconds=30,
        ),
        AlertRule(
            name='high_trading_cost',
            alert_type=AlertType.TRADING,
            condition=lambda m: m.get('cost_ratio', 0) > 0.01,
            severity=AlertSeverity.WARNING,
            message_template='交易成本过高: {cost_ratio:.2%}',
            cooldown_seconds=3600,
        ),

        # 性能告警
        AlertRule(
            name='api_slow_response',
            alert_type=AlertType.PERFORMANCE,
            condition=lambda m: m.get('api_latency_ms', 0) > 2000,
            severity=AlertSeverity.WARNING,
            message_template='API响应过慢: {endpoint} 耗时 {api_latency_ms:.0f}ms',
            cooldown_seconds=300,
        ),
    ]


# 全局单例
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """获取告警管理器"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
        # 注册默认规则
        for rule in get_default_rules():
            _alert_manager.register_rule(rule)
    return _alert_manager


async def check_system_health() -> Dict[str, Any]:
    """检查系统健康状态"""
    import psutil

    process = psutil.Process()

    return {
        'cpu_percent': process.cpu_percent(),
        'memory_percent': process.memory_percent(),
        'memory_mb': process.memory_info().rss / 1024 / 1024,
        'threads': process.num_threads(),
        'timestamp': datetime.now().isoformat(),
    }
