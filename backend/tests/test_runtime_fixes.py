"""运行时关键 bug 修复的回归测试."""
import inspect
import json
import math
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


class TestWebSocketNaNSerialization:
    """ws.py 必须将 NaN/Inf 序列化为合法 JSON (None)."""

    def test_sanitize_json_replaces_nan_inf(self):
        from app.api.ws import _sanitize_json_value

        data = {
            "price": 10.5,
            "pe": float("nan"),
            "pb": float("inf"),
            "neg_inf": float("-inf"),
            "nested": {"ratio": float("nan"), "valid": 1.0},
            "list": [1.0, float("nan"), 2.0],
        }
        clean = _sanitize_json_value(data)
        assert clean["price"] == 10.5
        assert clean["pe"] is None
        assert clean["pb"] is None
        assert clean["neg_inf"] is None
        assert clean["nested"]["ratio"] is None
        assert clean["nested"]["valid"] == 1.0
        assert clean["list"] == [1.0, None, 2.0]
        # 确保可以合法 JSON 序列化
        assert json.dumps(clean)


class TestSignalParamsSignature:
    """signals._params_signature 必须支持混合类型参数不抛异常."""

    def test_params_signature_mixed_types(self):
        from app.engine.signals import SignalEngine

        sig = SignalEngine._params_signature("s1", {"a": 1, "b": "x", "c": True})
        assert "s1:" in sig
        # 使用 json.dumps 后对 key 排序，key 应出现在签名中
        assert "a" in sig and "b" in sig and "c" in sig

    def test_params_signature_uncomparable_values(self):
        from app.engine.signals import SignalEngine

        # 旧实现 sorted(params.items()) 会在此抛 TypeError
        params = {"threshold": 0.05, "mode": "abc", "flag": 1}
        sig = SignalEngine._params_signature("s2", params)
        assert sig.startswith("s2:")


class TestTdxFinanceBatch:
    """TdxAdapter fetch_finance_batch 必须保留仅含 ROE 的数据."""

    def test_roe_only_not_dropped(self):
        from app.adapters.tdx_adapter import TdxAdapter

        adapter = TdxAdapter()
        with patch.object(adapter, "fetch_finance_info") as mock_fetch:
            mock_fetch.side_effect = [
                {"pe": None, "pb": None, "eps": None, "roe": 0.12},
                {"pe": 10.0, "pb": 1.5, "eps": 1.0},
            ]
            result = adapter.fetch_finance_batch(["000001", "000002"])
        assert "000001" in result
        assert result["000001"]["roe"] == 0.12
        assert "000002" in result


class TestPercentileScoreEdgeCases:
    """enhanced_timing_model.percentile_score 边界保护."""

    def test_equal_bounds_returns_neutral(self):
        from app.strategies.enhanced_timing_model import percentile_score

        # value == lower == upper 时，按 <= lower 返回 100，但除零已保护
        # 更合理的行为是上下界相等时返回中性分 50
        score = percentile_score(5.0, 5.0, 5.0)
        assert score == 50.0

    def test_nan_value(self):
        from app.strategies.enhanced_timing_model import percentile_score

        assert math.isnan(percentile_score(float("nan"), 0.0, 10.0))


class TestFusionStrategyPortfolioStopLoss:
    """fusion_strategy 组合止损不得返回 __PORTFOLIO__ 伪代码."""

    def test_portfolio_stop_loss_no_pseudo_code(self):
        from app.strategies.fusion_strategy import FusionStrategy

        params = {
            "portfolio_stop_loss": -5.0,
            "trailing_stop_pct": -10.0,
            "rebalance_days": 1,
            "max_premium": 100.0,
            "min_price": 0.0,
            "max_price": 1000.0,
            "top_n": 10,
        }
        strategy = FusionStrategy(**params)

        init_data = pd.DataFrame({
            "code": ["123001", "123002", "123001", "123002"],
            "date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02"],
            "price": [100.0, 100.0, 100.0, 100.0],
            "premium_ratio": [10.0, 20.0, 10.0, 20.0],
            "change_pct": [0.0, 0.0, 0.0, 0.0],
            "volume": [100, 100, 100, 100],
        })
        strategy.on_init(init_data)
        strategy._prev_selected = {"123001", "123002"}
        strategy._buy_prices = {"123001": 100.0, "123002": 100.0}
        strategy._portfolio_peak = 1.0

        data = pd.DataFrame({
            "code": ["123001", "123002", "123003"],
            "price": [90.0, 95.0, 100.0],
            "premium_ratio": [10.0, 20.0, 30.0],
            "volume": [100, 100, 100],
        })
        sigs = strategy.on_data(data, 0)
        assert sigs is not None
        codes = [s["code"] for s in sigs]
        assert "__PORTFOLIO__" not in codes
        assert "123001" in codes
        assert "123002" in codes
        assert all(s["action"] == "sell" for s in sigs)


class TestAutoExecuteGuards:
    """SignalEngine._auto_execute 必须有持仓才卖、失败不透支现金."""

    def test_sell_skips_when_no_position(self):
        from app.engine.signals import SignalEngine, TradeSignal
        from unittest.mock import MagicMock

        engine = SignalEngine()
        trade_engine = MagicMock()
        trade_engine.positions = []
        trade_engine.account = MagicMock(cash=100000)
        engine.set_trade_engine(trade_engine)
        engine.set_auto_execute_min_confidence(0.5)

        sig = TradeSignal(
            strategy="test",
            code="000001",
            name="test",
            action="sell",
            price=10.0,
            reason="test",
            confidence=0.9,
        )
        engine._auto_execute([sig])
        # 无持仓，应跳过，不调用 sell
        trade_engine.sell.assert_not_called()
        assert sig.executed is False

    def test_buy_failure_does_not_mark_executed(self):
        from app.engine.signals import SignalEngine, TradeSignal
        from unittest.mock import MagicMock

        engine = SignalEngine()
        account = MagicMock()
        account.cash = 10000
        trade_engine = MagicMock()
        trade_engine.account = account
        trade_engine.positions = []
        trade_engine.buy.side_effect = Exception("no liquidity")
        engine.set_trade_engine(trade_engine)
        engine.set_auto_execute_min_confidence(0.5)

        sig = TradeSignal(
            strategy="test",
            code="000001",
            name="test",
            action="buy",
            price=10.0,
            reason="test",
            confidence=0.9,
        )
        engine._auto_execute([sig])
        # 买入失败不应被标记为已执行
        assert sig.executed is False


class TestMacroDataWait:
    """macro_data 应使用 wait 收集已完成任务，避免超时丢失结果."""

    def test_fetch_all_uses_wait_not_as_completed(self):
        from app.services import macro_data

        source = inspect.getsource(macro_data.MacroDataService._fetch_all)
        assert "wait(" in source
        assert "as_completed(" not in source
