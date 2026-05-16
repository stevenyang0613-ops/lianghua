"""
Walk-Forward回测验证框架 V3.0

用于样本外验证策略有效性：
- 训练窗口：12个月滚动
- 测试窗口：3个月样本外
- 滚动步长：3个月
- 全周期：2018年1月 - 至今
- 交易成本：全额扣除
- 基准：中证转债指数（000832）
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable
import pandas as pd
import numpy as np


@dataclass
class BacktestResult:
    """回测结果"""
    start_date: str
    end_date: str
    total_return: float  # 总收益率
    annual_return: float  # 年化收益率
    max_drawdown: float  # 最大回撤
    sharpe_ratio: float  # 夏普比率
    win_rate: float  # 胜率
    profit_factor: float  # 盈亏比
    total_trades: int
    avg_holding_days: float
    benchmark_return: float
    excess_return: float
    details: dict = field(default_factory=dict)


@dataclass
class WalkForwardResult:
    """Walk-Forward验证结果"""
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_result: BacktestResult
    test_result: BacktestResult
    parameters: dict
    is_overfit: bool  # 是否过拟合（训练期远优于测试期）


class WalkForwardValidator:
    """Walk-Forward验证框架"""

    # 默认参数
    DEFAULT_PARAMS = {
        'train_window_months': 12,
        'test_window_months': 3,
        'step_months': 3,
        'commission_rate': 0.0002,  # 双边佣金
        'slippage_rate': 0.001,  # 滑点
        'impact_coefficient': 0.3,  # 冲击成本系数
    }

    def __init__(self, data: pd.DataFrame, strategy_func: Callable):
        """
        初始化验证框架
        data: 历史数据，包含date, code, price等列
        strategy_func: 策略函数，输入数据，返回信号列表
        """
        self._data = data.copy()
        self._strategy_func = strategy_func
        self._results: list[WalkForwardResult] = []
        self._benchmark_returns: dict[str, float] = {}

    def _get_date_ranges(self, start_date: str, end_date: str) -> list[tuple[str, str, str, str]]:
        """
        生成Walk-Forward日期范围
        返回: [(train_start, train_end, test_start, test_end), ...]
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        train_months = self.DEFAULT_PARAMS['train_window_months']
        test_months = self.DEFAULT_PARAMS['test_window_months']
        step_months = self.DEFAULT_PARAMS['step_months']

        ranges = []
        current = start

        while True:
            train_start = current
            train_end = current + timedelta(days=train_months * 30)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=test_months * 30)

            if test_end > end:
                break

            ranges.append((
                train_start.strftime('%Y-%m-%d'),
                train_end.strftime('%Y-%m-%d'),
                test_start.strftime('%Y-%m-%d'),
                test_end.strftime('%Y-%m-%d'),
            ))

            current = current + timedelta(days=step_months * 30)

        return ranges

    def _filter_data_by_date(self, start: str, end: str) -> pd.DataFrame:
        """按日期范围筛选数据"""
        mask = (self._data['date'] >= start) & (self._data['date'] <= end)
        return self._data[mask].copy()

    def _apply_transaction_cost(
        self,
        trade_amount: float,
        daily_volume: float = 10000,  # 默认1亿
    ) -> float:
        """应用交易成本"""
        commission = trade_amount * self.DEFAULT_PARAMS['commission_rate']
        slippage = trade_amount * self.DEFAULT_PARAMS['slippage_rate']

        # 冲击成本
        impact = (trade_amount / daily_volume) * self.DEFAULT_PARAMS['impact_coefficient'] * trade_amount

        return commission + slippage + impact

    def _run_backtest(
        self,
        data: pd.DataFrame,
        initial_capital: float = 1000000,
    ) -> BacktestResult:
        """运行单次回测"""
        if data.empty:
            return None

        # 获取策略信号
        try:
            signals = self._strategy_func(data)
        except Exception as e:
            return None

        if not signals:
            return None

        # 模拟交易
        capital = initial_capital
        positions: dict[str, dict] = {}  # code -> {price, volume, date}
        trades: list[dict] = []
        daily_values: list[float] = []
        dates = sorted(data['date'].unique())

        for date in dates:
            day_data = data[data['date'] == date]
            day_signals = [s for s in signals if s.get('date') == date or date in str(s.get('date', ''))]

            # 执行信号
            for sig in day_signals:
                code = sig['code']
                action = sig['action']
                price = sig['price']

                if action == 'buy' and code not in positions:
                    # 买入
                    volume = int(capital * 0.02 / price)  # 单只2%仓位
                    if volume > 0:
                        cost = self._apply_transaction_cost(volume * price)
                        if capital >= volume * price + cost:
                            positions[code] = {
                                'price': price,
                                'volume': volume,
                                'date': date,
                            }
                            capital -= volume * price + cost
                            trades.append({
                                'date': date,
                                'code': code,
                                'action': 'buy',
                                'price': price,
                                'volume': volume,
                                'cost': cost,
                            })

                elif action == 'sell' and code in positions:
                    # 卖出
                    pos = positions[code]
                    proceeds = pos['volume'] * price
                    cost = self._apply_transaction_cost(proceeds)
                    capital += proceeds - cost
                    pnl = (price - pos['price']) * pos['volume'] - cost
                    trades.append({
                        'date': date,
                        'code': code,
                        'action': 'sell',
                        'price': price,
                        'volume': pos['volume'],
                        'pnl': pnl,
                        'cost': cost,
                    })
                    del positions[code]

            # 计算当日净值
            position_value = sum(
                pos['volume'] * day_data[day_data['code'] == code]['price'].iloc[0]
                for code, pos in positions.items()
                if code in day_data['code'].values
            )
            total_value = capital + position_value
            daily_values.append(total_value)

        # 计算收益指标
        if not daily_values:
            return None

        values_series = pd.Series(daily_values)
        returns = values_series.pct_change().dropna()

        total_return = (values_series.iloc[-1] - initial_capital) / initial_capital
        days = len(daily_values)
        annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0

        # 最大回撤
        cummax = values_series.cummax()
        drawdown = (values_series - cummax) / cummax
        max_drawdown = abs(drawdown.min())

        # 夏普比率
        if returns.std() > 0:
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252)
        else:
            sharpe_ratio = 0

        # 胜率
        win_trades = [t for t in trades if t.get('pnl', 0) > 0]
        total_closed = len([t for t in trades if 'pnl' in t])
        win_rate = len(win_trades) / total_closed if total_closed > 0 else 0

        # 盈亏比
        wins = [t['pnl'] for t in win_trades]
        losses = [t['pnl'] for t in trades if t.get('pnl', 0) < 0]
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 1
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

        # 平均持有天数
        holding_days = []
        for i, t in enumerate(trades):
            if t['action'] == 'sell':
                buy_trade = next(
                    (trades[j] for j in range(i-1, -1, -1)
                     if trades[j]['code'] == t['code'] and trades[j]['action'] == 'buy'),
                    None
                )
                if buy_trade:
                    days = (datetime.strptime(t['date'], '%Y-%m-%d') -
                            datetime.strptime(buy_trade['date'], '%Y-%m-%d')).days
                    holding_days.append(days)

        avg_holding_days = np.mean(holding_days) if holding_days else 0

        return BacktestResult(
            start_date=dates[0] if dates else '',
            end_date=dates[-1] if dates else '',
            total_return=round(total_return, 4),
            annual_return=round(annual_return, 4),
            max_drawdown=round(max_drawdown, 4),
            sharpe_ratio=round(sharpe_ratio, 2),
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 2),
            total_trades=len(trades),
            avg_holding_days=round(avg_holding_days, 1),
            benchmark_return=0,  # 后续填充
            excess_return=0,
            details={
                'total_trades': len(trades),
                'win_trades': len(win_trades),
                'final_value': round(values_series.iloc[-1], 2),
            },
        )

    def run_validation(
        self,
        start_date: str = '2018-01-01',
        end_date: str = None,
        optimize_func: Optional[Callable] = None,
    ) -> list[WalkForwardResult]:
        """
        运行Walk-Forward验证
        optimize_func: 参数优化函数，在训练期优化参数
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        date_ranges = self._get_date_ranges(start_date, end_date)
        results = []

        for train_start, train_end, test_start, test_end in date_ranges:
            # 获取训练数据
            train_data = self._filter_data_by_date(train_start, train_end)
            if train_data.empty:
                continue

            # 参数优化（如果有优化函数）
            params = {}
            if optimize_func:
                params = optimize_func(train_data)

            # 训练期回测
            train_result = self._run_backtest(train_data)

            # 测试期回测
            test_data = self._filter_data_by_date(test_start, test_end)
            test_result = self._run_backtest(test_data)

            if train_result and test_result:
                # 判断是否过拟合
                is_overfit = (
                    train_result.annual_return > test_result.annual_return * 1.5
                    or train_result.sharpe_ratio > test_result.sharpe_ratio * 1.5
                )

                wf_result = WalkForwardResult(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_result=train_result,
                    test_result=test_result,
                    parameters=params,
                    is_overfit=is_overfit,
                )
                results.append(wf_result)
                self._results.append(wf_result)

        return results

    def get_summary(self) -> dict:
        """获取验证汇总"""
        if not self._results:
            return {}

        # 计算测试期平均指标
        test_returns = [r.test_result.annual_return for r in self._results]
        test_drawdowns = [r.test_result.max_drawdown for r in self._results]
        test_sharpes = [r.test_result.sharpe_ratio for r in self._results]
        test_win_rates = [r.test_result.win_rate for r in self._results]

        overfit_count = sum(1 for r in self._results if r.is_overfit)

        return {
            'total_periods': len(self._results),
            'overfit_periods': overfit_count,
            'overfit_ratio': round(overfit_count / len(self._results), 2),
            'avg_test_return': round(np.mean(test_returns), 4),
            'std_test_return': round(np.std(test_returns), 4),
            'avg_test_drawdown': round(np.mean(test_drawdowns), 4),
            'avg_test_sharpe': round(np.mean(test_sharpes), 2),
            'avg_test_win_rate': round(np.mean(test_win_rates), 4),
            'best_period': max(self._results, key=lambda r: r.test_result.annual_return).test_start,
            'worst_period': min(self._results, key=lambda r: r.test_result.annual_return).test_start,
        }

    def get_yearly_performance(self) -> dict:
        """获取分年度表现"""
        yearly = {}

        for r in self._results:
            year = r.test_start[:4]
            if year not in yearly:
                yearly[year] = {
                    'returns': [],
                    'drawdowns': [],
                    'sharpes': [],
                }
            yearly[year]['returns'].append(r.test_result.annual_return)
            yearly[year]['drawdowns'].append(r.test_result.max_drawdown)
            yearly[year]['sharpes'].append(r.test_result.sharpe_ratio)

        result = {}
        for year, data in yearly.items():
            result[year] = {
                'annual_return': round(np.mean(data['returns']), 4),
                'max_drawdown': round(max(data['drawdowns']), 4),
                'sharpe_ratio': round(np.mean(data['sharpes']), 2),
                'periods': len(data['returns']),
            }

        return result

    def generate_report(self) -> str:
        """生成验证报告"""
        summary = self.get_summary()
        yearly = self.get_yearly_performance()

        report = []
        report.append("=" * 60)
        report.append("Walk-Forward 验证报告")
        report.append("=" * 60)
        report.append("")
        report.append("【总体统计】")
        report.append(f"  验证周期数: {summary.get('total_periods', 0)}")
        report.append(f"  过拟合周期数: {summary.get('overfit_periods', 0)} ({summary.get('overfit_ratio', 0)*100:.0f}%)")
        report.append(f"  平均年化收益: {summary.get('avg_test_return', 0)*100:.2f}%")
        report.append(f"  收益标准差: {summary.get('std_test_return', 0)*100:.2f}%")
        report.append(f"  平均最大回撤: {summary.get('avg_test_drawdown', 0)*100:.2f}%")
        report.append(f"  平均夏普比率: {summary.get('avg_test_sharpe', 0):.2f}")
        report.append(f"  平均胜率: {summary.get('avg_test_win_rate', 0)*100:.1f}%")
        report.append("")
        report.append("【分年度表现】")

        for year in sorted(yearly.keys()):
            data = yearly[year]
            report.append(f"  {year}: 年化收益 {data['annual_return']*100:.2f}%, "
                         f"最大回撤 {data['max_drawdown']*100:.2f}%, "
                         f"夏普 {data['sharpe_ratio']:.2f}")

        report.append("")
        report.append("=" * 60)

        return "\n".join(report)

    @property
    def results(self) -> list[WalkForwardResult]:
        return self._results.copy()
