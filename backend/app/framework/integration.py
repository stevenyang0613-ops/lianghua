"""
研报分析框架集成钩子

将4框架集成到 lianghua 的研报分析流:
1. NLP分析完成后自动调用 Serenity Alpha 拆解投资假设
2. 提取的候选标的自动调用 3框架评分
3. 风险信号自动触发风险预警回调

用法:
    from app.framework.integration import enhance_nlp_result

    # 在 nlp_analyzer.py 中:
    analysis = nlp_analyzer.analyze(text)
    enhanced = enhance_nlp_result(analysis, stock_pool=current_pool)
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EnhancedResearch:
    """增强后的研报分析结果"""
    original_analysis: Any  # 原始NLP结果
    hypotheses: List[Any] = field(default_factory=list)  # Serenity Alpha结果
    stock_evaluations: Dict[str, Any] = field(default_factory=dict)  # 3框架评分
    risk_alerts: List[Dict[str, Any]] = field(default_factory=list)
    framework_summary: str = ""
    action_recommendation: str = ""


def enhance_nlp_result(
    analysis: Any,
    stock_pool: Optional[List[Dict[str, Any]]] = None,
    news_text: Optional[str] = None,
) -> EnhancedResearch:
    """
    增强研报分析结果: 自动调用4框架

    参数:
        analysis: nlp_analyzer的AnalysisResult
        stock_pool: 当前候选股票池
        news_text: 研报/新闻文本(可选,默认用analysis的title+summary)

    返回:
        EnhancedResearch 增强结果

    示例:
        >>> from app.research.nlp_analyzer import NLPAnalyzer
        >>> from app.framework.integration import enhance_nlp_result
        >>>
        >>> analyzer = NLPAnalyzer()
        >>> analysis = analyzer.analyze("AI液冷需求加速...")
        >>> enhanced = enhance_nlp_result(analysis, stock_pool=candidates)
        >>> print(enhanced.hypotheses[0].hypothesis_strength)
    """
    from app.framework.auto_trigger import get_trigger

    trigger = get_trigger()
    enhanced = EnhancedResearch(original_analysis=analysis)

    # 提取新闻文本
    if not news_text:
        title = getattr(analysis, "title", "") or ""
        summary = getattr(analysis, "summary", "") or ""
        key_points = " ".join(getattr(analysis, "key_points", []) or [])
        news_text = f"{title}。{summary}。{key_points}"

    # 如果没传股票池,从NLP提取的实体构造
    if not stock_pool:
        stock_pool = _extract_candidates_from_nlp(analysis)

    # 1. 自动触发 Serenity Alpha
    try:
        if news_text and stock_pool:
            hypotheses = trigger.on_news(news_text, stock_pool)
            if hypotheses:
                enhanced.hypotheses = hypotheses
                logger.info(f"Serenity Alpha: 找到{len(hypotheses)}个假设, 顶部假设强度{hypotheses[0].hypothesis_strength}")
    except Exception as e:
        logger.error(f"Serenity Alpha集成失败: {e}")

    # 2. 对假设顶部3个标的自动调3框架评估
    try:
        from app.framework.api import full_research
        if enhanced.hypotheses:
            top_candidates = []
            for h in enhanced.hypotheses[:5]:
                # 从原始candidates中找到对应的标的
                for c in stock_pool:
                    if c.get("code") == h.code:
                        top_candidates.append(c)
                        break

            if top_candidates:
                research_results = full_research(news_text, top_candidates)
                for r in research_results:
                    enhanced.stock_evaluations[r.code] = r

                    # 收集风险预警
                    if hasattr(r, "framework_alignment"):
                        for fname, finfo in r.framework_alignment.items():
                            if "bubble" in str(finfo.get("verdict", "")) or \
                               "expensive" in str(finfo.get("verdict", "")) or \
                               "sell" in str(finfo.get("verdict", "")):
                                enhanced.risk_alerts.append({
                                    "code": r.code,
                                    "name": r.name,
                                    "framework": fname,
                                    "verdict": finfo.get("verdict"),
                                    "score": finfo.get("score"),
                                    "message": f"{r.name}在{fname}框架被判定为{finfo.get('verdict')}"
                                })
    except Exception as e:
        logger.error(f"3框架评估失败: {e}")

    # 3. 生成综合摘要
    enhanced.framework_summary = _build_framework_summary(enhanced)
    enhanced.action_recommendation = _build_action_recommendation(enhanced)

    return enhanced


def _extract_candidates_from_nlp(analysis: Any) -> List[Dict[str, Any]]:
    """从NLP分析结果中提取候选标的"""
    candidates = []
    entities = getattr(analysis, "entities", {}) or {}

    # 优先从公司实体提取
    companies = entities.get("company") or entities.get("companies") or []
    stock_codes = entities.get("stock_code") or entities.get("stock_codes") or []

    for i, company in enumerate(companies[:20]):
        code = stock_codes[i] if i < len(stock_codes) else ""
        candidates.append({
            "code": code,
            "name": company,
            "industry": _infer_industry_from_topics(getattr(analysis, "topics", [])),
            "market_cap": 0,  # 未知
            "keywords": _infer_keywords_from_topics(getattr(analysis, "topics", [])),
        })

    # 如果没提取到候选,返回空列表
    return candidates


def _infer_industry_from_topics(topics: list) -> str:
    """从主题推断行业"""
    industry_keywords = {
        "AI": ["AI", "人工智能", "大模型", "GPU", "算力"],
        "AI数据中心液冷": ["液冷", "数据中心", "IDC", "服务器"],
        "半导体": ["芯片", "半导体", "晶圆", "光刻"],
        "新能源": ["新能源", "锂电", "光伏", "储能"],
        "医药": ["医药", "创新药", "CXO", "生物"],
        "机器人": ["机器人", "减速器", "伺服"],
    }
    topic_text = " ".join([t[0] if isinstance(t, tuple) else str(t) for t in topics or []])
    for ind, kws in industry_keywords.items():
        if any(kw in topic_text for kw in kws):
            return ind
    return "其他"


def _infer_keywords_from_topics(topics: list) -> List[str]:
    """从主题推断关键词"""
    keywords = []
    for t in topics or []:
        if isinstance(t, tuple):
            keywords.append(t[0])
        elif isinstance(t, str):
            keywords.append(t)
    return keywords[:5]


def _build_framework_summary(enhanced: EnhancedResearch) -> str:
    """构建框架摘要"""
    parts = []
    if enhanced.hypotheses:
        h = enhanced.hypotheses[0]
        parts.append(f"Serenity Alpha: 顶部假设{h.name}({h.hypothesis_strength:.0f}/100)")

    if enhanced.stock_evaluations:
        avg_score = sum(
            getattr(r, "final_score", 50) for r in enhanced.stock_evaluations.values()
        ) / len(enhanced.stock_evaluations)
        parts.append(f"3框架综合评分: {avg_score:.0f}/100")

    if enhanced.risk_alerts:
        parts.append(f"⚠️ 风险预警: {len(enhanced.risk_alerts)}条")

    return " | ".join(parts) if parts else "框架未触发"


def _build_action_recommendation(enhanced: EnhancedResearch) -> str:
    """构建行动建议"""
    if not enhanced.hypotheses:
        return "无明确投资假设,观望"

    top_h = enhanced.hypotheses[0]
    top_eval = enhanced.stock_evaluations.get(top_h.code)

    if top_eval and hasattr(top_eval, "final_verdict"):
        verdict = top_eval.final_verdict
        action_map = {
            "strong_buy": f"✅ 强烈推荐关注: {top_h.name}, 综合评分{top_eval.final_score:.0f}/100",
            "buy": f"✅ 推荐关注: {top_h.name}, 综合评分{top_eval.final_score:.0f}/100",
            "hold": f"⏸️ 持有观察: {top_h.name}, 综合评分{top_eval.final_score:.0f}/100",
            "trim": f"🔻 建议减仓: {top_h.name}",
            "sell": f"❌ 建议清仓: {top_h.name}",
        }
        return action_map.get(verdict, f"建议关注: {top_h.name} (强度{top_h.hypothesis_strength:.0f})")

    return f"建议关注: {top_h.name} (假设强度{top_h.hypothesis_strength:.0f}/100)"


# ============================================================
# 策略入池钩子
# ============================================================

def on_strategy_pool_add(stock_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    策略入池钩子: 当新标的进入策略观察池时自动触发3框架评估

    用法:
        # 在 strategy/service.py 中
        from app.framework.integration import on_strategy_pool_add

        async def add_to_pool(stock):
            result = on_strategy_pool_add(stock)
            if result and result.get("risk_alerts"):
                await send_alert(result["risk_alerts"])
    """
    from app.framework.auto_trigger import get_trigger

    trigger = get_trigger()
    result = trigger.on_stock_added_to_pool(stock_data)

    if result and result.get("risk_alerts"):
        logger.warning(f"标的{stock_data.get('code')}入池触发{len(result['risk_alerts'])}条风险预警")

    return result


# ============================================================
# 每日报告钩子
# ============================================================

def enhance_daily_report(report: Any, holdings: List[Dict[str, Any]]) -> Any:
    """
    每日报告增强: 自动添加4框架分析章节

    用法:
        # 在 reporting/daily_report.py 中
        from app.framework.integration import enhance_daily_report

        def generate_daily_report():
            report = build_base_report()
            holdings = get_today_holdings()
            report = enhance_daily_report(report, holdings)
            return report
    """
    from app.framework.auto_trigger import get_trigger

    trigger = get_trigger()
    framework_summary = trigger.daily_scan(holdings)

    # 添加到报告
    if hasattr(report, "add_section"):
        report.add_section("4框架综合分析", framework_summary)

    return report


# ============================================================
# 快速健康检查
# ============================================================

def quick_health_check() -> Dict[str, Any]:
    """快速健康检查(供业务系统调用)"""
    from app.framework.api import health_check
    return health_check()
