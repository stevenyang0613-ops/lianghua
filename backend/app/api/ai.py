"""
AI 分析 API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum
import httpx
import json
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# 日志降噪：60 秒内相同原因的失败不重复记录
_log_last_fail_ts: float = 0.0
_log_last_fail_key: str = ""
_LOG_SUPPRESS_SECONDS = 60


def _should_log_failure(key: str) -> bool:
    """判断是否应该记录本次失败日志（60 秒内相同 key 只记录一次）"""
    import time
    global _log_last_fail_ts, _log_last_fail_key
    now = time.time()
    if key == _log_last_fail_key and (now - _log_last_fail_ts) < _LOG_SUPPRESS_SECONDS:
        return False
    _log_last_fail_key = key
    _log_last_fail_ts = now
    return True


class AnalysisType(str, Enum):
    market = "market"
    signal = "signal"
    strategy = "strategy"
    risk = "risk"
    sentiment = "sentiment"

class AnalysisRequest(BaseModel):
    type: AnalysisType
    context: Dict[str, Any]
    question: Optional[str] = None
    language: str = "zh"

class AnalysisResult(BaseModel):
    id: str
    type: AnalysisType
    summary: str
    insights: List[str]
    recommendations: List[str]
    confidence: float
    warnings: Optional[List[str]] = None
    generatedAt: str

@router.post("/analyze", response_model=AnalysisResult)
async def analyze(request: AnalysisRequest):
    """执行 AI 分析 — 外部 AI 不可用时自动回退到基于规则的分析"""
    import uuid
    from datetime import datetime, timezone

    # 构建提示词
    prompt = build_prompt(request)

    # 尝试调用外部 AI 模型；失败时回退到基于规则的分析
    try:
        response_text = await call_ai_model(prompt)
        result = parse_response(response_text, request.type)
    except HTTPException as e:
        logger.warning(f"[AI] 外部 AI 服务不可用 ({e.status_code}: {e.detail})，回退到基于规则的分析")
        result = generate_fallback_analysis(request)
    except Exception as e:
        logger.warning(f"[AI] 外部 AI 调用异常 ({e})，回退到基于规则的分析")
        result = generate_fallback_analysis(request)

    return AnalysisResult(
        id=str(uuid.uuid4()),
        type=request.type,
        summary=result["summary"],
        insights=result["insights"],
        recommendations=result["recommendations"],
        confidence=result["confidence"],
        warnings=result.get("warnings"),
        generatedAt=datetime.now(timezone.utc).isoformat(),
    )

class SentimentRequest(BaseModel):
    symbols: List[str]
    data: Optional[Dict[str, Any]] = None

@router.post("/sentiment")
async def analyze_sentiment(request: SentimentRequest):
    """市场情绪分析 — 外部 AI 不可用时回退到基于规则的情绪评分"""
    symbols = request.symbols
    data = request.data
    # 构建情绪分析提示词
    prompt = f"""分析以下标的的市场情绪：{', '.join(symbols)}

请提供：
1. 整体市场情绪判断（看涨/看跌/中性）
2. 情绪驱动因素
3. 资金流向分析
4. 市场预期
"""

    try:
        response = await call_ai_model(prompt)
    except HTTPException:
        logger.warning("[AI] 外部 AI 服务不可用，回退到基于规则的情绪分析")
        return _generate_fallback_sentiment(symbols)
    except Exception as e:
        logger.warning(f"[AI] 外部 AI 调用异常 ({e})，回退到基于规则的情绪分析")
        return _generate_fallback_sentiment(symbols)

    # 解析情绪分数
    score = extract_sentiment_score(response)
    overall = "bullish" if score > 20 else "bearish" if score < -20 else "neutral"

    return {
        "overall": overall,
        "score": score,
        "factors": extract_factors(response),
        "analysis": response,
    }

@router.post("/signal/explain")
async def explain_signal(signal_data: Dict[str, Any]):
    """信号解释 — 外部 AI 不可用时回退到基于规则的信号解读"""
    prompt = f"""解释以下交易信号：

{json.dumps(signal_data, indent=2, ensure_ascii=False)}

请提供：
1. 信号含义解释
2. 触发原因分析
3. 历史胜率（如有）
4. 建议的操作策略
5. 止损止盈建议
"""

    try:
        response = await call_ai_model(prompt)
    except HTTPException:
        logger.warning("[AI] 外部 AI 服务不可用，回退到基于规则的信号解读")
        return _generate_fallback_signal_explain(signal_data)
    except Exception as e:
        logger.warning(f"[AI] 外部 AI 调用异常 ({e})，回退到基于规则的信号解读")
        return _generate_fallback_signal_explain(signal_data)

    return {
        "signalId": signal_data.get("id", ""),
        "signalType": signal_data.get("type", "unknown"),
        "explanation": response,
        "suggestedActions": extract_actions(response),
    }

@router.post("/strategy/optimize")
async def optimize_strategy(strategy_data: Dict[str, Any]):
    """策略优化建议 — 外部 AI 不可用时回退到基于规则的建议"""
    prompt = f"""评估并优化以下交易策略：

{json.dumps(strategy_data, indent=2, ensure_ascii=False)}

请提供：
1. 策略优势分析
2. 策略劣势分析
3. 参数优化建议
4. 风险管理建议
5. 改进方向
"""

    try:
        response = await call_ai_model(prompt)
    except HTTPException:
        logger.warning("[AI] 外部 AI 服务不可用，回退到基于规则的策略优化")
        return _generate_fallback_strategy_optimize(strategy_data)
    except Exception as e:
        logger.warning(f"[AI] 外部 AI 调用异常 ({e})，回退到基于规则的策略优化")
        return _generate_fallback_strategy_optimize(strategy_data)

    return {
        "improvements": extract_improvements(response),
        "parameterSuggestions": {},
        "riskWarnings": extract_warnings(response),
        "analysis": response,
    }

@router.post("/risk/assess")
async def assess_risk(portfolio: Dict[str, Any]):
    """风险评估 — 外部 AI 不可用时回退到基于规则的风险评估"""
    prompt = f"""评估以下投资组合的风险：

{json.dumps(portfolio, indent=2, ensure_ascii=False)}

请提供：
1. 主要风险因素
2. 风险敞口分析
3. 相关性风险
4. 极端情景压力测试
5. 风险对冲建议
"""

    try:
        response = await call_ai_model(prompt)
    except HTTPException:
        logger.warning("[AI] 外部 AI 服务不可用，回退到基于规则的风险评估")
        return _generate_fallback_risk_assess(portfolio)
    except Exception as e:
        logger.warning(f"[AI] 外部 AI 调用异常 ({e})，回退到基于规则的风险评估")
        return _generate_fallback_risk_assess(portfolio)

    return {
        "riskScore": calculate_risk_score(response),
        "riskFactors": extract_risk_factors(response),
        "hedgeSuggestions": extract_hedge_suggestions(response),
        "analysis": response,
    }

def generate_fallback_analysis(request: AnalysisRequest) -> dict:
    """外部 AI 不可用时，基于规则生成分析结果"""
    context = request.context or {}
    analysis_type = request.type

    summary = ""
    insights: list[str] = []
    recommendations: list[str] = []
    warnings: list[str] = []
    confidence = 50.0

    if analysis_type == AnalysisType.market and context.get("industry"):
        # 行业轮动分析回退
        industry = str(context.get("industry", "该行业"))
        horizon = str(context.get("horizon", "short_term"))
        metrics = context.get("metrics", {}) or {}

        # 提取指标
        momentum = metrics.get("momentum", 0) if isinstance(metrics, dict) else 0
        flow = metrics.get("flow", 0) if isinstance(metrics, dict) else 0
        turnover = metrics.get("turnover", 0) if isinstance(metrics, dict) else 0
        quality = metrics.get("quality", 0) if isinstance(metrics, dict) else 0
        valuation = metrics.get("valuation", 0) if isinstance(metrics, dict) else 0
        total_score = metrics.get("total_score", 0) if isinstance(metrics, dict) else 0

        # 生成摘要（综合核心观点，限制在2-3句）
        horizon_cn = {"short_term": "短期", "mid_term": "中期", "long_term": "长期"}.get(horizon, "")
        score_level = "较强" if total_score >= 70 else "中等" if total_score >= 40 else "偏弱"
        summary = f"{industry}行业在{horizon_cn}维度综合表现{score_level}（评分{total_score:.0f}）。"

        # 附加核心观点到摘要
        key_points: list[str] = []
        if momentum >= 70:
            key_points.append("动量强势")
        elif momentum <= 30:
            key_points.append("动量偏弱")
        if flow >= 70:
            key_points.append("资金流入积极")
        elif flow <= 30:
            key_points.append("资金流出压力")
        if quality >= 70:
            key_points.append("基本面优质")
        if valuation >= 70:
            key_points.append("估值偏低有安全边际")
        elif valuation <= 30:
            key_points.append("估值偏高")
        if turnover >= 80:
            key_points.append("换手率极高波动大")

        if key_points:
            summary += "核心特征：" + "、".join(key_points) + "。"
        else:
            summary += "各项指标表现中性，暂无突出特征。"

        summary += "（基于规则的分析，未调用外部 AI）"

        # 动量分析
        if momentum >= 70:
            insights.append(f"动量因子表现强势（{momentum:.0f}分），行业趋势向上，短期动能充足。")
        elif momentum >= 40:
            insights.append(f"动量因子表现平稳（{momentum:.0f}分），行业趋势中性。")
        else:
            insights.append(f"动量因子表现偏弱（{momentum:.0f}分），行业趋势向下或盘整。")

        # 资金流向
        if flow >= 70:
            insights.append(f"资金流入积极（{flow:.0f}分），主力资金关注度较高。")
        elif flow >= 40:
            insights.append(f"资金流向中性（{flow:.0f}分），市场参与度一般。")
        else:
            insights.append(f"资金流出压力较大（{flow:.0f}分），需谨慎关注。")

        # 质量与估值
        if quality >= 70:
            insights.append(f"行业基本面质量较好（{quality:.0f}分），盈利能力和成长性支撑较强。")
        elif quality <= 30:
            insights.append(f"行业基本面质量偏弱（{quality:.0f}分），需关注盈利下滑风险。")

        if valuation >= 70:
            insights.append(f"估值水平较低（{valuation:.0f}分），具备安全边际。")
        elif valuation <= 30:
            insights.append(f"估值水平偏高（{valuation:.0f}分），注意估值回调风险。")

        # 换手率
        if turnover >= 80:
            warnings.append(f"换手率极高（{turnover:.0f}分），短期博弈情绪浓厚，波动风险加大。")
        elif turnover >= 60:
            warnings.append(f"换手率较高（{turnover:.0f}分），市场分歧较大，注意节奏控制。")

        # 综合建议
        if total_score >= 70:
            recommendations.append(f"{industry}行业{horizon_cn}综合评分较高，可作为重点配置方向。")
        elif total_score >= 40:
            recommendations.append(f"{industry}行业{horizon_cn}表现中等，建议保持标配或逢低布局。")
        else:
            recommendations.append(f"{industry}行业{horizon_cn}评分偏低，建议观望或降低仓位。")

        if warnings:
            recommendations.append("注意上述风险提示，建议控制单笔仓位。")

        # 置信度计算：多因子加权（动量 30% + 资金 25% + 质量 20% + 估值 15% + 换手率 10%）
        # 换手率反向：越高代表波动风险，降低置信度
        turnover_adj = max(0, 100 - turnover) if turnover else 50
        raw_confidence = (
            momentum * 0.30
            + flow * 0.25
            + quality * 0.20
            + valuation * 0.15
            + turnover_adj * 0.10
        )
        confidence = min(95.0, max(30.0, round(raw_confidence, 1)))

    elif analysis_type == AnalysisType.signal:
        summary = "交易信号已触发，但外部 AI 分析服务暂不可用，以下为基于规则的信号解读。"
        insights.append(f"信号类型: {context.get('action', 'unknown')}")
        insights.append(f"触发标的: {context.get('code', 'unknown')}")
        recommendations.append("建议结合当前市场环境与个人风险偏好审慎决策。")

    elif analysis_type == AnalysisType.strategy:
        summary = "策略评估已启用基于规则的分析，外部 AI 服务暂不可用。"
        insights.append("策略回测指标可供参考，重点观察夏普比率与最大回撤。")
        recommendations.append("建议在不同市场周期中验证策略稳健性后再实盘部署。")

    elif analysis_type == AnalysisType.risk:
        summary = "风险评估已启用基于规则的分析，外部 AI 服务暂不可用。"
        insights.append("组合波动率与集中度是核心监控指标。")
        recommendations.append("建议控制单一行业敞口不超过总资产的20%，并设置止损纪律。")

    else:
        summary = request.question or "分析完成（基于规则）"
        insights.append("外部 AI 分析服务暂不可用，当前为基于规则的分析结果。")
        recommendations.append("建议后续配置 OpenAI 或 DeepSeek API 密钥以获取更深度分析。")

    return {
        "summary": summary,
        "insights": insights if insights else ["暂无详细分析，数据不足。"],
        "recommendations": recommendations if recommendations else ["建议关注后续数据更新。"],
        "confidence": confidence,
        "warnings": warnings if warnings else None,
    }


def _generate_fallback_sentiment(symbols: List[str]) -> dict:
    """基于规则的市场情绪分析回退"""
    return {
        "overall": "neutral",
        "score": 0,
        "factors": [
            {"name": "外部 AI 暂不可用", "impact": "neutral", "description": "已启用基于规则的情绪分析回退"},
            {"name": "数据有限", "impact": "neutral", "description": "无法获取实时情绪数据"},
        ],
        "analysis": "外部 AI 服务暂不可用，建议后续配置 OpenAI 或 DeepSeek API 密钥以获取更深度情绪分析。当前无法判断市场情绪。",
    }


def _generate_fallback_signal_explain(signal_data: Dict[str, Any]) -> dict:
    """基于规则的信号解读回退"""
    action = signal_data.get("action", "unknown")
    code = signal_data.get("code", "unknown")
    name = signal_data.get("name", code)
    price = signal_data.get("price", 0)
    reason = signal_data.get("reason", "策略触发")

    action_cn = {"buy": "买入", "sell": "卖出", "hold": "持有"}.get(action, action)
    explanation = (
        f"【{name}（{code}）】触发{action_cn}信号，参考价 {price}。"
        f"触发原因：{reason}。"
        "（外部 AI 暂不可用，此为基于规则的信号说明。）"
    )
    suggested_actions = [
        {
            "action": action if action in ("buy", "sell", "hold") else "hold",
            "confidence": 60,
            "reason": f"基于{reason}触发，建议核实后再操作",
        }
    ]
    return {
        "signalId": signal_data.get("id", ""),
        "signalType": signal_data.get("type", "unknown"),
        "explanation": explanation,
        "suggestedActions": suggested_actions,
    }


def _generate_fallback_strategy_optimize(strategy_data: Dict[str, Any]) -> dict:
    """基于规则的策略优化回退"""
    strategy_name = strategy_data.get("name", "未知策略")
    return {
        "improvements": [
            "建议在不同市场环境（牛市/熊市/震荡）中分别测试策略表现",
            "建议增加参数敏感性分析，避免过拟合",
        ],
        "parameterSuggestions": {},
        "riskWarnings": [
            "历史回测不代表未来表现，实盘前需充分验证",
            "注意控制单笔仓位和最大回撤",
        ],
        "analysis": (
            f"【{strategy_name}】策略优化建议（外部 AI 暂不可用，基于规则回退）：\n"
            "1. 建议检查策略在极端行情下的表现\n"
            "2. 关注参数优化是否导致过拟合\n"
            "3. 建议设置合理的止损和仓位控制机制"
        ),
    }


def _generate_fallback_risk_assess(portfolio: Dict[str, Any]) -> dict:
    """基于规则的风险评估回退"""
    positions = portfolio.get("positions", []) or []
    total_value = portfolio.get("total_value", 0)
    risk_factors = []
    if len(positions) > 5:
        risk_factors.append(f"持仓集中度：共 {len(positions)} 个标的，需关注单一标的风险敞口")
    if total_value > 0:
        risk_factors.append(f"组合总市值：{total_value}，建议按总资产的5%-10%分批建仓")
    risk_factors.append("外部 AI 暂不可用，无法计算精确的 VaR 或 CVaR 指标")

    return {
        "riskScore": 50,
        "riskFactors": risk_factors if risk_factors else ["数据不足，无法评估风险"],
        "hedgeSuggestions": [
            "建议通过股指期货或期权对冲系统性风险",
            "控制单一行业敞口不超过总资产20%",
        ],
        "analysis": (
            "风险评估（基于规则回退）：\n"
            + ("\n".join(risk_factors) if risk_factors else "数据不足")
            + "\n\n建议配置 OpenAI 或 DeepSeek API 密钥以获取更精准的风险评估。"
        ),
    }

def build_prompt(request: AnalysisRequest) -> str:
    """构建分析提示词"""
    language = "中文" if request.language == "zh" else "English"

    base_prompt = f"你是一个专业的可转债量化交易分析师。请用{language}回答。\n\n"

    if request.type == AnalysisType.market:
        return base_prompt + f"""分析以下市场情况：
{json.dumps(request.context, indent=2, ensure_ascii=False)}

请提供市场趋势分析、关键位、技术指标解读和交易建议。"""

    elif request.type == AnalysisType.signal:
        return base_prompt + f"""解释以下交易信号：
{json.dumps(request.context, indent=2, ensure_ascii=False)}

请提供信号含义、触发原因、历史表现和操作建议。"""

    elif request.type == AnalysisType.strategy:
        return base_prompt + f"""评估以下交易策略：
{json.dumps(request.context, indent=2, ensure_ascii=False)}

请提供策略优劣势、适用场景和改进建议。"""

    elif request.type == AnalysisType.risk:
        return base_prompt + f"""分析以下投资组合的风险：
{json.dumps(request.context, indent=2, ensure_ascii=False)}

请提供风险评估、敞口分析和风险管理建议。"""

    return base_prompt + request.question or "请分析当前情况。"

async def call_ai_model(prompt: str) -> str:
    """调用 AI 模型 — 优先 OpenAI，备选 DeepSeek；失败时抛出异常供上层回退"""
    from app.config import settings

    errors: list[str] = []

    # 优先使用 OpenAI
    if settings.OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.OPENAI_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={
                        "model": settings.OPENAI_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2000,
                    },
                    timeout=60.0,
                )
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"]
                else:
                    err_detail = f"OpenAI HTTP {response.status_code}"
                    try:
                        err_body = response.json()
                        if "error" in err_body:
                            err_detail += f": {err_body['error'].get('message', '')}"
                    except Exception:
                        pass
                    errors.append(err_detail)
                    if _should_log_failure(f"openai_{err_detail}"):
                        logger.warning(f"[AI] OpenAI 调用失败: {err_detail}")
        except Exception as e:
            errors.append(f"OpenAI 异常: {e}")
            if _should_log_failure(f"openai_exc_{type(e).__name__}"):
                logger.warning(f"[AI] OpenAI 调用异常: {e}")
    else:
        errors.append("OpenAI API 密钥未配置")
        if _should_log_failure("openai_no_key"):
            logger.debug("[AI] OpenAI API 密钥未配置，跳过")

    # 备选 DeepSeek
    if settings.DEEPSEEK_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.DEEPSEEK_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                    json={
                        "model": settings.DEEPSEEK_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2000,
                    },
                    timeout=60.0,
                )
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"]
                else:
                    err_detail = f"DeepSeek HTTP {response.status_code}"
                    try:
                        err_body = response.json()
                        if "error" in err_body:
                            err_detail += f": {err_body['error'].get('message', '')}"
                    except Exception:
                        pass
                    errors.append(err_detail)
                    if _should_log_failure(f"deepseek_{err_detail}"):
                        logger.warning(f"[AI] DeepSeek 调用失败: {err_detail}")
        except Exception as e:
            errors.append(f"DeepSeek 异常: {e}")
            if _should_log_failure(f"deepseek_exc_{type(e).__name__}"):
                logger.warning(f"[AI] DeepSeek 调用异常: {e}")
    else:
        errors.append("DeepSeek API 密钥未配置")
        if _should_log_failure("deepseek_no_key"):
            logger.debug("[AI] DeepSeek API 密钥未配置，跳过")

    # 第三选择 Minimax（OpenAI 兼容格式）
    if settings.MINIMAX_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.MINIMAX_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.MINIMAX_API_KEY}"},
                    json={
                        "model": settings.MINIMAX_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2000,
                    },
                    timeout=60.0,
                )
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"]
                else:
                    err_detail = f"Minimax HTTP {response.status_code}"
                    try:
                        err_body = response.json()
                        if "error" in err_body:
                            err_detail += f": {err_body['error'].get('message', '')}"
                    except Exception:
                        pass
                    errors.append(err_detail)
                    if _should_log_failure(f"minimax_{err_detail}"):
                        logger.warning(f"[AI] Minimax 调用失败: {err_detail}")
        except Exception as e:
            errors.append(f"Minimax 异常: {e}")
            if _should_log_failure(f"minimax_exc_{type(e).__name__}"):
                logger.warning(f"[AI] Minimax 调用异常: {e}")
    else:
        errors.append("Minimax API 密钥未配置")
        if _should_log_failure("minimax_no_key"):
            logger.debug("[AI] Minimax API 密钥未配置，跳过")

    # 所有 AI 服务均不可用，抛出异常让上层回退到基于规则的分析
    detail = "AI 分析服务暂不可用，已启用基于规则的分析。原因: " + "; ".join(errors)
    raise HTTPException(status_code=503, detail=detail)

def parse_response(response: str, analysis_type: AnalysisType) -> dict:
    """解析 AI 响应"""
    lines = response.split("\n")
    insights = []
    recommendations = []
    warnings = []

    for line in lines:
        line = line.strip()
        if line.startswith(("一、", "二、", "三、", "四、", "五、", "1.", "2.", "3.")):
            insights.append(line)
        elif "建议" in line or "推荐" in line:
            recommendations.append(line)
        elif "风险" in line or "警告" in line or "注意" in line:
            warnings.append(line)

    confidence = 70
    if "置信度" in response:
        import re
        match = re.search(r"置信度[：:]\s*(\d+)", response)
        if match:
            confidence = int(match.group(1))

    return {
        "summary": lines[0] if lines else response[:200],
        "insights": insights,
        "recommendations": recommendations,
        "confidence": confidence,
        "warnings": warnings if warnings else None,
    }

def extract_sentiment_score(text: str) -> int:
    """提取情绪分数"""
    positive_words = ["看涨", "积极", "利好", "上涨", "强势"]
    negative_words = ["看跌", "消极", "利空", "下跌", "弱势"]

    score = 0
    for word in positive_words:
        score += text.count(word) * 10
    for word in negative_words:
        score -= text.count(word) * 10

    return max(-100, min(100, score))

def extract_factors(text: str) -> list:
    """提取因素"""
    factors = []
    for line in text.split("\n"):
        if "因素" in line or "驱动" in line:
            factors.append({"name": line[:20], "impact": "neutral", "description": line})
    return factors[:5]

def extract_actions(text: str) -> list:
    """提取操作建议"""
    actions = []
    for line in text.split("\n"):
        if "建议" in line or "操作" in line:
            actions.append({
                "action": "buy" if "买入" in line else "sell" if "卖出" in line else "hold",
                "confidence": 70,
                "reason": line,
            })
    return actions

def extract_improvements(text: str) -> list:
    """提取改进建议"""
    return [line for line in text.split("\n") if "改进" in line or "优化" in line or "建议" in line]

def extract_warnings(text: str) -> list:
    """提取风险警告"""
    return [line for line in text.split("\n") if "风险" in line or "警告" in line]

def extract_risk_factors(text: str) -> list:
    """提取风险因素"""
    return [line for line in text.split("\n") if "风险" in line]

def extract_hedge_suggestions(text: str) -> list:
    """提取对冲建议"""
    return [line for line in text.split("\n") if "对冲" in line or "避险" in line]

def calculate_risk_score(text: str) -> int:
    """计算风险分数"""
    return 50  # 简化实现


@router.get("/stream")
async def stream_analyze():
    """兼容端点：AI 流式分析（前端 community.ts 调用）"""
    from app.engine import data_enrich as _de
    from datetime import datetime

    summary = {"analysis": []}
    try:
        # 1. 宏观数据摘要（来自 macro_data 缓存）
        try:
            from app.services.macro_data import macro_data_service
            if macro_data_service and macro_data_service.get_last_data():
                md = macro_data_service.get_last_data()
                summary["analysis"].append({
                    "type": "macro",
                    "title": "宏观环境",
                    "content": f"CPI={md.cpi_yoy:.1f}% PPI={md.ppi_yoy:.1f}% M2={md.m2_yoy:.1f}% 两融={md.margin_balance:.0f}亿",
                    "sentiment": "neutral" if abs(md.cpi_yoy) < 2 else ("positive" if md.cpi_yoy < 1 else "negative"),
                })
        except Exception as e:
            logger.debug(f"[AI] macro data unavailable: {e}")

        # 2. 北向资金摘要
        north_total = sum(v.get("net", 0) for v in (_de._north_map or {}).values() if isinstance(v, dict))
        summary["analysis"].append({
            "type": "fund_flow",
            "title": "北向资金",
            "content": f"今日净流入 {north_total/1e8:.1f} 亿元",
            "sentiment": "positive" if north_total > 0 else "negative",
        })

        # 3. 转债市场摘要
        cb_count = len(_de._spot_map) if _de._spot_map else 0
        if cb_count > 0:
            avg_ytm = sum(v.get("ytm", 0) for v in _de._spot_map.values() if isinstance(v, dict)) / max(cb_count, 1)
            summary["analysis"].append({
                "type": "market",
                "title": "转债市场",
                "content": f"覆盖 {cb_count} 只转债，平均YTM={avg_ytm:.2f}%",
                "sentiment": "neutral",
            })
    except Exception as e:
        logger.warning(f"[AI] Stream analysis generation failed: {e}")

    return {"status": "ok", "data": summary.get("analysis", []), "timestamp": datetime.now().isoformat()}
