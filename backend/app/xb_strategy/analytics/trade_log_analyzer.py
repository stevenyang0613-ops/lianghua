"""西部量化可转债策略 V3.0 交易日志分析模块

功能:
- 交易行为分析
- 执行质量统计
- 失败交易诊断
- 改进建议生成
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import math
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class TradeStatus(str, Enum):
    """交易状态"""
    FILLED = "filled"           # 完全成交
    PARTIAL = "partial"         # 部分成交
    CANCELLED = "cancelled"     # 已取消
    REJECTED = "rejected"       # 已拒绝
    FAILED = "failed"           # 失败


class TradeSide(str, Enum):
    """交易方向"""
    BUY = "buy"
    SELL = "sell"


class ExecutionQuality(str, Enum):
    """执行质量"""
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"
    BAD = "bad"


class FailureReason(str, Enum):
    """失败原因"""
    INSUFFICIENT_FUNDS = "insufficient_funds"
    LIMIT_HIT = "limit_hit"
    MARKET_CLOSED = "market_closed"
    PRICE_MOVEMENT = "price_movement"
    SYSTEM_ERROR = "system_error"
    NETWORK_ERROR = "network_error"
    RISK_CHECK_FAILED = "risk_check_failed"
    UNKNOWN = "unknown"


# ============ 数据模型 ============

@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: str
    code: str
    side: TradeSide
    order_type: str
    quantity: int
    price: float
    target_price: float
    filled_quantity: int
    filled_price: float
    status: TradeStatus
    submit_time: datetime
    fill_time: datetime
    commission: float
    slippage: float = 0
    market_impact: float = 0
    failure_reason: FailureReason = None
    signal_id: str = None
    strategy: str = None

    def calculate_slippage(self):
        """计算滑点"""
        if self.filled_price > 0 and self.target_price > 0:
            self.slippage = abs(self.filled_price - self.target_price) / self.target_price

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "code": self.code,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "status": self.status.value,
            "submit_time": self.submit_time.isoformat(),
            "fill_time": self.fill_time.isoformat() if self.fill_time else None,
            "slippage": round(self.slippage, 6),
            "commission": self.commission,
        }


@dataclass
class ExecutionMetrics:
    """执行指标"""
    total_trades: int = 0
    filled_trades: int = 0
    partial_trades: int = 0
    cancelled_trades: int = 0
    failed_trades: int = 0
    total_volume: int = 0
    total_turnover: float = 0
    avg_fill_rate: float = 0
    avg_slippage: float = 0
    avg_latency_ms: float = 0
    total_commission: float = 0

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "filled_trades": self.filled_trades,
            "partial_trades": self.partial_trades,
            "cancelled_trades": self.cancelled_trades,
            "failed_trades": self.failed_trades,
            "fill_rate": round(self.filled_trades / self.total_trades, 4) if self.total_trades > 0 else 0,
            "total_volume": self.total_volume,
            "total_turnover": round(self.total_turnover, 2),
            "avg_fill_rate": round(self.avg_fill_rate, 4),
            "avg_slippage": round(self.avg_slippage, 6),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_commission": round(self.total_commission, 2),
        }


@dataclass
class BehaviorPattern:
    """行为模式"""
    pattern_type: str
    frequency: int
    impact: float
    description: str
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "pattern_type": self.pattern_type,
            "frequency": self.frequency,
            "impact": round(self.impact, 4),
            "description": self.description,
            "recommendation": self.recommendation,
        }


@dataclass
class TradeAnalysisReport:
    """交易分析报告"""
    period_start: datetime
    period_end: datetime
    execution_metrics: ExecutionMetrics
    behavior_patterns: List[BehaviorPattern]
    failure_analysis: Dict[str, Any]
    quality_score: float
    recommendations: List[str]

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "execution_metrics": self.execution_metrics.to_dict(),
            "behavior_patterns": [p.to_dict() for p in self.behavior_patterns],
            "failure_analysis": self.failure_analysis,
            "quality_score": round(self.quality_score, 2),
            "recommendations": self.recommendations,
        }


# ============ 交易行为分析器 ============

class TradeBehaviorAnalyzer:
    """交易行为分析器"""

    def __init__(self):
        self._trades: List[TradeRecord] = []

    def add_trade(self, trade: TradeRecord):
        """添加交易"""
        self._trades.append(trade)

    def analyze_patterns(self) -> List[BehaviorPattern]:
        """分析行为模式"""
        patterns = []

        # 分析交易频率
        frequency_pattern = self._analyze_frequency()
        if frequency_pattern:
            patterns.append(frequency_pattern)

        # 分析交易时间偏好
        time_pattern = self._analyze_time_preference()
        if time_pattern:
            patterns.append(time_pattern)

        # 分析持仓周期
        holding_pattern = self._analyze_holding_period()
        if holding_pattern:
            patterns.append(holding_pattern)

        # 分析交易规模
        size_pattern = self._analyze_trade_size()
        if size_pattern:
            patterns.append(size_pattern)

        # 分析买卖偏向
        bias_pattern = self._analyze_direction_bias()
        if bias_pattern:
            patterns.append(bias_pattern)

        return patterns

    def _analyze_frequency(self) -> Optional[BehaviorPattern]:
        """分析交易频率"""
        if len(self._trades) < 10:
            return None

        # 计算日均交易次数
        dates = [t.submit_time.date() for t in self._trades]
        date_counts = Counter(dates)

        avg_trades_per_day = sum(date_counts.values()) / len(date_counts)

        # 判断是否过度交易
        if avg_trades_per_day > 20:
            return BehaviorPattern(
                pattern_type="overtrading",
                frequency=int(avg_trades_per_day),
                impact=-0.02,  # 负面影响
                description=f"日均交易{avg_trades_per_day:.1f}次, 可能过度交易",
                recommendation="降低交易频率, 提高单笔交易质量",
            )
        elif avg_trades_per_day < 2:
            return BehaviorPattern(
                pattern_type="undertrading",
                frequency=int(avg_trades_per_day),
                impact=0.01,
                description=f"日均交易{avg_trades_per_day:.1f}次, 交易频率较低",
                recommendation="评估是否错过了交易机会",
            )

        return None

    def _analyze_time_preference(self) -> Optional[BehaviorPattern]:
        """分析时间偏好"""
        if len(self._trades) < 20:
            return None

        # 按小时统计
        hour_counts = Counter(t.submit_time.hour for t in self._trades)
        peak_hour = hour_counts.most_common(1)[0][0]

        # 判断是否集中在开盘/收盘
        if peak_hour in [9, 10]:
            return BehaviorPattern(
                pattern_type="morning_bias",
                frequency=hour_counts[peak_hour],
                impact=0.005,
                description="交易集中在早盘时段",
                recommendation="注意开盘波动风险, 考虑分散交易时间",
            )
        elif peak_hour in [14, 15]:
            return BehaviorPattern(
                pattern_type="afternoon_bias",
                frequency=hour_counts[peak_hour],
                impact=0.005,
                description="交易集中在尾盘时段",
                recommendation="注意收盘前的流动性风险",
            )

        return None

    def _analyze_holding_period(self) -> Optional[BehaviorPattern]:
        """分析持仓周期"""
        # 需要配对的买卖交易
        buy_sell_pairs = self._match_buy_sell()

        if not buy_sell_pairs:
            return None

        holding_days = []
        for buy, sell in buy_sell_pairs:
            if buy.fill_time and sell.fill_time:
                days = (sell.fill_time - buy.fill_time).days
                holding_days.append(days)

        if not holding_days:
            return None

        avg_holding = sum(holding_days) / len(holding_days)

        if avg_holding < 1:
            return BehaviorPattern(
                pattern_type="day_trading",
                frequency=len(holding_days),
                impact=-0.01,
                description="平均持仓不足1天, 日内交易为主",
                recommendation="注意交易成本累积, 考虑延长持仓周期",
            )
        elif avg_holding > 30:
            return BehaviorPattern(
                pattern_type="long_term",
                frequency=len(holding_days),
                impact=0.02,
                description="平均持仓超过30天, 长线投资为主",
                recommendation="定期评估持仓, 确保与策略目标一致",
            )

        return None

    def _analyze_trade_size(self) -> Optional[BehaviorPattern]:
        """分析交易规模"""
        if len(self._trades) < 10:
            return None

        sizes = [t.filled_quantity for t in self._trades if t.filled_quantity > 0]

        if not sizes:
            return None

        avg_size = sum(sizes) / len(sizes)
        max_size = max(sizes)

        if max_size > avg_size * 10:
            return BehaviorPattern(
                pattern_type="size_outlier",
                frequency=1,
                impact=-0.015,
                description="存在异常大额交易",
                recommendation="审查大额交易决策, 考虑拆分执行",
            )

        return None

    def _analyze_direction_bias(self) -> Optional[BehaviorPattern]:
        """分析方向偏向"""
        if len(self._trades) < 20:
            return None

        buy_count = sum(1 for t in self._trades if t.side == TradeSide.BUY)
        sell_count = len(self._trades) - buy_count

        buy_ratio = buy_count / len(self._trades)

        if buy_ratio > 0.7:
            return BehaviorPattern(
                pattern_type="buy_bias",
                frequency=buy_count,
                impact=-0.01,
                description=f"买入占比{buy_ratio:.1%}, 存在买入偏向",
                recommendation="平衡买卖决策, 避免追高",
            )
        elif buy_ratio < 0.3:
            return BehaviorPattern(
                pattern_type="sell_bias",
                frequency=sell_count,
                impact=-0.01,
                description=f"卖出占比{1-buy_ratio:.1%}, 存在卖出偏向",
                recommendation="评估是否过度悲观",
            )

        return None

    def _match_buy_sell(self) -> List[Tuple[TradeRecord, TradeRecord]]:
        """匹配买卖对"""
        pairs = []
        buys: Dict[str, List[TradeRecord]] = defaultdict(list)

        for trade in sorted(self._trades, key=lambda t: t.submit_time):
            if trade.side == TradeSide.BUY:
                buys[trade.code].append(trade)
            else:
                # 匹配卖出
                if buys[trade.code]:
                    buy = buys[trade.code].pop(0)
                    pairs.append((buy, trade))

        return pairs


# ============ 执行质量分析器 ============

class ExecutionQualityAnalyzer:
    """执行质量分析器"""

    def __init__(self):
        self._trades: List[TradeRecord] = []

    def add_trade(self, trade: TradeRecord):
        """添加交易"""
        trade.calculate_slippage()
        self._trades.append(trade)

    def calculate_metrics(self) -> ExecutionMetrics:
        """计算指标"""
        metrics = ExecutionMetrics()

        if not self._trades:
            return metrics

        metrics.total_trades = len(self._trades)

        filled = [t for t in self._trades if t.status == TradeStatus.FILLED]
        partial = [t for t in self._trades if t.status == TradeStatus.PARTIAL]
        cancelled = [t for t in self._trades if t.status == TradeStatus.CANCELLED]
        failed = [t for t in self._trades if t.status in [TradeStatus.FAILED, TradeStatus.REJECTED]]

        metrics.filled_trades = len(filled)
        metrics.partial_trades = len(partial)
        metrics.cancelled_trades = len(cancelled)
        metrics.failed_trades = len(failed)

        # 成交量
        metrics.total_volume = sum(t.filled_quantity for t in self._trades)
        metrics.total_turnover = sum(t.filled_quantity * t.filled_price for t in self._trades)

        # 平均成交率
        fill_rates = [t.filled_quantity / t.quantity for t in self._trades if t.quantity > 0]
        metrics.avg_fill_rate = sum(fill_rates) / len(fill_rates) if fill_rates else 0

        # 平均滑点
        slippages = [t.slippage for t in filled if t.slippage > 0]
        metrics.avg_slippage = sum(slippages) / len(slippages) if slippages else 0

        # 平均延迟
        latencies = []
        for t in self._trades:
            if t.submit_time and t.fill_time:
                latency = (t.fill_time - t.submit_time).total_seconds() * 1000
                latencies.append(latency)
        metrics.avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0

        # 佣金
        metrics.total_commission = sum(t.commission for t in self._trades)

        return metrics

    def score_execution(self) -> float:
        """评分执行质量"""
        metrics = self.calculate_metrics()

        score = 100.0

        # 成交率扣分
        fill_rate = metrics.filled_trades / metrics.total_trades if metrics.total_trades > 0 else 0
        score -= (1 - fill_rate) * 20

        # 滑点扣分
        score -= metrics.avg_slippage * 1000  # 每10bps扣1分

        # 失败率扣分
        fail_rate = metrics.failed_trades / metrics.total_trades if metrics.total_trades > 0 else 0
        score -= fail_rate * 30

        # 延迟扣分
        if metrics.avg_latency_ms > 1000:
            score -= min(20, (metrics.avg_latency_ms - 1000) / 100)

        return max(0, min(100, score))

    def get_quality_level(self, score: float) -> ExecutionQuality:
        """获取质量等级"""
        if score >= 90:
            return ExecutionQuality.EXCELLENT
        elif score >= 75:
            return ExecutionQuality.GOOD
        elif score >= 60:
            return ExecutionQuality.AVERAGE
        elif score >= 40:
            return ExecutionQuality.POOR
        else:
            return ExecutionQuality.BAD


# ============ 失败交易诊断器 ============

class FailureAnalyzer:
    """失败交易诊断器"""

    def __init__(self):
        self._failed_trades: List[TradeRecord] = []

    def add_failed_trade(self, trade: TradeRecord):
        """添加失败交易"""
        self._failed_trades.append(trade)

    def diagnose(self) -> Dict[str, Any]:
        """诊断失败原因"""
        if not self._failed_trades:
            return {"total_failures": 0, "by_reason": {}, "recommendations": []}

        # 按原因统计
        reason_counts = Counter(t.failure_reason for t in self._failed_trades if t.failure_reason)

        # 按时间统计
        time_distribution = Counter(t.submit_time.hour for t in self._failed_trades)

        # 按标的统计
        code_distribution = Counter(t.code for t in self._failed_trades)

        # 生成建议
        recommendations = self._generate_recommendations(reason_counts)

        return {
            "total_failures": len(self._failed_trades),
            "by_reason": dict(reason_counts),
            "by_hour": dict(time_distribution),
            "by_code": dict(code_distribution.most_common(10)),
            "failure_rate": len(self._failed_trades) / max(1, len(self._failed_trades) + 100),
            "recommendations": recommendations,
        }

    def _generate_recommendations(self, reason_counts: Counter) -> List[str]:
        """生成改进建议"""
        recommendations = []

        for reason, count in reason_counts.most_common():
            if reason == FailureReason.INSUFFICIENT_FUNDS:
                recommendations.append("优化资金管理, 确保账户有足够资金")
            elif reason == FailureReason.LIMIT_HIT:
                recommendations.append("调整限价单价格策略, 提高成交概率")
            elif reason == FailureReason.PRICE_MOVEMENT:
                recommendations.append("使用市价单或更宽松的限价范围")
            elif reason == FailureReason.SYSTEM_ERROR:
                recommendations.append("检查系统稳定性, 增加重试机制")
            elif reason == FailureReason.NETWORK_ERROR:
                recommendations.append("优化网络连接, 使用备用通道")
            elif reason == FailureReason.RISK_CHECK_FAILED:
                recommendations.append("检查风控规则设置是否过于严格")

        return recommendations

    def identify_problematic_trades(self) -> List[Dict]:
        """识别问题交易"""
        problematic = []

        for trade in self._failed_trades:
            if trade.failure_reason in [
                FailureReason.SYSTEM_ERROR,
                FailureReason.NETWORK_ERROR,
            ]:
                problematic.append({
                    "trade_id": trade.trade_id,
                    "code": trade.code,
                    "reason": trade.failure_reason.value,
                    "time": trade.submit_time.isoformat(),
                    "severity": "high",
                })

        return problematic


# ============ 交易日志分析器 ============

class TradeLogAnalyzer:
    """交易日志分析器"""

    def __init__(self):
        self.behavior_analyzer = TradeBehaviorAnalyzer()
        self.quality_analyzer = ExecutionQualityAnalyzer()
        self.failure_analyzer = FailureAnalyzer()

        self._all_trades: List[TradeRecord] = []

    def add_trade(self, trade: TradeRecord):
        """添加交易"""
        self._all_trades.append(trade)
        self.behavior_analyzer.add_trade(trade)
        self.quality_analyzer.add_trade(trade)

        if trade.status in [TradeStatus.FAILED, TradeStatus.REJECTED]:
            self.failure_analyzer.add_failed_trade(trade)

    def analyze(self, period_start: datetime = None, period_end: datetime = None) -> TradeAnalysisReport:
        """分析交易"""
        # 过滤期间
        if period_start or period_end:
            filtered = []
            for trade in self._all_trades:
                if period_start and trade.submit_time < period_start:
                    continue
                if period_end and trade.submit_time > period_end:
                    continue
                filtered.append(trade)

        # 执行指标
        execution_metrics = self.quality_analyzer.calculate_metrics()

        # 行为模式
        behavior_patterns = self.behavior_analyzer.analyze_patterns()

        # 失败分析
        failure_analysis = self.failure_analyzer.diagnose()

        # 质量评分
        quality_score = self.quality_analyzer.score_execution()

        # 改进建议
        recommendations = self._generate_recommendations(
            execution_metrics, behavior_patterns, failure_analysis
        )

        return TradeAnalysisReport(
            period_start=period_start or datetime.min,
            period_end=period_end or datetime.max,
            execution_metrics=execution_metrics,
            behavior_patterns=behavior_patterns,
            failure_analysis=failure_analysis,
            quality_score=quality_score,
            recommendations=recommendations,
        )

    def _generate_recommendations(
        self,
        metrics: ExecutionMetrics,
        patterns: List[BehaviorPattern],
        failure_analysis: Dict,
    ) -> List[str]:
        """生成改进建议"""
        recommendations = []

        # 基于执行指标
        if metrics.avg_slippage > 0.005:
            recommendations.append("滑点较高, 建议优化执行算法或拆分大单")

        if metrics.avg_latency_ms > 500:
            recommendations.append("执行延迟较高, 检查交易通道或部署边缘节点")

        if metrics.failed_trades > metrics.total_trades * 0.05:
            recommendations.append("失败率较高, 检查风控设置和资金充足性")

        # 基于行为模式
        for pattern in patterns:
            if pattern.impact < 0:
                recommendations.append(pattern.recommendation)

        # 基于失败分析
        recommendations.extend(failure_analysis.get("recommendations", []))

        return list(set(recommendations))[:10]  # 去重并限制数量

    def get_daily_summary(self, date: datetime = None) -> Dict:
        """获取每日摘要"""
        date = date or datetime.now().date()

        day_trades = [
            t for t in self._all_trades
            if t.submit_time.date() == date
        ]

        if not day_trades:
            return {"date": date.isoformat(), "trades": 0}

        filled = [t for t in day_trades if t.status == TradeStatus.FILLED]

        return {
            "date": date.isoformat(),
            "total_trades": len(day_trades),
            "filled_trades": len(filled),
            "total_volume": sum(t.filled_quantity for t in day_trades),
            "total_turnover": sum(t.filled_quantity * t.filled_price for t in filled),
            "avg_slippage": sum(t.slippage for t in filled) / len(filled) if filled else 0,
            "buy_count": sum(1 for t in day_trades if t.side == TradeSide.BUY),
            "sell_count": sum(1 for t in day_trades if t.side == TradeSide.SELL),
        }


# ============ 便捷函数 ============

def create_trade_analyzer() -> TradeLogAnalyzer:
    """创建交易分析器"""
    return TradeLogAnalyzer()


def analyze_execution_quality(trades: List[TradeRecord]) -> Dict:
    """分析执行质量"""
    analyzer = ExecutionQualityAnalyzer()
    for trade in trades:
        analyzer.add_trade(trade)

    metrics = analyzer.calculate_metrics()
    score = analyzer.score_execution()
    level = analyzer.get_quality_level(score)

    return {
        "metrics": metrics.to_dict(),
        "score": round(score, 2),
        "level": level.value,
    }


def calculate_slippage(target_price: float, filled_price: float) -> float:
    """计算滑点"""
    if target_price == 0:
        return 0
    return abs(filled_price - target_price) / target_price
