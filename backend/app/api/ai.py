"""
AI 分析 API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum
import httpx
import json

router = APIRouter()

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
    """执行 AI 分析"""
    import uuid
    from datetime import datetime, timezone

    # 构建提示词
    prompt = build_prompt(request)

    # 调用 AI 模型
    response_text = await call_ai_model(prompt)

    # 解析响应
    result = parse_response(response_text, request.type)

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

@router.post("/sentiment")
async def analyze_sentiment(symbols: List[str], data: Optional[Dict[str, Any]] = None):
    """市场情绪分析"""
    # 构建情绪分析提示词
    prompt = f"""分析以下标的的市场情绪：{', '.join(symbols)}

请提供：
1. 整体市场情绪判断（看涨/看跌/中性）
2. 情绪驱动因素
3. 资金流向分析
4. 市场预期
"""

    response = await call_ai_model(prompt)

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
    """信号解释"""
    prompt = f"""解释以下交易信号：

{json.dumps(signal_data, indent=2, ensure_ascii=False)}

请提供：
1. 信号含义解释
2. 触发原因分析
3. 历史胜率（如有）
4. 建议的操作策略
5. 止损止盈建议
"""

    response = await call_ai_model(prompt)

    return {
        "signalId": signal_data.get("id", ""),
        "signalType": signal_data.get("type", "unknown"),
        "explanation": response,
        "suggestedActions": extract_actions(response),
    }

@router.post("/strategy/optimize")
async def optimize_strategy(strategy_data: Dict[str, Any]):
    """策略优化建议"""
    prompt = f"""评估并优化以下交易策略：

{json.dumps(strategy_data, indent=2, ensure_ascii=False)}

请提供：
1. 策略优势分析
2. 策略劣势分析
3. 参数优化建议
4. 风险管理建议
5. 改进方向
"""

    response = await call_ai_model(prompt)

    return {
        "improvements": extract_improvements(response),
        "parameterSuggestions": {},
        "riskWarnings": extract_warnings(response),
        "analysis": response,
    }

@router.post("/risk/assess")
async def assess_risk(portfolio: Dict[str, Any]):
    """风险评估"""
    prompt = f"""评估以下投资组合的风险：

{json.dumps(portfolio, indent=2, ensure_ascii=False)}

请提供：
1. 主要风险因素
2. 风险敞口分析
3. 相关性风险
4. 极端情景压力测试
5. 风险对冲建议
"""

    response = await call_ai_model(prompt)

    return {
        "riskScore": calculate_risk_score(response),
        "riskFactors": extract_risk_factors(response),
        "hedgeSuggestions": extract_hedge_suggestions(response),
        "analysis": response,
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
    """调用 AI 模型"""
    from app.config import settings

    # 优先使用 OpenAI
    if settings.OPENAI_API_KEY:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.OPENAI_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                },
                timeout=60.0,
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]

    # 所有AI服务均不可用时返回错误
    raise HTTPException(status_code=503, detail="AI 分析服务暂不可用，请检查 API 密钥配置")

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
