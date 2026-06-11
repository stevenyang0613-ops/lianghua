"""组合优化器（均值-方差模型）"""
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import asyncio

try:
    from scipy.optimize import minimize
    from scipy.stats import norm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


@dataclass
class OptimizationResult:
    """优化结果"""
    weights: Dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    diversification_ratio: float
    concentration_hhi: float
    efficient_frontier_point: Tuple[float, float]
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class OptimizationConstraints:
    """优化约束"""
    min_weight: float = 0.0
    max_weight: float = 1.0
    min_positions: int = 5
    max_positions: int = 30
    target_return: Optional[float] = None
    max_volatility: Optional[float] = None
    sector_limits: Dict[str, float] = None
    single_position_limit: float = 0.15
    turnover_limit: Optional[float] = None


class PortfolioOptimizer:
    """组合优化器"""
    
    def __init__(
        self,
        risk_free_rate: float = 0.03,
        risk_aversion: float = 1.0
    ):
        self.risk_free_rate = risk_free_rate
        self.risk_aversion = risk_aversion
        
        # 历史数据
        self.returns_data: np.ndarray = None
        self.cov_matrix: np.ndarray = None
        self.expected_returns: np.ndarray = None
        self.asset_names: List[str] = []
    
    def set_data(
        self,
        returns_data: np.ndarray,
        asset_names: List[str] = None
    ):
        """设置数据"""
        self.returns_data = returns_data
        self.asset_names = asset_names or [f"asset_{i}" for i in range(returns_data.shape[1])]
        
        # 计算期望收益和协方差矩阵
        self.expected_returns = np.mean(returns_data, axis=0)
        self.cov_matrix = np.cov(returns_data.T)
    
    def mean_variance_optimize(
        self,
        constraints: OptimizationConstraints = None,
        objective: str = 'max_sharpe'
    ) -> OptimizationResult:
        """均值-方差优化"""
        if not SCIPY_AVAILABLE:
            raise ImportError("需要安装scipy")
        
        if self.returns_data is None:
            raise ValueError("请先设置数据")
        
        constraints = constraints or OptimizationConstraints()
        n_assets = len(self.asset_names)
        
        # 初始权重（等权）
        initial_weights = np.ones(n_assets) / n_assets
        
        # 目标函数
        if objective == 'max_sharpe':
            def neg_sharpe(weights):
                ret = np.dot(weights, self.expected_returns)
                vol = np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))
                return -(ret - self.risk_free_rate) / vol if vol > 0 else 0
            objective_func = neg_sharpe
        
        elif objective == 'min_volatility':
            def portfolio_volatility(weights):
                return np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))
            objective_func = portfolio_volatility
        
        elif objective == 'max_return':
            def neg_return(weights):
                return -np.dot(weights, self.expected_returns)
            objective_func = neg_return
        
        elif objective == 'risk_parity':
            def risk_parity_objective(weights):
                portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))
                marginal_contrib = np.dot(self.cov_matrix, weights)
                risk_contrib = weights * marginal_contrib / portfolio_vol
                target_risk = portfolio_vol / n_assets
                return np.sum((risk_contrib - target_risk) ** 2)
            objective_func = risk_parity_objective
        
        else:
            raise ValueError(f"未知目标: {objective}")
        
        # 约束条件
        opt_constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}  # 权重和为1
        ]
        
        if constraints.target_return:
            opt_constraints.append({
                'type': 'eq',
                'fun': lambda w: np.dot(w, self.expected_returns) - constraints.target_return
            })
        
        if constraints.max_volatility:
            opt_constraints.append({
                'type': 'ineq',
                'fun': lambda w: constraints.max_volatility - np.sqrt(np.dot(w.T, np.dot(self.cov_matrix, w)))
            })
        
        # 边界
        bounds = tuple(
            (constraints.min_weight, min(constraints.max_weight, constraints.single_position_limit))
            for _ in range(n_assets)
        )
        
        # 优化
        result = minimize(
            objective_func,
            initial_weights,
            method='SLSQP',
            bounds=bounds,
            constraints=opt_constraints,
            options={'maxiter': 1000}
        )
        
        if not result.success:
            # 返回等权组合
            optimal_weights = initial_weights
        else:
            optimal_weights = result.x
        
        # 计算结果指标
        expected_return = np.dot(optimal_weights, self.expected_returns)
        expected_vol = np.sqrt(np.dot(optimal_weights.T, np.dot(self.cov_matrix, optimal_weights)))
        sharpe = (expected_return - self.risk_free_rate) / expected_vol if expected_vol > 0 else 0
        
        # 多样化比率
        diversification_ratio = self._calculate_diversification_ratio(optimal_weights)
        
        # 集中度
        hhi = np.sum(optimal_weights ** 2)
        
        # 权重字典
        weights_dict = {name: w for name, w in zip(self.asset_names, optimal_weights) if w > 0.001}
        
        return OptimizationResult(
            weights=weights_dict,
            expected_return=expected_return,
            expected_volatility=expected_vol,
            sharpe_ratio=sharpe,
            diversification_ratio=diversification_ratio,
            concentration_hhi=hhi,
            efficient_frontier_point=(expected_vol, expected_return)
        )
    
    def calculate_efficient_frontier(
        self,
        n_points: int = 50,
        constraints: OptimizationConstraints = None
    ) -> List[Tuple[float, float]]:
        """计算有效前沿"""
        constraints = constraints or OptimizationConstraints()
        
        # 计算最小和最大可能收益
        min_ret = np.min(self.expected_returns)
        max_ret = np.max(self.expected_returns)
        
        target_returns = np.linspace(min_ret, max_ret, n_points)
        frontier = []
        
        for target_ret in target_returns:
            constraints.target_return = target_ret
            try:
                result = self.mean_variance_optimize(constraints, 'min_volatility')
                frontier.append((result.expected_volatility, result.expected_return))
            except Exception:
                continue
        
        return frontier
    
    def _calculate_diversification_ratio(self, weights: np.ndarray) -> float:
        """计算多样化比率"""
        weighted_vol = np.sum(weights * np.sqrt(np.diag(self.cov_matrix)))
        portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))
        
        return weighted_vol / portfolio_vol if portfolio_vol > 0 else 1
    
    def black_litterman_optimize(
        self,
        market_caps: Dict[str, float],
        views: Dict[str, float] = None,
        view_confidences: Dict[str, float] = None,
        tau: float = 0.05
    ) -> OptimizationResult:
        """Black-Litterman优化"""
        n_assets = len(self.asset_names)
        
        # 市场均衡收益
        market_weights = np.array([market_caps.get(name, 1/n_assets) for name in self.asset_names])
        market_weights = market_weights / market_weights.sum()
        
        lambda_mkt = (np.dot(market_weights, self.expected_returns) - self.risk_free_rate) / \
                     np.dot(market_weights.T, np.dot(self.cov_matrix, market_weights))
        
        equilibrium_returns = lambda_mkt * np.dot(self.cov_matrix, market_weights)
        
        # 合并投资者观点
        if views:
            P = np.zeros((len(views), n_assets))
            Q = np.zeros(len(views))
            Omega = np.eye(len(views)) * 0.01
            
            for i, (asset, view) in enumerate(views.items()):
                idx = self.asset_names.index(asset) if asset in self.asset_names else -1
                if idx >= 0:
                    P[i, idx] = 1
                    Q[i] = view
                    if view_confidences and asset in view_confidences:
                        Omega[i, i] = 1 / view_confidences[asset]
            
            # Black-Litterman公式
            tau_sigma_inv = np.linalg.inv(tau * self.cov_matrix)
            omega_inv = np.linalg.inv(Omega)
            
            M = np.linalg.inv(tau_sigma_inv + np.dot(P.T, np.dot(omega_inv, P)))
            adjusted_returns = np.dot(M, np.dot(tau_sigma_inv, equilibrium_returns) + 
                                     np.dot(P.T, np.dot(omega_inv, Q)))
        else:
            adjusted_returns = equilibrium_returns
        
        # 更新期望收益
        old_returns = self.expected_returns
        self.expected_returns = adjusted_returns
        
        # 优化
        result = self.mean_variance_optimize(objective='max_sharpe')
        
        # 恢复
        self.expected_returns = old_returns
        
        return result
    
    def risk_parity_optimize(
        self,
        target_risk_contributions: Dict[str, float] = None
    ) -> OptimizationResult:
        """风险平价优化"""
        n_assets = len(self.asset_names)
        
        if target_risk_contributions:
            target = np.array([target_risk_contributions.get(name, 1/n_assets) 
                              for name in self.asset_names])
            target = target / target.sum()
        else:
            target = np.ones(n_assets) / n_assets
        
        def risk_parity_objective(weights):
            portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))
            marginal_contrib = np.dot(self.cov_matrix, weights)
            risk_contrib = weights * marginal_contrib / portfolio_vol
            risk_contrib_pct = risk_contrib / risk_contrib.sum()
            return np.sum((risk_contrib_pct - target) ** 2)
        
        # 优化
        initial_weights = np.ones(n_assets) / n_assets
        
        result = minimize(
            risk_parity_objective,
            initial_weights,
            method='SLSQP',
            bounds=tuple((0.01, 0.5) for _ in range(n_assets)),
            constraints={'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        )
        
        optimal_weights = result.x
        
        # 计算结果
        expected_return = np.dot(optimal_weights, self.expected_returns)
        expected_vol = np.sqrt(np.dot(optimal_weights.T, np.dot(self.cov_matrix, optimal_weights)))
        sharpe = (expected_return - self.risk_free_rate) / expected_vol if expected_vol > 0 else 0
        
        weights_dict = {name: w for name, w in zip(self.asset_names, optimal_weights) if w > 0.001}
        
        return OptimizationResult(
            weights=weights_dict,
            expected_return=expected_return,
            expected_volatility=expected_vol,
            sharpe_ratio=sharpe,
            diversification_ratio=self._calculate_diversification_ratio(optimal_weights),
            concentration_hhi=np.sum(optimal_weights ** 2),
            efficient_frontier_point=(expected_vol, expected_return)
        )
    
    def rebalance_suggest(
        self,
        current_weights: Dict[str, float],
        optimal_weights: Dict[str, float],
        portfolio_value: float
    ) -> Dict[str, Dict]:
        """再平衡建议"""
        suggestions = {}
        
        all_assets = set(current_weights.keys()) | set(optimal_weights.keys())
        
        for asset in all_assets:
            current = current_weights.get(asset, 0)
            optimal = optimal_weights.get(asset, 0)
            diff = optimal - current
            
            if abs(diff) > 0.001:
                suggestions[asset] = {
                    'current_weight': current,
                    'target_weight': optimal,
                    'weight_change': diff,
                    'value_change': diff * portfolio_value,
                    'action': 'buy' if diff > 0 else 'sell'
                }
        
        return suggestions
    
    def calculate_portfolio_metrics(
        self,
        weights: Dict[str, float]
    ) -> Dict:
        """计算组合指标"""
        w = np.array([weights.get(name, 0) for name in self.asset_names])
        
        expected_return = np.dot(w, self.expected_returns)
        volatility = np.sqrt(np.dot(w.T, np.dot(self.cov_matrix, w)))
        sharpe = (expected_return - self.risk_free_rate) / volatility if volatility > 0 else 0
        
        # VaR
        from scipy.stats import norm
        var_95 = norm.ppf(0.05, expected_return, volatility)
        var_99 = norm.ppf(0.01, expected_return, volatility)
        
        # 边际风险贡献
        marginal_risk = np.dot(self.cov_matrix, w) / volatility
        risk_contrib = w * marginal_risk / volatility
        
        return {
            'expected_return': expected_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe,
            'var_95': var_95,
            'var_99': var_99,
            'diversification_ratio': self._calculate_diversification_ratio(w),
            'concentration_hhi': np.sum(w ** 2),
            'marginal_risk_contribution': dict(zip(self.asset_names, marginal_risk)),
            'risk_contribution': dict(zip(self.asset_names, risk_contrib))
        }
