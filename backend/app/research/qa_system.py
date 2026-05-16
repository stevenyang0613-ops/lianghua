"""智能问答系统"""
import re
import jieba
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
import math

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


@dataclass
class Question:
    """问题"""
    question_id: str
    text: str
    question_type: str  # 'fact', 'comparison', 'trend', 'reason', 'recommendation'
    entities: List[str]
    intent: str
    context: Dict = field(default_factory=dict)


@dataclass
class Answer:
    """答案"""
    question_id: str
    text: str
    confidence: float
    sources: List[str]
    related_entities: List[str]
    additional_info: Dict = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.now)


@dataclass
class Document:
    """文档"""
    doc_id: str
    title: str
    content: str
    metadata: Dict = field(default_factory=dict)
    embedding: List[float] = field(default_factory=list)


class QuestionParser:
    """问题解析器"""
    
    def __init__(self):
        # 问题类型模式
        self.question_patterns = {
            'fact': [
                r'(.+?)是(什么|谁|哪)',
                r'(.+?)的(价格|市值|收益率)',
                r'(如何|怎么)看待',
            ],
            'comparison': [
                r'(.+?)和(.+?)(比|比较|对比)',
                r'(.+?)与(.+?)的(区别|差异)',
                r'(.+?)哪个(好|优)',
            ],
            'trend': [
                r'(.+?)的(走势|趋势|前景)',
                r'(.+?)未来(会|将)',
                r'(预测|展望)(.+?)',
            ],
            'reason': [
                r'(为什么|为何|原因)(.+?)',
                r'(.+?)为什么',
                r'(.+?)的原因',
            ],
            'recommendation': [
                r'(.+?)(值得|可以)(投资|买|持有)',
                r'(推荐|建议)(.+?)',
                r'(.+?)怎么操作',
            ],
        }
        
        # 疑问词
        self.question_words = ['什么', '谁', '哪', '如何', '怎么', '为什么', '多少', '几', '是否']
    
    def parse(self, question_text: str) -> Question:
        """解析问题"""
        question_id = f"q_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        # 提取实体
        entities = self._extract_entities(question_text)
        
        # 判断问题类型
        question_type = self._classify(question_text)
        
        # 提取意图
        intent = self._extract_intent(question_text, question_type)
        
        return Question(
            question_id=question_id,
            text=question_text,
            question_type=question_type,
            entities=entities,
            intent=intent
        )
    
    def _extract_entities(self, text: str) -> List[str]:
        """提取实体"""
        # 简化实体提取
        words = list(jieba.cut(text))
        
        # 过滤掉疑问词和停用词
        stop_words = {'的', '是', '有', '在', '了', '和', '与', '吗', '呢', '什么', '怎么', '如何'}
        entities = [w for w in words if len(w) > 1 and w not in stop_words and w not in self.question_words]
        
        return entities
    
    def _classify(self, text: str) -> str:
        """分类问题类型"""
        for q_type, patterns in self.question_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return q_type
        
        return 'fact'
    
    def _extract_intent(self, text: str, question_type: str) -> str:
        """提取意图"""
        # 基于问题类型的意图映射
        intent_map = {
            'fact': 'query_information',
            'comparison': 'compare_entities',
            'trend': 'analyze_trend',
            'reason': 'explain_reason',
            'recommendation': 'get_advice',
        }
        
        return intent_map.get(question_type, 'query_information')


class DocumentRetriever:
    """文档检索器"""
    
    def __init__(self):
        self.documents: Dict[str, Document] = {}
        self.inverted_index: Dict[str, List[str]] = {}  # 词到文档ID的索引
        self.doc_embeddings: Dict[str, List[float]] = {}
    
    def add_document(self, document: Document):
        """添加文档"""
        self.documents[document.doc_id] = document
        
        # 构建倒排索引
        words = list(jieba.cut(document.content))
        for word in words:
            if word not in self.inverted_index:
                self.inverted_index[word] = []
            self.inverted_index[word].append(document.doc_id)
    
    def search(self, query: str, top_k: int = 5) -> List[Tuple[Document, float]]:
        """搜索文档"""
        # 分词
        query_words = list(jieba.cut(query))
        
        # 计算文档得分
        doc_scores: Dict[str, float] = {}
        
        for word in query_words:
            if word in self.inverted_index:
                for doc_id in self.inverted_index[word]:
                    if doc_id not in doc_scores:
                        doc_scores[doc_id] = 0
                    # TF-IDF简化得分
                    doc_scores[doc_id] += 1 / len(self.inverted_index[word])
        
        # 排序
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        
        results = []
        for doc_id, score in sorted_docs[:top_k]:
            if doc_id in self.documents:
                results.append((self.documents[doc_id], score))
        
        return results
    
    def search_by_embedding(
        self, 
        query_embedding: List[float],
        top_k: int = 5
    ) -> List[Tuple[Document, float]]:
        """基于向量搜索"""
        if not NUMPY_AVAILABLE:
            return []
        
        query_vec = np.array(query_embedding)
        
        results = []
        for doc_id, doc_emb in self.doc_embeddings.items():
            if doc_id in self.documents:
                doc_vec = np.array(doc_emb)
                # 余弦相似度
                similarity = np.dot(query_vec, doc_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-10
                )
                results.append((self.documents[doc_id], float(similarity)))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


class AnswerGenerator:
    """答案生成器"""
    
    def __init__(self, knowledge_graph=None):
        self.knowledge_graph = knowledge_graph
        
        # 答案模板
        self.answer_templates = {
            'fact': {
                'price': '{entity}当前价格为{price}元，较前一交易日{change}。',
                'rate': '{entity}的{indicator}为{value}。',
                'info': '{entity}是{description}。',
            },
            'comparison': {
                'better': '从{aspect}来看，{entity1}比{entity2}{comparison_result}。',
                'difference': '{entity1}和{entity2}在{aspect}方面存在{difference}差异。',
            },
            'trend': {
                'up': '{entity}近期呈现上涨趋势，主要原因是{reason}。',
                'down': '{entity}近期呈现下跌趋势，建议关注{risk}风险。',
                'stable': '{entity}近期走势相对平稳，{analysis}。',
            },
            'recommendation': {
                'buy': '综合考虑{factors}，{entity}具有投资价值，建议{action}。',
                'hold': '{entity}当前估值合理，建议持有观望。',
                'sell': '{entity}存在{risk}风险，建议谨慎操作。',
            },
        }
    
    def generate(self, question: Question, retrieved_docs: List[Tuple[Document, float]]) -> Answer:
        """生成答案"""
        if not retrieved_docs:
            return Answer(
                question_id=question.question_id,
                text="抱歉，我没有找到相关信息。",
                confidence=0.0,
                sources=[],
                related_entities=question.entities
            )
        
        # 根据问题类型生成答案
        if question.question_type == 'fact':
            answer_text = self._generate_fact_answer(question, retrieved_docs)
        elif question.question_type == 'comparison':
            answer_text = self._generate_comparison_answer(question, retrieved_docs)
        elif question.question_type == 'trend':
            answer_text = self._generate_trend_answer(question, retrieved_docs)
        elif question.question_type == 'recommendation':
            answer_text = self._generate_recommendation_answer(question, retrieved_docs)
        else:
            answer_text = self._generate_fact_answer(question, retrieved_docs)
        
        # 计算置信度
        confidence = retrieved_docs[0][1] if retrieved_docs else 0
        
        # 提取来源
        sources = [doc.title for doc, _ in retrieved_docs[:3]]
        
        return Answer(
            question_id=question.question_id,
            text=answer_text,
            confidence=confidence,
            sources=sources,
            related_entities=question.entities
        )
    
    def _generate_fact_answer(self, question: Question, docs: List[Tuple[Document, float]]) -> str:
        """生成事实类答案"""
        # 从检索文档中提取相关信息
        relevant_content = []
        
        for doc, score in docs:
            # 查找包含实体的句子
            sentences = re.split(r'[。！？]', doc.content)
            for sentence in sentences:
                if any(entity in sentence for entity in question.entities):
                    relevant_content.append(sentence.strip())
        
        if relevant_content:
            return relevant_content[0]
        
        # 如果没有找到直接相关的内容，返回摘要
        return docs[0][0].content[:200] if docs else "暂无相关信息。"
    
    def _generate_comparison_answer(self, question: Question, docs: List[Tuple[Document, float]]) -> str:
        """生成比较类答案"""
        entities = question.entities
        
        if len(entities) < 2:
            return "请明确需要比较的对象。"
        
        entity1, entity2 = entities[0], entities[1]
        
        # 从知识图谱获取比较信息
        if self.knowledge_graph:
            path = self.knowledge_graph.find_path(entity1, entity2)
            if path:
                return f"{entity1}和{entity2}存在关联关系，关联路径：{path[0]}"
        
        return f"{entity1}和{entity2}在多个方面存在差异，具体请参考相关研报。"
    
    def _generate_trend_answer(self, question: Question, docs: List[Tuple[Document, float]]) -> str:
        """生成趋势类答案"""
        # 查找趋势相关的内容
        trend_keywords = ['趋势', '走势', '未来', '预测', '展望', '预期']
        
        for doc, _ in docs:
            sentences = re.split(r'[。！？]', doc.content)
            for sentence in sentences:
                if any(kw in sentence for kw in trend_keywords):
                    if any(entity in sentence for entity in question.entities):
                        return sentence.strip()
        
        return "根据市场分析，相关走势需要综合考虑多方面因素。"
    
    def _generate_recommendation_answer(self, question: Question, docs: List[Tuple[Document, float]]) -> str:
        """生成推荐类答案"""
        # 查找推荐相关的内容
        recommend_keywords = ['建议', '推荐', '看好', '买入', '持有', '卖出']
        
        for doc, _ in docs:
            sentences = re.split(r'[。！？]', doc.content)
            for sentence in sentences:
                if any(kw in sentence for kw in recommend_keywords):
                    return sentence.strip()
        
        return "投资决策需要综合考虑个人风险偏好和市场情况。"


class IntelligentQA:
    """智能问答系统"""
    
    def __init__(self, knowledge_graph=None):
        self.question_parser = QuestionParser()
        self.document_retriever = DocumentRetriever()
        self.answer_generator = AnswerGenerator(knowledge_graph)
        
        self.knowledge_graph = knowledge_graph
        
        # 对话历史
        self.conversation_history: List[Dict] = []
    
    def add_knowledge(self, documents: List[Document]):
        """添加知识库"""
        for doc in documents:
            self.document_retriever.add_document(doc)
    
    def ask(self, question_text: str, context: Dict = None) -> Answer:
        """提问"""
        # 解析问题
        question = self.question_parser.parse(question_text)
        
        if context:
            question.context = context
        
        # 检索相关文档
        retrieved_docs = self.document_retriever.search(question_text)
        
        # 生成答案
        answer = self.answer_generator.generate(question, retrieved_docs)
        
        # 记录对话历史
        self.conversation_history.append({
            'question': question_text,
            'answer': answer.text,
            'timestamp': datetime.now().isoformat()
        })
        
        return answer
    
    def ask_with_context(self, question_text: str, context_docs: List[Document]) -> Answer:
        """带上下文的提问"""
        question = self.question_parser.parse(question_text)
        
        # 使用提供的上下文文档
        retrieved_docs = [(doc, 1.0) for doc in context_docs]
        
        return self.answer_generator.generate(question, retrieved_docs)
    
    def multi_turn_ask(self, question_text: str) -> Answer:
        """多轮对话"""
        # 结合历史上下文
        context = {}
        
        if self.conversation_history:
            # 提取最近的对话内容作为上下文
            recent_history = self.conversation_history[-3:]
            context['previous_qa'] = recent_history
        
        return self.ask(question_text, context)
    
    def get_suggestions(self, partial_query: str) -> List[str]:
        """获取问题建议"""
        # 基于部分输入提供问题建议
        suggestions = []
        
        # 从知识图谱获取相关实体
        if self.knowledge_graph:
            entities = list(self.knowledge_graph.entity_index.keys())
            for entity in entities:
                if partial_query in entity:
                    suggestions.append(f"{entity}的投资价值如何？")
                    suggestions.append(f"{entity}近期走势如何？")
        
        # 通用问题模板
        if '转债' in partial_query:
            suggestions.extend([
                "哪些转债值得投资？",
                "转债如何分析？",
                "双低转债策略是什么？"
            ])
        
        return suggestions[:5]
    
    def get_related_questions(self, question_text: str) -> List[str]:
        """获取相关问题"""
        question = self.question_parser.parse(question_text)
        
        related = []
        
        # 基于实体生成相关问题
        for entity in question.entities:
            related.extend([
                f"{entity}的基本面如何？",
                f"{entity}的风险有哪些？",
                f"{entity}的投资建议是什么？"
            ])
        
        # 基于问题类型生成相关问题
        if question.question_type == 'fact':
            related.append("相关的行业趋势如何？")
        elif question.question_type == 'recommendation':
            related.append("有什么替代投资选择？")
        
        return related[:5]
    
    def clear_history(self):
        """清空对话历史"""
        self.conversation_history.clear()
    
    def export_history(self) -> str:
        """导出对话历史"""
        return json.dumps(self.conversation_history, ensure_ascii=False, indent=2)
