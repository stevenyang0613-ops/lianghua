from fastapi import APIRouter

from app.api.market import router as market_router
from app.api.ws import router as ws_router
from app.api.backtest import router as backtest_router
from app.api.history import router as history_router

router = APIRouter()
router.include_router(market_router, prefix="/market", tags=["market"])
router.include_router(ws_router, prefix="/ws", tags=["websocket"])
router.include_router(backtest_router, prefix="/backtest", tags=["backtest"])
router.include_router(history_router, prefix="/history", tags=["history"])
