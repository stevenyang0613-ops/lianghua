"""
研究框架调度器: 4个框架协同使用

1. Serenity Alpha: 找线索 (新闻→假设)
2. TAM-Adj-PEG: 看估值 (成长股估值合理性)
3. GF-DMA Health Index: 看走势 (是否健康上涨)
4. Bayesian Intrinsic Growth: 看定价 (市场是否过度)

完整研究流程:
新闻 → Serenity Alpha找候选 → TAM-Adj-PEG筛估值 → GF-DMA看走势 → Bayesian定量化定价
"""

from dataclasses import dataclass, field
from typing import Optional

from app.framework.serenity_alpha import SerenityAlphaAnalyzer, Hypothesis
from app.framework.tam_adj_peg import TAMAdjPEGAanalyzer, GrowthValuation
from app.framework.gf_dma_health import GFDMAHealthAnalyzer, HealthReport
from app.framework.bayesian_intrinsic_growth import BayesianIntrinsicGrowthValuation, BayesianValuation


@dataclass
class IntegratedResearch:
    """集成研究报告"""
    code: str
    name: str
    final_verdict: str  # strong_buy / buy / hold / trim / sell
    final_score: float  # 0-100

    # 4个框架结果
    serenity: Optional[Hypothesis] = None
    tam_peg: Optional[GrowthValuation] = None
    dma_health: Optional[HealthReport] = None
    bayesian: Optional[BayesianValuation] = None

    # 综合判断
    synthesis: str = ""  # 综合解读
    key_insights: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    framework_alignment: dict = field(default_factory=dict)  # 各框架一致性


class ResearchOrchestrator:
    """研究框架调度器"""

    def __init__(self):
        self.serenity_analyzer = SerenityAlphaAnalyzer()
        self.tam_peg_analyzer = TAMAdjPEGAanalyzer()
        self.dma_analyzer = GFDMAHealthAnalyzer()
        self.bayesian_analyzer = BayesianIntrinsicGrowthValuation()

    def full_research(self, news: Optional[str], candidates: list[dict],
                     market_data: Optional[dict] = None) -> list[IntegratedResearch]:
        """
        完整研究流程

        参数:
        - news: 可选新闻文本，触发Serenity Alpha
        - candidates: 候选股票列表
        - market_data: 行情数据(可选)
        """
        results = []

        # 步骤1: Serenity Alpha (如果提供新闻)
        hypothesis_map = {}
        if news:
            hypotheses = self.serenity_analyzer.analyze(news, candidates)
            for h in hypotheses:
                hypothesis_map[h.code] = h

        # 步骤2-4: 对每个候选标的运行剩余3个框架
        for c in candidates:
            code = c.get('code', '')
            name = c.get('name', '')

            research = IntegratedResearch(code=code, name=name, final_verdict="hold", final_score=50.0)

            # 假设强度
            if code in hypothesis_map:
                research.serenity = hypothesis_map[code]

            # TAM-Adj-PEG
            try:
                research.tam_peg = self.tam_peg_analyzer.analyze(c)
            except Exception as e:
                research.tam_peg = None

            # GF-DMA Health
            try:
                health_data = {
                    "code": code, "name": name,
                    "prices": c.get('prices', []),
                    "current_price": c.get('current_price', 0),
                    "ma_20": c.get('ma_20', 0),
                    "ma_50": c.get('ma_50', 0),
                    "ma_100": c.get('ma_100', 0),
                    "ma_200": c.get('ma_200', 0),
                    "eps_growth": c.get('eps_growth_ltm', 0),
                    "revenue_growth": c.get('revenue_growth_ltm', 0),
                    "pe": c.get('pe', 30),
                    "analyst_rating_change": c.get('analyst_rating_change', 'stable'),
                }
                research.dma_health = self.dma_analyzer.analyze(health_data)
            except Exception as e:
                research.dma_health = None

            # Bayesian Intrinsic Growth
            try:
                bayes_data = {
                    "code": code, "name": name,
                    "current_price": c.get('current_price', 0),
                    "eps_ttm": c.get('eps_ttm', 0),
                    "eps_growth_ltm": c.get('eps_growth_ltm', 15),
                    "revenue_growth_ltm": c.get('revenue_growth_ltm', 15),
                    "forward_eps": c.get('forward_eps', 0),
                    "analyst_target_price": c.get('analyst_target_price', 0),
                    "new_info": c.get('new_info', {}),
                    "sentiment_score": c.get('sentiment_score', 0),
                }
                research.bayesian = self.bayesian_analyzer.analyze(bayes_data)
            except Exception as e:
                research.bayesian = None

            # 综合判断
            self._synthesize(research)

            results.append(research)

        # 按最终得分排序
        results.sort(key=lambda r: r.final_score, reverse=True)
        return results

    def _synthesize(self, research: IntegratedResearch):
        """综合判断"""
        scores = []
        verdicts = []

        # 收集各框架的得分
        if research.tam_peg:
            peg_score = self._verdict_to_score(research.tam_peg.valuation_verdict)
            scores.append(("TAM-Adj-PEG", peg_score, research.tam_peg.valuation_verdict))

        if research.dma_health:
            health_score = research.dma_health.health_score
            scores.append(("DMA-Health", health_score, research.dma_health.recommendation))

        if research.bayesian:
            # mispricing -100~+100, 转 0~100
            bayes_score = 100 - research.bayesian.mispricing_score
            bayes_score = max(0, min(100, bayes_score))
            scores.append(("Bayesian", bayes_score, research.bayesian.recommendation))

        if research.serenity:
            serenity_score = research.serenity.hypothesis_strength
            scores.append(("Serenity", serenity_score, "informational"))

        # 加权综合
        weights = {"TAM-Adj-PEG": 0.30, "DMA-Health": 0.25, "Bayesian": 0.30, "Serenity": 0.15}
        total_score = 0
        total_weight = 0
        for name, score, _ in scores:
            w = weights.get(name, 0.20)
            total_score += score * w
            total_weight += w

        if total_weight > 0:
            research.final_score = total_score / total_weight

        # 最终判定
        if research.final_score >= 75:
            research.final_verdict = "strong_buy"
        elif research.final_score >= 60:
            research.final_verdict = "buy"
        elif research.final_score >= 40:
            research.final_verdict = "hold"
        elif research.final_score >= 25:
            research.final_verdict = "trim"
        else:
            research.final_verdict = "sell"

        # 框架一致性
        research.framework_alignment = {
            name: {"score": score, "verdict": verdict}
            for name, score, verdict in scores
        }

        # 综合解读
        research.synthesis = self._build_synthesis(research, scores)
        research.key_insights = self._extract_insights(research)
        research.action_items = self._generate_actions(research)

    def _verdict_to_score(self, verdict: str) -> float:
        """verdict → score"""
        return {
            "cheap": 90,
            "fair": 65,
            "expensive": 35,
            "bubble": 10,
        }.get(verdict, 50)

    def _build_synthesis(self, research: IntegratedResearch, scores: list) -> str:
        """构建综合解读"""
        parts = []

        if research.serenity:
            h = research.serenity
            parts.append(f"假设强度{h.hypothesis_strength:.0f}/100")

        if research.tam_peg:
            t = research.tam_peg
            parts.append(f"TAM-Adj-PEG估值{t.valuation_verdict} (调整PEG={t.tam_adj_peg})")

        if research.dma_health:
            d = research.dma_health
            parts.append(f"走势健康度{d.health_score:.0f}/100, 阶段={d.trend_phase}")

        if research.bayesian:
            b = research.bayesian
            parts.append(f"市场隐含增长{b.implied_growth_rate:.1f}% vs 真实增长{b.intrinsic_growth_rate:.1f}%")

        return " | ".join(parts) if parts else "数据不足"

    def _extract_insights(self, research: IntegratedResearch) -> list[str]:
        """提取关键洞察"""
        insights = []

        if research.bayesian:
            b = research.bayesian
            if b.mispricing_score < -30:
                insights.append(f"💎 显著低估: 内在价值{b.intrinsic_value} vs 当前价{b.current_price}, 上涨空间{b.upside_pct:.1f}%")
            elif b.mispricing_score > 30:
                insights.append(f"⚠️ 估值偏高: 市场可能已透支未来增长")

            if b.price_decomposition.get("sentiment", 0) > 40:
                insights.append(f"🎭 情绪驱动占比{b.price_decomposition['sentiment']:.0f}%, 警惕FOMO")

        if research.dma_health:
            d = research.dma_health
            if d.fomo_risk in ["high", "extreme"]:
                insights.append(f"🚨 FOMO风险{d.fomo_risk}, 短期超买")

            if d.ma_alignment == "perfect":
                insights.append(f"✨ 均线完美多头排列")

        if research.tam_peg:
            t = research.tam_peg
            if t.growth_quality == "high" and t.valuation_verdict in ["cheap", "fair"]:
                insights.append(f"🎯 高质量增长 + 合理估值, 优质标的")

        if research.serenity:
            s = research.serenity
            if s.hypothesis_strength >= 70:
                insights.append(f"📰 假设强度{s.hypothesis_strength:.0f}, 新闻催化强")

        return insights

    def _generate_actions(self, research: IntegratedResearch) -> list[str]:
        """生成行动建议"""
        actions = []

        if research.final_verdict == "strong_buy":
            actions.append("✅ 建议建仓: 综合评分优秀")
            actions.append("📋 关注基本面催化剂兑现进度")
        elif research.final_verdict == "buy":
            actions.append("✅ 可分批建仓, 控制单笔仓位")
        elif research.final_verdict == "hold":
            actions.append("⏸️ 持有观察, 不建议加仓")
        elif research.final_verdict == "trim":
            actions.append("🔻 建议减仓, 锁定部分利润")
        elif research.final_verdict == "sell":
            actions.append("❌ 建议清仓, 避免进一步损失")

        # 框架冲突时的特殊建议
        verdicts_list = [info.get("verdict") for info in research.framework_alignment.values()]
        if len(set(verdicts_list)) >= 3:
            actions.append("⚖️ 框架间分歧较大, 建议降低仓位, 等待信号一致")

        return actions
