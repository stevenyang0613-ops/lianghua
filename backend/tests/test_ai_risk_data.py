"""AI模型、风控系统、数据平台测试"""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta


# ============== AI模型测试 ==============

class TestFeatureEngineer:
    """特征工程测试"""

    def test_extract_price_features(self):
        """测试价格特征提取"""
        from app.ml.feature_engineer import FeatureEngineer, FeatureConfig
        
        config = FeatureConfig()
        engineer = FeatureEngineer(config)
        
        # 创建测试数据
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        data = pd.DataFrame({
            'date': dates,
            'open': 100 + np.random.randn(100).cumsum(),
            'high': 101 + np.random.randn(100).cumsum(),
            'low': 99 + np.random.randn(100).cumsum(),
            'close': 100 + np.random.randn(100).cumsum(),
            'volume': np.random.randint(1000, 10000, 100)
        })
        data = data.set_index('date')
        
        # 提取特征
        result = engineer.extract_all_features(data)
        
        # 验证特征
        assert 'return_1d' in result.columns
        assert 'ma_5' in result.columns
        assert 'rsi' in result.columns
        assert 'macd' in result.columns

    def test_technical_indicators(self):
        """测试技术指标"""
        from app.ml.feature_engineer import FeatureEngineer
        
        engineer = FeatureEngineer()
        
        data = pd.DataFrame({
            'high': np.random.uniform(100, 110, 50),
            'low': np.random.uniform(90, 100, 50),
            'close': np.random.uniform(95, 105, 50),
            'volume': np.random.randint(1000, 10000, 50)
        })
        
        result = engineer._extract_technical_indicators(data)
        
        assert 'rsi' in result.columns
        assert 'macd' in result.columns
        assert 'bollinger_upper' in result.columns


class TestPricingModel:
    """定价模型测试"""

    def test_feature_extraction(self):
        """测试特征提取"""
        pytest.importorskip("sklearn")
        
        from app.ml.pricing_model import ConvertibleBondPricer
        
        pricer = ConvertibleBondPricer(model_type="sklearn")
        
        bond_data = {
            'bond_code': '123456',
            'bond_price': 110.5,
            'stock_price': 15.0,
            'conversion_price': 10.0,
            'conversion_ratio': 10,
            'coupon_rate': 0.02,
            'remaining_years': 3.5,
            'credit_rating': 'AA',
            'volume': 1000000,
            'stock_volatility_30d': 0.25
        }
        
        features = pricer.extract_features(bond_data)
        
        assert features is not None
        assert len(features) > 0

    def test_credit_rating_conversion(self):
        """测试信用评级转换"""
        pytest.importorskip("sklearn")
        
        from app.ml.pricing_model import ConvertibleBondPricer
        
        pricer = ConvertibleBondPricer()
        
        assert pricer._credit_rating_to_score('AAA') == 1.0
        assert pricer._credit_rating_to_score('AA') == 0.85
        assert pricer._credit_rating_to_score('A') == 0.70


# ============== 风控系统测试 ==============

class TestRiskMonitor:
    """风险监控测试"""

    def test_risk_metrics_calculation(self):
        """测试风险指标计算"""
        from app.risk.risk_monitor import RiskMonitor
        
        monitor = RiskMonitor()
        
        # 模拟数据
        for i in range(30):
            portfolio_value = 1000000 * (1 + np.random.randn() * 0.02)
            positions = {'bond_1': 500000, 'bond_2': 300000}
            market_data = {}
            
            monitor.update(portfolio_value, positions, market_data)
        
        # 获取最新指标
        metrics = monitor._calculate_metrics(1000000, positions, market_data)
        
        assert metrics.portfolio_value == 1000000
        assert metrics.gross_exposure > 0

    def test_var_calculation(self):
        """测试VaR计算"""
        from app.risk.risk_monitor import RiskMonitor
        
        monitor = RiskMonitor()
        
        # 生成模拟收益
        np.random.seed(42)
        returns = np.random.randn(100) * 0.02
        
        for r in returns:
            monitor.returns_history.append(r)
        
        # 计算VaR
        metrics = monitor._calculate_metrics(
            portfolio_value=1000000,
            positions={},
            market_data={}
        )
        
        # VaR应该为负值（损失）
        assert metrics.var_95 < 0

    def test_alert_generation(self):
        """测试警报生成"""
        from app.risk.risk_monitor import RiskMonitor, RiskAlert
        
        monitor = RiskMonitor()
        monitor.alert_thresholds['max_drawdown'] = 0.05
        
        # 触发警报
        monitor._create_alert(
            alert_type='max_drawdown',
            severity='high',
            message='测试警报',
            metric_value=0.08,
            threshold=0.05
        )
        
        alerts = monitor.get_active_alerts()
        
        assert len(alerts) == 1
        assert alerts[0].alert_type == 'max_drawdown'


class TestStopLossManager:
    """止损管理测试"""

    def test_add_position(self):
        """测试添加持仓"""
        from app.risk.stop_loss import StopLossManager
        
        manager = StopLossManager()
        
        manager.add_position(
            bond_code='123456',
            quantity=1000,
            avg_cost=100.0,
            atr=2.0
        )
        
        assert '123456' in manager.positions
        assert manager.positions['123456'].quantity == 1000

    def test_fixed_stop_loss(self):
        """测试固定止损"""
        from app.risk.stop_loss import StopLossManager, StopLossType
        
        manager = StopLossManager()
        
        manager.add_position(
            bond_code='123456',
            quantity=1000,
            avg_cost=100.0
        )
        
        # 更新价格触发止损
        triggered = manager.update_position('123456', 94.0)  # 下跌6%
        
        assert len(triggered) > 0

    def test_position_size_suggestion(self):
        """测试仓位建议"""
        from app.risk.stop_loss import StopLossManager
        
        manager = StopLossManager()
        
        suggestion = manager.suggest_position_size(
            portfolio_value=1000000,
            entry_price=100.0,
            stop_loss_pct=0.05,
            max_risk_pct=0.02
        )
        
        assert suggestion['suggested_shares'] > 0
        assert suggestion['position_pct'] < 1


class TestPortfolioOptimizer:
    """组合优化器测试"""

    def test_mean_variance_optimization(self):
        """测试均值-方差优化"""
        pytest.importorskip("scipy")
        
        from app.risk.portfolio_optimizer import PortfolioOptimizer, OptimizationConstraints
        
        optimizer = PortfolioOptimizer()
        
        # 模拟收益数据
        np.random.seed(42)
        returns = np.random.randn(100, 5) * 0.02
        asset_names = ['bond_1', 'bond_2', 'bond_3', 'bond_4', 'bond_5']
        
        optimizer.set_data(returns, asset_names)
        
        # 优化
        constraints = OptimizationConstraints(min_weight=0.05, max_weight=0.4)
        result = optimizer.mean_variance_optimize(constraints, 'max_sharpe')
        
        assert result.weights is not None
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_risk_parity_optimization(self):
        """测试风险平价优化"""
        pytest.importorskip("scipy")
        
        from app.risk.portfolio_optimizer import PortfolioOptimizer
        
        optimizer = PortfolioOptimizer()
        
        np.random.seed(42)
        returns = np.random.randn(100, 4) * 0.02
        asset_names = ['bond_1', 'bond_2', 'bond_3', 'bond_4']
        
        optimizer.set_data(returns, asset_names)
        
        result = optimizer.risk_parity_optimize()
        
        assert result.weights is not None


# ============== 数据平台测试 ==============

class TestFeatureStore:
    """特征存储测试"""

    def test_feature_registration(self):
        """测试特征注册"""
        from app.data_platform.feature_store import (
            FeatureStore, FeatureGroup, FeatureDefinition
        )
        
        store = FeatureStore(offline_store_path="/tmp/features")
        
        features = [
            FeatureDefinition(
                name="return_1d",
                dtype="float",
                description="1日收益率",
                transformation="return",
                dependencies=["close"]
            ),
            FeatureDefinition(
                name="volatility_20d",
                dtype="float",
                description="20日波动率",
                transformation="std",
                dependencies=["close"]
            )
        ]
        
        group = FeatureGroup(
            name="price_features",
            features=features,
            entity_key="bond_code"
        )
        
        store.register_feature_group(group)
        
        assert "price_features" in store.feature_groups

    def test_feature_computation(self):
        """测试特征计算"""
        from app.data_platform.feature_store import FeatureStore, FeatureGroup, FeatureDefinition
        
        store = FeatureStore(offline_store_path="/tmp/features")
        
        features = [
            FeatureDefinition(
                name="return_1d",
                dtype="float",
                description="收益率",
                transformation="return",
                dependencies=["close"]
            )
        ]
        
        group = FeatureGroup(
            name="test_features",
            features=features,
            entity_key="bond_code"
        )
        
        store.register_feature_group(group)
        
        # 测试数据
        data = pd.DataFrame({
            'bond_code': ['A', 'B', 'C'],
            'close': [100, 101, 102]
        })
        
        result = store.compute_features("test_features", data, ["return_1d"])
        
        assert 'return_1d' in result.columns


class TestDataLineage:
    """数据血缘测试"""

    def test_node_registration(self):
        """测试节点注册"""
        from app.data_platform.data_lineage import DataLineageTracker, NodeType
        
        tracker = DataLineageTracker()
        
        node_id = tracker.register_node(
            name="quotes_table",
            node_type=NodeType.TABLE,
            description="行情数据表"
        )
        
        assert node_id in tracker.nodes

    def test_lineage_creation(self):
        """测试血缘创建"""
        from app.data_platform.data_lineage import (
            DataLineageTracker, NodeType, EdgeType
        )
        
        tracker = DataLineageTracker()
        
        tracker.add_lineage(
            source_name="raw_quotes",
            source_type=NodeType.SOURCE,
            target_name="quotes_table",
            target_type=NodeType.TABLE,
            edge_type=EdgeType.TRANSFORM,
            transformation="clean_and_validate"
        )
        
        assert len(tracker.edges) == 1

    def test_upstream_lineage(self):
        """测试上游血缘"""
        from app.data_platform.data_lineage import (
            DataLineageTracker, NodeType, EdgeType
        )
        
        tracker = DataLineageTracker()
        
        # 创建血缘链
        tracker.add_lineage("source", NodeType.SOURCE, "table_a", NodeType.TABLE, EdgeType.DERIVED)
        tracker.add_lineage("table_a", NodeType.TABLE, "table_b", NodeType.TABLE, EdgeType.JOIN)
        tracker.add_lineage("table_b", NodeType.TABLE, "report", NodeType.REPORT, EdgeType.AGGREGATE)
        
        # 获取上游
        upstream = tracker.get_upstream_lineage("report", NodeType.REPORT)
        
        assert len(upstream) > 0

    def test_impact_analysis(self):
        """测试影响分析"""
        from app.data_platform.data_lineage import (
            DataLineageTracker, NodeType, EdgeType
        )
        
        tracker = DataLineageTracker()
        
        tracker.add_lineage("source", NodeType.SOURCE, "table_a", NodeType.TABLE, EdgeType.DERIVED)
        tracker.add_lineage("table_a", NodeType.TABLE, "model", NodeType.MODEL, EdgeType.TRANSFORM)
        tracker.add_lineage("table_a", NodeType.TABLE, "report", NodeType.REPORT, EdgeType.AGGREGATE)
        
        impact = tracker.get_impact_analysis("source", NodeType.SOURCE)
        
        assert impact['impact_summary']['total_affected'] >= 2
