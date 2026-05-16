"""松岗量化可转债策略 V3.0 因子挖掘框架模块

功能:
- 遗传算法因子挖掘
- 因子正交化处理
- 因子有效性检验
- 因子库管理
- 因子报告生成
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple, Callable
from enum import Enum
import logging
import numpy as np
import pandas as pd
from collections import deque, defaultdict
import threading
import random
import json
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class FactorCategory(str, Enum):
    """因子类别"""
    VALUE = "value"           # 价值因子
    MOMENTUM = "momentum"     # 动量因子
    QUALITY = "quality"       # 质量因子
    VOLATILITY = "volatility" # 波动率因子
    LIQUIDITY = "liquidity"   # 流动性因子
    TECHNICAL = "technical"   # 技术因子
    FUNDAMENTAL = "fundamental"  # 基本面因子
    SENTIMENT = "sentiment"   # 情绪因子
    CUSTOM = "custom"         # 自定义因子


class FactorStatus(str, Enum):
    """因子状态"""
    DRAFT = "draft"           # 草稿
    TESTING = "testing"       # 测试中
    VALIDATED = "validated"   # 已验证
    DEPRECATED = "deprecated" # 已废弃


class OrthogonalMethod(str, Enum):
    """正交化方法"""
    GRAM_SCHMIDT = "gram_schmidt"
    PCA = "pca"
    RESIDUAL = "residual"
    SYMMETRIC = "symmetric"


class GeneticOperator(str, Enum):
    """遗传算子"""
    CROSSOVER = "crossover"
    MUTATION = "mutation"
    REPRODUCTION = "reproduction"


# ============ 数据模型 ============

@dataclass
class FactorExpression:
    """因子表达式"""
    expression_id: str
    formula: str
    operators: List[str]
    operands: List[str]
    parameters: Dict[str, float] = field(default_factory=dict)

    def evaluate(self, data: pd.DataFrame) -> pd.Series:
        """计算因子值"""
        try:
            # 安全评估
            local_vars = {}
            for col in data.columns:
                local_vars[col] = data[col].values

            for param, value in self.parameters.items():
                local_vars[param] = value

            result = eval(self.formula, {"__builtins__": {}}, local_vars)
            return pd.Series(result, index=data.index)
        except Exception as e:
            logger.error(f"[FactorExpression] 计算失败: {e}")
            return pd.Series(np.nan, index=data.index)


@dataclass
class Factor:
    """因子"""
    factor_id: str
    name: str
    category: FactorCategory
    expression: FactorExpression
    description: str = ""
    status: FactorStatus = FactorStatus.DRAFT
    created_at: datetime = None
    updated_at: datetime = None
    author: str = ""

    # 因子指标
    ic_mean: float = 0
    ic_std: float = 0
    icir: float = 0
    turnover: float = 0
    monotonicity: float = 0

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """计算因子值"""
        return self.expression.evaluate(data)

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "status": self.status.value,
            "expression": self.expression.formula,
            "ic_mean": round(self.ic_mean, 4),
            "ic_std": round(self.ic_std, 4),
            "icir": round(self.icir, 4),
            "turnover": round(self.turnover, 4),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class FactorTestResult:
    """因子测试结果"""
    factor_id: str
    test_period: Tuple[datetime, datetime]
    ic_series: List[float]
    ic_mean: float
    ic_std: float
    icir: float
    t_stat: float
    p_value: float
    turnover: float
    monotonicity: float
    group_returns: List[float]
    long_short_return: float
    passed: bool = False

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "test_period": [d.isoformat() for d in self.test_period],
            "ic_mean": round(self.ic_mean, 4),
            "ic_std": round(self.ic_std, 4),
            "icir": round(self.icir, 4),
            "t_stat": round(self.t_stat, 4),
            "p_value": round(self.p_value, 4),
            "turnover": round(self.turnover, 4),
            "monotonicity": round(self.monotonicity, 4),
            "long_short_return": round(self.long_short_return, 4),
            "passed": self.passed,
        }


@dataclass
class GeneticConfig:
    """遗传算法配置"""
    population_size: int = 100
    max_generations: int = 50
    crossover_rate: float = 0.8
    mutation_rate: float = 0.1
    elitism_rate: float = 0.1
    tournament_size: int = 5
    max_depth: int = 5
    min_ic_threshold: float = 0.02
    max_turnover: float = 0.5


# ============ 因子有效性检验器 ============

class FactorValidator:
    """因子有效性检验器"""

    def __init__(self):
        self._test_results: Dict[str, FactorTestResult] = {}

    def test_factor(
        self,
        factor: Factor,
        data: pd.DataFrame,
        forward_returns: pd.Series,
        n_groups: int = 5,
    ) -> FactorTestResult:
        """测试因子"""
        # 计算因子值
        factor_values = factor.calculate(data)

        # 计算IC
        ic_series = self._calculate_ic(factor_values, forward_returns)

        # IC统计
        ic_mean = np.nanmean(ic_series)
        ic_std = np.nanstd(ic_series)
        icir = ic_mean / ic_std if ic_std > 0 else 0

        # t检验
        valid_ics = [ic for ic in ic_series if not np.isnan(ic)]
        t_stat, p_value = self._t_test(valid_ics)

        # 分组收益
        group_returns = self._calculate_group_returns(
            factor_values, forward_returns, n_groups
        )

        # 多空收益
        long_short_return = group_returns[-1] - group_returns[0] if len(group_returns) > 1 else 0

        # 换手率
        turnover = self._calculate_turnover(factor_values)

        # 单调性
        monotonicity = self._calculate_monotonicity(group_returns)

        # 判断是否通过
        passed = (
            abs(ic_mean) >= 0.02
            and abs(icir) >= 0.5
            and p_value < 0.05
            and turnover <= 0.5
        )

        result = FactorTestResult(
            factor_id=factor.factor_id,
            test_period=(data.index[0], data.index[-1]),
            ic_series=ic_series.tolist(),
            ic_mean=ic_mean,
            ic_std=ic_std,
            icir=icir,
            t_stat=t_stat,
            p_value=p_value,
            turnover=turnover,
            monotonicity=monotonicity,
            group_returns=group_returns,
            long_short_return=long_short_return,
            passed=passed,
        )

        self._test_results[factor.factor_id] = result

        return result

    def _calculate_ic(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
    ) -> List[float]:
        """计算IC序列"""
        # 按日期分组计算IC
        ic_list = []

        # 简化处理：计算整体IC
        if len(factor_values) == len(forward_returns):
            valid_mask = ~(factor_values.isna() | forward_returns.isna())
            if valid_mask.sum() > 10:
                ic = factor_values[valid_mask].corr(forward_returns[valid_mask])
                ic_list.append(ic)

        return ic_list

    def _t_test(self, values: List[float]) -> Tuple[float, float]:
        """t检验"""
        if len(values) < 2:
            return 0, 1

        values = np.array(values)
        mean = np.mean(values)
        std = np.std(values, ddof=1)

        if std == 0:
            return 0, 1

        t_stat = mean / (std / np.sqrt(len(values)))

        # 简化p值计算
        from scipy import stats
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), len(values) - 1))

        return t_stat, p_value

    def _calculate_group_returns(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
        n_groups: int,
    ) -> List[float]:
        """计算分组收益"""
        valid_mask = ~(factor_values.isna() | forward_returns.isna())
        factor_valid = factor_values[valid_mask]
        returns_valid = forward_returns[valid_mask]

        if len(factor_valid) < n_groups:
            return []

        # 分组
        labels = pd.qcut(factor_valid, n_groups, labels=False, duplicates="drop")

        group_returns = []
        for g in range(n_groups):
            mask = labels == g
            if mask.sum() > 0:
                group_returns.append(returns_valid[mask].mean())

        return group_returns

    def _calculate_turnover(self, factor_values: pd.Series) -> float:
        """计算换手率"""
        if len(factor_values) < 2:
            return 0

        # 简化计算：使用因子值变化率
        diff = factor_values.diff().abs()
        turnover = diff.mean() / factor_values.abs().mean() if factor_values.abs().mean() > 0 else 0

        return min(1.0, turnover)

    def _calculate_monotonicity(self, group_returns: List[float]) -> float:
        """计算单调性"""
        if len(group_returns) < 2:
            return 0

        # 计算趋势一致性
        increasing = sum(
            1 for i in range(1, len(group_returns))
            if group_returns[i] >= group_returns[i - 1]
        )
        decreasing = sum(
            1 for i in range(1, len(group_returns))
            if group_returns[i] <= group_returns[i - 1]
        )

        monotonicity = max(increasing, decreasing) / (len(group_returns) - 1)

        return monotonicity

    def get_test_result(self, factor_id: str) -> Optional[FactorTestResult]:
        """获取测试结果"""
        return self._test_results.get(factor_id)


# ============ 因子正交化处理器 ============

class FactorOrthogonalizer:
    """因子正交化处理器"""

    def orthogonalize(
        self,
        factors: pd.DataFrame,
        method: OrthogonalMethod = OrthogonalMethod.GRAM_SCHMIDT,
    ) -> pd.DataFrame:
        """正交化因子"""
        if method == OrthogonalMethod.GRAM_SCHMIDT:
            return self._gram_schmidt(factors)
        elif method == OrthogonalMethod.PCA:
            return self._pca_orthogonalize(factors)
        elif method == OrthogonalMethod.RESIDUAL:
            return self._residual_orthogonalize(factors)
        else:
            return self._symmetric_orthogonalize(factors)

    def _gram_schmidt(self, factors: pd.DataFrame) -> pd.DataFrame:
        """Gram-Schmidt正交化"""
        result = pd.DataFrame(index=factors.index)
        columns = factors.columns.tolist()

        for i, col in enumerate(columns):
            if i == 0:
                result[col] = factors[col]
            else:
                # 减去在前面因子上的投影
                residual = factors[col].copy()
                for prev_col in columns[:i]:
                    if prev_col in result.columns:
                        projection = (
                            factors[col].dot(result[prev_col])
                            / result[prev_col].dot(result[prev_col])
                        )
                        residual = residual - projection * result[prev_col]

                result[col] = residual

        # 标准化
        result = (result - result.mean()) / result.std()

        return result

    def _pca_orthogonalize(self, factors: pd.DataFrame) -> pd.DataFrame:
        """PCA正交化"""
        from sklearn.decomposition import PCA

        # 标准化
        factors_std = (factors - factors.mean()) / factors.std()

        # PCA
        pca = PCA(n_components=factors.shape[1])
        transformed = pca.fit_transform(factors_std.fillna(0))

        result = pd.DataFrame(
            transformed,
            index=factors.index,
            columns=[f"PC{i + 1}" for i in range(factors.shape[1])],
        )

        return result

    def _residual_orthogonalize(self, factors: pd.DataFrame) -> pd.DataFrame:
        """残差正交化"""
        result = factors.copy()
        columns = factors.columns.tolist()

        for i in range(1, len(columns)):
            col = columns[i]
            prev_cols = columns[:i]

            # 对前面因子回归
            X = factors[prev_cols].fillna(0)
            y = factors[col].fillna(0)

            # OLS回归
            try:
                beta = np.linalg.lstsq(X, y, rcond=None)[0]
                residual = y - X.dot(beta)
                result[col] = residual
            except Exception:
                pass

        # 标准化
        result = (result - result.mean()) / result.std()

        return result

    def _symmetric_orthogonalize(self, factors: pd.DataFrame) -> pd.DataFrame:
        """对称正交化"""
        # 计算协方差矩阵
        cov = factors.cov()

        # 特征值分解
        eigenvalues, eigenvectors = np.linalg.eigh(cov)

        # 构造正交化矩阵
        D_inv_sqrt = np.diag(1.0 / np.sqrt(np.maximum(eigenvalues, 1e-10)))
        orthogonal_matrix = eigenvectors @ D_inv_sqrt @ eigenvectors.T

        # 应用变换
        result = factors @ orthogonal_matrix
        result.columns = factors.columns

        return result

    def calculate_correlation_matrix(
        self,
        factors: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算因子相关性矩阵"""
        return factors.corr()


# ============ 遗传算法因子挖掘器 ============

class GeneticFactorMiner:
    """遗传算法因子挖掘器"""

    def __init__(self, config: GeneticConfig = None):
        self.config = config or GeneticConfig()
        self._population: List[Factor] = []
        self._best_factors: List[Factor] = []
        self._generation = 0

        # 算子和操作数池
        self._operators = [
            "add", "sub", "mul", "div",
            "rank", "ts_rank", "ts_mean", "ts_std",
            "ts_max", "ts_min", "ts_delta", "ts_corr",
            "abs", "log", "sign", "power",
        ]

        self._operands = [
            "close", "open", "high", "low", "volume",
            "vwap", "turnover", "amount",
        ]

    def initialize_population(self) -> List[Factor]:
        """初始化种群"""
        self._population = []

        for i in range(self.config.population_size):
            factor = self._random_factor(i)
            self._population.append(factor)

        self._generation = 0

        return self._population

    def _random_factor(self, index: int) -> Factor:
        """生成随机因子"""
        depth = random.randint(1, self.config.max_depth)
        formula = self._generate_formula(depth)

        expression = FactorExpression(
            expression_id=f"expr_{index}",
            formula=formula,
            operators=random.sample(self._operators, min(3, len(self._operators))),
            operands=random.sample(self._operands, min(2, len(self._operands))),
        )

        return Factor(
            factor_id=f"genetic_{index}",
            name=f"遗传因子_{index}",
            category=FactorCategory.CUSTOM,
            expression=expression,
            description=f"遗传算法生成的因子，公式: {formula}",
        )

    def _generate_formula(self, depth: int) -> str:
        """生成公式"""
        if depth == 1:
            return random.choice(self._operands)

        operator = random.choice(self._operators[:4])  # 基础运算
        left = self._generate_formula(depth - 1)
        right = self._generate_formula(depth - 1)

        return f"({left} {operator} {right})"

    def evolve(
        self,
        fitness_scores: List[float],
    ) -> List[Factor]:
        """进化"""
        if len(fitness_scores) != len(self._population):
            raise ValueError("适应度分数数量与种群大小不匹配")

        # 记录最优个体
        sorted_pairs = sorted(
            zip(self._population, fitness_scores),
            key=lambda x: x[1],
            reverse=True,
        )

        elite_count = int(self.config.population_size * self.config.elitism_rate)
        elites = [pair[0] for pair in sorted_pairs[:elite_count]]
        self._best_factors.extend(elites)

        # 选择
        selected = self._selection(fitness_scores)

        # 交叉和变异
        new_population = elites.copy()

        while len(new_population) < self.config.population_size:
            parent1, parent2 = random.sample(selected, 2)

            if random.random() < self.config.crossover_rate:
                child1, child2 = self._crossover(parent1, parent2)
                new_population.extend([child1, child2])
            else:
                new_population.extend([parent1, parent2])

        # 变异
        for i in range(len(new_population)):
            if random.random() < self.config.mutation_rate:
                new_population[i] = self._mutate(new_population[i])

        # 确保种群大小
        new_population = new_population[:self.config.population_size]

        self._population = new_population
        self._generation += 1

        return self._population

    def _selection(self, fitness_scores: List[float]) -> List[Factor]:
        """锦标赛选择"""
        selected = []

        for _ in range(self.config.population_size):
            # 随机选择tournament_size个个体
            indices = random.sample(
                range(len(self._population)),
                min(self.config.tournament_size, len(self._population)),
            )

            # 选择适应度最高的
            best_idx = max(indices, key=lambda i: fitness_scores[i])
            selected.append(self._population[best_idx])

        return selected

    def _crossover(self, parent1: Factor, parent2: Factor) -> Tuple[Factor, Factor]:
        """交叉"""
        # 交换公式的一部分
        formula1 = parent1.expression.formula
        formula2 = parent2.expression.formula

        # 简化处理：随机交换
        if random.random() < 0.5:
            formula1, formula2 = formula2, formula1

        child1 = Factor(
            factor_id=f"genetic_{self._generation}_{random.randint(1000, 9999)}",
            name=f"遗传因子_{self._generation}_A",
            category=FactorCategory.CUSTOM,
            expression=FactorExpression(
                expression_id=f"expr_{random.randint(10000, 99999)}",
                formula=formula1,
                operators=list(set(parent1.expression.operators + parent2.expression.operators)),
                operands=list(set(parent1.expression.operands + parent2.expression.operands)),
            ),
            description=f"交叉生成的因子",
        )

        child2 = Factor(
            factor_id=f"genetic_{self._generation}_{random.randint(1000, 9999)}",
            name=f"遗传因子_{self._generation}_B",
            category=FactorCategory.CUSTOM,
            expression=FactorExpression(
                expression_id=f"expr_{random.randint(10000, 99999)}",
                formula=formula2,
                operators=list(set(parent1.expression.operators + parent2.expression.operators)),
                operands=list(set(parent1.expression.operands + parent2.expression.operands)),
            ),
            description=f"交叉生成的因子",
        )

        return child1, child2

    def _mutate(self, factor: Factor) -> Factor:
        """变异"""
        # 随机修改公式的一部分
        formula = factor.expression.formula

        # 简化处理：添加随机运算
        if random.random() < 0.5:
            operand = random.choice(self._operands)
            operator = random.choice(self._operators[:4])
            formula = f"({formula} {operator} {operand})"
        else:
            operator = random.choice(self._operators[4:8])
            formula = f"{operator}({formula})"

        return Factor(
            factor_id=factor.factor_id,
            name=factor.name,
            category=factor.category,
            expression=FactorExpression(
                expression_id=factor.expression.expression_id,
                formula=formula,
                operators=factor.expression.operators + [random.choice(self._operators)],
                operands=factor.expression.operands,
            ),
            description=f"变异后的因子",
        )

    def run(
        self,
        data: pd.DataFrame,
        forward_returns: pd.Series,
        max_generations: int = None,
    ) -> List[Factor]:
        """运行遗传算法"""
        max_generations = max_generations or self.config.max_generations

        # 初始化
        self.initialize_population()

        validator = FactorValidator()

        for gen in range(max_generations):
            # 计算适应度
            fitness_scores = []

            for factor in self._population:
                try:
                    result = validator.test_factor(factor, data, forward_returns)
                    # 适应度 = |IC均值| * ICIR - 换手率惩罚
                    fitness = abs(result.ic_mean) * abs(result.icir) - result.turnover * 0.1
                    fitness_scores.append(fitness)
                except Exception:
                    fitness_scores.append(0)

            # 进化
            self.evolve(fitness_scores)

            logger.info(
                f"[GeneticFactorMiner] 第{gen + 1}代完成, "
                f"最优适应度: {max(fitness_scores):.4f}"
            )

        # 返回最优因子
        return sorted(self._best_factors, key=lambda f: abs(f.ic_mean), reverse=True)[:10]


# ============ 因子库管理器 ============

class FactorLibrary:
    """因子库管理器"""

    def __init__(self):
        self._factors: Dict[str, Factor] = {}
        self._categories: Dict[FactorCategory, List[str]] = defaultdict(list)
        self._lock = threading.Lock()

    def add_factor(self, factor: Factor) -> bool:
        """添加因子"""
        with self._lock:
            if factor.factor_id in self._factors:
                return False

            self._factors[factor.factor_id] = factor
            self._categories[factor.category].append(factor.factor_id)

            return True

    def get_factor(self, factor_id: str) -> Optional[Factor]:
        """获取因子"""
        return self._factors.get(factor_id)

    def get_factors_by_category(self, category: FactorCategory) -> List[Factor]:
        """按类别获取因子"""
        return [
            self._factors[fid]
            for fid in self._categories.get(category, [])
            if fid in self._factors
        ]

    def get_all_factors(self) -> List[Factor]:
        """获取所有因子"""
        return list(self._factors.values())

    def update_factor(self, factor: Factor) -> bool:
        """更新因子"""
        with self._lock:
            if factor.factor_id not in self._factors:
                return False

            factor.updated_at = datetime.now()
            self._factors[factor.factor_id] = factor

            return True

    def delete_factor(self, factor_id: str) -> bool:
        """删除因子"""
        with self._lock:
            if factor_id not in self._factors:
                return False

            factor = self._factors.pop(factor_id)
            self._categories[factor.category].remove(factor_id)

            return True

    def search_factors(
        self,
        keyword: str = None,
        category: FactorCategory = None,
        status: FactorStatus = None,
        min_ic: float = None,
    ) -> List[Factor]:
        """搜索因子"""
        factors = self.get_all_factors()

        if keyword:
            factors = [f for f in factors if keyword in f.name or keyword in f.description]

        if category:
            factors = [f for f in factors if f.category == category]

        if status:
            factors = [f for f in factors if f.status == status]

        if min_ic is not None:
            factors = [f for f in factors if abs(f.ic_mean) >= min_ic]

        return factors

    def export_library(self, filepath: str):
        """导出因子库"""
        data = {
            factor_id: factor.to_dict()
            for factor_id, factor in self._factors.items()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_library(self, filepath: str):
        """导入因子库"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for factor_id, factor_data in data.items():
            # 重建因子对象
            expression = FactorExpression(
                expression_id=f"expr_{factor_id}",
                formula=factor_data["expression"],
                operators=[],
                operands=[],
            )

            factor = Factor(
                factor_id=factor_id,
                name=factor_data["name"],
                category=FactorCategory(factor_data["category"]),
                expression=expression,
                description=factor_data["description"],
                status=FactorStatus(factor_data["status"]),
                ic_mean=factor_data["ic_mean"],
                ic_std=factor_data["ic_std"],
                icir=factor_data["icir"],
            )

            self.add_factor(factor)


# ============ 因子报告生成器 ============

class FactorReportGenerator:
    """因子报告生成器"""

    def generate_report(
        self,
        factor: Factor,
        test_result: FactorTestResult = None,
    ) -> str:
        """生成因子报告"""
        report = f"""
# 因子分析报告

## 基本信息

- **因子名称**: {factor.name}
- **因子ID**: {factor.factor_id}
- **因子类别**: {factor.category.value}
- **创建时间**: {factor.created_at.strftime('%Y-%m-%d %H:%M:%S')}
- **状态**: {factor.status.value}

## 因子公式

```
{factor.expression.formula}
```

## 描述

{factor.description}

## 因子指标

| 指标 | 数值 |
|------|------|
| IC均值 | {factor.ic_mean:.4f} |
| IC标准差 | {factor.ic_std:.4f} |
| ICIR | {factor.icir:.4f} |
| 换手率 | {factor.turnover:.4f} |
| 单调性 | {factor.monotonicity:.4f} |
"""

        if test_result:
            report += f"""
## 测试结果

| 指标 | 数值 |
|------|------|
| 测试周期 | {test_result.test_period[0].strftime('%Y-%m-%d')} ~ {test_result.test_period[1].strftime('%Y-%m-%d')} |
| IC均值 | {test_result.ic_mean:.4f} |
| IC标准差 | {test_result.ic_std:.4f} |
| ICIR | {test_result.icir:.4f} |
| t统计量 | {test_result.t_stat:.4f} |
| p值 | {test_result.p_value:.4f} |
| 换手率 | {test_result.turnover:.4f} |
| 单调性 | {test_result.monotonicity:.4f} |
| 多空收益 | {test_result.long_short_return:.4f} |
| 测试通过 | {'是' if test_result.passed else '否'} |

## 分组收益

"""
            for i, ret in enumerate(test_result.group_returns):
                report += f"- 第{i + 1}组: {ret:.4f}\n"

        report += """
---

*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

        return report

    def generate_comparison_report(
        self,
        factors: List[Factor],
    ) -> str:
        """生成因子对比报告"""
        report = """
# 因子对比报告

## 对比概览

| 因子名称 | 类别 | IC均值 | ICIR | 换手率 | 状态 |
|----------|------|--------|------|--------|------|
"""

        for factor in factors:
            report += f"| {factor.name} | {factor.category.value} | {factor.ic_mean:.4f} | {factor.icir:.4f} | {factor.turnover:.4f} | {factor.status.value} |\n"

        report += """
## 因子相关性

*建议进行正交化处理以降低因子相关性*

---

*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

        return report


# ============ 因子挖掘服务 ============

class FactorMiningService:
    """因子挖掘服务"""

    def __init__(self):
        self.library = FactorLibrary()
        self.validator = FactorValidator()
        self.orthogonalizer = FactorOrthogonalizer()
        self.miner = GeneticFactorMiner()
        self.report_generator = FactorReportGenerator()

    def create_factor(
        self,
        name: str,
        category: FactorCategory,
        formula: str,
        description: str = "",
    ) -> Factor:
        """创建因子"""
        factor_id = f"factor_{int(datetime.now().timestamp() * 1000)}"

        expression = FactorExpression(
            expression_id=f"expr_{factor_id}",
            formula=formula,
            operators=[],
            operands=[],
        )

        factor = Factor(
            factor_id=factor_id,
            name=name,
            category=category,
            expression=expression,
            description=description,
        )

        self.library.add_factor(factor)

        return factor

    def test_factor(
        self,
        factor: Factor,
        data: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> FactorTestResult:
        """测试因子"""
        result = self.validator.test_factor(factor, data, forward_returns)

        # 更新因子指标
        factor.ic_mean = result.ic_mean
        factor.ic_std = result.ic_std
        factor.icir = result.icir
        factor.turnover = result.turnover
        factor.monotonicity = result.monotonicity
        factor.status = FactorStatus.VALIDATED if result.passed else FactorStatus.TESTING

        self.library.update_factor(factor)

        return result

    def mine_factors(
        self,
        data: pd.DataFrame,
        forward_returns: pd.Series,
        max_generations: int = 50,
    ) -> List[Factor]:
        """挖掘因子"""
        best_factors = self.miner.run(data, forward_returns, max_generations)

        # 添加到因子库
        for factor in best_factors:
            self.library.add_factor(factor)

        return best_factors

    def orthogonalize_factors(
        self,
        factor_ids: List[str],
        data: pd.DataFrame,
        method: OrthogonalMethod = OrthogonalMethod.GRAM_SCHMIDT,
    ) -> pd.DataFrame:
        """正交化因子"""
        factors_data = pd.DataFrame()

        for fid in factor_ids:
            factor = self.library.get_factor(fid)
            if factor:
                factors_data[fid] = factor.calculate(data)

        return self.orthogonalizer.orthogonalize(factors_data, method)

    def generate_report(
        self,
        factor_id: str,
        include_test_result: bool = True,
    ) -> str:
        """生成报告"""
        factor = self.library.get_factor(factor_id)
        if not factor:
            return "因子不存在"

        test_result = None
        if include_test_result:
            test_result = self.validator.get_test_result(factor_id)

        return self.report_generator.generate_report(factor, test_result)


# ============ 便捷函数 ============

def create_factor_mining_service() -> FactorMiningService:
    """创建因子挖掘服务"""
    return FactorMiningService()


def test_single_factor(
    formula: str,
    data: pd.DataFrame,
    forward_returns: pd.Series,
) -> FactorTestResult:
    """测试单个因子"""
    service = FactorMiningService()
    factor = service.create_factor(
        name="临时因子",
        category=FactorCategory.CUSTOM,
        formula=formula,
    )
    return service.test_factor(factor, data, forward_returns)
