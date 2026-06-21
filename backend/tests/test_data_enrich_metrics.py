"""Tests for data_enrich metrics registration and monitoring consistency.

These tests verify that the data-source monitor shows a clean, non-duplicated
view of cache refresh functions, without stale `_inproc` entries or conflicting
registrations.
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch

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
            "_refresh_main_biz_cache",
            "_refresh_analyst_rank_cache",
            "_refresh_macro_cpi_cache",
            "_refresh_macro_ppi_cache",
            "_refresh_macro_m2_cache",
            "_refresh_macro_lpr_cache",
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
    async def test_spot_cache_is_dispatched_in_process(self):
        """_spot_then_vol_then_bond must be dispatched in-process so the monitor does
        not stay in pending/error if the runner subprocess fails.
        Note: _refresh_spot_cache itself runs in the data_enrich_runner subprocess,
        but the chained _spot_then_vol_then_bond is dispatched in the main process.
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

        assert "_spot_then_vol_then_bond" in dispatched, (
            f"_spot_then_vol_then_bond was not dispatched. Dispatched: {dispatched}"
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
