import os
import time
import logging
import concurrent.futures
import numpy as np
import pandas as pd
from datetime import date, datetime
from itertools import product
from typing import Optional

logger = logging.getLogger(__name__)

from pydantic import BaseModel
from app.models.backtest import (
    BacktestResult, PerformanceMetrics, TradeRecord, MonthlyReturn,
    BacktestConfig, OptimizationConfig, OptimizationResult, OptimizationResultItem
)
from app.strategies.base import Strategy


class Portfolio:
    """模拟投资组合 - 封装持仓、现金和交易记录管理"""

    def __init__(self, cash: float = 1.0):
        self.cash = cash
        self.holdings: dict[str, dict] = {}  # code -> {buy_price, volume, buy_date}
        self.trades: list[TradeRecord] = []

    def remove_stale(self, code_row_map: dict) -> None:
        """移除当日无行情数据的持仓"""
        to_remove = [
            code for code in self.holdings
            if code not in code_row_map
        ]
        for code in to_remove:
            del self.holdings[code]

    def sell(self, code: str, price: float, slippage: float,
             commission: float, min_commission: float,
             current_date, code_row_map: dict,
             reason: str = '') -> None:
        """卖出持仓"""
        if code not in self.holdings:
            return
        h = self.holdings.pop(code)
        sell_price = price * (1 - slippage)
        sell_value = sell_price * h['volume']
        fee = max(sell_value * commission, min_commission)
        profit = sell_value - fee - (h['buy_price'] * h['volume'])
        self.cash += sell_value - fee

        sell_row = code_row_map.get(code)
        name = str(sell_row.get('name', '')) if sell_row is not None else ''

        self.trades.append(TradeRecord(
            code=code, name=name,
            buy_date=h['buy_date'], sell_date=current_date,
            buy_price=h['buy_price'], sell_price=sell_price,
            volume=h['volume'],
            profit_pct=round((sell_price - h['buy_price']) / h['buy_price'] * 100, 2),
            profit_amount=round(profit, 2),
            hold_days=(current_date - h['buy_date']).days,
            reason=reason,
        ))

    def buy(self, code: str, price: float, slippage: float,
            commission: float, min_commission: float,
            current_date, alloc: float) -> bool:
        """买入标的，等权分配资金"""
        if code in self.holdings:
            return False
        buy_price = price * (1 + slippage)
        volume = max(1, int(alloc / buy_price))
        cost = buy_price * volume
        fee = max(cost * commission, min_commission)

        if cost + fee > self.cash:
            return False

        self.cash -= cost + fee
        self.holdings[code] = {
            'buy_price': buy_price,
            'volume': volume,
            'buy_date': current_date,
        }
        return True

    def market_value(self, code_row_map: dict) -> float:
        """计算组合总市值（现金 + 持仓市值）"""
        val = self.cash
        for code, h in self.holdings.items():
            row = code_row_map.get(code)
            if row is not None:
                val += float(row['price']) * h['volume']
            else:
                val += h['buy_price'] * h['volume']
        return val


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


def _run_single_backtest(
    strategy_cls: type,
    params: dict,
    data: pd.DataFrame,
    commission_pct: float,
    slippage_pct: float,
    min_commission: float,
    risk_free_rate: float,
) -> OptimizationResultItem:
    """在子进程中运行单次回测 - 所有参数均可 pickle 序列化。

    ProcessPoolExecutor 要求提交的函数和参数均可序列化，
    因此传递标量配置值而非 BacktestEngine 实例。
    每个子进程会创建独立的 BacktestEngine，避免共享状态。
    """
    cfg = BacktestConfig(
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        min_commission=min_commission,
        risk_free_rate=risk_free_rate,
    )
    engine = BacktestEngine(config=cfg)
    strategy = strategy_cls(**params)
    result = engine.run(strategy, data)
    return _build_result_item(params, result.metrics)


class BacktestEngine:
    """回测引擎 - 向量化计算，支持可配置交易成本和参数优化"""

    def __init__(self, config: Optional[BacktestConfig] = None):
        cfg = config or BacktestConfig()
        self.commission_pct = cfg.commission_pct
        self.slippage_pct = cfg.slippage_pct
        self.min_commission = cfg.min_commission
        self.risk_free_rate = cfg.risk_free_rate

    def run(self, strategy: Strategy, data: pd.DataFrame) -> BacktestResult:
        """运行回测 - 使用 Portfolio 类管理持仓，与 SignalEngine 共享一致的信号处理流程"""
        start_time = time.time()

        # 排序 & 预构建日期索引
        data = data.sort_values(['code', 'date']).reset_index(drop=True)
        dates = sorted(data['date'].unique())
        start_date = dates[0] if isinstance(dates[0], date) else date.fromisoformat(str(dates[0]))
        end_date = dates[-1] if isinstance(dates[-1], date) else date.fromisoformat(str(dates[-1]))
        date_data_map = {d: group for d, group in data.groupby('date')}

        # 初始化策略 & 投资组合
        strategy.on_init(data)
        portfolio = Portfolio(cash=1.0)
        equity = [1.0]

        # 逐日执行
        for i, current_date in enumerate(dates):
            day_data = date_data_map[current_date]

            # 预构建 code -> row 映射，避免每次 O(M) 行过滤
            code_row_map = {code: group.iloc[0] for code, group in day_data.groupby('code')}

            # 1. 移除无行情的持仓
            portfolio.remove_stale(code_row_map)

            # 2. 生成信号（传入 day_data 而非完整 data，避免每日拷贝全量 DataFrame）
            signals = strategy.on_data(day_data, i) or []

            # 3. 先卖后买
            for sig in [s for s in signals if s['action'] == 'sell']:
                portfolio.sell(
                    sig['code'], sig['price'],
                    self.slippage_pct, self.commission_pct, self.min_commission,
                    current_date, code_row_map,
                    reason=sig.get('reason', ''),
                )

            buy_signals = [s for s in signals if s['action'] == 'buy']
            n_to_buy = len(buy_signals)
            for sig in buy_signals:
                if sig['code'] in portfolio.holdings:
                    n_to_buy -= 1
                    continue
                alloc = portfolio.cash / n_to_buy
                portfolio.buy(
                    sig['code'], sig['price'],
                    self.slippage_pct, self.commission_pct, self.min_commission,
                    current_date, alloc,
                )
                n_to_buy -= 1

            # 4. 记录净值
            equity.append(portfolio.market_value(code_row_map))

        # 计算指标
        metrics = _calculate_metrics(equity, self.risk_free_rate)
        metrics.total_trades = len(portfolio.trades)

        if portfolio.trades:
            wins = [t for t in portfolio.trades if t.profit_pct and t.profit_pct > 0]
            metrics.win_rate = round(len(wins) / len(portfolio.trades) * 100, 2)
            profits = [t.profit_pct for t in portfolio.trades if t.profit_pct is not None and t.profit_pct > 0]
            losses = [t.profit_pct for t in portfolio.trades if t.profit_pct is not None and t.profit_pct <= 0]
            avg_profit = float(np.mean(profits)) if profits else 0.0
            avg_loss = float(np.mean(losses)) if losses else 0.0
            metrics.profit_loss_ratio = round(abs(avg_profit / avg_loss), 2) if avg_loss != 0 else 0.0
            hold_days = [t.hold_days for t in portfolio.trades if t.hold_days]
            metrics.avg_hold_days = round(float(np.mean(hold_days)), 1) if hold_days else 0.0

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
            trades=portfolio.trades,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )

    def run_optimization(
        self,
        strategy_cls: type[Strategy],
        data: pd.DataFrame,
        optimization_config: OptimizationConfig,
    ) -> OptimizationResult:
        """参数优化 - 网格搜索，支持并行执行和进度日志"""
        start_time = time.time()

        # 生成参数组合网格
        ranges = optimization_config.param_ranges
        if not ranges:
            raise ValueError("优化参数范围不能为空")

        # 每个参数的取值范围
        param_values = {}
        for r in ranges:
            values = []
            if r.step <= 0:
                raise ValueError(f"Parameter step must be positive, got {r.step}")
            n_steps = int(round((r.max_val - r.min_val) / r.step)) + 1
            values = [round(r.min_val + i * r.step, 10) for i in range(n_steps)]
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
        n_combos = len(all_combinations)

        # 确定进度日志间隔（每 10% 至少记录一次）
        log_interval = max(1, n_combos // 10)

        parallel_workers = optimization_config.parallel_workers
        use_parallel = parallel_workers > 1

        if use_parallel:
            # 并行模式：使用 ProcessPoolExecutor 实现真正的 CPU 并行
            # 注意：每个子进程拥有独立的 data 副本，内存随 worker 数量增加
            # 在 Linux 上，fork 启动方式通过 copy-on-write 机制共享内存页，
            # 子进程在修改数据前不会真正复制；macOS 默认使用 spawn 方式，
            # 每个子进程都会完整序列化 data，内存开销 = data大小 × worker数
            actual_workers = min(parallel_workers, os.cpu_count() or 2, n_combos)

            # 内存估算与警告
            data_mb = data.memory_usage(deep=True).sum() / 1024 / 1024
            total_mb = data_mb * actual_workers
            if total_mb > 1024:  # > 1GB
                logger.warning(
                    f"并行优化将使用约 {total_mb:.0f}MB 内存 "
                    f"({data_mb:.0f}MB 数据 × {actual_workers} 工作进程)。"
                    f"如内存有限，建议减少 parallel_workers 或切换为顺序模式。"
                )

            logger.info(
                f"并行优化启动: {n_combos} 组合, {actual_workers} 工作进程, "
                f"CPU 核心数={os.cpu_count()}, 数据约 {data_mb:.0f}MB, "
                f"预计内存增加约 {total_mb:.0f}MB"
            )
            with concurrent.futures.ProcessPoolExecutor(max_workers=actual_workers) as executor:
                futures = {}
                for idx, combo in enumerate(all_combinations):
                    params = dict(zip(keys, [float(v) for v in combo]))
                    future = executor.submit(
                        _run_single_backtest,
                        strategy_cls, params, data,
                        self.commission_pct, self.slippage_pct,
                        self.min_commission, self.risk_free_rate,
                    )
                    futures[future] = idx

                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    try:
                        item = future.result()
                        results.append(item)
                    except Exception as e:
                        logger.warning(f"并行优化运行失败: {e}")
                    completed += 1
                    if completed % log_interval == 0 or completed == n_combos:
                        logger.info(
                            f"并行优化进度: {completed}/{n_combos} "
                            f"({completed * 100 // n_combos}%)"
                        )
        else:
            # 顺序模式：默认行为，零额外内存开销
            logger.info(f"顺序优化启动: {n_combos} 组合")
            for idx, combo in enumerate(all_combinations):
                params = dict(zip(keys, [float(v) for v in combo]))

                # 实例化策略
                strategy = strategy_cls(**params)

                # 运行回测
                result = self.run(strategy, data)
                metrics = result.metrics

                results.append(_build_result_item(params, metrics))

                # 每 10% 记录一次进度
                if (idx + 1) % log_interval == 0 or (idx + 1) == n_combos:
                    logger.info(
                        f"优化进度: {idx + 1}/{n_combos} "
                        f"({(idx + 1) * 100 // n_combos}%)"
                    )

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

        logger.info(
            f"优化完成: {n_combos} 组合, 耗时 {opt_result.execution_time_ms}ms, "
            f"模式={'并行' if use_parallel else '顺序'}"
        )
        return opt_result


class WalkForwardResult(BaseModel):
    """Walk-Forward验证结果"""
    total_windows: int = 0
    in_sample_metrics: list[dict] = []  # 样本内指标
    out_sample_metrics: list[dict] = []  # 样本外指标
    avg_in_sample_return: float = 0.0
    avg_out_sample_return: float = 0.0
    overfit_ratio: float = 0.0  # 样本内/样本外比值，越大过拟合越严重
    best_params_stability: float = 0.0  # 参数稳定性得分
    execution_time_ms: int = 0


class WalkForwardValidator:
    """Walk-Forward验证器 - 防止过拟合的样本外验证

    核心逻辑：
    1. 将时间序列分为多个滚动窗口
    2. 每个窗口：训练期优化参数 → 测试期验证
    3. 统计样本内vs样本外性能差异
    4. overfit_ratio = 样本内收益 / 样本外收益
    """

    def __init__(
        self,
        train_window: int = 120,  # 训练期天数（约半年）
        test_window: int = 60,    # 测试期天数（约一季度）
        step: int = 60,           # 滚动步长
    ):
        self.train_window = train_window
        self.test_window = test_window
        self.step = step

    def validate(
        self,
        strategy_cls: type[Strategy],
        data: pd.DataFrame,
        optimization_config: OptimizationConfig,
        engine: Optional[BacktestEngine] = None,
    ) -> WalkForwardResult:
        """执行Walk-Forward验证"""
        start_time = time.time()
        engine = engine or BacktestEngine()

        # 排序数据
        data = data.sort_values(['code', 'date']).reset_index(drop=True)
        dates = sorted(data['date'].unique())
        n_days = len(dates)

        # 计算窗口数量
        min_days = self.train_window + self.test_window
        if n_days < min_days:
            logger.warning(
                f"数据不足: 需要至少{min_days}天，实际{n_days}天"
            )
            return WalkForwardResult(total_windows=0)

        # 生成窗口
        windows = []
        start = 0
        while start + min_days <= n_days:
            train_end = start + self.train_window
            test_end = train_end + self.test_window
            if test_end > n_days:
                break
            windows.append({
                'train_start': start,
                'train_end': train_end,
                'test_start': train_end,
                'test_end': test_end,
            })
            start += self.step

        if not windows:
            logger.warning("无法生成有效窗口")
            return WalkForwardResult(total_windows=0)

        in_sample_metrics = []
        out_sample_metrics = []
        all_best_params = []

        for i, win in enumerate(windows):
            # 分割数据
            train_dates = dates[win['train_start']:win['train_end']]
            test_dates = dates[win['test_start']:win['test_end']]

            train_data = data[data['date'].isin(train_dates)]
            test_data = data[data['date'].isin(test_dates)]

            # 样本内优化
            opt_result = engine.run_optimization(
                strategy_cls, train_data, optimization_config
            )

            best_params = opt_result.best_params
            all_best_params.append(best_params)

            # 记录样本内指标
            in_sample_metrics.append({
                'window': i + 1,
                'total_return_pct': opt_result.best_metrics.total_return_pct if opt_result.best_metrics else 0,
                'sharpe_ratio': opt_result.best_metrics.sharpe_ratio if opt_result.best_metrics else 0,
                'max_drawdown_pct': opt_result.best_metrics.max_drawdown_pct if opt_result.best_metrics else 0,
            })

            # 样本外验证
            if best_params:
                test_strategy = strategy_cls(**best_params)
                test_result = engine.run(test_strategy, test_data)

                out_sample_metrics.append({
                    'window': i + 1,
                    'total_return_pct': test_result.metrics.total_return_pct,
                    'sharpe_ratio': test_result.metrics.sharpe_ratio,
                    'max_drawdown_pct': test_result.metrics.max_drawdown_pct,
                })
            else:
                out_sample_metrics.append({
                    'window': i + 1,
                    'total_return_pct': 0,
                    'sharpe_ratio': 0,
                    'max_drawdown_pct': 0,
                })

        # 计算统计指标
        avg_in_return = np.mean([m['total_return_pct'] for m in in_sample_metrics])
        avg_out_return = np.mean([m['total_return_pct'] for m in out_sample_metrics])

        # 过拟合比率
        overfit_ratio = 0.0
        if avg_out_return != 0:
            overfit_ratio = round(avg_in_return / avg_out_return, 3)
        elif avg_in_return > 0:
            overfit_ratio = float('inf')  # 样本内有收益但样本外为0

        # 参数稳定性得分（基于最优参数的变化程度）
        stability_score = self._calculate_stability(all_best_params)

        return WalkForwardResult(
            total_windows=len(windows),
            in_sample_metrics=in_sample_metrics,
            out_sample_metrics=out_sample_metrics,
            avg_in_sample_return=round(avg_in_return, 2),
            avg_out_sample_return=round(avg_out_return, 2),
            overfit_ratio=overfit_ratio,
            best_params_stability=stability_score,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )

    def _calculate_stability(self, all_params: list[dict]) -> float:
        """计算参数稳定性得分

        基于参数值的标准差，得分越高表示参数越稳定
        """
        if not all_params or len(all_params) < 2:
            return 1.0

        # 收集所有参数值
        param_values = {}
        for params in all_params:
            for k, v in params.items():
                if k not in param_values:
                    param_values[k] = []
                param_values[k].append(v)

        # 计算每个参数的变异系数
        stability_scores = []
        for param_name, values in param_values.items():
            if len(values) < 2:
                continue
            mean_val = np.mean(values)
            if mean_val == 0:
                continue
            std_val = np.std(values)
            cv = std_val / abs(mean_val)  # 变异系数
            # 变异系数越小，稳定性越高
            param_stability = max(0, 1 - cv)
            stability_scores.append(param_stability)

        return round(float(np.mean(stability_scores)), 3) if stability_scores else 1.0
