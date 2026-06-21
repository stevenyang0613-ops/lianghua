"""西部量化可转债策略 V3.0 告警通知模块

功能:
- Slack通知
- 邮件通知
- Webhook通知
- 短信通知
- 告警聚合
- 通知模板
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import time
from collections import defaultdict
import requests

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AlertSeverity(str, Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationChannel(str, Enum):
    """通知渠道"""
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"
    SMS = "sms"
    PAGERDUTY = "pagerduty"


# ============ 数据模型 ============

@dataclass
class Alert:
    """告警"""
    alert_id: str
    name: str
    severity: AlertSeverity
    summary: str
    description: str
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    starts_at: datetime = None
    ends_at: datetime = None
    status: str = "firing"  # firing, resolved

    def __post_init__(self):
        if self.starts_at is None:
            self.starts_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "name": self.name,
            "severity": self.severity.value,
            "summary": self.summary,
            "description": self.description,
            "labels": self.labels,
            "annotations": self.annotations,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "status": self.status,
        }


@dataclass
class NotificationConfig:
    """通知配置"""
    # Slack配置
    slack_webhook_url: str = ""
    slack_channel: str = "#alerts"

    # 邮件配置
    smtp_host: str = "smtp.xb-strategy.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "alerts@xb-strategy.com"
    email_to: List[str] = field(default_factory=list)

    # Webhook配置
    webhook_url: str = ""
    webhook_headers: Dict[str, str] = field(default_factory=dict)

    # 短信配置
    sms_api_url: str = ""
    sms_api_key: str = ""
    sms_recipients: List[str] = field(default_factory=list)

    # 聚合配置
    aggregation_window: int = 300  # 秒
    max_alerts_per_notification: int = 10


# ============ 通知发送器 ============

class SlackNotifier:
    """Slack通知发送器"""

    def __init__(self, webhook_url: str, channel: str = "#alerts"):
        self.webhook_url = webhook_url
        self.channel = channel

    def send(self, alert: Alert) -> bool:
        """发送Slack通知"""
        if not self.webhook_url:
            logger.warning("[SlackNotifier] 未配置webhook URL")
            return False

        # 构建消息
        color = self._get_color(alert.severity)
        emoji = self._get_emoji(alert.severity)

        payload = {
            "channel": self.channel,
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} [{alert.severity.value.upper()}] {alert.name}",
                    "text": alert.summary,
                    "fields": [
                        {
                            "title": "描述",
                            "value": alert.description,
                            "short": False,
                        },
                        {
                            "title": "时间",
                            "value": alert.starts_at.strftime("%Y-%m-%d %H:%M:%S"),
                            "short": True,
                        },
                        {
                            "title": "状态",
                            "value": alert.status.upper(),
                            "short": True,
                        },
                    ],
                    "footer": "西部量化策略告警系统",
                    "ts": int(alert.starts_at.timestamp()),
                }
            ],
        }

        # 添加标签
        if alert.labels:
            labels_text = "\n".join([f"• {k}: {v}" for k, v in alert.labels.items()])
            payload["attachments"][0]["fields"].append({
                "title": "标签",
                "value": f"```\n{labels_text}\n```",
                "short": False,
            })

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[SlackNotifier] 发送失败: {e}")
            return False

    def send_batch(self, alerts: List[Alert]) -> bool:
        """批量发送"""
        if not alerts:
            return True

        # 合并告警
        combined = self._combine_alerts(alerts)
        return self.send(combined)

    def _get_color(self, severity: AlertSeverity) -> str:
        """获取颜色"""
        colors = {
            AlertSeverity.INFO: "#439FE0",
            AlertSeverity.WARNING: "warning",
            AlertSeverity.CRITICAL: "danger",
        }
        return colors.get(severity, "#439FE0")

    def _get_emoji(self, severity: AlertSeverity) -> str:
        """获取Emoji"""
        emojis = {
            AlertSeverity.INFO: "ℹ️",
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.CRITICAL: "🚨",
        }
        return emojis.get(severity, "📢")

    def _combine_alerts(self, alerts: List[Alert]) -> Alert:
        """合并告警"""
        if len(alerts) == 1:
            return alerts[0]

        # 找到最高严重级别
        severities = [a.severity for a in alerts]
        if AlertSeverity.CRITICAL in severities:
            max_severity = AlertSeverity.CRITICAL
        elif AlertSeverity.WARNING in severities:
            max_severity = AlertSeverity.WARNING
        else:
            max_severity = AlertSeverity.INFO

        return Alert(
            alert_id=f"combined_{int(time.time())}",
            name=f"聚合告警 ({len(alerts)}条)",
            severity=max_severity,
            summary=f"过去5分钟内有 {len(alerts)} 条告警",
            description="\n".join([f"• {a.name}: {a.summary}" for a in alerts[:10]]),
            starts_at=min(a.starts_at for a in alerts),
        )


class EmailNotifier:
    """邮件通知发送器"""

    def __init__(self, config: NotificationConfig):
        self.config = config

    def send(self, alert: Alert, recipients: List[str] = None) -> bool:
        """发送邮件"""
        recipients = recipients or self.config.email_to
        if not recipients:
            logger.warning("[EmailNotifier] 未配置收件人")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[{alert.severity.value.upper()}] {alert.name}"
            msg["From"] = self.config.email_from
            msg["To"] = ", ".join(recipients)

            # 纯文本版本
            text_content = self._generate_text_content(alert)
            msg.attach(MIMEText(text_content, "plain", "utf-8"))

            # HTML版本
            html_content = self._generate_html_content(alert)
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            # 发送
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                server.starttls()
                if self.config.smtp_user and self.config.smtp_password:
                    server.login(self.config.smtp_user, self.config.smtp_password)
                server.sendmail(self.config.email_from, recipients, msg.as_string())

            logger.info(f"[EmailNotifier] 邮件发送成功: {alert.name}")
            return True

        except Exception as e:
            logger.error(f"[EmailNotifier] 发送失败: {e}")
            return False

    def _generate_text_content(self, alert: Alert) -> str:
        """生成纯文本内容"""
        lines = [
            f"告警名称: {alert.name}",
            f"告警级别: {alert.severity.value.upper()}",
            f"告警状态: {alert.status}",
            "",
            f"摘要: {alert.summary}",
            "",
            f"详细描述:",
            alert.description,
            "",
            f"触发时间: {alert.starts_at.strftime('%Y-%m-%d %H:%M:%S')}",
        ]

        if alert.labels:
            lines.append("")
            lines.append("标签:")
            for k, v in alert.labels.items():
                lines.append(f"  {k}: {v}")

        lines.append("")
        lines.append("---")
        lines.append("西部量化可转债策略 V3.0 告警系统")

        return "\n".join(lines)

    def _generate_html_content(self, alert: Alert) -> str:
        """生成HTML内容"""
        severity_colors = {
            AlertSeverity.INFO: "#439FE0",
            AlertSeverity.WARNING: "#F0AD4E",
            AlertSeverity.CRITICAL: "#D9534F",
        }
        color = severity_colors.get(alert.severity, "#777")

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: {color}; color: white; padding: 20px; border-radius: 5px 5px 0 0;">
                <h2 style="margin: 0;">🚨 [{alert.severity.value.upper()}] {alert.name}</h2>
            </div>
            <div style="background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>状态</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{alert.status.upper()}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>摘要</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{alert.summary}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>时间</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{alert.starts_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
                    </tr>
                </table>
                <div style="margin-top: 20px;">
                    <strong>详细描述:</strong>
                    <p style="background-color: white; padding: 15px; border-radius: 5px; border: 1px solid #eee;">
                        {alert.description}
                    </p>
                </div>
            </div>
            <div style="text-align: center; color: #999; padding: 10px;">
                西部量化可转债策略 V3.0 告警系统
            </div>
        </body>
        </html>
        """

        return html


class WebhookNotifier:
    """Webhook通知发送器"""

    def __init__(self, url: str, headers: Dict[str, str] = None):
        self.url = url
        self.headers = headers or {}

    def send(self, alert: Alert) -> bool:
        """发送Webhook通知"""
        if not self.url:
            logger.warning("[WebhookNotifier] 未配置URL")
            return False

        payload = {
            "event": "alert",
            "data": alert.to_dict(),
            "timestamp": datetime.now().isoformat(),
        }

        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=self.headers,
                timeout=10,
            )
            return response.status_code in [200, 201, 202]
        except Exception as e:
            logger.error(f"[WebhookNotifier] 发送失败: {e}")
            return False


class SMSNotifier:
    """短信通知发送器"""

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key

    def send(self, alert: Alert, recipients: List[str]) -> bool:
        """发送短信"""
        if not self.api_url or not recipients:
            return False

        # 短信内容（限制长度）
        content = f"【西部策略】{alert.severity.value.upper()}:{alert.name[:50]}"
        if len(content) > 70:
            content = content[:67] + "..."

        try:
            for phone in recipients:
                payload = {
                    "phone": phone,
                    "content": content,
                    "api_key": self.api_key,
                }
                requests.post(self.api_url, json=payload, timeout=10)

            logger.info(f"[SMSNotifier] 短信发送成功: {alert.name}")
            return True
        except Exception as e:
            logger.error(f"[SMSNotifier] 发送失败: {e}")
            return False


# ============ 告警管理器 ============

class AlertManager:
    """告警管理器"""

    def __init__(self, config: NotificationConfig):
        self.config = config

        self._slack = SlackNotifier(config.slack_webhook_url, config.slack_channel)
        self._email = EmailNotifier(config)
        self._webhook = WebhookNotifier(config.webhook_url, config.webhook_headers)
        self._sms = SMSNotifier(config.sms_api_url, config.sms_api_key)

        # 告警缓存
        self._alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._lock = threading.Lock()

        # 聚合窗口
        self._pending_alerts: List[Alert] = []
        self._last_flush = time.time()

    def fire_alert(
        self,
        name: str,
        severity: AlertSeverity,
        summary: str,
        description: str,
        labels: Dict[str, str] = None,
        channels: List[NotificationChannel] = None,
    ) -> str:
        """触发告警"""
        alert_id = f"alert_{int(time.time() * 1000)}"

        alert = Alert(
            alert_id=alert_id,
            name=name,
            severity=severity,
            summary=summary,
            description=description,
            labels=labels or {},
            status="firing",
        )

        with self._lock:
            self._alerts[alert_id] = alert
            self._alert_history.append(alert)

            # 保留最近1000条历史
            if len(self._alert_history) > 1000:
                self._alert_history = self._alert_history[-1000:]

        # 发送通知
        channels = channels or [NotificationChannel.SLACK, NotificationChannel.EMAIL]
        self._send_notification(alert, channels)

        logger.info(f"[AlertManager] 触发告警: {name} [{severity.value}]")

        return alert_id

    def resolve_alert(self, alert_id: str) -> bool:
        """解决告警"""
        with self._lock:
            if alert_id not in self._alerts:
                return False

            alert = self._alerts[alert_id]
            alert.status = "resolved"
            alert.ends_at = datetime.now()

            # 发送解决通知
            self._slack.send(alert)

            del self._alerts[alert_id]

        logger.info(f"[AlertManager] 解决告警: {alert_id}")
        return True

    def _send_notification(self, alert: Alert, channels: List[NotificationChannel]):
        """发送通知"""
        for channel in channels:
            try:
                if channel == NotificationChannel.SLACK:
                    self._slack.send(alert)
                elif channel == NotificationChannel.EMAIL:
                    self._email.send(alert)
                elif channel == NotificationChannel.WEBHOOK:
                    self._webhook.send(alert)
                elif channel == NotificationChannel.SMS:
                    if alert.severity == AlertSeverity.CRITICAL:
                        self._sms.send(alert, self.config.sms_recipients)
            except Exception as e:
                logger.error(f"[AlertManager] 通知发送失败 [{channel.value}]: {e}")

    def get_active_alerts(self) -> List[Alert]:
        """获取活跃告警"""
        with self._lock:
            return list(self._alerts.values())

    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """获取告警历史"""
        with self._lock:
            return self._alert_history[-limit:]


# ============ 告警模板 ============

class AlertTemplates:
    """告警模板"""

    @staticmethod
    def service_down(service_name: str, instance: str) -> Dict:
        """服务宕机"""
        return {
            "name": "ServiceDown",
            "severity": AlertSeverity.CRITICAL,
            "summary": f"服务 {service_name} 不可用",
            "description": f"服务 {service_name} 在实例 {instance} 上已停止响应",
            "labels": {"service": service_name, "instance": instance},
        }

    @staticmethod
    def high_error_rate(service_name: str, error_rate: float) -> Dict:
        """错误率过高"""
        severity = AlertSeverity.CRITICAL if error_rate > 0.1 else AlertSeverity.WARNING
        return {
            "name": "HighErrorRate",
            "severity": severity,
            "summary": f"服务 {service_name} 错误率过高",
            "description": f"错误率达到 {error_rate*100:.2f}%",
            "labels": {"service": service_name, "error_rate": str(error_rate)},
        }

    @staticmethod
    def drawdown_warning(portfolio_id: str, drawdown: float) -> Dict:
        """回撤预警"""
        severity = AlertSeverity.CRITICAL if drawdown > 0.1 else AlertSeverity.WARNING
        return {
            "name": "DrawdownWarning",
            "severity": severity,
            "summary": f"组合 {portfolio_id} 回撤预警",
            "description": f"当前回撤 {drawdown*100:.2f}%，建议检查持仓",
            "labels": {"portfolio_id": portfolio_id, "drawdown": str(drawdown)},
        }

    @staticmethod
    def data_source_down(source: str) -> Dict:
        """数据源异常"""
        return {
            "name": "DataSourceDown",
            "severity": AlertSeverity.CRITICAL,
            "summary": f"数据源 {source} 不可用",
            "description": f"数据源 {source} 连接失败，请检查网络和认证配置",
            "labels": {"source": source},
        }


# ============ 便捷函数 ============

def create_alert_manager(config: NotificationConfig = None) -> AlertManager:
    """创建告警管理器"""
    config = config or NotificationConfig()
    return AlertManager(config)


def send_slack_alert(webhook_url: str, channel: str, alert: Alert) -> bool:
    """发送Slack告警"""
    notifier = SlackNotifier(webhook_url, channel)
    return notifier.send(alert)
