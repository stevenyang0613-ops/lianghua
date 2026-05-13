from fastapi import APIRouter, Request, HTTPException, Query
from datetime import date

router = APIRouter()


def _get_storage(request: Request):
    return request.app.state.storage


@router.get("/history/{code}")
async def get_quote_history(
    code: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000)
):
    storage = _get_storage(request)
    history = storage.get_quote_history(code, limit)
    return {"code": code, "history": history}


@router.get("/daily/{code}")
async def get_daily_history(
    code: str,
    request: Request,
    days: int = Query(default=30, ge=1, le=365)
):
    storage = _get_storage(request)
    history = storage.get_daily_history(code, days)
    return {"code": code, "days": days, "history": history}
