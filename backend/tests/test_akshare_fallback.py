"""
TDD测试: AKShare网络超时-本地缓存兜底
1. AKShare返回空数据时从DuckDB加载兜底
2. AKShare超时后使用内存缓存
3. storage无数据时返回空列表
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.engine.market import MarketEngine
from app.models.convertible import ConvertibleQuote


def _make_quote(code="123456", name="测试转债", price=100.0):
    return ConvertibleQuote(
        code=code, name=name, price=price, change_pct=0.0,
        stock_price=10.0, stock_change_pct=0.0,
        conversion_price=10.0, conversion_value=100.0,
        premium_ratio=0.0, dual_low=100.0, volume=1000.0,
    )


@pytest.mark.asyncio
async def test_refresh_returns_akshare_data_when_available():
    """测试: AKShare正常返回数据"""
    adapter = AsyncMock()
    quote = _make_quote()
    adapter.fetch_all_quotes.return_value = [quote]

    engine = MarketEngine(adapter=adapter)
    bonds = await engine.refresh()
    assert len(bonds) == 1
    assert bonds[0].code == "123456"


@pytest.mark.asyncio
async def test_refresh_falls_back_to_storage_when_akshare_empty():
    """测试: AKShare返回空列表时从storage加载兜底"""
    adapter = AsyncMock()
    adapter.fetch_all_quotes.return_value = []

    storage = MagicMock()
    storage.get_latest_quotes.return_value = [
        {"code": "128001", "name": "兜底转债", "price": 105.0,
         "change_pct": 0, "stock_price": 10, "stock_change_pct": 0,
         "conversion_price": 10, "conversion_value": 100,
         "premium_ratio": 5, "dual_low": 110, "volume": 2000}
    ]

    engine = MarketEngine(adapter=adapter, storage=storage)
    bonds = await engine.refresh()
    assert len(bonds) == 1
    assert bonds[0].code == "128001"
    assert bonds[0].name == "兜底转债"


@pytest.mark.asyncio
async def test_refresh_returns_empty_when_no_storage():
    """测试: 无storage且AKShare空时返回空列表"""
    adapter = AsyncMock()
    adapter.fetch_all_quotes.return_value = []

    engine = MarketEngine(adapter=adapter, storage=None)
    bonds = await engine.refresh()
    assert bonds == []


@pytest.mark.asyncio
async def test_refresh_handles_storage_error():
    """测试: storage异常时不崩溃"""
    adapter = AsyncMock()
    adapter.fetch_all_quotes.return_value = []

    storage = MagicMock()
    storage.get_latest_quotes.side_effect = Exception("DB error")

    engine = MarketEngine(adapter=adapter, storage=storage)
    bonds = await engine.refresh()
    assert bonds == []


@pytest.mark.asyncio
async def test_refresh_handles_bad_storage_row():
    """测试: storage中有坏数据行时跳过而不崩溃"""
    adapter = AsyncMock()
    adapter.fetch_all_quotes.return_value = []

    storage = MagicMock()
    storage.get_latest_quotes.return_value = [
        {"code": "128001", "name": "好的", "price": 100,
         "change_pct": 0, "stock_price": 10, "stock_change_pct": 0,
         "conversion_price": 10, "conversion_value": 100,
         "premium_ratio": 0, "dual_low": 100, "volume": 1000},
        {"code": "BAD", "name": "坏的", "price": "not_a_number"},  # 会触发 ValueError
    ]

    engine = MarketEngine(adapter=adapter, storage=storage)
    bonds = await engine.refresh()
    assert len(bonds) == 1
    assert bonds[0].code == "128001"


@pytest.mark.asyncio
async def test_akshare_adapter_returns_cache_on_timeout():
    """测试: AKShare超时后返回内存缓存"""
    from app.adapters.akshare import AKShareAdapter

    adapter = AKShareAdapter(cache_ttl=300, max_retries=1, timeout=0.01)
    # 先手动设置缓存
    cached = [_make_quote("CACHE1"), _make_quote("CACHE2", price=200)]
    adapter._cache = cached
    adapter._cache_time = datetime.now()

    result = await adapter.fetch_all_quotes()
    assert len(result) == 2
    assert result[0].code == "CACHE1"


@pytest.mark.asyncio
async def test_akshare_adapter_returns_empty_on_no_cache_timeout():
    """测试: AKShare超时且无缓存时返回空列表"""
    from app.adapters.akshare import AKShareAdapter

    adapter = AKShareAdapter(cache_ttl=0, max_retries=1, timeout=0.01)
    adapter._cache = None
    adapter._cache_time = None

    # Mock _fetch_and_merge to raise timeout
    with patch.object(adapter, '_fetch_and_merge', side_effect=asyncio.TimeoutError):
        result = await adapter.fetch_all_quotes()
        assert result == []


@pytest.mark.asyncio
async def test_engine_stores_quotes_after_successful_refresh():
    """测试: 成功刷新后quotes被保存到内存"""
    adapter = AsyncMock()
    q1 = _make_quote("111111")
    q2 = _make_quote("222222", price=200)
    adapter.fetch_all_quotes.return_value = [q1, q2]

    engine = MarketEngine(adapter=adapter)
    await engine.refresh()

    all_quotes = await engine.get_all_quotes()
    assert len(all_quotes) == 2
    codes = {q.code for q in all_quotes}
    assert codes == {"111111", "222222"}
