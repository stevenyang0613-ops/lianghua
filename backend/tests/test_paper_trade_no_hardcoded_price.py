"""模拟盘策略价格硬编码100元问题回归测试

问题背景:
- 用户反馈模拟盘中部分策略无持仓,部分持仓标的价格显示为100元
- 检查策略代码发现多处使用 price = row.get('price', 100) 的硬编码默认值
- 策略 on_init 中也存在把缺失 price 填充为100的兜底逻辑

本测试确保:
1. PaperTradeManager 创建账户时默认使用最优参数
2. 策略评分函数在价格缺失时不默认按100元计算
3. 策略初始化不会把缺失价格填充为100元
4. 回测引擎和辅助模块不存在价格硬编码100
"""
import math

import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta

from app.engine.paper_trade_manager import PaperTradeManager
from app.strategies.fusion_strategy import FusionStrategy
from app.strategies.xuanji_twelve_factor import XuanjiTwelveFactorStrategy
from app.strategies.xibu_seven_dimension import XibuSevenDimensionStrategy
from app.strategies.sector_rotation import SectorRotationStrategy
from app.strategies.xuanji_v8 import XuanjiV8Strategy


class MockStorage:
    """最小化 Storage stub,仅用于 PaperTradeManager 初始化"""
    def __init__(self):
        self.conn = None

    def _write(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None


class TestPaperTradeOptimalParams:
    """测试模拟盘账户创建默认使用最优参数"""

    def test_create_account_uses_optimal_params_for_core_strategies(self):
        manager = PaperTradeManager(storage=MockStorage())
        for strategy_id in PaperTradeManager.CORE_STRATEGIES:
            account = manager.create_account(strategy_id)
            optimal = manager.get_optimal_params(strategy_id)
            assert account.params == optimal, (
                f"{strategy_id} 账户参数应与 OPTIMAL_PARAMS 一致,\n"
                f"期望: {optimal}\n实际: {account.params}"
            )

    def test_create_account_preserves_explicit_params(self):
        manager = PaperTradeManager(storage=MockStorage())
        explicit = {"hold_count": 5, "rebalance_days": 3}
        account = manager.create_account("xibu_seven", params=explicit)
        assert account.params == explicit


class TestStrategyNoHardcodedPrice100:
    """测试策略评分/初始化不使用100作为 price 默认值"""

    def test_fusion_estimate_credit_score_missing_price(self):
        s = FusionStrategy()
        row = pd.Series({"premium_ratio": 30, "ytm": 2, "rating_score": 80})
        score = s._estimate_credit_score(row)
        assert 0 <= score <= 100
        row_with_100 = pd.Series({"price": 100, "premium_ratio": 30, "ytm": 2, "rating_score": 80})
        score_with_100 = s._estimate_credit_score(row_with_100)
        assert score != score_with_100 or math.isnan(score)

    def test_xuanji_estimate_credit_score_missing_price(self):
        s = XuanjiTwelveFactorStrategy()
        row = pd.Series({"premium_ratio": 30, "ytm": 2, "dual_low": 130, "rating_score": 80})
        score = s._estimate_credit_score(row)
        assert 0 <= score <= 100
        row_with_100 = pd.Series({"price": 100, "premium_ratio": 30, "ytm": 2, "dual_low": 130, "rating_score": 80})
        score_with_100 = s._estimate_credit_score(row_with_100)
        assert score != score_with_100 or math.isnan(score)

    def test_xibu_estimate_credit_score_missing_price(self):
        s = XibuSevenDimensionStrategy()
        row = pd.Series({"premium_ratio": 30, "ytm": 2, "dual_low": 130})
        score = s._estimate_credit_score(row)
        assert 0 <= score <= 100
        row_with_100 = pd.Series({"price": 100, "premium_ratio": 30, "ytm": 2, "dual_low": 130})
        score_with_100 = s._estimate_credit_score(row_with_100)
        assert score != score_with_100 or math.isnan(score)

    def test_xibu_on_init_does_not_fill_missing_price_with_100(self):
        s = XibuSevenDimensionStrategy()
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(10)]
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "code": "110001",
                "date": d,
                "price": np.nan,
                "premium_ratio": 30,
                "volume": 1000,
            })
        df = pd.DataFrame(rows)
        s.on_init(df)
        prices = s._data["price"].dropna()
        assert len(prices) == 0, "缺失的 price 不应被填充为100"

    def test_sector_rotation_on_init_does_not_use_hardcoded_100(self):
        s = SectorRotationStrategy()
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(10)]
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "code": "ETF001",
                "date": d,
                "industry_code": "ETF001",
            })
        df = pd.DataFrame(rows)
        s.on_init(df)
        if "price" in s._data.columns:
            assert not (s._data["price"] == 100.0).all(), "不应硬编码 price=100"

    def test_xuanji_v8_fill_missing_columns_no_hardcoded_100(self):
        s = XuanjiV8Strategy()
        df = pd.DataFrame({
            "code": ["110001"],
            "date": [date(2024, 1, 1)],
            "premium_ratio": [30],
        })
        s._fill_missing_columns(df)
        assert "price" in df.columns
        assert df["price"].isna().all(), "无 close/close_price 时不应默认 price=100"


class TestBacktestEngineNoHardcodedPrice100:
    """测试回测引擎不使用100作为 price 默认值"""

    def test_backtest_engine_warns_when_price_column_missing(self):
        from app.engine.backtest import BacktestEngine
        from app.models.backtest import BacktestConfig
        import pandas as pd
        from datetime import date

        cfg = BacktestConfig(start_date=date(2024, 1, 1), end_date=date(2024, 1, 5))
        engine = BacktestEngine(cfg)
        df = pd.DataFrame({
            "code": ["110001", "110001"],
            "date": [date(2024, 1, 1), date(2024, 1, 2)],
            "premium_ratio": [30, 30],
            "volume": [1000, 1000],
            "change_pct": [0, 0],
        })
        # 预处理后的 price 列应为 NaN，而不是 100
        # 直接调用 run 需要策略实例；这里仅检查内部数据准备逻辑
        processed = engine._prepare_backtest_data(df)
        assert "price" in processed.columns
        assert processed["price"].isna().all(), "无 price/close 时不应默认填充 100"
