import time
import numpy as np
import pandas as pd
from datetime import date, datetime
from typing import Optional

from app.models.backtest import (
    BacktestResult, PerformanceMetrics, TradeRecord, MonthlyReturn
)
from app.strategies.base import Strategy


def _calculate_metrics(equity: list[float]) -> PerformanceMetrics:
    """计算绩效指标"""
    arr = np.array(equity)
    returns = np.diff(arr) / arr[:-1]

    if len(returns) == 0:
        return PerformanceMetrics()

    total_ret = (arr[-1] / arr[0]) - 1 if arr[0] > 0 else 0.0

    # 年化收益率 (假设日频数据, 250 交易日/年)
    n_years = len(returns) / 250
    annual_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else total_ret

    # 最大回撤
    peak = np.maximum.accumulate(arr)
    drawdowns = (arr - peak) / peak
    max_dd = float(np.min(drawdowns))

    # Sharpe
    std = float(np.std(returns, ddof=1))
    sharpe = float(annual_ret / std * np.sqrt(250)) if std > 0 else 0.0

    # Sortino
    downside = returns[returns < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = float(annual_ret / downside_std * np.sqrt(250)) if downside_std > 0 else 0.0

    # Calmar
    calmar = float(annual_ret / abs(max_dd)) if max_dd != 0 else 0.0

    return PerformanceMetrics(
        total_return_pct=round(total_ret * 100, 2),
        annual_return_pct=round(annual_ret * 100, 2),
        max_drawdown_pct=round(max_dd * 100, 2),
        sharpe_ratio=round(sharpe, 3),
        sortino_ratio=round(sortino, 3),
        calmar_ratio=round(calmar, 3),
    )


class BacktestEngine:
    """回测引擎 - 向量化计算"""

    def __init__(self, commission_pct: float = 0.001, slippage_pct: float = 0.001):
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct

    def run(self, strategy: Strategy, data: pd.DataFrame) -> BacktestResult:
        """运行回测"""
        start_time = time.time()

        # 排序
        data = data.sort_values(['code', 'date']).reset_index(drop=True)
        dates = sorted(data['date'].unique())
        start_date = dates[0] if isinstance(dates[0], date) else date.fromisoformat(str(dates[0]))
        end_date = dates[-1] if isinstance(dates[-1], date) else date.fromisoformat(str(dates[-1]))

        # 初始化策略
        strategy.on_init(data)

        # 逐日执行
        equity = [1.0]
        holdings: dict[str, dict] = {}  # code -> {buy_price, volume}
        trades: list[TradeRecord] = []
        cash = 1.0

        for i, current_date in enumerate(dates):
            day_data = data[data['date'] == current_date]

            # 标记持仓市值
            position_value = 0.0
            to_sell = []
            for code, holding in holdings.items():
                row = day_data[day_data['code'] == code]
                if row.empty:
                    to_sell.append(code)
                    continue
                current_price = float(row.iloc[0]['price'])
                position_value += current_price * holding['volume']

            for code in to_sell:
                del holdings[code]

            # 生成信号
            signals = strategy.on_data(data, i) or []

            # 执行卖出（先卖后买）
            sell_list = [s for s in signals if s['action'] == 'sell']
            for sig in sell_list:
                if sig['code'] in holdings:
                    h = holdings.pop(sig['code'])
                    sell_price = sig['price'] * (1 - self.slippage_pct)
                    sell_value = sell_price * h['volume']
                    fee = sell_value * self.commission_pct
                    profit = sell_value - fee - (h['buy_price'] * h['volume'])

                    cash += sell_value - fee

                    trades.append(TradeRecord(
                        code=sig['code'],
                        name=str(row.iloc[0].get('name', '')) if len(day_data) > 0 else '',
                        buy_date=h['buy_date'],
                        sell_date=current_date,
                        buy_price=h['buy_price'],
                        sell_price=sell_price,
                        volume=h['volume'],
                        profit_pct=round((sell_price - h['buy_price']) / h['buy_price'] * 100, 2),
                        profit_amount=round(profit, 2),
                        hold_days=(current_date - h['buy_date']).days,
                        reason=sig.get('reason', ''),
                    ))

            # 执行买入
            buy_list = [s for s in signals if s['action'] == 'buy']
            for sig in buy_list:
                if sig['code'] in holdings:
                    continue

                buy_price = sig['price'] * (1 + self.slippage_pct)

                # 等权分配资金
                n_to_buy = len(buy_list)
                if n_to_buy == 0:
                    continue
                alloc = cash / n_to_buy if n_to_buy > 0 else 0
                volume = max(1, int(alloc / buy_price))
                cost = buy_price * volume
                fee = cost * self.commission_pct

                if cost + fee <= cash:
                    cash -= cost + fee
                    holdings[sig['code']] = {
                        'buy_price': buy_price,
                        'volume': volume,
                        'buy_date': current_date,
                    }

            # 总资产
            total = cash + sum(h['buy_price'] * h['volume'] for h in holdings.values())
            # 用最新价重估
            reval = cash
            for code, h in holdings.items():
                row = day_data[day_data['code'] == code]
                if not row.empty:
                    reval += float(row.iloc[0]['price']) * h['volume']
                else:
                    reval += h['buy_price'] * h['volume']
            equity.append(reval)

        # 计算指标
        metrics = _calculate_metrics(equity)
        metrics.total_trades = len(trades)

        if trades:
            wins = [t for t in trades if t.profit_pct and t.profit_pct > 0]
            metrics.win_rate = round(len(wins) / len(trades) * 100, 2)
            avg_profit = np.mean([t.profit_pct for t in trades if t.profit_pct is not None])
            avg_loss = np.mean([t.profit_pct for t in trades if t.profit_pct is not None and t.profit_pct <= 0])
            metrics.profit_loss_ratio = round(abs(avg_profit / avg_loss), 2) if avg_loss != 0 else 0.0
            metrics.avg_hold_days = round(float(np.mean([t.hold_days for t in trades if t.hold_days])), 1)

        # 净值曲线
        equity_curve = []
        for j, val in enumerate(equity):
            if j > 0:
                d = dates[j - 1]
                equity_curve.append({
                    'date': d.isoformat() if isinstance(d, date) else str(d),
                    'value': round(val, 6),
                })

        return BacktestResult(
            strategy_name=strategy.name,
            strategy_params=strategy._params,
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )
