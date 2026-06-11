"""松岗量化可转债策略 V3.0 策略组合优化模块

功能:
- 均值方差优化
- 风险平价模型
- Black-Litterman模型
- 因子中性优化
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import math
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class OptimizationObjective(str, Enum):
    """优化目标"""
    MAX_RETURN = "max_return"           # 最大收益
    MIN_RISK = "min_risk"               # 最小风险
    MAX_SHARPE = "max_sharpe"           # 最大夏普
    RISK_PARITY = "risk_parity"         # 风险平价
    TARGET_RETURN = "target_return"     # 目标收益
    TARGET_RISK = "target_risk"         # 目标风险


class ConstraintType(str, Enum):
    """约束类型"""
    LONG_ONLY = "long_only"
    MAX_WEIGHT = "max_weight"
    MIN_WEIGHT = "min_weight"
    SECTOR_LIMIT = "sector_limit"
    TURNOVER_LIMIT = "turnover_limit"


# ============ 数据模型 ============

@dataclass
class AssetStats:
    """资产统计"""
    code: str
    expected_return: float
    volatility: float
    sharpe_ratio: float

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "expected_return": round(self.expected_return, 6),
            "volatility": round(self.volatility, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
        }


@dataclass
class OptimizationResult:
    """优化结果"""
    weights: Dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    diversification_ratio: float
    effective_assets: int
    optimization_time: datetime = None

    def __post_init__(self):
        if self.optimization_time is None:
            self.optimization_time = datetime.now()

    def to_dict(self) -> dict:
        return {
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "expected_return": round(self.expected_return, 6),
            "expected_volatility": round(self.expected_volatility, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "diversification_ratio": round(self.diversification_ratio, 4),
            "effective_assets": self.effective_assets,
        }


@dataclass
class OptimizationConstraints:
    """优化约束"""
    min_weight: float = 0.0
    max_weight: float = 1.0
    max_sector_weight: float = 0.3
    max_turnover: float = 0.3
    target_return: float = None
    target_risk: float = None
    sector_limits: Dict[str, float] = field(default_factory=dict)


# ============ 均值方差优化器 ============

class MeanVarianceOptimizer:
    """均值方差优化器"""

    def __init__(self, risk_free_rate: float = 0.03):
        self.risk_free_rate = risk_free_rate

    def optimize(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        objective: OptimizationObjective = OptimizationObjective.MAX_SHARPE,
        constraints: OptimizationConstraints = None,
    ) -> OptimizationResult:
        """执行优化"""
        constraints = constraints or OptimizationConstraints()
        n_assets = len(expected_returns)

        # 标准化协方差矩阵
        if cov_matrix.ndim == 1:
            cov_matrix = np.diag(cov_matrix)

        # 初始权重 (等权)
        init_weights = np.ones(n_assets) / n_assets

        # 根据目标选择优化方法
        if objective == OptimizationObjective.MAX_SHARPE:
            weights = self._optimize_max_sharpe(expected_returns, cov_matrix, constraints)
        elif objective == OptimizationObjective.MIN_RISK:
            weights = self._optimize_min_risk(cov_matrix, constraints)
        elif objective == OptimizationObjective.RISK_PARITY:
            weights = self._optimize_risk_parity(cov_matrix, constraints)
        elif objective == OptimizationObjective.TARGET_RETURN:
            target = constraints.target_return or np.mean(expected_returns)
            weights = self._optimize_target_return(expected_returns, cov_matrix, target, constraints)
        else:
            weights = init_weights

        # 计算结果
        port_return = np.dot(weights, expected_returns)
        port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        sharpe = (port_return - self.risk_free_rate) / port_vol if port_vol > 0 else 0

        # 分散化比率
        indiv_vol = np.sqrt(np.diag(cov_matrix))
        weighted_vol = np.dot(weights, indiv_vol)
        div_ratio = weighted_vol / port_vol if port_vol > 0 else 1

        # 有效资产数
        effective_assets = 1 / np.sum(weights ** 2) if np.sum(weights ** 2) > 0 else n_assets

        return OptimizationResult(
            weights=weights,
            expected_return=port_return,
            expected_volatility=port_vol,
            sharpe_ratio=sharpe,
            diversification_ratio=div_ratio,
            effective_assets=int(effective_assets),
        )

    def _optimize_max_sharpe(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        constraints: OptimizationConstraints,
    ) -> np.ndarray:
        """最大化夏普比率"""
        n = len(expected_returns)

        # 使用数值优化 (简化实现)
        best_sharpe = -np.inf
        best_weights = np.ones(n) / n

        # 网格搜索
        for _ in range(1000):
            # 生成随机权重
            weights = np.random.dirichlet(np.ones(n))
            weights = np.clip(weights, constraints.min_weight, constraints.max_weight)
            weights = weights / weights.sum()

            # 计算夏普
            port_return = np.dot(weights, expected_returns)
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            sharpe = (port_return - self.risk_free_rate) / port_vol if port_vol > 0 else 0

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_weights = weights

        return best_weights

    def _optimize_min_risk(
        self,
        cov_matrix: np.ndarray,
        constraints: OptimizationConstraints,
    ) -> np.ndarray:
        """最小化风险"""
        n = len(cov_matrix)

        # 最小方差组合 (逆方差加权)
        inv_var = 1 / np.diag(cov_matrix)
        weights = inv_var / inv_var.sum()

        # 应用约束
        weights = np.clip(weights, constraints.min_weight, constraints.max_weight)
        weights = weights / weights.sum()

        return weights

    def _optimize_risk_parity(
        self,
        cov_matrix: np.ndarray,
        constraints: OptimizationConstraints,
    ) -> np.ndarray:
        """风险平价"""
        n = len(cov_matrix)

        # 迭代求解风险平价
        weights = np.ones(n) / n

        for _ in range(100):
            # 计算边际风险贡献
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            marginal_risk = np.dot(cov_matrix, weights) / port_vol if port_vol > 0 else np.ones(n)

            # 风险贡献
            risk_contrib = weights * marginal_risk
            target_contrib = port_vol / n

            # 调整权重
            adj_factor = target_contrib / (risk_contrib + 1e-10)
            weights = weights * np.sqrt(adj_factor)
            weights = np.clip(weights, constraints.min_weight, constraints.max_weight)
            weights = weights / weights.sum()

        return weights

    def _optimize_target_return(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        target_return: float,
        constraints: OptimizationConstraints,
    ) -> np.ndarray:
        """目标收益优化"""
        n = len(expected_returns)

        # 在满足目标收益下最小化风险
        best_vol = np.inf
        best_weights = np.ones(n) / n

        for _ in range(1000):
            weights = np.random.dirichlet(np.ones(n))
            weights = np.clip(weights, constraints.min_weight, constraints.max_weight)
            weights = weights / weights.sum()

            port_return = np.dot(weights, expected_returns)

            if abs(port_return - target_return) < 0.01:  # 接近目标
                port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))

                if port_vol < best_vol:
                    best_vol = port_vol
                    best_weights = weights

        return best_weights

    def generate_efficient_frontier(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        n_points: int = 20,
    ) -> List[Dict]:
        """生成有效前沿"""
        frontier = []

        min_ret = np.min(expected_returns)
        max_ret = np.max(expected_returns)
        step = (max_ret - min_ret) / (n_points - 1)

        for i in range(n_points):
            target = min_ret + i * step
            constraints = OptimizationConstraints(target_return=target)

            result = self.optimize(
                expected_returns,
                cov_matrix,
                OptimizationObjective.TARGET_RETURN,
                constraints,
            )

            frontier.append({
                "target_return": target,
                "expected_volatility": result.expected_volatility,
                "sharpe_ratio": result.sharpe_ratio,
            })

        return frontier


# ============ Black-Litterman模型 ============

class BlackLittermanModel:
    """Black-Litterman模型"""

    def __init__(
        self,
        risk_free_rate: float = 0.03,
        tau: float = 0.025,
    ):
        self.risk_free_rate = risk_free_rate
        self.tau = tau  # 缩放因子

    def calculate_posterior_returns(
        self,
        market_weights: np.ndarray,
        cov_matrix: np.ndarray,
        views: List[Dict],  # 观点列表
        view_confidences: List[float] = None,
    ) -> np.ndarray:
        """计算后验收益"""
        n = len(market_weights)

        # 计算隐含均衡收益
        risk_aversion = 3.0  # 风险厌恶系数
        pi = risk_aversion * np.dot(cov_matrix, market_weights)

        if not views:
            return pi

        # 构建观点矩阵
        P = np.zeros((len(views), n))  # 观点矩阵
        Q = np.zeros(len(views))       # 观点收益

        for i, view in enumerate(views):
            assets = view.get("assets", [])
            weights = view.get("weights", [])
            Q[i] = view.get("expected_return", 0)

            for j, asset_idx in enumerate(assets):
                if asset_idx < n:
                    P[i, asset_idx] = weights[j] if j < len(weights) else 1 / len(assets)

        # 观点不确定性矩阵
        if view_confidences:
            omega = np.diag([1 / c for c in view_confidences])
        else:
            omega = np.eye(len(views)) * 0.01

        # Black-Litterman公式
        tau_cov = self.tau * cov_matrix

        # 后验收益
        M1 = np.linalg.inv(tau_cov)
        M2 = np.dot(P.T, np.dot(np.linalg.inv(omega), P))
        M3 = np.dot(M1, pi) + np.dot(P.T, np.dot(np.linalg.inv(omega), Q))

        posterior_returns = np.dot(np.linalg.inv(M1 + M2), M3)

        return posterior_returns

    def optimize_with_views(
        self,
        market_weights: np.ndarray,
        cov_matrix: np.ndarray,
        views: List[Dict],
        view_confidences: List[float] = None,
    ) -> OptimizationResult:
        """结合观点优化"""
        # 计算后验收益
        posterior_returns = self.calculate_posterior_returns(
            market_weights, cov_matrix, views, view_confidences
        )

        # 使用后验收益进行均值方差优化
        optimizer = MeanVarianceOptimizer(self.risk_free_rate)
        return optimizer.optimize(posterior_returns, cov_matrix)


# ============ 因子中性优化器 ============

class FactorNeutralOptimizer:
    """因子中性优化器"""

    def __init__(self, factors: List[str] = None):
        self.factors = factors or ["market", "size", "value", "momentum"]

    def calculate_factor_exposures(
        self,
        weights: np.ndarray,
        factor_loadings: np.ndarray,
    ) -> np.ndarray:
        """计算因子暴露"""
        return np.dot(weights, factor_loadings)

    def optimize_neutral(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        factor_loadings: np.ndarray,
        target_exposures: np.ndarray = None,
        constraints: OptimizationConstraints = None,
    ) -> OptimizationResult:
        """因子中性优化"""
        constraints = constraints or OptimizationConstraints()
        n = len(expected_returns)
        n_factors = factor_loadings.shape[1]

        target_exposures = target_exposures or np.zeros(n_factors)

        # 简化实现: 使用惩罚方法
        best_score = -np.inf
        best_weights = np.ones(n) / n

        for _ in range(1000):
            # 生成随机权重
            weights = np.random.dirichlet(np.ones(n))
            weights = np.clip(weights, constraints.min_weight, constraints.max_weight)
            weights = weights / weights.sum()

            # 计算因子暴露偏差
            exposures = self.calculate_factor_exposures(weights, factor_loadings)
            exposure_deviation = np.sum((exposures - target_exposures) ** 2)

            # 计算收益和风险
            port_return = np.dot(weights, expected_returns)
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))

            # 综合评分 (收益 - 风险惩罚 - 因子暴露惩罚)
            score = port_return - 0.5 * port_vol - 10 * exposure_deviation

            if score > best_score:
                best_score = score
                best_weights = weights

        # 计算结果
        port_return = np.dot(best_weights, expected_returns)
        port_vol = np.sqrt(np.dot(best_weights.T, np.dot(cov_matrix, best_weights)))
        sharpe = port_return / port_vol if port_vol > 0 else 0

        return OptimizationResult(
            weights=best_weights,
            expected_return=port_return,
            expected_volatility=port_vol,
            sharpe_ratio=sharpe,
            diversification_ratio=0,
            effective_assets=int(1 / np.sum(best_weights ** 2)),
        )


# ============ 组合优化服务 ============

class PortfolioOptimizationService:
    """组合优化服务"""

    def __init__(self, risk_free_rate: float = 0.03):
        self.mv_optimizer = MeanVarianceOptimizer(risk_free_rate)
        self.bl_model = BlackLittermanModel(risk_free_rate)
        self.factor_optimizer = FactorNeutralOptimizer()

    def optimize(
        self,
        expected_returns: Dict[str, float],
        cov_matrix: np.ndarray,
        objective: OptimizationObjective = OptimizationObjective.MAX_SHARPE,
        constraints: OptimizationConstraints = None,
    ) -> OptimizationResult:
        """执行优化"""
        codes = list(expected_returns.keys())
        returns = np.array([expected_returns[c] for c in codes])

        result = self.mv_optimizer.optimize(returns, cov_matrix, objective, constraints)

        # 转换权重为字典
        result.weights = {codes[i]: result.weights[i] for i in range(len(codes))}

        return result

    def optimize_with_views(
        self,
        expected_returns: Dict[str, float],
        cov_matrix: np.ndarray,
        market_weights: np.ndarray,
        views: List[Dict],
    ) -> OptimizationResult:
        """结合观点优化"""
        codes = list(expected_returns.keys())
        returns = np.array([expected_returns[c] for c in codes])

        result = self.bl_model.optimize_with_views(market_weights, cov_matrix, views)

        result.weights = {codes[i]: result.weights[i] for i in range(len(codes))}

        return result

    def rebalance(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        max_turnover: float = 0.3,
    ) -> Dict[str, float]:
        """再平衡"""
        all_codes = set(current_weights.keys()) | set(target_weights.keys())

        # 计算偏离
        trades = {}
        for code in all_codes:
            current = current_weights.get(code, 0)
            target = target_weights.get(code, 0)
            trades[code] = target - current

        # 限制换手
        total_turnover = sum(abs(t) for t in trades.values())

        if total_turnover > max_turnover:
            scale = max_turnover / total_turnover
            trades = {k: v * scale for k, v in trades.items()}

        # 计算新权重
        new_weights = {}
        for code in all_codes:
            new_weights[code] = current_weights.get(code, 0) + trades.get(code, 0)

        # 归一化
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: v / total for k, v in new_weights.items()}

        return new_weights


# ============ 便捷函数 ============

def create_optimizer(risk_free_rate: float = 0.03) -> PortfolioOptimizationService:
    """创建优化器"""
    return PortfolioOptimizationService(risk_free_rate)


def optimize_portfolio(
    expected_returns: Dict[str, float],
    cov_matrix: np.ndarray,
    objective: str = "max_sharpe",
) -> OptimizationResult:
    """优化组合"""
    service = PortfolioOptimizationService()
    return service.optimize(expected_returns, cov_matrix, OptimizationObjective(objective))


def calculate_risk_contribution(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
) -> np.ndarray:
    """计算风险贡献"""
    port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
    marginal_risk = np.dot(cov_matrix, weights) / port_vol
    return weights * marginal_risk
