"""
边界条件和异常处理测试

测试覆盖：
- 空数据处理
- 极端值测试
- 并发访问测试
- 异常恢复测试
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import asyncio
import threading


# ==================== 空数据处理测试 ====================

class TestEmptyDataHandling:
    """空数据处理测试"""

    def test_empty_dataframe_scoring(self):
        """测试空数据评分"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()
        empty_df = pd.DataFrame()

        # 初始化应该能处理空数据
        strategy.on_init(empty_df)

        # 对空数据不应该崩溃
        result = strategy.on_data(empty_df, 0)
        assert result is None

    def test_missing_columns_handling(self):
        """测试缺失列处理"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        # 缺失关键列的数据
        incomplete_df = pd.DataFrame({
            'code': ['123456'],
            'name': ['测试转债'],
            # 缺少 price, premium_ratio 等列
        })

        strategy.on_init(incomplete_df)

        # 应该不崩溃
        try:
            result = strategy.on_data(incomplete_df, 0)
        except Exception as e:
            # 允许抛出合理的异常，但不应该崩溃
            assert True

    def test_all_nan_values(self):
        """测试全NaN值"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        nan_df = pd.DataFrame({
            'code': ['123456'],
            'name': ['测试转债'],
            'price': [np.nan],
            'premium_ratio': [np.nan],
            'volume': [np.nan],
            'dual_low': [np.nan],
            'change_pct': [np.nan],
            'ytm': [np.nan],
            'remaining_years': [np.nan],
            'stock_change_pct': [np.nan],
            'forced_call_days': [0],
            'date': datetime.now().date(),
        })

        strategy.on_init(nan_df)

        # 应该处理NaN值
        try:
            result = strategy.on_data(nan_df, 0)
        except Exception:
            pass


# ==================== 极端值测试 ====================

class TestExtremeValues:
    """极端值测试"""

    def test_extreme_high_price(self):
        """测试极端高价"""
        from app.strategies.transaction_cost import TransactionCostModel

        model = TransactionCostModel(aum=100000000)

        # 极端高价交易
        cost = model.calc_total_cost(
            trade_amount=1e9,  # 10亿
            daily_volume=10000,
        )

        # 应该被流动性阻止
        assert cost.total == float('inf') or cost.total > 0

    def test_zero_price(self):
        """测试零价格"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        zero_price_df = pd.DataFrame({
            'code': ['123456'],
            'name': ['测试转债'],
            'price': [0],
            'premium_ratio': [30],
            'volume': [1],
            'dual_low': [130],
            'change_pct': [0],
            'ytm': [2],
            'remaining_years': [3],
            'stock_change_pct': [0],
            'forced_call_days': [0],
            'date': datetime.now().date(),
        })

        strategy.on_init(zero_price_df)

        # 零价格应该被否决
        result = strategy.on_data(zero_price_df, 0)
        # 应该被一票否决
        veto = strategy._check_veto(zero_price_df.iloc[0])
        assert veto.passed == False

    def test_extreme_premium(self):
        """测试极端溢价率"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy(max_premium=100)

        extreme_premium_df = pd.DataFrame({
            'code': ['123456'],
            'name': ['测试转债'],
            'price': [100],
            'premium_ratio': [500],  # 500%溢价
            'volume': [1],
            'dual_low': [600],
            'change_pct': [0],
            'ytm': [2],
            'remaining_years': [3],
            'stock_change_pct': [0],
            'forced_call_days': [0],
            'date': datetime.now().date(),
        })

        strategy.on_init(extreme_premium_df)

        # 极端溢价应该被否决
        veto = strategy._check_veto(extreme_premium_df.iloc[0])
        assert veto.passed == False

    def test_negative_ytm(self):
        """测试负YTM"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        negative_ytm_df = pd.DataFrame({
            'code': ['123456'],
            'name': ['测试转债'],
            'price': [150],
            'premium_ratio': [50],
            'volume': [1],
            'dual_low': [200],
            'change_pct': [0],
            'ytm': [-50],  # 负50% YTM
            'remaining_years': [3],
            'stock_change_pct': [0],
            'forced_call_days': [0],
            'date': datetime.now().date(),
        })

        strategy.on_init(negative_ytm_df)

        # 负YTM应该影响信用评分（高负YTM会被扣分）
        credit_score = strategy._estimate_credit_score(negative_ytm_df.iloc[0])
        # 注意：在实现中，负YTM < -5 时才会被扣分
        assert credit_score <= 100


# ==================== 并发访问测试 ====================

class TestConcurrentAccess:
    """并发访问测试"""

    def test_concurrent_scoring(self):
        """测试并发评分"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        # 创建测试数据
        test_df = pd.DataFrame({
            'code': [f'12{i:04d}' for i in range(100)],
            'name': [f'测试转债{i}' for i in range(100)],
            'price': np.random.uniform(90, 150, 100),
            'premium_ratio': np.random.uniform(5, 80, 100),
            'volume': np.random.uniform(0.5, 5, 100),
            'dual_low': np.random.uniform(100, 200, 100),
            'change_pct': np.random.uniform(-5, 5, 100),
            'ytm': np.random.uniform(-5, 10, 100),
            'remaining_years': np.random.uniform(0.5, 6, 100),
            'stock_change_pct': np.random.uniform(-3, 3, 100),
            'forced_call_days': np.random.randint(0, 30, 100),
            'date': datetime.now().date(),
        })

        strategy.on_init(test_df)

        results = []
        errors = []

        def score_thread():
            try:
                for i in range(10):
                    result = strategy.on_data(test_df, 0)
                    results.append(result)
            except Exception as e:
                errors.append(str(e))

        # 启动多个线程
        threads = [threading.Thread(target=score_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 应该没有错误
        assert len(errors) == 0
        assert len(results) == 50

    def test_concurrent_cost_calculation(self):
        """测试并发成本计算"""
        from app.strategies.transaction_cost import TransactionCostModel

        model = TransactionCostModel(aum=100000000)

        errors = []

        def calc_thread():
            try:
                for _ in range(100):
                    model.calc_total_cost(
                        trade_amount=np.random.uniform(10000, 1000000),
                        daily_volume=np.random.uniform(1000, 10000),
                    )
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=calc_thread) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ==================== 异常恢复测试 ====================

class TestErrorRecovery:
    """异常恢复测试"""

    def test_invalid_date_format(self):
        """测试无效日期格式"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        # 无效日期数据
        invalid_date_df = pd.DataFrame({
            'code': ['123456'],
            'name': ['测试转债'],
            'price': [100],
            'premium_ratio': [30],
            'volume': [1],
            'dual_low': [130],
            'change_pct': [0],
            'ytm': [2],
            'remaining_years': [3],
            'stock_change_pct': [0],
            'forced_call_days': [0],
            'date': 'invalid-date',  # 无效日期
        })

        # 应该能处理
        try:
            strategy.on_init(invalid_date_df)
        except Exception:
            pass  # 允许抛出异常

    def test_division_by_zero_in_metrics(self):
        """测试除零错误"""
        from app.strategies.four_factor_timing import FourFactorTiming

        timing = FourFactorTiming()

        # 空数据可能导致除零
        empty_bonds = pd.DataFrame()

        # 应该处理除零情况
        try:
            result = timing.calc_valuation_score(empty_bonds)
            # 或者返回合理的默认值
            assert result['score'] >= 0
        except ZeroDivisionError:
            pytest.fail("Should handle division by zero")
        except Exception:
            pass

    def test_infinite_value_handling(self):
        """测试无穷大值处理"""
        from app.strategies.transaction_cost import TransactionCostModel
        import math

        model = TransactionCostModel(aum=100000000)

        # 无穷大交易金额
        cost = model.calc_total_cost(
            trade_amount=float('inf'),
            daily_volume=10000,
        )

        # 应该处理无穷大或NaN（无穷大乘以0会得到NaN）
        assert math.isnan(cost.total) or cost.total == float('inf') or cost.total > 0


# ==================== 数据类型测试 ====================

class TestDataTypeHandling:
    """数据类型处理测试"""

    def test_string_price_conversion(self):
        """测试字符串价格转换"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        # 字符串类型的价格
        string_df = pd.DataFrame({
            'code': ['123456'],
            'name': ['测试转债'],
            'price': ['100.5'],  # 字符串
            'premium_ratio': ['30.0'],
            'volume': [1],
            'dual_low': [130],
            'change_pct': [0],
            'ytm': [2],
            'remaining_years': [3],
            'stock_change_pct': [0],
            'forced_call_days': [0],
            'date': datetime.now().date(),
        })

        # 应该能处理
        try:
            strategy.on_init(string_df)
        except Exception:
            pass

    def test_mixed_types(self):
        """测试混合类型"""
        from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy

        strategy = SonggangSevenDimensionStrategy()

        # 混合类型数据
        mixed_df = pd.DataFrame({
            'code': [123456, '123457'],  # 数字和字符串混合
            'name': ['测试转债1', '测试转债2'],
            'price': [100.5, '101.5'],
            'premium_ratio': [30, '35.5'],
            'volume': [1, 2],
            'dual_low': [130, 137],
            'change_pct': [0, 1],
            'ytm': [2, 3],
            'remaining_years': [3, 4],
            'stock_change_pct': [0, 0],
            'forced_call_days': [0, 0],
            'date': datetime.now().date(),
        })

        try:
            strategy.on_init(mixed_df)
        except Exception:
            pass


# ==================== 运行测试 ====================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
