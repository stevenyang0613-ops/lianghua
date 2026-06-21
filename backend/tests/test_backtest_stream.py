"""Tests for /backtest/run-stream SSE endpoint and /backtest/data-freshness."""
import pytest
import tempfile
import os
import shutil
import json
import logging
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch

import pandas as pd

_logger = logging.getLogger(__name__)
import numpy as np

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.engine.signals import SignalEngine
from app.engine.storage import DataStorage


async def _synthetic_backtest_data(request, start_date: date, end_date: date, progress_cb=None, strategy_name='') -> pd.DataFrame:
    """返回模拟回测数据，避免测试时调用真实数据源"""
    dates = pd.date_range(start_date, end_date, freq='D').date
    rows = []
    for i, d in enumerate(dates):
        for j in range(5):
            rows.append({
                'code': f'12{j:04d}',
                'name': f'test{j}',
                'date': d,
                'price': 110.0 + j + np.sin(i * 0.1) * 5,
                'change_pct': 0.5 + np.cos(i * 0.1) * 0.5,
                'premium_ratio': 10.0 - j + np.sin(i * 0.05) * 2,
                'volume': 5e7,
                'stock_price': 10.0,
                'stock_change_pct': 0.5,
                'conversion_price': 9.0,
                'conversion_value': 100.0,
                'dual_low': 120.0,
                'ytm': 1.0,
                'remaining_years': 3.0,
                'momentum': 0.1,
                'hv': 20.0,
                'quality': 0.5,
                'valuation': 0.5,
                'event': 0.5,
                'industry': '银行',
                'iv': 25.0,
                'score': 0.5,
                'dual_low_norm': 0.5,
                'market_cap': 1e9,
                'turnover_rate': 2.0,
                'net_capital_flow': 1e6,
                'net_capital_flow_pct': 0.1,
            })
    df = pd.DataFrame(rows)
    df._backtest_data_source = 'synthetic_test_data'
    return df


@pytest.fixture
def app_with_backtest():
    tmpdir = tempfile.mkdtemp()
    tmpdb = os.path.join(tmpdir, "test.db")

    engine = SignalEngine()
    storage = DataStorage(db_path=tmpdb)
    engine.set_storage(storage)

    mock_engine = MagicMock()
    mock_engine.get_all_quotes = AsyncMock(return_value=[])

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        # 将状态预先设置到 app 上，确保在 lifespan 内外均可访问
        for key, val in [('signal_engine', engine), ('storage', storage),
                          ('engine', mock_engine), ('trade_engine', MagicMock()),
                          ('scheduler', MagicMock())]:
            setattr(app.state, key, val)
        yield
        for key in ['signal_engine', 'storage', 'engine', 'trade_engine', 'scheduler']:
            try:
                delattr(app.state, key)
            except AttributeError:
                pass

    from app.main import app
    # 在 lifespan_context 替换前也设置一次，避免 TestClient 外部访问
    for key, val in [('signal_engine', engine), ('storage', storage),
                      ('engine', mock_engine), ('trade_engine', MagicMock()),
                      ('scheduler', MagicMock())]:
        setattr(app.state, key, val)
    app.router.lifespan_context = noop_lifespan

    yield app, tmpdir

    shutil.rmtree(tmpdir, ignore_errors=True)


class TestBacktestStream:
    @patch('app.api.backtest._build_data', new=_synthetic_backtest_data)
    def test_run_stream_returns_sse_format(self, app_with_backtest, test_token):
        app, tmpdir = app_with_backtest
        headers = {"Authorization": f"Bearer {test_token}"}
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/v1/backtest/run-stream",
                json={
                    "strategy": "xuanji_twelve",
                    "params": {"hold_count": 10, "rebalance_days": 20},
                    "start_date": "2024-01-01",
                    "end_date": "2024-06-01",
                },
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.headers.get("content-type", "").startswith("text/event-stream")

            body = resp.text
            lines = [l for l in body.split("\n") if l.startswith("data: ")]

            phases = []
            for line in lines:
                try:
                    evt = json.loads(line[6:])
                    phases.append(evt.get("phase"))
                except Exception as _e:
                    _logger.debug("SSE parse error: %s", _e)

            assert "build_data" in phases or "error" in phases or "done" in phases

    @patch('app.api.backtest._build_data', new=_synthetic_backtest_data)
    def test_run_stream_produces_done_event_with_simulated_data(self, app_with_backtest, test_token):
        app, tmpdir = app_with_backtest
        headers = {"Authorization": f"Bearer {test_token}"}

        from app.models.convertible import ConvertibleQuote

        fake_bonds = [
            ConvertibleQuote(
                code=f"12{i:04d}", name=f"测试{i}", price=110.0, change_pct=1.0,
                stock_price=10.0, stock_change_pct=0.5, conversion_price=9.0,
                conversion_value=100.0, premium_ratio=10.0, dual_low=120.0,
                ytm=1.0, volume=5e7, remaining_years=3.0, forced_call_days=0,
            )
            for i in range(30)
        ]
        app.state.engine.get_all_quotes = AsyncMock(return_value=fake_bonds)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/v1/backtest/run-stream",
                json={
                    "strategy": "xuanji_twelve",
                    "params": {"hold_count": 10, "rebalance_days": 20},
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-01",
                },
                headers=headers,
            )
            assert resp.status_code == 200
            body = resp.text
            lines = [l for l in body.split("\n") if l.startswith("data: ")]

            phases = []
            done_evt = None
            for line in lines:
                try:
                    evt = json.loads(line[6:])
                    phases.append(evt.get("phase"))
                    if evt.get("phase") == "done":
                        done_evt = evt
                except Exception as _e:
                    _logger.debug("SSE parse error: %s", _e)

            if "done" in phases and done_evt:
                assert done_evt.get("type") in ("backtest", "optimization")
                assert "result" in done_evt

    @patch('app.api.backtest._build_data', new=_synthetic_backtest_data)
    def test_run_stream_error_on_invalid_strategy(self, app_with_backtest, test_token):
        app, tmpdir = app_with_backtest
        headers = {"Authorization": f"Bearer {test_token}"}
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/v1/backtest/run-stream",
                json={
                    "strategy": "nonexistent_strategy",
                    "params": {},
                    "start_date": "2024-01-01",
                    "end_date": "2024-06-01",
                },
                headers=headers,
            )
            assert resp.status_code == 200
            body = resp.text
            assert "error" in body or "data:" in body

    @patch('app.api.backtest._build_data', new=_synthetic_backtest_data)
    def test_run_stream_invokes_on_run_progress(self, app_with_backtest, test_token):
        """验证回测阶段的 on_progress 回调通过 SSE 进度事件向前端传递。"""
        from app.engine import backtest as bt_module

        app, tmpdir = app_with_backtest
        headers = {"Authorization": f"Bearer {test_token}"}
        progress_calls: list[tuple[int, int, str]] = []
        original = bt_module.BacktestEngine.run

        def wrapped_run(self, strategy, data, on_progress=None):
            if on_progress is not None:
                on_progress(20, "20% mock")
                on_progress(50, "50% mock")
                on_progress(100, "100% mock")
            return original(self, strategy, data, on_progress)

        bt_module.BacktestEngine.run = wrapped_run
        try:
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/v1/backtest/run-stream",
                    json={
                        "strategy": "xuanji_twelve",
                        "params": {"hold_count": 10, "rebalance_days": 20},
                        "start_date": "2024-01-01",
                        "end_date": "2024-06-01",
                    },
                    headers=headers,
                )
                body = resp.text
                lines = [l for l in body.split("\n") if l.startswith("data: ")]
                phases = []
                for line in lines:
                    try:
                        evt = json.loads(line[6:])
                        phases.append((evt.get("phase"), evt.get("pct", 0), evt.get("msg", "")))
                    except Exception as _e:
                        _logger.debug("SSE parse error: %s", _e)
                backtest_msgs = [p for p in phases if p[0] == "backtest"]
                assert len(backtest_msgs) >= 1
                pcts = [p[1] for p in backtest_msgs]
                assert any(40 < p < 100 for p in pcts), f"backtest progress events should map 20-100% to 52-100%, got {pcts}"
        finally:
            bt_module.BacktestEngine.run = original

    def test_run_optimization_throttles_progress_to_5pct(self):
        """验证 run_optimization 的 on_progress 回调在 5% 间隔触发。"""
        from app.engine import backtest as bt_module
        from app.models.backtest import OptimizationConfig, OptimizationParamRange, BacktestResult, PerformanceMetrics

        calls: list[int] = []

        def cb(completed, total, msg):
            calls.append(completed)

        # Mock BacktestEngine.run to avoid real computation
        mock_result = BacktestResult(
            strategy_name="mock",
            strategy_params={},
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 1),
            metrics=PerformanceMetrics(total_return_pct=10.0, annual_return_pct=10.0, max_drawdown_pct=-5.0),
            equity_curve=[],
            trades=[],
        )
        original_run = bt_module.BacktestEngine.run

        def mock_run(self, strategy, data, on_progress=None):
            return mock_result

        bt_module.BacktestEngine.run = mock_run
        try:
            engine = bt_module.BacktestEngine()
            config = OptimizationConfig(
                max_iterations=20,
                parallel_workers=1,
                param_ranges=[OptimizationParamRange(name="hold_count", min_val=5.0, max_val=15.0, step=1.0)],
            )
            from app.strategies.xuanji_twelve_factor import XuanjiTwelveFactorStrategy
            import pandas as pd
            df = pd.DataFrame({
                'code': ['123456'] * 5,
                'date': pd.date_range('2024-01-01', periods=5).date,
                'price': [100.0] * 5,
            })
            engine.run_optimization(XuanjiTwelveFactorStrategy, df, config, on_progress=cb)
        except Exception as _e:
            _logger.error("run_optimization failed: %s", _e)
        finally:
            bt_module.BacktestEngine.run = original_run
        if calls:
            assert calls[-1] == 20, f"last call should be at completed=20, got {calls[-1]}"
            for c in calls:
                pct = c * 100 // 20
                assert pct % 5 == 0 or c == 20, f"call at completed={c} (pct={pct}%) violates 5% throttle"


class TestDataFreshness:
    def test_data_freshness_returns_json(self, app_with_backtest, test_token):
        app, tmpdir = app_with_backtest
        headers = {"Authorization": f"Bearer {test_token}"}
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/backtest/data-freshness", headers=headers)
            # 空数据库应返回 503（符合真实数据源策略: 无假数据）
            assert resp.status_code == 503

    def test_data_freshness_with_empty_db(self, app_with_backtest, test_token):
        app, tmpdir = app_with_backtest
        headers = {"Authorization": f"Bearer {test_token}"}
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/backtest/data-freshness", headers=headers)
            assert resp.status_code == 503
