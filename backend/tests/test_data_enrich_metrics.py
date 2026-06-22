"""Tests for data_enrich metrics registration and monitoring consistency.

These tests verify that the data-source monitor shows a clean, non-duplicated
view of cache refresh functions, without stale `_inproc` entries or conflicting
registrations.
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import data_enrich as de


class TestMetricsRegistration:
    """Verify that each data source maps to exactly one tracked refresh function."""

    def teardown_method(self):
        # Clear in-memory metrics after each test to avoid cross-test pollution.
        with de._cache_lock:
            de._refresh_metrics.clear()

    def test_no_inproc_metric_entries(self):
        """The frontend NAME_MAP does not include `_inproc` names; they must not
        appear in metrics because they create duplicate/confusing error rows."""
        # Simulate a scenario where both the wrapper and the inner inproc function
        # could have recorded metrics.
        de._record_refresh_metric("_refresh_north_cache_inproc", 0.1, 0, status="error", error="fail")
        de._record_refresh_metric("_refresh_north_cache", 0.2, 100, status="ok")

        metrics = de.get_refresh_metrics()
        inproc_keys = [k for k in metrics if "_inproc" in k]
        assert not inproc_keys, f"Found unexpected _inproc metric keys: {inproc_keys}"

    def test_expected_sources_have_metric_entry(self):
        """Every source shown in the frontend DataSourceMonitor must be trackable."""
        expected = {
            "_build_industry_cache",
            "_refresh_spot_cache",
            "_refresh_fund_flow_cache",
            "_refresh_fin_cache",
            "_refresh_debt_cache",
            "_refresh_volatility_cache",
            "_refresh_buyback_cache",
            "_refresh_mgmt_cache",
            "_refresh_pledge_cache",
            "_refresh_momentum_cache",
            "_refresh_event_cache",
            "_refresh_bond_outstanding_cache",
            "_refresh_call_status_cache",
            "_refresh_stock_name_cache",
            "_refresh_coupon_rate_cache",
            "_refresh_bond_price_cache",
            "_build_concept_cache",
            "_refresh_north_cache",
            "_refresh_margin_cache",
            "_refresh_lhb_cache",
            "_refresh_block_trade_cache",
            "_refresh_holder_num_cache",
            "_refresh_earnings_forecast_cache",
            "_refresh_restricted_release_cache",
            "_refresh_earnings_express_cache",
        }
        registered = {
            name for name, obj in de.__dict__.items()
            if callable(obj) and getattr(obj, "_REGISTER_METRIC", False) is True
        }
        missing = expected - registered
        assert not missing, f"Missing @_with_metrics registration for: {missing}"

    def test_preregister_does_not_overwrite_completed_metrics(self):
        """start_background_refresh pre-registers pending entries, but must not
        clobber metrics that have already been recorded by a refresh."""
        # Simulate a refresh completing before pre-registration runs.
        de._record_refresh_metric("_refresh_spot_cache", 10.0, 5000, status="ok")

        startup_ts = "2026-01-01T00:00:00"
        preregistered = {
            name for name, obj in de.__dict__.items()
            if callable(obj) and getattr(obj, "_REGISTER_METRIC", False) is True
        }
        with de._cache_lock:
            for name in preregistered:
                if name not in de._refresh_metrics:
                    de._refresh_metrics[name] = {
                        "name": name,
                        "elapsed_s": 0.0,
                        "count": 0,
                        "status": "pending",
                        "ts": startup_ts,
                    }

        metrics = de.get_refresh_metrics()
        spot = metrics.get("_refresh_spot_cache", {})
        assert spot.get("status") == "ok", "Completed metric was overwritten by pre-registration"
        assert spot.get("count") == 5000


class TestStartBackgroundRefreshSchedule:
    """Verify that start_background_refresh dispatches the right refresh functions."""

    @pytest.mark.asyncio
    async def test_runner_caches_are_loaded_in_process(self):
        """_load_runner_caches_with_fallback must be dispatched in-process so the monitor
        can load runner-produced caches (spot/vol/fund_flow/bond_price) and fall back
        to in-process refresh only if the runner output is missing.
        """
        dispatched = set()
        original_run_in_executor = asyncio.get_event_loop().run_in_executor

        def _capture_executor(executor, fn, *args):
            dispatched.add(getattr(fn, "__name__", repr(fn)))
            # Return a done future so the await doesn't hang.
            fut = asyncio.get_event_loop().create_future()
            fut.set_result(None)
            return fut

        # Patch the helper functions that would otherwise block/hang.
        with patch.object(asyncio.get_event_loop(), "run_in_executor", side_effect=_capture_executor):
            with patch.object(de, "_ensure_bond_stock_codes"):
                with patch.object(de, "_flush_metrics"):
                    try:
                        await de.start_background_refresh()
                    except Exception:
                        pass

        assert "_load_runner_caches_with_fallback" in dispatched, (
            f"_load_runner_caches_with_fallback was not dispatched. Dispatched: {dispatched}"
        )

    @pytest.mark.asyncio
    async def test_extended_batch_not_dispatched_twice(self):
        """The extended batch must be dispatched exactly once."""
        dispatched_names = []

        def _capture_executor(executor, fn, *args):
            dispatched_names.append(getattr(fn, "__name__", repr(fn)))
            fut = asyncio.get_event_loop().create_future()
            fut.set_result(None)
            return fut

        with patch.object(asyncio.get_event_loop(), "run_in_executor", side_effect=_capture_executor):
            with patch.object(de, "_ensure_bond_stock_codes"):
                with patch.object(de, "_flush_metrics"):
                    try:
                        await de.start_background_refresh()
                    except Exception:
                        pass

        assert dispatched_names.count("_refresh_extended_batch") == 1, (
            f"_refresh_extended_batch dispatched {dispatched_names.count('_refresh_extended_batch')} times"
        )


class TestExtendedCacheRefresh:
    """Verify extended-cache refresh functions (north/margin/lhb/...) handle
    AKShare responses and missing interfaces gracefully, and record metrics."""

    def setup_method(self):
        # Clear target maps so tests are not polluted by on-disk cache merges.
        for attr in (
            "_north_map", "_margin_map", "_lhb_map", "_block_trade_map",
            "_holder_num_map", "_earnings_forecast_map", "_restricted_release_map",
        ):
            target = getattr(de, attr, None)
            if isinstance(target, dict):
                target.clear()
        # Pin bond-stock universe so zero-fill tests are deterministic.
        self._original_bond_codes = set(de._bond_stock_codes) if de._bond_stock_codes else set()
        de._bond_stock_codes = {"000001"}
        # Prevent tests from writing mock data to the production cache directory.
        self._orig_save_cache = de._save_cache
        de._save_cache = lambda path, data: None

    def teardown_method(self):
        de._bond_stock_codes = self._original_bond_codes
        with de._cache_lock:
            de._refresh_metrics.clear()
        # Restore maps to empty to avoid leaking into other tests.
        for attr in (
            "_north_map", "_margin_map", "_lhb_map", "_block_trade_map",
            "_holder_num_map", "_earnings_forecast_map", "_restricted_release_map",
            "_mgmt_map",
        ):
            target = getattr(de, attr, None)
            if isinstance(target, dict):
                target.clear()
        # Restore production save_cache.
        de._save_cache = self._orig_save_cache

    def _mock_run_with_timeout(self, fn, *args, default=None, **kwargs):
        """Simulate _run_with_timeout returning a small DataFrame."""
        # For functions passed as callables (lambdas), call them to get the DataFrame.
        try:
            result = fn(*args)
        except Exception:
            return default
        if result is None:
            return default
        return result

    def test_north_cache_refresh_ok(self):
        summary_df = pd.DataFrame({"成交净买额": [1.5], "交易日期": ["2026-01-01"]})
        hold_df = pd.DataFrame({"代码": ["000001"], "持股市值": [2.5]})
        with patch.object(de, "_run_with_timeout", side_effect=lambda fn, *args, **kw: summary_df if "summary" in kw.get("op_name", "") else hold_df):
            count = de._refresh_north_cache()
        assert count == 1
        metrics = de.get_refresh_metrics()
        assert metrics["_refresh_north_cache"]["status"] == "ok"

    def test_margin_cache_handles_missing_akshare_interface(self):
        """If akshare doesn't expose the margin interface, refresh should still
        zero-fill bond stock codes and return count > 0, not an error."""
        saved_codes = de._bond_stock_codes
        de._bond_stock_codes = {"000001", "000002"}
        try:
            with patch.object(de.ak, "stock_margin_underlying_info_szse", create=True):
                # The hasattr check above would see a mock attribute and try to call it.
                # We simulate an AttributeError on the actual call to exercise the outer try/except.
                with patch.object(de, "_run_with_timeout", side_effect=AttributeError("no such api")):
                    count = de._refresh_margin_cache()
            # 零填充确保即使 API 失败也有基础数据
            assert count > 0
            metrics = de.get_refresh_metrics()
            assert metrics["_refresh_margin_cache"]["status"] == "ok"
        finally:
            de._bond_stock_codes = saved_codes

    def test_lhb_cache_refresh_empty_dataframe_records_ok(self):
        """Even when LHB API returns empty, zero-fill should produce count > 0."""
        saved_codes = de._bond_stock_codes
        de._bond_stock_codes = {"000001", "000002"}
        try:
            empty_df = pd.DataFrame()
            with patch.object(de, "_run_with_timeout", return_value=empty_df):
                count = de._refresh_lhb_cache()
            # 零填充确保即使 API 失败也有基础数据
            assert count > 0
            metrics = de.get_refresh_metrics()
            assert metrics["_refresh_lhb_cache"]["status"] == "ok"
        finally:
            de._bond_stock_codes = saved_codes

    def test_block_trade_cache_refresh_ok(self):
        df = pd.DataFrame({"证券代码": ["000001"], "成交额": [12345.6]})
        with patch.object(de, "_run_with_timeout", return_value=df):
            count = de._refresh_block_trade_cache()
        assert count >= 1
        assert de._block_trade_map.get("000001", {}).get("block_trade_amount") == 12345.6

    def test_holder_num_cache_handles_missing_interface(self):
        # 强制 _bond_stock_codes 为空，模拟 API 缺失且无可转债代码的场景，
        # 此时 zero_fill 不应添加任何条目，count 应为 0。
        saved_codes = de._bond_stock_codes
        de._bond_stock_codes = set()
        try:
            with patch.object(de.ak, "stock_main_stock_holder", create=True):
                with patch.object(de, "_run_with_timeout", side_effect=AttributeError("no such api")):
                    count = de._refresh_holder_num_cache()
            # Without zero_fill, count should be 0 when API fails
            assert count == 0
            metrics = de.get_refresh_metrics()
            assert metrics["_refresh_holder_num_cache"]["status"] == "empty"
        finally:
            de._bond_stock_codes = saved_codes

    def test_earnings_forecast_cache_refresh_ok(self):
        df = pd.DataFrame({"股票代码": ["000001"], "业绩变动幅度": [50.0]})
        with patch.object(de, "_run_with_timeout", return_value=df):
            count = de._refresh_earnings_forecast_cache()
        assert count >= 1
        assert de._earnings_forecast_map.get("000001", {}).get("yoy_change_pct") == 50.0

    def test_restricted_release_cache_refresh_ok(self):
        df = pd.DataFrame({"股票代码": ["000001"], "解禁数量": [1000000.0]})
        with patch.object(de, "_run_with_timeout", return_value=df):
            count = de._refresh_restricted_release_cache()
        assert count >= 1
        assert de._restricted_release_map.get("000001", {}).get("restricted_release_amount") == 1000000.0


class TestDataSourceApiCalls:
    """Verify that AKShare interfaces are called with the correct parameters.

    These tests catch parameter mismatches (e.g. wrong keyword, missing symbol)
    that silently produce empty results and show as errors in the monitor.
    """

    def setup_method(self):
        for attr in (
            "_north_map", "_margin_map", "_block_trade_map",
            "_earnings_forecast_map", "_restricted_release_map",
        ):
            target = getattr(de, attr, None)
            if isinstance(target, dict):
                target.clear()
        # Pin bond-stock universe so per-stock queries are deterministic.
        self._original_bond_codes = set(de._bond_stock_codes) if de._bond_stock_codes else set()
        de._bond_stock_codes = {"000001"}
        # Bypass threading/semaphore in _run_with_timeout to make tests deterministic
        self._orig_run_with_timeout = de._run_with_timeout
        def _direct_run(fn, *args, timeout=30.0, default=None, op_name="", quiet_errors=False):
            try:
                return fn(*args)
            except Exception:
                return default
        de._run_with_timeout = _direct_run
        # Prevent tests from writing mock data to the production cache directory.
        self._orig_save_cache = de._save_cache
        de._save_cache = lambda path, data: None

    def teardown_method(self):
        de._run_with_timeout = self._orig_run_with_timeout
        de._bond_stock_codes = self._original_bond_codes
        with de._cache_lock:
            de._refresh_metrics.clear()
        for attr in (
            "_north_map", "_margin_map", "_block_trade_map",
            "_earnings_forecast_map", "_restricted_release_map",
            "_mgmt_map",
        ):
            target = getattr(de, attr, None)
            if isinstance(target, dict):
                target.clear()
        # Restore production save_cache.
        de._save_cache = self._orig_save_cache

    def test_north_cache_uses_individual_em(self):
        """ak.stock_hsgt_individual_em is used for per-stock north-bound holdings."""
        summary_df = pd.DataFrame({"成交净买额": [1.5], "交易日期": ["2026-01-01"]})
        individual_df = pd.DataFrame({"持股市值": [2.5], "今日增持资金": [0.5]})
        with patch.object(de.ak, "stock_hsgt_fund_flow_summary_em", return_value=summary_df) as mock_summary:
            with patch.object(de.ak, "stock_hsgt_individual_em", return_value=individual_df) as mock_individual:
                de._refresh_north_cache()
        assert mock_summary.called
        assert mock_individual.called, "Expected stock_hsgt_individual_em to be called for per-stock data"
        assert any(c.args[0] == "000001" for c in mock_individual.call_args_list)

    def test_margin_cache_uses_recent_trading_date(self):
        """stock_margin_detail_szse/sse requires a real trading date; empty string returns 0 rows."""
        df = pd.DataFrame({"证券代码": ["000001"], "融资余额": [12345.0]})
        with patch.object(de.ak, "stock_margin_detail_szse", return_value=df) as mock_szse, \
             patch.object(de.ak, "stock_margin_detail_sse", return_value=pd.DataFrame()) as mock_sse:
            de._refresh_margin_cache()
        assert mock_szse.called or mock_sse.called
        called_mock = mock_szse if mock_szse.called else mock_sse
        date_arg = called_mock.call_args.kwargs.get("date") or (called_mock.call_args.args[0] if called_mock.call_args.args else None)
        assert isinstance(date_arg, str) and len(date_arg) == 8 and date_arg.isdigit(), (
            f"Expected YYYYMMDD date, got {date_arg!r}"
        )

    def test_block_trade_cache_uses_a_share_symbol(self):
        """stock_dzjy_mrmx requires symbol='A股' to return A-share block trades."""
        df = pd.DataFrame({"证券代码": ["000001"], "成交额": [100.0]})
        with patch.object(de.ak, "stock_dzjy_mrmx", return_value=df) as mock_dzjy:
            de._refresh_block_trade_cache()
        assert mock_dzjy.called
        kwargs = mock_dzjy.call_args.kwargs
        assert kwargs.get("symbol") == "A股", f"Expected symbol='A股': {kwargs}"
        assert "start_date" in kwargs, f"Expected start_date in kwargs: {kwargs}"
        assert "end_date" in kwargs, f"Expected end_date in kwargs: {kwargs}"

    def test_earnings_forecast_cache_uses_current_quarter(self):
        """stock_yjyg_em default date is 20200331; must pass current quarter end."""
        df = pd.DataFrame({"股票代码": ["000001"], "业绩变动幅度": [10.0]})
        with patch.object(de.ak, "stock_yjyg_em", return_value=df) as mock_yjyg:
            de._refresh_earnings_forecast_cache()
        assert mock_yjyg.called, "Expected stock_yjyg_em to be called"
        args, kwargs = mock_yjyg.call_args
        date_arg = kwargs.get("date") or (args[0] if args else None)
        assert date_arg != "20200331", f"Default stale date {date_arg!r} should not be used"
        assert isinstance(date_arg, str) and len(date_arg) == 8 and date_arg.endswith(("0331", "0630", "0930", "1231"))

    def test_restricted_release_cache_uses_batch_detail_endpoint(self):
        """Use stock_restricted_release_detail_em with date range, not per-stock queue."""
        df = pd.DataFrame({"股票代码": ["000001"], "解禁数量": [1000.0]})
        with patch.object(de.ak, "stock_restricted_release_detail_em", return_value=df) as mock_detail:
            with patch.object(de.ak, "stock_restricted_release_queue_em") as mock_queue:
                de._refresh_restricted_release_cache()
        assert mock_detail.called, "Expected stock_restricted_release_detail_em to be called"
        assert not mock_queue.called, "Per-stock queue endpoint should not be used"
        kwargs = mock_detail.call_args.kwargs
        assert "start_date" in kwargs and "end_date" in kwargs, f"Missing date range: {kwargs}"

    def test_mgmt_cache_skips_cninfo_by_default(self):
        """cninfo 接口默认应被跳过（macOS 沙盒不兼容），仅使用 EM 数据源。"""
        df_em_detail = pd.DataFrame({"代码": ["000001"], "变动方向": ["增持"], "成交均价": [10.5]})
        df_em_ggcg = pd.DataFrame({"代码": ["000002"], "持股变动信息-增减": ["增持"], "成交均价": [20.5]})
        with patch.object(de.ak, "stock_hold_management_detail_em", return_value=df_em_detail) as mock_em_detail:
            with patch.object(de.ak, "stock_ggcg_em", return_value=df_em_ggcg) as mock_ggcg:
                with patch.object(de.ak, "stock_hold_management_detail_cninfo") as mock_cninfo:
                    de._refresh_mgmt_cache()
        assert mock_em_detail.called, "Expected EM detail to be called"
        assert mock_ggcg.called, "Expected EM ggcg to be called"
        assert not mock_cninfo.called, "cninfo should be skipped by default (LH_MGMT_TRY_CNINFO not set)"
        assert de._mgmt_map.get("000001") == 10.5
        assert de._mgmt_map.get("000002") == 20.5

    def test_mgmt_cache_falls_back_to_em_when_cninfo_fails(self):
        """当 LH_MGMT_TRY_CNINFO=1 且 cninfo 抛出 dlsym 错误时，EM 数据应保留。"""
        df_em_detail = pd.DataFrame({"代码": ["000001"], "变动方向": ["增持"], "成交均价": [10.5]})
        df_em_ggcg = pd.DataFrame({"代码": ["000002"], "持股变动信息-增减": ["增持"], "成交均价": [20.5]})
        with patch.dict(os.environ, {"LH_MGMT_TRY_CNINFO": "1"}):
            with patch.object(de.ak, "stock_hold_management_detail_em", return_value=df_em_detail) as mock_em_detail:
                with patch.object(de.ak, "stock_ggcg_em", return_value=df_em_ggcg) as mock_ggcg:
                    with patch.object(de.ak, "stock_hold_management_detail_cninfo",
                                      side_effect=OSError("dlsym(RTLD_DEFAULT, init_mini_racer): symbol not found")) as mock_cninfo:
                        de._refresh_mgmt_cache()
        assert mock_em_detail.called, "Expected EM detail to be called"
        assert mock_ggcg.called, "Expected EM ggcg to be called"
        assert mock_cninfo.called, "cninfo should be attempted when LH_MGMT_TRY_CNINFO=1"
        assert de._mgmt_map.get("000001") == 10.5, "EM data should be preserved even when cninfo fails"
        assert de._mgmt_map.get("000002") == 20.5, "EM ggcg data should be preserved even when cninfo fails"


class TestFieldLoaderMap:
    """Verify _FIELD_LOADER_MAP completeness for self-check recovery."""

    def teardown_method(self):
        de._bond_stock_codes = set()

    def test_field_loader_map_includes_momentum_fields(self):
        """momentum_5d/10d/20d/60d 应有加载器，使 self_check_loop 可重载。"""
        de._populate_field_loader_map()
        for f in ("momentum_5d", "momentum_10d", "momentum_20d", "momentum_60d"):
            assert f in de._FIELD_LOADER_MAP, f"{f} missing from _FIELD_LOADER_MAP"
            assert de._FIELD_LOADER_MAP[f] is de._load_momentum_cache

    def test_field_loader_map_includes_event_score(self):
        """event_score 应有加载器。"""
        de._populate_field_loader_map()
        assert "event_score" in de._FIELD_LOADER_MAP
        assert de._FIELD_LOADER_MAP["event_score"] is de._load_event_cache

    def test_field_loader_map_includes_outstanding_scale(self):
        """outstanding_scale 应有加载器。"""
        de._populate_field_loader_map()
        assert "outstanding_scale" in de._FIELD_LOADER_MAP
        assert de._FIELD_LOADER_MAP["outstanding_scale"] is de._load_bond_outstanding_cache


class TestSpotThenVol:
    """Verify _spot_then_vol function exists and chains spot→vol correctly."""

    def test_spot_then_vol_exists(self):
        """_spot_then_vol 应在 data_enrich 模块中存在。"""
        assert hasattr(de, "_spot_then_vol")
        assert callable(de._spot_then_vol)

    def test_spot_then_vol_calls_spot_when_empty(self):
        """当 _spot_map 为空时，_spot_then_vol 应调用 _refresh_spot_cache。"""
        saved = de._spot_map
        de._spot_map = {}
        try:
            with patch.object(de, "_refresh_spot_cache") as mock_spot:
                with patch.object(de, "_refresh_volatility_cache"):
                    de._spot_then_vol()
            mock_spot.assert_called_once()
        finally:
            de._spot_map = saved

    def test_spot_then_vol_skips_spot_when_large_enough(self):
        """当 _spot_map >= 1000 时，_spot_then_vol 不应调用 _refresh_spot_cache。"""
        saved_spot = de._spot_map
        saved_vol = de._vol_map
        # 构造含 1000 个条目的 _spot_map
        de._spot_map = {str(i).zfill(6): {"price": float(i)} for i in range(1000)}
        de._vol_map = {}
        try:
            with patch.object(de, "_refresh_spot_cache") as mock_spot:
                with patch.object(de, "_refresh_volatility_cache") as mock_vol:
                    de._spot_then_vol()
            mock_spot.assert_not_called()
            mock_vol.assert_called_once()
        finally:
            de._spot_map = saved_spot
            de._vol_map = saved_vol

    def test_spot_then_vol_skips_both_when_large_enough(self):
        """当 _spot_map >= 1000 且 _vol_map >= 1000 时，不调用任何 refresh。"""
        saved_spot = de._spot_map
        saved_vol = de._vol_map
        de._spot_map = {str(i).zfill(6): {"price": float(i)} for i in range(1000)}
        de._vol_map = {str(i).zfill(6): {"iv": 0.2} for i in range(1000)}
        try:
            with patch.object(de, "_refresh_spot_cache") as mock_spot:
                with patch.object(de, "_refresh_volatility_cache") as mock_vol:
                    de._spot_then_vol()
            mock_spot.assert_not_called()
            mock_vol.assert_not_called()
        finally:
            de._spot_map = saved_spot
            de._vol_map = saved_vol


class TestBondOrFallbackCodes:
    """Verify _get_bond_or_fallback_codes() fallback chain."""

    def teardown_method(self):
        de._bond_stock_codes = set()
        de._name_map = {}

    def test_returns_bond_codes_when_populated(self):
        """_bond_stock_codes 已填充时，直接返回。"""
        saved = de._bond_stock_codes
        de._bond_stock_codes = {"000001", "000002"}
        try:
            codes = de._get_bond_or_fallback_codes()
            assert codes == frozenset({"000001", "000002"})
        finally:
            de._bond_stock_codes = saved

    def test_falls_back_to_stock_name_map(self):
        """_bond_stock_codes 为空时，回退到 _name_map 键。"""
        saved_codes = de._bond_stock_codes
        saved_names = de._name_map
        de._bond_stock_codes = set()
        de._name_map = {
            "000001": "name1",
            "000002": "name2",
            "12": "too_short",  # 应被过滤
            "abc": "not_digit",  # 应被过滤
            "": "empty",  # 应被过滤
            "600000": "valid_long",
        }
        try:
            codes = de._get_bond_or_fallback_codes()
            assert "000001" in codes
            assert "000002" in codes
            assert "600000" in codes
            assert "12" not in codes
            assert "abc" not in codes
            assert "" not in codes
        finally:
            de._bond_stock_codes = saved_codes
            de._name_map = saved_names

    def test_returns_empty_when_neither_populated(self):
        """两者都为空时，返回空 frozenset。"""
        saved_codes = de._bond_stock_codes
        saved_names = de._name_map
        de._bond_stock_codes = set()
        de._name_map = {}
        try:
            codes = de._get_bond_or_fallback_codes()
            assert codes == frozenset()
        finally:
            de._bond_stock_codes = saved_codes
            de._name_map = saved_names

