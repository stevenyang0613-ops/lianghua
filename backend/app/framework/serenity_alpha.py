"""
Serenity Alpha: 新闻→投资假设框架 V1.0

核心理念: AI 做投资研究最有价值的不是直接说"买什么"，
而是把一条新闻拆解成可验证的投资假设。

核心逻辑: 新闻 → 真实需求 → 财务传导 → 小市值弹性 → 验证路径

输入: 一条新闻 + 候选标的列表
输出: 每个标的的"假设强度分" + 验证路径 + 风险点
"""

from dataclasses import dataclass, field
from typing import Optional
import re
import math


@dataclass
class Hypothesis:
    """投资假设"""
    code: str
    name: str
    hypothesis_strength: float  # 0-100 假设强度
    chain_path: list[str]  # 传导路径
    financial_catalyst: str  # 财务催化剂
    market_cap_eligible: bool  # 是否小市值弹性股
    verification_path: list[str]  # 验证路径(订单/收入/毛利率)
    risks: list[str]  # 风险点
    confidence: float  # 0-1


@dataclass
class NewsContext:
    """新闻上下文"""
    title: str
    summary: str
    theme: str  # AI/液冷/医药等
    direction: str  # bullish/bearish/neutral
    raw_keywords: list[str] = field(default_factory=list)


class SerenityAlphaAnalyzer:
    """Serenity Alpha: 新闻 → 投资假设拆解器"""

    # === 行业关键词库 ===
    THEME_CHAINS = {
        "AI": {
            "upstream": ["GPU", "光模块", "PCB", "服务器", "存储", "电源"],
            "midstream": ["液冷", "散热", "机柜", "ODM", "网络设备"],
            "downstream": ["数据中心", "云厂商", "IDC", "SaaS", "应用"],
            "financial_signals": ["订单", "出货量", "毛利率", "ASP", "新客户"]
        },
        "半导体": {
            "upstream": ["设备", "材料", "光刻胶", "硅片"],
            "midstream": ["设计", "制造", "封测"],
            "downstream": ["消费电子", "汽车电子", "AI芯片"],
            "financial_signals": ["产能利用率", "ASP", "库存周转", "新订单"]
        },
        "新能源": {
            "upstream": ["锂矿", "硅料", "正极材料"],
            "midstream": ["电池", "组件", "电芯"],
            "downstream": ["储能", "电动车", "光伏"],
            "financial_signals": ["出货量", "排产", "价格", "客户结构"]
        },
        "医药": {
            "upstream": ["原料药", "CXO", "试剂"],
            "midstream": ["创新药", "医疗器械"],
            "downstream": ["医院", "药店", "互联网医疗"],
            "financial_signals": ["临床进度", "获批", "进医保", "海外授权"]
        },
        "机器人": {
            "upstream": ["减速器", "伺服", "传感器", "丝杠"],
            "midstream": ["本体", "控制器", "集成"],
            "downstream": ["工业", "汽车", "服务"],
            "financial_signals": ["订单", "出货量", "良率", "客户验证"]
        }
    }

    # === 需求传导动词（识别"真实需求"）===
    DEMAND_VERBS = ["带动", "拉动", "驱动", "增长", "扩张", "放量", "渗透率提升", "加速"]

    # === 财务传导名词（识别"受益项"）===
    FINANCIAL_ITEMS = ["收入", "营收", "利润", "毛利", "订单", "出货", "销量", "份额", "ASP", "毛利率"]

    def __init__(self):
        self.hypotheses: list[Hypothesis] = []

    def parse_news(self, news_text: str) -> NewsContext:
        """解析新闻: 提取主题、方向、关键词"""
        keywords = re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+', news_text)

        # 主题识别
        theme = "其他"
        for t in self.THEME_CHAINS:
            if t in news_text or any(kw in news_text for kw in [t.lower(), t.upper()]):
                theme = t
                break

        # 方向判断
        bullish_signals = ["上升", "增长", "受益", "订单", "扩产", "突破", "放量", "加速", "新高"]
        bearish_signals = ["下滑", "下跌", "亏损", "砍单", "降价", "过剩", "疲软"]
        bull_score = sum(1 for s in bullish_signals if s in news_text)
        bear_score = sum(1 for s in bearish_signals if s in news_text)
        if bull_score > bear_score:
            direction = "bullish"
        elif bear_score > bull_score:
            direction = "bearish"
        else:
            direction = "neutral"

        return NewsContext(
            title=news_text[:100],
            summary=news_text,
            theme=theme,
            direction=direction,
            raw_keywords=keywords[:20]
        )

    def _estimate_market_cap_eligible(self, market_cap: float, theme: str) -> tuple[bool, float]:
        """小市值弹性判断"""
        # 不同主题的市值阈值
        threshold_map = {
            "AI": 200,        # 200亿以下算小市值
            "半导体": 300,
            "新能源": 500,
            "医药": 200,
            "机器人": 150,
            "其他": 300
        }
        threshold = threshold_map.get(theme, 300)
        eligible = market_cap < threshold
        # 弹性分 = 阈值/市值 * 100 (越小市值分越高)
        elasticity = min(100, (threshold / max(market_cap, 1)) * 50) if eligible else 0
        return eligible, elasticity

    def _build_chain_path(self, ctx: NewsContext, candidate_keywords: list[str]) -> list[str]:
        """构建传导路径"""
        chain_map = self.THEME_CHAINS.get(ctx.theme, {})
        chain = []

        for segment, items in chain_map.items():
            for item in items:
                if any(kw in item or item in kw for kw in candidate_keywords) or \
                   any(item in ctx.summary for item in [item]):
                    chain.append(f"{segment}: {item}")

        return chain[:3] if chain else [f"主题: {ctx.theme}", "需要进一步验证"]

    def _build_verification_path(self, ctx: NewsContext) -> list[str]:
        """构建验证路径"""
        signals = self.THEME_CHAINS.get(ctx.theme, {}).get("financial_signals", [])
        verifications = []
        for signal in signals[:4]:
            verifications.append(f"关注{signal}环比变化")
        return verifications

    def _extract_financial_catalyst(self, ctx: NewsContext, candidate: dict) -> str:
        """提取财务催化剂"""
        theme_signals = self.THEME_CHAINS.get(ctx.theme, {}).get("financial_signals", [])
        if theme_signals:
            main_signal = theme_signals[0]
            return f"假设需求传导至{candidate.get('industry', '相关业务')}的{main_signal}"
        return "需要进一步验证"

    def _identify_risks(self, ctx: NewsContext, candidate: dict) -> list[str]:
        """识别风险点"""
        risks = []
        market_cap = candidate.get('market_cap', 0)

        if market_cap < 30:
            risks.append("市值过小，流动性风险")

        # 主题相关风险
        theme_risks = {
            "AI": ["产能扩张过快", "客户集中度高", "技术迭代风险"],
            "半导体": ["周期下行风险", "地缘政治风险", "库存周期"],
            "新能源": ["价格战", "产能过剩", "海外政策风险"],
            "医药": ["临床失败风险", "政策风险", "竞争加剧"],
            "机器人": ["量产不及预期", "技术路线变化", "成本控制"]
        }
        risks.extend(theme_risks.get(ctx.theme, ["需关注行业整体景气度"])[:2])
        return risks

    def analyze(self, news_text: str, candidates: list[dict]) -> list[Hypothesis]:
        """
        主入口: 接收新闻 + 候选标的列表，返回假设强度排序

        candidates: [{"code": str, "name": str, "industry": str, "market_cap": float, "keywords": list}, ...]
        """
        ctx = self.parse_news(news_text)
        self.hypotheses = []

        for c in candidates:
            # 1. 行业相关性
            industry_match = self._calc_industry_match(ctx, c)

            # 2. 市值弹性
            mcap_eligible, elasticity = self._estimate_market_cap_eligible(c.get('market_cap', 0), ctx.theme)

            # 3. 财务传导强度（基于候选公司的业务关键词）
            financial_strength = self._calc_financial_strength(ctx, c)

            # 4. 需求真实性
            demand_real = self._calc_demand_realness(ctx)

            # 综合得分
            weights = {
                "industry": 0.30,
                "financial": 0.30,
                "elasticity": 0.25,
                "demand": 0.15
            }
            score = (
                industry_match * weights["industry"] +
                financial_strength * weights["financial"] +
                elasticity * weights["elasticity"] +
                demand_real * weights["demand"]
            )

            hypothesis = Hypothesis(
                code=c.get('code', ''),
                name=c.get('name', ''),
                hypothesis_strength=round(score, 2),
                chain_path=self._build_chain_path(ctx, c.get('keywords', [])),
                financial_catalyst=self._extract_financial_catalyst(ctx, c),
                market_cap_eligible=mcap_eligible,
                verification_path=self._build_verification_path(ctx),
                risks=self._identify_risks(ctx, c),
                confidence=round(min(1.0, score / 100), 2)
            )
            self.hypotheses.append(hypothesis)

        # 按强度排序
        self.hypotheses.sort(key=lambda h: h.hypothesis_strength, reverse=True)
        return self.hypotheses

    def _calc_industry_match(self, ctx: NewsContext, candidate: dict) -> float:
        """行业匹配度"""
        industry = candidate.get('industry', '')
        keywords = candidate.get('keywords', [])
        theme = ctx.theme

        score = 0.0
        if theme in industry or industry in theme:
            score += 60

        # 关键词匹配
        theme_kws = []
        for seg in self.THEME_CHAINS.get(theme, {}).values():
            if isinstance(seg, list):
                theme_kws.extend(seg)

        matches = sum(1 for kw in keywords if any(tk in kw or kw in tk for tk in theme_kws))
        score += min(40, matches * 15)

        return min(100, score)

    def _calc_financial_strength(self, ctx: NewsContext, candidate: dict) -> float:
        """财务传导强度"""
        keywords = candidate.get('keywords', [])
        text = ctx.summary

        score = 0.0
        for verb in self.DEMAND_VERBS:
            if verb in text:
                score += 5

        for item in self.FINANCIAL_ITEMS:
            if item in text and any(item in kw for kw in keywords):
                score += 15

        # 行业直接匹配
        if candidate.get('industry') in text:
            score += 20

        return min(100, score)

    def _calc_demand_realness(self, ctx: NewsContext) -> float:
        """需求真实性"""
        # 数字越多，需求越具体
        numbers = re.findall(r'\d+[%％]?', ctx.summary)
        base_score = min(40, len(numbers) * 10)

        # 包含时间维度
        time_keywords = ["Q1", "Q2", "Q3", "Q4", "明年", "今年", "半年", "季度"]
        time_score = sum(8 for kw in time_keywords if kw in ctx.summary)
        time_score = min(30, time_score)

        # 包含数据来源
        source_keywords = ["订单", "出货", "数据", "调研", "公告", "报告"]
        source_score = sum(5 for kw in source_keywords if kw in ctx.summary)
        source_score = min(30, source_score)

        return base_score + time_score + source_score
