"""多因子择时信号 API 缓存测试

验证：
1. 缓存未命中时返回默认提示，不阻塞请求
2. 缓存命中时立即返回
3. refresh_timing_signal_caches 能正确写入缓存
"""
import asyncio
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

from app.api import xb_strategy as xb


class FakeState:
    def __init__(self, engine, macro_svc):
        self.engine = engine
        self.macro_data_service = macro_svc


class FakeApp:
    def __init__(self, engine, macro_svc):
        self.state = FakeState(engine, macro_svc)


class FakeRequest:
    def __init__(self, engine, macro_svc):
        self.app = FakeApp(engine, macro_svc)


def test_compute_returns_default_when_cache_empty(monkeypatch):
    """没有缓存时，接口应立即返回默认提示，而不是长时间计算"""
    monkeypatch.setattr(xb, "_enhanced_signal_cache", None)
    monkeypatch.setattr(xb, "_enhanced_signal_cache_ts", None)
    monkeypatch.setattr(xb, "_timing_signal_cache", None)
    monkeypatch.setattr(xb, "_timing_signal_cache_ts", None)

    request = FakeRequest(MagicMock(), MagicMock())
    result = asyncio.run(xb._compute_live_timing_signal(request, enhanced=True))
    assert result["totalScore"] == 0
    assert result["marketEnv"] == "unknown"
    assert result["recommendation"] == "暂无择时信号，数据加载中..."


def test_compute_returns_cached_signal_immediately(monkeypatch):
    """有缓存时，接口应立即返回缓存内容"""
    cached = {"totalScore": 72, "marketEnv": "bull", "factors": [], "recommendation": "test"}
    monkeypatch.setattr(xb, "_enhanced_signal_cache", cached)
    monkeypatch.setattr(xb, "_enhanced_signal_cache_ts", datetime.now())

    request = FakeRequest(MagicMock(), MagicMock())
    result = asyncio.run(xb._compute_live_timing_signal(request, enhanced=True))
    assert result is cached


def test_refresh_caches_writes_enhanced_and_legacy(monkeypatch):
    """refresh_timing_signal_caches 应同时写入增强版和普通版缓存"""
    monkeypatch.setattr(xb, "_enhanced_signal_cache", None)
    monkeypatch.setattr(xb, "_enhanced_signal_cache_ts", None)
    monkeypatch.setattr(xb, "_timing_signal_cache", None)
    monkeypatch.setattr(xb, "_timing_signal_cache_ts", None)

    monkeypatch.setattr(
        xb._enhanced_timing, "calculate",
        lambda data: MagicMock(),
    )
    monkeypatch.setattr(
        xb, "_build_enhanced_data",
        lambda bonds, macro_data: MagicMock(),
    )
    monkeypatch.setattr(
        xb, "_enhanced_signal_to_frontend",
        lambda signal, macro_data: {"totalScore": 60, "modelVersion": "v4.0-enhanced"},
    )
    monkeypatch.setattr(
        xb, "_signal_to_frontend",
        lambda signal, macro_data: {"totalScore": 55},
    )

    bond = MagicMock()
    bond.premium_ratio = 10
    bond.price = 110
    bond.volume = 1000
    bond.ytm = 0

    engine = MagicMock()
    engine.get_all_quotes = AsyncMock(return_value=[bond])

    macro_svc = MagicMock()
    macro_svc.fetch_macro_data = AsyncMock(return_value=MagicMock(
        cb_median_premium=20,
        cb_avg_daily_amount=400,
        cb_index_change=0.5,
        cb_index_ma20=400,
        cb_index_current=410,
        treasury_10y_yield=2.5,
        pmi_current=50,
        pmi_prev=49,
    ))

    asyncio.run(xb.refresh_timing_signal_caches(engine, macro_svc))

    assert xb._enhanced_signal_cache is not None
    assert xb._enhanced_signal_cache_ts is not None
    assert xb._timing_signal_cache is not None
    assert xb._timing_signal_cache_ts is not None
    assert xb._enhanced_signal_cache["totalScore"] == 60
    assert xb._timing_signal_cache["totalScore"] == 55
