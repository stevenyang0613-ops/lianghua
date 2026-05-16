"""
交易成本模型 V3.0

三层成本模型：
1. 显性成本：佣金、印花税、经手费
2. 滑点成本：按流动性分档
3. 冲击成本：与交易金额/成交额相关

用于回测扣除成本和实盘成本控制
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd


@dataclass
class TransactionCost:
    """单笔交易成本"""
    commission: float  # 佣金
    stamp_duty: float  # 印花税
    exchange_fee: float  # 经手费
    slippage: float  # 滑点
    market_impact: float  # 冲击成本
    total: float  # 总成本
    total_ratio: float  # 总成本比例


@dataclass
class MonthlyCostReport:
    """月度成本报告"""
    total_trades: int
    total_turnover: float  # 总成交额
    total_cost: float  # 总成本
    cost_ratio: float  # 成本占比
    avg_slippage: float
    avg_impact: float
    exceeded_warning: bool  # 是否超过阈值


class TransactionCostModel:
    """交易成本模型"""

    # 显性成本费率
    COMMISSION_RATE = 0.0001  # 万分之一（双边）
    STAMP_DUTY_RATE = 0.0  # 转债免印花税
    EXCHANGE_FEE_RATE = 0.00004  # 十万分之四

    # 滑点成本分档（单边）
    SLIPPAGE_TIERS = {
        'high': {'threshold': 10000, 'rate': 0.0005},      # >1亿成交额，0.05%
        'medium': {'threshold': 5000, 'rate': 0.0010},     # 5000万-1亿，0.10%
        'low': {'threshold': 1000, 'rate': 0.0020},        # 1000万-5000万，0.20%
        'blocked': {'threshold': 0, 'rate': float('inf')},  # <1000万禁止交易
    }

    # 冲击成本系数
    IMPACT_COEFFICIENT = 0.3

    # 月度成本预警阈值
    MONTHLY_COST_WARNING_RATIO = 0.008  # 月度成本超过AUM的0.8%

    def __init__(self, aum: float = 100000000):  # 默认1亿AUM
        self._aum = aum
        self._trade_history: list[dict] = []
        self._daily_cost: dict[str, float] = {}

    def calc_commission(self, amount: float, is_buy: bool = True) -> float:
        """计算佣金（双边收取）"""
        return amount * self.COMMISSION_RATE

    def calc_stamp_duty(self, amount: float) -> float:
        """计算印花税（转债免征）"""
        return amount * self.STAMP_DUTY_RATE

    def calc_exchange_fee(self, amount: float) -> float:
        """计算经手费"""
        return amount * self.EXCHANGE_FEE_RATE

    def calc_slippage(self, amount: float, daily_volume: float) -> tuple[float, str]:
        """
        计算滑点成本
        daily_volume: 日均成交额（万元）
        返回: (滑点金额, 流动性等级)
        """
        volume_w = daily_volume  # 万元

        if volume_w >= self.SLIPPAGE_TIERS['high']['threshold']:
            rate = self.SLIPPAGE_TIERS['high']['rate']
            tier = 'high'
        elif volume_w >= self.SLIPPAGE_TIERS['medium']['threshold']:
            rate = self.SLIPPAGE_TIERS['medium']['rate']
            tier = 'medium'
        elif volume_w >= self.SLIPPAGE_TIERS['low']['threshold']:
            rate = self.SLIPPAGE_TIERS['low']['rate']
            tier = 'low'
        else:
            return float('inf'), 'blocked'

        return amount * rate, tier

    def calc_market_impact(
        self,
        trade_amount: float,
        daily_volume: float,
    ) -> float:
        """
        计算冲击成本
        冲击成本 = (交易金额 / 日均成交额) × 0.3
        """
        if daily_volume <= 0:
            return float('inf')

        # trade_amount和daily_volume单位都是万元
        impact_ratio = (trade_amount / daily_volume) * self.IMPACT_COEFFICIENT
        return trade_amount * impact_ratio

    def calc_total_cost(
        self,
        trade_amount: float,
        daily_volume: float,
        is_buy: bool = True,
    ) -> TransactionCost:
        """计算单笔交易的总成本"""
        # 显性成本
        commission = self.calc_commission(trade_amount, is_buy)
        stamp_duty = self.calc_stamp_duty(trade_amount)
        exchange_fee = self.calc_exchange_fee(trade_amount)

        # 滑点成本
        slippage, tier = self.calc_slippage(trade_amount, daily_volume)

        if tier == 'blocked':
            return TransactionCost(
                commission=commission,
                stamp_duty=stamp_duty,
                exchange_fee=exchange_fee,
                slippage=float('inf'),
                market_impact=float('inf'),
                total=float('inf'),
                total_ratio=float('inf'),
            )

        # 冲击成本
        market_impact = self.calc_market_impact(trade_amount, daily_volume)

        # 总成本
        total = commission + stamp_duty + exchange_fee + slippage + market_impact
        total_ratio = total / trade_amount if trade_amount > 0 else 0

        return TransactionCost(
            commission=round(commission, 2),
            stamp_duty=round(stamp_duty, 2),
            exchange_fee=round(exchange_fee, 2),
            slippage=round(slippage, 2),
            market_impact=round(market_impact, 2),
            total=round(total, 2),
            total_ratio=round(total_ratio, 6),
        )

    def record_trade(
        self,
        code: str,
        action: str,
        amount: float,
        price: float,
        volume: float,
        daily_volume: float,
    ) -> TransactionCost:
        """记录交易并计算成本"""
        cost = self.calc_total_cost(amount, daily_volume, action == 'buy')

        trade_date = datetime.now().strftime('%Y-%m-%d')

        self._trade_history.append({
            'code': code,
            'action': action,
            'amount': amount,
            'price': price,
            'volume': volume,
            'daily_volume': daily_volume,
            'cost': cost.total,
            'cost_ratio': cost.total_ratio,
            'date': trade_date,
            'ts': datetime.now().isoformat(),
        })

        # 更新日成本统计
        if trade_date not in self._daily_cost:
            self._daily_cost[trade_date] = 0
        self._daily_cost[trade_date] += cost.total

        return cost

    def get_monthly_report(self, year: int, month: int) -> MonthlyCostReport:
        """获取月度成本报告"""
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)

        # 筛选当月交易
        month_trades = [
            t for t in self._trade_history
            if start_date <= datetime.fromisoformat(t['ts']) <= end_date
        ]

        if not month_trades:
            return MonthlyCostReport(
                total_trades=0,
                total_turnover=0,
                total_cost=0,
                cost_ratio=0,
                avg_slippage=0,
                avg_impact=0,
                exceeded_warning=False,
            )

        total_turnover = sum(t['amount'] for t in month_trades)
        total_cost = sum(t['cost'] for t in month_trades)
        cost_ratio = total_cost / self._aum if self._aum > 0 else 0

        # 计算平均滑点和冲击成本
        slippage_costs = []
        impact_costs = []
        for t in month_trades:
            cost = self.calc_total_cost(t['amount'], t['daily_volume'])
            if cost.slippage != float('inf'):
                slippage_costs.append(cost.slippage)
            if cost.market_impact != float('inf'):
                impact_costs.append(cost.market_impact)

        avg_slippage = sum(slippage_costs) / len(slippage_costs) if slippage_costs else 0
        avg_impact = sum(impact_costs) / len(impact_costs) if impact_costs else 0

        return MonthlyCostReport(
            total_trades=len(month_trades),
            total_turnover=round(total_turnover, 2),
            total_cost=round(total_cost, 2),
            cost_ratio=round(cost_ratio, 4),
            avg_slippage=round(avg_slippage, 2),
            avg_impact=round(avg_impact, 2),
            exceeded_warning=cost_ratio > self.MONTHLY_COST_WARNING_RATIO,
        )

    def should_reduce_turnover(self) -> bool:
        """判断是否应该降低换手率"""
        # 获取当月报告
        now = datetime.now()
        report = self.get_monthly_report(now.year, now.month)
        return report.exceeded_warning

    def estimate_round_trip_cost(
        self,
        position_value: float,
        daily_volume: float,
    ) -> float:
        """估算往返交易成本（买入+卖出）"""
        buy_cost = self.calc_total_cost(position_value, daily_volume, is_buy=True)
        sell_cost = self.calc_total_cost(position_value, daily_volume, is_buy=False)

        if buy_cost.total == float('inf') or sell_cost.total == float('inf'):
            return float('inf')

        return buy_cost.total + sell_cost.total

    def get_trading_limit(
        self,
        daily_volume: float,
        max_impact_ratio: float = 0.1,
    ) -> float:
        """
        获取单日交易限额
        限制单日交易量不超过日均成交额的一定比例
        """
        if daily_volume <= 0:
            return 0

        # 单日交易不超过日均成交额的20%
        return daily_volume * 0.2

    @property
    def aum(self) -> float:
        return self._aum

    def set_aum(self, aum: float) -> None:
        self._aum = aum

    def get_trade_history(self, days: int = 30) -> list[dict]:
        """获取交易历史"""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            t for t in self._trade_history
            if datetime.fromisoformat(t['ts']) >= cutoff
        ]
