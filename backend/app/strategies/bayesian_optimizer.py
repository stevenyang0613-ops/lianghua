"""
贝叶斯优化参数搜索模块

使用高斯过程回归进行参数优化，相比网格搜索：
- 更少的评估次数
- 自动探索有希望的参数区域
- 支持连续和离散参数
"""

import numpy as np
import math
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable, Any, Tuple
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


class AcquisitionType(Enum):
    """采集函数类型"""
    EI = 'expected_improvement'       # 期望改进
    UCB = 'upper_confidence_bound'    # 上置信界
    PI = 'probability_of_improvement' # 改进概率


@dataclass
class ParameterSpace:
    """参数空间定义"""
    name: str
    param_type: str  # 'continuous', 'discrete', 'categorical'
    bounds: Tuple[float, float] = None  # 连续参数边界
    values: List[Any] = None  # 离散/分类参数取值

    def sample(self, rng: np.random.Generator = None) -> Any:
        """随机采样一个值"""
        rng = rng or np.random.default_rng()
        if self.param_type == 'continuous':
            return rng.uniform(self.bounds[0], self.bounds[1])
        elif self.param_type == 'discrete':
            return rng.choice(self.values)
        elif self.param_type == 'categorical':
            return rng.choice(self.values)
        return None

    def normalize(self, value: Any) -> float:
        """归一化到[0, 1]"""
        if self.param_type == 'continuous':
            return (value - self.bounds[0]) / (self.bounds[1] - self.bounds[0])
        elif self.param_type in ('discrete', 'categorical'):
            idx = self.values.index(value) if value in self.values else 0
            return idx / (len(self.values) - 1)
        return 0.5

    def denormalize(self, normalized: float) -> Any:
        """从[0, 1]还原"""
        if self.param_type == 'continuous':
            return self.bounds[0] + normalized * (self.bounds[1] - self.bounds[0])
        elif self.param_type in ('discrete', 'categorical'):
            idx = int(round(normalized * (len(self.values) - 1)))
            idx = max(0, min(idx, len(self.values) - 1))
            return self.values[idx]
        return None


@dataclass
class OptimizationResult:
    """优化结果"""
    best_params: Dict[str, Any]
    best_value: float
    n_evaluations: int
    history: List[Dict] = field(default_factory=list)
    execution_time_ms: int = 0


class GaussianProcessRegressor:
    """简化版高斯过程回归"""

    def __init__(self, length_scale: float = 1.0, noise: float = 1e-6):
        self.length_scale = length_scale
        self.noise = noise
        self.X_train = None
        self.y_train = None
        self._K_inv = None

    def _kernel(self, x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
        """RBF核函数"""
        if x1.ndim == 1:
            x1 = x1.reshape(1, -1)
        if x2.ndim == 1:
            x2 = x2.reshape(1, -1)

        sq_dist = np.sum(x1**2, axis=1, keepdims=True) + \
                  np.sum(x2**2, axis=1) - 2 * np.dot(x1, x2.T)
        return np.exp(-0.5 * sq_dist / self.length_scale**2)

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """拟合模型"""
        self.X_train = np.atleast_2d(X)
        self.y_train = np.atleast_1d(y)

        K = self._kernel(self.X_train, self.X_train)
        K += self.noise * np.eye(len(self.X_train))
        self._K_inv = np.linalg.inv(K)

    def predict(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """预测均值和方差"""
        X = np.atleast_2d(X)

        K_s = self._kernel(X, self.X_train)
        K_ss = self._kernel(X, X)

        mu = K_s @ self._K_inv @ self.y_train
        cov = K_ss - K_s @ self._K_inv @ K_s.T
        var = np.diag(cov)
        var = np.maximum(var, 1e-10)  # 确保方差为正

        return mu, var


class AcquisitionFunction:
    """采集函数"""

    def __init__(self, acquisition_type: AcquisitionType = AcquisitionType.EI, kappa: float = 2.0):
        self.acquisition_type = acquisition_type
        self.kappa = kappa  # UCB参数

    def compute(
        self,
        mu: np.ndarray,
        var: np.ndarray,
        best_so_far: float,
    ) -> np.ndarray:
        """计算采集函数值"""
        std = np.sqrt(var)

        if self.acquisition_type == AcquisitionType.EI:
            # Expected Improvement
            z = (mu - best_so_far) / std
            ei = std * (z * self._norm_cdf(z) + self._norm_pdf(z))
            return ei

        elif self.acquisition_type == AcquisitionType.UCB:
            # Upper Confidence Bound
            return mu + self.kappa * std

        elif self.acquisition_type == AcquisitionType.PI:
            # Probability of Improvement
            z = (mu - best_so_far) / std
            return self._norm_cdf(z)

        return mu

    @staticmethod
    def _norm_cdf(x: np.ndarray) -> np.ndarray:
        """标准正态CDF"""
        # 使用math.erf逐元素计算
        result = np.zeros_like(x, dtype=float)
        for i, val in enumerate(np.atleast_1d(x)):
            result[i] = 0.5 * (1 + math.erf(val / math.sqrt(2)))
        return result if x.ndim > 0 else result[0]

    @staticmethod
    def _norm_pdf(x: np.ndarray) -> np.ndarray:
        """标准正态PDF"""
        return np.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)


class BayesianOptimizer:
    """贝叶斯优化器"""

    def __init__(
        self,
        parameter_spaces: List[ParameterSpace],
        objective: Callable[[Dict[str, Any]], float],
        acquisition_type: AcquisitionType = AcquisitionType.EI,
        n_initial: int = 5,
        n_iterations: int = 25,
        random_state: int = 42,
    ):
        """
        初始化贝叶斯优化器

        parameter_spaces: 参数空间列表
        objective: 目标函数，接收参数字典，返回评价值（越大越好）
        acquisition_type: 采集函数类型
        n_initial: 初始随机采样数
        n_iterations: 总迭代次数
        """
        self.parameter_spaces = {ps.name: ps for ps in parameter_spaces}
        self.objective = objective
        self.acquisition = AcquisitionFunction(acquisition_type)
        self.n_initial = n_initial
        self.n_iterations = n_iterations
        self.rng = np.random.default_rng(random_state)

        # 高斯过程模型
        self.gp = GaussianProcessRegressor()

        # 历史记录
        self._observations: List[Tuple[np.ndarray, float]] = []

    def _params_to_vector(self, params: Dict[str, Any]) -> np.ndarray:
        """参数字典转向量"""
        vector = []
        for name, ps in self.parameter_spaces.items():
            value = params.get(name)
            vector.append(ps.normalize(value))
        return np.array(vector)

    def _vector_to_params(self, vector: np.ndarray) -> Dict[str, Any]:
        """向量转参数字典"""
        params = {}
        for i, (name, ps) in enumerate(self.parameter_spaces.items()):
            params[name] = ps.denormalize(vector[i])
        return params

    def _sample_random(self) -> Dict[str, Any]:
        """随机采样参数"""
        return {name: ps.sample(self.rng) for name, ps in self.parameter_spaces.items()}

    def _suggest_next(self) -> Dict[str, Any]:
        """建议下一个评估点"""
        if len(self._observations) < self.n_initial:
            return self._sample_random()

        # 准备训练数据
        X = np.array([obs[0] for obs in self._observations])
        y = np.array([obs[1] for obs in self._observations])

        # 拟合高斯过程
        self.gp.fit(X, y)

        # 生成候选点
        n_candidates = 1000
        candidates = self.rng.uniform(0, 1, (n_candidates, len(self.parameter_spaces)))

        # 预测并计算采集函数值
        mu, var = self.gp.predict(candidates)
        best_so_far = np.max(y)
        acq_values = self.acquisition.compute(mu, var, best_so_far)

        # 选择最佳候选
        best_idx = np.argmax(acq_values)
        return self._vector_to_params(candidates[best_idx])

    def optimize(self) -> OptimizationResult:
        """执行优化"""
        start_time = time.time()
        history = []

        logger.info(f"[BayesianOpt] 开始优化，初始采样{self.n_initial}次，总计{self.n_iterations}次")

        for i in range(self.n_iterations):
            # 获取下一个评估点
            params = self._suggest_next()
            vector = self._params_to_vector(params)

            # 评估目标函数
            try:
                value = self.objective(params)
            except Exception as e:
                logger.warning(f"[BayesianOpt] 评估失败: {e}")
                value = float('-inf')

            # 记录观察
            self._observations.append((vector, value))

            history.append({
                'iteration': i + 1,
                'params': params.copy(),
                'value': value,
                'best_so_far': max(obs[1] for obs in self._observations),
            })

            if (i + 1) % 5 == 0 or i == 0:
                best = max(self._observations, key=lambda x: x[1])
                logger.info(
                    f"[BayesianOpt] 迭代 {i+1}/{self.n_iterations}: "
                    f"value={value:.4f}, best={best[1]:.4f}"
                )

        # 找到最优参数
        best_obs = max(self._observations, key=lambda x: x[1])
        best_params = self._vector_to_params(best_obs[0])
        best_value = best_obs[1]

        execution_time = int((time.time() - start_time) * 1000)

        logger.info(
            f"[BayesianOpt] 优化完成: best_value={best_value:.4f}, "
            f"耗时={execution_time}ms"
        )

        return OptimizationResult(
            best_params=best_params,
            best_value=best_value,
            n_evaluations=len(self._observations),
            history=history,
            execution_time_ms=execution_time,
        )


def create_bayesian_optimizer_for_strategy(
    strategy_cls,
    data,
    param_ranges: Dict[str, Tuple],
    metric: str = 'sharpe_ratio',
    n_iterations: int = 30,
) -> BayesianOptimizer:
    """
    为策略创建贝叶斯优化器

    strategy_cls: 策略类
    data: 回测数据
    param_ranges: 参数范围 {'param_name': (min, max)} 或 {'param_name': [value1, value2, ...]}
    metric: 优化目标指标
    n_iterations: 迭代次数
    """
    from app.engine.backtest import BacktestEngine, BacktestConfig

    # 构建参数空间
    param_spaces = []
    for name, spec in param_ranges.items():
        if isinstance(spec, tuple) and len(spec) == 2:
            # 连续参数
            param_spaces.append(ParameterSpace(
                name=name,
                param_type='continuous',
                bounds=spec,
            ))
        elif isinstance(spec, list):
            # 离散参数
            param_spaces.append(ParameterSpace(
                name=name,
                param_type='discrete',
                values=spec,
            ))

    # 目标函数
    def objective(params: Dict[str, Any]) -> float:
        try:
            # 转换参数类型
            converted = {}
            for name, value in params.items():
                if name in param_ranges and isinstance(param_ranges[name], tuple):
                    # 连续参数可能是整数（如hold_count）
                    if 'count' in name.lower() or 'days' in name.lower() or 'window' in name.lower():
                        converted[name] = int(round(value))
                    else:
                        converted[name] = value
                else:
                    converted[name] = value

            engine = BacktestEngine(config=BacktestConfig())
            strategy = strategy_cls(**converted)
            result = engine.run(strategy, data)

            metric_value = getattr(result.metrics, metric, 0)
            return metric_value if metric_value is not None else 0
        except Exception as e:
            logger.debug(f"Objective evaluation error: {e}")
            return float('-inf')

    return BayesianOptimizer(
        parameter_spaces=param_spaces,
        objective=objective,
        n_iterations=n_iterations,
    )
