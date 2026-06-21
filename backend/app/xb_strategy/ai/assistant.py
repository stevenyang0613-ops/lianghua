"""西部量化可转债策略 V3.0 AI助手模块

功能:
- LLM集成
- 自然语言查询
- 智能分析报告
- 策略问答
- 数据解释
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import json
import os

logger = logging.getLogger(__name__)

# 检查LLM库
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from langchain.llms import OpenAI, Anthropic
    from langchain.chains import LLMChain
    from langchain.prompts import PromptTemplate
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False


# ============ 枚举类型 ============

class LLMProvider(str, Enum):
    """LLM提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    LOCAL = "local"


class QueryType(str, Enum):
    """查询类型"""
    PORTFOLIO = "portfolio"
    POSITION = "position"
    SIGNAL = "signal"
    RISK = "risk"
    PERFORMANCE = "performance"
    MARKET = "market"
    STRATEGY = "strategy"
    GENERAL = "general"


# ============ 配置类 ============

@dataclass
class AIConfig:
    """AI配置"""
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = "gpt-4"
    api_key: str = ""
    api_base: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000

    # 提示词配置
    system_prompt: str = """你是西部量化可转债策略的AI助手。

你的职责是:
1. 回答关于投资组合、持仓、信号的问题
2. 解释策略逻辑和风险指标
3. 提供市场分析和投资建议
4. 生成分析报告

回答要求:
- 专业、准确、简洁
- 使用数据和事实支撑观点
- 对于不确定的问题，明确说明
- 避免过度自信的预测"""

    # 上下文配置
    max_context_length: int = 4000
    include_data_context: bool = True


# ============ AI助手类 ============

class AIAssistant:
    """AI助手"""

    _instance = None

    def __new__(cls, config: AIConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: AIConfig = None):
        if self._initialized:
            return

        self.config = config or AIConfig()
        self._llm = None
        self._conversation_history: List[Dict] = []

        self._init_llm()

        self._initialized = True

    def _init_llm(self):
        """初始化LLM"""
        if self.config.provider == LLMProvider.OPENAI and OPENAI_AVAILABLE:
            openai.api_key = self.config.api_key or os.getenv("OPENAI_API_KEY", "")
            if self.config.api_base:
                openai.api_base = self.config.api_base

        elif self.config.provider == LLMProvider.ANTHROPIC and ANTHROPIC_AVAILABLE:
            self._llm = anthropic.Anthropic(
                api_key=self.config.api_key or os.getenv("ANTHROPIC_API_KEY", ""),
            )

        logger.info(f"[AI] 初始化完成: {self.config.provider.value}")

    def chat(
        self,
        message: str,
        context: Dict[str, Any] = None,
        stream: bool = False,
    ) -> str:
        """对话"""
        # 构建上下文
        full_context = self._build_context(context)

        # 构建消息
        messages = [
            {"role": "system", "content": self.config.system_prompt},
        ]

        # 添加历史
        for msg in self._conversation_history[-10:]:
            messages.append(msg)

        # 添加当前消息
        user_message = message
        if full_context:
            user_message = f"{message}\n\n当前上下文:\n{full_context}"

        messages.append({"role": "user", "content": user_message})

        # 调用LLM
        if self.config.provider == LLMProvider.OPENAI and OPENAI_AVAILABLE:
            response = self._call_openai(messages, stream)
        elif self.config.provider == LLMProvider.ANTHROPIC and ANTHROPIC_AVAILABLE:
            response = self._call_anthropic(messages, stream)
        else:
            logger.warning("[AI] 没有可用的 LLM 提供者（需配置 OPENAI_API_KEY 或 ANTHROPIC_API_KEY）")
            response = "AI 助手暂不可用：未配置任何 LLM API 密钥。"

        # 记录历史
        self._conversation_history.append({"role": "user", "content": message})
        self._conversation_history.append({"role": "assistant", "content": response})

        return response

    def _build_context(self, context: Dict[str, Any]) -> str:
        """构建上下文"""
        if not context:
            return ""

        parts = []

        if "portfolio" in context:
            portfolio = context["portfolio"]
            parts.append(f"""
组合信息:
- 净值: {portfolio.get('nav', 'N/A')}
- 日收益: {portfolio.get('daily_return', 'N/A')}
- 持仓数: {portfolio.get('position_count', 'N/A')}
- 回撤: {portfolio.get('drawdown', 'N/A')}
""")

        if "positions" in context:
            positions = context["positions"]
            parts.append(f"""
持仓TOP5:
{self._format_positions(positions[:5])}
""")

        if "signals" in context:
            signals = context["signals"]
            parts.append(f"""
最近信号:
{self._format_signals(signals[:5])}
""")

        return "\n".join(parts)

    def _format_positions(self, positions: List[Dict]) -> str:
        """格式化持仓"""
        lines = []
        for p in positions:
            lines.append(f"- {p.get('code', '')} {p.get('name', '')}: "
                        f"数量{p.get('quantity', 0)}, 市值{p.get('market_value', 0):.0f}, "
                        f"收益{p.get('profit_pct', 0)*100:.2f}%")
        return "\n".join(lines)

    def _format_signals(self, signals: List[Dict]) -> str:
        """格式化信号"""
        lines = []
        for s in signals:
            lines.append(f"- {s.get('code', '')} {s.get('action', '')}: "
                        f"{s.get('quantity', 0)}张 @ {s.get('price', 0):.2f}")
        return "\n".join(lines)

    def _call_openai(self, messages: List[Dict], stream: bool) -> str:
        """调用OpenAI"""
        try:
            response = openai.ChatCompletion.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"[AI] OpenAI调用失败: {e}")
            return f"抱歉，AI服务暂时不可用: {e}"

    def _call_anthropic(self, messages: List[Dict], stream: bool) -> str:
        """调用Anthropic"""
        try:
            response = self._llm.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                messages=[
                    {"role": m["role"], "content": m["content"]}
                    for m in messages if m["role"] != "system"
                ],
                system=self.config.system_prompt,
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"[AI] Anthropic调用失败: {e}")
            return f"抱歉，AI服务暂时不可用: {e}"

    def analyze_portfolio(self, portfolio: Dict) -> str:
        """分析组合"""
        context = {"portfolio": portfolio}
        return self.chat("请分析当前投资组合的表现和风险状况", context)

    def explain_signal(self, signal: Dict) -> str:
        """解释信号"""
        context = {"signals": [signal]}
        return self.chat(
            f"请解释这个交易信号的原因和逻辑: {signal.get('code')} {signal.get('action')}",
            context,
        )

    def generate_report(
        self,
        report_type: str = "daily",
        data: Dict = None,
    ) -> str:
        """生成报告"""
        prompts = {
            "daily": "请根据以下数据生成今日投资报告，包括市场回顾、组合表现、风险分析和明日展望",
            "weekly": "请生成本周投资周报，包括周度收益、持仓变化、重要事件回顾和下周策略",
            "monthly": "请生成本月投资月报，详细分析月度表现、风险指标、策略调整建议",
        }

        return self.chat(prompts.get(report_type, prompts["daily"]), data)

    def answer_question(self, question: str, data: Dict = None) -> str:
        """回答问题"""
        return self.chat(question, data)

    def suggest_action(self, situation: str, data: Dict = None) -> str:
        """建议操作"""
        return self.chat(f"当前情况: {situation}\n\n请给出操作建议", data)

    def clear_history(self):
        """清空对话历史"""
        self._conversation_history.clear()


# ============ 查询处理器 ============

class QueryProcessor:
    """自然语言查询处理器"""

    def __init__(self, ai_assistant: AIAssistant = None):
        self.ai = ai_assistant or AIAssistant()

        # 关键词映射
        self._keyword_mappings = {
            "净值": QueryType.PORTFOLIO,
            "收益": QueryType.PERFORMANCE,
            "持仓": QueryType.POSITION,
            "信号": QueryType.SIGNAL,
            "风险": QueryType.RISK,
            "市场": QueryType.MARKET,
            "策略": QueryType.STRATEGY,
        }

    def process(self, query: str, context: Dict = None) -> Dict[str, Any]:
        """处理查询"""
        # 识别查询类型
        query_type = self._classify_query(query)

        # 获取相关数据
        data = self._get_relevant_data(query_type, context)

        # 构建回答
        response = self.ai.chat(query, data)

        return {
            "query": query,
            "query_type": query_type.value,
            "response": response,
            "timestamp": datetime.now().isoformat(),
        }

    def _classify_query(self, query: str) -> QueryType:
        """分类查询"""
        for keyword, query_type in self._keyword_mappings.items():
            if keyword in query:
                return query_type
        return QueryType.GENERAL

    def _get_relevant_data(self, query_type: QueryType, context: Dict) -> Dict:
        """获取相关数据"""
        if not context:
            return {}

        data = {}

        if query_type == QueryType.PORTFOLIO:
            data["portfolio"] = context.get("portfolio", {})

        elif query_type == QueryType.POSITION:
            data["positions"] = context.get("positions", [])

        elif query_type == QueryType.SIGNAL:
            data["signals"] = context.get("signals", [])

        elif query_type == QueryType.RISK:
            data["portfolio"] = context.get("portfolio", {})
            data["risk_metrics"] = context.get("risk_metrics", {})

        return data


# ============ 报告生成器 ============

class ReportGenerator:
    """报告生成器"""

    def __init__(self, ai_assistant: AIAssistant = None):
        self.ai = ai_assistant or AIAssistant()

    def generate_daily_report(
        self,
        portfolio: Dict,
        positions: List[Dict],
        signals: List[Dict],
        trades: List[Dict],
    ) -> Dict[str, Any]:
        """生成日报"""
        context = {
            "portfolio": portfolio,
            "positions": positions,
            "signals": signals,
            "trades": trades,
        }

        report_content = self.ai.generate_report("daily", context)

        return {
            "report_type": "daily",
            "date": date.today().isoformat(),
            "content": report_content,
            "summary": {
                "nav": portfolio.get("nav"),
                "daily_return": portfolio.get("daily_return"),
                "position_count": portfolio.get("position_count"),
                "signal_count": len(signals),
                "trade_count": len(trades),
            },
            "generated_at": datetime.now().isoformat(),
        }

    def generate_weekly_report(
        self,
        weekly_data: Dict,
    ) -> Dict[str, Any]:
        """生成周报"""
        report_content = self.ai.generate_report("weekly", weekly_data)

        return {
            "report_type": "weekly",
            "week_start": weekly_data.get("week_start"),
            "week_end": weekly_data.get("week_end"),
            "content": report_content,
            "generated_at": datetime.now().isoformat(),
        }

    def generate_monthly_report(
        self,
        monthly_data: Dict,
    ) -> Dict[str, Any]:
        """生成月报"""
        report_content = self.ai.generate_report("monthly", monthly_data)

        return {
            "report_type": "monthly",
            "month": monthly_data.get("month"),
            "content": report_content,
            "generated_at": datetime.now().isoformat(),
        }


# ============ 便捷函数 ============

def get_ai_assistant(config: AIConfig = None) -> AIAssistant:
    """获取AI助手"""
    return AIAssistant(config)


def get_query_processor() -> QueryProcessor:
    """获取查询处理器"""
    return QueryProcessor()


def get_report_generator() -> ReportGenerator:
    """获取报告生成器"""
    return ReportGenerator()


def init_ai(
    provider: LLMProvider = LLMProvider.OPENAI,
    model: str = "gpt-4",
    api_key: str = None,
) -> AIAssistant:
    """初始化AI助手"""
    config = AIConfig(
        provider=provider,
        model=model,
        api_key=api_key or "",
    )
    return AIAssistant(config)
