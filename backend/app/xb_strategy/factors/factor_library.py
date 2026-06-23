"""西部量化可转债策略 V3.0 量化因子库模块

功能:
- 因子挖掘
- 因子有效性检验
- 因子库管理
- 因子组合
- 因子正交化
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import numpy as np
import pandas as pd
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class FactorCategory(str, Enum):
    """因子类别"""
    VALUE = "value"           # 价值因子
    MOMENTUM = "momentum"     # 动量因子
    QUALITY = "quality"       # 质量因子
    SENTIMENT = "sentiment"   # 情绪因子
    LIQUIDITY = "liquidity"   # 流动性因子
    VOLATILITY = "volatility" # 波动率因子
    TECHNICAL = "technical"   # 技术因子
    FUNDAMENTAL = "fundamental"  # 基本面因子
    CONVERTIBLE = "convertible"  # 转债特有因子


class FactorType(str, Enum):
    """因子类型"""
    ALPHA = "alpha"   # Alpha因子
    BETA = "beta"     # Beta因子
    RISK = "risk"     # 风险因子


class TestPeriod(str, Enum):
    """测试周期"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# ============ 数据模型 ============

@dataclass
class FactorDefinition:
    """因子定义"""
    factor_id: str
    name: str
    category: FactorCategory
    factor_type: FactorType
    description: str
    formula: str  # 计算公式描述
    parameters: Dict[str, Any] = field(default_factory=dict)
    data_requirements: List[str] = field(default_factory=list)
    author: str = ""
    version: str = "1.0"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "name": self.name,
            "category": self.category.value,
            "factor_type": self.factor_type.value,
            "description": self.description,
            "formula": self.formula,
            "parameters": self.parameters,
            "data_requirements": self.data_requirements,
            "author": self.author,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class FactorResult:
    """因子计算结果"""
    factor_id: str
    date: date
    values: Dict[str, float]  # code -> value
    ranks: Dict[str, int] = None
    zscores: Dict[str, float] = None

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "date": self.date.isoformat(),
            "values": self.values,
            "ranks": self.ranks,
            "zscores": self.zscores,
        }


@dataclass
class FactorPerformance:
    """因子表现"""
    factor_id: str
    test_period: str
    ic_mean: float  # IC均值
    ic_std: float   # IC标准差
    ic_ir: float    # IC信息比率
    ic_positive_ratio: float  # IC正比例
    rank_ic_mean: float  # Rank IC均值
    monotonicity: float  # 单调性
    turnover: float  # 换手率
    returns: Dict[str, float] = None  # 分组收益
    sharpe: float = 0.0
    max_drawdown: float = 0.0

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "test_period": self.test_period,
            "ic_mean": round(self.ic_mean, 4),
            "ic_std": round(self.ic_std, 4),
            "ic_ir": round(self.ic_ir, 4),
            "ic_positive_ratio": round(self.ic_positive_ratio, 4),
            "rank_ic_mean": round(self.rank_ic_mean, 4),
            "monotonicity": round(self.monotonicity, 4),
            "turnover": round(self.turnover, 4),
            "returns": self.returns,
            "sharpe": round(self.sharpe, 4),
            "max_drawdown": round(self.max_drawdown, 4),
        }


# ============ 因子计算器基类 ============

class FactorCalculator:
    """因子计算器"""

    def __init__(self, definition: FactorDefinition):
        self.definition = definition
        self._cache: Dict[str, FactorResult] = {}

    def calculate(self, data: Dict[str, Any], date: date) -> FactorResult:
        """计算因子值"""
        raise NotImplementedError

    def _normalize(self, values: Dict[str, float]) -> Tuple[Dict[str, int], Dict[str, float]]:
        """标准化"""
        if not values:
            return {}, {}

        # 排名
        sorted_items = sorted(values.items(), key=lambda x: x[1], reverse=True)
        ranks = {code: rank + 1 for rank, (code, _) in enumerate(sorted_items)}

        # Z-Score
        vals = np.array(list(values.values()))
        mean = np.mean(vals)
        std = np.std(vals)
        zscores = {code: (v - mean) / std if std > 0 else 0 for code, v in values.items()}

        return ranks, zscores


# ============ 内置因子 ============

class MomentumFactor(FactorCalculator):
    """动量因子"""

    def calculate(self, data: Dict[str, Any], date: date) -> FactorResult:
        """计算动量因子"""
        prices = data.get("prices", {})  # {code: [price_history]}
        window = self.definition.parameters.get("window", 20)

        values = {}
        for code, price_list in prices.items():
            if len(price_list) >= window + 1:
                current = price_list[-1]
                past = price_list[-(window + 1)]
                momentum = (current - past) / past if past > 0 else 0
                values[code] = momentum

        ranks, zscores = self._normalize(values)

        return FactorResult(
            factor_id=self.definition.factor_id,
            date=date,
            values=values,
            ranks=ranks,
            zscores=zscores,
        )


class ValueFactor(FactorCalculator):
    """价值因子"""

    def calculate(self, data: Dict[str, Any], date: date) -> FactorResult:
        """计算价值因子"""
        cb_data = data.get("cb_data", {})

        values = {}
        for code, cb in cb_data.items():
            # 溢价率因子（越低越好，取负值）
            premium = cb.get("premium", 0)
            # 转股溢价率 + 纯债溢价率 综合价值
            conversion_premium = cb.get("conversion_premium", premium)
            bond_premium = cb.get("bond_premium", 0)

            # 价值因子 = -溢价率（溢价率低更优）
            value_score = -(conversion_premium + bond_premium * 0.5)
            values[code] = value_score

        ranks, zscores = self._normalize(values)

        return FactorResult(
            factor_id=self.definition.factor_id,
            date=date,
            values=values,
            ranks=ranks,
            zscores=zscores,
        )


class QualityFactor(FactorCalculator):
    """质量因子"""

    def calculate(self, data: Dict[str, Any], date: date) -> FactorResult:
        """计算质量因子"""
        stock_data = data.get("stock_data", {})

        values = {}
        for code, stock in stock_data.items():
            # ROE + 盈利稳定性 + 负债率
            roe = stock.get("roe", 0)
            debt_ratio = stock.get("debt_ratio", 0.5)
            profit_stability = stock.get("profit_stability", 0.5)

            # 质量得分
            quality = roe * 0.4 + (1 - debt_ratio) * 0.3 + profit_stability * 0.3
            values[code] = quality

        ranks, zscores = self._normalize(values)

        return FactorResult(
            factor_id=self.definition.factor_id,
            date=date,
            values=values,
            ranks=ranks,
            zscores=zscores,
        )


class LiquidityFactor(FactorCalculator):
    """流动性因子"""

    def calculate(self, data: Dict[str, Any], date: date) -> FactorResult:
        """计算流动性因子"""
        cb_data = data.get("cb_data", {})

        values = {}
        for code, cb in cb_data.items():
            # 成交额 + 换手率
            amount = cb.get("amount", 0)
            turnover = cb.get("turnover_rate", 0)

            # 流动性得分（对数化）
            liquidity = np.log1p(amount / 1e8) * 0.6 + turnover * 100 * 0.4
            values[code] = liquidity

        ranks, zscores = self._normalize(values)

        return FactorResult(
            factor_id=self.definition.factor_id,
            date=date,
            values=values,
            ranks=ranks,
            zscores=zscores,
        )


class VolatilityFactor(FactorCalculator):
    """波动率因子"""

    def calculate(self, data: Dict[str, Any], date: date) -> FactorResult:
        """计算波动率因子"""
        prices = data.get("prices", {})
        window = self.definition.parameters.get("window", 20)

        values = {}
        for code, price_list in prices.items():
            if len(price_list) >= window:
                returns = np.diff(price_list[-(window + 1):]) / price_list[-(window + 1):-1]
                # 去除异常值
                returns = returns[~np.isinf(returns)]
                if len(returns) > 0:
                    volatility = np.std(returns) * np.sqrt(252)  # 年化波动率
                    values[code] = -volatility  # 低波动更优

        ranks, zscores = self._normalize(values)

        return FactorResult(
            factor_id=self.definition.factor_id,
            date=date,
            values=values,
            ranks=ranks,
            zscores=zscores,
        )


# ============ 因子检验器 ============

class FactorTester:
    """因子有效性检验器"""

    def __init__(self):
        self._results: Dict[str, FactorPerformance] = {}

    def test_factor(
        self,
        factor_values: List[FactorResult],
        forward_returns: List[Dict[str, float]],  # 未来收益
        n_groups: int = 5,
    ) -> FactorPerformance:
        """检验因子有效性"""
        if len(factor_values) != len(forward_returns):
            raise ValueError("因子值和收益数据长度不匹配")

        # 计算IC序列
        ic_series = []
        rank_ic_series = []

        for factor_result, returns in zip(factor_values, forward_returns):
            # 获取共同标的
            common_codes = set(factor_result.values.keys()) & set(returns.keys())

            if len(common_codes) < 10:
                continue

            factor_vals = [factor_result.values[c] for c in common_codes]
            ret_vals = [returns[c] for c in common_codes]

            # 计算IC
            ic = np.corrcoef(factor_vals, ret_vals)[0, 1]
            if not np.isnan(ic):
                ic_series.append(ic)

            # 计算Rank IC
            rank_factor = np.argsort(np.argsort(factor_vals))
            rank_ret = np.argsort(np.argsort(ret_vals))
            rank_ic = np.corrcoef(rank_factor, rank_ret)[0, 1]
            if not np.isnan(rank_ic):
                rank_ic_series.append(rank_ic)

        # 统计指标
        ic_array = np.array(ic_series)
        rank_ic_array = np.array(rank_ic_series)

        ic_mean = np.mean(ic_array) if len(ic_array) > 0 else 0
        ic_std = np.std(ic_array) if len(ic_array) > 0 else 0
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        ic_positive_ratio = np.sum(ic_array > 0) / len(ic_array) if len(ic_array) > 0 else 0

        rank_ic_mean = np.mean(rank_ic_array) if len(rank_ic_array) > 0 else 0

        # 分组收益
        group_returns = self._calculate_group_returns(factor_values, forward_returns, n_groups)

        # 单调性检验
        monotonicity = self._test_monotonicity(group_returns)

        # 构建结果
        factor_id = factor_values[0].factor_id if factor_values else "unknown"

        performance = FactorPerformance(
            factor_id=factor_id,
            test_period="daily",
            ic_mean=ic_mean,
            ic_std=ic_std,
            ic_ir=ic_ir,
            ic_positive_ratio=ic_positive_ratio,
            rank_ic_mean=rank_ic_mean,
            monotonicity=monotonicity,
            turnover=0,  # 需要额外计算
            returns=group_returns,
        )

        self._results[factor_id] = performance
        return performance

    def _calculate_group_returns(
        self,
        factor_values: List[FactorResult],
        forward_returns: List[Dict[str, float]],
        n_groups: int,
    ) -> Dict[str, float]:
        """计算分组收益"""
        group_returns = {f"group_{i+1}": [] for i in range(n_groups)}

        for factor_result, returns in zip(factor_values, forward_returns):
            if not factor_result.ranks:
                continue

            n = len(factor_result.ranks)
            group_size = n // n_groups

            # 按排名分组
            sorted_codes = sorted(factor_result.ranks.keys(), key=lambda x: factor_result.ranks[x])

            for i in range(n_groups):
                start = i * group_size
                end = start + group_size if i < n_groups - 1 else n
                group_codes = sorted_codes[start:end]

                # 计算组内平均收益
                group_ret = np.mean([returns.get(c, 0) for c in group_codes if c in returns])
                if not np.isnan(group_ret):
                    group_returns[f"group_{i+1}"].append(group_ret)

        # 平均收益
        return {
            name: np.mean(rets) if rets else 0
            for name, rets in group_returns.items()
        }

    def _test_monotonicity(self, group_returns: Dict[str, float]) -> float:
        """测试单调性"""
        returns = list(group_returns.values())
        if len(returns) < 2:
            return 0

        # 计算趋势
        x = np.arange(len(returns))
        y = np.array(returns)

        # 线性回归斜率
        slope = np.polyfit(x, y, 1)[0]

        # 归一化到[-1, 1]
        return np.clip(slope * 10, -1, 1)


# ============ 因子库管理器 ============

class FactorLibrary:
    """因子库管理器"""

    # 预定义因子
    PREDEFINED_FACTORS = [
        FactorDefinition(
            factor_id="momentum_20d",
            name="20日动量",
            category=FactorCategory.MOMENTUM,
            factor_type=FactorType.ALPHA,
            description="过去20个交易日的价格动量",
            formula="(close[-1] - close[-21]) / close[-21]",
            parameters={"window": 20},
            data_requirements=["close"],
        ),
        FactorDefinition(
            factor_id="momentum_60d",
            name="60日动量",
            category=FactorCategory.MOMENTUM,
            factor_type=FactorType.ALPHA,
            description="过去60个交易日的价格动量",
            formula="(close[-1] - close[-61]) / close[-61]",
            parameters={"window": 60},
            data_requirements=["close"],
        ),
        FactorDefinition(
            factor_id="value_premium",
            name="转债价值",
            category=FactorCategory.VALUE,
            factor_type=FactorType.ALPHA,
            description="转债综合价值因子",
            formula="-(conversion_premium + bond_premium * 0.5)",
            parameters={},
            data_requirements=["conversion_premium", "bond_premium"],
        ),
        FactorDefinition(
            factor_id="quality_roe",
            name="质量因子",
            category=FactorCategory.QUALITY,
            factor_type=FactorType.ALPHA,
            description="正股质量综合得分",
            formula="roe * 0.4 + (1 - debt_ratio) * 0.3 + profit_stability * 0.3",
            parameters={},
            data_requirements=["roe", "debt_ratio", "profit_stability"],
        ),
        FactorDefinition(
            factor_id="liquidity_score",
            name="流动性因子",
            category=FactorCategory.LIQUIDITY,
            factor_type=FactorType.ALPHA,
            description="转债流动性综合得分",
            formula="log(amount) * 0.6 + turnover * 100 * 0.4",
            parameters={},
            data_requirements=["amount", "turnover_rate"],
        ),
        FactorDefinition(
            factor_id="volatility_20d",
            name="20日波动率",
            category=FactorCategory.VOLATILITY,
            factor_type=FactorType.RISK,
            description="过去20日年化波动率",
            formula="std(daily_returns) * sqrt(252)",
            parameters={"window": 20},
            data_requirements=["close"],
        ),
    ]

    def __init__(self):
        self._factors: Dict[str, FactorDefinition] = {}
        self._calculators: Dict[str, FactorCalculator] = {}
        self._tester = FactorTester()

        # 加载预定义因子
        for factor_def in self.PREDEFINED_FACTORS:
            self.register_factor(factor_def)

    def register_factor(self, definition: FactorDefinition) -> str:
        """注册因子"""
        self._factors[definition.factor_id] = definition

        # 创建计算器
        if "momentum" in definition.factor_id:
            self._calculators[definition.factor_id] = MomentumFactor(definition)
        elif "value" in definition.factor_id:
            self._calculators[definition.factor_id] = ValueFactor(definition)
        elif "quality" in definition.factor_id:
            self._calculators[definition.factor_id] = QualityFactor(definition)
        elif "liquidity" in definition.factor_id:
            self._calculators[definition.factor_id] = LiquidityFactor(definition)
        elif "volatility" in definition.factor_id:
            self._calculators[definition.factor_id] = VolatilityFactor(definition)

        logger.info(f"[FactorLibrary] 注册因子: {definition.name} ({definition.factor_id})")

        return definition.factor_id

    def get_factor(self, factor_id: str) -> Optional[FactorDefinition]:
        """获取因子"""
        return self._factors.get(factor_id)

    def calculate_factor(
        self,
        factor_id: str,
        data: Dict[str, Any],
        date: date,
    ) -> Optional[FactorResult]:
        """计算因子"""
        calculator = self._calculators.get(factor_id)
        if calculator:
            return calculator.calculate(data, date)
        return None

    def calculate_all_factors(
        self,
        data: Dict[str, Any],
        date: date,
    ) -> Dict[str, FactorResult]:
        """计算所有因子"""
        results = {}
        for factor_id in self._factors:
            result = self.calculate_factor(factor_id, data, date)
            if result:
                results[factor_id] = result
        return results

    def test_factor(
        self,
        factor_id: str,
        factor_values: List[FactorResult],
        forward_returns: List[Dict[str, float]],
    ) -> Optional[FactorPerformance]:
        """检验因子"""
        return self._tester.test_factor(factor_values, forward_returns)

    def get_factors_by_category(self, category: FactorCategory) -> List[FactorDefinition]:
        """按类别获取因子"""
        return [f for f in self._factors.values() if f.category == category]

    def list_factors(self) -> List[FactorDefinition]:
        """列出所有因子"""
        return list(self._factors.values())


# ============ 因子组合 ============

class FactorCombiner:
    """因子组合器"""

    def __init__(self, library: FactorLibrary):
        self.library = library

    def combine_factors(
        self,
        factor_results: Dict[str, FactorResult],
        weights: Dict[str, float] = None,
        method: str = "weighted_sum",
    ) -> Dict[str, float]:
        """组合因子"""
        if not factor_results:
            return {}

        # 获取所有标的
        all_codes = set()
        for result in factor_results.values():
            all_codes.update(result.values.keys())

        # 默认等权
        if weights is None:
            weights = {fid: 1.0 / len(factor_results) for fid in factor_results}

        combined = {}

        if method == "weighted_sum":
            for code in all_codes:
                total = 0
                total_weight = 0
                for factor_id, result in factor_results.items():
                    if code in result.zscores:
                        total += result.zscores[code] * weights.get(factor_id, 0)
                        total_weight += weights.get(factor_id, 0)

                if total_weight > 0:
                    combined[code] = total / total_weight

        elif method == "rank_average":
            for code in all_codes:
                ranks = []
                for result in factor_results.values():
                    if code in result.ranks:
                        ranks.append(result.ranks[code])

                if ranks:
                    combined[code] = np.mean(ranks)

        elif method == "max":
            for code in all_codes:
                values = []
                for result in factor_results.values():
                    if code in result.zscores:
                        values.append(result.zscores[code])

                if values:
                    combined[code] = max(values)

        return combined

    def orthogonalize(
        self,
        factor_values: Dict[str, Dict[str, float]],
        target_factor: str,
    ) -> Dict[str, float]:
        """因子正交化"""
        if target_factor not in factor_values:
            return {}

        target = factor_values[target_factor]
        other_factors = {k: v for k, v in factor_values.items() if k != target_factor}

        if not other_factors:
            return target

        # 获取共同标的
        common_codes = set(target.keys())
        for values in other_factors.values():
            common_codes &= set(values.keys())

        if len(common_codes) < 10:
            return target

        # 构建矩阵
        Y = np.array([target[c] for c in common_codes])
        X = np.array([[other_factors[f].get(c, 0) for f in other_factors] for c in common_codes])

        # 线性回归残差
        try:
            from sklearn.linear_model import LinearRegression
            model = LinearRegression()
            model.fit(X, Y)
            residuals = Y - model.predict(X)

            return {code: res for code, res in zip(common_codes, residuals)}
        except Exception as e:
            logger.debug(f"[FactorLibrary] residual_factor failed: {e}")
            return target


# ============ 便捷函数 ============

def create_factor_library() -> FactorLibrary:
    """创建因子库"""
    return FactorLibrary()


def calculate_factor(factor_id: str, data: Dict, date: date) -> Optional[FactorResult]:
    """计算因子"""
    library = FactorLibrary()
    return library.calculate_factor(factor_id, data, date)


def test_factor_effectiveness(
    factor_values: List[FactorResult],
    forward_returns: List[Dict[str, float]],
) -> FactorPerformance:
    """检验因子有效性"""
    tester = FactorTester()
    return tester.test_factor(factor_values, forward_returns)
