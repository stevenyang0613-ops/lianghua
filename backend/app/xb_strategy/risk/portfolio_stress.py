"""西部量化可转债策略 V3.0 组合压力测试模块

功能:
- 历史情景回放
- 蒙特卡洛模拟
- 极端事件分析
- 风险预算分配
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

class StressScenario(str, Enum):
    """压力情景"""
    MARKET_CRASH = "market_crash"         # 市场崩盘
    RATE_SHOCK = "rate_shock"             # 利率冲击
    CREDIT_CRISIS = "credit_crisis"       # 信用危机
    LIQUIDITY_CRUNCH = "liquidity_crunch" # 流动性枯竭
    VOLATILITY_SPIKE = "vol_spike"        # 波动率飙升
    FLASH_CRASH = "flash_crash"           # 闪崩
    CURRENCY_CRISIS = "currency_crisis"   # 汇率危机
    CUSTOM = "custom"                     # 自定义


class SimulationMethod(str, Enum):
    """模拟方法"""
    HISTORICAL = "historical"       # 历史模拟
    PARAMETRIC = "parametric"       # 参数化
    MONTE_CARLO = "monte_carlo"     # 蒙特卡洛
    COPULA = "copula"               # Copula


class RiskBudgetMethod(str, Enum):
    """风险预算方法"""
    EQUAL = "equal"                 # 等风险
    MCR = "mcr"                     # 边际风险贡献
    RISK_PARITY = "risk_parity"     # 风险平价
    MIN_VARIANCE = "min_variance"   # 最小方差


# ============ 数据模型 ============

@dataclass
class HistoricalScenario:
    """历史情景"""
    scenario_id: str
    name: str
    scenario_type: StressScenario
    start_date: datetime
    end_date: datetime
    description: str
    market_impact: Dict[str, float]  # index -> % change
    key_events: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "type": self.scenario_type.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "description": self.description,
            "market_impact": {k: round(v, 4) for k, v in self.market_impact.items()},
        }


@dataclass
class StressTestResult:
    """压力测试结果"""
    scenario_name: str
    scenario_type: StressScenario
    portfolio_value_before: float
    portfolio_value_after: float
    pnl: float
    pnl_pct: float
    max_drawdown: float
    var_breach: bool
    recovery_days: int
    affected_positions: List[Dict]

    def to_dict(self) -> dict:
        return {
            "scenario_name": self.scenario_name,
            "scenario_type": self.scenario_type.value,
            "portfolio_value_before": round(self.portfolio_value_before, 2),
            "portfolio_value_after": round(self.portfolio_value_after, 2),
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "var_breach": self.var_breach,
            "recovery_days": self.recovery_days,
            "affected_positions": self.affected_positions[:10],
        }


@dataclass
class MonteCarloResult:
    """蒙特卡洛结果"""
    simulation_id: str
    iterations: int
    confidence_level: float
    expected_return: float
    expected_volatility: float
    var: float
    cvar: float
    max_loss: float
    max_gain: float
    percentile_5: float
    percentile_95: float
    distribution: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "simulation_id": self.simulation_id,
            "iterations": self.iterations,
            "expected_return": round(self.expected_return, 6),
            "expected_volatility": round(self.expected_volatility, 6),
            "var": round(self.var, 4),
            "cvar": round(self.cvar, 4),
            "max_loss": round(self.max_loss, 4),
            "max_gain": round(self.max_gain, 4),
        }


@dataclass
class RiskBudget:
    """风险预算"""
    position_id: str
    allocation: float
    risk_contribution: float
    marginal_risk: float
    budget_ratio: float

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "allocation": round(self.allocation, 4),
            "risk_contribution": round(self.risk_contribution, 4),
            "marginal_risk": round(self.marginal_risk, 4),
            "budget_ratio": round(self.budget_ratio, 4),
        }


# ============ 历史情景库 ============

class HistoricalScenarioLibrary:
    """历史情景库"""

    def __init__(self):
        self._scenarios: Dict[str, HistoricalScenario] = {}
        self._initialize_standard_scenarios()

    def _initialize_standard_scenarios(self):
        """初始化标准情景"""
        standard_scenarios = [
            HistoricalScenario(
                scenario_id="2008_financial_crisis",
                name="2008年金融危机",
                scenario_type=StressScenario.MARKET_CRASH,
                start_date=datetime(2008, 9, 1),
                end_date=datetime(2008, 11, 30),
                description="雷曼兄弟破产引发的全球金融危机",
                market_impact={
                    "sp500": -0.38,
                    "hsi": -0.45,
                    "csi300": -0.35,
                    "bond_index": 0.05,
                },
                key_events=["雷曼兄弟破产", "AIG救助", "全球央行降息"],
            ),
            HistoricalScenario(
                scenario_id="2015_china_crash",
                name="2015年A股股灾",
                scenario_type=StressScenario.MARKET_CRASH,
                start_date=datetime(2015, 6, 15),
                end_date=datetime(2015, 8, 26),
                description="A股杠杆去化引发的股灾",
                market_impact={
                    "csi300": -0.43,
                    "chinext": -0.52,
                    "convertible_bond": -0.15,
                },
                key_events=["去杠杆", "熔断机制", "国家队救市"],
            ),
            HistoricalScenario(
                scenario_id="2020_covid",
                name="2020年新冠疫情",
                scenario_type=StressScenario.MARKET_CRASH,
                start_date=datetime(2020, 2, 20),
                end_date=datetime(2020, 3, 23),
                description="新冠疫情全球爆发",
                market_impact={
                    "sp500": -0.34,
                    "csi300": -0.13,
                    "convertible_bond": -0.05,
                },
                key_events=["疫情爆发", "全球封锁", "央行救市"],
            ),
            HistoricalScenario(
                scenario_id="2013_cash_crunch",
                name="2013年钱荒",
                scenario_type=StressScenario.LIQUIDITY_CRUNCH,
                start_date=datetime(2013, 6, 1),
                end_date=datetime(2013, 6, 30),
                description="银行间市场流动性枯竭",
                market_impact={
                    "bond_index": -0.04,
                    "repo_rate": 2.0,
                    "csi300": -0.15,
                },
                key_events=["银行间利率飙升", "央行不救助", "货币基金赎回潮"],
            ),
            HistoricalScenario(
                scenario_id="vol_spike_2018",
                name="2018年波动率飙升",
                scenario_type=StressScenario.VOLATILITY_SPIKE,
                start_date=datetime(2018, 2, 5),
                end_date=datetime(2018, 2, 9),
                description="VIX指数飙升引发的全球股市调整",
                market_impact={
                    "sp500": -0.10,
                    "vix": 4.0,
                    "csi300": -0.10,
                },
                key_events=["VIX期货爆仓", "量化策略回撤", "风险平价策略调整"],
            ),
        ]

        for scenario in standard_scenarios:
            self._scenarios[scenario.scenario_id] = scenario

    def add_scenario(self, scenario: HistoricalScenario):
        """添加情景"""
        self._scenarios[scenario.scenario_id] = scenario

    def get_scenario(self, scenario_id: str) -> Optional[HistoricalScenario]:
        """获取情景"""
        return self._scenarios.get(scenario_id)

    def get_scenarios_by_type(self, scenario_type: StressScenario) -> List[HistoricalScenario]:
        """按类型获取情景"""
        return [s for s in self._scenarios.values() if s.scenario_type == scenario_type]

    def get_all_scenarios(self) -> List[HistoricalScenario]:
        """获取所有情景"""
        return list(self._scenarios.values())


# ============ 历史情景回放器 ============

class HistoricalScenarioReplay:
    """历史情景回放器"""

    def __init__(self):
        self.scenario_library = HistoricalScenarioLibrary()

    def replay(
        self,
        scenario_id: str,
        positions: Dict[str, Dict],
        correlations: Dict[str, float] = None,
    ) -> StressTestResult:
        """回放情景"""
        scenario = self.scenario_library.get_scenario(scenario_id)
        if not scenario:
            return None

        # 计算组合初始价值
        initial_value = sum(p.get("market_value", 0) for p in positions.values())

        # 应用冲击
        total_pnl = 0
        affected = []

        for code, position in positions.items():
            # 获取标的类型
            asset_type = position.get("type", "stock")

            # 获取冲击系数
            impact_key = self._get_impact_key(code, asset_type)
            base_impact = scenario.market_impact.get(impact_key, -0.1)

            # 考虑相关性调整
            if correlations and code in correlations:
                impact = base_impact * correlations[code]
            else:
                impact = base_impact

            # 计算PnL
            position_value = position.get("market_value", 0)
            position_pnl = position_value * impact

            total_pnl += position_pnl

            if abs(impact) > 0.05:
                affected.append({
                    "code": code,
                    "impact": impact,
                    "pnl": position_pnl,
                })

        # 计算结果
        final_value = initial_value + total_pnl
        pnl_pct = total_pnl / initial_value if initial_value > 0 else 0

        # 估算最大回撤
        max_drawdown = abs(min(0, pnl_pct * 1.5))

        # 判断VaR突破
        var_limit = -0.02  # 假设2% VaR
        var_breach = pnl_pct < var_limit

        # 估算恢复天数
        recovery_days = int(abs(pnl_pct) * 20) if pnl_pct < 0 else 0

        return StressTestResult(
            scenario_name=scenario.name,
            scenario_type=scenario.scenario_type,
            portfolio_value_before=initial_value,
            portfolio_value_after=final_value,
            pnl=total_pnl,
            pnl_pct=pnl_pct,
            max_drawdown=max_drawdown,
            var_breach=var_breach,
            recovery_days=recovery_days,
            affected_positions=affected,
        )

    def _get_impact_key(self, code: str, asset_type: str) -> str:
        """获取冲击键"""
        if asset_type == "convertible_bond":
            return "convertible_bond"
        elif asset_type == "bond":
            return "bond_index"
        elif code.startswith("6"):
            return "csi300"
        else:
            return "csi300"

    def replay_all(
        self,
        positions: Dict[str, Dict],
        scenario_type: StressScenario = None,
    ) -> List[StressTestResult]:
        """回放所有情景"""
        if scenario_type:
            scenarios = self.scenario_library.get_scenarios_by_type(scenario_type)
        else:
            scenarios = self.scenario_library.get_all_scenarios()

        results = []
        for scenario in scenarios:
            result = self.replay(scenario.scenario_id, positions)
            if result:
                results.append(result)

        return results


# ============ 蒙特卡洛模拟器 ============

class MonteCarloSimulator:
    """蒙特卡洛模拟器"""

    def __init__(self):
        self._default_params = {
            "iterations": 10000,
            "time_horizon": 252,  # 天
            "confidence_level": 0.95,
        }

    def simulate(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        weights: np.ndarray,
        iterations: int = 10000,
        time_horizon: int = 252,
    ) -> MonteCarloResult:
        """执行模拟"""
        # Cholesky分解
        L = np.linalg.cholesky(cov_matrix)

        # 生成随机样本
        n_assets = len(expected_returns)
        simulated_returns = np.zeros(iterations)

        for i in range(iterations):
            # 生成相关随机变量
            z = np.random.standard_normal(n_assets)
            correlated_returns = expected_returns + L @ z

            # 组合收益
            portfolio_return = np.dot(weights, correlated_returns) * time_horizon / 252
            simulated_returns[i] = portfolio_return

        # 统计结果
        expected_return = np.mean(simulated_returns)
        expected_volatility = np.std(simulated_returns)

        # VaR和CVaR
        sorted_returns = np.sort(simulated_returns)
        var_index = int(iterations * 0.05)
        var = -sorted_returns[var_index]
        cvar = -np.mean(sorted_returns[:var_index])

        # 极值
        max_loss = sorted_returns[0]
        max_gain = sorted_returns[-1]

        # 分位数
        percentile_5 = sorted_returns[int(iterations * 0.05)]
        percentile_95 = sorted_returns[int(iterations * 0.95)]

        return MonteCarloResult(
            simulation_id=f"mc_{int(datetime.now().timestamp() * 1000)}",
            iterations=iterations,
            confidence_level=0.95,
            expected_return=expected_return,
            expected_volatility=expected_volatility,
            var=var,
            cvar=cvar,
            max_loss=max_loss,
            max_gain=max_gain,
            percentile_5=percentile_5,
            percentile_95=percentile_95,
            distribution=simulated_returns[:1000].tolist(),
        )

    def simulate_with_fat_tails(
        self,
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        weights: np.ndarray,
        degrees_of_freedom: int = 5,
        iterations: int = 10000,
    ) -> MonteCarloResult:
        """带肥尾的模拟"""
        from scipy.stats import t as student_t

        L = np.linalg.cholesky(cov_matrix)
        n_assets = len(expected_returns)
        simulated_returns = np.zeros(iterations)

        for i in range(iterations):
            # 使用t分布生成肥尾
            z = student_t.rvs(df=degrees_of_freedom, size=n_assets)
            z = (z - student_t.mean(df=degrees_of_freedom)) / student_t.std(df=degrees_of_freedom)

            correlated_returns = expected_returns + L @ z
            portfolio_return = np.dot(weights, correlated_returns)
            simulated_returns[i] = portfolio_return

        sorted_returns = np.sort(simulated_returns)
        var_index = int(iterations * 0.05)

        return MonteCarloResult(
            simulation_id=f"mc_fat_tail_{int(datetime.now().timestamp() * 1000)}",
            iterations=iterations,
            confidence_level=0.95,
            expected_return=np.mean(simulated_returns),
            expected_volatility=np.std(simulated_returns),
            var=-sorted_returns[var_index],
            cvar=-np.mean(sorted_returns[:var_index]),
            max_loss=sorted_returns[0],
            max_gain=sorted_returns[-1],
            percentile_5=sorted_returns[int(iterations * 0.05)],
            percentile_95=sorted_returns[int(iterations * 0.95)],
        )


# ============ 极端事件分析器 ============

class ExtremeEventAnalyzer:
    """极端事件分析器"""

    def __init__(self):
        self._events: List[Dict] = []

    def identify_extreme_events(
        self,
        returns: List[float],
        threshold_sigma: float = 3.0,
    ) -> List[Dict]:
        """识别极端事件"""
        mean = np.mean(returns)
        std = np.std(returns)

        threshold_high = mean + threshold_sigma * std
        threshold_low = mean - threshold_sigma * std

        events = []

        for i, r in enumerate(returns):
            if r > threshold_high:
                events.append({
                    "index": i,
                    "return": r,
                    "type": "extreme_positive",
                    "deviation": (r - mean) / std,
                })
            elif r < threshold_low:
                events.append({
                    "index": i,
                    "return": r,
                    "type": "extreme_negative",
                    "deviation": abs(r - mean) / std,
                })

        return events

    def analyze_tail_behavior(
        self,
        returns: List[float],
    ) -> Dict:
        """分析尾部行为"""
        returns = np.array(returns)
        sorted_returns = np.sort(returns)
        n = len(sorted_returns)

        # 尾部统计
        left_tail = sorted_returns[:int(n * 0.05)]
        right_tail = sorted_returns[int(n * 0.95):]

        # 偏度和峰度
        from scipy.stats import skew, kurtosis

        return {
            "skewness": skew(returns),
            "kurtosis": kurtosis(returns),
            "left_tail_mean": np.mean(left_tail),
            "left_tail_std": np.std(left_tail),
            "right_tail_mean": np.mean(right_tail),
            "right_tail_std": np.std(right_tail),
            "tail_ratio": abs(np.mean(left_tail)) / abs(np.mean(right_tail)) if np.mean(right_tail) != 0 else 0,
        }

    def estimate_extreme_var(
        self,
        returns: List[float],
        confidence_level: float = 0.99,
    ) -> float:
        """估算极端VaR (使用极值理论)"""
        # 使用POT(Peaks Over Threshold)方法
        threshold = np.percentile(returns, 95)
        excesses = [r - threshold for r in returns if r < threshold]

        if not excesses:
            return 0

        # GPD参数估计 (简化)
        excess_mean = np.mean(excesses)
        n_excess = len(excesses)
        n_total = len(returns)

        # VaR估计
        p = 1 - confidence_level
        var = threshold - excess_mean * (n_total * p / n_excess) ** (-excess_mean / np.std(excesses))

        return -var


# ============ 风险预算分配器 ============

class RiskBudgetAllocator:
    """风险预算分配器"""

    def __init__(self):
        self._method = RiskBudgetMethod.RISK_PARITY

    def allocate(
        self,
        positions: Dict[str, Dict],
        cov_matrix: np.ndarray,
        method: RiskBudgetMethod = None,
        total_risk_budget: float = 0.02,  # 2%总风险预算
    ) -> List[RiskBudget]:
        """分配风险预算"""
        method = method or self._method
        n = len(positions)

        if n == 0:
            return []

        # 计算各方法下的权重
        if method == RiskBudgetMethod.EQUAL:
            weights = np.ones(n) / n
        elif method == RiskBudgetMethod.RISK_PARITY:
            weights = self._risk_parity_weights(cov_matrix)
        elif method == RiskBudgetMethod.MIN_VARIANCE:
            weights = self._min_variance_weights(cov_matrix)
        else:
            weights = np.ones(n) / n

        # 计算风险贡献
        port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        marginal_risk = np.dot(cov_matrix, weights) / port_vol if port_vol > 0 else np.zeros(n)
        risk_contrib = weights * marginal_risk

        # 分配预算
        budgets = []
        codes = list(positions.keys())

        for i, code in enumerate(codes):
            budget_ratio = risk_contrib[i] / sum(risk_contrib) if sum(risk_contrib) > 0 else 1 / n
            allocation = total_risk_budget * budget_ratio

            budgets.append(RiskBudget(
                position_id=code,
                allocation=allocation,
                risk_contribution=risk_contrib[i],
                marginal_risk=marginal_risk[i],
                budget_ratio=budget_ratio,
            ))

        return budgets

    def _risk_parity_weights(self, cov_matrix: np.ndarray) -> np.ndarray:
        """风险平价权重"""
        n = len(cov_matrix)
        weights = np.ones(n) / n

        for _ in range(100):
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            marginal_risk = np.dot(cov_matrix, weights) / port_vol if port_vol > 0 else np.ones(n)

            target_contrib = port_vol / n
            adjustment = target_contrib / (weights * marginal_risk + 1e-10)

            weights = weights * np.sqrt(adjustment)
            weights = weights / weights.sum()

        return weights

    def _min_variance_weights(self, cov_matrix: np.ndarray) -> np.ndarray:
        """最小方差权重"""
        try:
            inv_cov = np.linalg.inv(cov_matrix)
            ones = np.ones(len(cov_matrix))
            weights = inv_cov @ ones
            weights = weights / weights.sum()
            return weights
        except Exception as e:
            logger.debug(f"[PortfolioStress] min_variance_weights failed: {e}")
            return np.ones(len(cov_matrix)) / len(cov_matrix)


# ============ 组合压力测试服务 ============

class PortfolioStressTestService:
    """组合压力测试服务"""

    def __init__(self):
        self.scenario_replay = HistoricalScenarioReplay()
        self.monte_carlo = MonteCarloSimulator()
        self.extreme_analyzer = ExtremeEventAnalyzer()
        self.risk_allocator = RiskBudgetAllocator()

    def run_stress_test(
        self,
        positions: Dict[str, Dict],
        scenarios: List[str] = None,
    ) -> Dict:
        """运行压力测试"""
        results = {
            "historical_scenarios": [],
            "monte_carlo": None,
            "summary": {},
        }

        # 历史情景回放
        if scenarios:
            for scenario_id in scenarios:
                result = self.scenario_replay.replay(scenario_id, positions)
                if result:
                    results["historical_scenarios"].append(result.to_dict())
        else:
            all_results = self.scenario_replay.replay_all(positions)
            results["historical_scenarios"] = [r.to_dict() for r in all_results]

        # 汇总统计
        if results["historical_scenarios"]:
            pnls = [r["pnl_pct"] for r in results["historical_scenarios"]]
            results["summary"] = {
                "worst_case": min(pnls),
                "average_impact": np.mean(pnls),
                "var_breach_count": sum(1 for r in results["historical_scenarios"] if r["var_breach"]),
                "scenario_count": len(results["historical_scenarios"]),
            }

        return results

    def run_monte_carlo(
        self,
        positions: Dict[str, Dict],
        expected_returns: Dict[str, float],
        cov_matrix: np.ndarray,
        iterations: int = 10000,
    ) -> MonteCarloResult:
        """运行蒙特卡洛"""
        codes = list(positions.keys())
        weights = np.array([
            positions[c].get("weight", 0)
            for c in codes
        ])
        returns = np.array([expected_returns.get(c, 0) for c in codes])

        return self.monte_carlo.simulate(returns, cov_matrix, weights, iterations)

    def allocate_risk_budget(
        self,
        positions: Dict[str, Dict],
        cov_matrix: np.ndarray,
        method: RiskBudgetMethod = RiskBudgetMethod.RISK_PARITY,
    ) -> List[RiskBudget]:
        """分配风险预算"""
        return self.risk_allocator.allocate(positions, cov_matrix, method)


# ============ 便捷函数 ============

def create_stress_test_service() -> PortfolioStressTestService:
    """创建压力测试服务"""
    return PortfolioStressTestService()


def run_historical_scenario(
    scenario_id: str,
    positions: Dict[str, Dict],
) -> StressTestResult:
    """运行历史情景"""
    replay = HistoricalScenarioReplay()
    return replay.replay(scenario_id, positions)


def run_monte_carlo_simulation(
    expected_returns: List[float],
    cov_matrix: np.ndarray,
    weights: List[float],
) -> MonteCarloResult:
    """运行蒙特卡洛模拟"""
    simulator = MonteCarloSimulator()
    return simulator.simulate(
        np.array(expected_returns),
        cov_matrix,
        np.array(weights),
    )
