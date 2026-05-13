import time
import numpy as np
import pandas as pd
from datetime import date, datetime
from itertools import product
from typing import Optional

from app.models.backtest import (
    BacktestResult, PerformanceMetrics, TradeRecord, MonthlyReturn,
    BacktestConfig, OptimizationConfig, OptimizationResult, OptimizationResultItem
)
from app.strategies.base import Strategy


def _calculate_metrics(equity: list[float], risk_free_rate: float = 0.02) -> PerformanceMetrics:
    """计算绩效指标，支持可配置无风险利率"""
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

    # Sharpe (使用可配置的无风险利率)
    std = float(np.std(returns, ddof=1))
    excess_ret = annual_ret - risk_free_rate
    sharpe = float(excess_ret / std * np.sqrt(250)) if std > 0 else 0.0

    # Sortino
    downside = returns[returns < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = float(excess_ret / downside_std * np.sqrt(250)) if downside_std > 0 else 0.0

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


def _build_result_item(params: dict, metrics: PerformanceMetrics) -> OptimizationResultItem:
    """将 PerformanceMetrics 展平为 OptimizationResultItem"""
    return OptimizationResultItem(
        params=params,
        total_return_pct=metrics.total_return_pct,
        annual_return_pct=metrics.annual_return_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        calmar_ratio=metrics.calmar_ratio,
        win_rate=metrics.win_rate,
        total_trades=metrics.total_trades,
    )


class BacktestEngine:
    """回测引擎 - 向量化计算，支持可配置交易成本和参数优化"""

    def __init__(self, config: Optional[BacktestConfig] = None):
        cfg = config or BacktestConfig()
        self.commission_pct = cfg.commission_pct
        self.slippage_pct = cfg.slippage_pct
        self.min_commission = cfg.min_commission
        self.risk_free_rate = cfg.risk_free_rate

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
                    fee = max(sell_value * self.commission_pct, self.min_commission)
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
                fee = max(cost * self.commission_pct, self.min_commission)

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
        metrics = _calculate_metrics(equity, self.risk_free_rate)
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

    def run_optimization(
        self,
        strategy_cls: type[Strategy],
        data: pd.DataFrame,
        optimization_config: OptimizationConfig,
    ) -> OptimizationResult:
        """参数优化 - 网格搜索"""
        start_time = time.time()

        # 生成参数组合网格
        ranges = optimization_config.param_ranges
        if not ranges:
            raise ValueError("优化参数范围不能为空")

        # 每个参数的取值范围
        param_values = {}
        for r in ranges:
            values = []
            v = r.min_val
            while v <= r.max_val + 1e-9:
                values.append(v)
                v += r.step
            param_values[r.name] = values

        # 生成所有组合
        keys = list(param_values.keys())
        value_lists = [param_values[k] for k in keys]
        all_combinations = list(product(*value_lists))

        # 限制迭代次数
        total_combos = len(all_combinations)
        max_iter = min(optimization_config.max_iterations, total_combos)
        if max_iter < total_combos:
            # 随机采样
            indices = np.random.choice(total_combos, size=max_iter, replace=False)
            all_combinations = [all_combinations[i] for i in indices]

        results: list[OptimizationResultItem] = []
        metric_key = optimization_config.optimize_metric

        for combo in all_combinations:
            params = dict(zip(keys, [float(v) for v in combo]))

            # 实例化策略
            strategy = strategy_cls(**params)

            # 运行回测
            result = self.run(strategy, data)
            metrics = result.metrics

            # 获取优化目标值
            metric_value = getattr(metrics, metric_key, 0.0)

            results.append(_build_result_item(params, metrics))

        # 按优化目标排序
        results.sort(key=lambda x: getattr(x, metric_key, 0.0), reverse=True)
        top_results = results[:optimization_config.top_n]

        # 最优参数
        best_item = top_results[0] if top_results else None

        opt_result = OptimizationResult(
            strategy_name=strategy_cls.name,
            optimize_metric=optimization_config.optimize_metric,
            total_combinations=total_combos,
            best_params=best_item.params if best_item else {},
            top_results=top_results,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )

        if best_item:
            opt_result.best_metrics = PerformanceMetrics(
                total_return_pct=best_item.total_return_pct,
                annual_return_pct=best_item.annual_return_pct,
                max_drawdown_pct=best_item.max_drawdown_pct,
                sharpe_ratio=best_item.sharpe_ratio,
                sortino_ratio=best_item.sortino_ratio,
                calmar_ratio=best_item.calmar_ratio,
                win_rate=best_item.win_rate,
                total_trades=best_item.total_trades,
            )

        return opt_result
