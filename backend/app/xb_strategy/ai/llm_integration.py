"""西部量化可转债策略 V3.0 AI增强模块

功能:
- 大语言模型集成
- 智能投研报告生成
- 自然语言查询
- 智能问答
- 市场情绪分析
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import json
import time

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


# ============ 枚举类型 ============

class LLMProvider(str, Enum):
    """LLM提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    LOCAL = "local"


class ReportType(str, Enum):
    """报告类型"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SIGNAL = "signal"
    RISK = "risk"
    PORTFOLIO = "portfolio"


# ============ 配置类 ============

@dataclass
class LLMConfig:
    """LLM配置"""
    provider: LLMProvider = LLMProvider.OPENAI
    api_key: str = ""
    model: str = "gpt-4-turbo-preview"
    temperature: float = 0.7
    max_tokens: int = 4096
    base_url: str = None

    # 系统提示
    system_prompt: str = """你是一个专业的量化投资分析师，专注于中国可转债市场。
你的任务是帮助用户分析可转债投资机会，生成投研报告，并回答相关问题。
请基于数据和技术分析给出专业、客观的建议。"""


# ============ LLM客户端 ============

class LLMClient:
    """大语言模型客户端"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None
        self._init_client()

    def _init_client(self):
        """初始化客户端"""
        if self.config.provider == LLMProvider.OPENAI and OPENAI_AVAILABLE:
            self._client = openai.OpenAI(api_key=self.config.api_key)
        elif self.config.provider == LLMProvider.ANTHROPIC and ANTHROPIC_AVAILABLE:
            self._client = anthropic.Anthropic(api_key=self.config.api_key)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = None,
        max_tokens: int = None,
    ) -> str:
        """对话"""
        temperature = temperature if temperature is not None else self.config.temperature
        max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        if self.config.provider == LLMProvider.OPENAI:
            return self._chat_openai(messages, temperature, max_tokens)
        elif self.config.provider == LLMProvider.ANTHROPIC:
            return self._chat_anthropic(messages, temperature, max_tokens)
        else:
            return "LLM服务未配置"

    def _chat_openai(self, messages: List[Dict], temperature: float, max_tokens: int) -> str:
        """OpenAI对话"""
        if not self._client:
            return "OpenAI客户端未初始化"

        try:
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": self.config.system_prompt},
                    *messages,
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"[LLMClient] OpenAI调用失败: {e}")
            return f"调用失败: {str(e)}"

    def _chat_anthropic(self, messages: List[Dict], temperature: float, max_tokens: int) -> str:
        """Anthropic对话"""
        if not self._client:
            return "Anthropic客户端未初始化"

        try:
            # 转换消息格式
            user_messages = []
            system_prompt = self.config.system_prompt

            for msg in messages:
                if msg["role"] == "user":
                    user_messages.append({"role": "user", "content": msg["content"]})
                elif msg["role"] == "assistant":
                    user_messages.append({"role": "assistant", "content": msg["content"]})

            response = self._client.messages.create(
                model=self.config.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=user_messages,
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"[LLMClient] Anthropic调用失败: {e}")
            return f"调用失败: {str(e)}"


# ============ 智能投研报告生成器 ============

class ResearchReportGenerator:
    """投研报告生成器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate_daily_report(
        self,
        market_data: Dict,
        signals: List[Dict],
        positions: List[Dict],
        risk_metrics: Dict,
    ) -> str:
        """生成日报"""
        prompt = f"""请根据以下数据生成今日可转债市场日报：

## 市场概况
- 沪深300: {market_data.get('hs300_change', 0):.2f}%
- 中证转债指数: {market_data.get('cb_index_change', 0):.2f}%
- 成交额: {market_data.get('total_amount', 0):.2f}亿

## 今日信号
{json.dumps(signals[:5], ensure_ascii=False, indent=2)}

## 持仓情况
{json.dumps(positions[:5], ensure_ascii=False, indent=2)}

## 风险指标
- VaR(95%): {risk_metrics.get('var_95', 0):.2f}%
- 最大回撤: {risk_metrics.get('max_drawdown', 0):.2f}%

请生成一份专业的日报，包括：
1. 市场回顾与分析
2. 重点信号解读
3. 持仓建议
4. 风险提示
5. 明日展望

报告要求：
- 语言专业、简洁
- 重点突出、逻辑清晰
- 给出明确投资建议
"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def generate_signal_report(self, signal: Dict, cb_data: Dict, stock_data: Dict) -> str:
        """生成信号报告"""
        prompt = f"""请分析以下交易信号：

## 信号详情
- 标的: {signal.get('code')} {signal.get('name')}
- 动作: {signal.get('action')}
- 建议数量: {signal.get('quantity')}
- 置信度: {signal.get('confidence', 0):.2%}
- 原因: {signal.get('reason')}

## 转债数据
{json.dumps(cb_data, ensure_ascii=False, indent=2)}

## 正股数据
{json.dumps(stock_data, ensure_ascii=False, indent=2)}

请生成详细的信号分析报告，包括：
1. 信号触发原因分析
2. 转债与正股基本面评估
3. 风险收益比分析
4. 建议执行价格区间
5. 止损止盈建议
"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def generate_risk_report(self, risk_metrics: Dict, stress_test: Dict, violations: List[Dict]) -> str:
        """生成风险报告"""
        prompt = f"""请生成风险分析报告：

## 风险指标
{json.dumps(risk_metrics, ensure_ascii=False, indent=2)}

## 压力测试结果
{json.dumps(stress_test, ensure_ascii=False, indent=2)}

## 风险违规
{json.dumps(violations, ensure_ascii=False, indent=2)}

请生成专业的风险报告，包括：
1. 当前风险敞口分析
2. 极端情景影响评估
3. 风险预警和建议
4. 对冲策略建议
"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def generate_portfolio_report(self, portfolio: Dict, performance: Dict, benchmarks: Dict) -> str:
        """生成组合报告"""
        prompt = f"""请生成投资组合分析报告：

## 组合概况
{json.dumps(portfolio, ensure_ascii=False, indent=2)}

## 业绩表现
{json.dumps(performance, ensure_ascii=False, indent=2)}

## 基准对比
{json.dumps(benchmarks, ensure_ascii=False, indent=2)}

请生成详细的组合报告，包括：
1. 组合结构分析
2. 业绩归因分析
3. 行业配置建议
4. 优化建议
"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def generate_weekly_summary(
        self,
        daily_reports: List[str],
        weekly_pnl: float,
        weekly_trades: int,
        key_events: List[str],
    ) -> str:
        """生成周报"""
        reports_summary = "\n".join(daily_reports[-5:])  # 最近5天

        prompt = f"""请根据本周数据生成周报：

## 本周概况
- 周收益率: {weekly_pnl:.2f}%
- 交易次数: {weekly_trades}

## 本周重要事件
{chr(10).join(f'- {e}' for e in key_events)}

## 本周日报摘要
{reports_summary}

请生成周报，包括：
1. 本周市场回顾
2. 操作总结与收益分析
3. 成功与失败案例复盘
4. 下周策略展望
"""

        return self.llm.chat([{"role": "user", "content": prompt}])


# ============ 自然语言查询 ============

class NaturalLanguageQuery:
    """自然语言查询处理器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def parse_query(self, query: str) -> Dict[str, Any]:
        """解析查询意图"""
        prompt = f"""请解析以下自然语言查询，提取关键信息：

查询: "{query}"

请返回JSON格式的解析结果，包括：
- intent: 查询意图 (score/signal/position/risk/backtest/market)
- entities: 实体列表 (转债代码、股票代码等)
- filters: 筛选条件
- time_range: 时间范围
- metrics: 需要查询的指标

示例输出:
{{"intent": "score", "entities": ["128001"], "filters": {{"min_score": 70}}, "time_range": null, "metrics": ["total_score", "rank"]}}
"""

        response = self.llm.chat([{"role": "user", "content": prompt}])

        try:
            # 提取JSON
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.warning("[LLM] JSON parse failed: %s", e)

        return {"intent": "unknown", "raw_query": query}

    def execute_query(self, query: str, data_context: Dict) -> str:
        """执行查询"""
        parsed = self.parse_query(query)
        intent = parsed.get("intent", "unknown")

        if intent == "score":
            return self._query_score(parsed, data_context)
        elif intent == "signal":
            return self._query_signal(parsed, data_context)
        elif intent == "position":
            return self._query_position(parsed, data_context)
        elif intent == "risk":
            return self._query_risk(parsed, data_context)
        elif intent == "market":
            return self._query_market(parsed, data_context)
        else:
            return self._general_query(query, data_context)

    def _query_score(self, parsed: Dict, context: Dict) -> str:
        """查询打分"""
        entities = parsed.get("entities", [])
        scores = context.get("scores", {})

        if entities:
            result = {code: scores.get(code) for code in entities if code in scores}
        else:
            min_score = parsed.get("filters", {}).get("min_score", 0)
            result = {k: v for k, v in scores.items() if v and v.get("total_score", 0) >= min_score}

        prompt = f"""请用自然语言回答以下打分查询：

查询参数: {json.dumps(parsed, ensure_ascii=False)}
查询结果: {json.dumps(result, ensure_ascii=False, indent=2)}

请给出清晰、专业的回答。"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def _query_signal(self, parsed: Dict, context: Dict) -> str:
        """查询信号"""
        signals = context.get("signals", [])[:10]

        prompt = f"""请用自然语言回答以下信号查询：

查询参数: {json.dumps(parsed, ensure_ascii=False)}
信号列表: {json.dumps(signals, ensure_ascii=False, indent=2)}

请总结当前信号情况，并给出投资建议。"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def _query_position(self, parsed: Dict, context: Dict) -> str:
        """查询持仓"""
        positions = context.get("positions", [])

        prompt = f"""请用自然语言回答以下持仓查询：

查询参数: {json.dumps(parsed, ensure_ascii=False)}
持仓情况: {json.dumps(positions, ensure_ascii=False, indent=2)}

请分析当前持仓结构和风险。"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def _query_risk(self, parsed: Dict, context: Dict) -> str:
        """查询风险"""
        risk_metrics = context.get("risk_metrics", {})

        prompt = f"""请用自然语言回答以下风险查询：

查询参数: {json.dumps(parsed, ensure_ascii=False)}
风险指标: {json.dumps(risk_metrics, ensure_ascii=False, indent=2)}

请给出风险分析和建议。"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def _query_market(self, parsed: Dict, context: Dict) -> str:
        """查询市场"""
        market_data = context.get("market", {})

        prompt = f"""请用自然语言回答以下市场查询：

查询参数: {json.dumps(parsed, ensure_ascii=False)}
市场数据: {json.dumps(market_data, ensure_ascii=False, indent=2)}

请给出市场分析和展望。"""

        return self.llm.chat([{"role": "user", "content": prompt}])

    def _general_query(self, query: str, context: Dict) -> str:
        """通用查询"""
        prompt = f"""请回答以下问题：

问题: {query}

上下文数据:
{json.dumps(context, ensure_ascii=False, indent=2)}

请给出专业、准确的回答。"""

        return self.llm.chat([{"role": "user", "content": prompt}])


# ============ 市场情绪分析 ============

class SentimentAnalyzer:
    """市场情绪分析器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def analyze_news_sentiment(self, news_list: List[Dict]) -> Dict[str, Any]:
        """分析新闻情绪"""
        news_text = "\n".join([
            f"- {n.get('title', '')}: {n.get('summary', '')[:200]}"
            for n in news_list[:20]
        ])

        prompt = f"""请分析以下市场新闻的情绪：

新闻列表:
{news_text}

请返回JSON格式的分析结果：
- overall_sentiment: 整体情绪 (positive/negative/neutral)
- sentiment_score: 情绪分数 (-1到1)
- key_topics: 关键主题列表
- risk_factors: 风险因素
- opportunities: 投资机会

{{"overall_sentiment": "...", "sentiment_score": 0.0, "key_topics": [], "risk_factors": [], "opportunities": []}}
"""

        response = self.llm.chat([{"role": "user", "content": prompt}])

        try:
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.warning("[LLM] JSON parse failed (sentiment): %s", e)

        return {"overall_sentiment": "neutral", "sentiment_score": 0}

    def analyze_market_sentiment(self, market_data: Dict, technical_indicators: Dict) -> Dict[str, Any]:
        """分析市场情绪"""
        prompt = f"""请综合分析市场情绪：

市场数据:
{json.dumps(market_data, ensure_ascii=False, indent=2)}

技术指标:
{json.dumps(technical_indicators, ensure_ascii=False, indent=2)}

请给出市场情绪分析报告，包括：
1. 市场情绪判断
2. 技术面解读
3. 风险偏好评估
4. 投资建议
"""

        return self.llm.chat([{"role": "user", "content": prompt}])


# ============ 智能问答系统 ============

class IntelligentQA:
    """智能问答系统"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self._conversation_history: List[Dict] = []

    def ask(self, question: str, context: Dict = None) -> str:
        """提问"""
        # 构建消息
        messages = []

        # 添加历史
        for msg in self._conversation_history[-10:]:  # 保留最近10轮
            messages.append(msg)

        # 构建当前问题
        if context:
            question_with_context = f"""上下文信息:
{json.dumps(context, ensure_ascii=False, indent=2)}

问题: {question}"""
        else:
            question_with_context = question

        messages.append({"role": "user", "content": question_with_context})

        # 获取回答
        response = self.llm.chat(messages)

        # 保存历史
        self._conversation_history.append({"role": "user", "content": question_with_context})
        self._conversation_history.append({"role": "assistant", "content": response})

        return response

    def clear_history(self):
        """清空历史"""
        self._conversation_history = []


# ============ AI助手统一接口 ============

class AIAssistant:
    """AI助手"""

    def __init__(self, config: LLMConfig = None):
        self.config = config or LLMConfig()
        self.llm = LLMClient(self.config)
        self.report_generator = ResearchReportGenerator(self.llm)
        self.query_processor = NaturalLanguageQuery(self.llm)
        self.sentiment_analyzer = SentimentAnalyzer(self.llm)
        self.qa = IntelligentQA(self.llm)

    def ask(self, question: str, context: Dict = None) -> str:
        """提问"""
        return self.qa.ask(question, context)

    def generate_report(
        self,
        report_type: ReportType,
        data: Dict,
    ) -> str:
        """生成报告"""
        if report_type == ReportType.DAILY:
            return self.report_generator.generate_daily_report(**data)
        elif report_type == ReportType.SIGNAL:
            return self.report_generator.generate_signal_report(**data)
        elif report_type == ReportType.RISK:
            return self.report_generator.generate_risk_report(**data)
        elif report_type == ReportType.PORTFOLIO:
            return self.report_generator.generate_portfolio_report(**data)
        elif report_type == ReportType.WEEKLY:
            return self.report_generator.generate_weekly_summary(**data)
        else:
            return "未知报告类型"

    def analyze_sentiment(self, news: List[Dict] = None, market: Dict = None) -> Dict:
        """分析情绪"""
        if news:
            return self.sentiment_analyzer.analyze_news_sentiment(news)
        elif market:
            return self.sentiment_analyzer.analyze_market_sentiment(market, {})
        return {}

    def natural_query(self, query: str, context: Dict) -> str:
        """自然语言查询"""
        return self.query_processor.execute_query(query, context)


# ============ 便捷函数 ============

def create_ai_assistant(api_key: str = None, provider: LLMProvider = LLMProvider.OPENAI) -> AIAssistant:
    """创建AI助手"""
    config = LLMConfig(
        provider=provider,
        api_key=api_key or "",
    )
    return AIAssistant(config)


def generate_research_report(
    report_type: str,
    data: Dict,
    api_key: str = None,
) -> str:
    """生成投研报告"""
    assistant = create_ai_assistant(api_key)
    return assistant.generate_report(ReportType(report_type), data)
