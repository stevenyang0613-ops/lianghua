import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable
from collections import defaultdict

from app.models.alert import AlertCondition, AlertTrigger, AlertType
from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


class AlertEngine:
    """告警引擎 - 监控行情并触发告警"""

    def __init__(self):
        self._alerts: dict[str, AlertCondition] = {}
        self._callbacks: list[Callable[[AlertTrigger], Awaitable[None]]] = []
        self._triggered: dict[str, datetime] = {}
        self._cooldown_seconds = 300

    def add_alert(self, alert: AlertCondition) -> None:
        self._alerts[f"{alert.code}_{alert.alert_type}"] = alert

    def remove_alert(self, alert_id: str) -> None:
        self._alerts.pop(alert_id, None)

    def get_alerts(self) -> list[AlertCondition]:
        return list(self._alerts.values())

    def subscribe(self, callback: Callable[[AlertTrigger], Awaitable[None]]) -> None:
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[AlertTrigger], Awaitable[None]]) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def check_quotes(self, quotes: list[ConvertibleQuote]) -> list[AlertTrigger]:
        """检查行情并返回触发的告警"""
        triggers = []
        now = datetime.now()
        quote_map = {q.code: q for q in quotes}

        for alert_id, alert in self._alerts.items():
            if not alert.enabled:
                continue

            quote = quote_map.get(alert.code)
            if not quote:
                continue

            if alert_id in self._triggered:
                elapsed = (now - self._triggered[alert_id]).total_seconds()
                if elapsed < self._cooldown_seconds:
                    continue

            triggered = self._check_condition(alert, quote)
            if triggered:
                self._triggered[alert_id] = now
                triggers.append(triggered)

        for trigger in triggers:
            for callback in self._callbacks:
                try:
                    await callback(trigger)
                except Exception as e:
                    logger.warning(f"[AlertEngine] Callback error: {e}")

        return triggers

    def _check_condition(self, alert: AlertCondition, quote: ConvertibleQuote) -> Optional[AlertTrigger]:
        """检查单个条件"""
        value = None

        if alert.alert_type == AlertType.PRICE_ABOVE:
            if quote.price > alert.threshold:
                value = quote.price
        elif alert.alert_type == AlertType.PRICE_BELOW:
            if quote.price < alert.threshold:
                value = quote.price
        elif alert.alert_type == AlertType.PREMIUM_ABOVE:
            if quote.premium_ratio > alert.threshold:
                value = quote.premium_ratio
        elif alert.alert_type == AlertType.PREMIUM_BELOW:
            if quote.premium_ratio < alert.threshold:
                value = quote.premium_ratio
        elif alert.alert_type == AlertType.DUAL_LOW_BELOW:
            if quote.dual_low < alert.threshold:
                value = quote.dual_low
        elif alert.alert_type == AlertType.YTM_ABOVE:
            if quote.ytm > alert.threshold:
                value = quote.ytm

        if value is not None:
            return AlertTrigger(
                code=quote.code,
                name=quote.name,
                alert_type=alert.alert_type,
                threshold=alert.threshold,
                current_value=value,
            )
        return None

    def clear_triggered(self) -> None:
        """清除所有触发记录"""
        self._triggered.clear()
