"""西部量化可转债策略 V3.0 智能参数优化模块

功能:
- 遗传算法参数优化
- 贝叶斯优化
- 自动参数调优
- 参数敏感性分析
- 多目标优化
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import random
import numpy as np
import time

logger = logging.getLogger(__name__)

# 检查优化库
try:
    from deap import base, creator, tools, algorithms
    from deap.base import Fitness
    DEAP_AVAILABLE = True
except ImportError:
    DEAP_AVAILABLE = False

try:
    from skopt import gp_minimize
    from skopt.space import Real, Integer, Categorical
    from skopt.utils import use_named_args
    SKOPT_AVAILABLE = True
except ImportError:
    SKOPT_AVAILABLE = False


# ============ 枚举类型 ============

class OptimizationMethod(str, Enum):
    """优化方法"""
    GENETIC = "genetic"         # 遗传算法
    BAYESIAN = "bayesian"       # 贝叶斯优化
    GRID_SEARCH = "grid"        # 网格搜索
    RANDOM = "random"           # 随机搜索
    PARTICLE_SWARM = "pso"      # 粒子群


class ObjectiveType(str, Enum):
    """目标类型"""
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


# ============ 配置类 ============

@dataclass
class ParameterRange:
    """参数范围"""
    name: str
    param_type: str  # int, float, categorical
    low: float = None
    high: float = None
    choices: List[Any] = None

    def sample(self) -> Any:
        """随机采样"""
        if self.param_type == "int":
            return random.randint(int(self.low), int(self.high))
        elif self.param_type == "float":
            return random.uniform(self.low, self.high)
        elif self.param_type == "categorical":
            return random.choice(self.choices)
        return None

    def to_skopt_space(self):
        """转换为skopt空间"""
        if self.param_type == "int":
            return Integer(int(self.low), int(self.high), name=self.name)
        elif self.param_type == "float":
            return Real(self.low, self.high, name=self.name)
        elif self.param_type == "categorical":
            return Categorical(self.choices, name=self.name)
        return None


@dataclass
class OptimizationConfig:
    """优化配置"""
    method: OptimizationMethod = OptimizationMethod.GENETIC

    # 遗传算法参数
    population_size: int = 50
    generations: int = 30
    crossover_prob: float = 0.7
    mutation_prob: float = 0.2
    elite_size: int = 5

    # 贝叶斯优化参数
    n_calls: int = 50
    n_initial_points: int = 10

    # 并行配置
    n_jobs: int = 1

    # 早停
    early_stopping_rounds: int = 10
    tolerance: float = 0.001


@dataclass
class OptimizationResult:
    """优化结果"""
    best_params: Dict[str, Any]
    best_score: float
    optimization_history: List[float]
    parameter_importance: Dict[str, float]
    execution_time: float
    n_evaluations: int
    method: str

    def to_dict(self) -> dict:
        return {
            "best_params": self.best_params,
            "best_score": round(self.best_score, 4),
            "optimization_history": [round(s, 4) for s in self.optimization_history],
            "parameter_importance": self.parameter_importance,
            "execution_time": round(self.execution_time, 2),
            "n_evaluations": self.n_evaluations,
            "method": self.method,
        }


# ============ 遗传算法优化器 ============

class GeneticOptimizer:
    """遗传算法优化器"""

    def __init__(self, config: OptimizationConfig = None):
        self.config = config or OptimizationConfig()
        self._history: List[float] = []
        self._best_individual = None
        self._best_score = float('-inf')

    def optimize(
        self,
        param_ranges: List[ParameterRange],
        objective_func: Callable[[Dict], float],
        n_jobs: int = 1,
    ) -> OptimizationResult:
        """执行优化"""
        start_time = time.time()

        if not DEAP_AVAILABLE:
            logger.warning("[GeneticOptimizer] DEAP未安装，使用简化优化")
            return self._simple_optimize(param_ranges, objective_func)

        # 创建适应度和个体类
        if not hasattr(creator, "FitnessMax"):
            creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        if not hasattr(creator, "Individual"):
            creator.create("Individual", list, fitness=creator.FitnessMax)

        # 初始化工具箱
        toolbox = base.Toolbox()

        # 注册个体生成函数
        def create_individual():
            return [pr.sample() for pr in param_ranges]

        toolbox.register("individual", tools.initIterate, creator.Individual, create_individual)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)

        # 注册评估函数
        def evaluate(individual):
            params = {pr.name: val for pr, val in zip(param_ranges, individual)}
            score = objective_func(params)
            return (score,)

        toolbox.register("evaluate", evaluate)
        toolbox.register("mate", tools.cxTwoPoint)
        toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=1, indpb=0.2)
        toolbox.register("select", tools.selTournament, tournsize=3)

        # 创建初始种群
        population = toolbox.population(n=self.config.population_size)

        # 评估初始种群
        fitnesses = list(map(toolbox.evaluate, population))
        for ind, fit in zip(population, fitnesses):
            ind.fitness.values = fit

        # 进化
        for gen in range(self.config.generations):
            # 选择
            offspring = toolbox.select(population, len(population))
            offspring = list(map(toolbox.clone, offspring))

            # 交叉
            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < self.config.crossover_prob:
                    toolbox.mate(child1, child2)
                    del child1.fitness.values
                    del child2.fitness.values

            # 变异
            for mutant in offspring:
                if random.random() < self.config.mutation_prob:
                    toolbox.mutate(mutant)
                    del mutant.fitness.values

            # 评估新个体
            invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
            fitnesses = list(map(toolbox.evaluate, invalid_ind))
            for ind, fit in zip(invalid_ind, fitnesses):
                ind.fitness.values = fit

            # 精英保留
            elite = tools.selBest(population, self.config.elite_size)
            offspring.extend(elite)

            # 更新种群
            population = offspring

            # 记录最佳
            best = tools.selBest(population, 1)[0]
            self._history.append(best.fitness.values[0])

            logger.debug(f"[Genetic] Gen {gen+1}: Best = {best.fitness.values[0]:.4f}")

        # 最终结果
        best_individual = tools.selBest(population, 1)[0]
        best_params = {pr.name: val for pr, val in zip(param_ranges, best_individual)}
        best_score = best_individual.fitness.values[0]

        execution_time = time.time() - start_time

        # 参数重要性
        importance = self._calculate_importance(population, param_ranges)

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            optimization_history=self._history,
            parameter_importance=importance,
            execution_time=execution_time,
            n_evaluations=self.config.population_size * self.config.generations,
            method="genetic",
        )

    def _simple_optimize(
        self,
        param_ranges: List[ParameterRange],
        objective_func: Callable,
    ) -> OptimizationResult:
        """简化优化"""
        start_time = time.time()

        best_params = None
        best_score = float('-inf')

        for _ in range(self.config.n_calls):
            params = {pr.name: pr.sample() for pr in param_ranges}
            score = objective_func(params)
            self._history.append(score)

            if score > best_score:
                best_score = score
                best_params = params

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            optimization_history=self._history,
            parameter_importance={},
            execution_time=time.time() - start_time,
            n_evaluations=self.config.n_calls,
            method="random",
        )

    def _calculate_importance(
        self,
        population: List,
        param_ranges: List[ParameterRange],
    ) -> Dict[str, float]:
        """计算参数重要性"""
        importance = {}

        for i, pr in enumerate(param_ranges):
            values = [ind[i] for ind in population]
            scores = [ind.fitness.values[0] for ind in population]

            # 计算相关系数
            if len(set(values)) > 1:
                try:
                    corr = np.corrcoef(values, scores)[0, 1]
                    importance[pr.name] = abs(corr) if not np.isnan(corr) else 0
                except Exception as e:
                    logger.warning("[ParamOptimizer] corrcoef failed for %s: %s", pr.name, e)
                    importance[pr.name] = 0
            else:
                importance[pr.name] = 0

        return importance


# ============ 贝叶斯优化器 ============

class BayesianOptimizer:
    """贝叶斯优化器"""

    def __init__(self, config: OptimizationConfig = None):
        self.config = config or OptimizationConfig()
        self._history: List[float] = []

    def optimize(
        self,
        param_ranges: List[ParameterRange],
        objective_func: Callable[[Dict], float],
        n_jobs: int = 1,
    ) -> OptimizationResult:
        """执行优化"""
        start_time = time.time()

        if not SKOPT_AVAILABLE:
            logger.warning("[BayesianOptimizer] scikit-optimize未安装，使用随机搜索")
            return self._random_optimize(param_ranges, objective_func)

        # 构建搜索空间
        dimensions = [pr.to_skopt_space() for pr in param_ranges]

        # 包装目标函数
        @use_named_args(dimensions)
        def objective(**params):
            score = objective_func(params)
            self._history.append(score)
            return -score  # 最小化负值 = 最大化正值

        # 执行优化
        result = gp_minimize(
            func=objective,
            dimensions=dimensions,
            n_calls=self.config.n_calls,
            n_initial_points=self.config.n_initial_points,
            random_state=42,
        )

        # 提取结果
        best_params = {pr.name: val for pr, val in zip(param_ranges, result.x)}
        best_score = -result.fun

        # 参数重要性
        importance = {}
        if hasattr(result, 'models') and result.models:
            try:
                from skopt.plots import plot_objective
                # 简化处理
                for i, pr in enumerate(param_ranges):
                    importance[pr.name] = 1.0 / len(param_ranges)  # 等权重
            except Exception:
                pass

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            optimization_history=[-s for s in result.func_vals],
            parameter_importance=importance,
            execution_time=time.time() - start_time,
            n_evaluations=len(result.func_vals),
            method="bayesian",
        )

    def _random_optimize(
        self,
        param_ranges: List[ParameterRange],
        objective_func: Callable,
    ) -> OptimizationResult:
        """随机优化"""
        start_time = time.time()

        best_params = None
        best_score = float('-inf')

        for _ in range(self.config.n_calls):
            params = {pr.name: pr.sample() for pr in param_ranges}
            score = objective_func(params)
            self._history.append(score)

            if score > best_score:
                best_score = score
                best_params = params

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            optimization_history=self._history,
            parameter_importance={},
            execution_time=time.time() - start_time,
            n_evaluations=self.config.n_calls,
            method="random",
        )


# ============ 多目标优化器 ============

class MultiObjectiveOptimizer:
    """多目标优化器"""

    def __init__(self, config: OptimizationConfig = None):
        self.config = config or OptimizationConfig()

    def optimize(
        self,
        param_ranges: List[ParameterRange],
        objective_funcs: List[Tuple[Callable, ObjectiveType]],  # [(func, type), ...]
        weights: List[float] = None,
    ) -> Dict[str, Any]:
        """多目标优化"""
        weights = weights or [1.0] * len(objective_funcs)

        # 归一化权重
        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]

        # 组合目标函数
        def combined_objective(params: Dict) -> float:
            scores = []
            for (func, obj_type), weight in zip(objective_funcs, weights):
                score = func(params)
                if obj_type == ObjectiveType.MINIMIZE:
                    score = -score
                scores.append(score * weight)
            return sum(scores)

        # 使用单目标优化
        optimizer = GeneticOptimizer(self.config)
        result = optimizer.optimize(param_ranges, combined_objective)

        # 计算各目标分数
        individual_scores = {}
        for i, (func, obj_type) in enumerate(objective_funcs):
            score = func(result.best_params)
            individual_scores[f"objective_{i}"] = score

        return {
            "best_params": result.best_params,
            "combined_score": result.best_score,
            "individual_scores": individual_scores,
            "optimization_history": result.optimization_history,
        }


# ============ 参数敏感性分析 ============

class SensitivityAnalyzer:
    """参数敏感性分析"""

    def analyze(
        self,
        param_ranges: List[ParameterRange],
        objective_func: Callable,
        n_samples: int = 10,
    ) -> Dict[str, Dict]:
        """分析参数敏感性"""
        results = {}

        for target_param in param_ranges:
            param_results = []
            other_params = {pr.name: pr.sample() for pr in param_ranges if pr != target_param}

            # 遍历目标参数
            if target_param.param_type == "int":
                values = np.linspace(target_param.low, target_param.high, n_samples, dtype=int)
            elif target_param.param_type == "float":
                values = np.linspace(target_param.low, target_param.high, n_samples)
            else:
                values = target_param.choices

            for value in values:
                params = {**other_params, target_param.name: value}
                score = objective_func(params)
                param_results.append({"value": value, "score": score})

            # 计算敏感性
            scores = [r["score"] for r in param_results]
            sensitivity = max(scores) - min(scores) if scores else 0

            results[target_param.name] = {
                "sensitivity": sensitivity,
                "values": param_results,
                "best_value": param_results[np.argmax(scores)]["value"],
            }

        return results


# ============ 统一优化接口 ============

class ParameterOptimizer:
    """参数优化器统一接口"""

    def __init__(self, config: OptimizationConfig = None):
        self.config = config or OptimizationConfig()

        self._optimizers = {
            OptimizationMethod.GENETIC: GeneticOptimizer,
            OptimizationMethod.BAYESIAN: BayesianOptimizer,
        }

    def optimize(
        self,
        param_ranges: List[ParameterRange],
        objective_func: Callable[[Dict], float],
        method: OptimizationMethod = None,
    ) -> OptimizationResult:
        """执行优化"""
        method = method or self.config.method

        optimizer_class = self._optimizers.get(method, GeneticOptimizer)
        optimizer = optimizer_class(self.config)

        logger.info(f"[ParameterOptimizer] 开始优化: {method.value}")
        result = optimizer.optimize(param_ranges, objective_func)

        logger.info(f"[ParameterOptimizer] 优化完成: Best Score = {result.best_score:.4f}")
        return result

    def sensitivity_analysis(
        self,
        param_ranges: List[ParameterRange],
        objective_func: Callable,
        n_samples: int = 10,
    ) -> Dict[str, Dict]:
        """敏感性分析"""
        analyzer = SensitivityAnalyzer()
        return analyzer.analyze(param_ranges, objective_func, n_samples)


# ============ 预定义参数范围 ============

def get_default_param_ranges() -> List[ParameterRange]:
    """获取默认参数范围"""
    return [
        ParameterRange(name="whitelist_size", param_type="int", low=30, high=100),
        ParameterRange(name="buffer_size", param_type="int", low=5, high=20),
        ParameterRange(name="max_single_position", param_type="float", low=0.02, high=0.10),
        ParameterRange(name="max_drawdown", param_type="float", low=0.05, high=0.15),
        ParameterRange(name="signal_threshold", param_type="float", low=60.0, high=80.0),
        ParameterRange(name="rebalance_days", param_type="int", low=1, high=10),
    ]


# ============ 便捷函数 ============

def optimize_params(
    objective_func: Callable[[Dict], float],
    param_ranges: List[ParameterRange] = None,
    method: OptimizationMethod = OptimizationMethod.GENETIC,
    n_calls: int = 50,
) -> OptimizationResult:
    """优化参数"""
    param_ranges = param_ranges or get_default_param_ranges()

    config = OptimizationConfig(
        method=method,
        n_calls=n_calls,
    )

    optimizer = ParameterOptimizer(config)
    return optimizer.optimize(param_ranges, objective_func, method)
