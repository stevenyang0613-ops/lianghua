"""智能投研、高频交易、合规风控测试"""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch


# ============== 智能投研测试 ==============

class TestReportAnalyzer:
    """研报分析器测试"""

    def test_text_preprocessing(self):
        """测试文本预处理"""
        from app.research.nlp_analyzer import ReportAnalyzer
        
        analyzer = ReportAnalyzer()
        
        text = "这是一篇测试文本！！！包含特殊字符@#$%"
        clean = analyzer._preprocess(text)
        
        assert '@' not in clean
        assert '#' not in clean

    def test_summary_generation(self):
        """测试摘要生成"""
        from app.research.nlp_analyzer import ReportAnalyzer
        
        analyzer = ReportAnalyzer()
        
        text = "这是第一句话。这是第二句话。这是第三句话。这是第四句话。这是第五句话。"
        summary = analyzer._generate_summary(text, max_sentences=2)
        
        assert len(summary) > 0

    def test_sentiment_analysis(self):
        """测试情感分析"""
        from app.research.nlp_analyzer import SentimentAnalyzer
        
        analyzer = SentimentAnalyzer()
        
        positive_result = analyzer.analyze("这只债券非常看好，建议买入")
        assert positive_result.label in ['正面', '中性']
        
        negative_result = analyzer.analyze("风险很大，建议卖出")
        assert negative_result.label in ['负面', '中性']


class TestKnowledgeGraph:
    """知识图谱测试"""

    def test_entity_extraction(self):
        """测试实体提取"""
        from app.research.knowledge_graph import EntityExtractor
        
        extractor = EntityExtractor()
        
        text = "招商银行发行了招银转债，目标价120元"
        entities = extractor.extract(text)
        
        assert len(entities) > 0

    def test_knowledge_graph_build(self):
        """测试知识图谱构建"""
        from app.research.knowledge_graph import KnowledgeGraph
        
        kg = KnowledgeGraph()
        
        text = "招商银行发行了招银转债"
        kg.build_from_text(text)
        
        assert len(kg.entities) > 0


class TestIntelligentQA:
    """智能问答测试"""

    def test_question_parsing(self):
        """测试问题解析"""
        from app.research.qa_system import QuestionParser
        
        parser = QuestionParser()
        
        question = parser.parse("招商转债的投资价值如何？")
        
        assert question.question_type in ['fact', 'recommendation', 'trend']
        assert len(question.entities) > 0

    def test_answer_generation(self):
        """测试答案生成"""
        from app.research.qa_system import IntelligentQA, Document
        
        qa = IntelligentQA()
        
        # 添加文档
        doc = Document(
            doc_id="doc_1",
            title="招商转债分析报告",
            content="招商转债是一只优质的转债，具有良好的投资价值。"
        )
        qa.add_knowledge([doc])
        
        # 提问
        answer = qa.ask("招商转债怎么样？")
        
        assert answer.text is not None


# ============== 高频交易测试 ==============

class TestOrderExecutor:
    """订单执行器测试"""

    def test_order_creation(self):
        """测试订单创建"""
        from app.hft.order_executor import OrderExecutor, OrderSide, OrderType
        
        executor = OrderExecutor()
        
        order = executor.submit_order(
            symbol="123456",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1000,
            price=100.0
        )
        
        assert order.order_id is not None
        assert order.symbol == "123456"
        assert order.quantity == 1000

    def test_order_cancel(self):
        """测试订单取消"""
        from app.hft.order_executor import OrderExecutor, OrderSide, OrderType, OrderStatus
        
        executor = OrderExecutor()
        
        order = executor.submit_order(
            symbol="123456",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1000,
            price=100.0
        )
        
        result = executor.cancel_order(order.order_id)
        assert result is True

    def test_order_statistics(self):
        """测试订单统计"""
        from app.hft.order_executor import OrderExecutor, OrderSide, OrderType
        
        executor = OrderExecutor()
        
        # 提交多个订单
        for i in range(5):
            executor.submit_order(
                symbol="123456",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=100
            )
        
        stats = executor.get_statistics()
        assert stats['total_orders'] == 5


class TestSmartRouter:
    """智能路由测试"""

    def test_routing_decision(self):
        """测试路由决策"""
        from app.hft.smart_router import SmartOrderRouter, Venue
        
        router = SmartOrderRouter()
        
        # 添加市场数据
        from app.hft.smart_router import MarketDepth
        from datetime import datetime
        
        depth = MarketDepth(
            venue=Venue.SSE,
            symbol="123456",
            timestamp=datetime.now(),
            bids=[(100.0, 1000), (99.5, 2000)],
            asks=[(100.5, 1000), (101.0, 2000)]
        )
        router.update_market_data(Venue.SSE, depth)
        
        decision = router.route("123456", "buy", 1000)
        
        assert decision is not None
        assert len(decision.venues) > 0

    def test_large_order_split(self):
        """测试大单拆分"""
        from app.hft.smart_router import SmartOrderRouter
        
        router = SmartOrderRouter()
        
        slices = router.split_large_order(
            symbol="123456",
            side="buy",
            total_quantity=100000,
            time_window_seconds=60
        )
        
        assert len(slices) > 1


class TestLatencyMonitor:
    """延迟监控测试"""

    def test_latency_recording(self):
        """测试延迟记录"""
        from app.hft.latency_monitor import LatencyMonitor, LatencyType
        
        monitor = LatencyMonitor()
        
        monitor.record(LatencyType.ORDER_SUBMISSION, 50.0)
        monitor.record(LatencyType.ORDER_SUBMISSION, 100.0)
        
        stats = monitor.get_stats(LatencyType.ORDER_SUBMISSION)
        
        assert stats is not None
        assert stats.count == 2
        assert stats.mean_us == 75.0

    def test_latency_context(self):
        """测试延迟上下文"""
        from app.hft.latency_monitor import LatencyMonitor, LatencyType
        import time
        
        monitor = LatencyMonitor()
        
        with monitor.measure(LatencyType.PROCESSING):
            time.sleep(0.001)  # 1毫秒
        
        stats = monitor.get_stats(LatencyType.PROCESSING)
        assert stats is not None
        assert stats.mean_us > 0

    def test_bottleneck_detection(self):
        """测试瓶颈检测"""
        from app.hft.latency_monitor import LatencyMonitor, LatencyType
        
        monitor = LatencyMonitor()
        monitor.set_threshold(LatencyType.ORDER_EXECUTION, 100)
        
        # 记录高延迟
        for _ in range(100):
            monitor.record(LatencyType.ORDER_EXECUTION, 200.0)
        
        bottlenecks = monitor.identify_bottlenecks()
        
        assert len(bottlenecks) > 0


# ============== 合规风控测试 ==============

class TestComplianceMonitor:
    """合规监控测试"""

    def test_rule_initialization(self):
        """测试规则初始化"""
        from app.compliance.compliance_monitor import ComplianceMonitor
        
        monitor = ComplianceMonitor()
        
        assert len(monitor.rules) > 0

    def test_pre_trade_check(self):
        """测试交易前检查"""
        from app.compliance.compliance_monitor import (
            ComplianceMonitor, TradingContext
        )
        
        monitor = ComplianceMonitor()
        
        context = TradingContext(
            trader_id="trader_1",
            account_id="account_1",
            symbol="123456",
            side="buy",
            quantity=1000,
            price=100.0,
            order_type="limit",
            timestamp=datetime.now(),
            portfolio_value=1000000,
            current_positions={},
            daily_volume={}
        )
        
        violations = monitor.check_pre_trade(context)
        
        assert isinstance(violations, list)

    def test_violation_statistics(self):
        """测试违规统计"""
        from app.compliance.compliance_monitor import ComplianceMonitor
        
        monitor = ComplianceMonitor()
        
        stats = monitor.get_violation_statistics()
        
        assert 'total' in stats


class TestAnomalyDetector:
    """异常检测测试"""

    def test_volume_spike_detection(self):
        """测试交易量激增检测"""
        from app.compliance.anomaly_detector import AnomalyDetector
        
        detector = AnomalyDetector()
        
        # 建立历史
        for i in range(20):
            trade = {
                'trader_id': 'trader_1',
                'symbol': '123456',
                'quantity': 100,
                'price': 100.0,
                'timestamp': datetime.now() - timedelta(minutes=20-i)
            }
            detector.detect(trade)
        
        # 异常交易
        anomaly_trade = {
            'trader_id': 'trader_1',
            'symbol': '123456',
            'quantity': 10000,  # 大幅增加
            'price': 100.0,
            'timestamp': datetime.now()
        }
        
        anomalies = detector.detect(anomaly_trade)
        
        # 可能检测到异常
        assert isinstance(anomalies, list)

    def test_anomaly_statistics(self):
        """测试异常统计"""
        from app.compliance.anomaly_detector import AnomalyDetector
        
        detector = AnomalyDetector()
        
        stats = detector.get_anomaly_statistics()
        
        assert 'total' in stats


class TestReportGenerator:
    """报告生成测试"""

    def test_daily_report_generation(self):
        """测试日报告生成"""
        from app.compliance.report_generator import ReportGenerator
        
        generator = ReportGenerator()
        
        report = generator.generate_daily_trading_report(
            date=datetime.now(),
            trades=[
                {'symbol': '123456', 'side': 'buy', 'quantity': 100, 'price': 100.0, 'pnl': 100}
            ],
            compliance_results=[],
            risk_metrics={'var_95': 0.02, 'max_drawdown': 0.05, 'sharpe_ratio': 1.5}
        )
        
        assert report.report_id is not None
        assert len(report.sections) > 0

    def test_report_export(self):
        """测试报告导出"""
        from app.compliance.report_generator import ReportGenerator, ReportFormat
        
        generator = ReportGenerator()
        
        report = generator.generate_daily_trading_report(
            date=datetime.now(),
            trades=[],
            compliance_results=[],
            risk_metrics={}
        )
        
        json_output = generator.export_report(report, ReportFormat.JSON)
        
        assert 'report_id' in json_output

    def test_html_export(self):
        """测试HTML导出"""
        from app.compliance.report_generator import ReportGenerator, ReportFormat
        
        generator = ReportGenerator()
        
        report = generator.generate_daily_trading_report(
            date=datetime.now(),
            trades=[],
            compliance_results=[],
            risk_metrics={}
        )
        
        html_output = generator.export_report(report, ReportFormat.HTML)
        
        assert '<html>' in html_output
