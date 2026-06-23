"""西部量化可转债策略 V3.0 风控模块

功能:
- VaR计算 (历史模拟法、参数法、蒙特卡洛)
- 压力测试
- 最大回撤监控
- 实时风控
- 仓位限制检查
- 风险预警
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum
import numpy as np
import pandas as pd
import logging
from scipy import stats

from app.xb_strategy.core.types import Portfolio, Position
from app.xb_strategy.config.settings import params

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"           # 低风险
    MEDIUM = "medium"     # 中风险
    HIGH = "high"         # 高风险
    CRITICAL = "critical" # 极高风险


class AlertType(str, Enum):
    """预警类型"""
    DRAWDOWN = "drawdown"       # 回撤预警
    CONCENTRATION = "concentration"  # 集中度预警
    LIQUIDITY = "liquidity"     # 流动性预警
    VOLATILITY = "volatility"   # 波动率预警
    VAR = "var"                 # VaR预警
    LOSS = "loss"               # 亏损预警


# ============ 数据类型 ============

@dataclass
class VaRResult:
    """VaR计算结果"""
    var_95: float          # 95%置信度VaR
    var_99: float          # 99%置信度VaR
    cvar_95: float         # 95% CVaR (条件VaR)
    cvar_99: float         # 99% CVaR
    method: str            # 计算方法
    horizon: int           # 时间跨度(天)
    portfolio_value: float # 组合价值

    def to_dict(self) -> dict:
        return {
            "var_95": round(self.var_95, 4),
            "var_99": round(self.var_99, 4),
            "cvar_95": round(self.cvar_95, 4),
            "cvar_99": round(self.cvar_99, 4),
            "method": self.method,
            "horizon": self.horizon,
            "portfolio_value": round(self.portfolio_value, 2),
        }


@dataclass
class StressTestResult:
    """压力测试结果"""
    scenario: str          # 场景名称
    shock: float           # 冲击幅度
    loss: float            # 预计损失
    loss_pct: float        # 损失比例
    impact_by_position: Dict[str, float]  # 各持仓影响

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "shock": self.shock,
            "loss": round(self.loss, 2),
            "loss_pct": round(self.loss_pct * 100, 2),
            "impact_by_position": self.impact_by_position,
        }


@dataclass
class RiskAlert:
    """风险预警"""
    alert_type: AlertType
    level: RiskLevel
    message: str
    value: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "alert_type": self.alert_type.value,
            "level": self.level.value,
            "message": self.message,
            "value": round(self.value, 4),
            "threshold": round(self.threshold, 4),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RiskReport:
    """风险报告"""
    date: date
    var: Optional[VaRResult] = None
    stress_tests: List[StressTestResult] = field(default_factory=list)
    alerts: List[RiskAlert] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    drawdown: float = 0.0
    concentration: float = 0.0
    liquidity_score: float = 1.0

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "var": self.var.to_dict() if self.var else None,
            "stress_tests": [s.to_dict() for s in self.stress_tests],
            "alerts": [a.to_dict() for a in self.alerts],
            "risk_level": self.risk_level.value,
            "drawdown": round(self.drawdown, 4),
            "concentration": round(self.concentration, 4),
            "liquidity_score": round(self.liquidity_score, 4),
        }


# ============ VaR计算引擎 ============

class VaRCalculator:
    """VaR计算引擎"""

    def __init__(self, confidence_levels: List[float] = None):
        """初始化

        Args:
            confidence_levels: 置信水平列表
        """
        self.confidence_levels = confidence_levels or [0.95, 0.99]

    def historical_var(
        self,
        returns: np.ndarray,
        portfolio_value: float,
        horizon: int = 1,
    ) -> VaRResult:
        """历史模拟法计算VaR

        Args:
            returns: 历史收益率序列
            portfolio_value: 组合价值
            horizon: 时间跨度(天)

        Returns:
            VaR计算结果
        """
        if len(returns) < 10:
            return VaRResult(0, 0, 0, 0, "historical", horizon, portfolio_value)

        # 计算各置信水平的VaR
        var_95 = np.percentile(returns, 5) * portfolio_value * np.sqrt(horizon)
        var_99 = np.percentile(returns, 1) * portfolio_value * np.sqrt(horizon)

        # 计算CVaR (预期损失)
        cvar_95 = returns[returns <= np.percentile(returns, 5)].mean() * portfolio_value * np.sqrt(horizon)
        cvar_99 = returns[returns <= np.percentile(returns, 1)].mean() * portfolio_value * np.sqrt(horizon)

        return VaRResult(
            var_95=abs(var_95),
            var_99=abs(var_99),
            cvar_95=abs(cvar_95),
            cvar_99=abs(cvar_99),
            method="historical",
            horizon=horizon,
            portfolio_value=portfolio_value,
        )

    def parametric_var(
        self,
        returns: np.ndarray,
        portfolio_value: float,
        horizon: int = 1,
    ) -> VaRResult:
        """参数法计算VaR (假设正态分布)

        Args:
            returns: 历史收益率序列
            portfolio_value: 组合价值
            horizon: 时间跨度(天)

        Returns:
            VaR计算结果
        """
        if len(returns) < 10:
            return VaRResult(0, 0, 0, 0, "parametric", horizon, portfolio_value)

        mean = np.mean(returns)
        std = np.std(returns)

        # 正态分布分位数
        z_95 = stats.norm.ppf(0.05)  # -1.645
        z_99 = stats.norm.ppf(0.01)  # -2.326

        var_95 = abs((mean + z_95 * std) * portfolio_value * np.sqrt(horizon))
        var_99 = abs((mean + z_99 * std) * portfolio_value * np.sqrt(horizon))

        # CVaR计算
        cvar_95 = abs((mean - std * stats.norm.pdf(z_95) / 0.05) * portfolio_value * np.sqrt(horizon))
        cvar_99 = abs((mean - std * stats.norm.pdf(z_99) / 0.01) * portfolio_value * np.sqrt(horizon))

        return VaRResult(
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            cvar_99=cvar_99,
            method="parametric",
            horizon=horizon,
            portfolio_value=portfolio_value,
        )

    def monte_carlo_var(
        self,
        returns: np.ndarray,
        portfolio_value: float,
        horizon: int = 1,
        simulations: int = 10000,
    ) -> VaRResult:
        """蒙特卡洛模拟计算VaR

        Args:
            returns: 历史收益率序列
            portfolio_value: 组合价值
            horizon: 时间跨度(天)
            simulations: 模拟次数

        Returns:
            VaR计算结果
        """
        if len(returns) < 10:
            return VaRResult(0, 0, 0, 0, "monte_carlo", horizon, portfolio_value)

        mean = np.mean(returns)
        std = np.std(returns)

        # 蒙特卡洛模拟
        np.random.seed(42)
        simulated_returns = np.random.normal(mean, std, simulations)

        var_95 = np.percentile(simulated_returns, 5) * portfolio_value * np.sqrt(horizon)
        var_99 = np.percentile(simulated_returns, 1) * portfolio_value * np.sqrt(horizon)

        cvar_95 = simulated_returns[simulated_returns <= np.percentile(simulated_returns, 5)].mean() * portfolio_value * np.sqrt(horizon)
        cvar_99 = simulated_returns[simulated_returns <= np.percentile(simulated_returns, 1)].mean() * portfolio_value * np.sqrt(horizon)

        return VaRResult(
            var_95=abs(var_95),
            var_99=abs(var_99),
            cvar_95=abs(cvar_95),
            cvar_99=abs(cvar_99),
            method="monte_carlo",
            horizon=horizon,
            portfolio_value=portfolio_value,
        )


# ============ 压力测试引擎 ============

class StressTestEngine:
    """压力测试引擎"""

    def __init__(self):
        """初始化压力测试场景"""
        self.scenarios = {
            "市场大幅下跌": {"stock_shock": -0.20, "bond_shock": -0.05},
            "流动性危机": {"stock_shock": -0.15, "bond_shock": -0.10},
            "信用风险爆发": {"stock_shock": -0.10, "bond_shock": -0.15},
            "利率上行": {"stock_shock": -0.05, "bond_shock": -0.08},
            "极端市场": {"stock_shock": -0.30, "bond_shock": -0.15},
        }

    def run_stress_test(
        self,
        portfolio: Portfolio,
        position_details: Dict[str, Dict],
    ) -> List[StressTestResult]:
        """运行压力测试

        Args:
            portfolio: 组合信息
            position_details: 持仓详情 {code: {"type": "stock/bond", "value": ...}}

        Returns:
            压力测试结果列表
        """
        results = []

        for scenario_name, shocks in self.scenarios.items():
            total_loss = 0.0
            impact_by_position = {}

            for code, details in position_details.items():
                value = details.get("value", 0)
                pos_type = details.get("type", "bond")

                shock = shocks.get("bond_shock", 0) if pos_type == "bond" else shocks.get("stock_shock", 0)
                loss = value * shock
                total_loss += loss
                impact_by_position[code] = loss

            portfolio_value = portfolio.aum * 10000  # 万元转元
            loss_pct = total_loss / portfolio_value if portfolio_value > 0 else 0

            results.append(StressTestResult(
                scenario=scenario_name,
                shock=shocks.get("bond_shock", 0) * 100,  # 转为百分比
                loss=abs(total_loss),
                loss_pct=abs(loss_pct),
                impact_by_position=impact_by_position,
            ))

        return results

    def add_custom_scenario(self, name: str, stock_shock: float, bond_shock: float):
        """添加自定义压力测试场景

        Args:
            name: 场景名称
            stock_shock: 正股冲击幅度
            bond_shock: 转债冲击幅度
        """
        self.scenarios[name] = {"stock_shock": stock_shock, "bond_shock": bond_shock}


# ============ 实时风控引擎 ============

class RealTimeRiskMonitor:
    """实时风控监控"""

    def __init__(
        self,
        max_drawdown: float = 0.10,
        max_single_position: float = 0.05,
        max_sector_position: float = 0.20,
        min_liquidity_score: float = 0.5,
    ):
        """初始化

        Args:
            max_drawdown: 最大回撤限制
            max_single_position: 单一持仓上限
            max_sector_position: 单一行业持仓上限
            min_liquidity_score: 最低流动性得分
        """
        self.max_drawdown = max_drawdown
        self.max_single_position = max_single_position
        self.max_sector_position = max_sector_position
        self.min_liquidity_score = min_liquidity_score

        self._alerts: List[RiskAlert] = []
        self._peak_value = 0.0
        self._current_drawdown = 0.0

    def check_portfolio(
        self,
        portfolio: Portfolio,
        positions: Dict[str, Position],
        liquidity_scores: Optional[Dict[str, float]] = None,
    ) -> List[RiskAlert]:
        """检查组合风险

        Args:
            portfolio: 组合信息
            positions: 持仓信息
            liquidity_scores: 流动性得分

        Returns:
            风险预警列表
        """
        self._alerts = []

        # 1. 检查回撤
        self._check_drawdown(portfolio)

        # 2. 检查集中度
        self._check_concentration(portfolio, positions)

        # 3. 检查流动性
        if liquidity_scores:
            self._check_liquidity(liquidity_scores)

        return self._alerts

    def _check_drawdown(self, portfolio: Portfolio):
        """检查回撤"""
        current_value = portfolio.aum * 10000  # 万元转元

        # 更新峰值
        if current_value > self._peak_value:
            self._peak_value = current_value

        # 计算回撤
        if self._peak_value > 0:
            self._current_drawdown = (self._peak_value - current_value) / self._peak_value

        # 预警
        if self._current_drawdown >= self.max_drawdown:
            self._alerts.append(RiskAlert(
                alert_type=AlertType.DRAWDOWN,
                level=RiskLevel.CRITICAL,
                message=f"回撤{self._current_drawdown*100:.2f}%超过限制{self.max_drawdown*100:.2f}%",
                value=self._current_drawdown,
                threshold=self.max_drawdown,
            ))
        elif self._current_drawdown >= self.max_drawdown * 0.8:
            self._alerts.append(RiskAlert(
                alert_type=AlertType.DRAWDOWN,
                level=RiskLevel.HIGH,
                message=f"回撤{self._current_drawdown*100:.2f}%接近限制",
                value=self._current_drawdown,
                threshold=self.max_drawdown,
            ))

    def _check_concentration(self, portfolio: Portfolio, positions: Dict[str, Position]):
        """检查集中度"""
        total_value = portfolio.total_market_value * 10000

        if total_value <= 0:
            return

        # 单一持仓检查
        for code, pos in positions.items():
            weight = pos.market_value / total_value
            if weight > self.max_single_position:
                self._alerts.append(RiskAlert(
                    alert_type=AlertType.CONCENTRATION,
                    level=RiskLevel.HIGH,
                    message=f"{pos.cb_name}仓位{weight*100:.2f}%超过限制{self.max_single_position*100:.2f}%",
                    value=weight,
                    threshold=self.max_single_position,
                ))

    def _check_liquidity(self, liquidity_scores: Dict[str, float]):
        """检查流动性"""
        for code, score in liquidity_scores.items():
            if score < self.min_liquidity_score:
                self._alerts.append(RiskAlert(
                    alert_type=AlertType.LIQUIDITY,
                    level=RiskLevel.MEDIUM,
                    message=f"{code}流动性得分{score:.2f}低于限制",
                    value=score,
                    threshold=self.min_liquidity_score,
                ))

    def get_current_drawdown(self) -> float:
        """获取当前回撤"""
        return self._current_drawdown


# ============ 综合风险管理器 ============

class RiskManager:
    """综合风险管理器"""

    def __init__(
        self,
        aum: float = 10000.0,
        max_drawdown: float = 0.10,
    ):
        """初始化

        Args:
            aum: 资产规模(万元)
            max_drawdown: 最大回撤限制
        """
        self.aum = aum
        self.var_calculator = VaRCalculator()
        self.stress_engine = StressTestEngine()
        self.realtime_monitor = RealTimeRiskMonitor(max_drawdown=max_drawdown)

        self._returns_history: List[float] = []
        self._equity_curve: List[float] = []

    def update_returns(self, daily_return: float):
        """更新收益率历史"""
        self._returns_history.append(daily_return)
        # 保留最近252个交易日
        if len(self._returns_history) > 252:
            self._returns_history = self._returns_history[-252:]

    def update_equity(self, equity: float):
        """更新净值曲线"""
        self._equity_curve.append(equity)

    def calculate_var(self, method: str = "historical", horizon: int = 1) -> Optional[VaRResult]:
        """计算VaR

        Args:
            method: 计算方法 (historical/parametric/monte_carlo)
            horizon: 时间跨度

        Returns:
            VaR结果
        """
        if len(self._returns_history) < 10:
            return None

        returns = np.array(self._returns_history)
        portfolio_value = self.aum * 10000

        if method == "parametric":
            return self.var_calculator.parametric_var(returns, portfolio_value, horizon)
        elif method == "monte_carlo":
            return self.var_calculator.monte_carlo_var(returns, portfolio_value, horizon)
        else:
            return self.var_calculator.historical_var(returns, portfolio_value, horizon)

    def run_stress_test(
        self,
        portfolio: Portfolio,
        position_details: Dict[str, Dict],
    ) -> List[StressTestResult]:
        """运行压力测试"""
        return self.stress_engine.run_stress_test(portfolio, position_details)

    def check_risks(
        self,
        portfolio: Portfolio,
        positions: Dict[str, Position],
        liquidity_scores: Optional[Dict[str, float]] = None,
    ) -> List[RiskAlert]:
        """风险检查"""
        return self.realtime_monitor.check_portfolio(portfolio, positions, liquidity_scores)

    def generate_report(
        self,
        portfolio: Portfolio,
        positions: Dict[str, Position],
        position_details: Optional[Dict[str, Dict]] = None,
        liquidity_scores: Optional[Dict[str, float]] = None,
    ) -> RiskReport:
        """生成风险报告

        Args:
            portfolio: 组合信息
            positions: 持仓信息
            position_details: 持仓详情
            liquidity_scores: 流动性得分

        Returns:
            风险报告
        """
        # 计算VaR
        var_result = self.calculate_var()

        # 压力测试
        stress_results = []
        if position_details:
            stress_results = self.run_stress_test(portfolio, position_details)

        # 风险检查
        alerts = self.check_risks(portfolio, positions, liquidity_scores)

        # 计算集中度
        total_value = portfolio.total_market_value * 10000
        concentration = 0.0
        if total_value > 0 and positions:
            max_weight = max(pos.market_value / total_value for pos in positions.values())
            concentration = max_weight

        # 计算平均流动性
        liquidity_score = 1.0
        if liquidity_scores:
            liquidity_score = np.mean(list(liquidity_scores.values()))

        # 确定风险等级
        risk_level = RiskLevel.LOW
        if alerts:
            levels = [a.level for a in alerts]
            if RiskLevel.CRITICAL in levels:
                risk_level = RiskLevel.CRITICAL
            elif RiskLevel.HIGH in levels:
                risk_level = RiskLevel.HIGH
            elif RiskLevel.MEDIUM in levels:
                risk_level = RiskLevel.MEDIUM

        return RiskReport(
            date=date.today(),
            var=var_result,
            stress_tests=stress_results,
            alerts=alerts,
            risk_level=risk_level,
            drawdown=self.realtime_monitor.get_current_drawdown(),
            concentration=concentration,
            liquidity_score=liquidity_score,
        )

    def get_max_position_size(
        self,
        code: str,
        current_positions: Dict[str, Position],
        aum: float,
        current_price: float = 0.0,
    ) -> int:
        """计算最大可开仓数量

        Args:
            code: 转债代码
            current_positions: 当前持仓
            aum: 资产规模(万元)

        Returns:
            最大可开仓数量(张)
        """
        # 单一持仓限制
        max_single_value = aum * 10000 * self.realtime_monitor.max_single_position

        # 当前已有持仓
        current_value = 0
        if code in current_positions:
            current_value = current_positions[code].market_value

        # 可增加仓位
        available_value = max_single_value - current_value

        # 可增加仓位（实际应从行情获取；价格无效时不应默认100，直接返回0）
        estimated_price = current_price if current_price and current_price > 0 else 0.0
        if estimated_price <= 0:
            return 0
        max_qty = int(available_value / estimated_price / 100) * 100

        return max(0, max_qty)

    def should_reduce_position(self, alerts: List[RiskAlert]) -> bool:
        """判断是否需要减仓

        Args:
            alerts: 风险预警列表

        Returns:
            是否需要减仓
        """
        critical_alerts = [a for a in alerts if a.level == RiskLevel.CRITICAL]
        return len(critical_alerts) > 0
