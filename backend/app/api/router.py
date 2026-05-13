from fastapi import APIRouter

from app.api.market import router as market_router
from app.api.ws import router as ws_router

router = APIRouter()
router.include_router(market_router, prefix="/market", tags=["market"])
router.include_router(ws_router, prefix="/ws", tags=["websocket"])
