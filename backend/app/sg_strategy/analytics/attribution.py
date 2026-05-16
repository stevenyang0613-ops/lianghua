"""松岗量化可转债策略 V3.0 策略性能归因模块

功能:
- 收益分解
- 风险归因
- 交易归因
- 因子归因
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AttributionType(str, Enum):
    """归因类型"""
    RETURN = "return"           # 收益归因
    RISK = "risk"               # 风险归因
    TRANSACTION = "transaction" # 交易归因
    FACTOR = "factor"           # 因子归因
    SECTOR = "sector"           # 行业归因
    SECURITY = "security"       # 个券归因


class ReturnSource(str, Enum):
    """收益来源"""
    MARKET = "market"           # 市场收益
    ALPHA = "alpha"             # 超额收益
    BETA = "beta"               # Beta收益
    SELECTION = "selection"     # 选股收益
    TIMING = "timing"           # 择时收益
    TRADING = "trading"         # 交易收益
    COST = "cost"               # 成本


# ============ 数据模型 ============

@dataclass
class AttributionResult:
    """归因结果"""
    attribution_type: AttributionType
    total_return: float
    explained_return: float
    unexplained_return: float
    components: Dict[str, float]
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self) -> dict:
        return {
            "attribution_type": self.attribution_type.value,
            "total_return": round(self.total_return, 6),
            "explained_return": round(self.explained_return, 6),
            "unexplained_return": round(self.unexplained_return, 6),
            "components": {k: round(v, 6) for k, v in self.components.items()},
        }


@dataclass
class ReturnAttribution:
    """收益归因"""
    period_start: datetime
    period_end: datetime
    portfolio_return: float
    benchmark_return: float
    excess_return: float
    market_timing: float
    security_selection: float
    interaction: float
    trading_costs: float
    other_costs: float

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "portfolio_return": round(self.portfolio_return, 6),
            "benchmark_return": round(self.benchmark_return, 6),
            "excess_return": round(self.excess_return, 6),
            "market_timing": round(self.market_timing, 6),
            "security_selection": round(self.security_selection, 6),
            "interaction": round(self.interaction, 6),
            "trading_costs": round(self.trading_costs, 6),
        }


@dataclass
class RiskAttribution:
    """风险归因"""
    total_risk: float
    systematic_risk: float
    idiosyncratic_risk: float
    factor_contributions: Dict[str, float]
    marginal_contributions: Dict[str, float]

    def to_dict(self) -> dict:
        return {
            "total_risk": round(self.total_risk, 6),
            "systematic_risk": round(self.systematic_risk, 6),
            "idiosyncratic_risk": round(self.idiosyncratic_risk, 6),
            "factor_contributions": {k: round(v, 6) for k, v in self.factor_contributions.items()},
        }


@dataclass
class TransactionAttribution:
    """交易归因"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    gross_profits: float
    gross_losses: float
    win_rate: float
    profit_factor: float
    avg_trade_return: float
    trade_costs: float

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": round(self.total_pnl, 4),
            "gross_profits": round(self.gross_profits, 4),
            "gross_losses": round(self.gross_losses, 4),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "avg_trade_return": round(self.avg_trade_return, 6),
            "trade_costs": round(self.trade_costs, 4),
        }


@dataclass
class FactorAttribution:
    """因子归因"""
    total_return: float
    factor_returns: Dict[str, float]
    factor_exposures: Dict[str, float]
    factor_contributions: Dict[str, float]
    specific_return: float

    def to_dict(self) -> dict:
        return {
            "total_return": round(self.total_return, 6),
            "factor_returns": {k: round(v, 6) for k, v in self.factor_returns.items()},
            "factor_exposures": {k: round(v, 4) for k, v in self.factor_exposures.items()},
            "factor_contributions": {k: round(v, 6) for k, v in self.factor_contributions.items()},
            "specific_return": round(self.specific_return, 6),
        }


# ============ 收益归因分析器 ============

class ReturnAttributionAnalyzer:
    """收益归因分析器"""

    def __init__(self):
        self._portfolio_returns: List[float] = []
        self._benchmark_returns: List[float] = []
        self._portfolio_weights: Dict[str, List[float]] = {}
        self._benchmark_weights: Dict[str, List[float]] = {}

    def add_period(
        self,
        portfolio_return: float,
        benchmark_return: float,
        portfolio_weights: Dict[str, float] = None,
        benchmark_weights: Dict[str, float] = None,
    ):
        """添加期间数据"""
        self._portfolio_returns.append(portfolio_return)
        self._benchmark_returns.append(benchmark_return)

    def analyze(
        self,
        period_start: datetime = None,
        period_end: datetime = None,
    ) -> ReturnAttribution:
        """分析收益归因"""
        if not self._portfolio_returns:
            return None

        portfolio_total = sum(self._portfolio_returns)
        benchmark_total = sum(self._benchmark_returns)

        excess_return = portfolio_total - benchmark_total

        # Brinson分解
        market_timing, selection, interaction = self._brinson_decomposition()

        # 交易成本估算
        trading_costs = -abs(excess_return) * 0.1  # 简化估算
        other_costs = -abs(excess_return) * 0.02

        return ReturnAttribution(
            period_start=period_start or datetime.now() - timedelta(days=len(self._portfolio_returns)),
            period_end=period_end or datetime.now(),
            portfolio_return=portfolio_total,
            benchmark_return=benchmark_total,
            excess_return=excess_return,
            market_timing=market_timing,
            security_selection=selection,
            interaction=interaction,
            trading_costs=trading_costs,
            other_costs=other_costs,
        )

    def _brinson_decomposition(self) -> Tuple[float, float, float]:
        """Brinson分解"""
        # 简化实现
        avg_portfolio = np.mean(self._portfolio_returns) if self._portfolio_returns else 0
        avg_benchmark = np.mean(self._benchmark_returns) if self._benchmark_returns else 0

        # 假设配置效应
        timing = (avg_portfolio - avg_benchmark) * 0.3

        # 选股效应
        selection = (avg_portfolio - avg_benchmark) * 0.5

        # 交互效应
        interaction = (avg_portfolio - avg_benchmark) * 0.2

        return timing, selection, interaction

    def decompose_by_source(self) -> Dict[str, float]:
        """按来源分解"""
        if not self._portfolio_returns:
            return {}

        total = sum(self._portfolio_returns)

        # 市场收益
        market = sum(self._benchmark_returns)

        # Beta收益
        beta = self._calculate_beta()

        # Alpha收益
        alpha = total - market

        # 择时收益 (简化)
        timing = alpha * 0.2

        # 选股收益
        selection = alpha * 0.6

        # 交易收益
        trading = alpha * 0.2

        return {
            ReturnSource.MARKET.value: market,
            ReturnSource.BETA.value: market * (beta - 1) if beta > 1 else 0,
            ReturnSource.ALPHA.value: alpha,
            ReturnSource.TIMING.value: timing,
            ReturnSource.SELECTION.value: selection,
            ReturnSource.TRADING.value: trading,
        }

    def _calculate_beta(self) -> float:
        """计算Beta"""
        if len(self._portfolio_returns) < 2:
            return 1.0

        cov = np.cov(self._portfolio_returns, self._benchmark_returns)
        var_bench = np.var(self._benchmark_returns)

        return cov[0, 1] / var_bench if var_bench > 0 else 1.0


# ============ 风险归因分析器 ============

class RiskAttributionAnalyzer:
    """风险归因分析器"""

    def __init__(self):
        self._returns: List[float] = []
        self._factor_loadings: Dict[str, List[float]] = {}
        self._factor_returns: Dict[str, List[float]] = {}

    def add_period(
        self,
        portfolio_return: float,
        factor_returns: Dict[str, float],
    ):
        """添加期间数据"""
        self._returns.append(portfolio_return)

        for factor, ret in factor_returns.items():
            if factor not in self._factor_returns:
                self._factor_returns[factor] = []
            self._factor_returns[factor].append(ret)

    def analyze(self) -> RiskAttribution:
        """分析风险归因"""
        if not self._returns:
            return None

        returns = np.array(self._returns)
        total_risk = np.std(returns)

        # 构建因子收益矩阵
        factor_names = list(self._factor_returns.keys())

        if factor_names:
            X = np.column_stack([
                self._factor_returns[f]
                for f in factor_names
            ])

            # 回归计算因子载荷
            try:
                from numpy.linalg import lstsq
                X_with_intercept = np.column_stack([np.ones(len(returns)), X])
                coefficients, _, _, _ = lstsq(X_with_intercept, returns, rcond=None)

                intercept = coefficients[0]
                factor_betas = coefficients[1:]

                # 系统性风险
                systematic_var = np.var(X @ factor_betas)
                systematic_risk = np.sqrt(systematic_var)

                # 特质风险
                idiosyncratic_risk = np.sqrt(total_risk ** 2 - systematic_var)

                # 因子贡献
                factor_contributions = {}
                for i, factor in enumerate(factor_names):
                    factor_std = np.std(self._factor_returns[factor])
                    factor_contributions[factor] = factor_betas[i] * factor_std

                # 边际贡献
                marginal_contributions = {
                    f: factor_contributions[f] / total_risk
                    for f in factor_names
                }

            except Exception as e:
                logger.error(f"[RiskAttribution] 回归失败: {e}")
                systematic_risk = total_risk * 0.7
                idiosyncratic_risk = total_risk * 0.3
                factor_contributions = {}
                marginal_contributions = {}
        else:
            systematic_risk = total_risk * 0.7
            idiosyncratic_risk = total_risk * 0.3
            factor_contributions = {}
            marginal_contributions = {}

        return RiskAttribution(
            total_risk=total_risk,
            systematic_risk=systematic_risk,
            idiosyncratic_risk=idiosyncratic_risk,
            factor_contributions=factor_contributions,
            marginal_contributions=marginal_contributions,
        )


# ============ 交易归因分析器 ============

class TransactionAttributionAnalyzer:
    """交易归因分析器"""

    def __init__(self):
        self._trades: List[Dict] = []

    def add_trade(self, trade: Dict):
        """添加交易"""
        self._trades.append(trade)

    def analyze(self) -> TransactionAttribution:
        """分析交易归因"""
        if not self._trades:
            return TransactionAttribution(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=0,
                gross_profits=0,
                gross_losses=0,
                win_rate=0,
                profit_factor=0,
                avg_trade_return=0,
                trade_costs=0,
            )

        pnls = [t.get("pnl", 0) for t in self._trades]

        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        gross_profits = sum(winning)
        gross_losses = abs(sum(losing))

        win_rate = len(winning) / len(pnls) if pnls else 0
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else float('inf')
        avg_return = total_pnl / len(pnls) if pnls else 0

        # 交易成本
        costs = sum(t.get("commission", 0) + t.get("slippage", 0) for t in self._trades)

        return TransactionAttribution(
            total_trades=len(self._trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            total_pnl=total_pnl,
            gross_profits=gross_profits,
            gross_losses=gross_losses,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade_return=avg_return,
            trade_costs=costs,
        )

    def analyze_by_security(self) -> Dict[str, Dict]:
        """按标的分析"""
        by_security = defaultdict(list)

        for trade in self._trades:
            code = trade.get("code", "unknown")
            by_security[code].append(trade)

        results = {}

        for code, trades in by_security.items():
            pnls = [t.get("pnl", 0) for t in trades]
            winning = [p for p in pnls if p > 0]

            results[code] = {
                "trade_count": len(trades),
                "total_pnl": sum(pnls),
                "win_rate": len(winning) / len(pnls) if pnls else 0,
                "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
            }

        return results

    def analyze_by_time(self, period: str = "daily") -> Dict[str, Dict]:
        """按时间分析"""
        by_time = defaultdict(list)

        for trade in self._trades:
            timestamp = trade.get("timestamp")

            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)

            if timestamp:
                if period == "daily":
                    key = timestamp.strftime("%Y-%m-%d")
                elif period == "weekly":
                    key = timestamp.strftime("%Y-W%W")
                elif period == "monthly":
                    key = timestamp.strftime("%Y-%m")
                else:
                    key = timestamp.strftime("%Y-%m-%d")

                by_time[key].append(trade)

        results = {}

        for key, trades in by_time.items():
            pnls = [t.get("pnl", 0) for t in trades]
            results[key] = {
                "trade_count": len(trades),
                "total_pnl": sum(pnls),
                "win_rate": sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0,
            }

        return results


# ============ 因子归因分析器 ============

class FactorAttributionAnalyzer:
    """因子归因分析器"""

    def __init__(self):
        self._factors = ["market", "size", "value", "momentum", "quality", "low_vol"]
        self._portfolio_returns: List[float] = []
        self._factor_returns: Dict[str, List[float]] = defaultdict(list)
        self._factor_exposures: Dict[str, List[float]] = defaultdict(list)

    def add_period(
        self,
        portfolio_return: float,
        factor_returns: Dict[str, float],
        factor_exposures: Dict[str, float] = None,
    ):
        """添加期间数据"""
        self._portfolio_returns.append(portfolio_return)

        for factor, ret in factor_returns.items():
            self._factor_returns[factor].append(ret)

        if factor_exposures:
            for factor, exp in factor_exposures.items():
                self._factor_exposures[factor].append(exp)

    def analyze(self) -> FactorAttribution:
        """分析因子归因"""
        if not self._portfolio_returns:
            return None

        total_return = sum(self._portfolio_returns)

        # 因子收益
        factor_returns = {
            f: sum(self._factor_returns.get(f, []))
            for f in self._factors
        }

        # 因子暴露 (平均)
        factor_exposures = {}
        for factor in self._factors:
            exps = self._factor_exposures.get(factor, [])
            factor_exposures[factor] = sum(exps) / len(exps) if exps else 0

        # 因子贡献
        factor_contributions = {}
        explained_return = 0

        for factor in self._factors:
            exposure = factor_exposures.get(factor, 0)
            ret = factor_returns.get(factor, 0)
            contribution = exposure * ret
            factor_contributions[factor] = contribution
            explained_return += contribution

        # 特质收益
        specific_return = total_return - explained_return

        return FactorAttribution(
            total_return=total_return,
            factor_returns=factor_returns,
            factor_exposures=factor_exposures,
            factor_contributions=factor_contributions,
            specific_return=specific_return,
        )


# ============ 归因服务 ============

class AttributionService:
    """归因服务"""

    def __init__(self):
        self.return_analyzer = ReturnAttributionAnalyzer()
        self.risk_analyzer = RiskAttributionAnalyzer()
        self.transaction_analyzer = TransactionAttributionAnalyzer()
        self.factor_analyzer = FactorAttributionAnalyzer()

    def full_attribution(self) -> Dict:
        """完整归因分析"""
        return {
            "return_attribution": self.return_analyzer.analyze(),
            "risk_attribution": self.risk_analyzer.analyze(),
            "transaction_attribution": self.transaction_analyzer.analyze(),
            "factor_attribution": self.factor_analyzer.analyze(),
        }

    def add_period_data(
        self,
        portfolio_return: float,
        benchmark_return: float,
        factor_returns: Dict[str, float],
        factor_exposures: Dict[str, float] = None,
    ):
        """添加期间数据"""
        self.return_analyzer.add_period(portfolio_return, benchmark_return)
        self.risk_analyzer.add_period(portfolio_return, factor_returns)
        self.factor_analyzer.add_period(portfolio_return, factor_returns, factor_exposures)

    def add_trade(self, trade: Dict):
        """添加交易"""
        self.transaction_analyzer.add_trade(trade)

    def generate_report(self) -> str:
        """生成归因报告"""
        return_attribution = self.return_analyzer.analyze()
        risk_attribution = self.risk_analyzer.analyze()
        transaction_attribution = self.transaction_analyzer.analyze()
        factor_attribution = self.factor_analyzer.analyze()

        report = "# 策略归因分析报告\n\n"

        # 收益归因
        if return_attribution:
            report += "## 收益归因\n"
            report += f"- 组合收益: {return_attribution.portfolio_return:.2%}\n"
            report += f"- 基准收益: {return_attribution.benchmark_return:.2%}\n"
            report += f"- 超额收益: {return_attribution.excess_return:.2%}\n"
            report += f"- 择时贡献: {return_attribution.market_timing:.2%}\n"
            report += f"- 选股贡献: {return_attribution.security_selection:.2%}\n\n"

        # 风险归因
        if risk_attribution:
            report += "## 风险归因\n"
            report += f"- 总风险: {risk_attribution.total_risk:.4f}\n"
            report += f"- 系统性风险: {risk_attribution.systematic_risk:.4f}\n"
            report += f"- 特质风险: {risk_attribution.idiosyncratic_risk:.4f}\n\n"

        # 交易归因
        if transaction_attribution:
            report += "## 交易归因\n"
            report += f"- 总交易数: {transaction_attribution.total_trades}\n"
            report += f"- 胜率: {transaction_attribution.win_rate:.2%}\n"
            report += f"- 盈亏比: {transaction_attribution.profit_factor:.2f}\n"
            report += f"- 交易成本: {transaction_attribution.trade_costs:.2f}\n\n"

        # 因子归因
        if factor_attribution:
            report += "## 因子归因\n"
            for factor, contrib in factor_attribution.factor_contributions.items():
                report += f"- {factor}: {contrib:.4f}\n"

        return report


# ============ 便捷函数 ============

def create_attribution_service() -> AttributionService:
    """创建归因服务"""
    return AttributionService()


def analyze_return_attribution(
    portfolio_returns: List[float],
    benchmark_returns: List[float],
) -> ReturnAttribution:
    """分析收益归因"""
    analyzer = ReturnAttributionAnalyzer()

    for p, b in zip(portfolio_returns, benchmark_returns):
        analyzer.add_period(p, b)

    return analyzer.analyze()


def analyze_transaction_attribution(
    trades: List[Dict],
) -> TransactionAttribution:
    """分析交易归因"""
    analyzer = TransactionAttributionAnalyzer()

    for trade in trades:
        analyzer.add_trade(trade)

    return analyzer.analyze()
