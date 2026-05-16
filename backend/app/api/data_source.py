"""
数据源API端点

提供数据源管理和查询接口
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import date

router = APIRouter(prefix='/data', tags=['data'])


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
    price: float
    premium_ratio: float
    dual_low: float
    volume: float
    change_pct: float
    ytm: Optional[float]
    remaining_years: Optional[float]


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
            price=row.get('price', 0),
            premium_ratio=row.get('premium_ratio', 0),
            dual_low=row.get('dual_low', 0),
            volume=row.get('volume', 0),
            change_pct=row.get('change_pct', 0),
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
