"""西部量化可转债策略 V3.0 策略性能分析器模块

功能:
- 收益归因分析
- Brinson归因模型
- 风险归因
- 因子暴露分析
- 业绩评估
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import math
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AttributionType(str, Enum):
    """归因类型"""
    BRINSON = "brinson"         # Brinson归因
    FACTOR = "factor"           # 因子归因
    RISK = "risk"               # 风险归因
    TRANSACTION = "transaction" # 交易归因


class PerformanceMetric(str, Enum):
    """业绩指标"""
    TOTAL_RETURN = "total_return"
    ANNUALIZED_RETURN = "annualized_return"
    VOLATILITY = "volatility"
    SHARPE_RATIO = "sharpe_ratio"
    MAX_DRAWDOWN = "max_drawdown"
    SORTINO_RATIO = "sortino_ratio"
    CALMAR_RATIO = "calmar_ratio"
    INFORMATION_RATIO = "information_ratio"
    TRACKING_ERROR = "tracking_error"
    ALPHA = "alpha"
    BETA = "beta"


# ============ 数据模型 ============

@dataclass
class PortfolioSnapshot:
    """组合快照"""
    date: datetime
    total_value: float
    cash: float
    positions: Dict[str, float]  # code -> market_value
    weights: Dict[str, float]    # code -> weight
    daily_return: float = 0

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "total_value": self.total_value,
            "cash": self.cash,
            "positions": self.positions,
            "weights": self.weights,
            "daily_return": round(self.daily_return, 6),
        }


@dataclass
class BenchmarkSnapshot:
    """基准快照"""
    date: datetime
    total_return: float
    sector_weights: Dict[str, float]
    sector_returns: Dict[str, float]

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "total_return": self.total_return,
            "sector_weights": self.sector_weights,
            "sector_returns": self.sector_returns,
        }


@dataclass
class BrinsonAttribution:
    """Brinson归因结果"""
    allocation_effect: float      # 配置效应
    selection_effect: float       # 选股效应
    interaction_effect: float     # 交互效应
    total_active_return: float    # 总主动收益
    sector_breakdown: Dict[str, Dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "allocation_effect": round(self.allocation_effect, 6),
            "selection_effect": round(self.selection_effect, 6),
            "interaction_effect": round(self.interaction_effect, 6),
            "total_active_return": round(self.total_active_return, 6),
            "sector_breakdown": self.sector_breakdown,
        }


@dataclass
class FactorExposure:
    """因子暴露"""
    factor_name: str
    exposure: float
    contribution: float
    risk: float
    marginal_contribution: float

    def to_dict(self) -> dict:
        return {
            "factor": self.factor_name,
            "exposure": round(self.exposure, 4),
            "contribution": round(self.contribution, 6),
            "risk": round(self.risk, 6),
            "marginal_contribution": round(self.marginal_contribution, 6),
        }


@dataclass
class PerformanceReport:
    """业绩报告"""
    period_start: datetime
    period_end: datetime
    total_return: float
    benchmark_return: float
    excess_return: float
    annualized_return: float
    volatility: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    attribution: BrinsonAttribution = None
    factor_exposures: List[FactorExposure] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_return": round(self.total_return, 6),
            "benchmark_return": round(self.benchmark_return, 6),
            "excess_return": round(self.excess_return, 6),
            "annualized_return": round(self.annualized_return, 6),
            "volatility": round(self.volatility, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 6),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "attribution": self.attribution.to_dict() if self.attribution else None,
            "factor_exposures": [f.to_dict() for f in self.factor_exposures],
        }


# ============ Brinson归因模型 ============

class BrinsonAttributionModel:
    """Brinson归因模型"""

    def __init__(self):
        self._portfolio_returns: List[Dict] = []
        self._benchmark_returns: List[Dict] = []

    def add_period(
        self,
        portfolio_weights: Dict[str, float],
        portfolio_returns: Dict[str, float],
        benchmark_weights: Dict[str, float],
        benchmark_returns: Dict[str, float],
    ):
        """添加期间数据"""
        self._portfolio_returns.append({
            "weights": portfolio_weights,
            "returns": portfolio_returns,
        })
        self._benchmark_returns.append({
            "weights": benchmark_weights,
            "returns": benchmark_returns,
        })

    def calculate_attribution(self) -> BrinsonAttribution:
        """计算归因"""
        # 聚合所有期间
        portfolio_weight = {}
        portfolio_return = {}
        benchmark_weight = {}
        benchmark_return = {}

        # 取平均值
        for period in self._portfolio_returns:
            for sector, w in period["weights"].items():
                portfolio_weight[sector] = portfolio_weight.get(sector, 0) + w / len(self._portfolio_returns)
            for sector, r in period["returns"].items():
                portfolio_return[sector] = portfolio_return.get(sector, 0) + r / len(self._portfolio_returns)

        for period in self._benchmark_returns:
            for sector, w in period["weights"].items():
                benchmark_weight[sector] = benchmark_weight.get(sector, 0) + w / len(self._benchmark_returns)
            for sector, r in period["returns"].items():
                benchmark_return[sector] = benchmark_return.get(sector, 0) + r / len(self._benchmark_returns)

        # 计算配置效应
        allocation_effect = 0
        selection_effect = 0
        interaction_effect = 0
        sector_breakdown = {}

        all_sectors = set(portfolio_weight.keys()) | set(benchmark_weight.keys())

        for sector in all_sectors:
            wp = portfolio_weight.get(sector, 0)
            wb = benchmark_weight.get(sector, 0)
            rp = portfolio_return.get(sector, 0)
            rb = benchmark_return.get(sector, 0)

            # 配置效应 = (组合权重 - 基准权重) * (基准收益 - 基准总收益)
            bench_total = sum(benchmark_weight.get(s, 0) * benchmark_return.get(s, 0) for s in all_sectors)
            alloc = (wp - wb) * (rb - bench_total)

            # 选股效应 = 基准权重 * (组合收益 - 基准收益)
            select = wb * (rp - rb)

            # 交互效应 = (组合权重 - 基准权重) * (组合收益 - 基准收益)
            interact = (wp - wb) * (rp - rb)

            allocation_effect += alloc
            selection_effect += select
            interaction_effect += interact

            sector_breakdown[sector] = {
                "allocation": round(alloc, 6),
                "selection": round(select, 6),
                "interaction": round(interact, 6),
                "portfolio_weight": round(wp, 4),
                "benchmark_weight": round(wb, 4),
            }

        total_active = allocation_effect + selection_effect + interaction_effect

        return BrinsonAttribution(
            allocation_effect=allocation_effect,
            selection_effect=selection_effect,
            interaction_effect=interaction_effect,
            total_active_return=total_active,
            sector_breakdown=sector_breakdown,
        )


# ============ 因子归因模型 ============

class FactorAttributionModel:
    """因子归因模型"""

    # 定义因子
    FACTORS = [
        "market",        # 市场因子
        "size",          # 规模因子
        "value",         # 价值因子
        "momentum",      # 动量因子
        "quality",       # 质量因子
        "low_vol",       # 低波动因子
        "liquidity",     # 流动性因子
    ]

    def __init__(self, factor_returns: Dict[str, List[float]] = None):
        self.factor_returns = factor_returns or {}
        self._exposures: Dict[str, List[float]] = defaultdict(list)

    def set_factor_returns(self, factor_returns: Dict[str, List[float]]):
        """设置因子收益"""
        self.factor_returns = factor_returns

    def calculate_exposures(
        self,
        portfolio_returns: List[float],
        factor_returns: Dict[str, List[float]],
    ) -> List[FactorExposure]:
        """计算因子暴露"""
        if not factor_returns or not portfolio_returns:
            return []

        # 转换为矩阵
        n = len(portfolio_returns)
        factor_names = list(factor_returns.keys())
        k = len(factor_names)

        # 构建因子收益矩阵
        X = np.zeros((n, k))
        for i, name in enumerate(factor_names):
            returns = factor_returns.get(name, [0] * n)
            X[:, i] = returns[:n]

        # 因变量
        y = np.array(portfolio_returns)

        # 多元回归
        try:
            # 添加截距
            X_with_intercept = np.column_stack([np.ones(n), X])

            # 最小二乘
            beta = np.linalg.lstsq(X_with_intercept, y, rcond=None)[0]

            intercept = beta[0]
            factor_betas = beta[1:]

            # 计算贡献
            exposures = []
            for i, name in enumerate(factor_names):
                exposure = factor_betas[i]
                contribution = exposure * np.mean(factor_returns.get(name, [0]))

                # 计算风险贡献
                factor_std = np.std(factor_returns.get(name, [0]))
                risk = abs(exposure) * factor_std

                exposures.append(FactorExposure(
                    factor_name=name,
                    exposure=exposure,
                    contribution=contribution,
                    risk=risk,
                    marginal_contribution=contribution / risk if risk > 0 else 0,
                ))

            return exposures

        except Exception as e:
            logger.error(f"[FactorAttribution] 回归失败: {e}")
            return []

    def decompose_return(
        self,
        portfolio_return: float,
        exposures: List[FactorExposure],
    ) -> Dict[str, float]:
        """分解收益"""
        decomposition = {
            "total_return": portfolio_return,
            "factor_contribution": 0,
            "idiosyncratic": portfolio_return,
        }

        for exp in exposures:
            decomposition[f"factor_{exp.factor_name}"] = exp.contribution
            decomposition["factor_contribution"] += exp.contribution
            decomposition["idiosyncratic"] -= exp.contribution

        return decomposition


# ============ 风险归因模型 ============

class RiskAttributionModel:
    """风险归因模型"""

    def __init__(self):
        self._covariance_matrix: np.ndarray = None
        self._factor_loadings: Dict[str, np.ndarray] = {}

    def set_covariance_matrix(self, cov_matrix: np.ndarray):
        """设置协方差矩阵"""
        self._covariance_matrix = cov_matrix

    def set_factor_loadings(self, code: str, loadings: np.ndarray):
        """设置因子载荷"""
        self._factor_loadings[code] = loadings

    def calculate_risk_decomposition(
        self,
        positions: Dict[str, float],  # code -> weight
        factor_covariance: np.ndarray = None,
    ) -> Dict[str, Any]:
        """计算风险分解"""
        if not positions:
            return {}

        # 构建权重向量
        codes = list(positions.keys())
        weights = np.array([positions[c] for c in codes])

        # 计算组合方差
        if self._covariance_matrix is not None:
            portfolio_variance = weights @ self._covariance_matrix @ weights.T
        else:
            portfolio_variance = np.var(weights)  # 简化

        portfolio_vol = np.sqrt(portfolio_variance)

        # 边际风险贡献
        marginal_contributions = {}
        for i, code in enumerate(codes):
            # MCR_i = w_i * Cov_i,p / sigma_p
            if self._covariance_matrix is not None:
                cov_ip = self._covariance_matrix[i] @ weights
                mcr = weights[i] * cov_ip / portfolio_vol if portfolio_vol > 0 else 0
            else:
                mcr = weights[i] * portfolio_vol / len(codes)

            marginal_contributions[code] = {
                "weight": round(weights[i], 4),
                "marginal_risk": round(mcr, 6),
                "risk_contribution": round(mcr / portfolio_vol if portfolio_vol > 0 else 0, 4),
            }

        return {
            "portfolio_volatility": round(portfolio_vol, 6),
            "marginal_contributions": marginal_contributions,
        }


# ============ 业绩分析器 ============

class PerformanceAnalyzer:
    """业绩分析器"""

    def __init__(self, risk_free_rate: float = 0.03):
        self.risk_free_rate = risk_free_rate
        self.brinson_model = BrinsonAttributionModel()
        self.factor_model = FactorAttributionModel()
        self.risk_model = RiskAttributionModel()

        self._portfolio_history: List[PortfolioSnapshot] = []
        self._benchmark_history: List[BenchmarkSnapshot] = []

    def add_portfolio_snapshot(self, snapshot: PortfolioSnapshot):
        """添加组合快照"""
        self._portfolio_history.append(snapshot)

    def add_benchmark_snapshot(self, snapshot: BenchmarkSnapshot):
        """添加基准快照"""
        self._benchmark_history.append(snapshot)

    def calculate_metrics(self) -> Dict[str, float]:
        """计算业绩指标"""
        if len(self._portfolio_history) < 2:
            return {}

        returns = [s.daily_return for s in self._portfolio_history[1:]]
        benchmark_returns = [s.total_return for s in self._benchmark_history] if self._benchmark_history else [0] * len(returns)

        # 总收益
        total_return = (1 + sum(returns)) - 1

        # 年化收益
        days = len(returns)
        annualized_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0

        # 波动率
        volatility = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0

        # Sharpe比率
        excess_returns = [r - self.risk_free_rate / 252 for r in returns]
        sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252) if len(excess_returns) > 1 and np.std(excess_returns) > 0 else 0

        # 最大回撤
        cumulative = [1]
        for r in returns:
            cumulative.append(cumulative[-1] * (1 + r))

        peak = cumulative[0]
        max_dd = 0
        for c in cumulative:
            if c > peak:
                peak = c
            dd = (peak - c) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Sortino比率
        downside_returns = [r for r in returns if r < 0]
        downside_std = np.std(downside_returns) * np.sqrt(252) if downside_returns else 0
        sortino = (annualized_return - self.risk_free_rate) / downside_std if downside_std > 0 else 0

        # Calmar比率
        calmar = annualized_return / max_dd if max_dd > 0 else 0

        # 胜率
        positive_days = sum(1 for r in returns if r > 0)
        win_rate = positive_days / len(returns) if returns else 0

        # 盈亏比
        gains = sum(r for r in returns if r > 0)
        losses = abs(sum(r for r in returns if r < 0))
        profit_factor = gains / losses if losses > 0 else float('inf')

        # Alpha和Beta
        if benchmark_returns and len(benchmark_returns) == len(returns):
            cov_matrix = np.cov(returns, benchmark_returns)
            beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 0
            alpha = annualized_return - self.risk_free_rate - beta * (np.mean(benchmark_returns) * 252 - self.risk_free_rate)
        else:
            alpha, beta = 0, 1

        # 信息比率
        active_returns = [r - b for r, b in zip(returns, benchmark_returns)] if benchmark_returns else returns
        tracking_error = np.std(active_returns) * np.sqrt(252) if len(active_returns) > 1 else 0
        information_ratio = (annualized_return - np.mean(benchmark_returns) * 252) / tracking_error if tracking_error > 0 else 0

        return {
            PerformanceMetric.TOTAL_RETURN.value: round(total_return, 6),
            PerformanceMetric.ANNUALIZED_RETURN.value: round(annualized_return, 6),
            PerformanceMetric.VOLATILITY.value: round(volatility, 6),
            PerformanceMetric.SHARPE_RATIO.value: round(sharpe, 4),
            PerformanceMetric.MAX_DRAWDOWN.value: round(max_dd, 6),
            PerformanceMetric.SORTINO_RATIO.value: round(sortino, 4),
            PerformanceMetric.CALMAR_RATIO.value: round(calmar, 4),
            PerformanceMetric.WIN_RATE.value: round(win_rate, 4),
            PerformanceMetric.PROFIT_FACTOR.value: round(profit_factor, 4),
            PerformanceMetric.ALPHA.value: round(alpha, 6),
            PerformanceMetric.BETA.value: round(beta, 4),
            PerformanceMetric.INFORMATION_RATIO.value: round(information_ratio, 4),
            PerformanceMetric.TRACKING_ERROR.value: round(tracking_error, 6),
        }

    def generate_report(
        self,
        period_start: datetime = None,
        period_end: datetime = None,
    ) -> PerformanceReport:
        """生成报告"""
        if not self._portfolio_history:
            return None

        period_start = period_start or self._portfolio_history[0].date
        period_end = period_end or self._portfolio_history[-1].date

        metrics = self.calculate_metrics()

        # Brinson归因
        if self._benchmark_history:
            attribution = self.brinson_model.calculate_attribution()
        else:
            attribution = None

        # 因子暴露
        returns = [s.daily_return for s in self._portfolio_history[1:]]
        if self.factor_model.factor_returns:
            factor_exposures = self.factor_model.calculate_exposures(
                returns, self.factor_model.factor_returns
            )
        else:
            factor_exposures = []

        return PerformanceReport(
            period_start=period_start,
            period_end=period_end,
            total_return=metrics.get(PerformanceMetric.TOTAL_RETURN.value, 0),
            benchmark_return=0,  # 需要基准数据
            excess_return=metrics.get(PerformanceMetric.TOTAL_RETURN.value, 0),
            annualized_return=metrics.get(PerformanceMetric.ANNUALIZED_RETURN.value, 0),
            volatility=metrics.get(PerformanceMetric.VOLATILITY.value, 0),
            sharpe_ratio=metrics.get(PerformanceMetric.SHARPE_RATIO.value, 0),
            max_drawdown=metrics.get(PerformanceMetric.MAX_DRAWDOWN.value, 0),
            win_rate=metrics.get(PerformanceMetric.WIN_RATE.value, 0),
            profit_factor=metrics.get(PerformanceMetric.PROFIT_FACTOR.value, 0),
            attribution=attribution,
            factor_exposures=factor_exposures,
        )

    def calculate_rolling_sharpe(self, window: int = 60) -> List[Tuple[datetime, float]]:
        """计算滚动夏普"""
        if len(self._portfolio_history) < window:
            return []

        results = []
        returns = [s.daily_return for s in self._portfolio_history]

        for i in range(window, len(returns)):
            window_returns = returns[i-window:i]
            excess = [r - self.risk_free_rate / 252 for r in window_returns]

            sharpe = np.mean(excess) / np.std(excess) * np.sqrt(252) if np.std(excess) > 0 else 0

            results.append((self._portfolio_history[i].date, sharpe))

        return results

    def calculate_rolling_volatility(self, window: int = 20) -> List[Tuple[datetime, float]]:
        """计算滚动波动率"""
        if len(self._portfolio_history) < window:
            return []

        results = []
        returns = [s.daily_return for s in self._portfolio_history]

        for i in range(window, len(returns)):
            window_returns = returns[i-window:i]
            vol = np.std(window_returns) * np.sqrt(252)
            results.append((self._portfolio_history[i].date, vol))

        return results


# ============ 便捷函数 ============

def create_performance_analyzer(risk_free_rate: float = 0.03) -> PerformanceAnalyzer:
    """创建业绩分析器"""
    return PerformanceAnalyzer(risk_free_rate)


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.03) -> float:
    """计算夏普比率"""
    if not returns or len(returns) < 2:
        return 0

    excess = [r - risk_free_rate / 252 for r in returns]
    return np.mean(excess) / np.std(excess) * np.sqrt(252) if np.std(excess) > 0 else 0


def calculate_max_drawdown(returns: List[float]) -> float:
    """计算最大回撤"""
    if not returns:
        return 0

    cumulative = [1]
    for r in returns:
        cumulative.append(cumulative[-1] * (1 + r))

    peak = cumulative[0]
    max_dd = 0

    for c in cumulative:
        if c > peak:
            peak = c
        dd = (peak - c) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return max_dd


def calculate_sortino_ratio(returns: List[float], risk_free_rate: float = 0.03) -> float:
    """计算Sortino比率"""
    if not returns:
        return 0

    downside = [r for r in returns if r < 0]
    if not downside:
        return float('inf')

    downside_std = np.std(downside) * np.sqrt(252)
    annualized_return = np.mean(returns) * 252

    return (annualized_return - risk_free_rate) / downside_std if downside_std > 0 else 0
