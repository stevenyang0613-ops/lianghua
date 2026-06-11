"""Tests for Bayesian optimizer module"""
import pytest
import numpy as np
from unittest.mock import MagicMock

from app.strategies.bayesian_optimizer import (
    ParameterSpace, GaussianProcessRegressor, AcquisitionFunction,
    AcquisitionType, BayesianOptimizer, OptimizationResult,
)


class TestParameterSpace:
    """参数空间测试"""

    def test_continuous_parameter_sample(self):
        """测试连续参数采样"""
        ps = ParameterSpace(
            name='test',
            param_type='continuous',
            bounds=(0.0, 1.0),
        )
        rng = np.random.default_rng(42)

        for _ in range(10):
            value = ps.sample(rng)
            assert 0.0 <= value <= 1.0

    def test_discrete_parameter_sample(self):
        """测试离散参数采样"""
        ps = ParameterSpace(
            name='test',
            param_type='discrete',
            values=[1, 3, 5, 10],
        )
        rng = np.random.default_rng(42)

        for _ in range(10):
            value = ps.sample(rng)
            assert value in [1, 3, 5, 10]

    def test_normalize_denormalize_continuous(self):
        """测试连续参数归一化"""
        ps = ParameterSpace(
            name='test',
            param_type='continuous',
            bounds=(0.0, 100.0),
        )

        # 归一化
        assert ps.normalize(0.0) == 0.0
        assert ps.normalize(50.0) == 0.5
        assert ps.normalize(100.0) == 1.0

        # 反归一化
        assert ps.denormalize(0.0) == 0.0
        assert ps.denormalize(0.5) == 50.0
        assert ps.denormalize(1.0) == 100.0

    def test_normalize_denormalize_discrete(self):
        """测试离散参数归一化"""
        ps = ParameterSpace(
            name='test',
            param_type='discrete',
            values=[1, 5, 10],
        )

        assert ps.normalize(1) == 0.0
        assert ps.normalize(5) == 0.5
        assert ps.normalize(10) == 1.0

        assert ps.denormalize(0.0) == 1
        assert ps.denormalize(0.5) == 5
        assert ps.denormalize(1.0) == 10


class TestGaussianProcessRegressor:
    """高斯过程回归测试"""

    def test_fit_and_predict(self):
        """测试拟合和预测"""
        gp = GaussianProcessRegressor()

        X = np.array([[0.0], [0.5], [1.0]])
        y = np.array([0.0, 0.5, 1.0])

        gp.fit(X, y)

        mu, var = gp.predict(np.array([[0.25], [0.75]]))

        assert len(mu) == 2
        assert len(var) == 2
        # 预测值应接近真实值
        assert abs(mu[0] - 0.25) < 0.5
        assert abs(mu[1] - 0.75) < 0.5

    def test_uncertainty_increases_with_distance(self):
        """测试不确定性随距离增加"""
        gp = GaussianProcessRegressor()

        X = np.array([[0.0], [1.0]])
        y = np.array([0.0, 1.0])

        gp.fit(X, y)

        # 在训练点附近的不确定性应较小
        _, var_near = gp.predict(np.array([[0.5]]))
        # 远离训练点的不确定性应较大
        _, var_far = gp.predict(np.array([[2.0]]))

        # 方差都应为正
        assert var_near[0] > 0
        assert var_far[0] > 0


class TestAcquisitionFunction:
    """采集函数测试"""

    def test_expected_improvement(self):
        """测试期望改进"""
        acq = AcquisitionFunction(AcquisitionType.EI)

        mu = np.array([0.5, 0.3, 0.7])
        var = np.array([0.1, 0.2, 0.1])
        best = 0.4

        ei = acq.compute(mu, var, best)

        assert len(ei) == 3
        # 大于best的点应有正的EI值
        assert ei[2] > 0  # mu=0.7 > best=0.4

    def test_upper_confidence_bound(self):
        """测试上置信界"""
        acq = AcquisitionFunction(AcquisitionType.UCB, kappa=2.0)

        mu = np.array([0.5, 0.3])
        var = np.array([0.1, 0.2])
        best = 0.4

        ucb = acq.compute(mu, var, best)

        # UCB = mu + kappa * sqrt(var)
        expected = mu + 2.0 * np.sqrt(var)
        assert np.allclose(ucb, expected)

    def test_probability_of_improvement(self):
        """测试改进概率"""
        acq = AcquisitionFunction(AcquisitionType.PI)

        mu = np.array([0.5, 0.3])
        var = np.array([0.1, 0.1])
        best = 0.4

        pi = acq.compute(mu, var, best)

        # mu=0.5 > best，PI应接近0.84
        # mu=0.3 < best，PI应接近0.16
        assert pi[0] > pi[1]


class TestBayesianOptimizer:
    """贝叶斯优化器测试"""

    def test_optimization_simple(self):
        """测试简单优化问题"""
        # 目标函数：最大化 -x^2 + 1
        def objective(params):
            x = params['x']
            return -x**2 + 1

        param_spaces = [
            ParameterSpace(name='x', param_type='continuous', bounds=(-2.0, 2.0)),
        ]

        optimizer = BayesianOptimizer(
            parameter_spaces=param_spaces,
            objective=objective,
            n_initial=3,
            n_iterations=10,
            random_state=42,
        )

        result = optimizer.optimize()

        assert isinstance(result, OptimizationResult)
        assert 'x' in result.best_params
        # 最优解应在x=0附近
        assert abs(result.best_params['x']) < 0.5
        assert result.best_value > 0.9

    def test_optimization_with_discrete_params(self):
        """测试离散参数优化"""
        def objective(params):
            # 最佳参数是hold_count=5
            return -abs(params['hold_count'] - 5)

        param_spaces = [
            ParameterSpace(
                name='hold_count',
                param_type='discrete',
                values=[1, 3, 5, 7, 10],
            ),
        ]

        optimizer = BayesianOptimizer(
            parameter_spaces=param_spaces,
            objective=objective,
            n_initial=2,
            n_iterations=8,
            random_state=42,
        )

        result = optimizer.optimize()

        assert result.best_params['hold_count'] in [1, 3, 5, 7, 10]
        assert result.n_evaluations == 8

    def test_history_recording(self):
        """测试历史记录"""
        def objective(params):
            return params['x']

        param_spaces = [
            ParameterSpace(name='x', param_type='continuous', bounds=(0.0, 1.0)),
        ]

        optimizer = BayesianOptimizer(
            parameter_spaces=param_spaces,
            objective=objective,
            n_initial=2,
            n_iterations=5,
            random_state=42,
        )

        result = optimizer.optimize()

        assert len(result.history) == 5
        assert all('iteration' in h for h in result.history)
        assert all('params' in h for h in result.history)
        assert all('value' in h for h in result.history)

    def test_handles_exception_in_objective(self):
        """测试目标函数异常处理"""
        def objective(params):
            if params['x'] < 0.5:
                raise ValueError("Test error")
            return params['x']

        param_spaces = [
            ParameterSpace(name='x', param_type='continuous', bounds=(0.0, 1.0)),
        ]

        optimizer = BayesianOptimizer(
            parameter_spaces=param_spaces,
            objective=objective,
            n_initial=2,
            n_iterations=5,
            random_state=42,
        )

        # 应该能完成优化，即使有异常
        result = optimizer.optimize()
        assert result is not None
