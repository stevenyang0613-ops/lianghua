"""西部量化可转债策略 V3.0 交易成本分析(TCA)模块

功能:
- 实现缺口分析
- 隐性成本量化
- 交易效率评分
- 优化建议生成
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class CostCategory(str, Enum):
    """成本类别"""
    EXPLICIT = "explicit"   # 显性成本
    IMPLICIT = "implicit"   # 隐性成本
    OPPORTUNITY = "opportunity"  # 机会成本


class ExecutionQuality(str, Enum):
    """执行质量"""
    EXCELLENT = "excellent"  # 优秀
    GOOD = "good"           # 良好
    AVERAGE = "average"     # 一般
    POOR = "poor"          # 较差
    BAD = "bad"            # 差


class BenchmarkType(str, Enum):
    """基准类型"""
    ARRIVAL = "arrival"       # 到达价
    TWAP = "twap"             # 时间加权平均价
    VWAP = "vwap"             # 成交量加权平均价
    CLOSE = "close"           # 收盘价
    OPEN = "open"             # 开盘价
    PREVIOUS_CLOSE = "prev_close"  # 前收盘


# ============ 数据模型 ============

@dataclass
class TradeExecution:
    """交易执行记录"""
    trade_id: str
    code: str
    side: str  # buy/sell
    order_time: datetime
    arrival_price: float
    target_price: float
    filled_quantity: int
    filled_price: float
    filled_time: datetime
    commission: float
    market_vwap: float = 0
    market_twap: float = 0
    close_price: float = 0
    high_price: float = 0
    low_price: float = 0
    volume_at_execution: int = 0
    adv: float = 0

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "code": self.code,
            "side": self.side,
            "order_time": self.order_time.isoformat(),
            "filled_price": self.filled_price,
            "filled_quantity": self.filled_quantity,
            "commission": self.commission,
        }


@dataclass
class CostBreakdown:
    """成本分解"""
    total_cost: float
    commission: float           # 佣金
    spread_cost: float          # 买卖价差
    market_impact: float        # 市场冲击
    timing_cost: float          # 时机成本
    opportunity_cost: float     # 机会成本
    delay_cost: float           # 延迟成本

    def to_dict(self) -> dict:
        return {
            "total_cost": round(self.total_cost, 4),
            "commission": round(self.commission, 4),
            "spread_cost": round(self.spread_cost, 4),
            "market_impact": round(self.market_impact, 4),
            "timing_cost": round(self.timing_cost, 4),
            "opportunity_cost": round(self.opportunity_cost, 4),
            "delay_cost": round(self.delay_cost, 4),
        }


@dataclass
class ImplementationShortfall:
    """实现缺口"""
    trade_id: str
    decision_price: float       # 决策价格
    arrival_price: float        # 到达价格
    execution_price: float      # 执行价格
    quantity: int
    total_shortfall: float      # 总缺口
    trading_cost: float         # 交易成本
    timing_cost: float          # 时机成本
    opportunity_cost: float     # 机会成本

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "decision_price": self.decision_price,
            "arrival_price": self.arrival_price,
            "execution_price": self.execution_price,
            "total_shortfall": round(self.total_shortfall, 4),
            "trading_cost": round(self.trading_cost, 4),
            "timing_cost": round(self.timing_cost, 4),
            "opportunity_cost": round(self.opportunity_cost, 4),
        }


# ============ 实现缺口分析器 ============

class ImplementationShortfallAnalyzer:
    """实现缺口分析器"""

    def __init__(self):
        self._trades: List[TradeExecution] = []
        self._shortfalls: List[ImplementationShortfall] = []

    def add_trade(self, trade: TradeExecution):
        """添加交易"""
        self._trades.append(trade)
        self._calculate_shortfall(trade)

    def _calculate_shortfall(self, trade: TradeExecution):
        """计算实现缺口"""
        # 假设决策价格为前收盘价
        decision_price = trade.arrival_price  # 简化处理

        # 计算各项成本
        if trade.side == "buy":
            # 买单: 实际支付 - 理想支付
            total_shortfall = (trade.filled_price - decision_price) * trade.filled_quantity
            trading_cost = (trade.filled_price - trade.arrival_price) * trade.filled_quantity
            timing_cost = (trade.arrival_price - decision_price) * trade.filled_quantity
        else:
            # 卖单: 理想收入 - 实际收入
            total_shortfall = (decision_price - trade.filled_price) * trade.filled_quantity
            trading_cost = (trade.arrival_price - trade.filled_price) * trade.filled_quantity
            timing_cost = (decision_price - trade.arrival_price) * trade.filled_quantity

        # 机会成本 (未成交部分)
        opportunity_cost = 0  # 简化处理

        shortfall = ImplementationShortfall(
            trade_id=trade.trade_id,
            decision_price=decision_price,
            arrival_price=trade.arrival_price,
            execution_price=trade.filled_price,
            quantity=trade.filled_quantity,
            total_shortfall=total_shortfall,
            trading_cost=trading_cost,
            timing_cost=timing_cost,
            opportunity_cost=opportunity_cost,
        )

        self._shortfalls.append(shortfall)

    def get_summary(self) -> Dict:
        """获取汇总"""
        if not self._shortfalls:
            return {}

        total_shortfall = sum(s.total_shortfall for s in self._shortfalls)
        total_trading_cost = sum(s.trading_cost for s in self._shortfalls)
        total_timing_cost = sum(s.timing_cost for s in self._shortfalls)

        total_value = sum(
            t.filled_quantity * t.filled_price for t in self._trades
        )

        return {
            "total_shortfall": round(total_shortfall, 2),
            "total_trading_cost": round(total_trading_cost, 2),
            "total_timing_cost": round(total_timing_cost, 2),
            "shortfall_bps": round(total_shortfall / total_value * 10000, 2) if total_value > 0 else 0,
            "trade_count": len(self._shortfalls),
        }

    def get_trade_analysis(self, trade_id: str) -> Optional[Dict]:
        """获取单笔分析"""
        for s in self._shortfalls:
            if s.trade_id == trade_id:
                return s.to_dict()
        return None


# ============ 隐性成本分析器 ============

class ImplicitCostAnalyzer:
    """隐性成本分析器"""

    def __init__(self):
        self._cost_history: Dict[str, List[CostBreakdown]] = defaultdict(list)

    def analyze(self, trade: TradeExecution) -> CostBreakdown:
        """分析隐性成本"""
        # 佣金
        commission = trade.commission

        # 买卖价差成本
        if trade.side == "buy":
            spread_cost = (trade.filled_price - trade.arrival_price) * 0.5 * trade.filled_quantity
        else:
            spread_cost = (trade.arrival_price - trade.filled_price) * 0.5 * trade.filled_quantity

        # 市场冲击
        if trade.adv > 0:
            participation = trade.filled_quantity / trade.adv
            # 简化的冲击模型
            market_impact = trade.arrival_price * participation * 0.001 * trade.filled_quantity
        else:
            market_impact = 0

        # 时机成本 (相对于VWAP)
        if trade.market_vwap > 0:
            if trade.side == "buy":
                timing_cost = (trade.filled_price - trade.market_vwap) * trade.filled_quantity
            else:
                timing_cost = (trade.market_vwap - trade.filled_price) * trade.filled_quantity
        else:
            timing_cost = 0

        # 机会成本
        opportunity_cost = 0  # 需要更多数据

        # 延迟成本
        delay_cost = self._calculate_delay_cost(trade)

        total_cost = commission + abs(spread_cost) + abs(market_impact) + abs(timing_cost)

        breakdown = CostBreakdown(
            total_cost=total_cost,
            commission=commission,
            spread_cost=abs(spread_cost),
            market_impact=abs(market_impact),
            timing_cost=timing_cost,
            opportunity_cost=opportunity_cost,
            delay_cost=delay_cost,
        )

        self._cost_history[trade.code].append(breakdown)

        return breakdown

    def _calculate_delay_cost(self, trade: TradeExecution) -> float:
        """计算延迟成本"""
        # 下单到成交的时间
        delay_seconds = (trade.filled_time - trade.order_time).total_seconds()

        # 价格波动
        if trade.high_price > 0 and trade.low_price > 0:
            price_volatility = trade.high_price - trade.low_price
            delay_cost = price_volatility * (delay_seconds / 3600) * trade.filled_quantity * 0.1
        else:
            delay_cost = 0

        return delay_cost

    def get_aggregate_costs(self, code: str = None) -> Dict:
        """获取汇总成本"""
        if code:
            costs = self._cost_history.get(code, [])
        else:
            costs = []
            for c in self._cost_history.values():
                costs.extend(c)

        if not costs:
            return {}

        return {
            "avg_total_cost": sum(c.total_cost for c in costs) / len(costs),
            "avg_commission": sum(c.commission for c in costs) / len(costs),
            "avg_spread_cost": sum(c.spread_cost for c in costs) / len(costs),
            "avg_market_impact": sum(c.market_impact for c in costs) / len(costs),
            "avg_timing_cost": sum(c.timing_cost for c in costs) / len(costs),
            "trade_count": len(costs),
        }


# ============ 执行效率评分器 ============

class ExecutionQualityScorer:
    """执行质量评分器"""

    def __init__(self):
        self._score_weights = {
            "shortfall": 0.3,
            "fill_rate": 0.2,
            "timing": 0.2,
            "impact": 0.15,
            "consistency": 0.15,
        }

    def score_trade(self, trade: TradeExecution, shortfall: ImplementationShortfall) -> Dict:
        """评分单笔交易"""
        scores = {}

        # 实现缺口评分
        shortfall_bps = abs(shortfall.total_shortfall) / (trade.filled_price * trade.filled_quantity) * 10000
        scores["shortfall"] = self._score_shortfall(shortfall_bps)

        # 成交率评分
        scores["fill_rate"] = 100  # 假设完全成交

        # 时机评分 (相对于VWAP)
        if trade.market_vwap > 0:
            timing_diff = abs(trade.filled_price - trade.market_vwap) / trade.market_vwap * 10000
            scores["timing"] = self._score_timing(timing_diff, trade.side)
        else:
            scores["timing"] = 50

        # 冲击评分
        if trade.adv > 0:
            participation = trade.filled_quantity / trade.adv
            scores["impact"] = self._score_impact(participation)
        else:
            scores["impact"] = 50

        # 一致性评分
        scores["consistency"] = 70  # 需要历史数据

        # 总分
        total_score = sum(
            scores[k] * self._score_weights[k]
            for k in self._score_weights
        )

        return {
            "scores": scores,
            "total_score": round(total_score, 2),
            "quality": self._get_quality_label(total_score),
        }

    def _score_shortfall(self, bps: float) -> float:
        """缺口评分"""
        if bps <= 2:
            return 100
        elif bps <= 5:
            return 90
        elif bps <= 10:
            return 80
        elif bps <= 20:
            return 70
        elif bps <= 50:
            return 60
        else:
            return max(0, 60 - (bps - 50) / 10)

    def _score_timing(self, bps: float, side: str) -> float:
        """时机评分"""
        if bps <= 1:
            return 100
        elif bps <= 3:
            return 90
        elif bps <= 5:
            return 80
        elif bps <= 10:
            return 70
        else:
            return max(0, 70 - (bps - 10) / 5)

    def _score_impact(self, participation: float) -> float:
        """冲击评分"""
        if participation <= 0.01:
            return 100
        elif participation <= 0.05:
            return 90
        elif participation <= 0.1:
            return 80
        elif participation <= 0.2:
            return 70
        else:
            return max(0, 70 - (participation - 0.2) * 100)

    def _get_quality_label(self, score: float) -> str:
        """获取质量标签"""
        if score >= 90:
            return ExecutionQuality.EXCELLENT.value
        elif score >= 80:
            return ExecutionQuality.GOOD.value
        elif score >= 70:
            return ExecutionQuality.AVERAGE.value
        elif score >= 60:
            return ExecutionQuality.POOR.value
        else:
            return ExecutionQuality.BAD.value

    def score_portfolio(self, trades: List[TradeExecution]) -> Dict:
        """评分组合"""
        if not trades:
            return {}

        total_value = sum(t.filled_quantity * t.filled_price for t in trades)
        total_shortfall = sum(
            abs(t.filled_price - t.arrival_price) * t.filled_quantity
            for t in trades
        )

        avg_shortfall_bps = total_shortfall / total_value * 10000 if total_value > 0 else 0

        return {
            "avg_shortfall_bps": round(avg_shortfall_bps, 2),
            "total_trades": len(trades),
            "total_value": round(total_value, 2),
            "quality": self._get_quality_label(100 - avg_shortfall_bps * 2),
        }


# ============ 优化建议生成器 ============

class OptimizationAdvisor:
    """优化建议生成器"""

    def __init__(self):
        self._recommendations: List[Dict] = []

    def analyze_and_recommend(
        self,
        trades: List[TradeExecution],
        shortfalls: List[ImplementationShortfall],
        costs: List[CostBreakdown],
    ) -> List[Dict]:
        """分析并生成建议"""
        recommendations = []

        # 分析实现缺口
        avg_shortfall = sum(s.total_shortfall for s in shortfalls) / len(shortfalls) if shortfalls else 0

        if avg_shortfall > 0:
            recommendations.append({
                "category": "execution",
                "priority": "high",
                "issue": f"平均实现缺口为 {avg_shortfall:.2f} 元",
                "recommendation": "建议使用VWAP/TWAP算法拆分大单，减少市场冲击",
                "expected_improvement": "预计可降低缺口30-50%",
            })

        # 分析市场冲击
        avg_impact = sum(c.market_impact for c in costs) / len(costs) if costs else 0
        avg_total = sum(c.total_cost for c in costs) / len(costs) if costs else 0

        if avg_impact > avg_total * 0.3:
            recommendations.append({
                "category": "impact",
                "priority": "high",
                "issue": f"市场冲击成本占比过高 ({avg_impact/avg_total*100:.1f}%)",
                "recommendation": "降低单笔交易规模，提高交易频率，或使用暗池",
                "expected_improvement": "预计可降低冲击成本40%",
            })

        # 分析时机成本
        avg_timing = sum(c.timing_cost for c in costs) / len(costs) if costs else 0

        if abs(avg_timing) > avg_total * 0.2:
            recommendations.append({
                "category": "timing",
                "priority": "medium",
                "issue": f"时机成本显著 ({avg_timing:.2f} 元)",
                "recommendation": "优化交易时机选择，避开市场波动剧烈时段",
                "expected_improvement": "预计可降低时机成本30%",
            })

        # 分析延迟成本
        avg_delay = sum(c.delay_cost for c in costs) / len(costs) if costs else 0

        if avg_delay > avg_total * 0.1:
            recommendations.append({
                "category": "latency",
                "priority": "medium",
                "issue": f"延迟成本较高 ({avg_delay:.2f} 元)",
                "recommendation": "使用低延迟交易通道，或部署边缘计算节点",
                "expected_improvement": "预计可降低延迟成本50%",
            })

        # 通用建议
        recommendations.extend(self._generate_general_recommendations(trades))

        self._recommendations = recommendations
        return recommendations

    def _generate_general_recommendations(self, trades: List[TradeExecution]) -> List[Dict]:
        """生成通用建议"""
        recommendations = []

        # 检查交易规模分布
        volumes = [t.filled_quantity for t in trades]
        if volumes:
            avg_volume = sum(volumes) / len(volumes)
            max_volume = max(volumes)

            if max_volume > avg_volume * 5:
                recommendations.append({
                    "category": "sizing",
                    "priority": "low",
                    "issue": "存在异常大额交易",
                    "recommendation": "对大额交易进行预先拆单",
                    "expected_improvement": "降低大单冲击风险",
                })

        return recommendations

    def generate_report(self) -> str:
        """生成报告"""
        if not self._recommendations:
            return "当前交易执行质量良好，无需特别优化。"

        report = "# 交易成本优化建议报告\n\n"

        for i, rec in enumerate(self._recommendations, 1):
            report += f"## {i}. {rec['category'].upper()} - {rec['priority'].upper()}\n"
            report += f"**问题**: {rec['issue']}\n\n"
            report += f"**建议**: {rec['recommendation']}\n\n"
            report += f"**预期效果**: {rec['expected_improvement']}\n\n"
            report += "---\n\n"

        return report


# ============ TCA分析器 ============

class TCAAnalyzer:
    """交易成本分析器"""

    def __init__(self):
        self.shortfall_analyzer = ImplementationShortfallAnalyzer()
        self.implicit_analyzer = ImplicitCostAnalyzer()
        self.quality_scorer = ExecutionQualityScorer()
        self.optimizer = OptimizationAdvisor()

        self._trades: List[TradeExecution] = []
        self._costs: List[CostBreakdown] = []

    def analyze_trade(self, trade: TradeExecution) -> Dict:
        """分析单笔交易"""
        # 计算实现缺口
        self.shortfall_analyzer.add_trade(trade)
        shortfall = self.shortfall_analyzer.get_trade_analysis(trade.trade_id)

        # 计算隐性成本
        cost = self.implicit_analyzer.analyze(trade)

        # 评分
        if shortfall:
            is_obj = ImplementationShortfall(
                trade_id=shortfall["trade_id"],
                decision_price=shortfall["decision_price"],
                arrival_price=shortfall["arrival_price"],
                execution_price=shortfall["execution_price"],
                quantity=trade.filled_quantity,
                total_shortfall=shortfall["total_shortfall"],
                trading_cost=shortfall["trading_cost"],
                timing_cost=shortfall["timing_cost"],
                opportunity_cost=shortfall["opportunity_cost"],
            )
            score = self.quality_scorer.score_trade(trade, is_obj)
        else:
            score = {}

        self._trades.append(trade)
        self._costs.append(cost)

        return {
            "trade_id": trade.trade_id,
            "shortfall": shortfall,
            "cost_breakdown": cost.to_dict(),
            "score": score,
        }

    def analyze_portfolio(self) -> Dict:
        """分析组合"""
        # 汇总缺口
        shortfall_summary = self.shortfall_analyzer.get_summary()

        # 汇总成本
        cost_summary = self.implicit_analyzer.get_aggregate_costs()

        # 组合评分
        quality_summary = self.quality_scorer.score_portfolio(self._trades)

        # 优化建议
        shortfalls = [
            ImplementationShortfall(
                trade_id=s["trade_id"],
                decision_price=s["decision_price"],
                arrival_price=s["arrival_price"],
                execution_price=s["execution_price"],
                quantity=0,
                total_shortfall=s["total_shortfall"],
                trading_cost=s["trading_cost"],
                timing_cost=s["timing_cost"],
                opportunity_cost=s["opportunity_cost"],
            )
            for s in [self.shortfall_analyzer.get_trade_analysis(t.trade_id) for t in self._trades]
            if s
        ]

        recommendations = self.optimizer.analyze_and_recommend(
            self._trades, shortfalls, self._costs
        )

        return {
            "shortfall_summary": shortfall_summary,
            "cost_summary": cost_summary,
            "quality_summary": quality_summary,
            "recommendations": recommendations,
            "trade_count": len(self._trades),
        }

    def generate_report(self) -> str:
        """生成完整报告"""
        analysis = self.analyze_portfolio()

        report = f"""
# 交易成本分析报告

## 1. 实现缺口分析
- 总缺口: {analysis['shortfall_summary'].get('total_shortfall', 0):.2f} 元
- 交易成本: {analysis['shortfall_summary'].get('total_trading_cost', 0):.2f} 元
- 时机成本: {analysis['shortfall_summary'].get('total_timing_cost', 0):.2f} 元
- 缺口基点: {analysis['shortfall_summary'].get('shortfall_bps', 0):.2f} bps

## 2. 隐性成本分解
- 平均总成本: {analysis['cost_summary'].get('avg_total_cost', 0):.2f} 元
- 平均佣金: {analysis['cost_summary'].get('avg_commission', 0):.2f} 元
- 平均价差: {analysis['cost_summary'].get('avg_spread_cost', 0):.2f} 元
- 平均冲击: {analysis['cost_summary'].get('avg_market_impact', 0):.2f} 元

## 3. 执行质量评分
- 平均缺口: {analysis['quality_summary'].get('avg_shortfall_bps', 0):.2f} bps
- 质量等级: {analysis['quality_summary'].get('quality', 'N/A')}

## 4. 优化建议
{self.optimizer.generate_report()}
"""
        return report


# ============ 便捷函数 ============

def create_tca_analyzer() -> TCAAnalyzer:
    """创建TCA分析器"""
    return TCAAnalyzer()


def analyze_trade_cost(trade: TradeExecution) -> Dict:
    """分析单笔交易成本"""
    analyzer = TCAAnalyzer()
    return analyzer.analyze_trade(trade)


def calculate_implementation_shortfall(
    decision_price: float,
    execution_price: float,
    quantity: int,
    side: str,
) -> float:
    """计算实现缺口"""
    if side == "buy":
        return (execution_price - decision_price) * quantity
    else:
        return (decision_price - execution_price) * quantity
