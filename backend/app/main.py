"""
LiangHua Backend - FastAPI Application
"""

import asyncio
import logging
import sys
import os
import signal
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.router import router
from app.engine.market import MarketEngine
from app.engine.storage import DataStorage
from app.engine.scheduler import Scheduler
from app.engine.signals import SignalEngine
from app.engine.trade import TradeEngine

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    limiter = Limiter(key_func=get_remote_address)
    HAS_RATE_LIMIT = True
except ImportError:
    limiter = None
    HAS_RATE_LIMIT = False


def setup_logging():
    level = logging.DEBUG if settings.debug else logging.INFO

    # 日志目录
    log_dir = Path.home() / ".lianghua" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "lianghua.log"

    # 文件handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    logging.basicConfig(
        level=level,
        handlers=[file_handler, console_handler],
    )

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 快速初始化 - 不等待数据加载
    storage = DataStorage(settings.db_path)
    engine = MarketEngine(refresh_interval=settings.market_refresh_interval, storage=storage)
    signal_engine = SignalEngine()
    signal_engine.set_storage(storage)
    trade_engine = TradeEngine()
    scheduler = Scheduler()

    app.state.engine = engine
    app.state.storage = storage
    app.state.signal_engine = signal_engine
    app.state.trade_engine = trade_engine
    app.state.scheduler = scheduler

    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")

    # 后台启动数据加载 - 不阻塞服务器就绪
    async def background_start():
        try:
            await engine.start()
            await scheduler.start()
            logger.info("Background data loading completed")
        except Exception as e:
            logger.error(f"Background startup error: {e}")

    background_task = asyncio.create_task(background_start())

    # Signal handling for graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler(sig: int, frame):
        sig_name = signal.Signals(sig).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        shutdown_event.set()

    # Register signal handlers (only in main thread)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

    yield

    # Graceful shutdown
    logger.info(f"Shutting down {settings.app_name}...")

    # Cancel background task
    background_task.cancel()
    try:
        await background_task
    except asyncio.CancelledError:
        pass

    # Stop engines
    try:
        await engine.stop()
        logger.info("Market engine stopped")
    except Exception as e:
        logger.error(f"Error stopping market engine: {e}")

    try:
        scheduler.stop()
        logger.info("Scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")

    try:
        storage.close()
        logger.info("Storage closed")
    except Exception as e:
        logger.error(f"Error closing storage: {e}")

    logger.info(f"{settings.app_name} shutdown complete")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

if HAS_RATE_LIMIT and limiter:
    app.state.limiter = limiter
    app.add_exception_handler(429, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = sys.float_info.epsilon  # avoid unused import
    start_time = __import__("time").time()
    response = await call_next(request)
    duration = __import__("time").time() - start_time
    logger.info(f"{request.method} {request.url.path} {response.status_code} {duration*1000:.1f}ms")
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health_root():
    return _health_response()


def _health_response() -> dict:
    engine_running = False
    db_ok = False
    try:
        engine_running = getattr(app.state, "engine", None) and app.state.engine.is_running
    except Exception:
        pass
    try:
        db_ok = getattr(app.state, "storage", None) is not None
    except Exception:
        pass
    token = settings.ws_auth_token
    result = {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "market_running": engine_running,
        "db_ok": db_ok,
        "ws_auth_token": token,
    }
    return result


@app.get("/api/v1/health")
async def health_v1():
    return _health_response()


@app.get("/debug/settings")
async def debug_settings():
    try:
        from app.config import settings
        import os
        return {
            "ws_auth_token": settings.ws_auth_token,
            "ws_auth_token_len": len(settings.ws_auth_token),
            "env_LH_WS_AUTH_TOKEN": os.environ.get("LH_WS_AUTH_TOKEN", ""),
            "has_token_file": os.path.exists(os.path.join(os.path.dirname(__file__), "..", "data", ".ws_token")),
        }
    except Exception as e:
        return {"error": str(e)}
