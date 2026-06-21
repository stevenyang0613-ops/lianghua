"""西部量化可转债策略 V3.0 归因分析与监控

日度监控仪表板:
- 日内换手率
- 交易成本/收益
- 实盘滑点/预估滑点
- 七维得分分布
- 行业集中度
- 组合日内回撤

周度因子分析:
- 因子IC值(Rank IC)
- 因子IC累计曲线
- 因子收益率
- 行业偏离度

月度Brinson归因:
- 配置效应(Allocation)
- 选券效应(Selection)
- 交互效应(Interaction)
- 交易成本效应
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from scipy import stats
import logging

from app.xb_strategy.core.types import Portfolio, Position, SevenDimScore, TradeSignal
from app.xb_strategy.config.settings import params

logger = logging.getLogger(__name__)


@dataclass
class DailyMetrics:
    """日度监控指标"""
    date: date
    turnover_rate: float  # 换手率
    cost_to_return: float  # 成本/收益比
    slippage_deviation: float  # 滑点偏差
    avg_score: float  # 平均七维得分
    median_score: float  # 中位数得分
    max_sector_concentration: float  # 最大行业集中度
    intraday_drawdown: float  # 日内回撤
    position_count: int  # 持仓数量

    alerts: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "turnover_rate": round(self.turnover_rate * 100, 2),
            "cost_to_return": round(self.cost_to_return * 100, 2),
            "slippage_deviation": round(self.slippage_deviation, 2),
            "avg_score": round(self.avg_score, 1),
            "median_score": round(self.median_score, 1),
            "max_sector_concentration": round(self.max_sector_concentration * 100, 2),
            "intraday_drawdown": round(self.intraday_drawdown * 100, 2),
            "position_count": self.position_count,
            "alerts": self.alerts,
        }


@dataclass
class FactorAnalysis:
    """因子分析结果"""
    factor_name: str
    ic: float  # Rank IC
    ic_ir: float  # IC信息比率
    factor_return: float  # 因子收益率
    turnover_contribution: float  # 换手贡献

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "ic": round(self.ic, 4),
            "ic_ir": round(self.ic_ir, 4),
            "factor_return": round(self.factor_return * 100, 2),
            "turnover_contribution": round(self.turnover_contribution * 100, 2),
        }


@dataclass
class BrinsonAttribution:
    """Brinson归因结果"""
    period_start: date
    period_end: date
    portfolio_return: float  # 组合收益
    benchmark_return: float  # 基准收益
    allocation_effect: float  # 配置效应
    selection_effect: float  # 选券效应
    interaction_effect: float  # 交互效应
    trading_cost_effect: float  # 交易成本效应
    total_excess: float  # 总超额

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "portfolio_return": round(self.portfolio_return * 100, 2),
            "benchmark_return": round(self.benchmark_return * 100, 2),
            "allocation_effect": round(self.allocation_effect * 100, 4),
            "selection_effect": round(self.selection_effect * 100, 4),
            "interaction_effect": round(self.interaction_effect * 100, 4),
            "trading_cost_effect": round(self.trading_cost_effect * 100, 4),
            "total_excess": round(self.total_excess * 100, 2),
        }


class DailyMonitor:
    """日度监控"""

    def __init__(self, aum: float = 10000.0):
        """初始化

        Args:
            aum: 资产规模(万元)
        """
        self.aum = aum
        self._metrics_history: List[DailyMetrics] = []

    def calculate_metrics(
        self,
        portfolio: Portfolio,
        scores: List[SevenDimScore],
        trades: List[TradeSignal],
        daily_return: float,
        daily_cost: float,
        estimated_slippage: float,
        actual_slippage: float,
        current_date: date,
    ) -> DailyMetrics:
        """计算日度指标

        Args:
            portfolio: 组合
            scores: 七维得分
            trades: 交易信号
            daily_return: 当日收益
            daily_cost: 当日成本
            estimated_slippage: 预估滑点
            actual_slippage: 实际滑点
            current_date: 当前日期

        Returns:
            DailyMetrics: 日度指标
        """
        alerts = []

        # 1. 换手率
        trade_value = sum(t.price * t.quantity for t in trades if t.action in ["buy", "sell"])
        turnover_rate = trade_value / (self.aum * 10000) if self.aum > 0 else 0

        if turnover_rate > params.max_daily_turnover:
            alerts.append(f"换手率{turnover_rate*100:.1f}%超过阈值{params.max_daily_turnover*100}%")

        # 2. 成本/收益比
        cost_to_return = abs(daily_cost / daily_return) if daily_return != 0 else 0

        if daily_return > 0 and cost_to_return > params.cost_to_return_max:
            alerts.append(f"成本/收益比{cost_to_return*100:.1f}%超过阈值")

        # 3. 滑点偏差
        slippage_deviation = actual_slippage / estimated_slippage if estimated_slippage > 0 else 1.0

        if slippage_deviation > params.slippage_deviation_max:
            alerts.append(f"滑点偏差{slippage_deviation:.1f}倍超过阈值")

        # 4. 七维得分分布
        score_values = [s.total_score for s in scores]
        avg_score = np.mean(score_values) if score_values else 0
        median_score = np.median(score_values) if score_values else 0

        if avg_score < 68:
            alerts.append(f"平均七维得分{avg_score:.1f}偏低")
        elif avg_score > 85:
            alerts.append(f"平均七维得分{avg_score:.1f}偏高，可能过拟合")

        # 5. 行业集中度
        sector_weights = portfolio.sector_positions
        max_sector_concentration = max(sector_weights.values()) if sector_weights else 0

        if max_sector_concentration > params.max_sector_position:
            alerts.append(f"最大行业集中度{max_sector_concentration*100:.1f}%超过阈值")

        # 6. 日内回撤(简化)
        intraday_drawdown = 0  # 需要日内数据

        metrics = DailyMetrics(
            date=current_date,
            turnover_rate=turnover_rate,
            cost_to_return=cost_to_return,
            slippage_deviation=slippage_deviation,
            avg_score=avg_score,
            median_score=median_score,
            max_sector_concentration=max_sector_concentration,
            intraday_drawdown=intraday_drawdown,
            position_count=len(portfolio.positions),
            alerts=alerts,
        )

        self._metrics_history.append(metrics)

        if alerts:
            logger.warning(f"[Monitor] {current_date} 告警: {alerts}")

        return metrics

    def get_metrics_history(self, days: int = 30) -> List[DailyMetrics]:
        """获取历史指标

        Args:
            days: 天数

        Returns:
            指标列表
        """
        return self._metrics_history[-days:]

    def get_summary(self) -> dict:
        """获取汇总指标

        Returns:
            汇总结果
        """
        if not self._metrics_history:
            return {}

        recent = self._metrics_history[-5:]
        return {
            "avg_turnover": np.mean([m.turnover_rate for m in recent]),
            "avg_cost_to_return": np.mean([m.cost_to_return for m in recent]),
            "avg_score": np.mean([m.avg_score for m in recent]),
            "total_alerts": sum(len(m.alerts) for m in self._metrics_history),
        }


class FactorAnalyzer:
    """周度因子分析"""

    def __init__(self):
        """初始化"""
        self._ic_history: Dict[str, List[float]] = {}
        self._factor_returns: Dict[str, List[float]] = {}

    def calculate_ic(
        self,
        scores: List[SevenDimScore],
        forward_returns: Dict[str, float],  # {code: return}
    ) -> Dict[str, float]:
        """计算因子IC值

        Args:
            scores: 七维得分
            forward_returns: 下期收益率

        Returns:
            各因子IC值
        """
        ics = {}

        # 总分IC
        score_df = pd.DataFrame([
            {"code": s.cb_code, "total_score": s.total_score}
            for s in scores
        ])
        return_df = pd.DataFrame([
            {"code": code, "return": ret}
            for code, ret in forward_returns.items()
        ])

        merged = score_df.merge(return_df, on="code", how="inner")

        if len(merged) > 10:
            ic, _ = stats.spearmanr(merged["total_score"], merged["return"])
            ics["total_score"] = ic if not np.isnan(ic) else 0

        # 各维度IC
        dimensions = [
            "short_momentum", "sector_sentiment", "technical",
            "chip_structure", "volatility", "news_factor", "fundamentals",
            "valuation", "clause_value", "liquidity", "credit",
        ]

        for dim in dimensions:
            dim_scores = [
                {"code": s.cb_code, dim: getattr(s, dim, 0)}
                for s in scores
            ]
            dim_df = pd.DataFrame(dim_scores)
            merged_dim = dim_df.merge(return_df, on="code", how="inner")

            if len(merged_dim) > 10:
                ic, _ = stats.spearmanr(merged_dim[dim], merged_dim["return"])
                ics[dim] = ic if not np.isnan(ic) else 0

        # 记录历史
        for factor, ic in ics.items():
            if factor not in self._ic_history:
                self._ic_history[factor] = []
            self._ic_history[factor].append(ic)

        return ics

    def get_factor_analysis(self) -> List[FactorAnalysis]:
        """获取因子分析结果

        Returns:
            因子分析列表
        """
        results = []

        for factor, ic_history in self._ic_history.items():
            if not ic_history:
                continue

            avg_ic = np.mean(ic_history)
            ic_ir = np.mean(ic_history) / np.std(ic_history) if np.std(ic_history) > 0 else 0

            results.append(FactorAnalysis(
                factor_name=factor,
                ic=avg_ic,
                ic_ir=ic_ir,
                factor_return=0,  # 需要多空组合计算
                turnover_contribution=0,
            ))

        return results

    def check_factor_validity(self) -> Dict[str, str]:
        """检查因子有效性

        Returns:
            {因子名: 状态}
        """
        status = {}

        for factor, ic_history in self._ic_history.items():
            if len(ic_history) < 3:
                status[factor] = "数据不足"
                continue

            recent_ic = np.mean(ic_history[-3:])

            if abs(recent_ic) < 0.03:
                status[factor] = f"IC过低({recent_ic:.3f})，可能失效"
            elif recent_ic > 0.05:
                status[factor] = f"有效(IC={recent_ic:.3f})"
            else:
                status[factor] = f"一般(IC={recent_ic:.3f})"

        return status


class BrinsonAttributor:
    """月度Brinson归因"""

    def calculate_attribution(
        self,
        portfolio: Portfolio,
        portfolio_return: float,
        benchmark_weights: Dict[str, float],  # {行业: 权重}
        benchmark_returns: Dict[str, float],  # {行业: 收益}
        portfolio_sector_weights: Dict[str, float],
        portfolio_sector_returns: Dict[str, float],
        trading_cost: float,
        period_start: date,
        period_end: date,
    ) -> BrinsonAttribution:
        """计算Brinson归因

        Args:
            portfolio: 组合
            portfolio_return: 组合收益
            benchmark_weights: 基准行业权重
            benchmark_returns: 基准行业收益
            portfolio_sector_weights: 组合行业权重
            portfolio_sector_returns: 组合行业收益
            trading_cost: 交易成本
            period_start: 开始日期
            period_end: 结束日期

        Returns:
            BrinsonAttribution: 归因结果
        """
        # 基准总收益
        benchmark_return = sum(
            benchmark_weights.get(sector, 0) * ret
            for sector, ret in benchmark_returns.items()
        )

        # 配置效应
        # (组合权重 - 基准权重) × (基准收益 - 基准总收益)
        allocation_effect = 0
        all_sectors = set(benchmark_weights.keys()) | set(portfolio_sector_weights.keys())

        for sector in all_sectors:
            pw = portfolio_sector_weights.get(sector, 0)
            bw = benchmark_weights.get(sector, 0)
            br = benchmark_returns.get(sector, 0)

            allocation_effect += (pw - bw) * (br - benchmark_return)

        # 选券效应
        # 基准权重 × (组合收益 - 基准收益)
        selection_effect = 0
        for sector in all_sectors:
            bw = benchmark_weights.get(sector, 0)
            pr = portfolio_sector_returns.get(sector, 0)
            br = benchmark_returns.get(sector, 0)

            selection_effect += bw * (pr - br)

        # 交互效应
        # (组合权重 - 基准权重) × (组合收益 - 基准收益)
        interaction_effect = 0
        for sector in all_sectors:
            pw = portfolio_sector_weights.get(sector, 0)
            bw = benchmark_weights.get(sector, 0)
            pr = portfolio_sector_returns.get(sector, 0)
            br = benchmark_returns.get(sector, 0)

            interaction_effect += (pw - bw) * (pr - br)

        # 交易成本效应
        trading_cost_effect = -trading_cost / (self.aum * 10000) if hasattr(self, 'aum') else -trading_cost / 10000

        # 总超额
        total_excess = allocation_effect + selection_effect + interaction_effect + trading_cost_effect

        return BrinsonAttribution(
            period_start=period_start,
            period_end=period_end,
            portfolio_return=portfolio_return,
            benchmark_return=benchmark_return,
            allocation_effect=allocation_effect,
            selection_effect=selection_effect,
            interaction_effect=interaction_effect,
            trading_cost_effect=trading_cost_effect,
            total_excess=total_excess,
        )


class DeviationTracker:
    """实盘-回测偏差追踪"""

    def __init__(self):
        """初始化"""
        self._signal_overlaps: List[float] = []
        self._price_deviations: List[float] = []
        self._position_deviations: List[int] = []

    def record_signal_overlap(
        self,
        live_signals: List[str],
        backtest_signals: List[str],
    ) -> float:
        """记录信号重合率

        Args:
            live_signals: 实盘信号代码列表
            backtest_signals: 回测信号代码列表

        Returns:
            重合率
        """
        if not live_signals and not backtest_signals:
            return 1.0

        live_set = set(live_signals)
        bt_set = set(backtest_signals)

        intersection = len(live_set & bt_set)
        union = len(live_set | bt_set)

        overlap = intersection / union if union > 0 else 0
        self._signal_overlaps.append(overlap)

        return overlap

    def record_price_deviation(
        self,
        live_price: float,
        backtest_price: float,
    ) -> float:
        """记录价格偏差

        Args:
            live_price: 实盘价格
            backtest_price: 回测价格

        Returns:
            偏差率
        """
        if backtest_price == 0:
            return 0

        deviation = abs(live_price - backtest_price) / backtest_price
        self._price_deviations.append(deviation)

        return deviation

    def check_deviation_alerts(self) -> List[str]:
        """检查偏差告警

        Returns:
            告警列表
        """
        alerts = []

        # 信号重合率检查
        if self._signal_overlaps:
            recent_overlap = np.mean(self._signal_overlaps[-5:])
            if recent_overlap < params.min_signal_overlap:
                alerts.append(f"信号重合率{recent_overlap*100:.1f}%低于阈值{params.min_signal_overlap*100}%")

        # 价格偏差检查
        if self._price_deviations:
            recent_deviation = np.mean(self._price_deviations[-5:])
            if recent_deviation > 0.005:
                alerts.append(f"价格偏差{recent_deviation*100:.2f}%连续5日超过0.5%")

        return alerts

    def get_deviation_report(self) -> dict:
        """获取偏差报告

        Returns:
            报告内容
        """
        return {
            "avg_signal_overlap": np.mean(self._signal_overlaps) if self._signal_overlaps else 0,
            "avg_price_deviation": np.mean(self._price_deviations) if self._price_deviations else 0,
            "signal_overlap_history": self._signal_overlaps[-30:],
            "price_deviation_history": self._price_deviations[-30:],
        }
