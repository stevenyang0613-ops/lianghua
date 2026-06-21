"""西部量化可转债策略 V3.0 智能调仓系统模块

功能:
- 现金流预测
- 最优调仓时点
- 税务优化
- 分批执行策略
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum
import logging
import math
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class RebalanceTrigger(str, Enum):
    """调仓触发类型"""
    SCHEDULED = "scheduled"       # 定期调仓
    SIGNAL = "signal"             # 信号触发
    THRESHOLD = "threshold"       # 阈值触发
    CASHFLOW = "cashflow"         # 现金流触发
    RISK = "risk"                 # 风控触发
    MANUAL = "manual"             # 手动触发


class RebalanceStatus(str, Enum):
    """调仓状态"""
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaxOptimizationStrategy(str, Enum):
    """税务优化策略"""
    NONE = "none"                 # 无优化
    FIFO = "fifo"                 # 先进先出
    LIFO = "lifo"                 # 后进先出
    HIFO = "hifo"                 # 最高成本先出
    TAX_LOSS_HARVESTING = "tlh"  # 税损收割
    SPECIFIC_ID = "specific"      # 指定批次


class ExecutionStrategy(str, Enum):
    """执行策略"""
    IMMEDIATE = "immediate"       # 立即执行
    TWAP = "twap"                 # 时间加权
    VWAP = "vwap"                 # 成交量加权
    ADAPTIVE = "adaptive"         # 自适应
    TRIGGER = "trigger"           # 触发执行


# ============ 数据模型 ============

@dataclass
class Position:
    """持仓"""
    code: str
    quantity: int
    cost_basis: float  # 成本基础
    current_price: float
    market_value: float = 0
    unrealized_pnl: float = 0
    weight: float = 0
    target_weight: float = 0
    drift: float = 0

    def __post_init__(self):
        self.market_value = self.quantity * self.current_price
        self.unrealized_pnl = (self.current_price - self.cost_basis) * self.quantity

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "quantity": self.quantity,
            "cost_basis": self.cost_basis,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "weight": round(self.weight, 4),
            "target_weight": round(self.target_weight, 4),
            "drift": round(self.drift, 4),
        }


@dataclass
class CashflowForecast:
    """现金流预测"""
    date: datetime
    expected_inflow: float
    expected_outflow: float
    net_cashflow: float
    confidence: float
    source: str

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "expected_inflow": self.expected_inflow,
            "expected_outflow": self.expected_outflow,
            "net_cashflow": self.net_cashflow,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass
class TaxLot:
    """税务批次"""
    lot_id: str
    code: str
    quantity: int
    purchase_date: datetime
    purchase_price: float
    current_price: float
    holding_days: int = 0
    unrealized_pnl: float = 0
    tax_rate: float = 0.2  # 假设20%税率

    def __post_init__(self):
        self.unrealized_pnl = (self.current_price - self.purchase_price) * self.quantity

    def calculate_tax_impact(self) -> float:
        """计算税务影响"""
        if self.unrealized_pnl > 0:
            return self.unrealized_pnl * self.tax_rate
        return 0  # 亏损无税

    def to_dict(self) -> dict:
        return {
            "lot_id": self.lot_id,
            "code": self.code,
            "quantity": self.quantity,
            "purchase_date": self.purchase_date.isoformat(),
            "purchase_price": self.purchase_price,
            "holding_days": self.holding_days,
            "unrealized_pnl": self.unrealized_pnl,
            "tax_impact": self.calculate_tax_impact(),
        }


@dataclass
class RebalancePlan:
    """调仓计划"""
    plan_id: str
    trigger: RebalanceTrigger
    status: RebalanceStatus
    created_at: datetime
    current_positions: List[Position]
    target_weights: Dict[str, float]
    trades: List[Dict] = field(default_factory=list)
    estimated_cost: float = 0
    tax_impact: float = 0
    execution_strategy: ExecutionStrategy = ExecutionStrategy.VWAP
    scheduled_time: datetime = None
    completed_at: datetime = None

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "trigger": self.trigger.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "current_positions": [p.to_dict() for p in self.current_positions],
            "target_weights": self.target_weights,
            "trades": self.trades,
            "estimated_cost": self.estimated_cost,
            "tax_impact": self.tax_impact,
            "execution_strategy": self.execution_strategy.value,
        }


# ============ 现金流预测器 ============

class CashflowForecaster:
    """现金流预测器"""

    def __init__(self, forecast_days: int = 30):
        self.forecast_days = forecast_days
        self._historical_cashflows: List[Dict] = []
        self._scheduled_events: List[Dict] = []

    def add_historical_cashflow(self, cashflow: Dict):
        """添加历史现金流"""
        self._historical_cashflows.append(cashflow)

    def add_scheduled_event(self, event: Dict):
        """添加计划事件"""
        self._scheduled_events.append(event)

    def forecast(self, start_date: datetime = None) -> List[CashflowForecast]:
        """预测现金流"""
        start_date = start_date or datetime.now()
        forecasts = []

        for i in range(self.forecast_days):
            forecast_date = start_date + timedelta(days=i)

            # 基于历史数据预测
            expected_inflow, inflow_conf = self._predict_inflow(forecast_date)
            expected_outflow, outflow_conf = self._predict_outflow(forecast_date)

            # 添加计划事件
            scheduled_inflow, scheduled_outflow = self._get_scheduled_amounts(forecast_date)

            total_inflow = expected_inflow + scheduled_inflow
            total_outflow = expected_outflow + scheduled_outflow
            net_cashflow = total_inflow - total_outflow

            confidence = (inflow_conf + outflow_conf) / 2

            forecast = CashflowForecast(
                date=forecast_date,
                expected_inflow=total_inflow,
                expected_outflow=total_outflow,
                net_cashflow=net_cashflow,
                confidence=confidence,
                source="predicted",
            )

            forecasts.append(forecast)

        return forecasts

    def _predict_inflow(self, date: datetime) -> Tuple[float, float]:
        """预测流入"""
        # 简化: 基于历史平均值
        if not self._historical_cashflows:
            return 0, 0.5

        inflows = [cf.get("inflow", 0) for cf in self._historical_cashflows[-30:]]
        avg_inflow = sum(inflows) / len(inflows) if inflows else 0

        # 根据星期几调整
        weekday = date.weekday()
        weekday_factor = {0: 0.8, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.2, 5: 0.5, 6: 0.3}

        expected = avg_inflow * weekday_factor.get(weekday, 1.0)
        confidence = 0.7 if len(inflows) >= 10 else 0.5

        return expected, confidence

    def _predict_outflow(self, date: datetime) -> Tuple[float, float]:
        """预测流出"""
        if not self._historical_cashflows:
            return 0, 0.5

        outflows = [cf.get("outflow", 0) for cf in self._historical_cashflows[-30:]]
        avg_outflow = sum(outflows) / len(outflows) if outflows else 0

        expected = avg_outflow
        confidence = 0.6 if len(outflows) >= 10 else 0.4

        return expected, confidence

    def _get_scheduled_amounts(self, date: datetime) -> Tuple[float, float]:
        """获取计划金额"""
        inflow, outflow = 0, 0

        for event in self._scheduled_events:
            event_date = event.get("date")
            if isinstance(event_date, str):
                event_date = datetime.fromisoformat(event_date)

            if event_date and event_date.date() == date.date():
                if event.get("type") == "inflow":
                    inflow += event.get("amount", 0)
                else:
                    outflow += event.get("amount", 0)

        return inflow, outflow

    def get_cash_needs(self, days: int = 7) -> float:
        """获取现金需求"""
        forecasts = self.forecast()
        net_need = sum(f.net_cashflow for f in forecasts[:days] if f.net_cashflow < 0)
        return abs(net_need)


# ============ 调仓时机优化器 ============

class RebalanceTimingOptimizer:
    """调仓时机优化器"""

    def __init__(self):
        self._market_calendar: List[datetime] = []
        self._volatility_forecasts: Dict[str, float] = {}

    def set_market_calendar(self, trading_days: List[datetime]):
        """设置交易日历"""
        self._market_calendar = trading_days

    def find_optimal_timing(
        self,
        rebalance_plan: RebalancePlan,
        constraints: Dict = None,
    ) -> datetime:
        """寻找最优调仓时点"""
        constraints = constraints or {}

        # 默认约束
        max_delay_days = constraints.get("max_delay_days", 5)
        avoid_days = constraints.get("avoid_days", [])  # 避免的星期几
        preferred_hours = constraints.get("preferred_hours", [10, 14])  # 偏好时段

        now = datetime.now()
        best_time = None
        best_score = -1

        for i in range(max_delay_days):
            candidate = now + timedelta(days=i)

            # 检查是否交易日
            if self._market_calendar and candidate not in self._market_calendar:
                continue

            # 检查是否避免日
            if candidate.weekday() in avoid_days:
                continue

            # 计算评分
            score = self._score_timing(candidate, rebalance_plan, constraints)

            if score > best_score:
                best_score = score
                best_time = candidate.replace(hour=preferred_hours[0], minute=0, second=0)

        return best_time or now

    def _score_timing(
        self,
        candidate: datetime,
        plan: RebalancePlan,
        constraints: Dict,
    ) -> float:
        """评分时点"""
        score = 100.0

        # 波动率调整
        if candidate.strftime("%Y-%m-%d") in self._volatility_forecasts:
            vol = self._volatility_forecasts[candidate.strftime("%Y-%m-%d")]
            score -= vol * 100

        # 流动性调整 (开盘后1小时和收盘前1小时流动性较好)
        hour = candidate.hour
        if hour in [10, 14]:
            score += 10

        # 延迟惩罚
        days_delay = (candidate - datetime.now()).days
        score -= days_delay * 5

        return score


# ============ 税务优化器 ============

class TaxOptimizer:
    """税务优化器"""

    def __init__(self, strategy: TaxOptimizationStrategy = TaxOptimizationStrategy.HIFO):
        self.strategy = strategy
        self._tax_lots: Dict[str, List[TaxLot]] = defaultdict(list)
        self._tax_rate = 0.2  # 20%税率

    def add_tax_lot(self, lot: TaxLot):
        """添加税务批次"""
        self._tax_lots[lot.code].append(lot)

    def set_tax_lots(self, code: str, lots: List[TaxLot]):
        """设置税务批次"""
        self._tax_lots[code] = lots

    def optimize_sell_order(
        self,
        code: str,
        quantity: int,
        current_price: float,
    ) -> Tuple[List[TaxLot], float]:
        """优化卖出订单"""
        available_lots = self._tax_lots.get(code, [])

        if not available_lots:
            return [], 0

        # 更新当前价格
        for lot in available_lots:
            lot.current_price = current_price

        # 根据策略排序
        if self.strategy == TaxOptimizationStrategy.FIFO:
            sorted_lots = sorted(available_lots, key=lambda x: x.purchase_date)
        elif self.strategy == TaxOptimizationStrategy.LIFO:
            sorted_lots = sorted(available_lots, key=lambda x: x.purchase_date, reverse=True)
        elif self.strategy == TaxOptimizationStrategy.HIFO:
            sorted_lots = sorted(available_lots, key=lambda x: x.purchase_price, reverse=True)
        elif self.strategy == TaxOptimizationStrategy.TAX_LOSS_HARVESTING:
            # 先卖亏损批次
            sorted_lots = sorted(available_lots, key=lambda x: x.unrealized_pnl)
        else:
            sorted_lots = available_lots

        # 选择批次
        selected_lots = []
        remaining = quantity
        total_tax = 0

        for lot in sorted_lots:
            if remaining <= 0:
                break

            sell_qty = min(lot.quantity, remaining)
            tax_impact = lot.calculate_tax_impact() * (sell_qty / lot.quantity)

            selected_lots.append(TaxLot(
                lot_id=lot.lot_id,
                code=lot.code,
                quantity=sell_qty,
                purchase_date=lot.purchase_date,
                purchase_price=lot.purchase_price,
                current_price=current_price,
            ))

            total_tax += tax_impact
            remaining -= sell_qty

        return selected_lots, total_tax

    def calculate_tax_harvest_opportunity(
        self,
        positions: Dict[str, Position],
    ) -> List[Dict]:
        """计算税损收割机会"""
        opportunities = []

        for code, position in positions.items():
            lots = self._tax_lots.get(code, [])

            for lot in lots:
                if lot.unrealized_pnl < 0:
                    # 亏损批次，可收割
                    tax_benefit = abs(lot.unrealized_pnl) * self._tax_rate

                    opportunities.append({
                        "code": code,
                        "lot_id": lot.lot_id,
                        "quantity": lot.quantity,
                        "unrealized_loss": lot.unrealized_pnl,
                        "tax_benefit": tax_benefit,
                        "holding_days": lot.holding_days,
                    })

        # 按税务收益排序
        opportunities.sort(key=lambda x: x["tax_benefit"], reverse=True)

        return opportunities

    def estimate_tax_impact(
        self,
        trades: List[Dict],
    ) -> float:
        """估算税务影响"""
        total_tax = 0

        for trade in trades:
            if trade.get("side") == "sell":
                code = trade.get("code")
                quantity = trade.get("quantity", 0)
                price = trade.get("price", 0)

                _, tax = self.optimize_sell_order(code, quantity, price)
                total_tax += tax

        return total_tax


# ============ 调仓规划器 ============

class RebalancePlanner:
    """调仓规划器"""

    def __init__(
        self,
        tax_optimizer: TaxOptimizer = None,
        timing_optimizer: RebalanceTimingOptimizer = None,
    ):
        self.tax_optimizer = tax_optimizer or TaxOptimizer()
        self.timing_optimizer = timing_optimizer or RebalanceTimingOptimizer()
        self._plans: Dict[str, RebalancePlan] = {}

    def create_plan(
        self,
        positions: List[Position],
        target_weights: Dict[str, float],
        trigger: RebalanceTrigger = RebalanceTrigger.SCHEDULED,
        drift_threshold: float = 0.05,
    ) -> RebalancePlan:
        """创建调仓计划"""
        plan_id = f"rebalance_{int(datetime.now().timestamp() * 1000)}"

        # 计算总市值
        total_value = sum(p.market_value for p in positions)

        # 计算当前权重和偏离
        for pos in positions:
            pos.weight = pos.market_value / total_value if total_value > 0 else 0
            pos.target_weight = target_weights.get(pos.code, 0)
            pos.drift = pos.target_weight - pos.weight

        # 生成交易列表
        trades = self._generate_trades(positions, total_value, drift_threshold)

        # 计算成本
        estimated_cost = self._estimate_transaction_cost(trades)

        # 计算税务影响
        tax_impact = self.tax_optimizer.estimate_tax_impact(
            [t for t in trades if t.get("side") == "sell"]
        )

        plan = RebalancePlan(
            plan_id=plan_id,
            trigger=trigger,
            status=RebalanceStatus.PENDING,
            created_at=datetime.now(),
            current_positions=positions,
            target_weights=target_weights,
            trades=trades,
            estimated_cost=estimated_cost,
            tax_impact=tax_impact,
        )

        self._plans[plan_id] = plan

        return plan

    def _generate_trades(
        self,
        positions: List[Position],
        total_value: float,
        drift_threshold: float,
    ) -> List[Dict]:
        """生成交易列表"""
        trades = []

        # 卖出: 权重过高
        for pos in positions:
            if pos.drift < -drift_threshold:
                # 需要卖出
                sell_value = abs(pos.drift) * total_value
                sell_quantity = int(sell_value / pos.current_price)

                if sell_quantity > 0:
                    trades.append({
                        "code": pos.code,
                        "side": "sell",
                        "quantity": sell_quantity,
                        "price": pos.current_price,
                        "reason": f"权重过高，需降低 {-pos.drift:.2%}",
                    })

        # 买入: 权重过低
        for pos in positions:
            if pos.drift > drift_threshold:
                # 需要买入
                buy_value = pos.drift * total_value
                buy_quantity = int(buy_value / pos.current_price)

                if buy_quantity > 0:
                    trades.append({
                        "code": pos.code,
                        "side": "buy",
                        "quantity": buy_quantity,
                        "price": pos.current_price,
                        "reason": f"权重过低，需增加 {pos.drift:.2%}",
                    })

        # 新增标的
        for code, weight in self.target_weights.items():
            if not any(p.code == code for p in positions) and weight > drift_threshold:
                buy_value = weight * total_value
                # 需要获取价格
                trades.append({
                    "code": code,
                    "side": "buy",
                    "quantity": 0,  # 待确定
                    "price": 0,     # 待确定
                    "reason": f"新增持仓，目标权重 {weight:.2%}",
                })

        return trades

    def _estimate_transaction_cost(self, trades: List[Dict]) -> float:
        """估算交易成本"""
        total_cost = 0
        commission_rate = 0.0003

        for trade in trades:
            value = trade.get("quantity", 0) * trade.get("price", 0)
            total_cost += value * commission_rate

        return total_cost

    def optimize_plan(
        self,
        plan_id: str,
        constraints: Dict = None,
    ) -> Dict:
        """优化计划"""
        plan = self._plans.get(plan_id)
        if not plan:
            return {}

        # 寻找最优时点
        optimal_time = self.timing_optimizer.find_optimal_timing(plan, constraints)

        # 税务优化卖出订单
        optimized_trades = []
        for trade in plan.trades:
            if trade.get("side") == "sell":
                lots, tax = self.tax_optimizer.optimize_sell_order(
                    code=trade["code"],
                    quantity=trade["quantity"],
                    current_price=trade["price"],
                )
                trade["tax_lots"] = [l.to_dict() for l in lots]
                trade["estimated_tax"] = tax
            optimized_trades.append(trade)

        plan.trades = optimized_trades
        plan.scheduled_time = optimal_time

        return {
            "plan_id": plan_id,
            "optimal_time": optimal_time.isoformat(),
            "optimized_trades": optimized_trades,
            "tax_impact": plan.tax_impact,
        }

    def get_plan(self, plan_id: str) -> Optional[RebalancePlan]:
        """获取计划"""
        return self._plans.get(plan_id)


# ============ 智能调仓执行器 ============

class SmartRebalanceExecutor:
    """智能调仓执行器"""

    def __init__(self, planner: RebalancePlanner = None):
        self.planner = planner or RebalancePlanner()
        self.cashflow_forecaster = CashflowForecaster()

        self._execution_callbacks: List[Callable] = []
        self._lock = threading.Lock()

    def create_and_execute(
        self,
        positions: List[Position],
        target_weights: Dict[str, float],
        trigger: RebalanceTrigger = RebalanceTrigger.SCHEDULED,
        execution_strategy: ExecutionStrategy = ExecutionStrategy.VWAP,
    ) -> str:
        """创建并执行调仓"""
        # 创建计划
        plan = self.planner.create_plan(positions, target_weights, trigger)
        plan.execution_strategy = execution_strategy

        # 检查现金流
        cash_needs = self._calculate_cash_needs(plan)
        cash_available = self.cashflow_forecaster.get_cash_needs(0)

        if cash_needs > cash_available:
            logger.warning(f"[SmartRebalanceExecutor] 现金不足: 需要 {cash_needs}, 可用 {cash_available}")

        # 优化计划
        self.planner.optimize_plan(plan.plan_id)

        # 执行
        plan.status = RebalanceStatus.EXECUTING

        logger.info(f"[SmartRebalanceExecutor] 开始执行调仓: {plan.plan_id}")

        return plan.plan_id

    def _calculate_cash_needs(self, plan: RebalancePlan) -> float:
        """计算现金需求"""
        cash_needs = 0

        for trade in plan.trades:
            if trade.get("side") == "buy":
                cash_needs += trade.get("quantity", 0) * trade.get("price", 0)

        return cash_needs

    def register_callback(self, callback: Callable):
        """注册回调"""
        self._execution_callbacks.append(callback)

    def get_execution_status(self, plan_id: str) -> Dict:
        """获取执行状态"""
        plan = self.planner.get_plan(plan_id)
        if not plan:
            return {"error": "plan_not_found"}

        return {
            "plan_id": plan_id,
            "status": plan.status.value,
            "trades": plan.trades,
            "created_at": plan.created_at.isoformat(),
            "scheduled_time": plan.scheduled_time.isoformat() if plan.scheduled_time else None,
        }

    def cancel_plan(self, plan_id: str) -> bool:
        """取消计划"""
        plan = self.planner.get_plan(plan_id)
        if not plan:
            return False

        if plan.status in [RebalanceStatus.COMPLETED, RebalanceStatus.CANCELLED]:
            return False

        plan.status = RebalanceStatus.CANCELLED
        logger.info(f"[SmartRebalanceExecutor] 取消调仓: {plan_id}")

        return True


# ============ 便捷函数 ============

def create_rebalance_planner() -> RebalancePlanner:
    """创建调仓规划器"""
    return RebalancePlanner()


def create_smart_rebalancer() -> SmartRebalanceExecutor:
    """创建智能调仓器"""
    return SmartRebalanceExecutor()


def calculate_drift(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
) -> Dict[str, float]:
    """计算权重偏离"""
    drift = {}
    all_codes = set(current_weights.keys()) | set(target_weights.keys())

    for code in all_codes:
        current = current_weights.get(code, 0)
        target = target_weights.get(code, 0)
        drift[code] = target - current

    return drift


def needs_rebalance(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
    threshold: float = 0.05,
) -> bool:
    """判断是否需要调仓"""
    drift = calculate_drift(current_weights, target_weights)

    for code, d in drift.items():
        if abs(d) > threshold:
            return True

    return False
