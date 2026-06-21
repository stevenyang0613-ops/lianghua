from fastapi import APIRouter, Request, Depends

from app.api.market import router as market_router
from app.api.ws import router as ws_router
from app.api.backtest import router as backtest_router
from app.api.history import router as history_router
from app.api.trade import router as trade_router
from app.api.analysis import router as analysis_router
from app.api.signals import router as signal_router
from app.api.score import router as score_router
try:
    from app.api.xb_strategy import router as xb_strategy_router
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"xb_strategy router unavailable ({e}), skipping")
    xb_strategy_router = None
from app.api.xuanji import router as xuanji_router
from app.api.alert import router as alert_router
from app.api.auth import router as auth_router, verify_token
from app.api.accounts import router as accounts_router
from app.api.logs import router as logs_router
from app.api.data_source import router as data_source_router
from app.api.mx import router as mx_router
from app.api.fund_flow import router as fund_flow_router
from app.api.ai import router as ai_router
from app.api.paper_trade import router as paper_trade_router
from app.api.metrics import router as metrics_router
from app.api.strategies import router as strategies_router

router = APIRouter()
router.include_router(market_router, prefix="/market", tags=["market"], dependencies=[Depends(verify_token)])
router.include_router(ws_router, prefix="/ws", tags=["websocket"])  # WS auth handled in ws.py via verify_ws_auth()
router.include_router(backtest_router, prefix="/backtest", tags=["backtest"], dependencies=[Depends(verify_token)])
router.include_router(history_router, prefix="/history", tags=["history"], dependencies=[Depends(verify_token)])
router.include_router(trade_router, prefix="/trade", tags=["trade"], dependencies=[Depends(verify_token)])
router.include_router(analysis_router, prefix="/analysis", tags=["analysis"], dependencies=[Depends(verify_token)])
router.include_router(signal_router, prefix="", tags=["signals"], dependencies=[Depends(verify_token)])
router.include_router(score_router, prefix="/analysis", tags=["score"], dependencies=[Depends(verify_token)])
if xb_strategy_router is not None:
    router.include_router(xb_strategy_router, tags=["xb-strategy"], dependencies=[Depends(verify_token)])
router.include_router(xuanji_router, tags=["xuanji"], dependencies=[Depends(verify_token)])
router.include_router(alert_router, tags=["alerts"], dependencies=[Depends(verify_token)])
router.include_router(auth_router, prefix="/auth", tags=["auth"])  # 无需认证
router.include_router(accounts_router, prefix="/accounts", tags=["accounts"], dependencies=[Depends(verify_token)])
router.include_router(logs_router, prefix="/logs", tags=["logs"], dependencies=[Depends(verify_token)])
router.include_router(mx_router, tags=["mx"], dependencies=[Depends(verify_token)])
router.include_router(data_source_router, tags=["data"], dependencies=[Depends(verify_token)])
router.include_router(fund_flow_router, tags=["fund_flow"], dependencies=[Depends(verify_token)])
router.include_router(ai_router, prefix="/ai", tags=["ai"], dependencies=[Depends(verify_token)])
router.include_router(paper_trade_router, prefix="/paper-trade", tags=["paper-trade"], dependencies=[Depends(verify_token)])
router.include_router(metrics_router, prefix="/monitoring", tags=["monitoring"], dependencies=[Depends(verify_token)])
router.include_router(strategies_router, prefix="/strategies-share", tags=["strategies-share"], dependencies=[Depends(verify_token)])


# 兼容旧路径的索引端点(测试与外部消费者期望的 /api/v1/<resource> 入口)
@router.get("/backtest/plans", dependencies=[Depends(verify_token)])
async def _list_backtest_plans():
    return {"plans": [], "hint": "use /api/v1/backtest/strategies for full listing"}


@router.get("/analysis/scores", dependencies=[Depends(verify_token)])
async def _list_analysis_scores():
    return {"scores": [], "hint": "see /api/v1/analysis/* for score endpoints"}


@router.get("/strategies", dependencies=[Depends(verify_token)])
async def _list_strategies():
    return {"strategies": [], "hint": "use /api/v1/xb-strategy/* for xb strategies"}


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
        "version": settings.app_version,
        "ws_auth_token": settings.ws_auth_token,
        "market_running": engine_running,
        "db_ok": db_ok,
    }


@router.get("/data-enrich/metrics", dependencies=[Depends(verify_token)])
async def data_enrich_metrics():
    """返回所有缓存刷新的执行指标：耗时、覆盖率、bond_stock 覆盖率等"""
    from app.engine.data_enrich import get_refresh_metrics, get_cache_refresh_ts
    metrics = get_refresh_metrics()
    refresh_ts = get_cache_refresh_ts()
    return {
        "metrics": metrics,
        "refresh_ts": refresh_ts,
    }


@router.get("/data-enrich/self-check", dependencies=[Depends(verify_token)])
async def data_enrich_self_check():
    """返回字段覆盖率自检结果 + 缓存状态摘要。

    前端桌面 GUI 的 EnrichmentDashboard 使用此端点展示：
    - 各字段覆盖率(%)
    - 缓存新鲜度（fresh/stale/missing）
    - 内存缓存行数
    """
    from app.engine.data_enrich import (
        _compute_field_coverage, cache_status,
        _NORTH_CACHE, _MARGIN_CACHE, _LHB_CACHE, _BLOCK_TRADE_CACHE,
        _HOLDER_NUM_CACHE, _EARNINGS_FORECAST_CACHE, _EARNINGS_EXPRESS_CACHE,
        _RESTRICTED_RELEASE_CACHE, _FIN_CACHE, _SPOT_CACHE,
        _north_map, _margin_map, _lhb_map, _block_trade_map,
        _holder_num_map, _earnings_forecast_map, _earnings_express_map,
        _restricted_release_map, _fin_map, _spot_map,
    )
    from app.engine.data_enrich import _last_enriched_bonds

    coverage = _compute_field_coverage()
    bond_count = len(_last_enriched_bonds) if _last_enriched_bonds else 0

    # 缓存状态摘要
    cache_paths = {
        "north": (_NORTH_CACHE, 6 * 3600, len(_north_map)),
        "margin": (_MARGIN_CACHE, 12 * 3600, len(_margin_map)),
        "lhb": (_LHB_CACHE, 12 * 3600, len(_lhb_map)),
        "block_trade": (_BLOCK_TRADE_CACHE, 12 * 3600, len(_block_trade_map)),
        "holder_num": (_HOLDER_NUM_CACHE, 24 * 3600, len(_holder_num_map)),
        "earnings_forecast": (_EARNINGS_FORECAST_CACHE, 7 * 24 * 3600, len(_earnings_forecast_map)),
        "earnings_express": (_EARNINGS_EXPRESS_CACHE, 7 * 24 * 3600, len(_earnings_express_map)),
        "restricted_release": (_RESTRICTED_RELEASE_CACHE, 0, len(_restricted_release_map)),
        "fin": (_FIN_CACHE, 0, len(_fin_map)),
        "spot": (_SPOT_CACHE, 0, len(_spot_map)),
    }

    caches = {}
    for name, (path, ttl, mem_size) in cache_paths.items():
        status = cache_status(path, ttl=ttl) if ttl else "unknown"
        caches[name] = {
            "status": status,
            "memory_entries": mem_size,
        }

    return {
        "coverage": coverage,
        "bond_count": bond_count,
        "caches": caches,
    }
