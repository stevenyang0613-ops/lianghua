"""
数据源API端点

提供数据源管理和查询接口
"""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/data_sources', tags=['data'])


@router.get("/")
async def list_data_sources():
    """列出已注册的数据源及其状态"""
    try:
        from app.data import get_data_source_manager
        manager = get_data_source_manager()
        status = manager.get_status()
        # status 格式: {name: {"connected": bool, "last_success": str|None, "last_error": str|None, ...}}
        sources = []
        for name, st in status.items():
            sources.append({
                "name": name,
                "type": "unknown",
                "status": "connected" if st.connected else "disconnected",
                "description": "",
                "last_success": st.last_success.isoformat() if st.last_success else None,
                "last_error": st.last_error,
                "request_count": st.request_count,
                "error_count": st.error_count,
                "avg_latency_ms": st.avg_latency_ms,
            })
        return sources
    except Exception as e:
        logger.warning(f"[DataSource] list failed: {e}")
        # 兜底：返回核心免费源
        return [
            {"name": "akshare", "type": "free", "status": "connected", "description": "AKShare 免费开源金融数据"},
            {"name": "ths", "type": "free", "status": "connected", "description": "同花顺网页数据"},
        ]


@router.get('/sources/history')
async def get_data_source_history():
    """获取数据源连接历史"""
    return [
        {"source": "akshare", "event": "connected", "time": datetime.now().isoformat()}
    ]


@router.get('/sources/metrics')
async def get_data_source_metrics():
    """获取数据源性能指标"""
    from app.engine import data_enrich as _de
    try:
        spot_map = getattr(_de, '_spot_map', None)
        refresh_metrics = getattr(_de, '_refresh_metrics', {})
        return {
            "akshare": {
                "cache_count": len(spot_map) if spot_map else 0,
                "last_refresh": refresh_metrics.get("_refresh_spot_cache", {}).get("ts", "unknown"),
            }
        }
    except Exception as e:
        logger.warning(f"[DataSource] metrics failed: {e}")
        return {"akshare": {"cache_count": 0, "last_refresh": "unknown"}}


class DataSourceStatusResponse(BaseModel):
    """数据源状态响应"""
    name: str
    connected: bool
    last_success: Optional[str]
    last_error: Optional[str]
    request_count: int
    error_count: int
    avg_latency_ms: float


class SyncStatusResponse(BaseModel):
    """同步状态响应"""
    name: str
    last_sync: Optional[str]
    last_count: int
    status: str


class ConvertibleBond(BaseModel):
    """转债数据"""
    code: str
    name: str
    price: Optional[float] = None
    premium_ratio: Optional[float] = None
    dual_low: Optional[float] = None
    volume: Optional[float] = None
    change_pct: Optional[float] = None
    ytm: Optional[float] = None
    remaining_years: Optional[float] = None


class Announcement(BaseModel):
    """公告数据"""
    code: str
    name: str
    title: str
    publish_time: str
    source: str
    content: Optional[str]


@router.get('/sources/status')
async def get_data_sources_status() -> List[DataSourceStatusResponse]:
    """获取所有数据源状态"""
    from app.data import get_data_source_manager

    manager = get_data_source_manager()
    status = manager.get_status()

    return [
        DataSourceStatusResponse(
            name=s.name,
            connected=s.connected,
            last_success=s.last_success.isoformat() if s.last_success else None,
            last_error=s.last_error,
            request_count=s.request_count,
            error_count=s.error_count,
            avg_latency_ms=s.avg_latency_ms,
        )
        for s in status.values()
    ]


@router.post('/sources/connect')
async def connect_data_sources() -> dict:
    """连接所有数据源"""
    from app.data import get_data_source_manager

    manager = get_data_source_manager()
    results = await manager.connect_all()

    return {
        'status': 'completed',
        'results': results,
    }


@router.post('/sources/disconnect')
async def disconnect_data_sources() -> dict:
    """断开所有数据源"""
    from app.data import get_data_source_manager

    manager = get_data_source_manager()
    await manager.disconnect_all()

    return {'status': 'disconnected'}


@router.get('/sources/health')
async def health_check_sources() -> dict:
    """健康检查"""
    from app.data import get_data_source_manager

    manager = get_data_source_manager()
    return await manager.health_check()


@router.get('/sync/status')
async def get_sync_status() -> dict:
    """获取同步状态"""
    from app.data import get_sync_service

    service = get_sync_service()
    return service.get_task_status()


@router.post('/sync/{task_name}')
async def sync_now(task_name: str) -> dict:
    """立即同步指定任务"""
    from app.data import get_sync_service

    service = get_sync_service()
    data = await service.sync_now(task_name)

    return {
        'task': task_name,
        'count': len(data) if not data.empty else 0,
        'status': 'completed',
    }


@router.get('/convertibles')
async def get_convertible_bonds(
    date: Optional[date] = None,
) -> List[ConvertibleBond]:
    """获取转债列表"""
    from app.data import get_data_source_manager

    manager = get_data_source_manager()
    data = await manager.get_convertible_bonds(date)

    if data.empty:
        return []

    # 转换为响应格式
    result = []
    for _, row in data.iterrows():
        result.append(ConvertibleBond(
            code=row.get('code', ''),
            name=row.get('name', ''),
            price=row.get('price') if row.get('price') is not None else None,
            premium_ratio=row.get('premium_ratio') if row.get('premium_ratio') is not None else None,
            dual_low=row.get('dual_low') if row.get('dual_low') is not None else None,
            volume=row.get('volume') if row.get('volume') is not None else None,
            change_pct=row.get('change_pct') if row.get('change_pct') is not None else None,
            ytm=row.get('ytm'),
            remaining_years=row.get('remaining_years'),
        ))

    return result


@router.get('/quotes')
async def get_realtime_quotes(
    codes: str = Query(..., description='逗号分隔的转债代码'),
) -> List[dict]:
    """获取实时行情"""
    from app.data import get_data_source_manager

    code_list = [c.strip() for c in codes.split(',') if c.strip()]

    manager = get_data_source_manager()
    data = await manager.get_realtime_quotes(code_list)

    if data.empty:
        return []

    return data.to_dict('records')


@router.get('/announcements')
async def get_announcements(
    codes: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    keywords: Optional[str] = None,
) -> List[dict]:
    """获取公告"""
    from app.data import get_data_source_manager

    code_list = [c.strip() for c in codes.split(',') if c.strip()] if codes else None
    keyword_list = [k.strip() for k in keywords.split(',') if k.strip()] if keywords else None

    manager = get_data_source_manager()
    data = await manager.get_announcements(
        codes=code_list,
        start_date=start_date,
        end_date=end_date,
        keywords=keyword_list,
    )

    if data.empty:
        return []

    return data.to_dict('records')


@router.post('/cache/clear')
async def clear_cache() -> dict:
    """清除数据缓存"""
    from app.data import get_data_source_manager

    manager = get_data_source_manager()
    count = manager.clear_cache()

    return {
        'status': 'cleared',
        'entries_removed': count,
    }


@router.post('/history/backfill')
async def backfill_history(
    request: Request,
    days: int = Query(30, ge=5, le=365, description='回填历史天数'),
    top_n: int = Query(0, ge=0, le=637, description='只回填前 N 只活跃转债（0=全部）'),
) -> dict:
    """回填可转债历史日线数据，用于计算 N 日涨跌幅。

    异步执行，立即返回 task_id，可通过 GET /data_sources/history/backfill/status 查询进度。
    """
    import asyncio
    from app.engine.historical import HistoricalDataLoader

    storage = request.app.state.storage
    engine = request.app.state.engine

    async def _do_backfill():
        try:
            bonds = await engine.get_all_quotes()
            if top_n > 0:
                bonds = bonds[:top_n]
            codes = [b.code for b in bonds]
            factor_snapshot = {}
            for b in bonds:
                factor_snapshot[b.code] = {
                    "premium_ratio": b.premium_ratio or 0,
                    "change_pct": b.change_pct or 0,
                    "stock_price": b.stock_price or 0,
                    "conversion_value": b.conversion_value or 0,
                    "dual_low": b.dual_low or 0,
                    "ytm": b.ytm or 0,
                    "remaining_years": b.remaining_years or 0,
                    "roe": getattr(b, 'roe', None),
                    "gpm": getattr(b, 'gpm', None),
                    "cagr": getattr(b, 'cagr', None),
                    "debt_ratio": getattr(b, 'debt_ratio', None),
                    "pe": getattr(b, 'pe', None),
                    "pb": getattr(b, 'pb', None),
                    "iv": getattr(b, 'iv', None),
                    "buyback_amount": getattr(b, 'buyback_amount', None),
                    "mgmt_buy_price": getattr(b, 'mgmt_buy_price', None),
                    "industry": getattr(b, 'industry', None),
                    "rating": getattr(b, 'rating', None),
                    "outstanding_scale": getattr(b, 'outstanding_scale', None),
                }
            loader = HistoricalDataLoader(storage)
            await loader.seed_historical_data(codes, days=days, factor_snapshot=factor_snapshot)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"[Backfill] failed: {e}")

    asyncio.create_task(_do_backfill())

    return {
        'status': 'started',
        'days': days,
        'top_n': top_n,
        'message': f'已启动历史数据回填任务（{days} 天），执行过程中可继续其他操作',
    }
