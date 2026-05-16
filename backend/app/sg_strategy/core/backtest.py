"""松岗量化可转债策略 V3.0 Walk-forward回测引擎

Walk-Forward验证框架:
- 训练窗口: 12个月(滚动)
- 测试窗口: 3个月(样本外)
- 滚动步长: 3个月
- 全周期: 2018年1月 - 至今
- 交易成本: 全额扣除(三层成本模型)
- 基准: 中证转债指数(000832)
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple, Callable
import pandas as pd
import numpy as np
import logging

from app.sg_strategy.core.types import (
    Portfolio, Position, SevenDimScore, TimingSignal, TradeSignal,
    TransactionCost, DailyReport,
)
from app.sg_strategy.config.settings import params
from app.sg_strategy.core.scoring import SevenDimScoringEngine
from app.sg_strategy.core.whitelist import WhitelistManager
from app.sg_strategy.core.timing import TimingEngine, MarketData
from app.sg_strategy.core.filters import VetoFilter
from app.sg_strategy.core.cost import TransactionCostModel

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """回测配置"""
    start_date: date
    end_date: date
    initial_capital: float = 10000.0  # 万元
    train_window_months: int = 12
    test_window_months: int = 3
    rolling_step_months: int = 3
    commission_rate: float = 0.0001
    slippage_rate: float = 0.001
    benchmark: str = "000832.CSI"  # 中证转债指数


@dataclass
class BacktestResult:
    """回测结果"""
    period_start: date
    period_end: date
    is_train: bool
    returns: float  # 收益率
    benchmark_returns: float  # 基准收益率
    excess_returns: float  # 超额收益
    max_drawdown: float  # 最大回撤
    sharpe_ratio: float  # 夏普比率
    win_rate: float  # 胜率
    turnover_rate: float  # 换手率
    total_cost: float  # 总成本
    trade_count: int  # 交易次数

    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "is_train": self.is_train,
            "returns": round(self.returns * 100, 2),
            "benchmark_returns": round(self.benchmark_returns * 100, 2),
            "excess_returns": round(self.excess_returns * 100, 2),
            "max_drawdown": round(self.max_drawdown * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "win_rate": round(self.win_rate * 100, 1),
            "turnover_rate": round(self.turnover_rate * 100, 2),
            "total_cost": round(self.total_cost, 2),
            "trade_count": self.trade_count,
        }


@dataclass
class WalkForwardResult:
    """Walk-Forward结果"""
    config: BacktestConfig
    periods: List[BacktestResult] = field(default_factory=list)
    total_returns: float = 0.0
    total_benchmark_returns: float = 0.0
    total_excess_returns: float = 0.0
    avg_sharpe: float = 0.0
    avg_max_drawdown: float = 0.0
    avg_win_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "config": {
                "start_date": self.config.start_date.isoformat(),
                "end_date": self.config.end_date.isoformat(),
                "initial_capital": self.config.initial_capital,
            },
            "periods": [p.to_dict() for p in self.periods],
            "summary": {
                "total_returns": round(self.total_returns * 100, 2),
                "total_benchmark_returns": round(self.total_benchmark_returns * 100, 2),
                "total_excess_returns": round(self.total_excess_returns * 100, 2),
                "avg_sharpe": round(self.avg_sharpe, 2),
                "avg_max_drawdown": round(self.avg_max_drawdown * 100, 2),
                "avg_win_rate": round(self.avg_win_rate * 100, 1),
            },
        }


class BacktestEngine:
    """回测引擎"""

    def __init__(self, config: BacktestConfig):
        """初始化

        Args:
            config: 回测配置
        """
        self.config = config
        self.cost_model = TransactionCostModel(config.initial_capital)

        # 历史数据
        self._daily_values: List[Dict] = []
        self._trades: List[Dict] = []
        self._positions_history: List[Dict] = []

    def run_backtest(
        self,
        cb_data: pd.DataFrame,
        stock_data: Optional[pd.DataFrame] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
        strategy_func: Optional[Callable] = None,
    ) -> BacktestResult:
        """运行单次回测

        Args:
            cb_data: 可转债数据
            stock_data: 正股数据
            benchmark_data: 基准数据
            strategy_func: 策略函数

        Returns:
            BacktestResult: 回测结果
        """
        # 初始化组合
        portfolio = Portfolio(
            date=self.config.start_date,
            aum=self.config.initial_capital,
            cash=self.config.initial_capital,
        )

        # 按日期迭代
        dates = sorted(cb_data["date"].unique())
        daily_values = []

        for i, current_date in enumerate(dates):
            if current_date < self.config.start_date or current_date > self.config.end_date:
                continue

            # 获取当日数据
            day_cb = cb_data[cb_data["date"] == current_date]

            # 执行策略
            if strategy_func:
                signals = strategy_func(portfolio, day_cb, current_date)
            else:
                signals = self._default_strategy(portfolio, day_cb, current_date)

            # 执行交易
            portfolio = self._execute_signals(portfolio, signals, day_cb, current_date)

            # 更新持仓市值
            portfolio = self._update_portfolio(portfolio, day_cb, current_date)

            # 记录每日净值
            daily_values.append({
                "date": current_date,
                "value": portfolio.aum,
                "cash": portfolio.cash,
                "positions": len(portfolio.positions),
            })

        self._daily_values = daily_values

        # 计算绩效
        return self._calculate_performance(daily_values, benchmark_data)

    def _default_strategy(
        self,
        portfolio: Portfolio,
        day_data: pd.DataFrame,
        current_date: date,
    ) -> List[TradeSignal]:
        """默认策略(简单双低)

        Args:
            portfolio: 当前组合
            day_data: 当日数据
            current_date: 当前日期

        Returns:
            交易信号列表
        """
        signals = []

        if day_data.empty:
            return signals

        # 计算双低值
        day_data = day_data.copy()
        day_data["dual_low"] = day_data["close"] + day_data.get("premium_ratio", 30)

        # 过滤
        filtered = day_data[
            (day_data["close"] > 80) &
            (day_data["close"] < 130) &
            (day_data.get("premium_ratio", 30) < 50)
        ]

        if filtered.empty:
            return signals

        # 选择双低最小的N只
        selected = filtered.nsmallest(10, "dual_low")
        selected_codes = set(selected["code"].tolist())

        # 卖出
        for code in list(portfolio.positions.keys()):
            if code not in selected_codes:
                pos = portfolio.positions[code]
                signals.append(TradeSignal(
                    signal_id=f"sell_{code}",
                    cb_code=code,
                    cb_name=pos.cb_name,
                    action="sell",
                    signal_type="rebalance",
                    price=pos.current_price,
                    quantity=pos.quantity,
                    reason="调仓卖出",
                ))

        # 买入
        held_codes = set(portfolio.positions.keys()) - set(s.cb_code for s in signals if s.action == "sell")
        for _, row in selected.iterrows():
            if row["code"] not in held_codes:
                signals.append(TradeSignal(
                    signal_id=f"buy_{row['code']}",
                    cb_code=row["code"],
                    cb_name=row.get("name", ""),
                    action="buy",
                    signal_type="rebalance",
                    price=row["close"],
                    quantity=100,
                    reason=f"双低{row['dual_low']:.1f}",
                ))

        return signals

    def _execute_signals(
        self,
        portfolio: Portfolio,
        signals: List[TradeSignal],
        day_data: pd.DataFrame,
        current_date: date,
    ) -> Portfolio:
        """执行交易信号

        Args:
            portfolio: 当前组合
            signals: 交易信号
            day_data: 当日数据
            current_date: 当前日期

        Returns:
            更新后的组合
        """
        for signal in signals:
            if signal.action == "buy":
                # 计算成本
                amount = signal.price * signal.quantity
                cost = self.cost_model.calculate_cost(
                    signal.price, signal.quantity,
                    day_data[day_data["code"] == signal.cb_code]["volume"].sum() * 100 if not day_data.empty else 1000
                )

                # 检查资金
                if portfolio.cash >= amount + cost.total:
                    portfolio.cash -= (amount + cost.total)
                    portfolio.positions[signal.cb_code] = Position(
                        cb_code=signal.cb_code,
                        cb_name=signal.cb_name,
                        quantity=signal.quantity,
                        avg_cost=signal.price,
                        current_price=signal.price,
                        market_value=amount,
                        cost_basis=amount,
                        buy_date=current_date,
                        buy_price=signal.price,
                    )
                    self._trades.append({
                        "date": current_date,
                        "code": signal.cb_code,
                        "action": "buy",
                        "price": signal.price,
                        "quantity": signal.quantity,
                        "cost": cost.total,
                    })

            elif signal.action == "sell":
                if signal.cb_code in portfolio.positions:
                    pos = portfolio.positions[signal.cb_code]
                    amount = signal.price * signal.quantity
                    cost = self.cost_model.calculate_cost(
                        signal.price, signal.quantity,
                        day_data[day_data["code"] == signal.cb_code]["volume"].sum() * 100 if not day_data.empty else 1000
                    )

                    portfolio.cash += (amount - cost.total)
                    del portfolio.positions[signal.cb_code]

                    self._trades.append({
                        "date": current_date,
                        "code": signal.cb_code,
                        "action": "sell",
                        "price": signal.price,
                        "quantity": signal.quantity,
                        "cost": cost.total,
                        "pnl": amount - pos.cost_basis,
                    })

        return portfolio

    def _update_portfolio(
        self,
        portfolio: Portfolio,
        day_data: pd.DataFrame,
        current_date: date,
    ) -> Portfolio:
        """更新组合市值

        Args:
            portfolio: 当前组合
            day_data: 当日数据
            current_date: 当前日期

        Returns:
            更新后的组合
        """
        total_market_value = 0

        for code, pos in portfolio.positions.items():
            row = day_data[day_data["code"] == code]
            if not row.empty:
                pos.current_price = row.iloc[0]["close"]
                pos.market_value = pos.current_price * pos.quantity
                pos.unrealized_pnl = pos.market_value - pos.cost_basis
                pos.unrealized_pnl_pct = pos.unrealized_pnl / pos.cost_basis if pos.cost_basis > 0 else 0
                pos.days_held += 1

            total_market_value += pos.market_value

        portfolio.total_market_value = total_market_value
        portfolio.aum = portfolio.cash + total_market_value
        portfolio.position_count = len(portfolio.positions)
        portfolio.date = current_date

        return portfolio

    def _calculate_performance(
        self,
        daily_values: List[Dict],
        benchmark_data: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """计算绩效

        Args:
            daily_values: 每日净值
            benchmark_data: 基准数据

        Returns:
            BacktestResult: 回测结果
        """
        if not daily_values:
            return BacktestResult(
                period_start=self.config.start_date,
                period_end=self.config.end_date,
                is_train=False,
                returns=0,
                benchmark_returns=0,
                excess_returns=0,
                max_drawdown=0,
                sharpe_ratio=0,
                win_rate=0,
                turnover_rate=0,
                total_cost=0,
                trade_count=0,
            )

        values = pd.DataFrame(daily_values)
        values["return"] = values["value"].pct_change()

        # 总收益
        total_return = (values["value"].iloc[-1] / values["value"].iloc[0]) - 1

        # 最大回撤
        cummax = values["value"].cummax()
        drawdown = (values["value"] - cummax) / cummax
        max_drawdown = drawdown.min()

        # 夏普比率(假设无风险利率3%)
        if values["return"].std() > 0:
            sharpe = (values["return"].mean() * 252 - 0.03) / (values["return"].std() * np.sqrt(252))
        else:
            sharpe = 0

        # 胜率
        win_days = (values["return"] > 0).sum()
        total_days = len(values) - 1
        win_rate = win_days / total_days if total_days > 0 else 0

        # 换手率
        total_trades = len(self._trades)
        avg_aum = values["value"].mean()
        turnover = sum(t["price"] * t["quantity"] for t in self._trades) / avg_aum if avg_aum > 0 else 0

        # 总成本
        total_cost = sum(t.get("cost", 0) for t in self._trades)

        # 基准收益
        benchmark_return = 0
        if benchmark_data is not None and not benchmark_data.empty:
            bm_start = benchmark_data[benchmark_data["date"] >= self.config.start_date]
            bm_end = bm_start[bm_start["date"] <= self.config.end_date]
            if not bm_end.empty:
                benchmark_return = bm_end["close"].iloc[-1] / bm_end["close"].iloc[0] - 1

        return BacktestResult(
            period_start=self.config.start_date,
            period_end=self.config.end_date,
            is_train=False,
            returns=total_return,
            benchmark_returns=benchmark_return,
            excess_returns=total_return - benchmark_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            turnover_rate=turnover,
            total_cost=total_cost,
            trade_count=total_trades,
        )


class WalkForwardEngine:
    """Walk-Forward验证引擎"""

    def __init__(self, config: BacktestConfig):
        """初始化

        Args:
            config: 回测配置
        """
        self.config = config

    def run(
        self,
        cb_data: pd.DataFrame,
        stock_data: Optional[pd.DataFrame] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
        strategy_func: Optional[Callable] = None,
    ) -> WalkForwardResult:
        """运行Walk-Forward验证

        Args:
            cb_data: 可转债数据
            stock_data: 正股数据
            benchmark_data: 基准数据
            strategy_func: 策略函数

        Returns:
            WalkForwardResult: 验证结果
        """
        result = WalkForwardResult(config=self.config)

        # 计算滚动周期
        dates = sorted(cb_data["date"].unique())
        start_idx = 0

        while True:
            train_end_idx = start_idx + self.config.train_window_months * 21
            test_end_idx = train_end_idx + self.config.test_window_months * 21

            if test_end_idx >= len(dates):
                break

            # 训练期
            train_start = dates[start_idx]
            train_end = dates[train_end_idx]

            # 测试期
            test_start = dates[train_end_idx + 1]
            test_end = dates[min(test_end_idx, len(dates) - 1)]

            logger.info(
                f"[WalkForward] 训练期: {train_start} - {train_end}, "
                f"测试期: {test_start} - {test_end}"
            )

            # 运行测试期回测
            test_config = BacktestConfig(
                start_date=test_start,
                end_date=test_end,
                initial_capital=self.config.initial_capital,
            )

            backtest = BacktestEngine(test_config)
            period_result = backtest.run_backtest(
                cb_data, stock_data, benchmark_data, strategy_func
            )
            period_result.is_train = False

            result.periods.append(period_result)

            # 滚动
            start_idx += self.config.rolling_step_months * 21

        # 计算汇总指标
        if result.periods:
            result.total_returns = sum(p.returns for p in result.periods) / len(result.periods)
            result.total_benchmark_returns = sum(p.benchmark_returns for p in result.periods) / len(result.periods)
            result.total_excess_returns = result.total_returns - result.total_benchmark_returns
            result.avg_sharpe = sum(p.sharpe_ratio for p in result.periods) / len(result.periods)
            result.avg_max_drawdown = sum(p.max_drawdown for p in result.periods) / len(result.periods)
            result.avg_win_rate = sum(p.win_rate for p in result.periods) / len(result.periods)

        return result

    def get_yearly_results(self, result: WalkForwardResult) -> Dict[int, BacktestResult]:
        """按年份汇总结果

        Args:
            result: Walk-Forward结果

        Returns:
            按年份的结果字典
        """
        yearly = {}

        for period in result.periods:
            year = period.period_start.year
            if year not in yearly:
                yearly[year] = []
            yearly[year].append(period)

        # 合并同一年度的结果
        yearly_result = {}
        for year, periods in yearly.items():
            avg_return = sum(p.returns for p in periods) / len(periods)
            avg_benchmark = sum(p.benchmark_returns for p in periods) / len(periods)
            max_dd = max(p.max_drawdown for p in periods)
            avg_sharpe = sum(p.sharpe_ratio for p in periods) / len(periods)

            yearly_result[year] = BacktestResult(
                period_start=periods[0].period_start,
                period_end=periods[-1].period_end,
                is_train=False,
                returns=avg_return,
                benchmark_returns=avg_benchmark,
                excess_returns=avg_return - avg_benchmark,
                max_drawdown=max_dd,
                sharpe_ratio=avg_sharpe,
                win_rate=sum(p.win_rate for p in periods) / len(periods),
                turnover_rate=sum(p.turnover_rate for p in periods) / len(periods),
                total_cost=sum(p.total_cost for p in periods),
                trade_count=sum(p.trade_count for p in periods),
            )

        return yearly_result


# ============ 并行回测引擎 ============

class ParallelBacktestEngine:
    """并行回测引擎 - 支持多进程加速"""

    def __init__(
        self,
        config: BacktestConfig,
        n_workers: int = 4,
        chunk_size: int = 252,  # 约一年交易日
    ):
        """初始化

        Args:
            config: 回测配置
            n_workers: 并行进程数
            chunk_size: 数据分块大小(天)
        """
        self.config = config
        self.n_workers = n_workers
        self.chunk_size = chunk_size

    def run_parallel_backtest(
        self,
        cb_data: pd.DataFrame,
        strategy_func: Optional[Callable] = None,
        show_progress: bool = True,
    ) -> BacktestResult:
        """运行并行回测

        Args:
            cb_data: 可转债数据
            strategy_func: 策略函数
            show_progress: 显示进度

        Returns:
            回测结果
        """
        try:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            import multiprocessing
            PARALLEL_AVAILABLE = True
        except ImportError:
            PARALLEL_AVAILABLE = False
            logger.warning("[ParallelBacktest] 多进程不可用，使用单进程")
            engine = BacktestEngine(self.config)
            return engine.run_backtest(cb_data, strategy_func=strategy_func)

        # 按日期分块
        dates = sorted(cb_data["date"].unique())
        dates = [d for d in dates if self.config.start_date <= d <= self.config.end_date]

        if len(dates) == 0:
            return self._empty_result()

        # 分块
        chunks = self._create_chunks(dates)

        if PARALLEL_AVAILABLE and len(chunks) > 1:
            # 并行执行
            results = self._run_parallel(chunks, cb_data, strategy_func, show_progress)
        else:
            # 单进程执行
            results = self._run_sequential(chunks, cb_data, strategy_func, show_progress)

        # 合并结果
        return self._merge_results(results)

    def _create_chunks(self, dates: List) -> List[Tuple]:
        """创建日期分块"""
        chunks = []
        for i in range(0, len(dates), self.chunk_size):
            chunk_dates = dates[i:i + self.chunk_size]
            chunks.append((chunk_dates[0], chunk_dates[-1]))
        return chunks

    def _run_parallel(
        self,
        chunks: List[Tuple],
        cb_data: pd.DataFrame,
        strategy_func: Optional[Callable],
        show_progress: bool,
    ) -> List[Dict]:
        """并行执行"""
        from concurrent.futures import ProcessPoolExecutor, as_completed

        results = []

        with ProcessPoolExecutor(max_workers=self.n_workers) as executor:
            futures = {
                executor.submit(
                    self._run_chunk,
                    chunk,
                    cb_data,
                    strategy_func,
                ): chunk
                for chunk in chunks
            }

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    if show_progress:
                        chunk = futures[future]
                        logger.info(f"[ParallelBacktest] 完成: {chunk[0]} ~ {chunk[1]}")
                except Exception as e:
                    logger.error(f"[ParallelBacktest] 执行失败: {e}")

        # 按时间排序
        results.sort(key=lambda x: x.get('start_date', date.min))
        return results

    def _run_sequential(
        self,
        chunks: List[Tuple],
        cb_data: pd.DataFrame,
        strategy_func: Optional[Callable],
        show_progress: bool,
    ) -> List[Dict]:
        """顺序执行"""
        results = []
        for i, chunk in enumerate(chunks):
            result = self._run_chunk(chunk, cb_data, strategy_func)
            results.append(result)
            if show_progress:
                progress = (i + 1) / len(chunks) * 100
                logger.info(f"[Backtest] 进度: {progress:.1f}%")
        return results

    def _run_chunk(
        self,
        chunk: Tuple,
        cb_data: pd.DataFrame,
        strategy_func: Optional[Callable],
    ) -> Dict:
        """运行单个分块"""
        start_date, end_date = chunk

        # 筛选数据
        chunk_data = cb_data[
            (cb_data['date'] >= start_date) &
            (cb_data['date'] <= end_date)
        ]

        # 创建子配置
        chunk_config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital,
            commission_rate=self.config.commission_rate,
            slippage_rate=self.config.slippage_rate,
        )

        # 运行回测
        engine = BacktestEngine(chunk_config)
        result = engine.run_backtest(chunk_data, strategy_func=strategy_func)

        return {
            'start_date': start_date,
            'end_date': end_date,
            'result': result,
            'daily_values': engine._daily_values,
        }

    def _merge_results(self, results: List[Dict]) -> BacktestResult:
        """合并多个分块结果"""
        if not results:
            return self._empty_result()

        # 合并每日净值
        all_daily = []
        for r in results:
            all_daily.extend(r.get('daily_values', []))

        # 计算综合指标
        total_return = 1.0
        for r in results:
            total_return *= (1 + r['result'].returns)
        total_return -= 1

        # 使用第一个和最后一个的时间范围
        first_result = results[0]['result']
        last_result = results[-1]['result']

        # 计算整体夏普比率
        if all_daily:
            values = [d['value'] for d in all_daily]
            returns = pd.Series(values).pct_change().dropna()
            if returns.std() > 0:
                sharpe = returns.mean() / returns.std() * np.sqrt(252)
            else:
                sharpe = 0
        else:
            sharpe = 0

        # 计算最大回撤
        max_drawdown = self._calculate_max_drawdown(all_daily)

        return BacktestResult(
            period_start=results[0]['start_date'],
            period_end=results[-1]['end_date'],
            is_train=False,
            returns=total_return,
            benchmark_returns=sum(r['result'].benchmark_returns for r in results) / len(results),
            excess_returns=total_return - sum(r['result'].benchmark_returns for r in results) / len(results),
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=sum(r['result'].win_rate for r in results) / len(results),
            turnover_rate=sum(r['result'].turnover_rate for r in results) / len(results),
            total_cost=sum(r['result'].total_cost for r in results),
            trade_count=sum(r['result'].trade_count for r in results),
        )

    def _calculate_max_drawdown(self, daily_values: List[Dict]) -> float:
        """计算最大回撤"""
        if not daily_values:
            return 0

        values = [d['value'] for d in daily_values]
        peak = values[0]
        max_dd = 0

        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _empty_result(self) -> BacktestResult:
        """返回空结果"""
        return BacktestResult(
            period_start=self.config.start_date,
            period_end=self.config.end_date,
            is_train=False,
            returns=0,
            benchmark_returns=0,
            excess_returns=0,
            max_drawdown=0,
            sharpe_ratio=0,
            win_rate=0,
            turnover_rate=0,
            total_cost=0,
            trade_count=0,
        )


class MemoryOptimizedBacktest:
    """内存优化回测 - 支持大数据量"""

    def __init__(self, config: BacktestConfig, max_memory_mb: int = 500):
        """初始化

        Args:
            config: 回测配置
            max_memory_mb: 最大内存使用(MB)
        """
        self.config = config
        self.max_memory_mb = max_memory_mb

    def run_backtest(
        self,
        cb_data_iterator,
        strategy_func: Optional[Callable] = None,
    ) -> BacktestResult:
        """运行内存优化回测

        Args:
            cb_data_iterator: 数据迭代器（按日生成数据）
            strategy_func: 策略函数

        Returns:
            回测结果
        """
        portfolio = Portfolio(
            date=self.config.start_date,
            aum=self.config.initial_capital,
            cash=self.config.initial_capital,
        )

        daily_values = []
        trade_count = 0
        total_cost = 0

        for day_data in cb_data_iterator:
            current_date = day_data.get('date')

            if current_date < self.config.start_date or current_date > self.config.end_date:
                continue

            # 执行策略
            if strategy_func:
                signals = strategy_func(portfolio, day_data, current_date)
            else:
                signals = self._simple_strategy(portfolio, day_data)

            # 执行交易
            for signal in signals:
                if signal.action == "buy":
                    cost = signal.price * signal.quantity * self.config.commission_rate
                    if portfolio.cash >= signal.price * signal.quantity + cost:
                        portfolio.cash -= signal.price * signal.quantity + cost
                        if signal.cb_code not in portfolio.positions:
                            portfolio.positions[signal.cb_code] = Position(
                                cb_code=signal.cb_code,
                                cb_name=signal.cb_name,
                                quantity=signal.quantity,
                                avg_cost=signal.price,
                                current_price=signal.price,
                                market_value=signal.price * signal.quantity,
                                cost_basis=signal.price * signal.quantity,
                            )
                        else:
                            pos = portfolio.positions[signal.cb_code]
                            total_qty = pos.quantity + signal.quantity
                            pos.avg_cost = (pos.cost_basis + signal.price * signal.quantity) / total_qty
                            pos.quantity = total_qty
                            pos.cost_basis = pos.avg_cost * total_qty
                        trade_count += 1
                        total_cost += cost

                elif signal.action == "sell":
                    if signal.cb_code in portfolio.positions:
                        pos = portfolio.positions[signal.cb_code]
                        sell_qty = min(signal.quantity, pos.quantity)
                        proceeds = signal.price * sell_qty * (1 - self.config.commission_rate)
                        portfolio.cash += proceeds
                        pos.quantity -= sell_qty
                        if pos.quantity <= 0:
                            del portfolio.positions[signal.cb_code]
                        trade_count += 1
                        total_cost += signal.price * sell_qty * self.config.commission_rate

            # 更新市值
            total_mv = sum(pos.market_value for pos in portfolio.positions.values())
            portfolio.aum = portfolio.cash + total_mv

            # 记录（限制内存使用）
            daily_values.append({
                'date': current_date,
                'value': portfolio.aum,
            })

            # 内存检查
            import sys
            if sys.getsizeof(daily_values) > self.max_memory_mb * 1024 * 1024:
                # 压缩历史数据
                daily_values = self._compress_daily_values(daily_values)

        # 计算结果
        return self._calculate_result(daily_values, trade_count, total_cost)

    def _simple_strategy(self, portfolio, day_data) -> List:
        """简单策略"""
        return []

    def _compress_daily_values(self, daily_values: List[Dict]) -> List[Dict]:
        """压缩每日净值数据"""
        if len(daily_values) < 100:
            return daily_values
        # 只保留每周的数据点
        compressed = daily_values[::5]
        compressed.append(daily_values[-1])  # 保留最后一天
        return compressed

    def _calculate_result(
        self,
        daily_values: List[Dict],
        trade_count: int,
        total_cost: float,
    ) -> BacktestResult:
        """计算回测结果"""
        if not daily_values:
            return BacktestResult(
                period_start=self.config.start_date,
                period_end=self.config.end_date,
                is_train=False,
                returns=0,
                benchmark_returns=0,
                excess_returns=0,
                max_drawdown=0,
                sharpe_ratio=0,
                win_rate=0,
                turnover_rate=0,
                total_cost=total_cost,
                trade_count=trade_count,
            )

        values = [d['value'] for d in daily_values]
        returns = (values[-1] - values[0]) / values[0] if values[0] > 0 else 0

        # 计算夏普
        returns_series = pd.Series(values).pct_change().dropna()
        sharpe = returns_series.mean() / returns_series.std() * np.sqrt(252) if returns_series.std() > 0 else 0

        # 计算回撤
        peak = values[0]
        max_dd = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        return BacktestResult(
            period_start=daily_values[0]['date'],
            period_end=daily_values[-1]['date'],
            is_train=False,
            returns=returns,
            benchmark_returns=0,
            excess_returns=returns,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            win_rate=0.5,
            turnover_rate=trade_count / len(daily_values) if daily_values else 0,
            total_cost=total_cost,
            trade_count=trade_count,
        )


# 便捷函数
def quick_backtest(
    cb_data: pd.DataFrame,
    start_date: date,
    end_date: date,
    initial_capital: float = 10000.0,
    n_workers: int = 4,
) -> BacktestResult:
    """快速并行回测

    Args:
        cb_data: 可转债数据
        start_date: 开始日期
        end_date: 结束日期
        initial_capital: 初始资金
        n_workers: 并行进程数

    Returns:
        回测结果
    """
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
    )

    engine = ParallelBacktestEngine(config, n_workers=n_workers)
    return engine.run_parallel_backtest(cb_data)
