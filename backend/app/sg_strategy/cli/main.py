"""松岗量化可转债策略 V3.0 CLI命令行工具"""
import click
from datetime import date, datetime
import json
import sys
import os

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.sg_strategy.core.strategy import SGConvertibleStrategy
from app.sg_strategy.config.weights import MarketRegime


@click.group()
def cli():
    """松岗量化可转债策略 V3.0 CLI"""
    pass


@cli.command()
@click.option('--aum', default=10000.0, help='资产规模(万元)')
@click.option('--regime', type=click.Choice(['bull', 'range', 'bear']), default='range', help='市场环境')
def init(aum: float, regime: str):
    """初始化策略"""
    regime_map = {
        'bull': MarketRegime.BULL,
        'range': MarketRegime.RANGE,
        'bear': MarketRegime.BEAR,
    }
    strategy = SGConvertibleStrategy(aum, regime_map[regime])
    click.echo(f"策略初始化完成:")
    click.echo(f"  AUM: {aum}万元")
    click.echo(f"  市场环境: {regime}")
    click.echo(f"  白名单大小: {len(strategy.whitelist)}")


@cli.command()
@click.option('--top', default=20, help='显示前N名')
def whitelist(top: int):
    """查看白名单"""
    strategy = SGConvertibleStrategy()
    wl = strategy.get_whitelist()[:top]
    click.echo(f"白名单 (前{top}只):")
    for i, code in enumerate(wl, 1):
        click.echo(f"  {i}. {code}")


@cli.command()
@click.option('--aum', default=10000.0, help='资产规模(万元)')
def cost(aum: float):
    """预估交易成本"""
    from app.sg_strategy.core.cost import TransactionCostModel
    model = TransactionCostModel(aum)
    result = model.estimate_monthly_cost()
    click.echo("月度交易成本预估:")
    click.echo(f"  佣金: {result['monthly_commission']:.2f}元")
    click.echo(f"  经手费: {result['monthly_exchange']:.2f}元")
    click.echo(f"  滑点: {result['monthly_slippage']:.2f}元")
    click.echo(f"  冲击成本: {result['monthly_impact']:.2f}元")
    click.echo(f"  月度总成本: {result['monthly_total']:.2f}元")
    click.echo(f"  年化成本率: {result['annual_cost_ratio']:.2f}%")


@cli.command()
@click.option('--premium', default=20.0, help='转股溢价率中位数(%)')
@click.option('--amount', default=500.0, help='日均成交额(亿)')
@click.option('--yield10y', default=2.5, help='10年期国债收益率(%)')
@click.option('--pmi', default=50.0, help='PMI')
def timing(premium: float, amount: float, yield10y: float, pmi: float):
    """计算择时信号"""
    from app.sg_strategy.core.timing import TimingEngine, MarketData

    engine = TimingEngine()
    market_data = MarketData(
        date=date.today(),
        cb_median_premium=premium,
        cb_avg_daily_amount=amount,
        treasury_10y_yield=yield10y,
        pmi=pmi,
    )

    signal = engine.calculate_timing(market_data)

    click.echo("择时信号:")
    click.echo(f"  估值得分: {signal.valuation_score:.1f}")
    click.echo(f"  情绪得分: {signal.sentiment_score:.1f}")
    click.echo(f"  流动性得分: {signal.liquidity_score:.1f}")
    click.echo(f"  宏观得分: {signal.macro_score:.1f}")
    click.echo(f"  综合得分: {signal.total_score:.1f}")
    click.echo(f"  建议仓位: {signal.position_ratio*100:.0f}%")
    click.echo(f"  市场环境: {signal.regime.value}")
    click.echo(f"  需要对冲: {'是' if signal.hedge_required else '否'}")


@cli.command()
@click.option('--output', default='report.json', help='输出文件')
def report(output: str):
    """生成策略报告"""
    strategy = SGConvertibleStrategy()
    perf = strategy.get_performance_summary()

    report_data = {
        "date": date.today().isoformat(),
        "performance": perf,
        "whitelist_size": len(strategy.whitelist),
        "regime": strategy.regime.value,
    }

    with open(output, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    click.echo(f"报告已生成: {output}")
    click.echo(json.dumps(report_data, ensure_ascii=False, indent=2))


@cli.command()
@click.option('--days', default=365, help='回测天数')
@click.option('--capital', default=10000.0, help='初始资金(万元)')
def backtest(days: int, capital: float):
    """运行回测"""
    from app.sg_strategy.core.backtest import BacktestEngine, BacktestConfig
    from datetime import timedelta
    import pandas as pd
    import numpy as np

    click.echo("正在准备模拟数据...")

    # 生成模拟数据
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    dates = pd.date_range(start_date, end_date, freq='B')  # 工作日
    n_bonds = 50
    codes = [f"110{i:03d}" for i in range(n_bonds)]

    rows = []
    np.random.seed(42)

    for d in dates:
        for code in codes:
            base_price = 100 + np.random.randn() * 10
            rows.append({
                'date': d.date(),
                'code': code,
                'name': f"转债{code[-3:]}",
                'close': max(80, min(150, base_price + np.random.randn() * 2)),
                'premium_ratio': np.random.uniform(5, 40),
                'volume': np.random.uniform(1000, 10000),
            })

    cb_data = pd.DataFrame(rows)

    click.echo(f"模拟数据: {len(dates)}天, {n_bonds}只转债")

    # 运行回测
    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=capital,
    )

    engine = BacktestEngine(config)
    result = engine.run_backtest(cb_data)

    click.echo("\n回测结果:")
    click.echo(f"  区间: {result.period_start} ~ {result.period_end}")
    click.echo(f"  总收益: {result.returns*100:.2f}%")
    click.echo(f"  最大回撤: {result.max_drawdown*100:.2f}%")
    click.echo(f"  夏普比率: {result.sharpe_ratio:.2f}")
    click.echo(f"  胜率: {result.win_rate*100:.1f}%")
    click.echo(f"  换手率: {result.turnover_rate*100:.1f}%")
    click.echo(f"  交易次数: {result.trade_count}")
    click.echo(f"  总成本: {result.total_cost:.2f}元")


@cli.command()
def daily():
    """每日操作时间表"""
    click.echo("松岗量化可转债策略 V3.0 每日操作时间表")
    click.echo("=" * 50)

    schedule = [
        ("8:30-9:00", "数据更新", "盘前更新正股和转债基础数据"),
        ("9:00-9:25", "开盘准备", "更新择时信号，检查持仓异常"),
        ("9:30-10:30", "卖出执行", "卖出不在白名单的持仓"),
        ("9:30-10:30", "买入执行", "按计划买入白名单标的"),
        ("10:30-11:30", "监控预警", "监控止盈止损，处理异常"),
        ("13:00-14:00", "高频交易", "执行高频交易信号"),
        ("14:00-14:50", "调仓执行", "中低频调仓"),
        ("14:50", "清仓检查", "强制清仓未达标高频持仓"),
        ("15:00-16:00", "日终处理", "生成次日白名单，更新评分"),
        ("16:00-17:00", "成本追踪", "计算当日成本，实盘偏差对比"),
    ]

    for time, action, desc in schedule:
        click.echo(f"\n{time} | {action}")
        click.echo(f"  {desc}")


@cli.command()
@click.option('--code', required=True, help='转债代码')
def analyze(code: str):
    """分析单只转债"""
    from app.sg_strategy.core.scoring import SevenDimScoringEngine
    from app.sg_strategy.core.types import ConvertibleBondData
    from app.sg_strategy.config.weights import MarketRegime

    # 模拟数据
    cb = ConvertibleBondData(
        code=code,
        name=f"转债{code[-3:]}",
        stock_code=code.replace("110", "000"),
        stock_name=f"股票{code[-3:]}",
        date=date.today(),
        close=105.0,
        conversion_premium=18.0,
        remaining_years=2.5,
        daily_amount_20d=5000.0,
        implied_vol_percentile=45.0,
        vol_skew=0.1,
    )

    engine = SevenDimScoringEngine(MarketRegime.RANGE, 10000.0)
    score = engine.score_bond(cb)

    click.echo(f"\n转债代码: {code}")
    click.echo(f"转债名称: {cb.name}")
    click.echo("\n七维得分:")
    click.echo(f"  短期动量: {score.short_momentum:.2f}/16.5")
    click.echo(f"  板块情绪: {score.sector_sentiment:.2f}/9.9")
    click.echo(f"  技术面: {score.technical:.2f}/9.9")
    click.echo(f"  筹码面: {score.chip_structure:.2f}/6.6")
    click.echo(f"  波动率: {score.volatility:.2f}/6.6")
    click.echo(f"  消息面: {score.news_factor:.2f}/3.85")
    click.echo(f"  基本面: {score.fundamentals:.2f}/1.65")
    click.echo(f"  正股小计: {score.stock_total:.2f}/55")
    click.echo(f"\n转债得分:")
    click.echo(f"  估值指标: {score.valuation:.2f}/17.1")
    click.echo(f"  条款价值: {score.clause_value:.2f}/10.8")
    click.echo(f"  流动性: {score.liquidity:.2f}/9.0")
    click.echo(f"  信用评分: {score.credit:.2f}/8.1")
    click.echo(f"  转债小计: {score.cb_total:.2f}/45")
    click.echo(f"\n总分: {score.total_score:.2f}/100")


@cli.command()
def params():
    """显示策略参数"""
    from app.sg_strategy.config.settings import params as p

    click.echo("松岗量化可转债策略 V3.0 核心参数")
    click.echo("=" * 50)

    sections = [
        ("一票否决", [
            ("最大转股溢价率", f"{p.max_conversion_premium}%"),
            ("最小剩余期限", f"{p.min_remaining_years}年"),
            ("最低信用评分", f"{p.min_credit_score}分"),
        ]),
        ("七维权重", [
            ("正股权重", f"{p.stock_weight*100}%"),
            ("转债权重", f"{p.cb_weight*100}%"),
            ("短期动量", f"{p.w_short_momentum*100}%"),
            ("板块情绪", f"{p.w_sector_sentiment*100}%"),
        ]),
        ("白名单", [
            ("牛市白名单数", f"{p.whitelist_size_bull}只"),
            ("震荡市白名单数", f"{p.whitelist_size_range}只"),
            ("熊市白名单数", f"{p.whitelist_size_bear}只"),
            ("缓冲带观察期", f"{p.buffer_days_max}天"),
        ]),
        ("止盈止损", [
            ("常规止损", f"{p.stop_loss_pct}%"),
            ("第一止盈位", f"{p.take_profit_tier1}%"),
            ("第二止盈位", f"{p.take_profit_tier2}%"),
            ("第三止盈位", f"{p.take_profit_tier3}%"),
        ]),
        ("交易成本", [
            ("佣金率", f"{p.commission_rate*10000}万分之一"),
            ("高流动性滑点", f"{p.slippage_high_liq*100}%"),
            ("中流动性滑点", f"{p.slippage_mid_liq*100}%"),
            ("低流动性滑点", f"{p.slippage_low_liq*100}%"),
        ]),
    ]

    for section_name, items in sections:
        click.echo(f"\n{section_name}:")
        for name, value in items:
            click.echo(f"  {name}: {value}")


if __name__ == '__main__':
    cli()
