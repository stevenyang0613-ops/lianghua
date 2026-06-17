"""松岗量化可转债策略 V3.0 合规与审计模块

功能:
- 审计日志
- 交易合规检查
- 监管报告生成
- 合规规则引擎
- 风险限额管理
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import json
import numpy as np
import hashlib
import os

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AuditEventType(str, Enum):
    """审计事件类型"""
    TRADE = "trade"               # 交易
    ORDER = "order"               # 订单
    SIGNAL = "signal"             # 信号
    POSITION = "position"         # 持仓
    CASH = "cash"                 # 资金
    CONFIG = "config"             # 配置
    LOGIN = "login"               # 登录
    PERMISSION = "permission"     # 权限
    RISK = "risk"                 # 风控
    COMPLIANCE = "compliance"     # 合规


class ComplianceStatus(str, Enum):
    """合规状态"""
    PASS = "pass"
    WARNING = "warning"
    VIOLATION = "violation"
    BLOCKED = "blocked"


class ReportType(str, Enum):
    """报告类型"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


# ============ 数据模型 ============

@dataclass
class AuditEvent:
    """审计事件"""
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    user_id: str
    ip_address: str
    action: str
    resource: str
    details: Dict[str, Any] = field(default_factory=dict)
    before_state: Dict[str, Any] = None
    after_state: Dict[str, Any] = None
    status: str = "success"
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "ip_address": self.ip_address,
            "action": self.action,
            "resource": self.resource,
            "details": self.details,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "status": self.status,
            "error_message": self.error_message,
        }

    def compute_hash(self) -> str:
        """计算哈希值"""
        data = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(data.encode()).hexdigest()


@dataclass
class ComplianceRule:
    """合规规则"""
    rule_id: str
    name: str
    description: str
    rule_type: str  # position_limit, trade_limit, holding_period, etc.
    parameters: Dict[str, Any]
    severity: str  # info, warning, error, critical
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "rule_type": self.rule_type,
            "parameters": self.parameters,
            "severity": self.severity,
            "enabled": self.enabled,
        }


@dataclass
class ComplianceCheckResult:
    """合规检查结果"""
    rule_id: str
    rule_name: str
    status: ComplianceStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


# ============ 审计日志管理器 ============

class AuditLogger:
    """审计日志管理器"""

    def __init__(self, log_dir: str = "logs/audit"):
        self.log_dir = log_dir
        self._events: List[AuditEvent] = []
        self._enabled = True

        os.makedirs(log_dir, exist_ok=True)

    def log_event(
        self,
        event_type: AuditEventType,
        user_id: str,
        action: str,
        resource: str,
        ip_address: str = "0.0.0.0",
        details: Dict = None,
        before_state: Dict = None,
        after_state: Dict = None,
        status: str = "success",
        error_message: str = "",
    ) -> AuditEvent:
        """记录审计事件"""
        event_id = f"{event_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        event = AuditEvent(
            event_id=event_id,
            event_type=event_type,
            timestamp=datetime.now(),
            user_id=user_id,
            ip_address=ip_address,
            action=action,
            resource=resource,
            details=details or {},
            before_state=before_state,
            after_state=after_state,
            status=status,
            error_message=error_message,
        )

        self._events.append(event)

        # 写入文件
        if self._enabled:
            self._write_event(event)

        logger.debug(f"[Audit] {event_type.value}: {action} on {resource} by {user_id}")

        return event

    def _write_event(self, event: AuditEvent):
        """写入事件到文件"""
        date_str = event.timestamp.strftime("%Y-%m-%d")
        log_file = os.path.join(self.log_dir, f"audit_{date_str}.jsonl")

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + '\n')

    def log_trade(
        self,
        user_id: str,
        trade: Dict,
        ip_address: str = "0.0.0.0",
    ):
        """记录交易"""
        return self.log_event(
            event_type=AuditEventType.TRADE,
            user_id=user_id,
            action="execute_trade",
            resource=f"trade/{trade.get('code', '')}",
            ip_address=ip_address,
            details=trade,
        )

    def log_order(
        self,
        user_id: str,
        order: Dict,
        action: str,
        ip_address: str = "0.0.0.0",
    ):
        """记录订单"""
        return self.log_event(
            event_type=AuditEventType.ORDER,
            user_id=user_id,
            action=action,
            resource=f"order/{order.get('order_id', '')}",
            ip_address=ip_address,
            details=order,
        )

    def log_position_change(
        self,
        user_id: str,
        code: str,
        before: Dict,
        after: Dict,
        ip_address: str = "0.0.0.0",
    ):
        """记录持仓变更"""
        return self.log_event(
            event_type=AuditEventType.POSITION,
            user_id=user_id,
            action="position_change",
            resource=f"position/{code}",
            ip_address=ip_address,
            before_state=before,
            after_state=after,
        )

    def log_config_change(
        self,
        user_id: str,
        config_key: str,
        old_value: Any,
        new_value: Any,
        ip_address: str = "0.0.0.0",
    ):
        """记录配置变更"""
        return self.log_event(
            event_type=AuditEventType.CONFIG,
            user_id=user_id,
            action="config_change",
            resource=f"config/{config_key}",
            ip_address=ip_address,
            before_state={"value": old_value},
            after_state={"value": new_value},
        )

    def query_events(
        self,
        start_time: datetime = None,
        end_time: datetime = None,
        event_type: AuditEventType = None,
        user_id: str = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """查询事件"""
        events = self._events

        if start_time:
            events = [e for e in events if e.timestamp >= start_time]
        if end_time:
            events = [e for e in events if e.timestamp <= end_time]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if user_id:
            events = [e for e in events if e.user_id == user_id]

        return events[-limit:]

    def export_events(
        self,
        start_date: date,
        end_date: date,
        format: str = "json",
    ) -> str:
        """导出事件"""
        events = self.query_events(
            start_time=datetime.combine(start_date, datetime.min.time()),
            end_time=datetime.combine(end_date, datetime.max.time()),
        )

        if format == "json":
            return json.dumps([e.to_dict() for e in events], indent=2)
        elif format == "csv":
            import pandas as pd
            df = pd.DataFrame([e.to_dict() for e in events])
            return df.to_csv(index=False)

        return ""


# ============ 合规检查引擎 ============

class ComplianceEngine:
    """合规检查引擎"""

    def __init__(self):
        self._rules: Dict[str, ComplianceRule] = {}
        self._load_default_rules()

    def _load_default_rules(self):
        """加载默认规则"""
        default_rules = [
            ComplianceRule(
                rule_id="position_limit_single",
                name="单只持仓限制",
                description="单只转债持仓不超过组合净值的5%",
                rule_type="position_limit",
                parameters={"max_weight": 0.05},
                severity="error",
            ),
            ComplianceRule(
                rule_id="position_limit_total",
                name="总持仓限制",
                description="总持仓不超过30只",
                rule_type="position_limit",
                parameters={"max_count": 30},
                severity="warning",
            ),
            ComplianceRule(
                rule_id="trade_limit_daily",
                name="日内交易限制",
                description="日内交易次数不超过50次",
                rule_type="trade_limit",
                parameters={"max_trades": 50},
                severity="warning",
            ),
            ComplianceRule(
                rule_id="drawdown_limit",
                name="回撤限制",
                description="最大回撤不超过10%",
                rule_type="risk_limit",
                parameters={"max_drawdown": 0.10},
                severity="critical",
            ),
            ComplianceRule(
                rule_id="liquidity_limit",
                name="流动性限制",
                description="持仓资产日均成交额不低于1000万",
                rule_type="liquidity",
                parameters={"min_amount": 10000000},
                severity="warning",
            ),
            ComplianceRule(
                rule_id="holding_period",
                name="持有期限",
                description="买入后至少持有1天",
                rule_type="holding_period",
                parameters={"min_days": 1},
                severity="info",
            ),
        ]

        for rule in default_rules:
            self._rules[rule.rule_id] = rule

    def add_rule(self, rule: ComplianceRule):
        """添加规则"""
        self._rules[rule.rule_id] = rule

    def check_position_limit(
        self,
        positions: Dict[str, Dict],
        portfolio_value: float,
    ) -> List[ComplianceCheckResult]:
        """检查持仓限制"""
        results = []

        # 单只持仓限制
        rule = self._rules.get("position_limit_single")
        if rule and rule.enabled:
            max_weight = rule.parameters["max_weight"]
            for code, pos in positions.items():
                weight = pos.get("market_value", 0) / portfolio_value if portfolio_value > 0 else 0
                if weight > max_weight:
                    results.append(ComplianceCheckResult(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        status=ComplianceStatus.VIOLATION,
                        message=f"{code}持仓权重{weight*100:.2f}%超过限制{max_weight*100:.2f}%",
                        details={"code": code, "weight": weight, "limit": max_weight},
                    ))

        # 总持仓数量限制
        rule = self._rules.get("position_limit_total")
        if rule and rule.enabled:
            max_count = rule.parameters["max_count"]
            if len(positions) > max_count:
                results.append(ComplianceCheckResult(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    status=ComplianceStatus.WARNING,
                    message=f"持仓数量{len(positions)}超过限制{max_count}",
                    details={"count": len(positions), "limit": max_count},
                ))

        return results

    def check_trade_limit(
        self,
        trades_today: int,
    ) -> ComplianceCheckResult:
        """检查交易限制"""
        rule = self._rules.get("trade_limit_daily")
        if not rule or not rule.enabled:
            return None

        max_trades = rule.parameters["max_trades"]

        if trades_today > max_trades:
            return ComplianceCheckResult(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                status=ComplianceStatus.VIOLATION,
                message=f"今日交易次数{trades_today}超过限制{max_trades}",
                details={"trades": trades_today, "limit": max_trades},
            )

        return ComplianceCheckResult(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            status=ComplianceStatus.PASS,
            message="交易次数在限制范围内",
            details={"trades": trades_today, "limit": max_trades},
        )

    def check_drawdown(
        self,
        current_drawdown: float,
    ) -> ComplianceCheckResult:
        """检查回撤"""
        rule = self._rules.get("drawdown_limit")
        if not rule or not rule.enabled:
            return None

        max_dd = rule.parameters["max_drawdown"]

        if current_drawdown > max_dd:
            return ComplianceCheckResult(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                status=ComplianceStatus.BLOCKED,
                message=f"当前回撤{current_drawdown*100:.2f}%超过限制{max_dd*100:.2f}%",
                details={"drawdown": current_drawdown, "limit": max_dd},
            )

        return ComplianceCheckResult(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            status=ComplianceStatus.PASS,
            message="回撤在限制范围内",
            details={"drawdown": current_drawdown, "limit": max_dd},
        )

    def check_before_trade(
        self,
        trade: Dict,
        portfolio: Dict,
        positions: Dict[str, Dict],
    ) -> Tuple[bool, List[ComplianceCheckResult]]:
        """交易前检查"""
        results = []

        # 检查持仓限制
        results.extend(self.check_position_limit(positions, portfolio.get("aum", 0) * 10000))

        # 检查交易限制
        trade_check = self.check_trade_limit(portfolio.get("trades_today", 0))
        if trade_check:
            results.append(trade_check)

        # 检查回撤
        dd_check = self.check_drawdown(portfolio.get("drawdown", 0))
        if dd_check:
            results.append(dd_check)

        # 判断是否允许交易
        blocked = any(r.status == ComplianceStatus.BLOCKED for r in results)

        return not blocked, results


# ============ 监管报告生成器 ============

class RegulatoryReporter:
    """监管报告生成器"""

    def __init__(self):
        self.audit_logger = AuditLogger()

    def generate_daily_report(
        self,
        portfolio: Dict,
        positions: Dict[str, Dict],
        trades: List[Dict],
    ) -> Dict[str, Any]:
        """生成日报"""
        report_date = date.today()

        return {
            "report_type": "daily",
            "report_date": report_date.isoformat(),
            "generated_at": datetime.now().isoformat(),

            # 组合概况
            "portfolio_summary": {
                "aum": portfolio.get("aum", 0),
                "total_value": portfolio.get("total_value", 0),
                "cash": portfolio.get("cash", 0),
                "position_count": len(positions),
                "daily_return": portfolio.get("daily_return", 0),
            },

            # 持仓明细
            "positions": [
                {
                    "code": code,
                    "name": pos.get("name", ""),
                    "quantity": pos.get("quantity", 0),
                    "market_value": pos.get("market_value", 0),
                    "weight": pos.get("market_value", 0) / (portfolio.get("total_value", 1) * 10000),
                }
                for code, pos in positions.items()
            ],

            # 交易明细
            "trades": trades,

            # 合规状态
            "compliance_status": self._get_compliance_summary(portfolio, positions),
        }

    def generate_monthly_report(
        self,
        portfolio_history: List[Dict],
        trade_history: List[Dict],
        compliance_history: List[Dict],
    ) -> Dict[str, Any]:
        """生成月报"""
        month = date.today().strftime("%Y-%m")

        return {
            "report_type": "monthly",
            "report_month": month,
            "generated_at": datetime.now().isoformat(),

            # 绩效概况
            "performance_summary": self._calculate_performance(portfolio_history),

            # 交易统计
            "trade_statistics": self._calculate_trade_stats(trade_history),

            # 合规统计
            "compliance_statistics": self._calculate_compliance_stats(compliance_history),

            # 风险指标
            "risk_metrics": self._calculate_risk_metrics(portfolio_history),
        }

    def _get_compliance_summary(
        self,
        portfolio: Dict,
        positions: Dict,
    ) -> Dict:
        """获取合规摘要"""
        engine = ComplianceEngine()

        position_results = engine.check_position_limit(
            positions,
            portfolio.get("aum", 0) * 10000,
        )

        dd_result = engine.check_drawdown(portfolio.get("drawdown", 0))

        violations = [r for r in position_results if r.status in [ComplianceStatus.VIOLATION, ComplianceStatus.BLOCKED]]
        warnings = [r for r in position_results if r.status == ComplianceStatus.WARNING]

        return {
            "status": "pass" if not violations else "violation",
            "violations": len(violations),
            "warnings": len(warnings),
            "details": [r.to_dict() for r in position_results],
        }

    def _calculate_performance(self, history: List[Dict]) -> Dict:
        """计算绩效"""
        if not history:
            return {}

        returns = [h.get("daily_return", 0) for h in history]
        navs = [h.get("nav", 1) for h in history]

        return {
            "total_return": (navs[-1] / navs[0] - 1) if len(navs) > 1 else 0,
            "avg_daily_return": np.mean(returns) if returns else 0,
            "volatility": np.std(returns) if len(returns) > 1 else 0,
            "max_drawdown": max(0, max(navs) - min(navs)) / max(navs) if navs else 0,
            "trading_days": len(history),
        }

    def _calculate_trade_stats(self, trades: List[Dict]) -> Dict:
        """计算交易统计"""
        if not trades:
            return {"total_trades": 0}

        buy_trades = [t for t in trades if t.get("side") == "buy"]
        sell_trades = [t for t in trades if t.get("side") == "sell"]

        return {
            "total_trades": len(trades),
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "total_amount": sum(t.get("amount", 0) for t in trades),
        }

    def _calculate_compliance_stats(self, history: List[Dict]) -> Dict:
        """计算合规统计"""
        if not history:
            return {"total_checks": 0}

        violations = sum(1 for h in history if h.get("status") == "violation")
        warnings = sum(1 for h in history if h.get("status") == "warning")

        return {
            "total_checks": len(history),
            "violations": violations,
            "warnings": warnings,
            "compliance_rate": (len(history) - violations) / len(history) if history else 1,
        }

    def _calculate_risk_metrics(self, history: List[Dict]) -> Dict:
        """计算风险指标"""
        if not history:
            return {}

        returns = [h.get("daily_return", 0) for h in history]

        return {
            "var_95": np.percentile(returns, 5) if returns else 0,
            "max_drawdown": max(h.get("drawdown", 0) for h in history) if history else 0,
            "volatility": np.std(returns) * np.sqrt(252) if returns else 0,
        }


# ============ 便捷函数 ============

def get_audit_logger() -> AuditLogger:
    """获取审计日志器"""
    return AuditLogger()


def get_compliance_engine() -> ComplianceEngine:
    """获取合规引擎"""
    return ComplianceEngine()


def get_regulatory_reporter() -> RegulatoryReporter:
    """获取监管报告生成器"""
    return RegulatoryReporter()


def log_trade_audit(
    user_id: str,
    trade: Dict,
    ip_address: str = "0.0.0.0",
) -> AuditEvent:
    """记录交易审计"""
    return get_audit_logger().log_trade(user_id, trade, ip_address)


def check_trade_compliance(
    trade: Dict,
    portfolio: Dict,
    positions: Dict[str, Dict],
) -> Tuple[bool, List[ComplianceCheckResult]]:
    """检查交易合规性"""
    return get_compliance_engine().check_before_trade(trade, portfolio, positions)
