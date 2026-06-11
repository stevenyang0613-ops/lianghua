"""松岗量化可转债策略 V3.0 使用示例"""
import sys
sys.path.insert(0, '/Users/stevenyang/Public/lianghua/backend')

from datetime import date
from app.sg_strategy.core.strategy import SGConvertibleStrategy
from app.sg_strategy.core.types import ConvertibleBondData, StockData
from app.sg_strategy.config.weights import MarketRegime


def example_basic_usage():
    """基础使用示例"""
    print("=" * 60)
    print("松岗量化可转债策略 V3.0 - 基础使用示例")
    print("=" * 60)

    # 1. 初始化策略
    print("\n1. 初始化策略...")
    strategy = SGConvertibleStrategy(
        aum=10000.0,  # 1亿规模
        regime=MarketRegime.RANGE,  # 震荡市
    )
    print(f"   AUM: {strategy.aum}万元")
    print(f"   市场环境: {strategy.regime.value}")

    # 2. 准备测试数据
    print("\n2. 准备测试数据...")
    cb_data = [
        ConvertibleBondData(
            code=f"110{i:03d}",
            name=f"测试转债{i}",
            stock_code=f"00000{i}",
            stock_name=f"测试股票{i}",
            date=date.today(),
            close=100 + i * 2,
            conversion_premium=10 + i * 2,
            remaining_years=3.0,
            daily_amount_20d=5000.0,
            implied_vol_percentile=50.0,
        )
        for i in range(1, 31)
    ]
    print(f"   准备了{len(cb_data)}只可转债数据")

    # 3. 运行每日策略
    print("\n3. 运行每日策略...")
    report = strategy.run_daily(cb_data)

    # 4. 查看结果
    print("\n4. 策略结果:")
    perf = strategy.get_performance_summary()
    print(f"   净值: {perf['aum']:.2f}万元")
    print(f"   持仓数: {perf['position_count']}只")
    print(f"   白名单数: {perf['whitelist_size']}只")

    # 5. 查看白名单
    print("\n5. 当前白名单(前10只):")
    whitelist = strategy.get_whitelist()[:10]
    for i, code in enumerate(whitelist, 1):
        print(f"   {i}. {code}")


def example_scoring():
    """七维打分示例"""
    print("\n" + "=" * 60)
    print("七维打分示例")
    print("=" * 60)

    from app.sg_strategy.core.scoring import SevenDimScoringEngine
    from app.sg_strategy.core.types import SevenDimScore

    engine = SevenDimScoringEngine(MarketRegime.RANGE, 10000.0)

    cb = ConvertibleBondData(
        code="110001",
        name="测试转债",
        stock_code="000001",
        stock_name="测试股票",
        date=date.today(),
        close=105.0,
        conversion_premium=15.0,
        remaining_years=3.0,
        daily_amount_20d=5000.0,
        implied_vol_percentile=50.0,
    )

    stock = StockData(
        code="000001",
        date=date.today(),
        close=10.0,
        change_pct=3.0,
        volume_ratio=2.0,
        turnover_rate=5.0,
        sector_change_pct=2.0,
        sector_limit_up_count=5,
        sector_total_count=50,
    )

    score: SevenDimScore = engine.score_bond(cb, stock)

    print(f"\n转债: {cb.code} {cb.name}")
    print("\n正股七维得分:")
    print(f"  短期动量: {score.short_momentum:.2f}/16.5")
    print(f"  板块情绪: {score.sector_sentiment:.2f}/9.9")
    print(f"  技术面: {score.technical:.2f}/9.9")
    print(f"  筹码面: {score.chip_structure:.2f}/6.6")
    print(f"  波动率: {score.volatility:.2f}/6.6")
    print(f"  消息面: {score.news_factor:.2f}/3.85")
    print(f"  基本面: {score.fundamentals:.2f}/1.65")
    print(f"  正股小计: {score.stock_total:.2f}/55")

    print("\n转债自身得分:")
    print(f"  估值指标: {score.valuation:.2f}/17.1")
    print(f"  条款价值: {score.clause_value:.2f}/10.8")
    print(f"  流动性: {score.liquidity:.2f}/9.0")
    print(f"  信用评分: {score.credit:.2f}/8.1")
    print(f"  转债小计: {score.cb_total:.2f}/45")

    print(f"\n总分: {score.total_score:.2f}/100")


def example_timing():
    """择时信号示例"""
    print("\n" + "=" * 60)
    print("多维度综合择时示例")
    print("=" * 60)

    from app.sg_strategy.core.timing import TimingEngine, MarketData

    engine = TimingEngine()

    market_data = MarketData(
        date=date.today(),
        cb_median_premium=18.0,  # 转股溢价率中位数
        cb_avg_daily_amount=500.0,  # 日均成交额(亿)
        treasury_10y_yield=2.3,  # 10年期国债收益率
        pmi=51.0,  # PMI
        pmi_prev=50.5,
    )

    signal = engine.calculate_timing(market_data)

    print(f"\n市场数据:")
    print(f"  转股溢价率中位数: {market_data.cb_median_premium}%")
    print(f"  日均成交额: {market_data.cb_avg_daily_amount}亿")
    print(f"  10年期国债收益率: {market_data.treasury_10y_yield}%")
    print(f"  PMI: {market_data.pmi}")

    print(f"\n择时得分:")
    print(f"  估值得分: {signal.valuation_score:.1f}/100")
    print(f"  情绪得分: {signal.sentiment_score:.1f}/100")
    print(f"  流动性得分: {signal.liquidity_score:.1f}/100")
    print(f"  宏观得分: {signal.macro_score:.1f}/100")
    print(f"  综合得分: {signal.total_score:.1f}/100")

    print(f"\n建议:")
    print(f"  市场环境: {signal.regime.value}")
    print(f"  建议仓位: {signal.position_ratio*100:.0f}%")
    print(f"  需要对冲: {'是' if signal.hedge_required else '否'}")


def example_cost():
    """交易成本示例"""
    print("\n" + "=" * 60)
    print("三层交易成本示例")
    print("=" * 60)

    from app.sg_strategy.core.cost import TransactionCostModel

    model = TransactionCostModel(aum=10000.0)

    # 计算单笔交易成本
    cost = model.calculate_cost(
        price=105.0,
        volume=1000,
        daily_amount=5000.0,  # 日均成交额5000万
    )

    print(f"\n交易: 买入1000张@105元")
    print(f"  交易金额: {105.0 * 1000:.0f}元")
    print(f"  佣金: {cost.commission:.2f}元")
    print(f"  经手费: {cost.exchange_fee:.2f}元")
    print(f"  滑点: {cost.slippage:.2f}元")
    print(f"  冲击成本: {cost.impact:.2f}元")
    print(f"  总成本: {cost.total:.2f}元")
    print(f"  成本率: {cost.total / (105 * 1000) * 100:.3f}%")

    # 月度成本预估
    print("\n月度成本预估:")
    monthly = model.estimate_monthly_cost()
    print(f"  月度总成本: {monthly['monthly_total']:.2f}元")
    print(f"  年化成本率: {monthly['annual_cost_ratio']:.2f}%")


def example_events():
    """事件驱动策略示例"""
    print("\n" + "=" * 60)
    print("事件驱动策略示例")
    print("=" * 60)

    from app.sg_strategy.core.events import (
        EventDrivenEngine, DownwardRevisionStrategy,
        DiscountArbitrageStrategy
    )

    # 下修博弈示例
    print("\n下修博弈分析:")
    revision_strategy = DownwardRevisionStrategy()

    cb = ConvertibleBondData(
        code="110001",
        name="测试转债",
        stock_code="000001",
        stock_name="测试股票",
        date=date.today(),
        close=105.0,
        conversion_premium=35.0,
        remaining_years=2.5,
        major_holder_ratio=25.0,  # 大股东持有25%
    )

    stock = StockData(
        code="000001",
        date=date.today(),
        debt_ratio=72.0,  # 资产负债率72%
    )

    revision_score = revision_strategy.calculate_revision_probability(cb, stock)

    print(f"  财务压力: {revision_score.financial_pressure:.1f}/30")
    print(f"  回售压力: {revision_score.put_time_pressure:.1f}/25")
    print(f"  大股东利益: {revision_score.major_holder_interest:.1f}/25")
    print(f"  下修历史: {revision_score.revision_history:.1f}/20")
    print(f"  总分: {revision_score.total_score:.1f}/100")
    print(f"  概率等级: {revision_score.probability_level}")

    # 折价套利示例
    print("\n折价套利分析:")
    arb_strategy = DiscountArbitrageStrategy()

    cb_arb = ConvertibleBondData(
        code="110002",
        name="折价转债",
        stock_code="000002",
        stock_name="测试股票2",
        date=date.today(),
        close=98.0,
        conversion_premium=-3.5,  # -3.5%折价
        conversion_value=101.5,
    )

    opportunity = arb_strategy.check_opportunity(cb_arb)
    if opportunity:
        print(f"  发现套利机会!")
        print(f"  转债代码: {opportunity.cb_code}")
        print(f"  转股溢价率: {cb_arb.conversion_premium:.2f}%")
        print(f"  预期收益: {opportunity.expected_return:.2f}%")
        print(f"  成功概率: {opportunity.probability:.0f}%")


def example_hedge():
    """动态对冲示例"""
    print("\n" + "=" * 60)
    print("动态对冲策略示例")
    print("=" * 60)

    from app.sg_strategy.core.hedge import HedgeEngine
    from app.sg_strategy.core.timing import TimingSignal

    engine = HedgeEngine(aum=10000.0)

    # 模拟择时信号
    timing = TimingSignal(
        date=date.today(),
        total_score=25.0,  # 低分，需要启动对冲
        regime=MarketRegime.BEAR,
    )

    # 检查对冲条件
    should_hedge, reason = engine.check_hedge_conditions(
        timing_signal=timing,
        correlation=0.72,  # 高相关性
        index_ma20=400.0,
        index_current=385.0,  # 跌破均线
        index_ma_slope=-0.5,  # 斜率向下
    )

    print(f"\n对冲条件检查:")
    print(f"  择时得分: {timing.total_score:.1f}")
    print(f"  相关性: 0.72")
    print(f"  是否启动对冲: {'是' if should_hedge else '否'}")
    print(f"  原因: {reason}")

    if should_hedge:
        status = engine.activate_hedge(0.72, date.today())
        print(f"\n对冲方案:")
        print(f"  股指期货: {status.csi300_hedge_ratio*100:.0f}%")
        print(f"  认沽期权: {status.put_hedge_ratio*100:.0f}%")
        print(f"  纯债性转债: {status.pure_bond_ratio*100:.0f}%")

        cost = engine.calculate_hedge_cost(30)
        print(f"\n月度对冲成本:")
        print(f"  期货成本: {cost['futures_cost']:.2f}元")
        print(f"  期权成本: {cost['put_cost']:.2f}元")
        print(f"  总成本: {cost['total_cost']:.2f}元")


def run_all_examples():
    """运行所有示例"""
    example_basic_usage()
    example_scoring()
    example_timing()
    example_cost()
    example_events()
    example_hedge()

    print("\n" + "=" * 60)
    print("所有示例运行完成!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_examples()
