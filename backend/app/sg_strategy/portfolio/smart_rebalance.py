"""松岗量化可转债策略 V3.0 智能调仓优化模块

功能:
- 交易成本优化
- 税务优化
- 执行算法集成
- 再平衡策略
- 约束处理
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple, Callable
from enum import Enum
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class RebalanceTrigger(str, Enum):
    """调仓触发条件"""
    PERIODIC = "periodic"         # 定期
    THRESHOLD = "threshold"       # 阈值触发
    SIGNAL = "signal"             # 信号触发
    RISK = "risk"                 # 风险触发
    MANUAL = "manual"             # 手动


class RebalanceStrategy(str, Enum):
    """调仓策略"""
    FULL = "full"                 # 完全调仓
    PARTIAL = "partial"           # 部分调仓
    GRADUAL = "gradual"           # 渐进调仓
    SMART = "smart"               # 智能调仓


class ExecutionAlgorithm(str, Enum):
    """执行算法"""
    MARKET = "market"             # 市价单
    LIMIT = "limit"               # 限价单
    TWAP = "twap"                 # 时间加权平均价格
    VWAP = "vwap"                 # 成交量加权平均价格
    POV = "pov"                   # 参与率算法
    IS = "implementation_shortfall"  # 执行 shortfall


class TaxLotMethod(str, Enum):
    """税务处理方法"""
    FIFO = "fifo"                 # 先进先出
    LIFO = "lifo"                 # 后进先出
    HIFO = "hifo"                 # 最高成本先出
    LOFO = "lofo"                 # 最低成本先出
    SPECIFIC = "specific"         # 指定


# ============ 数据模型 ============

@dataclass
class TaxLot:
    """税务批次"""
    lot_id: str
    code: str
    quantity: int
    cost_price: float
    purchase_date: datetime
    holding_days: int = 0

    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏（需要当前价格）"""
        return 0

    def calculate_tax(self, current_price: float, tax_rate: float = 0.1) -> float:
        """计算税费"""
        pnl = (current_price - self.cost_price) * self.quantity
        if pnl > 0:
            return pnl * tax_rate
        return 0


@dataclass
class TradeProposal:
    """交易提案"""
    code: str
    side: str
    quantity: int
    current_weight: float
    target_weight: float
    estimated_price: float
    estimated_cost: float
    estimated_tax: float
    priority: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "side": self.side,
            "quantity": self.quantity,
            "current_weight": round(self.current_weight, 4),
            "target_weight": round(self.target_weight, 4),
            "estimated_price": round(self.estimated_price, 4),
            "estimated_cost": round(self.estimated_cost, 2),
            "estimated_tax": round(self.estimated_tax, 2),
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass
class RebalancePlan:
    """调仓计划"""
    plan_id: str
    trigger: RebalanceTrigger
    strategy: RebalanceStrategy
    trades: List[TradeProposal] = field(default_factory=list)
    total_cost: float = 0
    total_tax: float = 0
    expected_improvement: float = 0
    created_at: datetime = None
    executed: bool = False

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def calculate_totals(self):
        """计算总计"""
        self.total_cost = sum(t.estimated_cost for t in self.trades)
        self.total_tax = sum(t.estimated_tax for t in self.trades)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "trigger": self.trigger.value,
            "strategy": self.strategy.value,
            "trade_count": len(self.trades),
            "total_cost": round(self.total_cost, 2),
            "total_tax": round(self.total_tax, 2),
            "expected_improvement": round(self.expected_improvement, 4),
            "created_at": self.created_at.isoformat(),
            "executed": self.executed,
        }


@dataclass
class PortfolioConstraints:
    """组合约束"""
    min_position_size: int = 100
    max_position_weight: float = 0.10
    min_position_weight: float = 0.01
    max_cash_weight: float = 0.20
    max_sector_weight: float = 0.30
    max_turnover: float = 0.50
    min_trades: int = 0
    max_trades: int = 50
    restricted_codes: List[str] = field(default_factory=list)
    required_codes: List[str] = field(default_factory=list)


@dataclass
class ExecutionConfig:
    """执行配置"""
    algorithm: ExecutionAlgorithm = ExecutionAlgorithm.SMART
    time_horizon: int = 60  # 分钟
    max_participation_rate: float = 0.1
    price_limit_pct: float = 0.01
    allow_partial_fill: bool = True
    cancel_on_limit: bool = True


# ============ 交易成本估算器 ============

class TransactionCostEstimator:
    """交易成本估算器"""

    def __init__(
        self,
        commission_rate: float = 0.0003,
        stamp_duty_rate: float = 0.001,
        slippage_rate: float = 0.0001,
    ):
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.slippage_rate = slippage_rate

    def estimate_cost(
        self,
        code: str,
        side: str,
        quantity: int,
        price: float,
        volume: float = None,
        volatility: float = None,
    ) -> float:
        """估算交易成本"""
        amount = price * quantity

        # 佣金
        commission = amount * self.commission_rate
        commission = max(commission, 5)  # 最低5元

        # 印花税（仅卖出）
        stamp_duty = amount * self.stamp_duty_rate if side == "sell" else 0

        # 滑点
        slippage = amount * self.slippage_rate

        # 市场冲击（基于成交量）
        if volume and volume > 0:
            participation = amount / volume
            market_impact = amount * participation * 0.01
            slippage += market_impact

        # 波动率调整
        if volatility and volatility > 0:
            slippage *= (1 + volatility * 10)

        return commission + stamp_duty + slippage

    def estimate_total_cost(
        self,
        trades: List[TradeProposal],
        volumes: Dict[str, float] = None,
        volatilities: Dict[str, float] = None,
    ) -> float:
        """估算总交易成本"""
        total = 0

        for trade in trades:
            volume = volumes.get(trade.code) if volumes else None
            volatility = volatilities.get(trade.code) if volatilities else None

            cost = self.estimate_cost(
                code=trade.code,
                side=trade.side,
                quantity=trade.quantity,
                price=trade.estimated_price,
                volume=volume,
                volatility=volatility,
            )
            total += cost

        return total


# ============ 税务优化器 ============

class TaxOptimizer:
    """税务优化器"""

    def __init__(self, tax_rate: float = 0.1, short_term_threshold: int = 365):
        self.tax_rate = tax_rate
        self.short_term_threshold = short_term_threshold

    def optimize_sell_order(
        self,
        code: str,
        quantity: int,
        tax_lots: List[TaxLot],
        current_price: float,
        method: TaxLotMethod = TaxLotMethod.HIFO,
    ) -> Tuple[List[TaxLot], float]:
        """优化卖出批次"""
        if method == TaxLotMethod.FIFO:
            sorted_lots = sorted(tax_lots, key=lambda x: x.purchase_date)
        elif method == TaxLotMethod.LIFO:
            sorted_lots = sorted(tax_lots, key=lambda x: x.purchase_date, reverse=True)
        elif method == TaxLotMethod.HIFO:
            sorted_lots = sorted(tax_lots, key=lambda x: x.cost_price, reverse=True)
        elif method == TaxLotMethod.LOFO:
            sorted_lots = sorted(tax_lots, key=lambda x: x.cost_price)
        else:
            sorted_lots = tax_lots

        # 选择批次
        selected_lots = []
        remaining = quantity
        total_tax = 0

        for lot in sorted_lots:
            if remaining <= 0:
                break

            sell_qty = min(lot.quantity, remaining)
            selected_lots.append(TaxLot(
                lot_id=lot.lot_id,
                code=lot.code,
                quantity=sell_qty,
                cost_price=lot.cost_price,
                purchase_date=lot.purchase_date,
                holding_days=lot.holding_days,
            ))

            # 计算税费
            pnl = (current_price - lot.cost_price) * sell_qty
            if pnl > 0:
                # 短期资本利得税率可能更高
                tax_rate = self.tax_rate
                if lot.holding_days < self.short_term_threshold:
                    tax_rate *= 1.5  # 短期税率更高

                total_tax += pnl * tax_rate

            remaining -= sell_qty

        return selected_lots, total_tax

    def calculate_harvesting_opportunity(
        self,
        positions: Dict[str, List[TaxLot]],
        current_prices: Dict[str, float],
    ) -> Dict:
        """计算税收收割机会"""
        opportunities = []

        for code, lots in positions.items():
            current_price = current_prices.get(code, 0)
            if current_price <= 0:
                continue

            for lot in lots:
                pnl = (current_price - lot.cost_price) * lot.quantity

                # 亏损批次可以用于抵税
                if pnl < 0:
                    opportunities.append({
                        "code": code,
                        "lot_id": lot.lot_id,
                        "quantity": lot.quantity,
                        "loss": abs(pnl),
                        "tax_saving": abs(pnl) * self.tax_rate,
                        "holding_days": lot.holding_days,
                    })

        # 按税收节省排序
        opportunities.sort(key=lambda x: x["tax_saving"], reverse=True)

        return {
            "opportunities": opportunities[:10],
            "total_loss": sum(o["loss"] for o in opportunities),
            "total_saving": sum(o["tax_saving"] for o in opportunities),
        }

    def wash_sale_check(
        self,
        code: str,
        sale_date: datetime,
        purchase_history: List[datetime],
        wash_period_days: int = 30,
    ) -> bool:
        """检查是否触发洗售规则"""
        for purchase_date in purchase_history:
            days_diff = (sale_date - purchase_date).days
            if 0 <= days_diff <= wash_period_days:
                return True

        return False


# ============ 执行算法 ============

class ExecutionAlgorithmBase(ABC):
    """执行算法基类"""

    @abstractmethod
    def generate_orders(
        self,
        code: str,
        side: str,
        total_quantity: int,
        current_price: float,
        config: ExecutionConfig,
        **kwargs,
    ) -> List[Dict]:
        """生成订单"""
        pass


class MarketOrderAlgorithm(ExecutionAlgorithmBase):
    """市价单算法"""

    def generate_orders(
        self,
        code: str,
        side: str,
        total_quantity: int,
        current_price: float,
        config: ExecutionConfig,
        **kwargs,
    ) -> List[Dict]:
        return [{
            "code": code,
            "side": side,
            "order_type": "market",
            "quantity": total_quantity,
            "price": current_price,
        }]


class TWAPAlgorithm(ExecutionAlgorithmBase):
    """TWAP算法"""

    def generate_orders(
        self,
        code: str,
        side: str,
        total_quantity: int,
        current_price: float,
        config: ExecutionConfig,
        **kwargs,
    ) -> List[Dict]:
        orders = []
        time_horizon = config.time_horizon
        n_slices = min(time_horizon, 60)  # 最多60个分片

        base_quantity = total_quantity // n_slices
        remaining = total_quantity

        for i in range(n_slices):
            if remaining <= 0:
                break

            slice_qty = min(base_quantity, remaining)
            remaining -= slice_qty

            orders.append({
                "code": code,
                "side": side,
                "order_type": "limit",
                "quantity": slice_qty,
                "price": current_price * (1 + config.price_limit_pct if side == "buy" else -config.price_limit_pct),
                "delay_minutes": i,
            })

        return orders


class VWAPAlgorithm(ExecutionAlgorithmBase):
    """VWAP算法"""

    def generate_orders(
        self,
        code: str,
        side: str,
        total_quantity: int,
        current_price: float,
        config: ExecutionConfig,
        volume_profile: List[float] = None,
        **kwargs,
    ) -> List[Dict]:
        orders = []

        if not volume_profile:
            # 默认均匀分布
            n_slices = min(config.time_horizon, 60)
            volume_profile = [1.0 / n_slices] * n_slices
        else:
            n_slices = len(volume_profile)
            total_volume = sum(volume_profile)
            volume_profile = [v / total_volume for v in volume_profile]

        remaining = total_quantity

        for i, pct in enumerate(volume_profile):
            if remaining <= 0:
                break

            slice_qty = int(total_quantity * pct)
            slice_qty = min(slice_qty, remaining)
            remaining -= slice_qty

            orders.append({
                "code": code,
                "side": side,
                "order_type": "limit",
                "quantity": slice_qty,
                "price": current_price,
                "delay_minutes": i,
            })

        return orders


class SmartAlgorithm(ExecutionAlgorithmBase):
    """智能执行算法"""

    def generate_orders(
        self,
        code: str,
        side: str,
        total_quantity: int,
        current_price: float,
        config: ExecutionConfig,
        volume: float = None,
        volatility: float = None,
        urgency: float = 0.5,
        **kwargs,
    ) -> List[Dict]:
        # 根据紧急程度选择策略
        if urgency > 0.8:
            # 高紧急：使用市价单
            return MarketOrderAlgorithm().generate_orders(
                code, side, total_quantity, current_price, config
            )
        elif urgency > 0.5:
            # 中等紧急：TWAP
            return TWAPAlgorithm().generate_orders(
                code, side, total_quantity, current_price, config
            )
        else:
            # 低紧急：VWAP
            return VWAPAlgorithm().generate_orders(
                code, side, total_quantity, current_price, config
            )


class ExecutionEngine:
    """执行引擎"""

    def __init__(self):
        self._algorithms: Dict[ExecutionAlgorithm, ExecutionAlgorithmBase] = {
            ExecutionAlgorithm.MARKET: MarketOrderAlgorithm(),
            ExecutionAlgorithm.TWAP: TWAPAlgorithm(),
            ExecutionAlgorithm.VWAP: VWAPAlgorithm(),
            ExecutionAlgorithm.SMART: SmartAlgorithm(),
        }

    def execute(
        self,
        code: str,
        side: str,
        quantity: int,
        price: float,
        config: ExecutionConfig,
        **kwargs,
    ) -> List[Dict]:
        """执行订单"""
        algorithm = self._algorithms.get(config.algorithm, SmartAlgorithm())

        return algorithm.generate_orders(
            code=code,
            side=side,
            total_quantity=quantity,
            current_price=price,
            config=config,
            **kwargs,
        )


# ============ 调仓优化器 ============

class RebalanceOptimizer:
    """调仓优化器"""

    def __init__(self):
        self.cost_estimator = TransactionCostEstimator()
        self.tax_optimizer = TaxOptimizer()
        self.execution_engine = ExecutionEngine()

    def optimize(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        portfolio_value: float,
        prices: Dict[str, float],
        constraints: PortfolioConstraints,
        volumes: Dict[str, float] = None,
        volatilities: Dict[str, float] = None,
        tax_lots: Dict[str, List[TaxLot]] = None,
    ) -> RebalancePlan:
        """优化调仓"""
        # 生成交易提案
        proposals = self._generate_proposals(
            current_weights=current_weights,
            target_weights=target_weights,
            portfolio_value=portfolio_value,
            prices=prices,
        )

        # 应用约束
        proposals = self._apply_constraints(proposals, constraints, portfolio_value)

        # 估算成本
        for proposal in proposals:
            proposal.estimated_cost = self.cost_estimator.estimate_cost(
                code=proposal.code,
                side=proposal.side,
                quantity=proposal.quantity,
                price=proposal.estimated_price,
                volume=volumes.get(proposal.code) if volumes else None,
                volatility=volatilities.get(proposal.code) if volatilities else None,
            )

            # 估算税费
            if proposal.side == "sell" and tax_lots:
                lots = tax_lots.get(proposal.code, [])
                _, proposal.estimated_tax = self.tax_optimizer.optimize_sell_order(
                    code=proposal.code,
                    quantity=proposal.quantity,
                    tax_lots=lots,
                    current_price=proposal.estimated_price,
                )

        # 按优先级排序
        proposals.sort(key=lambda x: x.priority, reverse=True)

        # 创建调仓计划
        plan = RebalancePlan(
            plan_id=f"rebalance_{int(datetime.now().timestamp() * 1000)}",
            trigger=RebalanceTrigger.MANUAL,
            strategy=RebalanceStrategy.SMART,
            trades=proposals,
        )

        plan.calculate_totals()

        return plan

    def _generate_proposals(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        portfolio_value: float,
        prices: Dict[str, float],
    ) -> List[TradeProposal]:
        """生成交易提案"""
        proposals = []
        all_codes = set(current_weights.keys()) | set(target_weights.keys())

        for code in all_codes:
            current_weight = current_weights.get(code, 0)
            target_weight = target_weights.get(code, 0)
            weight_diff = target_weight - current_weight

            if abs(weight_diff) < 0.001:  # 忽略微小变化
                continue

            price = prices.get(code, 0)
            if price <= 0:
                continue

            # 计算交易数量
            value_diff = portfolio_value * weight_diff
            quantity = int(value_diff / price / 100) * 100

            if quantity == 0:
                continue

            side = "buy" if quantity > 0 else "sell"

            proposal = TradeProposal(
                code=code,
                side=side,
                quantity=abs(quantity),
                current_weight=current_weight,
                target_weight=target_weight,
                estimated_price=price,
                estimated_cost=0,
                estimated_tax=0,
                priority=abs(weight_diff) * 100,  # 权重差异越大优先级越高
                reason=f"权重调整: {current_weight:.2%} -> {target_weight:.2%}",
            )

            proposals.append(proposal)

        return proposals

    def _apply_constraints(
        self,
        proposals: List[TradeProposal],
        constraints: PortfolioConstraints,
        portfolio_value: float,
    ) -> List[TradeProposal]:
        """应用约束"""
        filtered = []

        for proposal in proposals:
            # 检查最小交易量
            if proposal.quantity < constraints.min_position_size:
                continue

            # 检查限制股票
            if proposal.code in constraints.restricted_codes:
                continue

            # 检查最大持仓权重
            if proposal.target_weight > constraints.max_position_weight:
                proposal.target_weight = constraints.max_position_weight
                proposal.quantity = int(
                    portfolio_value * constraints.max_position_weight
                    / proposal.estimated_price / 100
                ) * 100

            filtered.append(proposal)

        # 检查最大交易数量
        if len(filtered) > constraints.max_trades:
            filtered.sort(key=lambda x: x.priority, reverse=True)
            filtered = filtered[:constraints.max_trades]

        return filtered

    def calculate_expected_improvement(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        expected_returns: Dict[str, float],
    ) -> float:
        """计算预期收益改进"""
        current_return = sum(
            current_weights.get(code, 0) * ret
            for code, ret in expected_returns.items()
        )

        target_return = sum(
            target_weights.get(code, 0) * ret
            for code, ret in expected_returns.items()
        )

        return target_return - current_return


# ============ 再平衡策略器 ============

class RebalanceScheduler:
    """再平衡调度器"""

    def __init__(self):
        self._schedules: Dict[str, Dict] = {}
        self._last_rebalance: Dict[str, datetime] = {}

    def should_rebalance(
        self,
        portfolio_id: str,
        trigger: RebalanceTrigger,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        threshold: float = 0.05,
        period_days: int = 30,
    ) -> bool:
        """判断是否需要调仓"""
        if trigger == RebalanceTrigger.PERIODIC:
            last = self._last_rebalance.get(portfolio_id)
            if last and (datetime.now() - last).days < period_days:
                return False
            return True

        elif trigger == RebalanceTrigger.THRESHOLD:
            # 检查权重偏离
            for code in set(current_weights.keys()) | set(target_weights.keys()):
                current = current_weights.get(code, 0)
                target = target_weights.get(code, 0)
                if abs(current - target) > threshold:
                    return True
            return False

        elif trigger == RebalanceTrigger.SIGNAL:
            # 信号触发需要外部判断
            return True

        elif trigger == RebalanceTrigger.RISK:
            # 风险触发需要外部判断
            return True

        return False

    def record_rebalance(self, portfolio_id: str):
        """记录调仓"""
        self._last_rebalance[portfolio_id] = datetime.now()

    def set_schedule(
        self,
        portfolio_id: str,
        trigger: RebalanceTrigger,
        config: Dict,
    ):
        """设置调度"""
        self._schedules[portfolio_id] = {
            "trigger": trigger,
            "config": config,
            "created_at": datetime.now(),
        }

    def get_schedule(self, portfolio_id: str) -> Optional[Dict]:
        """获取调度"""
        return self._schedules.get(portfolio_id)


# ============ 智能调仓服务 ============

class SmartRebalanceService:
    """智能调仓服务"""

    def __init__(self):
        self.optimizer = RebalanceOptimizer()
        self.scheduler = RebalanceScheduler()
        self.cost_estimator = TransactionCostEstimator()
        self.tax_optimizer = TaxOptimizer()
        self.execution_engine = ExecutionEngine()

        self._rebalance_history: List[RebalancePlan] = []

    def create_rebalance_plan(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        portfolio_value: float,
        prices: Dict[str, float],
        constraints: PortfolioConstraints = None,
        volumes: Dict[str, float] = None,
        volatilities: Dict[str, float] = None,
        tax_lots: Dict[str, List[TaxLot]] = None,
    ) -> RebalancePlan:
        """创建调仓计划"""
        constraints = constraints or PortfolioConstraints()

        plan = self.optimizer.optimize(
            current_weights=current_weights,
            target_weights=target_weights,
            portfolio_value=portfolio_value,
            prices=prices,
            constraints=constraints,
            volumes=volumes,
            volatilities=volatilities,
            tax_lots=tax_lots,
        )

        self._rebalance_history.append(plan)

        return plan

    def execute_rebalance(
        self,
        plan: RebalancePlan,
        config: ExecutionConfig = None,
    ) -> List[Dict]:
        """执行调仓"""
        config = config or ExecutionConfig()
        all_orders = []

        for trade in plan.trades:
            orders = self.execution_engine.execute(
                code=trade.code,
                side=trade.side,
                quantity=trade.quantity,
                price=trade.estimated_price,
                config=config,
            )
            all_orders.extend(orders)

        plan.executed = True

        return all_orders

    def should_rebalance(
        self,
        portfolio_id: str,
        trigger: RebalanceTrigger,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        **kwargs,
    ) -> bool:
        """判断是否需要调仓"""
        return self.scheduler.should_rebalance(
            portfolio_id=portfolio_id,
            trigger=trigger,
            current_weights=current_weights,
            target_weights=target_weights,
            **kwargs,
        )

    def analyze_tax_impact(
        self,
        positions: Dict[str, List[TaxLot]],
        current_prices: Dict[str, float],
    ) -> Dict:
        """分析税务影响"""
        return self.tax_optimizer.calculate_harvesting_opportunity(
            positions=positions,
            current_prices=current_prices,
        )

    def estimate_rebalance_cost(
        self,
        trades: List[TradeProposal],
        volumes: Dict[str, float] = None,
        volatilities: Dict[str, float] = None,
    ) -> Dict:
        """估算调仓成本"""
        total_cost = self.cost_estimator.estimate_total_cost(
            trades=trades,
            volumes=volumes,
            volatilities=volatilities,
        )

        total_tax = sum(t.estimated_tax for t in trades)

        return {
            "transaction_cost": round(total_cost, 2),
            "estimated_tax": round(total_tax, 2),
            "total_cost": round(total_cost + total_tax, 2),
            "trade_count": len(trades),
        }

    def get_rebalance_history(
        self,
        limit: int = 10,
    ) -> List[RebalancePlan]:
        """获取调仓历史"""
        return self._rebalance_history[-limit:]


# ============ 便捷函数 ============

def create_rebalance_service() -> SmartRebalanceService:
    """创建调仓服务"""
    return SmartRebalanceService()


def optimize_rebalance(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
    portfolio_value: float,
    prices: Dict[str, float],
) -> RebalancePlan:
    """优化调仓"""
    service = SmartRebalanceService()
    return service.create_rebalance_plan(
        current_weights=current_weights,
        target_weights=target_weights,
        portfolio_value=portfolio_value,
        prices=prices,
    )
