import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Callable, Awaitable, Any
from collections import defaultdict

from app.models.alert import AlertCondition, AlertTrigger, AlertType
from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


class AlertEngine:
    """告警引擎 - 监控行情并触发告警，支持持久化存储"""

    def __init__(self, storage=None):
        self._alerts: dict[str, AlertCondition] = {}
        self._callbacks: list[Callable[[AlertTrigger], Awaitable[None]]] = []
        self._triggered: dict[str, datetime] = {}
        self._storage = storage
        self._cooldown_seconds = 300
        if storage:
            self._load_from_storage()

    def add_alert(self, alert: AlertCondition) -> None:
        if not alert.id:
            alert.id = uuid.uuid4().hex[:12]
        alert.updated_at = datetime.now()
        self._alerts[alert.id] = alert
        self._save_to_storage()

    def update_alert(self, alert_id: str, updates: dict) -> Optional[AlertCondition]:
        alert = self._alerts.get(alert_id)
        if not alert:
            return None
        for k, v in updates.items():
            if hasattr(alert, k):
                setattr(alert, k, v)
        alert.updated_at = datetime.now()
        self._save_to_storage()
        return alert

    def remove_alert(self, alert_id: str) -> bool:
        if alert_id not in self._alerts:
            return False
        del self._alerts[alert_id]
        self._save_to_storage()
        return True

    def get_alerts(self, code: Optional[str] = None, alert_type: Optional[AlertType] = None) -> list[AlertCondition]:
        alerts = list(self._alerts.values())
        if code:
            alerts = [a for a in alerts if a.code == code]
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        return alerts

    def get_alert(self, alert_id: str) -> Optional[AlertCondition]:
        return self._alerts.get(alert_id)

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
            # 检查抑制时间
            if alert_id in self._triggered:
                elapsed = (now - self._triggered[alert_id]).total_seconds()
                suppress = alert.suppress_duration if alert.suppress_duration > 0 else self._cooldown_seconds
                if elapsed < suppress:
                    continue
            triggered = self._check_condition(alert, quote)
            if triggered:
                triggered.rule_id = alert_id
                self._triggered[alert_id] = now
                triggers.append(triggered)
                self._record_trigger(triggered)

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
        at = alert.alert_type
        if at == AlertType.PRICE_ABOVE:
            if quote.price is not None and quote.price > alert.threshold:
                value = quote.price
        elif at == AlertType.PRICE_BELOW:
            if quote.price is not None and quote.price < alert.threshold:
                value = quote.price
        elif at == AlertType.PREMIUM_ABOVE:
            if quote.premium_ratio is not None and quote.premium_ratio > alert.threshold:
                value = quote.premium_ratio
        elif at == AlertType.PREMIUM_BELOW:
            if quote.premium_ratio is not None and quote.premium_ratio < alert.threshold:
                value = quote.premium_ratio
        elif at == AlertType.DUAL_LOW_BELOW:
            if quote.dual_low is not None and quote.dual_low < alert.threshold:
                value = quote.dual_low
        elif at == AlertType.YTM_ABOVE:
            if quote.ytm is not None and quote.ytm > alert.threshold:
                value = quote.ytm
        elif at == AlertType.CHANGE_PCT_ABOVE:
            if quote.change_pct is not None and quote.change_pct > alert.threshold:
                value = quote.change_pct
        elif at == AlertType.CHANGE_PCT_BELOW:
            if quote.change_pct is not None and quote.change_pct < alert.threshold:
                value = quote.change_pct
        elif at == AlertType.TURNOVER_RATE_ABOVE:
            if quote.turnover_rate is not None and quote.turnover_rate > alert.threshold:
                value = quote.turnover_rate
        elif at == AlertType.IS_CALLED:
            if quote.is_called:
                value = 1.0
        elif at == AlertType.FORCED_CALL_DAYS_BELOW:
            if quote.forced_call_days is not None and quote.forced_call_days <= alert.threshold:
                value = quote.forced_call_days
        elif at == AlertType.VOLUME_ABOVE:
            if quote.volume is not None and quote.volume > alert.threshold:
                value = quote.volume
        elif at == AlertType.VOLUME_BELOW:
            if quote.volume is not None and quote.volume < alert.threshold:
                value = quote.volume
        elif at == AlertType.RATING_DOWNGRADE:
            if quote.rating_score is not None and quote.rating_score < alert.threshold:
                value = quote.rating_score
        if value is not None:
            msg = self._build_message(alert, quote, value)
            return AlertTrigger(
                rule_id=alert.id,
                code=quote.code,
                name=quote.name,
                alert_type=alert.alert_type,
                threshold=alert.threshold,
                current_value=value,
                message=msg,
            )
        return None

    @staticmethod
    def _build_message(alert: AlertCondition, quote: ConvertibleQuote, value: float) -> str:
        """构建告警消息"""
        at = alert.alert_type
        type_labels = {
            AlertType.PRICE_ABOVE: "价格",
            AlertType.PRICE_BELOW: "价格",
            AlertType.PREMIUM_ABOVE: "溢价率",
            AlertType.PREMIUM_BELOW: "溢价率",
            AlertType.DUAL_LOW_BELOW: "双低值",
            AlertType.YTM_ABOVE: "到期收益率",
            AlertType.CHANGE_PCT_ABOVE: "涨跌幅",
            AlertType.CHANGE_PCT_BELOW: "涨跌幅",
            AlertType.TURNOVER_RATE_ABOVE: "换手率",
            AlertType.IS_CALLED: "强赎状态",
            AlertType.FORCED_CALL_DAYS_BELOW: "强赎倒计时",
            AlertType.VOLUME_ABOVE: "成交额",
            AlertType.VOLUME_BELOW: "成交额",
            AlertType.RATING_DOWNGRADE: "评级评分",
        }
        label = type_labels.get(at, "指标")
        operators = {
            AlertType.PRICE_ABOVE: ">",
            AlertType.PREMIUM_ABOVE: ">",
            AlertType.YTM_ABOVE: ">",
            AlertType.CHANGE_PCT_ABOVE: ">",
            AlertType.TURNOVER_RATE_ABOVE: ">",
            AlertType.VOLUME_ABOVE: ">",
            AlertType.PRICE_BELOW: "<",
            AlertType.PREMIUM_BELOW: "<",
            AlertType.DUAL_LOW_BELOW: "<",
            AlertType.CHANGE_PCT_BELOW: "<",
            AlertType.FORCED_CALL_DAYS_BELOW: "<",
            AlertType.VOLUME_BELOW: "<",
            AlertType.RATING_DOWNGRADE: "<",
            AlertType.IS_CALLED: "=",
        }
        op = operators.get(at, "变化")
        if at == AlertType.IS_CALLED:
            return f"{quote.name}({quote.code}) 已公告强赎"
        return f"{quote.name}({quote.code}) {label} {op} {alert.threshold}: 当前 {value:.2f}"

    def acknowledge_alert(self, trigger_id: str) -> bool:
        """确认告警"""
        if not self._storage:
            return False
        try:
            self._storage.conn.execute(
                "UPDATE alert_triggers SET acknowledged=1, acknowledged_at=? WHERE id=?",
                (datetime.now(), trigger_id),
            )
            return True
        except Exception as e:
            logger.warning(f"[AlertEngine] Acknowledge failed: {e}")
            return False

    def resolve_alert(self, trigger_id: str) -> bool:
        """解决告警"""
        if not self._storage:
            return False
        try:
            self._storage.conn.execute(
                "UPDATE alert_triggers SET resolved=1, resolved_at=? WHERE id=?",
                (datetime.now(), trigger_id),
            )
            return True
        except Exception as e:
            logger.warning(f"[AlertEngine] Resolve failed: {e}")
            return False

    def get_trigger_history(self, limit: int = 100, acknowledged: Optional[bool] = None, resolved: Optional[bool] = None) -> list[dict]:
        """获取触发历史"""
        if not self._storage:
            return []
        try:
            sql = "SELECT * FROM alert_triggers WHERE 1=1"
            params = []
            if acknowledged is not None:
                sql += " AND acknowledged = ?"
                params.append(1 if acknowledged else 0)
            if resolved is not None:
                sql += " AND resolved = ?"
                params.append(1 if resolved else 0)
            sql += " ORDER BY triggered_at DESC LIMIT ?"
            params.append(limit)
            cursor = self._storage.conn.execute(sql, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"[AlertEngine] History query failed: {e}")
            return []

    def clear_triggered(self) -> None:
        self._triggered.clear()

    def _load_from_storage(self):
        if not self._storage:
            return
        try:
            self._init_alert_tables()
            cursor = self._storage.conn.execute("SELECT id, code, name, alert_type, threshold, enabled, created_at, updated_at, description, channels, suppress_duration, tags FROM alert_rules")
            for row in cursor.fetchall():
                channels = row[9] if isinstance(row[9], list) else []
                tags = row[11] if isinstance(row[11], list) else []
                alert = AlertCondition(
                    id=row[0], code=row[1], name=row[2], alert_type=AlertType(row[3]),
                    threshold=row[4], enabled=bool(row[5]), created_at=row[6], updated_at=row[7],
                    description=row[8] or "", channels=channels, suppress_duration=row[10] or 300,
                    tags=tags,
                )
                self._alerts[alert.id] = alert
            logger.info(f"[AlertEngine] Loaded {len(self._alerts)} rules from storage")
        except Exception as e:
            logger.warning(f"[AlertEngine] Load from storage failed: {e}")

    def _save_to_storage(self):
        if not self._storage:
            return
        try:
            self._init_alert_tables()
            for alert in self._alerts.values():
                self._storage.conn.execute(
                    """INSERT OR REPLACE INTO alert_rules
                    (id, code, name, alert_type, threshold, enabled, created_at, updated_at, description, channels, suppress_duration, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (alert.id, alert.code, alert.name, alert.alert_type.value, alert.threshold,
                     1 if alert.enabled else 0, alert.created_at, alert.updated_at,
                     alert.description, alert.channels, alert.suppress_duration, alert.tags),
                )
        except Exception as e:
            logger.warning(f"[AlertEngine] Save to storage failed: {e}")

    def _record_trigger(self, trigger: AlertTrigger):
        if not self._storage:
            return
        try:
            self._init_alert_tables()
            self._storage.conn.execute(
                """INSERT INTO alert_triggers
                (id, rule_id, code, name, alert_type, threshold, current_value, triggered_at, acknowledged, resolved, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (trigger.id, trigger.rule_id, trigger.code, trigger.name, trigger.alert_type.value,
                 trigger.threshold, trigger.current_value, trigger.triggered_at,
                 1 if trigger.acknowledged else 0, 1 if trigger.resolved else 0, trigger.message),
            )
        except Exception as e:
            logger.warning(f"[AlertEngine] Record trigger failed: {e}")

    def _init_alert_tables(self):
        if not self._storage:
            return
        try:
            self._storage.conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id VARCHAR PRIMARY KEY,
                    code VARCHAR,
                    name VARCHAR,
                    alert_type VARCHAR,
                    threshold DOUBLE,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    description VARCHAR,
                    channels JSON,
                    suppress_duration INTEGER DEFAULT 300,
                    tags JSON
                )
            """)
            self._storage.conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_triggers (
                    id VARCHAR PRIMARY KEY,
                    rule_id VARCHAR,
                    code VARCHAR,
                    name VARCHAR,
                    alert_type VARCHAR,
                    threshold DOUBLE,
                    current_value DOUBLE,
                    triggered_at TIMESTAMP,
                    acknowledged BOOLEAN DEFAULT 0,
                    acknowledged_at TIMESTAMP,
                    resolved BOOLEAN DEFAULT 0,
                    resolved_at TIMESTAMP,
                    message VARCHAR
                )
            """)
        except Exception as e:
            logger.warning(f"[AlertEngine] Init tables failed: {e}")
