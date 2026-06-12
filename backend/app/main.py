"""
LiangHua Backend - FastAPI Application
"""

import os
from concurrent.futures import ThreadPoolExecutor

# SSL 证书修复：必须在所有网络库 import 之前设置
# PyInstaller 打包后 Python 找不到系统 CA 证书
def _fix_ssl_certs():
    try:
        import certifi
        cert_path = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', cert_path)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', cert_path)
        return
    except ImportError:
        pass
    macos_cert = '/etc/ssl/cert.pem'
    if os.path.isfile(macos_cert):
        os.environ.setdefault('SSL_CERT_FILE', macos_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', macos_cert)
        return
    brew_cert = '/opt/homebrew/etc/openssl@3/cert.pem'
    if os.path.isfile(brew_cert):
        os.environ.setdefault('SSL_CERT_FILE', brew_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', brew_cert)

_fix_ssl_certs()

import asyncio
import logging
import sys
import signal
import threading
import time
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
from app.engine.analysis import AnalysisEngine
from app.engine.scheduler import Scheduler
from app.engine.signals import SignalEngine
from app.engine.trade import TradeEngine
from app.services.macro_data import MacroDataService

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

    def on_revision(record: dict):
        """回调：检测到转股价下修时通过WebSocket广播 + 精确失效该code的缓存"""
        try:
            ae = getattr(app.state, "analysis_engine", None)
            if ae is not None:
                code = record.get("code", "")
                if code:
                    ae.invalidate_by_code(code)
        except Exception as e:
            logger.warning(f"[Revision callback] Cache invalidation error: {e}")
        try:
            # 使用 ws.py 模块中的 WebSocket 广播机制
            from app.api.ws import broadcast_revision
            broadcast_revision(record)
        except Exception as e:
            logger.warning(f"[Revision callback] Failed to broadcast: {e}")

    storage = DataStorage(settings.db_path, on_revision=on_revision)

    # 配置线程池：限制并发计算线程数，避免CPU密集任务抢占事件循环
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="compute")
    loop = asyncio.get_running_loop()
    loop.set_default_executor(executor)
    app.state.executor = executor
    engine = MarketEngine(refresh_interval=settings.market_refresh_interval, storage=storage)
    signal_engine = SignalEngine()
    signal_engine.set_storage(storage)
    trade_engine = TradeEngine()
    signal_engine.set_trade_engine(trade_engine)
    scheduler = Scheduler()

    app.state.engine = engine
    app.state.storage = storage
    app.state.signal_engine = signal_engine
    app.state.trade_engine = trade_engine
    app.state.scheduler = scheduler
    app.state.analysis_engine = AnalysisEngine(cache_ttl=30, max_entries=100)

    # 初始化宏观市场数据服务
    macro_data_service = MacroDataService(cache_ttl=1800)  # 宏观数据缓存30分钟
    app.state.macro_data_service = macro_data_service

    # 初始化告警引擎（使用简单的内存实现）
    try:
        from app.engine.alert import AlertEngine
        app.state.alert_engine = AlertEngine()
    except ImportError:
        # 如果 AlertEngine 不存在，使用轻量级内存实现
        from app.api.alert import AlertCondition, AlertTrigger
        class _SimpleAlertEngine:
            def __init__(self):
                self._alerts: dict[str, AlertCondition] = {}
                self._triggers: list[AlertTrigger] = []
            def get_alerts(self) -> list[AlertCondition]:
                return list(self._alerts.values())
            def add_alert(self, alert: AlertCondition):
                self._alerts[alert.id] = alert
            def remove_alert(self, alert_id: str):
                self._alerts.pop(alert_id, None)
        app.state.alert_engine = _SimpleAlertEngine()

    # 绑定 WebSocket manager 到 app.state
    try:
        from app.api.ws import ws_manager
        app.state.ws_manager = ws_manager
    except ImportError:
        pass

    # Connect signal engine to market engine for real-time signal generation
    engine.subscribe(signal_engine.process_quotes)

    # 注册择时信号定时刷新任务（每5分钟刷新一次宏观数据+择时信号）
    async def _refresh_timing_signal():
        try:
            bonds = await engine.get_all_quotes()
            await macro_data_service.fetch_macro_data(bonds)
            logger.info("[Scheduler] Timing signal refreshed")
        except Exception as e:
            logger.warning(f"[Scheduler] Timing signal refresh failed: {e}")

    scheduler.add_interval_task("timing_signal_refresh", _refresh_timing_signal, 300)

    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")

    # 后台启动数据加载 - 不阻塞服务器就绪
    async def background_start():
        try:
            await engine.start()
            await scheduler.start()
            # Start WS stats persistence
            from app.api.ws import start_stats_persistence
            start_stats_persistence()
            logger.info("Background data loading completed")

            # 启动数据增强缓存（行业/PE/PB 后台预热）
            try:
                from app.engine.data_enrich import start_background_refresh
                await start_background_refresh()
                logger.info("[DataEnrich] Background cache refresh started")
            except Exception as e:
                logger.warning(f"[DataEnrich] Background cache start failed: {e}")

            # 缓存预热：引擎就绪后触发一次七维排名计算，避免首次请求慢
            async def _warmup_songgang_cache():
                try:
                    from app.api.score import _compute_songgang_scores, _set_cache, _get_cache_key, _LONG_CACHE_TTL
                    from app.strategies.songgang_seven_dimension import SonggangSevenDimensionStrategy
                    import pandas as pd

                    bonds = await engine.get_all_quotes()
                    if not bonds:
                        return
                    from datetime import datetime
                    rows = []
                    for b in bonds:
                        rows.append({
                            "code": b.code, "name": b.name, "price": b.price,
                            "premium_ratio": b.premium_ratio, "volume": b.volume or 0,
                            "dual_low": b.dual_low, "change_pct": b.change_pct or 0,
                            "ytm": b.ytm or 0, "remaining_years": b.remaining_years or 0,
                            "conversion_value": b.conversion_value or 0,
                            "stock_price": b.stock_price or 0, "stock_change_pct": b.stock_change_pct or 0,
                            "forced_call_days": b.forced_call_days or 0,
                            "date": datetime.now().date(),
                        })
                    df = pd.DataFrame(rows)
                    strategy = SonggangSevenDimensionStrategy()
                    strategy.on_init(df)
                    scores_list, vetoed_list = await asyncio.to_thread(_compute_songgang_scores, strategy, df)
                    if scores_list:
                        # scores_list 已按 total 降序排列
                        top_n = 60
                        top_scores = scores_list[:top_n]
                        items = []
                        for idx, s in enumerate(top_scores):
                            items.append({
                                "rank": idx + 1,
                                "code": s['code'],
                                "name": s['name'],
                                "price": round(s['price'], 3),
                                "premium_ratio": round(s['premium_ratio'], 2),
                                "dual_low": round(s['dual_low'], 2),
                                "volume": round(s['volume'], 2),
                                "change_pct": round(s['change_pct'], 2),
                                "ytm": round(s['ytm'], 2) if s['ytm'] else None,
                                "remaining_years": round(s['remaining_years'], 2) if s['remaining_years'] else None,
                                "total_score": s['total'],
                                "stock_score": s['stock_score'],
                                "bond_score": s['bond_score'],
                                "score_details": s['stock_details'],
                                "bond_details": s['bond_details'],
                            })
                        vetoed_items = vetoed_list[:20]
                        result = {
                            "total": len(scores_list),
                            "returned": len(items),
                            "market_env": "neutral",
                            "aum_level": "small",
                            "params": {"top_n": top_n, "buffer_size": 5, "buffer_days": 3},
                            "items": items,
                            "vetoed": vetoed_items,
                            "vetoed_count": len(vetoed_list),
                            "buffer_status": [],
                            "cached": False,
                        }
                        cache_key = _get_cache_key("songgang_ranking", top_n=top_n, aum="small", market="neutral")
                        _set_cache(cache_key, result, ttl=_LONG_CACHE_TTL)
                        logger.info(f"[Warmup] Seven-dim cache preloaded: {len(scores_list)} bonds, {len(items)} items")
                except Exception as e:
                    logger.warning(f"[Warmup] Seven-dim cache preload failed: {e}")

            asyncio.create_task(_warmup_songgang_cache())

            # 自动回填历史数据：如果 daily_snapshots 中可用历史日期 < 3 个，
            # 启动后台任务从东方财富补齐，确保 N 日涨跌幅能立即生效
            async def _auto_backfill_history():
                try:
                    from app.engine.historical import HistoricalDataLoader
                    distinct_dates = storage.conn.execute(
                        "SELECT COUNT(DISTINCT snapshot_date) FROM daily_snapshots"
                    ).fetchone()[0]
                    if distinct_dates >= 3:
                        logger.info(
                            f"[AutoBackfill] daily_snapshots has {distinct_dates} dates, skip"
                        )
                        return
                    logger.warning(
                        f"[AutoBackfill] daily_snapshots 仅 {distinct_dates} 个日期，"
                        f"启动 30 天历史回填（异步执行，不阻塞其他初始化）"
                    )
                    bonds = await engine.get_all_quotes()
                    if not bonds:
                        return
                    codes = [b.code for b in bonds]
                    loader = HistoricalDataLoader(storage)
                    await loader.seed_historical_data(codes, days=30)
                    # 回填完成后清空 songgang 缓存，让前端看到新数据
                    try:
                        from app.api.score import _cache
                        cleared = sum(
                            1 for k in list(_cache.keys())
                            if k.startswith("songgang_ranking:")
                        )
                        _cache.clear()
                        logger.info(
                            f"[AutoBackfill] Cleared {cleared} songgang cache entries"
                        )
                    except Exception as ce:
                        logger.warning(f"[AutoBackfill] cache clear failed: {ce}")
                except Exception as e:
                    logger.error(f"[AutoBackfill] failed: {e}")

            asyncio.create_task(_auto_backfill_history())
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
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} {response.status_code} {duration*1000:.1f}ms")
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

app.include_router(router, prefix="/api/v1")

# ---- 挂载前端静态文件 ----
# 使用中间件方式：API 路由优先匹配，未匹配的 GET 请求返回前端 SPA
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir() and (_frontend_dist / "index.html").exists():
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi.responses import FileResponse

    class SPAMiddleware(BaseHTTPMiddleware):
        """SPA 中间件：未匹配的 GET 请求返回 index.html，让前端路由处理"""
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            # 如果路由返回 404 且是 GET 请求，返回前端 index.html
            if response.status_code == 404 and request.method == "GET":
                # 不对 API 路径返回 HTML
                if request.url.path.startswith("/api/"):
                    return response
                return FileResponse(_frontend_dist / "index.html")
            return response

    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="assets")
    app.add_middleware(SPAMiddleware)
    logger.info(f"前端静态文件已挂载: {_frontend_dist}")


def _health_response() -> dict:
    engine_running = False
    db_ok = False
    try:
        engine_running = getattr(app.state, "engine", None) and app.state.engine.is_running
    except Exception:
        pass
    try:
        storage = getattr(app.state, "storage", None)
        if storage is not None:
            storage.ensure_connection()
            storage.conn.execute("SELECT 1")
            db_ok = True
    except Exception:
        pass
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "market_running": engine_running,
        "db_ok": db_ok,
        "ws_auth_token": settings.ws_auth_token,
    }


@app.get("/health")
@app.get("/api/v1/health")
async def health_v1():
    return _health_response()
