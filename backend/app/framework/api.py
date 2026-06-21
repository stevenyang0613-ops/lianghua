"""
4框架自动调用API - 集成到 lianghua 主程序

提供3种调用方式:
1. FastAPI REST 接口 (生产环境)
2. Python 函数接口 (编程调用)
3. CLI 入口 (命令行)
"""

import logging
from typing import Optional, List, Dict, Any

from app.framework.serenity_alpha import SerenityAlphaAnalyzer, Hypothesis
from app.framework.tam_adj_peg import TAMAdjPEGAanalyzer, GrowthValuation
from app.framework.gf_dma_health import GFDMAHealthAnalyzer, HealthReport
from app.framework.bayesian_intrinsic_growth import BayesianIntrinsicGrowthValuation, BayesianValuation
from app.framework.orchestrator import ResearchOrchestrator, IntegratedResearch

logger = logging.getLogger(__name__)


# ============================================================
# 单框架调用
# ============================================================

def analyze_news(news_text: str, candidates: List[Dict[str, Any]]) -> List[Hypothesis]:
    """
    Serenity Alpha: 新闻 → 投资假设

    使用场景: 看到一条行业新闻,想知道哪些公司真正受益

    参数:
        news_text: 新闻文本
        candidates: 候选标的列表
                   [{"code": str, "name": str, "industry": str,
                     "market_cap": float, "keywords": list}, ...]

    返回:
        按假设强度排序的Hypothesis列表

    示例:
        >>> candidates = [
        ...     {"code": "002335", "name": "英维克",
        ...      "industry": "AI数据中心液冷", "market_cap": 180,
        ...      "keywords": ["液冷", "数据中心"]}
        ... ]
        >>> hypotheses = analyze_news("AI液冷需求加速", candidates)
        >>> print(hypotheses[0].hypothesis_strength)
        48.39
    """
    analyzer = SerenityAlphaAnalyzer()
    return analyzer.analyze(news_text, candidates)


def analyze_valuation(stock: Dict[str, Any]) -> GrowthValuation:
    """
    TAM-Adj-PEG: 成长股估值合理性

    使用场景: 判断AI/半导体/机器人/SaaS等成长股估值是否合理

    参数:
        stock: 股票数据字典
              {"code": str, "name": str, "industry": str,
               "pe": float, "growth_rate": float(%), "market_cap": float,
               "gross_margin": float, "operating_margin": float,
               "market_share": float, "moat_indicators": dict}

    返回:
        GrowthValuation 对象

    示例:
        >>> stock = {"code": "300750", "name": "宁德时代", "industry": "新能源车",
        ...          "pe": 25, "growth_rate": 35, "market_cap": 12000,
        ...          "gross_margin": 28, "operating_margin": 15}
        >>> result = analyze_valuation(stock)
        >>> print(result.valuation_verdict)
        fair
    """
    analyzer = TAMAdjPEGAanalyzer()
    return analyzer.analyze(stock)


def analyze_trend(stock: Dict[str, Any]) -> HealthReport:
    """
    GF-DMA Health Index: 走势健康度

    使用场景: 判断股票上涨是健康上涨还是短线过热,回调是否健康

    参数:
        stock: 股票数据字典
              {"code": str, "name": str,
               "prices": list[float], "current_price": float,
               "ma_20/50/100/200": float,
               "eps_growth": float, "revenue_growth": float,
               "pe": float, "analyst_rating_change": str}

    返回:
        HealthReport 对象

    示例:
        >>> stock = {"code": "600519", "name": "贵州茅台",
        ...          "prices": [10.0 + i*0.05 for i in range(250)],
        ...          "current_price": 22.5, "ma_20": 22, "ma_50": 21,
        ...          "ma_100": 20, "ma_200": 19,
        ...          "eps_growth": 18, "revenue_growth": 15,
        ...          "pe": 28, "analyst_rating_change": "stable"}
        >>> result = analyze_trend(stock)
        >>> print(result.health_score)
        72.5
    """
    analyzer = GFDMAHealthAnalyzer()
    return analyzer.analyze(stock)


def analyze_pricing(stock: Dict[str, Any]) -> BayesianValuation:
    """
    Bayesian Intrinsic Growth: 定价合理性

    使用场景: 判断上涨是基本面驱动还是情绪FOMO,市场是否透支未来

    参数:
        stock: 股票数据字典
              {"code": str, "name": str,
               "current_price": float, "eps_ttm": float,
               "eps_growth_ltm": float(%), "forward_eps": float,
               "analyst_target_price": float,
               "new_info": dict (订单增长/指引上调等贝叶斯信息),
               "sentiment_score": float (-1 to +1)}

    返回:
        BayesianValuation 对象

    示例:
        >>> stock = {"code": "000001", "name": "低估股",
        ...          "current_price": 15.0, "eps_ttm": 1.0,
        ...          "eps_growth_ltm": 12, "forward_eps": 1.15,
        ...          "new_info": {"revenue_beat": 0.15, "guidance_raised": 0.3},
        ...          "sentiment_score": -0.2}
        >>> result = analyze_pricing(stock)
        >>> print(result.mispricing_score)
        -35.8
    """
    analyzer = BayesianIntrinsicGrowthValuation()
    return analyzer.analyze(stock)


# ============================================================
# 集成调用
# ============================================================

def full_research(news: Optional[str] = None,
                  candidates: Optional[List[Dict[str, Any]]] = None) -> List[IntegratedResearch]:
    """
    4框架协同: 完整研究流程

    流程:
    1. Serenity Alpha: 新闻找假设 (如果提供news)
    2. TAM-Adj-PEG: 看估值
    3. GF-DMA: 看走势
    4. Bayesian: 看定价
    5. 综合评分 + 投资建议

    参数:
        news: 可选新闻文本
        candidates: 候选标的列表(必填)

    返回:
        按综合评分排序的IntegratedResearch列表

    示例:
        >>> candidates = [{"code": "002335", "name": "英维克",
        ...                "industry": "AI", "market_cap": 180, ...}]
        >>> results = full_research(news="AI需求加速", candidates=candidates)
        >>> print(results[0].final_verdict)
        strong_buy
    """
    if not candidates:
        return []

    orchestrator = ResearchOrchestrator()
    return orchestrator.full_research(news, candidates)


def quick_screening(stock_codes: List[str], news: Optional[str] = None) -> Dict[str, Any]:
    """
    快速筛选: 对多个标的快速评估

    适用: 大量标的快速过滤,只做基础3框架评估(不调用Serenity)

    参数:
        stock_codes: 股票代码列表
        news: 可选新闻

    返回:
        简化报告字典
    """
    results = []
    for code in stock_codes:
        # 实际实现需要从数据库获取stock数据
        # 这里返回占位符
        results.append({"code": code, "status": "data_needed"})

    return {"codes": stock_codes, "results": results, "news": news}


# ============================================================
# 辅助函数
# ============================================================

def get_framework_help(framework: str = "") -> Dict[str, str]:
    """获取框架使用帮助"""
    helps = {
        "serenity": {
            "name": "Serenity Alpha",
            "use_when": "看到行业新闻,想找产业链投资线索",
            "input": "新闻文本 + 候选标的数据",
            "output": "假设强度评分 + 传导路径 + 验证路径",
            "example": 'analyze_news("AI液冷需求加速", [{"code": "002335", ...}])'
        },
        "tam_peg": {
            "name": "TAM-Adj-PEG",
            "use_when": "判断成长股估值是否合理",
            "input": "公司财务数据 (PE, growth_rate, gross_margin, etc.)",
            "output": "调整PEG + 估值判定 + 跑道年数 + 增长质量",
            "example": 'analyze_valuation({"code": "300750", "pe": 25, "growth_rate": 35, ...})'
        },
        "dma": {
            "name": "GF-DMA Health",
            "use_when": "判断股票走势是否健康,是否过热",
            "input": "价格序列 + 均线 + 基本面指标",
            "output": "健康度评分 + 趋势阶段 + FOMO风险 + 建议",
            "example": 'analyze_trend({"code": "600519", "prices": [...], "current_price": 22.5, ...})'
        },
        "bayesian": {
            "name": "Bayesian Intrinsic Growth",
            "use_when": "判断市场定价是否过度,上涨是否FOMO",
            "input": "当前价 + EPS + 增长信息 + 情绪分",
            "output": "内在价值 + 隐含增长率 + 定价偏差 + 价格分解",
            "example": 'analyze_pricing({"code": "000001", "current_price": 15.0, ...})'
        }
    }

    if framework and framework in helps:
        return helps[framework]
    return helps


# ============================================================
# 健康检查
# ============================================================

def health_check() -> Dict[str, Any]:
    """检查所有框架是否可用"""
    status = {
        "all_available": True,
        "frameworks": {}
    }

    try:
        SerenityAlphaAnalyzer()
        status["frameworks"]["serenity_alpha"] = "available"
    except Exception as e:
        status["frameworks"]["serenity_alpha"] = f"error: {e}"
        status["all_available"] = False

    try:
        TAMAdjPEGAanalyzer()
        status["frameworks"]["tam_adj_peg"] = "available"
    except Exception as e:
        status["frameworks"]["tam_adj_peg"] = f"error: {e}"
        status["all_available"] = False

    try:
        GFDMAHealthAnalyzer()
        status["frameworks"]["gf_dma_health"] = "available"
    except Exception as e:
        status["frameworks"]["gf_dma_health"] = f"error: {e}"
        status["all_available"] = False

    try:
        BayesianIntrinsicGrowthValuation()
        status["frameworks"]["bayesian_growth"] = "available"
    except Exception as e:
        status["frameworks"]["bayesian_growth"] = f"error: {e}"
        status["all_available"] = False

    try:
        ResearchOrchestrator()
        status["frameworks"]["orchestrator"] = "available"
    except Exception as e:
        status["frameworks"]["orchestrator"] = f"error: {e}"
        status["all_available"] = False

    return status


if __name__ == "__main__":
    # 健康检查
    print("🔍 框架健康检查:\n")
    health = health_check()
    for name, state in health["frameworks"].items():
        emoji = "✅" if state == "available" else "❌"
        print(f"  {emoji} {name}: {state}")
    print(f"\n{'✅ 所有框架可用' if health['all_available'] else '❌ 部分框架异常'}")
