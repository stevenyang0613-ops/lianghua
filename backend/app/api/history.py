from fastapi import APIRouter, Request, HTTPException, Query
from datetime import date
from app.utils.data_source import DataSource

router = APIRouter()


def _get_storage(request: Request):
    return request.app.state.storage


@router.get("/records")
async def list_history_records(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000)
):
    storage = _get_storage(request)
    records = storage.list_recent_records(limit) if hasattr(storage, 'list_recent_records') else []
    return {
        "records": records,
        "count": len(records),
        "data_source": DataSource.REAL.value,
    }


@router.get("/history/{code}")
async def get_quote_history(
    code: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000)
):
    """报价历史（按时间倒序 limit 条）。前端 ChartPanel 兼容保留此路径。"""
    storage = _get_storage(request)
    history = storage.get_quote_history(code, limit)
    return {
        "code": code,
        "history": history,
        "data_source": DataSource.REAL.value,
    }


@router.get("/daily/{code}")
async def get_daily_history(
    code: str,
    request: Request,
    days: int = Query(default=30, ge=1, le=365)
):
    storage = _get_storage(request)
    history = storage.get_daily_history(code, days)
    return {
        "code": code,
        "days": days,
        "history": history,
        "data_source": DataSource.REAL.value,
    }


# 注意：必须放在最后注册。FastAPI 按注册顺序匹配，literal 路径（/records、/daily/{code}）
# 必须优先于通配参数 {code}，否则 /records 会被错误地当作 code="records" 解析。
@router.get("/{code}")
async def get_quote_history_alias(
    code: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000)
):
    """报价历史（按时间倒序 limit 条）。ChartPanel 等前端组件调用的标准路径。

    返回格式与 /history/{code} 完全一致，是后者的语义化别名（避免 /history/history/... 的双重前缀）。
    """
    storage = _get_storage(request)
    history = storage.get_quote_history(code, limit)
    return {
        "code": code,
        "history": history,
        "data_source": DataSource.REAL.value,
    }
