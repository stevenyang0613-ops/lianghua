"""实时合规监控"""
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import re


class ComplianceType(Enum):
    """合规类型"""
    POSITION_LIMIT = "position_limit"      # 持仓限制
    TRADING_LIMIT = "trading_limit"        # 交易限制
    SHORT_SELLING = "short_selling"        # 卖空限制
    MARKET_MANIPULATION = "market_manipulation"  # 市场操纵
    INSIDER_TRADING = "insider_trading"    # 内幕交易
    DISCLOSURE = "disclosure"              # 信息披露
    RISK_LIMIT = "risk_limit"              # 风险限制
    TRADING_HOURS = "trading_hours"        # 交易时间
    PROHIBITED_STOCKS = "prohibited_stocks"  # 禁止交易股票


class ViolationSeverity(Enum):
    """违规严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleStatus(Enum):
    """规则状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


@dataclass
class ComplianceRule:
    """合规规则"""
    rule_id: str
    rule_name: str
    compliance_type: ComplianceType
    description: str
    condition: str  # 规则条件表达式
    threshold: float
    severity: ViolationSeverity
    status: RuleStatus = RuleStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)


@dataclass
class Violation:
    """违规记录"""
    violation_id: str
    rule_id: str
    compliance_type: ComplianceType
    severity: ViolationSeverity
    description: str
    entity: str
    value: float
    threshold: float
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    status: str = "open"
    action_taken: str = ""
    metadata: Dict = field(default_factory=dict)


@dataclass
class TradingContext:
    """交易上下文"""
    trader_id: str
    account_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    order_type: str
    timestamp: datetime
    portfolio_value: float
    current_positions: Dict[str, float]
    daily_volume: Dict[str, float]
    total_pnl: float = 0.0
    metadata: Dict = field(default_factory=dict)


class ComplianceMonitor:
    """合规监控器"""
    
    def __init__(self):
        # 合规规则
        self.rules: Dict[str, ComplianceRule] = {}
        
        # 违规记录
        self.violations: List[Violation] = []
        
        # 告警回调
        self.alert_callbacks: List[Callable] = []
        
        # 实时状态
        self.trading_status: Dict[str, Dict] = defaultdict(dict)
        
        # 初始化默认规则
        self._init_default_rules()
    
    def _init_default_rules(self):
        """初始化默认规则"""
        default_rules = [
            ComplianceRule(
                rule_id="POS_001",
                rule_name="单只债券持仓上限",
                compliance_type=ComplianceType.POSITION_LIMIT,
                description="单只债券持仓不得超过基金净值的10%",
                condition="position_value / portfolio_value",
                threshold=0.10,
                severity=ViolationSeverity.HIGH
            ),
            ComplianceRule(
                rule_id="POS_002",
                rule_name="总持仓上限",
                compliance_type=ComplianceType.POSITION_LIMIT,
                description="总持仓不得超过基金净值的95%",
                condition="total_position_value / portfolio_value",
                threshold=0.95,
                severity=ViolationSeverity.HIGH
            ),
            ComplianceRule(
                rule_id="TRD_001",
                rule_name="单日交易量限制",
                compliance_type=ComplianceType.TRADING_LIMIT,
                description="单日单只债券交易量不得超过总交易量的30%",
                condition="daily_trade_volume / total_daily_volume",
                threshold=0.30,
                severity=ViolationSeverity.MEDIUM
            ),
            ComplianceRule(
                rule_id="TRD_002",
                rule_name="大额交易报告",
                compliance_type=ComplianceType.TRADING_LIMIT,
                description="单笔交易金额超过100万元需报告",
                condition="trade_amount",
                threshold=1000000,
                severity=ViolationSeverity.LOW
            ),
            ComplianceRule(
                rule_id="RISK_001",
                rule_name="VaR限额",
                compliance_type=ComplianceType.RISK_LIMIT,
                description="组合VaR不得超过净值的5%",
                condition="portfolio_var / portfolio_value",
                threshold=0.05,
                severity=ViolationSeverity.HIGH
            ),
            ComplianceRule(
                rule_id="RISK_002",
                rule_name="最大回撤限制",
                compliance_type=ComplianceType.RISK_LIMIT,
                description="最大回撤不得超过15%",
                condition="max_drawdown",
                threshold=0.15,
                severity=ViolationSeverity.CRITICAL
            ),
            ComplianceRule(
                rule_id="TRD_003",
                rule_name="交易时间限制",
                compliance_type=ComplianceType.TRADING_HOURS,
                description="仅允许在交易时间内进行交易",
                condition="is_trading_hours",
                threshold=1.0,
                severity=ViolationSeverity.HIGH
            ),
            ComplianceRule(
                rule_id="MAN_001",
                rule_name="异常交易检测",
                compliance_type=ComplianceType.MARKET_MANIPULATION,
                description="短时间内频繁买入卖出同一证券",
                condition="trade_frequency_5min",
                threshold=10,
                severity=ViolationSeverity.HIGH
            ),
        ]
        
        for rule in default_rules:
            self.rules[rule.rule_id] = rule
    
    def add_rule(self, rule: ComplianceRule):
        """添加规则"""
        self.rules[rule.rule_id] = rule
    
    def remove_rule(self, rule_id: str):
        """移除规则"""
        if rule_id in self.rules:
            del self.rules[rule_id]
    
    def check_pre_trade(self, context: TradingContext) -> List[Violation]:
        """交易前检查"""
        violations = []
        
        for rule_id, rule in self.rules.items():
            if rule.status != RuleStatus.ACTIVE:
                continue
            
            if rule.compliance_type in [ComplianceType.POSITION_LIMIT, ComplianceType.TRADING_LIMIT, 
                                        ComplianceType.RISK_LIMIT, ComplianceType.TRADING_HOURS,
                                        ComplianceType.PROHIBITED_STOCKS]:
                violation = self._evaluate_rule(rule, context)
                if violation:
                    violations.append(violation)
        
        return violations
    
    def check_post_trade(self, context: TradingContext) -> List[Violation]:
        """交易后检查"""
        violations = []
        
        for rule_id, rule in self.rules.items():
            if rule.status != RuleStatus.ACTIVE:
                continue
            
            violation = self._evaluate_rule(rule, context)
            if violation:
                violations.append(violation)
                self.violations.append(violation)
                self._notify_violation(violation)
        
        return violations
    
    def _evaluate_rule(self, rule: ComplianceRule, context: TradingContext) -> Optional[Violation]:
        """评估规则"""
        try:
            # 计算条件值
            value = self._calculate_condition(rule.condition, context)
            
            # 判断是否违规
            if self._is_violation(value, rule.threshold, rule.compliance_type):
                return Violation(
                    violation_id=f"viol_{int(datetime.now().timestamp() * 1000000)}",
                    rule_id=rule.rule_id,
                    compliance_type=rule.compliance_type,
                    severity=rule.severity,
                    description=rule.description,
                    entity=context.symbol,
                    value=value,
                    threshold=rule.threshold,
                    detected_at=datetime.now(),
                    metadata={
                        'trader_id': context.trader_id,
                        'account_id': context.account_id,
                        'order_type': context.order_type
                    }
                )
        
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[Compliance] Rule evaluation failed: {e}")
        
        return None
    
    def _calculate_condition(self, condition: str, context: TradingContext) -> float:
        """计算条件值"""
        # 简化的条件计算
        if condition == "position_value / portfolio_value":
            position_value = abs(context.current_positions.get(context.symbol, 0) * context.price)
            return position_value / context.portfolio_value if context.portfolio_value > 0 else 0
        
        elif condition == "total_position_value / portfolio_value":
            total_position = sum(
                abs(qty * context.price) for qty in context.current_positions.values()
            )
            return total_position / context.portfolio_value if context.portfolio_value > 0 else 0
        
        elif condition == "daily_trade_volume / total_daily_volume":
            symbol_volume = context.daily_volume.get(context.symbol, 0)
            total_volume = sum(context.daily_volume.values())
            return symbol_volume / total_volume if total_volume > 0 else 0
        
        elif condition == "trade_amount":
            return context.quantity * context.price
        
        elif condition == "portfolio_var / portfolio_value":
            # 简化：使用持仓波动率估计
            return 0.02  # 假设2% VaR
        
        elif condition == "max_drawdown":
            return self.trading_status.get(context.account_id, {}).get('drawdown', 0)
        
        elif condition == "is_trading_hours":
            hour = context.timestamp.hour
            return 1.0 if 9 <= hour < 15 else 0.0
        
        elif condition == "trade_frequency_5min":
            return self.trading_status.get(context.account_id, {}).get('trade_frequency_5min', 0)
        
        return 0
    
    def _is_violation(self, value: float, threshold: float, compliance_type: ComplianceType) -> bool:
        """判断是否违规"""
        # 对于交易时间等布尔类型
        if compliance_type == ComplianceType.TRADING_HOURS:
            return value < threshold
        
        # 对于大额报告等触发型
        if compliance_type == ComplianceType.TRADING_LIMIT and threshold > 100000:
            return value >= threshold
        
        # 默认：超过阈值即违规
        return value > threshold
    
    def update_trading_status(self, account_id: str, status: Dict):
        """更新交易状态"""
        self.trading_status[account_id].update(status)
    
    def resolve_violation(self, violation_id: str, action_taken: str):
        """解决违规"""
        for violation in self.violations:
            if violation.violation_id == violation_id:
                violation.status = "resolved"
                violation.resolved_at = datetime.now()
                violation.action_taken = action_taken
                break
    
    def get_open_violations(self, severity: ViolationSeverity = None) -> List[Violation]:
        """获取未解决违规"""
        violations = [v for v in self.violations if v.status == "open"]
        
        if severity:
            violations = [v for v in violations if v.severity == severity]
        
        return violations
    
    def get_violation_statistics(self, days: int = 30) -> Dict:
        """获取违规统计"""
        cutoff = datetime.now() - timedelta(days=days)
        recent_violations = [v for v in self.violations if v.detected_at >= cutoff]
        
        # 按类型统计
        by_type = defaultdict(int)
        by_severity = defaultdict(int)
        by_status = defaultdict(int)
        
        for violation in recent_violations:
            by_type[violation.compliance_type.value] += 1
            by_severity[violation.severity.value] += 1
            by_status[violation.status] += 1
        
        return {
            'total': len(recent_violations),
            'by_type': dict(by_type),
            'by_severity': dict(by_severity),
            'by_status': dict(by_status),
            'resolution_rate': by_status.get('resolved', 0) / len(recent_violations) if recent_violations else 0
        }
    
    def _notify_violation(self, violation: Violation):
        """通知违规"""
        for callback in self.alert_callbacks:
            try:
                callback(violation)
            except Exception:
                pass
    
    def add_alert_callback(self, callback: Callable):
        """添加告警回调"""
        self.alert_callbacks.append(callback)
    
    def export_rules(self) -> List[Dict]:
        """导出规则"""
        return [
            {
                'rule_id': r.rule_id,
                'rule_name': r.rule_name,
                'compliance_type': r.compliance_type.value,
                'description': r.description,
                'threshold': r.threshold,
                'severity': r.severity.value,
                'status': r.status.value
            }
            for r in self.rules.values()
        ]
    
    def import_rules(self, rules_data: List[Dict]):
        """导入规则"""
        for data in rules_data:
            rule = ComplianceRule(
                rule_id=data['rule_id'],
                rule_name=data['rule_name'],
                compliance_type=ComplianceType(data['compliance_type']),
                description=data['description'],
                condition=data.get('condition', ''),
                threshold=data['threshold'],
                severity=ViolationSeverity(data['severity']),
                status=RuleStatus(data.get('status', 'active'))
            )
            self.rules[rule.rule_id] = rule
