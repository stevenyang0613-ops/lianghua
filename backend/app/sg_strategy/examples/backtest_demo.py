"""运行完整回测示例"""
import sys
sys.path.insert(0, '/Users/stevenyang/Public/lianghua/backend')

from datetime import date, timedelta
import pandas as pd
import numpy as np

from app.sg_strategy.core.backtest import BacktestEngine, WalkForwardEngine, BacktestConfig
from app.sg_strategy.core.strategy import SGConvertibleStrategy
from app.sg_strategy.config.weights import MarketRegime


def generate_mock_data(days: int = 365, n_bonds: int = 50):
    """生成模拟数据"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    dates = pd.date_range(start_date, end_date, freq='B')
    codes = [f"110{i:03d}" for i in range(n_bonds)]

    rows = []
    np.random.seed(42)

    for d in dates:
        for code in codes:
            base_price = 100 + np.random.randn() * 10
            premium = 5 + np.random.random() * 35
            rows.append({
                'date': d.date(),
                'code': code,
                'name': f"转债{code[-3:]}",
                'stock_code': code.replace("110", "000"),
                'stock_name': f"股票{code[-3:]}",
                'close': max(80, min(150, base_price + np.random.randn() * 2)),
                'premium_ratio': premium,
                'volume': np.random.uniform(1000, 10000),
                'remaining_years': 0.5 + np.random.random() * 5,
            })

    return pd.DataFrame(rows), start_date, end_date


def run_simple_backtest():
    """运行简单回测"""
    print("=" * 60)
    print("简单回测示例")
    print("=" * 60)

    # 生成数据
    cb_data, start_date, end_date = generate_mock_data(days=180, n_bonds=30)
    print(f"\n数据: {len(cb_data)}条记录")
    print(f"日期范围: {start_date} ~ {end_date}")

    # 配置回测
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=10000.0,
    )

    # 运行回测
    engine = BacktestEngine(config)
    result = engine.run_backtest(cb_data)

    # 输出结果
    print(f"\n回测结果:")
    print(f"  总收益: {result.returns*100:.2f}%")
    print(f"  最大回撤: {result.max_drawdown*100:.2f}%")
    print(f"  夏普比率: {result.sharpe_ratio:.2f}")
    print(f"  胜率: {result.win_rate*100:.1f}%")
    print(f"  换手率: {result.turnover_rate*100:.1f}%")
    print(f"  交易次数: {result.trade_count}")
    print(f"  总成本: {result.total_cost:.2f}元")


def run_walkforward_backtest():
    """运行Walk-Forward回测"""
    print("\n" + "=" * 60)
    print("Walk-Forward回测示例")
    print("=" * 60)

    # 生成数据
    cb_data, start_date, end_date = generate_mock_data(days=365, n_bonds=30)
    print(f"\n数据: {len(cb_data)}条记录")

    # 配置
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=10000.0,
        train_window_months=6,
        test_window_months=2,
        rolling_step_months=2,
    )

    # 运行
    engine = WalkForwardEngine(config)
    result = engine.run(cb_data)

    # 输出结果
    print(f"\nWalk-Forward结果:")
    print(f"  测试期数: {len(result.periods)}")
    print(f"  平均收益: {result.total_returns*100:.2f}%")
    print(f"  平均夏普: {result.avg_sharpe:.2f}")
    print(f"  平均最大回撤: {result.avg_max_drawdown*100:.2f}%")
    print(f"  平均胜率: {result.avg_win_rate*100:.1f}%")

    # 按年份汇总
    yearly = engine.get_yearly_results(result)
    print(f"\n按年度统计:")
    for year, res in yearly.items():
        print(f"  {year}: 收益{res.returns*100:.2f}%, 回撤{res.max_drawdown*100:.2f}%")


def run_strategy_simulation():
    """运行策略模拟"""
    print("\n" + "=" * 60)
    print("策略模拟示例")
    print("=" * 60)

    from app.sg_strategy.core.types import ConvertibleBondData
    from app.sg_strategy.core.timing import MarketData

    # 初始化策略
    strategy = SGConvertibleStrategy(
        aum=10000.0,
        regime=MarketRegime.RANGE,
    )

    # 模拟5个交易日
    print("\n模拟5个交易日...")

    for day in range(5):
        current_date = date.today() - timedelta(days=5-day)

        # 生成当日数据
        np.random.seed(42 + day)
        n_bonds = 30
        cb_data = [
            ConvertibleBondData(
                code=f"110{i:03d}",
                name=f"转债{i}",
                stock_code=f"00000{i}",
                stock_name=f"股票{i}",
                date=current_date,
                close=100 + np.random.randn() * 10,
                conversion_premium=10 + np.random.random() * 25,
                remaining_years=2 + np.random.random() * 3,
                daily_amount_20d=1000 + np.random.random() * 5000,
            )
            for i in range(n_bonds)
        ]

        # 市场数据
        market_data = MarketData(
            date=current_date,
            cb_median_premium=18 + np.random.randn() * 3,
            cb_avg_daily_amount=450 + np.random.randn() * 50,
            treasury_10y_yield=2.3 + np.random.randn() * 0.1,
            pmi=50 + np.random.randn() * 2,
        )

        # 运行策略
        report = strategy.run_daily(cb_data, market_data=market_data, current_date=current_date)

        # 输出
        perf = strategy.get_performance_summary()
        print(f"\nDay {day+1} ({current_date}):")
        print(f"  净值: {perf['aum']:.2f}万")
        print(f"  持仓: {perf['position_count']}只")
        print(f"  白名单: {perf['whitelist_size']}只")

    # 最终绩效
    print("\n" + "-" * 40)
    print("最终绩效:")
    perf = strategy.get_performance_summary()
    print(f"  总资产: {perf['aum']:.2f}万元")
    print(f"  总持仓: {perf['position_count']}只")


if __name__ == "__main__":
    run_simple_backtest()
    run_walkforward_backtest()
    run_strategy_simulation()
