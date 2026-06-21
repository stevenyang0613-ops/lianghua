"""
4个投资研究框架的CLI入口

用法:
    python3 -m app.framework.cli news "AI数据中心需求爆发"
    python3 -m app.framework.cli analyze --code 002335 --industry AI
    python3 -m app.framework.cli full --news "AI液冷需求上升" --codes 002335,300442
    python3 -m app.framework.cli test  # 跑全部测试
"""

import sys
import json
import argparse

sys.path.insert(0, '/Users/mac/lianghua/backend')


def cmd_news(args):
    """Serenity Alpha: 解析新闻找假设"""
    from app.framework.serenity_alpha import SerenityAlphaAnalyzer

    print(f"\n📰 新闻: {args.text}\n")

    candidates = [
        {"code": "002335", "name": "英维克", "industry": "AI数据中心液冷",
         "market_cap": 180, "keywords": ["液冷", "数据中心", "散热"]},
        {"code": "300442", "name": "润泽科技", "industry": "AI",
         "market_cap": 350, "keywords": ["IDC", "数据中心"]},
        {"code": "300394", "name": "天孚通信", "industry": "AI",
         "market_cap": 280, "keywords": ["光模块", "AI"]},
        {"code": "002415", "name": "海康威视", "industry": "AI",
         "market_cap": 3500, "keywords": ["视频监控", "AI视觉"]},
    ]

    analyzer = SerenityAlphaAnalyzer()
    hypotheses = analyzer.analyze(args.text, candidates)

    print("=" * 70)
    print("🔍 投资假设分析 (按强度排序)")
    print("=" * 70)

    for i, h in enumerate(hypotheses, 1):
        print(f"\n{i}. {h.name} ({h.code})")
        print(f"   假设强度: {h.hypothesis_strength}/100")
        print(f"   信心: {h.confidence}")
        print(f"   小市值弹性: {'✓' if h.market_cap_eligible else '✗'}")
        print(f"   传导路径: {' → '.join(h.chain_path)}")
        print(f"   财务催化: {h.financial_catalyst}")
        print(f"   验证路径: {', '.join(h.verification_path[:3])}")
        print(f"   风险点: {', '.join(h.risks)}")


def cmd_analyze(args):
    """单个标的分析"""
    from app.framework.tam_adj_peg import TAMAdjPEGAanalyzer
    from app.framework.gf_dma_health import GFDMAHealthAnalyzer
    from app.framework.bayesian_intrinsic_growth import BayesianIntrinsicGrowthValuation

    # 这里简化处理,实际应该从数据库获取真实数据
    print(f"\n📊 分析 {args.code} ({args.industry})")
    print("(演示模式: 使用模拟数据)")


def cmd_full(args):
    """完整研究流程"""
    from app.framework.orchestrator import ResearchOrchestrator

    news = args.news or "AI数据中心需求加速,液冷渗透率快速提升"

    candidates = [
        {
            "code": "002335", "name": "英维克",
            "industry": "AI数据中心液冷", "market_cap": 180,
            "keywords": ["液冷", "数据中心", "散热"],
            "pe": 35, "growth_rate": 50,
            "gross_margin": 32, "operating_margin": 18,
            "market_share": 0.15,
            "moat_indicators": {"brand": 7, "tech": 8, "scale": 6, "network": 6},
        },
        {
            "code": "300442", "name": "润泽科技",
            "industry": "AI", "market_cap": 350,
            "keywords": ["IDC", "数据中心"],
            "pe": 28, "growth_rate": 35,
            "gross_margin": 30, "operating_margin": 20,
            "market_share": 0.08,
            "moat_indicators": {"brand": 6, "tech": 6, "scale": 8, "network": 5},
        },
    ]

    # 填充价格数据
    prices = [10.0 + i*0.05 for i in range(250)]
    for c in candidates:
        c.update({
            "prices": prices,
            "current_price": prices[-1],
            "ma_20": prices[-20],
            "ma_50": prices[-50],
            "ma_100": prices[-100],
            "ma_200": prices[-200],
            "eps_growth_ltm": 40,
            "revenue_growth_ltm": 45,
            "analyst_rating_change": "upgraded",
            "eps_ttm": 1.5,
            "forward_eps": 2.0,
            "analyst_target_price": 50.0,
            "new_info": {"order_book_growth": 0.4, "revenue_beat": 0.2},
            "sentiment_score": 0.3,
        })

    print(f"\n🔬 集成研究: 新闻={news}\n")
    orchestrator = ResearchOrchestrator()
    results = orchestrator.full_research(news, candidates)

    print("=" * 70)
    print("📋 综合研究报告")
    print("=" * 70)

    for r in results:
        print(f"\n🎯 {r.name}({r.code})")
        print(f"   最终判定: {r.final_verdict} (评分: {r.final_score:.1f}/100)")
        print(f"   综合解读: {r.synthesis}")
        print(f"\n   关键洞察:")
        for insight in r.key_insights:
            print(f"      {insight}")
        print(f"\n   行动建议:")
        for action in r.action_items:
            print(f"      {action}")
        print(f"\n   框架一致性:")
        for name, info in r.framework_alignment.items():
            print(f"      {name}: {info['score']:.0f}/100 → {info['verdict']}")


def cmd_test(args):
    """运行全部测试"""
    from app.framework.test_frameworks import main
    main()


def main():
    parser = argparse.ArgumentParser(
        description="LiangHua 投资研究框架 CLI",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest='command', help='命令')

    # news
    p_news = subparsers.add_parser('news', help='Serenity Alpha: 新闻→假设')
    p_news.add_argument('text', help='新闻文本')
    p_news.set_defaults(func=cmd_news)

    # analyze
    p_analyze = subparsers.add_parser('analyze', help='单个标的分析')
    p_analyze.add_argument('--code', required=True)
    p_analyze.add_argument('--industry', default='其他')
    p_analyze.set_defaults(func=cmd_analyze)

    # full
    p_full = subparsers.add_parser('full', help='完整研究流程')
    p_full.add_argument('--news', help='新闻文本')
    p_full.add_argument('--codes', help='候选代码,逗号分隔')
    p_full.set_defaults(func=cmd_full)

    # test
    p_test = subparsers.add_parser('test', help='运行全部测试')
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
