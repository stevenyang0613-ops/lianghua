"""松岗量化可转债策略 V3.0 监控告警模块

支持:
- 钉钉机器人通知
- 企业微信机器人通知
- 邮件通知
- Webhook通知
- 告警规则引擎
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Callable, Any
from enum import Enum
from abc import ABC, abstractmethod
import json
import logging
import hashlib
import hmac
import base64
import time
import urllib.parse

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AlertLevel(str, Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    """告警类别"""
    TRADE = "trade"           # 交易信号
    RISK = "risk"             # 风险预警
    SYSTEM = "system"         # 系统状态
    PERFORMANCE = "performance"  # 绩效通知
    POSITION = "position"     # 持仓变动
    MARKET = "market"         # 市场动态


# ============ 数据类型 ============

@dataclass
class Alert:
    """告警消息"""
    title: str
    content: str
    level: AlertLevel
    category: AlertCategory
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "level": self.level.value,
            "category": self.category.value,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        level_emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }
        emoji = level_emoji.get(self.level, "📌")

        md = f"""## {emoji} {self.title}

**级别**: {self.level.value.upper()}
**类别**: {self.category.value}
**时间**: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

{self.content}
"""
        if self.metadata:
            md += "\n**详情**:\n"
            for k, v in self.metadata.items():
                md += f"- {k}: {v}\n"

        return md


# ============ 通知渠道接口 ============

class NotificationChannel(ABC):
    """通知渠道抽象类"""

    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """发送通知"""
        pass

    @abstractmethod
    def get_channel_name(self) -> str:
        """获取渠道名称"""
        pass


# ============ 钉钉通知 ============

class DingTalkChannel(NotificationChannel):
    """钉钉机器人通知"""

    def __init__(
        self,
        webhook: str,
        secret: str = "",
        at_mobiles: List[str] = None,
        at_all: bool = False,
    ):
        """初始化

        Args:
            webhook: Webhook地址
            secret: 加签密钥
            at_mobiles: @手机号列表
            at_all: 是否@所有人
        """
        self.webhook = webhook
        self.secret = secret
        self.at_mobiles = at_mobiles or []
        self.at_all = at_all

    def get_channel_name(self) -> str:
        return "dingtalk"

    def send(self, alert: Alert) -> bool:
        """发送钉钉消息"""
        try:
            import requests

            # 构建URL
            url = self.webhook
            if self.secret:
                timestamp = str(round(time.time() * 1000))
                sign = self._generate_sign(timestamp)
                url = f"{self.webhook}&timestamp={timestamp}&sign={sign}"

            # 构建消息
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "title": alert.title,
                    "text": alert.to_markdown(),
                },
                "at": {
                    "atMobiles": self.at_mobiles,
                    "isAtAll": self.at_all,
                }
            }

            response = requests.post(url, json=message, timeout=10)
            result = response.json()

            if result.get("errcode") == 0:
                logger.info(f"[DingTalk] 发送成功: {alert.title}")
                return True
            else:
                logger.error(f"[DingTalk] 发送失败: {result}")
                return False

        except ImportError:
            logger.warning("[DingTalk] requests未安装")
            return False
        except Exception as e:
            logger.error(f"[DingTalk] 发送异常: {e}")
            return False

    def _generate_sign(self, timestamp: str) -> str:
        """生成签名"""
        if not self.secret:
            return ""

        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()

        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return sign


# ============ 企业微信通知 ============

class WeChatWorkChannel(NotificationChannel):
    """企业微信机器人通知"""

    def __init__(
        self,
        webhook: str,
        mentioned_list: List[str] = None,
        mentioned_mobile_list: List[str] = None,
    ):
        """初始化

        Args:
            webhook: Webhook地址
            mentioned_list: @用户ID列表
            mentioned_mobile_list: @手机号列表
        """
        self.webhook = webhook
        self.mentioned_list = mentioned_list or []
        self.mentioned_mobile_list = mentioned_mobile_list or []

    def get_channel_name(self) -> str:
        return "wechat_work"

    def send(self, alert: Alert) -> bool:
        """发送企业微信消息"""
        try:
            import requests

            # 构建消息
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "content": alert.to_markdown(),
                    "mentioned_list": self.mentioned_list,
                    "mentioned_mobile_list": self.mentioned_mobile_list,
                }
            }

            response = requests.post(self.webhook, json=message, timeout=10)
            result = response.json()

            if result.get("errcode") == 0:
                logger.info(f"[WeChatWork] 发送成功: {alert.title}")
                return True
            else:
                logger.error(f"[WeChatWork] 发送失败: {result}")
                return False

        except ImportError:
            logger.warning("[WeChatWork] requests未安装")
            return False
        except Exception as e:
            logger.error(f"[WeChatWork] 发送异常: {e}")
            return False


# ============ 邮件通知 ============

class EmailChannel(NotificationChannel):
    """邮件通知"""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: List[str],
    ):
        """初始化

        Args:
            smtp_server: SMTP服务器
            smtp_port: SMTP端口
            username: 用户名
            password: 密码
            from_addr: 发件人地址
            to_addrs: 收件人地址列表
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs

    def get_channel_name(self) -> str:
        return "email"

    def send(self, alert: Alert) -> bool:
        """发送邮件"""
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            # 构建邮件
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[{alert.level.value.upper()}] {alert.title}"
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)

            # 纯文本内容
            text_content = f"""
{alert.title}
级别: {alert.level.value}
类别: {alert.category.value}
时间: {alert.timestamp}

{alert.content}
"""
            msg.attach(MIMEText(text_content, "plain", "utf-8"))

            # HTML内容
            html_content = f"""
<html>
<body>
<h2>{alert.title}</h2>
<p><strong>级别:</strong> {alert.level.value}</p>
<p><strong>类别:</strong> {alert.category.value}</p>
<p><strong>时间:</strong> {alert.timestamp}</p>
<hr>
<p>{alert.content}</p>
</body>
</html>
"""
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            # 发送
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.from_addr, self.to_addrs, msg.as_string())

            logger.info(f"[Email] 发送成功: {alert.title}")
            return True

        except Exception as e:
            logger.error(f"[Email] 发送异常: {e}")
            return False


# ============ Webhook通知 ============

class WebhookChannel(NotificationChannel):
    """通用Webhook通知"""

    def __init__(self, url: str, headers: Dict[str, str] = None):
        """初始化

        Args:
            url: Webhook地址
            headers: 请求头
        """
        self.url = url
        self.headers = headers or {}

    def get_channel_name(self) -> str:
        return "webhook"

    def send(self, alert: Alert) -> bool:
        """发送Webhook"""
        try:
            import requests

            response = requests.post(
                self.url,
                json=alert.to_dict(),
                headers=self.headers,
                timeout=10,
            )

            if response.status_code == 200:
                logger.info(f"[Webhook] 发送成功: {alert.title}")
                return True
            else:
                logger.error(f"[Webhook] 发送失败: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"[Webhook] 发送异常: {e}")
            return False


# ============ 控制台通知 ============

class ConsoleChannel(NotificationChannel):
    """控制台输出通知"""

    def get_channel_name(self) -> str:
        return "console"

    def send(self, alert: Alert) -> bool:
        """输出到控制台"""
        level_colors = {
            AlertLevel.INFO: "\033[94m",      # 蓝色
            AlertLevel.WARNING: "\033[93m",   # 黄色
            AlertLevel.ERROR: "\033[91m",     # 红色
            AlertLevel.CRITICAL: "\033[95m",  # 紫色
        }
        reset = "\033[0m"
        color = level_colors.get(alert.level, "")

        print(f"\n{color}{'='*60}{reset}")
        print(f"{color}[{alert.level.value.upper()}] {alert.title}{reset}")
        print(f"时间: {alert.timestamp}")
        print(f"类别: {alert.category.value}")
        print(f"{color}{'='*60}{reset}")
        print(alert.content)
        print(f"{color}{'='*60}{reset}\n")

        return True


# ============ 告警管理器 ============

class AlertManager:
    """告警管理器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._channels: List[NotificationChannel] = []
        self._rules: List[Callable] = []
        self._history: List[Alert] = []
        self._max_history = 1000

        # 默认添加控制台通道
        self._channels.append(ConsoleChannel())

    def add_channel(self, channel: NotificationChannel):
        """添加通知渠道"""
        self._channels.append(channel)
        logger.info(f"[AlertManager] 添加通知渠道: {channel.get_channel_name()}")

    def add_rule(self, rule: Callable[[Alert], bool]):
        """添加告警规则

        Args:
            rule: 规则函数，返回True则发送通知
        """
        self._rules.append(rule)

    def send_alert(self, alert: Alert) -> bool:
        """发送告警

        Args:
            alert: 告警消息

        Returns:
            是否发送成功
        """
        # 检查规则
        should_send = True
        for rule in self._rules:
            if not rule(alert):
                should_send = False
                break

        if not should_send:
            logger.debug(f"[AlertManager] 告警被规则拦截: {alert.title}")
            return False

        # 记录历史
        self._history.append(alert)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # 发送到所有渠道
        success = False
        for channel in self._channels:
            try:
                if channel.send(alert):
                    success = True
            except Exception as e:
                logger.error(f"[AlertManager] 渠道{channel.get_channel_name()}发送失败: {e}")

        return success

    # ============ 便捷方法 ============

    def info(self, title: str, content: str, category: AlertCategory = AlertCategory.SYSTEM, **metadata):
        """发送INFO告警"""
        self.send_alert(Alert(title, content, AlertLevel.INFO, category, metadata=metadata))

    def warning(self, title: str, content: str, category: AlertCategory = AlertCategory.SYSTEM, **metadata):
        """发送WARNING告警"""
        self.send_alert(Alert(title, content, AlertLevel.WARNING, category, metadata=metadata))

    def error(self, title: str, content: str, category: AlertCategory = AlertCategory.SYSTEM, **metadata):
        """发送ERROR告警"""
        self.send_alert(Alert(title, content, AlertLevel.ERROR, category, metadata=metadata))

    def critical(self, title: str, content: str, category: AlertCategory = AlertCategory.SYSTEM, **metadata):
        """发送CRITICAL告警"""
        self.send_alert(Alert(title, content, AlertLevel.CRITICAL, category, metadata=metadata))

    def trade_signal(self, title: str, content: str, **metadata):
        """发送交易信号告警"""
        self.info(title, content, AlertCategory.TRADE, **metadata)

    def risk_warning(self, title: str, content: str, level: AlertLevel = AlertLevel.WARNING, **metadata):
        """发送风险预警"""
        self.send_alert(Alert(title, content, level, AlertCategory.RISK, metadata=metadata))

    def daily_report(self, title: str, content: str, **metadata):
        """发送每日报告"""
        self.info(title, content, AlertCategory.PERFORMANCE, **metadata)

    def get_history(self, limit: int = 100) -> List[Alert]:
        """获取告警历史"""
        return self._history[-limit:]

    def clear_history(self):
        """清空历史"""
        self._history.clear()


def get_alert_manager() -> AlertManager:
    """获取告警管理器单例"""
    return AlertManager()


# ============ 预定义告警 ============

def alert_trade_signal(code: str, name: str, action: str, quantity: int, price: float, reason: str):
    """交易信号告警"""
    manager = get_alert_manager()
    manager.trade_signal(
        title=f"交易信号: {action.upper()} {name}",
        content=f"""
**代码**: {code}
**名称**: {name}
**动作**: {action}
**数量**: {quantity}张
**价格**: {price:.2f}
**原因**: {reason}
""",
        code=code,
        action=action,
        quantity=quantity,
        price=price,
    )


def alert_risk_drawdown(drawdown: float, threshold: float):
    """回撤预警"""
    manager = get_alert_manager()
    level = AlertLevel.CRITICAL if drawdown >= threshold else AlertLevel.WARNING
    manager.risk_warning(
        title=f"回撤预警: {drawdown*100:.2f}%",
        content=f"当前回撤{drawdown*100:.2f}%，阈值{threshold*100:.2f}%",
        level=level,
        drawdown=drawdown,
        threshold=threshold,
    )


def alert_position_limit(code: str, name: str, current_pct: float, limit_pct: float):
    """持仓超限告警"""
    manager = get_alert_manager()
    manager.warning(
        title=f"持仓超限: {name}",
        content=f"{name}({code})仓位{current_pct*100:.2f}%超过限制{limit_pct*100:.2f}%",
        category=AlertCategory.POSITION,
        code=code,
        current_pct=current_pct,
        limit_pct=limit_pct,
    )


def alert_daily_summary(aum: float, daily_return: float, position_count: int):
    """每日汇总告警"""
    manager = get_alert_manager()
    return_emoji = "📈" if daily_return >= 0 else "📉"
    manager.daily_report(
        title=f"{return_emoji} 每日报告 {date.today()}",
        content=f"""
**净值**: {aum:.2f}万
**日收益**: {daily_return*100:.2f}%
**持仓数**: {position_count}只
""",
        aum=aum,
        daily_return=daily_return,
        position_count=position_count,
    )
