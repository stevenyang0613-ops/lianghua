import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import router
from app.api.alert import router as alert_router
from app.engine.market import MarketEngine
from app.engine.alert import AlertEngine
from app.engine.storage import DataStorage
from app.engine.trade import TradeEngine


def setup_logging():
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    market_engine = MarketEngine(refresh_interval=settings.market_refresh_interval)
    alert_engine = AlertEngine()
    storage = DataStorage(settings.db_path)
    trade_engine = TradeEngine()

    async def on_market_update(bonds):
        await alert_engine.check_quotes(bonds)
        storage.save_quotes_batch(bonds)

    market_engine.subscribe(on_market_update)

    app.state.engine = market_engine
    app.state.alert_engine = alert_engine
    app.state.storage = storage
    app.state.trade_engine = trade_engine

    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    await market_engine.start()
    yield
    await market_engine.stop()
    storage.close()
    logger.info(f"Shutting down {settings.app_name}")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(alert_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "market_running": app.state.engine.is_running}
