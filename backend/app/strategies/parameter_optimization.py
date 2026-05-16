"""
策略参数网格优化模块

功能：
- 参数网格定义
- 多进程并行优化
- 参数稳定性分析
- 过拟合检测
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, Any
from itertools import product
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParameterRange:
    """参数范围定义"""
    name: str
    min_val: float
    max_val: float
    step: float
    values: Optional[list] = None

    def get_values(self) -> list:
        """获取参数值列表"""
        if self.values:
            return self.values
        if self.step > 0:
            return list(np.arange(self.min_val, self.max_val + self.step, self.step))
        return [self.min_val, self.max_val]


@dataclass
class OptimizationResult:
    """优化结果"""
    params: dict
    score: float
    metrics: dict
    is_stable: bool
    overfit_score: float


@dataclass
class GridSearchResult:
    """网格搜索结果"""
    best_params: dict
    best_score: float
    all_results: list[OptimizationResult]
    stability_report: dict
    overfit_report: dict
    execution_time: float


class ParameterGridOptimizer:
    """参数网格优化器"""

    def __init__(
        self,
        param_ranges: list[ParameterRange],
        objective_func: Callable[[dict], float],
        stability_threshold: float = 0.15,
        overfit_threshold: float = 0.3,
    ):
        """
        初始化优化器

        param_ranges: 参数范围列表
        objective_func: 目标函数，输入参数，返回得分
        stability_threshold: 参数稳定性阈值（变化率）
        overfit_threshold: 过拟合阈值
        """
        self._param_ranges = param_ranges
        self._objective_func = objective_func
        self._stability_threshold = stability_threshold
        self._overfit_threshold = overfit_threshold

    def _generate_grid(self) -> list[dict]:
        """生成参数网格"""
        param_names = [p.name for p in self._param_ranges]
        param_values = [p.get_values() for p in self._param_ranges]

        grid = []
        for combo in product(*param_values):
            grid.append(dict(zip(param_names, combo)))

        return grid

    def _evaluate_params(self, params: dict) -> OptimizationResult:
        """评估单组参数"""
        try:
            score = self._objective_func(params)

            # 计算稳定性
            is_stable = self._check_stability(params)

            # 计算过拟合分数
            overfit_score = self._calc_overfit_score(params, score)

            return OptimizationResult(
                params=params,
                score=score,
                metrics={'raw_score': score},
                is_stable=is_stable,
                overfit_score=overfit_score,
            )
        except Exception as e:
            logger.warning(f"[Optimizer] Error evaluating {params}: {e}")
            return OptimizationResult(
                params=params,
                score=-float('inf'),
                metrics={'error': str(e)},
                is_stable=False,
                overfit_score=1.0,
            )

    def _check_stability(self, params: dict) -> bool:
        """检查参数稳定性"""
        # 在参数附近小范围扰动测试
        perturbations = []
        for name, value in params.items():
            if isinstance(value, (int, float)):
                # ±5%扰动
                perturbed_plus = params.copy()
                perturbed_plus[name] = value * 1.05
                perturbed_minus = params.copy()
                perturbed_minus[name] = value * 0.95

                try:
                    score_plus = self._objective_func(perturbed_plus)
                    score_minus = self._objective_func(perturbed_minus)
                    base_score = self._objective_func(params)

                    # 变化率
                    change_rate = max(
                        abs(score_plus - base_score) / abs(base_score) if base_score else 0,
                        abs(score_minus - base_score) / abs(base_score) if base_score else 0,
                    )
                    perturbations.append(change_rate)
                except:
                    perturbations.append(1.0)

        if not perturbations:
            return True

        avg_change = np.mean(perturbations)
        return avg_change < self._stability_threshold

    def _calc_overfit_score(self, params: dict, score: float) -> float:
        """计算过拟合分数"""
        # 简化的过拟合检测：参数值越极端，过拟合风险越高
        overfit_score = 0.0

        for pr in self._param_ranges:
            value = params.get(pr.name, pr.min_val)
            if pr.max_val > pr.min_val:
                # 参数位置在0-1之间
                position = (value - pr.min_val) / (pr.max_val - pr.min_val)
                # 越靠近边界，过拟合风险越高
                if position < 0.1 or position > 0.9:
                    overfit_score += 0.1

        return overfit_score

    def optimize(self, max_workers: int = 4) -> GridSearchResult:
        """执行网格搜索优化"""
        start_time = datetime.now()
        grid = self._generate_grid()
        results = []

        logger.info(f"[Optimizer] Starting grid search with {len(grid)} combinations")

        # 并行评估
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._evaluate_params, params): params
                for params in grid
            }

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.warning(f"[Optimizer] Future error: {e}")

        # 排序结果
        results.sort(key=lambda x: x.score, reverse=True)

        if not results:
            return GridSearchResult(
                best_params={},
                best_score=-float('inf'),
                all_results=[],
                stability_report={},
                overfit_report={},
                execution_time=0,
            )

        # 选择最佳参数（综合考虑得分、稳定性、过拟合风险）
        best_result = None
        for r in results:
            if r.is_stable and r.overfit_score < self._overfit_threshold:
                best_result = r
                break

        if best_result is None:
            best_result = results[0]

        # 生成稳定性报告
        stability_report = self._generate_stability_report(results)

        # 生成过拟合报告
        overfit_report = self._generate_overfit_report(results)

        execution_time = (datetime.now() - start_time).total_seconds()

        return GridSearchResult(
            best_params=best_result.params,
            best_score=best_result.score,
            all_results=results,
            stability_report=stability_report,
            overfit_report=overfit_report,
            execution_time=execution_time,
        )

    def _generate_stability_report(self, results: list[OptimizationResult]) -> dict:
        """生成稳定性报告"""
        stable_count = sum(1 for r in results if r.is_stable)
        top_10 = results[:10]
        top_10_stable = sum(1 for r in top_10 if r.is_stable)

        return {
            'total_params': len(results),
            'stable_params': stable_count,
            'stability_ratio': stable_count / len(results) if results else 0,
            'top_10_stable': top_10_stable,
            'recommendation': '使用稳定的最佳参数' if top_10_stable > 5 else '建议放宽筛选条件',
        }

    def _generate_overfit_report(self, results: list[OptimizationResult]) -> dict:
        """生成过拟合报告"""
        low_overfit = [r for r in results if r.overfit_score < self._overfit_threshold]
        high_overfit = [r for r in results if r.overfit_score >= self._overfit_threshold]

        return {
            'low_overfit_count': len(low_overfit),
            'high_overfit_count': len(high_overfit),
            'overfit_ratio': len(high_overfit) / len(results) if results else 0,
            'recommendation': '过拟合风险可控' if len(low_overfit) > len(high_overfit) else '注意过拟合风险',
        }


class WalkForwardOptimizer:
    """Walk-Forward参数优化器"""

    def __init__(
        self,
        data: pd.DataFrame,
        strategy_class: type,
        param_ranges: list[ParameterRange],
        train_months: int = 12,
        test_months: int = 3,
        step_months: int = 3,
    ):
        self._data = data
        self._strategy_class = strategy_class
        self._param_ranges = param_ranges
        self._train_months = train_months
        self._test_months = test_months
        self._step_months = step_months

    def optimize(self) -> dict:
        """执行Walk-Forward优化"""
        from app.strategies.walk_forward_backtest import WalkForwardValidator

        def objective(params):
            # 使用参数创建策略
            strategy = self._strategy_class(**params)
            # 运行回测返回得分
            validator = WalkForwardValidator(self._data, lambda d: strategy.on_data(d, 0) or [])
            results = validator.run_validation()
            if results:
                return np.mean([r.test_result.annual_return for r in results if r.test_result])
            return 0

        optimizer = ParameterGridOptimizer(self._param_ranges, objective)
        result = optimizer.optimize()

        return {
            'best_params': result.best_params,
            'best_score': result.best_score,
            'stability_report': result.stability_report,
            'overfit_report': result.overfit_report,
            'execution_time': result.execution_time,
        }
