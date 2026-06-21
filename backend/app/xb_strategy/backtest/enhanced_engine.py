"""西部量化可转债策略 V3.0 增强回测引擎模块

功能:
- 多资产组合回测
- 滑点/冲击成本建模
- 逐笔成交模拟
- 资金曲线追踪
- 风险指标实时计算
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple, Callable
from enum import Enum
import logging
import numpy as np
import pandas as pd
from collections import deque, defaultdict
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class SlippageModel(str, Enum):
    """滑点模型"""
    FIXED = "fixed"               # 固定滑点
    PERCENTAGE = "percentage"     # 百分比滑点
    VOLUME = "volume"             # 成交量相关
    VOLATILITY = "volatility"     # 波动率相关
    SMART = "smart"               # 智能滑点


# ============ 数据模型 ============

@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 10_000_000.0
    commission_rate: float = 0.0003
    stamp_duty_rate: float = 0.001
    slippage_model: SlippageModel = SlippageModel.SMART
    base_slippage: float = 0.0001
    enable_margin: bool = False
    margin_rate: float = 0.5
    risk_free_rate: float = 0.03
    benchmark_code: str = "000300.SH"
    rebalance_frequency: str = "daily"
    max_position_pct: float = 0.1
    min_trade_amount: int = 100


@dataclass
class Trade:
    """交易记录"""
    trade_id: str
    code: str
    side: OrderSide
    quantity: int
    price: float
    amount: float
    commission: float
    stamp_duty: float
    slippage: float
    timestamp: datetime
    order_id: str = None

    @property
    def total_cost(self) -> float:
        """总成本"""
        if self.side == OrderSide.BUY:
            return self.amount + self.commission + self.slippage
        else:
            return self.amount - self.commission - self.stamp_duty - self.slippage


@dataclass
class Position:
    """持仓"""
    code: str
    quantity: int = 0
    cost_price: float = 0
    market_value: float = 0
    unrealized_pnl: float = 0
    realized_pnl: float = 0
    daily_pnl: float = 0

    def update_market_value(self, current_price: float):
        """更新市值"""
        self.market_value = self.quantity * current_price
        if self.quantity > 0 and self.cost_price > 0:
            self.unrealized_pnl = (current_price - self.cost_price) * self.quantity

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "quantity": self.quantity,
            "cost_price": round(self.cost_price, 4),
            "market_value": round(self.market_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
        }


@dataclass
class PortfolioSnapshot:
    """组合快照"""
    timestamp: datetime
    total_value: float
    cash: float
    positions: Dict[str, Position]
    daily_return: float = 0
    cumulative_return: float = 0
    drawdown: float = 0
    sharpe_ratio: float = 0
    volatility: float = 0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_value": round(self.total_value, 2),
            "cash": round(self.cash, 2),
            "position_count": len([p for p in self.positions.values() if p.quantity > 0]),
            "daily_return": round(self.daily_return, 6),
            "cumulative_return": round(self.cumulative_return, 6),
            "drawdown": round(self.drawdown, 6),
        }


@dataclass
class BacktestResult:
    """回测结果"""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_value: float
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_loss_ratio: float
    total_trades: int
    total_commission: float
    total_slippage: float
    equity_curve: List[PortfolioSnapshot] = field(default_factory=list)
    trade_history: List[Trade] = field(default_factory=list)

    def to_summary(self) -> dict:
        return {
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.end_date.strftime("%Y-%m-%d"),
            "initial_capital": round(self.initial_capital, 2),
            "final_value": round(self.final_value, 2),
            "total_return": f"{self.total_return * 100:.2f}%",
            "annualized_return": f"{self.annualized_return * 100:.2f}%",
            "annualized_volatility": f"{self.annualized_volatility * 100:.2f}%",
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown": f"{self.max_drawdown * 100:.2f}%",
            "win_rate": f"{self.win_rate * 100:.2f}%",
            "total_trades": self.total_trades,
        }


# ============ 滑点模型 ============

class SlippageCalculator:
    """滑点计算器"""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def calculate_slippage(
        self,
        price: float,
        quantity: int,
        volume: float = None,
        volatility: float = None,
        side: OrderSide = OrderSide.BUY,
    ) -> float:
        """计算滑点"""
        model = self.config.slippage_model

        if model == SlippageModel.FIXED:
            return self._fixed_slippage(price, quantity)
        elif model == SlippageModel.PERCENTAGE:
            return self._percentage_slippage(price, quantity)
        elif model == SlippageModel.VOLUME:
            return self._volume_slippage(price, quantity, volume)
        elif model == SlippageModel.VOLATILITY:
            return self._volatility_slippage(price, quantity, volatility)
        else:
            return self._smart_slippage(price, quantity, volume, volatility)

    def _fixed_slippage(self, price: float, quantity: int) -> float:
        """固定滑点"""
        return price * quantity * self.config.base_slippage

    def _percentage_slippage(self, price: float, quantity: int) -> float:
        """百分比滑点"""
        return price * quantity * self.config.base_slippage

    def _volume_slippage(self, price: float, quantity: int, volume: float) -> float:
        """成交量相关滑点"""
        if volume is None or volume <= 0:
            volume = quantity * price

        participation_rate = (quantity * price) / volume
        slippage_rate = self.config.base_slippage * (1 + participation_rate * 10)

        return price * quantity * slippage_rate

    def _volatility_slippage(self, price: float, quantity: int, volatility: float) -> float:
        """波动率相关滑点"""
        if volatility is None or volatility <= 0:
            volatility = 0.02

        slippage_rate = self.config.base_slippage * (1 + volatility * 10)

        return price * quantity * slippage_rate

    def _smart_slippage(
        self,
        price: float,
        quantity: int,
        volume: float = None,
        volatility: float = None,
    ) -> float:
        """智能滑点"""
        base = price * quantity * self.config.base_slippage

        # 成交量影响
        if volume and volume > 0:
            participation = (quantity * price) / volume
            base *= (1 + participation * 5)

        # 波动率影响
        if volatility and volatility > 0:
            base *= (1 + volatility * 3)

        return base


# ============ 成交模拟器 ============

class ExecutionSimulator:
    """成交模拟器"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.slippage_calc = SlippageCalculator(config)
        self._trade_counter = 0

    def simulate_market_order(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        current_price: float,
        volume: float = None,
        volatility: float = None,
        timestamp: datetime = None,
    ) -> Trade:
        """模拟市价单成交"""
        timestamp = timestamp or datetime.now()

        # 计算滑点
        slippage = self.slippage_calc.calculate_slippage(
            price=current_price,
            quantity=quantity,
            volume=volume,
            volatility=volatility,
            side=side,
        )

        # 计算成交价格（考虑滑点方向）
        if side == OrderSide.BUY:
            fill_price = current_price + slippage / quantity
        else:
            fill_price = current_price - slippage / quantity

        # 计算金额和费用
        amount = fill_price * quantity
        commission = amount * self.config.commission_rate
        stamp_duty = amount * self.config.stamp_duty_rate if side == OrderSide.SELL else 0

        # 生成交易ID
        self._trade_counter += 1
        trade_id = f"trade_{self._trade_counter}_{int(timestamp.timestamp() * 1000)}"

        return Trade(
            trade_id=trade_id,
            code=code,
            side=side,
            quantity=quantity,
            price=fill_price,
            amount=amount,
            commission=commission,
            stamp_duty=stamp_duty,
            slippage=slippage,
            timestamp=timestamp,
        )

    def simulate_limit_order(
        self,
        code: str,
        side: OrderSide,
        quantity: int,
        limit_price: float,
        current_price: float,
        volume: float = None,
        volatility: float = None,
        timestamp: datetime = None,
    ) -> Optional[Trade]:
        """模拟限价单成交"""
        timestamp = timestamp or datetime.now()

        # 检查是否能够成交
        if side == OrderSide.BUY and current_price > limit_price:
            return None
        if side == OrderSide.SELL and current_price < limit_price:
            return None

        # 按限价成交
        amount = limit_price * quantity
        commission = amount * self.config.commission_rate
        stamp_duty = amount * self.config.stamp_duty_rate if side == OrderSide.SELL else 0

        self._trade_counter += 1
        trade_id = f"trade_{self._trade_counter}_{int(timestamp.timestamp() * 1000)}"

        return Trade(
            trade_id=trade_id,
            code=code,
            side=side,
            quantity=quantity,
            price=limit_price,
            amount=amount,
            commission=commission,
            stamp_duty=stamp_duty,
            slippage=0,
            timestamp=timestamp,
        )

    def simulate_tick_by_tick(
        self,
        code: str,
        side: OrderSide,
        total_quantity: int,
        tick_prices: List[float],
        tick_volumes: List[float],
        participation_rate: float = 0.1,
        timestamp: datetime = None,
    ) -> List[Trade]:
        """逐笔成交模拟"""
        trades = []
        remaining = total_quantity
        timestamp = timestamp or datetime.now()

        for i, (price, volume) in enumerate(zip(tick_prices, tick_volumes)):
            if remaining <= 0:
                break

            # 按参与率计算可成交量
            fillable_qty = min(
                int(volume * participation_rate),
                remaining
            )

            if fillable_qty > 0:
                trade = self.simulate_market_order(
                    code=code,
                    side=side,
                    quantity=fillable_qty,
                    current_price=price,
                    volume=volume,
                    timestamp=timestamp,
                )
                trades.append(trade)
                remaining -= fillable_qty

        return trades


# ============ 组合管理器 ============

class PortfolioManager:
    """组合管理器"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.positions: Dict[str, Position] = {}
        self.cash = config.initial_capital
        self.total_value = config.initial_capital
        self.realized_pnl = 0
        self._trade_history: List[Trade] = []

    def execute_trade(self, trade: Trade):
        """执行交易"""
        code = trade.code

        if code not in self.positions:
            self.positions[code] = Position(code=code)

        position = self.positions[code]

        if trade.side == OrderSide.BUY:
            # 买入
            new_quantity = position.quantity + trade.quantity
            new_cost = position.cost_price * position.quantity + trade.total_cost

            if new_quantity > 0:
                position.cost_price = new_cost / new_quantity
            position.quantity = new_quantity

            self.cash -= trade.total_cost

        else:
            # 卖出
            if position.quantity >= trade.quantity:
                # 计算已实现盈亏
                cost_basis = position.cost_price * trade.quantity
                position.realized_pnl += trade.total_cost - cost_basis
                self.realized_pnl += trade.total_cost - cost_basis

            position.quantity -= trade.quantity
            self.cash += trade.total_cost

        self._trade_history.append(trade)

    def update_prices(self, prices: Dict[str, float]):
        """更新价格"""
        total_market_value = 0

        for code, price in prices.items():
            if code in self.positions:
                self.positions[code].update_market_value(price)
                total_market_value += self.positions[code].market_value

        self.total_value = self.cash + total_market_value

    def get_position(self, code: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(code)

    def get_all_positions(self) -> Dict[str, Position]:
        """获取所有持仓"""
        return {k: v for k, v in self.positions.items() if v.quantity > 0}

    def get_trade_history(self) -> List[Trade]:
        """获取交易历史"""
        return self._trade_history.copy()

    def get_snapshot(self, timestamp: datetime) -> PortfolioSnapshot:
        """获取快照"""
        return PortfolioSnapshot(
            timestamp=timestamp,
            total_value=self.total_value,
            cash=self.cash,
            positions=self.get_all_positions(),
        )


# ============ 绩效计算器 ============

class PerformanceCalculator:
    """绩效计算器"""

    def __init__(self, risk_free_rate: float = 0.03):
        self.risk_free_rate = risk_free_rate
        self._returns: deque = deque(maxlen=252)

    def add_return(self, daily_return: float):
        """添加日收益率"""
        self._returns.append(daily_return)

    def calculate_sharpe_ratio(self) -> float:
        """计算夏普比率"""
        if len(self._returns) < 2:
            return 0

        returns = np.array(self._returns)
        excess_returns = returns - self.risk_free_rate / 252

        if np.std(excess_returns) == 0:
            return 0

        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)

    def calculate_max_drawdown(self, equity_curve: List[float]) -> Tuple[float, int]:
        """计算最大回撤"""
        if not equity_curve:
            return 0, 0

        peak = equity_curve[0]
        max_dd = 0
        max_dd_duration = 0
        current_duration = 0

        for value in equity_curve:
            if value > peak:
                peak = value
                current_duration = 0
            else:
                dd = (peak - value) / peak
                max_dd = max(max_dd, dd)
                current_duration += 1
                max_dd_duration = max(max_dd_duration, current_duration)

        return max_dd, max_dd_duration

    def calculate_win_rate(self, trades: List[Trade]) -> float:
        """计算胜率"""
        if not trades:
            return 0

        wins = sum(1 for t in trades if t.side == OrderSide.SELL and t.price > 0)

        sell_trades = sum(1 for t in trades if t.side == OrderSide.SELL)

        return wins / sell_trades if sell_trades > 0 else 0

    def calculate_profit_loss_ratio(self, trades: List[Trade]) -> float:
        """计算盈亏比"""
        profits = []
        losses = []

        for trade in trades:
            if trade.side == OrderSide.SELL:
                pnl = trade.amount
                if pnl > 0:
                    profits.append(pnl)
                else:
                    losses.append(abs(pnl))

        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 1

        return avg_profit / avg_loss if avg_loss > 0 else 0


# ============ 增强回测引擎 ============

class EnhancedBacktestEngine:
    """增强回测引擎"""

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.portfolio = PortfolioManager(self.config)
        self.executor = ExecutionSimulator(self.config)
        self.performance = PerformanceCalculator(self.config.risk_free_rate)

        self._equity_curve: List[PortfolioSnapshot] = []
        self._trade_history: List[Trade] = []
        self._daily_prices: Dict[str, List[float]] = defaultdict(list)

    def load_data(self, data: pd.DataFrame):
        """加载数据"""
        self._data = data
        self._dates = sorted(data['date'].unique())

    def run(
        self,
        strategy: Callable[[datetime, Dict, Dict], Dict[str, float]],
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> BacktestResult:
        """运行回测"""
        logger.info("[EnhancedBacktestEngine] 开始回测...")

        start_date = start_date or self._dates[0]
        end_date = end_date or self._dates[-1]

        prev_value = self.config.initial_capital
        peak_value = self.config.initial_capital

        for date in self._dates:
            if date < start_date or date > end_date:
                continue

            # 获取当日数据
            daily_data = self._data[self._data['date'] == date]
            prices = dict(zip(daily_data['code'], daily_data['close']))

            # 更新持仓市值
            self.portfolio.update_prices(prices)

            # 执行策略
            signals = strategy(date, daily_data.to_dict('records'), self.portfolio.get_all_positions())

            # 执行交易
            for code, weight in signals.items():
                if code in prices:
                    self._rebalance_position(code, weight, prices[code], date, daily_data)

            # 记录快照
            snapshot = self.portfolio.get_snapshot(date)
            snapshot.daily_return = (self.portfolio.total_value - prev_value) / prev_value
            snapshot.cumulative_return = (self.portfolio.total_value - self.config.initial_capital) / self.config.initial_capital

            # 计算回撤
            if self.portfolio.total_value > peak_value:
                peak_value = self.portfolio.total_value
            snapshot.drawdown = (peak_value - self.portfolio.total_value) / peak_value

            self._equity_curve.append(snapshot)
            self.performance.add_return(snapshot.daily_return)

            prev_value = self.portfolio.total_value

        # 生成结果
        result = self._generate_result(start_date, end_date)
        logger.info(f"[EnhancedBacktestEngine] 回测完成: 总收益率={result.total_return:.2%}")

        return result

    def _rebalance_position(
        self,
        code: str,
        target_weight: float,
        price: float,
        date: datetime,
        daily_data: pd.DataFrame,
    ):
        """调整持仓"""
        current_position = self.portfolio.get_position(code)
        current_value = current_position.market_value if current_position else 0
        target_value = self.portfolio.total_value * target_weight

        diff_value = target_value - current_value
        trade_quantity = int(diff_value / price / 100) * 100

        if trade_quantity == 0:
            return

        side = OrderSide.BUY if trade_quantity > 0 else OrderSide.SELL
        trade_quantity = abs(trade_quantity)

        # 获取波动率和成交量
        row = daily_data[daily_data['code'] == code]
        volatility = row['volatility'].iloc[0] if 'volatility' in row.columns else None
        volume = row['volume'].iloc[0] if 'volume' in row.columns else None

        trade = self.executor.simulate_market_order(
            code=code,
            side=side,
            quantity=trade_quantity,
            current_price=price,
            volume=volume,
            volatility=volatility,
            timestamp=date,
        )

        self.portfolio.execute_trade(trade)
        self._trade_history.append(trade)

    def _generate_result(self, start_date: datetime, end_date: datetime) -> BacktestResult:
        """生成回测结果"""
        equity_values = [s.total_value for s in self._equity_curve]

        if not equity_values:
            return BacktestResult(
                start_date=start_date,
                end_date=end_date,
                initial_capital=self.config.initial_capital,
                final_value=self.config.initial_capital,
                total_return=0,
                annualized_return=0,
                annualized_volatility=0,
                sharpe_ratio=0,
                max_drawdown=0,
                max_drawdown_duration=0,
                win_rate=0,
                profit_loss_ratio=0,
                total_trades=0,
                total_commission=0,
                total_slippage=0,
            )

        returns = np.array([s.daily_return for s in self._equity_curve])

        total_return = (equity_values[-1] - self.config.initial_capital) / self.config.initial_capital
        annualized_return = (1 + total_return) ** (252 / len(equity_values)) - 1
        annualized_volatility = np.std(returns) * np.sqrt(252)

        max_dd, max_dd_duration = self.performance.calculate_max_drawdown(equity_values)

        total_commission = sum(t.commission for t in self._trade_history)
        total_slippage = sum(t.slippage for t in self._trade_history)

        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital,
            final_value=equity_values[-1],
            total_return=total_return,
            annualized_return=annualized_return,
            annualized_volatility=annualized_volatility,
            sharpe_ratio=self.performance.calculate_sharpe_ratio(),
            max_drawdown=max_dd,
            max_drawdown_duration=max_dd_duration,
            win_rate=self.performance.calculate_win_rate(self._trade_history),
            profit_loss_ratio=self.performance.calculate_profit_loss_ratio(self._trade_history),
            total_trades=len(self._trade_history),
            total_commission=total_commission,
            total_slippage=total_slippage,
            equity_curve=self._equity_curve,
            trade_history=self._trade_history,
        )


# ============ 便捷函数 ============

def create_backtest_engine(config: BacktestConfig = None) -> EnhancedBacktestEngine:
    """创建回测引擎"""
    return EnhancedBacktestEngine(config)


def run_backtest(
    data: pd.DataFrame,
    strategy: Callable,
    initial_capital: float = 10_000_000,
) -> BacktestResult:
    """运行回测"""
    config = BacktestConfig(initial_capital=initial_capital)
    engine = EnhancedBacktestEngine(config)
    engine.load_data(data)
    return engine.run(strategy)
