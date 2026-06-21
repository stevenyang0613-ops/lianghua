"""
4个投资研究框架测试

覆盖:
1. Serenity Alpha: 新闻→假设拆解
2. TAM-Adj-PEG: 成长股估值
3. GF-DMA Health: 走势健康度
4. Bayesian Intrinsic Growth: 定价合理性
5. Orchestrator: 集成研究
"""

import sys
sys.path.insert(0, '/Users/mac/lianghua/backend')

from app.framework.serenity_alpha import SerenityAlphaAnalyzer
from app.framework.tam_adj_peg import TAMAdjPEGAanalyzer
from app.framework.gf_dma_health import GFDMAHealthAnalyzer
from app.framework.bayesian_intrinsic_growth import BayesianIntrinsicGrowthValuation
from app.framework.orchestrator import ResearchOrchestrator


def test_serenity_alpha():
    """测试1: Serenity Alpha - 新闻→假设"""
    print("\n" + "="*70)
    print("TEST 1: Serenity Alpha (新闻→投资假设)")
    print("="*70)

    news = "AI数据中心需求爆发,液冷渗透率快速提升,带动相关公司订单大幅增长,预计Q2环比加速"

    candidates = [
        {
            "code": "002335",
            "name": "英维克",
            "industry": "AI数据中心液冷",
            "market_cap": 180,
            "keywords": ["液冷", "数据中心", "散热", "机柜"],
        },
        {
            "code": "300442",
            "name": "润泽科技",
            "industry": "AI数据中心",
            "market_cap": 350,
            "keywords": ["IDC", "数据中心", "云计算"],
        },
        {
            "code": "002415",
            "name": "海康威视",
            "industry": "AI",
            "market_cap": 3500,
            "keywords": ["视频监控", "AI视觉"],
        },
    ]

    analyzer = SerenityAlphaAnalyzer()
    hypotheses = analyzer.analyze(news, candidates)

    for h in hypotheses[:3]:
        print(f"\n📰 {h.name}({h.code})")
        print(f"   假设强度: {h.hypothesis_strength}/100 (信心: {h.confidence})")
        print(f"   小市值弹性: {'✓' if h.market_cap_eligible else '✗'}")
        print(f"   传导路径: {' → '.join(h.chain_path)}")
        print(f"   财务催化: {h.financial_catalyst}")
        print(f"   验证路径: {', '.join(h.verification_path[:3])}")
        print(f"   风险点: {', '.join(h.risks)}")

    assert len(hypotheses) == 3
    assert hypotheses[0].hypothesis_strength > hypotheses[1].hypothesis_strength  # 应该按强度排序
    print("\n✅ Serenity Alpha 测试通过")


def test_tam_adj_peg():
    """测试2: TAM-Adj-PEG - 成长股估值"""
    print("\n" + "="*70)
    print("TEST 2: TAM-Adj-PEG (成长股估值)")
    print("="*70)

    # 测试案例: 高质量增长公司(便宜)
    stock1 = {
        "code": "300750",
        "name": "宁德时代",
        "industry": "新能源车",
        "pe": 25,
        "growth_rate": 35,
        "market_cap": 12000,
        "revenue": 4000,
        "market_share": 0.30,
        "gross_margin": 28,
        "operating_margin": 15,
        "moat_indicators": {"brand": 9, "tech": 9, "scale": 10, "network": 7}
    }

    # 测试案例: 高估值但弱护城河(贵)
    stock2 = {
        "code": "688XXX",
        "name": "某AI公司",
        "industry": "AI",
        "pe": 100,
        "growth_rate": 40,
        "market_cap": 200,
        "revenue": 50,
        "market_share": 0.02,
        "gross_margin": 35,
        "operating_margin": -5,  # 还在亏损
        "moat_indicators": {"brand": 4, "tech": 7, "scale": 3, "network": 5}
    }

    analyzer = TAMAdjPEGAanalyzer()

    for stock in [stock1, stock2]:
        result = analyzer.analyze(stock)
        print(f"\n📊 {stock['name']}")
        print(f"   传统PEG: {result.traditional_peg}")
        print(f"   TAM调整PEG: {result.tam_adj_peg}")
        print(f"   估值判定: {result.valuation_verdict}")
        print(f"   TAM分: {result.tam_score}/100")
        print(f"   跑道年数: {result.runway_years}年")
        print(f"   定价权: {result.pricing_power_score}/100")
        print(f"   利润率质量: {result.margin_quality_score}/100")
        print(f"   护城河: {result.moat_score}/100")
        print(f"   增长质量: {result.growth_quality}")
        print(f"   建议: {result.recommendation}")
        if result.key_risks:
            print(f"   风险: {', '.join(result.key_risks)}")

    print("\n✅ TAM-Adj-PEG 测试通过")


def test_gf_dma_health():
    """测试3: GF-DMA Health - 走势健康度"""
    print("\n" + "="*70)
    print("TEST 3: GF-DMA Health Index (走势健康度)")
    print("="*70)

    # 健康上涨的标的
    prices_healthy = [10.0 + i*0.05 + (i%7)*0.02 for i in range(250)]
    ma_20 = prices_healthy[-20] if len(prices_healthy) >= 20 else 22
    ma_50 = prices_healthy[-50] if len(prices_healthy) >= 50 else 21
    ma_100 = prices_healthy[-100] if len(prices_healthy) >= 100 else 20
    ma_200 = prices_healthy[-200] if len(prices_healthy) >= 200 else 19

    # 排序一下均线
    if ma_20 < ma_50:
        ma_20, ma_50 = ma_50, ma_20
    if ma_50 < ma_100:
        ma_50, ma_100 = ma_100, ma_50
    if ma_100 < ma_200:
        ma_100, ma_200 = ma_200, ma_100

    stock1 = {
        "code": "600519",
        "name": "贵州茅台",
        "prices": prices_healthy,
        "current_price": prices_healthy[-1],
        "ma_20": ma_20,
        "ma_50": ma_50,
        "ma_100": ma_100,
        "ma_200": ma_200,
        "eps_growth": 18,
        "revenue_growth": 15,
        "pe": 28,
        "analyst_rating_change": "stable"
    }

    # FOMO过热的标的
    prices_fomo = [10.0 + i*0.05 for i in range(200)] + [22.0 + i*0.3 for i in range(60)]
    fomo_ma = {
        20: sum(prices_fomo[-20:])/20,
        50: sum(prices_fomo[-50:])/50,
        100: sum(prices_fomo[-100:])/100,
        200: sum(prices_fomo[-200:])/200,
    }

    stock2 = {
        "code": "300XXX",
        "name": "某FOMO标的",
        "prices": prices_fomo,
        "current_price": prices_fomo[-1],
        "ma_20": fomo_ma[20] * 0.95,
        "ma_50": fomo_ma[50] * 0.85,
        "ma_100": fomo_ma[100] * 0.80,
        "ma_200": fomo_ma[200] * 0.75,
        "eps_growth": 5,
        "revenue_growth": 8,
        "pe": 80,
        "analyst_rating_change": "downgraded"
    }

    analyzer = GFDMAHealthAnalyzer()

    for stock in [stock1, stock2]:
        result = analyzer.analyze(stock)
        print(f"\n💚 {stock['name']}")
        print(f"   健康度评分: {result.health_score}/100")
        print(f"   趋势阶段: {result.trend_phase}")
        print(f"   均线排列: {result.ma_alignment}")
        print(f"   偏离警告: {result.ma_deviation_warning}")
        print(f"   基本面支撑: {result.fundamental_support}")
        print(f"   预期修正: {result.expectation_revision}")
        print(f"   FOMO风险: {result.fomo_risk}")
        print(f"   建议: {result.recommendation}")
        if result.warnings:
            for w in result.warnings:
                print(f"   {w}")
        print(f"   因子分解: {result.health_factors}")

    print("\n✅ GF-DMA Health 测试通过")


def test_bayesian_growth():
    """测试4: Bayesian Intrinsic Growth - 定价合理性"""
    print("\n" + "="*70)
    print("TEST 4: Bayesian Intrinsic Growth (定价合理性)")
    print("="*70)

    # 案例A: 显著低估(内在价值高于价格)
    stock1 = {
        "code": "000001",
        "name": "某低估价值股",
        "current_price": 15.0,
        "eps_ttm": 1.0,
        "eps_growth_ltm": 12,
        "revenue_growth_ltm": 10,
        "forward_eps": 1.15,
        "analyst_target_price": 22.0,
        "new_info": {
            "revenue_beat": 0.15,
            "guidance_raised": 0.3,
            "market_share_gain": 0.2,
        },
        "sentiment_score": -0.2  # 情绪偏空
    }

    # 案例B: 估值泡沫(隐含增长远超真实)
    stock2 = {
        "code": "300XXX",
        "name": "某FOMO标的",
        "current_price": 120.0,
        "eps_ttm": 1.0,
        "eps_growth_ltm": 25,
        "revenue_growth_ltm": 30,
        "forward_eps": 1.40,
        "analyst_target_price": 100.0,  # 分析师目标价低于当前价
        "new_info": {
            "price_pressure": 0.2,
            "competition": 0.3,
        },
        "sentiment_score": 0.7  # 情绪极乐观
    }

    analyzer = BayesianIntrinsicGrowthValuation()

    for stock in [stock1, stock2]:
        result = analyzer.analyze(stock)
        print(f"\n🎲 {stock['name']}")
        print(f"   当前价: {result.current_price}")
        print(f"   内在价值: {result.intrinsic_value}")
        print(f"   上涨空间: {result.upside_pct:+.1f}%")
        print(f"   市场隐含增长: {result.implied_growth_rate:.1f}%")
        print(f"   真实增长: {result.intrinsic_growth_rate:.1f}%")
        print(f"   定价偏差: {result.mispricing_score:+.1f}/100")
        print(f"   价格分解: 基本面{result.price_decomposition.get('fundamental', 0):.0f}% / 情绪{result.price_decomposition.get('sentiment', 0):.0f}%")
        print(f"   置信区间: {result.confidence_interval[0]:.1f} ~ {result.confidence_interval[1]:.1f}")
        print(f"   建议: {result.recommendation}")
        if result.intrinsic_drivers:
            print(f"   内在驱动: {result.intrinsic_drivers[0]}")
        print(f"   概率分布: {result.probability_distribution.get('base', {})}")

    print("\n✅ Bayesian Intrinsic Growth 测试通过")


def test_orchestrator():
    """测试5: 集成研究框架"""
    print("\n" + "="*70)
    print("TEST 5: 集成研究框架 (4框架协同)")
    print("="*70)

    news = "AI数据中心需求爆发,液冷渗透率快速提升,带动相关公司订单大幅增长"

    prices = [10.0 + i*0.05 for i in range(250)]
    candidates = [
        {
            "code": "002335",
            "name": "英维克",
            "industry": "AI数据中心液冷",
            "market_cap": 180,
            "keywords": ["液冷", "数据中心", "散热"],
            "pe": 35,
            "growth_rate": 50,
            "gross_margin": 32,
            "operating_margin": 18,
            "market_share": 0.15,
            "moat_indicators": {"brand": 7, "tech": 8, "scale": 6, "network": 6},
            "prices": prices,
            "current_price": prices[-1],
            "ma_20": prices[-20],
            "ma_50": prices[-50],
            "ma_100": prices[-100],
            "ma_200": prices[-200],
            "eps_growth_ltm": 45,
            "revenue_growth_ltm": 50,
            "analyst_rating_change": "upgraded",
            "eps_ttm": 1.5,
            "forward_eps": 2.0,
            "analyst_target_price": 60.0,
            "new_info": {"order_book_growth": 0.4, "revenue_beat": 0.2, "guidance_raised": 0.3},
            "sentiment_score": 0.4,
        }
    ]

    orchestrator = ResearchOrchestrator()
    results = orchestrator.full_research(news, candidates)

    for r in results:
        print(f"\n🎯 {r.name}({r.code})")
        print(f"   最终判定: {r.final_verdict} (评分 {r.final_score:.1f}/100)")
        print(f"   综合解读: {r.synthesis}")
        print(f"\n   关键洞察:")
        for insight in r.key_insights:
            print(f"      {insight}")
        print(f"\n   行动建议:")
        for action in r.action_items:
            print(f"      {action}")
        print(f"\n   框架一致性:")
        for name, info in r.framework_alignment.items():
            print(f"      {name}: 评分={info['score']:.0f}, 判定={info['verdict']}")

    print("\n✅ 集成研究框架测试通过")


def main():
    print("\n" + "🚀"*35)
    print("LiangHua 投资研究框架 - 4框架测试套件")
    print("🚀"*35)

    test_serenity_alpha()
    test_tam_adj_peg()
    test_gf_dma_health()
    test_bayesian_growth()
    test_orchestrator()

    print("\n" + "="*70)
    print("✅ 所有框架测试通过!")
    print("="*70)
    print("""
使用说明:
- Serenity Alpha: 看新闻找假设 (产业链线索)
- TAM-Adj-PEG: 看成长股估值合理性
- GF-DMA Health: 看走势是否健康
- Bayesian: 看市场定价是否过度

一句话总结:
- AI做投资研究,不是直接说"买什么"
- 而是帮你建立更稳定的研究框架
- 一条新闻→投资假设→估值判断→走势确认→定价验证
""")


if __name__ == "__main__":
    main()
