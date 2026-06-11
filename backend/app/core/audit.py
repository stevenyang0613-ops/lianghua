"""
日志审计系统

功能：
- 操作日志记录
- 交易日志记录
- 日志查询API
- 日志导出功能
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
import json
import csv
import io
import logging

logger = logging.getLogger(__name__)


class LogType(Enum):
    """日志类型"""
    OPERATION = 'operation'      # 操作日志
    TRADE = 'trade'             # 交易日志
    SYSTEM = 'system'           # 系统日志
    ERROR = 'error'             # 错误日志
    SECURITY = 'security'       # 安全日志
    PERFORMANCE = 'performance' # 性能日志


class LogLevel(Enum):
    """日志级别"""
    DEBUG = 'debug'
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'


@dataclass
class LogEntry:
    """日志条目"""
    log_id: str
    log_type: LogType
    level: LogLevel
    timestamp: str
    user_id: Optional[str]
    session_id: Optional[str]
    action: str
    resource: str
    details: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    duration_ms: Optional[int]
    result: str  # success/failure/partial

    def to_dict(self) -> Dict:
        return {
            'log_id': self.log_id,
            'log_type': self.log_type.value,
            'level': self.level.value,
            'timestamp': self.timestamp,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'action': self.action,
            'resource': self.resource,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'duration_ms': self.duration_ms,
            'result': self.result,
        }


@dataclass
class TradeLogEntry:
    """交易日志条目"""
    trade_id: str
    timestamp: str
    user_id: str
    account_id: str
    code: str
    name: str
    action: str  # buy/sell
    price: float
    volume: int
    amount: float
    commission: float
    slippage: float
    strategy: Optional[str]
    signal_source: Optional[str]
    reason: str
    result: str  # success/failure
    error_message: Optional[str]
    execution_time_ms: int

    def to_dict(self) -> Dict:
        return {
            'trade_id': self.trade_id,
            'timestamp': self.timestamp,
            'user_id': self.user_id,
            'account_id': self.account_id,
            'code': self.code,
            'name': self.name,
            'action': self.action,
            'price': self.price,
            'volume': self.volume,
            'amount': self.amount,
            'commission': self.commission,
            'slippage': self.slippage,
            'strategy': self.strategy,
            'signal_source': self.signal_source,
            'reason': self.reason,
            'result': self.result,
            'error_message': self.error_message,
            'execution_time_ms': self.execution_time_ms,
        }


class AuditLogService:
    """审计日志服务"""

    def __init__(self, max_entries: int = 100000):
        self._operation_logs: List[LogEntry] = []
        self._trade_logs: List[TradeLogEntry] = []
        self._max_entries = max_entries

    def log_operation(
        self,
        user_id: str,
        action: str,
        resource: str,
        details: Dict = None,
        level: LogLevel = LogLevel.INFO,
        session_id: str = None,
        ip_address: str = None,
        user_agent: str = None,
        duration_ms: int = None,
        result: str = 'success',
    ) -> LogEntry:
        """记录操作日志"""
        import secrets

        entry = LogEntry(
            log_id=f"log_{secrets.token_hex(8)}",
            log_type=LogType.OPERATION,
            level=level,
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            session_id=session_id,
            action=action,
            resource=resource,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            duration_ms=duration_ms,
            result=result,
        )

        self._operation_logs.append(entry)
        self._trim_logs()

        logger.info(f"[Audit] {user_id} {action} {resource} - {result}")

        return entry

    def log_trade(
        self,
        user_id: str,
        account_id: str,
        code: str,
        name: str,
        action: str,
        price: float,
        volume: int,
        commission: float = 0,
        slippage: float = 0,
        strategy: str = None,
        signal_source: str = None,
        reason: str = '',
        result: str = 'success',
        error_message: str = None,
        execution_time_ms: int = 0,
    ) -> TradeLogEntry:
        """记录交易日志"""
        import secrets

        amount = price * volume

        entry = TradeLogEntry(
            trade_id=f"trade_{secrets.token_hex(8)}",
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            account_id=account_id,
            code=code,
            name=name,
            action=action,
            price=price,
            volume=volume,
            amount=amount,
            commission=commission,
            slippage=slippage,
            strategy=strategy,
            signal_source=signal_source,
            reason=reason,
            result=result,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )

        self._trade_logs.append(entry)
        self._trim_logs()

        log_level = LogLevel.INFO if result == 'success' else LogLevel.ERROR
        logger.log(
            logging.INFO if result == 'success' else logging.ERROR,
            f"[Trade] {user_id} {action} {code} {volume}@{price} - {result}"
        )

        return entry

    def log_error(
        self,
        user_id: str,
        error_type: str,
        error_message: str,
        stack_trace: str = None,
        context: Dict = None,
    ) -> LogEntry:
        """记录错误日志"""
        import secrets

        entry = LogEntry(
            log_id=f"err_{secrets.token_hex(8)}",
            log_type=LogType.ERROR,
            level=LogLevel.ERROR,
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            session_id=None,
            action='error',
            resource=error_type,
            details={
                'error_message': error_message,
                'stack_trace': stack_trace,
                'context': context or {},
            },
            ip_address=None,
            user_agent=None,
            duration_ms=None,
            result='failure',
        )

        self._operation_logs.append(entry)
        self._trim_logs()

        logger.error(f"[Error] {user_id} {error_type}: {error_message}")

        return entry

    def _trim_logs(self):
        """清理过期日志"""
        if len(self._operation_logs) > self._max_entries:
            self._operation_logs = self._operation_logs[-self._max_entries:]

        if len(self._trade_logs) > self._max_entries:
            self._trade_logs = self._trade_logs[-self._max_entries:]

    # ==================== 查询接口 ====================

    def query_operation_logs(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        level: Optional[LogLevel] = None,
        result: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """查询操作日志"""
        logs = self._operation_logs.copy()

        if user_id:
            logs = [l for l in logs if l.user_id == user_id]
        if action:
            logs = [l for l in logs if l.action == action]
        if resource:
            logs = [l for l in logs if l.resource == resource]
        if level:
            logs = [l for l in logs if l.level == level]
        if result:
            logs = [l for l in logs if l.result == result]
        if start_time:
            logs = [l for l in logs if datetime.fromisoformat(l.timestamp) >= start_time]
        if end_time:
            logs = [l for l in logs if datetime.fromisoformat(l.timestamp) <= end_time]

        logs = logs[offset:offset+limit]

        return [l.to_dict() for l in logs]

    def query_trade_logs(
        self,
        user_id: Optional[str] = None,
        account_id: Optional[str] = None,
        code: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """查询交易日志"""
        logs = self._trade_logs.copy()

        if user_id:
            logs = [l for l in logs if l.user_id == user_id]
        if account_id:
            logs = [l for l in logs if l.account_id == account_id]
        if code:
            logs = [l for l in logs if l.code == code]
        if action:
            logs = [l for l in logs if l.action == action]
        if result:
            logs = [l for l in logs if l.result == result]
        if start_time:
            logs = [l for l in logs if datetime.fromisoformat(l.timestamp) >= start_time]
        if end_time:
            logs = [l for l in logs if datetime.fromisoformat(l.timestamp) <= end_time]

        logs = logs[offset:offset+limit]

        return [l.to_dict() for l in logs]

    def get_trade_statistics(
        self,
        user_id: Optional[str] = None,
        account_id: Optional[str] = None,
        days: int = 30,
    ) -> Dict:
        """获取交易统计"""
        cutoff = datetime.now() - timedelta(days=days)
        logs = [l for l in self._trade_logs if datetime.fromisoformat(l.timestamp) >= cutoff]

        if user_id:
            logs = [l for l in logs if l.user_id == user_id]
        if account_id:
            logs = [l for l in logs if l.account_id == account_id]

        total_trades = len(logs)
        buy_trades = len([l for l in logs if l.action == 'buy'])
        sell_trades = len([l for l in logs if l.action == 'sell'])
        success_trades = len([l for l in logs if l.result == 'success'])

        total_amount = sum(l.amount for l in logs)
        total_commission = sum(l.commission for l in logs)
        total_slippage = sum(l.slippage for l in logs)

        return {
            'period_days': days,
            'total_trades': total_trades,
            'buy_trades': buy_trades,
            'sell_trades': sell_trades,
            'success_rate': success_trades / total_trades if total_trades > 0 else 0,
            'total_amount': round(total_amount, 2),
            'total_commission': round(total_commission, 2),
            'total_slippage': round(total_slippage, 2),
            'total_cost': round(total_commission + total_slippage, 2),
            'avg_trade_amount': round(total_amount / total_trades, 2) if total_trades > 0 else 0,
        }

    def get_operation_statistics(
        self,
        user_id: Optional[str] = None,
        days: int = 30,
    ) -> Dict:
        """获取操作统计"""
        cutoff = datetime.now() - timedelta(days=days)
        logs = [l for l in self._operation_logs if datetime.fromisoformat(l.timestamp) >= cutoff]

        if user_id:
            logs = [l for l in logs if l.user_id == user_id]

        action_counts = {}
        resource_counts = {}

        for log in logs:
            action_counts[log.action] = action_counts.get(log.action, 0) + 1
            resource_counts[log.resource] = resource_counts.get(log.resource, 0) + 1

        return {
            'period_days': days,
            'total_operations': len(logs),
            'action_breakdown': action_counts,
            'resource_breakdown': resource_counts,
            'error_count': len([l for l in logs if l.level == LogLevel.ERROR]),
        }

    # ==================== 导出功能 ====================

    def export_operation_logs_csv(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> str:
        """导出操作日志为CSV"""
        logs = self.query_operation_logs(
            start_time=start_time,
            end_time=end_time,
            limit=10000,
        )

        if not logs:
            return ''

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=logs[0].keys())
        writer.writeheader()
        writer.writerows(logs)

        return output.getvalue()

    def export_trade_logs_csv(
        self,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> str:
        """导出交易日志为CSV"""
        logs = self.query_trade_logs(
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            limit=10000,
        )

        if not logs:
            return ''

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=logs[0].keys())
        writer.writeheader()
        writer.writerows(logs)

        return output.getvalue()

    def export_logs_json(
        self,
        log_type: str = 'operation',
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> str:
        """导出日志为JSON"""
        if log_type == 'trade':
            logs = self.query_trade_logs(start_time=start_time, end_time=end_time, limit=10000)
        else:
            logs = self.query_operation_logs(start_time=start_time, end_time=end_time, limit=10000)

        return json.dumps(logs, ensure_ascii=False, indent=2)


# 全局实例
_audit_service: Optional[AuditLogService] = None


def get_audit_service() -> AuditLogService:
    """获取审计日志服务"""
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditLogService()
    return _audit_service
