"""西部量化可转债策略 V3.0 三层交易成本模型

三层成本:
1. 第一层: 显性交易成本
   - 佣金: 万分之一(双边0.02%)
   - 经手费: 十万分之四

2. 第二层: 滑点成本(按标的流动性分档)
   - >1亿: 0.05%
   - 5000万-1亿: 0.10%
   - 1000万-5000万: 0.20%
   - <1000万: 禁止交易

3. 第三层: 冲击成本
   - 冲击成本 = (单次交易金额 / 标的日均成交额) × 0.3

成本控制优化:
- 轮换缓冲带
- 最小持仓期
- 合并调仓窗口
- AUM分级轮换频率
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional, Tuple
import logging

from app.xb_strategy.core.types import TransactionCost, Position
from app.xb_strategy.config.settings import params

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """交易记录"""
    date: date
    code: str
    action: str  # buy/sell
    price: float
    volume: int
    amount: float  # 交易金额(元)
    cost: TransactionCost


class TransactionCostModel:
    """交易成本模型"""

    def __init__(self, aum: float = 10000.0):
        """初始化

        Args:
            aum: 资产规模(万元)
        """
        self.aum = aum
        self._trade_history: List[TradeRecord] = []
        self._monthly_cost: Dict[str, float] = {}  # {YYYY-MM: cost}

    def calculate_cost(
        self,
        price: float,
        volume: int,
        daily_amount: float,
        action: str = "buy",
    ) -> TransactionCost:
        """计算交易成本

        Args:
            price: 价格
            volume: 数量(张)
            daily_amount: 标的日均成交额(万元)
            action: 买卖方向

        Returns:
            TransactionCost: 交易成本
        """
        trade_amount = price * volume  # 交易金额(元)

        # 1. 显性成本
        # 佣金(双边收取)
        commission = trade_amount * params.commission_rate * 2
        # 经手费
        exchange_fee = trade_amount * params.exchange_fee

        # 2. 滑点成本
        slippage = self._calculate_slippage(trade_amount, daily_amount)

        # 3. 冲击成本
        impact = self._calculate_impact(trade_amount, daily_amount)

        total = commission + exchange_fee + slippage + impact

        return TransactionCost(
            commission=commission,
            exchange_fee=exchange_fee,
            slippage=slippage,
            impact=impact,
            total=total,
        )

    def _calculate_slippage(
        self,
        trade_amount: float,
        daily_amount: float,
    ) -> float:
        """计算滑点成本

        Args:
            trade_amount: 交易金额(元)
            daily_amount: 日均成交额(万元)

        Returns:
            滑点成本(元)
        """
        daily_amount_yuan = daily_amount * 10000  # 转换为元

        if daily_amount_yuan >= params.liq_high_threshold * 10000:
            rate = params.slippage_high_liq
        elif daily_amount_yuan >= params.liq_mid_threshold * 10000:
            rate = params.slippage_mid_liq
        elif daily_amount_yuan >= params.liq_low_threshold * 10000:
            rate = params.slippage_low_liq
        else:
            # 流动性过低，禁止交易
            rate = float("inf")

        return trade_amount * rate

    def _calculate_impact(
        self,
        trade_amount: float,
        daily_amount: float,
    ) -> float:
        """计算冲击成本

        冲击成本 = (单次交易金额 / 标的日均成交额) × 0.3

        Args:
            trade_amount: 交易金额(元)
            daily_amount: 日均成交额(万元)

        Returns:
            冲击成本(元)
        """
        if daily_amount <= 0:
            return trade_amount * 0.01  # 默认1%

        daily_amount_yuan = daily_amount * 10000

        # 冲击成本率
        impact_rate = (trade_amount / daily_amount_yuan) * params.impact_factor if daily_amount_yuan > 0 else 0

        # 限制最大冲击成本
        impact_rate = min(impact_rate, 0.02)  # 最大2%

        return trade_amount * impact_rate

    def estimate_monthly_cost(
        self,
        avg_daily_turnover: float = 0.15,
        avg_positions: int = 40,
        trading_days: int = 21,
    ) -> dict:
        """预估月度交易成本

        Args:
            avg_daily_turnover: 平均日换手率
            avg_positions: 平均持仓数
            trading_days: 交易天数

        Returns:
            月度成本预估
        """
        aum_yuan = self.aum * 10000  # 转换为元

        # 日均交易金额
        daily_trade = aum_yuan * avg_daily_turnover

        # 佣金(双边)
        monthly_commission = daily_trade * params.commission_rate * 2 * trading_days

        # 经手费
        monthly_exchange = daily_trade * params.exchange_fee * trading_days

        # 滑点(假设中等流动性)
        monthly_slippage = daily_trade * params.slippage_mid_liq * trading_days

        # 冲击成本(假设单笔交易额/日均成交额 = 0.05)
        avg_trade_per_position = daily_trade / max(avg_positions * avg_daily_turnover * 10, 1)
        impact_rate = avg_trade_per_position / 30000000 * params.impact_factor  # 假设日均成交3000万
        monthly_impact = daily_trade * min(impact_rate, 0.005) * trading_days

        monthly_total = (
            monthly_commission
            + monthly_exchange
            + monthly_slippage
            + monthly_impact
        )

        # 年化成本
        annual_cost = monthly_total * 12
        annual_cost_ratio = annual_cost / aum_yuan

        return {
            "monthly_commission": round(monthly_commission, 2),
            "monthly_exchange": round(monthly_exchange, 2),
            "monthly_slippage": round(monthly_slippage, 2),
            "monthly_impact": round(monthly_impact, 2),
            "monthly_total": round(monthly_total, 2),
            "annual_cost": round(annual_cost, 2),
            "annual_cost_ratio": round(annual_cost_ratio * 100, 2),
            "monthly_cost_ratio": round(monthly_total / aum_yuan * 100, 4),
        }

    def record_trade(
        self,
        date: date,
        code: str,
        action: str,
        price: float,
        volume: int,
        daily_amount: float,
    ) -> TradeRecord:
        """记录交易

        Args:
            date: 日期
            code: 转债代码
            action: 买卖方向
            price: 价格
            volume: 数量
            daily_amount: 日均成交额

        Returns:
            TradeRecord: 交易记录
        """
        cost = self.calculate_cost(price, volume, daily_amount, action)
        amount = price * volume

        record = TradeRecord(
            date=date,
            code=code,
            action=action,
            price=price,
            volume=volume,
            amount=amount,
            cost=cost,
        )

        self._trade_history.append(record)

        # 更新月度成本
        month_key = date.strftime("%Y-%m")
        self._monthly_cost[month_key] = self._monthly_cost.get(month_key, 0) + cost.total

        return record

    def get_daily_cost(self, date: date) -> float:
        """获取当日交易成本

        Args:
            date: 日期

        Returns:
            成本总额
        """
        return sum(
            r.cost.total for r in self._trade_history
            if r.date == date
        )

    def get_monthly_cost(self, month: str) -> float:
        """获取月度交易成本

        Args:
            month: 月份(YYYY-MM)

        Returns:
            成本总额
        """
        return self._monthly_cost.get(month, 0.0)

    def check_cost_limit(self, month: str) -> Tuple[bool, str]:
        """检查成本是否超限

        Args:
            month: 月份

        Returns:
            (是否超限, 说明)
        """
        monthly_cost = self.get_monthly_cost(month)
        monthly_cost_ratio = monthly_cost / (self.aum * 10000)

        # 月度成本不应超过AUM的0.8%
        if monthly_cost_ratio > 0.008:
            return True, f"月度成本({monthly_cost_ratio*100:.2f}%)超过0.8%阈值"

        return False, "成本正常"

    def get_cost_report(self) -> dict:
        """获取成本报告

        Returns:
            成本报告
        """
        if not self._trade_history:
            return {
                "total_trades": 0,
                "total_cost": 0,
                "avg_cost_per_trade": 0,
            }

        total_cost = sum(r.cost.total for r in self._trade_history)
        total_amount = sum(r.amount for r in self._trade_history)

        return {
            "total_trades": len(self._trade_history),
            "total_cost": round(total_cost, 2),
            "total_amount": round(total_amount, 2),
            "cost_ratio": round(total_cost / total_amount * 100, 4) if total_amount > 0 else 0,
            "avg_cost_per_trade": round(total_cost / len(self._trade_history), 2),
            "monthly_costs": self._monthly_cost.copy(),
        }


class CostController:
    """成本控制器"""

    def __init__(self, aum: float = 10000.0):
        """初始化

        Args:
            aum: 资产规模(万元)
        """
        self.aum = aum
        self.cost_model = TransactionCostModel(aum)
        self._min_holding_days = params.min_holding_days
        self._position_dates: Dict[str, date] = {}  # {code: buy_date}

    def check_min_holding_period(
        self,
        code: str,
        sell_date: date,
    ) -> Tuple[bool, int]:
        """检查最小持仓期

        Args:
            code: 转债代码
            sell_date: 拟卖出日期

        Returns:
            (是否满足, 持仓天数)
        """
        buy_date = self._position_dates.get(code)
        if buy_date is None:
            return True, 0

        holding_days = (sell_date - buy_date).days
        return holding_days >= self._min_holding_days, holding_days

    def record_buy(self, code: str, buy_date: date) -> None:
        """记录买入

        Args:
            code: 转债代码
            buy_date: 买入日期
        """
        self._position_dates[code] = buy_date

    def record_sell(self, code: str) -> None:
        """记录卖出

        Args:
            code: 转债代码
        """
        self._position_dates.pop(code, None)

    def should_reduce_rebalance(
        self,
        monthly_cost_ratio: float,
    ) -> bool:
        """是否应该降低调仓频率

        Args:
            monthly_cost_ratio: 月度成本比例

        Returns:
            是否应该降低
        """
        return monthly_cost_ratio > 0.008

    def get_optimal_trade_size(
        self,
        daily_amount: float,
        max_position_ratio: float = 0.05,
    ) -> int:
        """获取最优交易规模

        Args:
            daily_amount: 日均成交额(万元)
            max_position_ratio: 最大仓位比例

        Returns:
            建议交易数量(张)
        """
        # 不超过日均成交额的5%
        max_trade_amount = daily_amount * 10000 * 0.05  # 元

        # 不超过AUM的max_position_ratio
        max_position_amount = self.aum * 10000 * max_position_ratio

        # 取较小值
        optimal_amount = min(max_trade_amount, max_position_amount)

        # 转换为张数(假设均价100元)
        return int(optimal_amount / 100)

    def batch_trades(
        self,
        signals: List[dict],
        max_daily_ratio: float = 0.20,
    ) -> Tuple[List[dict], List[dict]]:
        """批量处理交易信号

        将交易信号分批，避免单日交易过大

        Args:
            signals: 交易信号列表
            max_daily_ratio: 单日最大交易比例

        Returns:
            (当日执行信号, 延迟执行信号)
        """
        aum_yuan = self.aum * 10000
        max_daily_trade = aum_yuan * max_daily_ratio

        current_day_amount = 0
        today_signals = []
        deferred_signals = []

        for signal in signals:
            signal_amount = signal.get("amount", signal.get("price", 100) * 10)

            if current_day_amount + signal_amount <= max_daily_trade:
                today_signals.append(signal)
                current_day_amount += signal_amount
            else:
                deferred_signals.append(signal)

        return today_signals, deferred_signals
