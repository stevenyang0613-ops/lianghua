"""NLP研报分析模块"""
import re
import jieba
import jieba.analyse
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import Counter
import json

try:
    from transformers import pipeline, AutoModel, AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


@dataclass
class AnalysisResult:
    """分析结果"""
    report_id: str
    title: str
    summary: str
    sentiment_score: float  # -1 到 1
    sentiment_label: str
    key_points: List[str]
    entities: Dict[str, List[str]]
    topics: List[Tuple[str, float]]
    risk_factors: List[str]
    recommendations: List[str]
    confidence: float
    analyzed_at: datetime = field(default_factory=datetime.now)


@dataclass
class SentimentResult:
    """情感分析结果"""
    text: str
    score: float
    label: str
    confidence: float
    aspects: Dict[str, float] = field(default_factory=dict)


class ReportAnalyzer:
    """研报分析器"""
    
    def __init__(self, model_path: str = None):
        self.model_path = model_path
        
        # 初始化情感分析模型
        self.sentiment_pipeline = None
        if TRANSFORMERS_AVAILABLE:
            try:
                self.sentiment_pipeline = pipeline(
                    "sentiment-analysis",
                    model="uer/roberta-base-finetuned-chinanews-chinese",
                    device=-1
                )
            except Exception:
                pass
        
        # 自定义词典
        self._init_custom_dict()
        
        # 行业关键词
        self.industry_keywords = {
            '银行': ['净息差', '不良率', '资本充足率', '拨备覆盖率'],
            '地产': ['销售面积', '土地储备', '去化率', '杠杆率'],
            '新能源': ['装机容量', '利用小时', '度电成本', '储能'],
            '医药': ['研发投入', '临床试验', '药品批文', '医保目录'],
            '科技': ['研发费用率', '专利数量', '市占率', 'DAU'],
        }
    
    def _init_custom_dict(self):
        """初始化自定义词典"""
        # 添加转债相关词汇
        custom_words = [
            ('转股价', 10, 'n'),
            ('转股价值', 10, 'n'),
            ('溢价率', 10, 'n'),
            ('双低', 10, 'n'),
            ('强赎', 10, 'v'),
            ('回售', 10, 'v'),
            ('下修', 10, 'v'),
            ('转债', 10, 'n'),
        ]
        
        for word, freq, tag in custom_words:
            jieba.add_word(word, freq, tag)
    
    def analyze(self, report_text: str, report_id: str = None, title: str = None) -> AnalysisResult:
        """分析研报"""
        report_id = report_id or self._generate_id()
        
        # 文本预处理
        clean_text = self._preprocess(report_text)
        
        # 生成摘要
        summary = self._generate_summary(clean_text)
        
        # 情感分析
        sentiment = self._analyze_sentiment(clean_text)
        
        # 提取关键点
        key_points = self._extract_key_points(clean_text)
        
        # 实体识别
        entities = self._extract_entities(clean_text)
        
        # 主题提取
        topics = self._extract_topics(clean_text)
        
        # 风险因素
        risk_factors = self._extract_risk_factors(clean_text)
        
        # 推荐意见
        recommendations = self._extract_recommendations(clean_text)
        
        return AnalysisResult(
            report_id=report_id,
            title=title or "",
            summary=summary,
            sentiment_score=sentiment.score,
            sentiment_label=sentiment.label,
            key_points=key_points,
            entities=entities,
            topics=topics,
            risk_factors=risk_factors,
            recommendations=recommendations,
            confidence=sentiment.confidence
        )
    
    def _preprocess(self, text: str) -> str:
        """文本预处理"""
        # 移除特殊字符
        text = re.sub(r'[^一-龥a-zA-Z0-9\s，。！？、；：""''（）【】]', '', text)
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _generate_summary(self, text: str, max_sentences: int = 3) -> str:
        """生成摘要"""
        # 按句子分割
        sentences = re.split(r'[。！？]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) <= max_sentences:
            return text[:500]
        
        # 使用TextRank思想选择重要句子
        sentence_scores = []
        keywords = jieba.analyse.extract_tags(text, topK=20)
        
        for sentence in sentences:
            score = sum(1 for kw in keywords if kw in sentence)
            sentence_scores.append((sentence, score))
        
        # 选择得分最高的句子
        top_sentences = sorted(sentence_scores, key=lambda x: x[1], reverse=True)[:max_sentences]
        
        # 按原文顺序排列
        selected = [s[0] for s in sorted(top_sentences, key=lambda x: sentences.index(x[0]))]
        
        return '。'.join(selected) + '。'
    
    def _analyze_sentiment(self, text: str) -> SentimentResult:
        """情感分析"""
        if self.sentiment_pipeline:
            try:
                # 截取前512个字符
                truncated = text[:512]
                result = self.sentiment_pipeline(truncated)[0]
                
                label = result['label']
                score = result['score']
                
                if label == 'positive':
                    sentiment_score = score
                elif label == 'negative':
                    sentiment_score = -score
                else:
                    sentiment_score = 0
                
                return SentimentResult(
                    text=truncated,
                    score=sentiment_score,
                    label='正面' if sentiment_score > 0.3 else ('负面' if sentiment_score < -0.3 else '中性'),
                    confidence=score
                )
            except Exception:
                pass
        
        # 基于词典的情感分析
        return self._dict_sentiment(text)
    
    def _dict_sentiment(self, text: str) -> SentimentResult:
        """基于词典的情感分析"""
        positive_words = ['看好', '推荐', '买入', '增持', '优秀', '领先', '增长', '突破', '机遇']
        negative_words = ['风险', '下降', '亏损', '压力', '挑战', '不确定', '下跌', '减仓', '谨慎']
        
        words = jieba.lcut(text)
        
        pos_count = sum(1 for w in words if w in positive_words)
        neg_count = sum(1 for w in words if w in negative_words)
        
        total = pos_count + neg_count
        if total == 0:
            score = 0
        else:
            score = (pos_count - neg_count) / total
        
        if score > 0.3:
            label = '正面'
        elif score < -0.3:
            label = '负面'
        else:
            label = '中性'
        
        return SentimentResult(
            text=text[:100],
            score=score,
            label=label,
            confidence=min(abs(score) + 0.5, 1.0)
        )
    
    def _extract_key_points(self, text: str, top_n: int = 5) -> List[str]:
        """提取关键点"""
        # 使用TextRank提取关键词
        keywords = jieba.analyse.textrank(text, topK=top_n * 2, withWeight=True)
        
        # 提取包含关键词的句子
        sentences = re.split(r'[。！？]', text)
        key_points = []
        
        for keyword, weight in keywords:
            for sentence in sentences:
                if keyword in sentence and sentence.strip() not in key_points:
                    key_points.append(sentence.strip())
                    break
        
        return key_points[:top_n]
    
    def _extract_entities(self, text: str) -> Dict[str, List[str]]:
        """提取实体"""
        entities = {
            'companies': [],
            'bonds': [],
            'indicators': [],
            'dates': []
        }
        
        # 公司名称模式
        company_pattern = r'[一-龥]{2,10}(股份|集团|公司|科技|银行|证券)'
        companies = re.findall(company_pattern, text)
        entities['companies'] = list(set(companies))[:10]
        
        # 转债代码模式
        bond_pattern = r'\d{6}[SZSH]?'
        bonds = re.findall(bond_pattern, text)
        entities['bonds'] = list(set(bonds))[:10]
        
        # 财务指标
        indicator_pattern = r'(毛利率|净利率|ROE|ROA|PE|PB|PS|EV/EBITDA)[：:]\s*([\d.]+%?)'
        indicators = re.findall(indicator_pattern, text)
        entities['indicators'] = [f"{i[0]}: {i[1]}" for i in indicators]
        
        # 日期
        date_pattern = r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?'
        dates = re.findall(date_pattern, text)
        entities['dates'] = list(set(dates))[:5]
        
        return entities
    
    def _extract_topics(self, text: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """提取主题"""
        return jieba.analyse.extract_tags(text, topK=top_n, withWeight=True)
    
    def _extract_risk_factors(self, text: str) -> List[str]:
        """提取风险因素"""
        risk_keywords = ['风险', '不确定性', '压力', '挑战', '下滑', '亏损', '政策', '监管']
        
        sentences = re.split(r'[。！？]', text)
        risk_sentences = []
        
        for sentence in sentences:
            if any(kw in sentence for kw in risk_keywords):
                risk_sentences.append(sentence.strip())
        
        return risk_sentences[:5]
    
    def _extract_recommendations(self, text: str) -> List[str]:
        """提取推荐意见"""
        recommend_patterns = [
            r'(建议|推荐|给予)[买入卖出增持减持持有]+',
            r'(目标价|合理估值)[：:]\s*[\d.]+',
            r'(看好|关注|重点推荐).+'
        ]
        
        recommendations = []
        for pattern in recommend_patterns:
            matches = re.findall(pattern, text)
            recommendations.extend(matches)
        
        return recommendations[:5]
    
    def _generate_id(self) -> str:
        """生成报告ID"""
        return f"report_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    def batch_analyze(self, reports: List[Dict]) -> List[AnalysisResult]:
        """批量分析"""
        return [
            self.analyze(
                report.get('content', ''),
                report.get('id'),
                report.get('title')
            )
            for report in reports
        ]


class SentimentAnalyzer:
    """情感分析器"""
    
    def __init__(self):
        self.positive_words = self._load_sentiment_words('positive')
        self.negative_words = self._load_sentiment_words('negative')
        self.negators = ['不', '没', '无', '非', '未', '别']
    
    def _load_sentiment_words(self, sentiment_type: str) -> set:
        """加载情感词典"""
        positive = [
            '好', '优', '强', '涨', '增', '利', '盈', '赢', '胜', '佳',
            '看好', '推荐', '买入', '增持', '优秀', '领先', '突破', '机遇',
            '增长', '上升', '改善', '乐观', '积极', '稳健'
        ]
        negative = [
            '差', '弱', '跌', '减', '亏', '损', '败', '劣', '坏', '差',
            '风险', '下降', '亏损', '压力', '挑战', '不确定', '下跌', '减仓',
            '谨慎', '悲观', '恶化', '下滑', '负面'
        ]
        
        return set(positive) if sentiment_type == 'positive' else set(negative)
    
    def analyze(self, text: str) -> SentimentResult:
        """分析情感"""
        words = list(jieba.cut(text))
        
        pos_count = 0
        neg_count = 0
        
        for i, word in enumerate(words):
            if word in self.positive_words:
                # 检查否定词
                if i > 0 and words[i-1] in self.negators:
                    neg_count += 1
                else:
                    pos_count += 1
            elif word in self.negative_words:
                if i > 0 and words[i-1] in self.negators:
                    pos_count += 1
                else:
                    neg_count += 1
        
        total = pos_count + neg_count
        if total == 0:
            score = 0
        else:
            score = (pos_count - neg_count) / total
        
        if score > 0.3:
            label = '正面'
        elif score < -0.3:
            label = '负面'
        else:
            label = '中性'
        
        return SentimentResult(
            text=text[:100],
            score=score,
            label=label,
            confidence=min(0.5 + abs(score) * 0.5, 1.0)
        )
    
    def analyze_aspect(self, text: str, aspects: List[str]) -> Dict[str, float]:
        """方面级情感分析"""
        results = {}
        
        sentences = re.split(r'[。！？，]', text)
        
        for aspect in aspects:
            aspect_sentences = [s for s in sentences if aspect in s]
            
            if aspect_sentences:
                aspect_text = ' '.join(aspect_sentences)
                sentiment = self.analyze(aspect_text)
                results[aspect] = sentiment.score
            else:
                results[aspect] = 0.0
        
        return results
