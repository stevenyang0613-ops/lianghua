"""参数网格搜索 + Walk-Forward 验证联用脚本

用法:
    cd /Users/mac/lianghua/backend
    .venv/bin/python scripts/backtest_optimize_wf.py

功能:
    1. 对璇玑十二因子策略进行参数网格搜索优化
    2. 对最优参数进行 Walk-Forward 验证（防止过拟合）
    3. 输出成本敏感性分析
    4. 支持并行执行

改进 (2025-06-15):
    - 网格搜索 + Walk-Forward 联用，评估参数稳定性
    - 增加成本敏感性测试（含冲击成本）
    - 输出基准对比和超额收益
"""
import sys, os, gc, time, logging
sys.path.insert(0, ".")
os.chdir("/Users/mac/lianghua/backend")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backtest_optimize_wf")

import pandas as pd, numpy as np
from datetime import date

from app.strategies.xuanji_twelve_factor import XuanjiTwelveFactorStrategy
from app.engine.backtest import (
    BacktestEngine, BacktestConfig, WalkForwardValidator, BacktestConfig
)
from app.models.backtest import OptimizationConfig, OptimizationParamRange


def load_data() -> pd.DataFrame:
    """加载回测数据 - 从 DuckDB 缓存获取"""
    from app.engine.storage import DataStorage
    storage = DataStorage(db_path="data/bonds.duckdb")
    from app.engine.historical import HistoricalDataLoader
    loader = HistoricalDataLoader(storage)
    df = loader.get_cached_history(
        start_date=date(2022, 1, 1),
        end_date=date(2025, 6, 14),
    )
    if df.empty:
        logger.error("无缓存数据，请先运行 seed_historical_data()")
        sys.exit(1)
    return df


def grid_search_walk_forward(
    data: pd.DataFrame,
    optimize_metric: str = "sharpe_ratio",
    n_iter: int = 50,
) -> dict:
    """网格搜索 + Walk-Forward 验证"""
    t0 = time.time()

    # 1. 参数网格搜索
    logger.info(f"=== Step 1: 参数网格搜索 ({n_iter} 组合) ===")
    engine = BacktestEngine(config=BacktestConfig(
        commission_pct=0.0003, slippage_pct=0.0003, impact_cost_pct=0.0001,
        min_commission=1.0, risk_free_rate=0.02, initial_cash=1_000_000,
        benchmark="equal_weight",
    ))
    opt_config = OptimizationConfig(
        optimize_metric=optimize_metric,
        max_iterations=n_iter,
        parallel_workers=4,  # 4进程并行
        top_n=10,
        param_ranges=[
            OptimizationParamRange(name="hold_count", min_val=5, max_val=20, step=1),
            OptimizationParamRange(name="rebalance_days", min_val=5, max_val=30, step=1),
            OptimizationParamRange(name="stop_loss_pct", min_val=-8, max_val=-3, step=0.5),
            OptimizationParamRange(name="max_premium", min_val=30, max_val=60, step=2),
            OptimizationParamRange(name="vol_adjust", min_val=0.7, max_val=1.0, step=0.05),
        ],
    )
    opt_result = engine.run_optimization(
        XuanjiTwelveFactorStrategy, data, opt_config,
        on_progress=lambda c, t, m: logger.info(f"  {m}") if c % 10 == 0 else None,
    )

    logger.info(f"网格搜索完成: {opt_result.execution_time_ms}ms")
    best = opt_result.best_params
    logger.info(f"最优参数: {best}")
    logger.info(f"最优指标: return={opt_result.best_metrics.total_return_pct:+.2f}% "
                f"sharpe={opt_result.best_metrics.sharpe_ratio:.2f} "
                f"drawdown={opt_result.best_metrics.max_drawdown_pct:.2f}%")

    # 2. Walk-Forward 验证（使用最优参数）
    logger.info(f"\n=== Step 2: Walk-Forward 验证 ===")
    wf = WalkForwardValidator()
    wf_result = wf.validate(
        XuanjiTwelveFactorStrategy, data,
        train_days=360, test_days=180,  # 训练1年，测试半年
        param_grid=opt_config,
        optimize_metric=optimize_metric,
        on_progress=lambda c, t, m: logger.info(f"  {m}"),
    )
    logger.info(f"\n{wf_result.summary()}")
    logger.info(f"策略稳健性: {'通过' if wf_result.is_robust() else '未通过'}")

    # 3. 成本敏感性分析
    logger.info(f"\n=== Step 3: 成本敏感性分析 ===")
    cost_result = engine.cost_sensitivity(
        XuanjiTwelveFactorStrategy(**best), data,
        on_progress=lambda c, t, m: logger.info(f"  {m}") if c % 2 == 0 else None,
    )
    logger.info(f"零成本基准: {cost_result.baseline.total_return_pct:+.2f}%")
    logger.info(f"最高成本场景: comm={cost_result.worst_params.get('commission_pct', 0)*100:.2f}% "
                f"slip={cost_result.worst_params.get('slippage_pct', 0)*100:.2f}% -> "
                f"return={min(s.total_return_pct for s in cost_result.scenarios):+.2f}%")
    logger.info(f"成本拖累: {cost_result.baseline.total_return_pct - min(s.total_return_pct for s in cost_result.scenarios):.2f}%")

    # 4. 最终全期回测（最优参数）
    logger.info(f"\n=== Step 4: 最终全期回测 ===")
    final_engine = BacktestEngine(config=BacktestConfig(
        commission_pct=0.0003, slippage_pct=0.0003, impact_cost_pct=0.0001,
        benchmark="equal_weight", initial_cash=1_000_000,
    ))
    final_result = final_engine.run(XuanjiTwelveFactorStrategy(**best), data)
    m = final_result.metrics
    logger.info(f"全期收益: {m.total_return_pct:+.2f}% 年化: {m.annual_return_pct:+.2f}%")
    logger.info(f"夏普: {m.sharpe_ratio:.2f} 回撤: {m.max_drawdown_pct:.2f}% 胜率: {m.win_rate:.1f}%")
    logger.info(f"交易: {m.total_trades}笔 总成本: {final_result.total_cost:.0f}元")
    if final_result.benchmark_metrics:
        logger.info(f"基准收益: {final_result.benchmark_metrics.total_return_pct:+.2f}%")
    if final_result.excess_metrics:
        logger.info(f"超额收益: {final_result.excess_metrics.total_return_pct:+.2f}%")

    total_time = time.time() - t0
    logger.info(f"\n总耗时: {total_time:.0f}s")

    return {
        "optimal_params": best,
        "opt_result": opt_result,
        "wf_result": wf_result,
        "cost_result": cost_result,
        "final_result": final_result,
    }


if __name__ == "__main__":
    data = load_data()
    grid_search_walk_forward(data, optimize_metric="sharpe_ratio", n_iter=50)
