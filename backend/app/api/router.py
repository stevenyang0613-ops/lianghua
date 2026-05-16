from fastapi import APIRouter, Request

from app.api.market import router as market_router
from app.api.ws import router as ws_router
from app.api.backtest import router as backtest_router
from app.api.history import router as history_router
from app.api.trade import router as trade_router
from app.api.analysis import router as analysis_router
from app.api.signals import router as signal_router
from app.api.score import router as score_router

router = APIRouter()
router.include_router(market_router, prefix="/market", tags=["market"])
router.include_router(ws_router, prefix="/ws", tags=["websocket"])
router.include_router(backtest_router, prefix="/backtest", tags=["backtest"])
router.include_router(history_router, prefix="/history", tags=["history"])
router.include_router(trade_router, prefix="/trade", tags=["trade"])
router.include_router(analysis_router, prefix="/analysis", tags=["analysis"])
router.include_router(signal_router, prefix="", tags=["signals"])
router.include_router(score_router, prefix="/analysis", tags=["score"])


@router.get("/health")
async def api_health_check(request: Request):
    """API兼容的健康检查端点 - 路径: /api/v1/health"""
    from app.config import settings
    engine_running = False
    db_ok = False
    try:
        engine = getattr(request.app.state, "engine", None)
        engine_running = engine and engine.is_running
    except Exception:
        pass
    try:
        db_ok = getattr(request.app.state, "storage", None) is not None
    except Exception:
        pass
    return {
        "status": "ok",
        "app": settings.app_name,
        "market_running": engine_running,
        "db_ok": db_ok,
    }
