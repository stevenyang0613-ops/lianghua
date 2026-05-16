from fastapi import APIRouter, Request, HTTPException, Query, Response
from pydantic import BaseModel

from app.strategies import list_strategies

router = APIRouter()


@router.get("/signals")
async def get_signals(request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        return {"signals": [], "active_strategies": [], "total": 0}
    return {
        "signals": engine.current_signals,
        "active_strategies": engine.active_strategies,
        "total": len(engine.current_signals),
    }


@router.get("/signals/history")
async def get_signal_history(
    request: Request,
    strategy: str = "",
    code: str = "",
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
):
    storage = getattr(request.app.state, "storage", None)
    if not storage:
        return {"signals": [], "total": 0}
    signals, total = storage.get_signal_history(strategy=strategy, code=code, limit=limit, offset=offset)
    return {"signals": signals, "total": total}


@router.get("/signals/stats")
async def get_signal_stats(request: Request):
    storage = getattr(request.app.state, "storage", None)
    if not storage:
        return {"total": 0, "executed": 0, "strategy_stats": []}
    return storage.get_signal_stats()


@router.get("/signals/export-csv")
async def export_signal_csv(
    request: Request,
    strategy: str = "",
    code: str = "",
    limit: int = Query(10000, le=50000),
):
    storage = getattr(request.app.state, "storage", None)
    if not storage:
        raise HTTPException(status_code=500, detail="Storage not available")
    signals, _total = storage.get_signal_history(strategy=strategy, code=code, limit=limit)
    if not signals:
        return Response(content="", media_type="text/csv", headers={"Content-Disposition": "attachment; filename=signals.csv"})
    import csv, io
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=signals[0].keys())
    writer.writeheader()
    writer.writerows(signals)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=signals.csv"},
    )


@router.post("/signals/cleanup")
async def cleanup_signal_history(request: Request, keep_days: int = Query(30, ge=7)):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    engine.cleanup_history(keep_days)
    return {"status": "ok", "keep_days": keep_days}


@router.get("/signals/executed-positions")
async def get_executed_positions(
    request: Request,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
):
    storage = getattr(request.app.state, "storage", None)
    if not storage:
        return {"positions": [], "total": 0}
    positions = storage.get_executed_positions(limit=limit, offset=offset)
    return {"positions": positions, "total": len(positions)}


@router.delete("/signals/executed-positions")
async def cleanup_executed_positions(request: Request, keep_days: int = Query(30, ge=7)):
    storage = getattr(request.app.state, "storage", None)
    if not storage:
        raise HTTPException(status_code=500, detail="Storage not available")
    count = storage.cleanup_executed_positions(keep_days)
    return {"status": "ok", "deleted": count, "keep_days": keep_days}


class StrategiesRequest(BaseModel):
    strategies: list[str]


@router.post("/signals/strategies")
async def set_active_strategies(req: StrategiesRequest, request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    available = {s["id"] for s in list_strategies()}
    for s in req.strategies:
        if s not in available:
            raise HTTPException(status_code=400, detail=f"Unknown strategy: {s}")
    engine.set_active_strategies(req.strategies)
    return {"active_strategies": engine.active_strategies}


@router.get("/signals/available-strategies")
async def get_available_strategies():
    return {"strategies": list_strategies()}


class AutoExecuteConfig(BaseModel):
    min_confidence: float = 0.0


class StrategyParamsRequest(BaseModel):
    strategy: str
    params: dict


class InvalidateCacheRequest(BaseModel):
    strategy: str | None = None


@router.put("/signals/strategy-params")
async def set_strategy_params(req: StrategyParamsRequest, request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    available = {s["id"] for s in list_strategies()}
    if req.strategy not in available:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")
    engine.set_strategy_params(req.strategy, req.params)
    return {"strategy": req.strategy, "params": req.params}


@router.post("/signals/invalidate-cache")
async def invalidate_cache(req: InvalidateCacheRequest, request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    engine.invalidate_cache(req.strategy)
    if req.strategy:
        return {"status": "ok", "invalidated": req.strategy}
    return {"status": "ok", "invalidated": "all"}


@router.post("/signals/auto-execute")
async def set_auto_execute_config(req: AutoExecuteConfig, request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    engine.set_auto_execute_min_confidence(req.min_confidence)
    return {"auto_execute_min_confidence": req.min_confidence}


class DedupConfigRequest(BaseModel):
    window_seconds: int | None = None
    price_threshold: float | None = None


@router.get("/signals/dedup-config")
async def get_dedup_config(request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    return engine.get_dedup_config()


# 策略去重推荐配置
_DEDUCK_PRESETS: dict[str, dict] = {
    "dual_low": {"window_seconds": 300, "price_threshold": 0.02, "reason": "双低策略价格波动小，5分钟窗口+2%阈值"},
    "premium_low": {"window_seconds": 600, "price_threshold": 0.03, "reason": "低溢价策略信号较少，10分钟窗口+3%阈值"},
    "momentum": {"window_seconds": 180, "price_threshold": 0.01, "reason": "动量策略信号频繁，3分钟窗口+1%阈值"},
    "volume_spike": {"window_seconds": 120, "price_threshold": 0.01, "reason": "放量策略信号密集，2分钟窗口+1%阈值"},
    "event_driven": {"window_seconds": 900, "price_threshold": 0.05, "reason": "事件驱动信号稀少，15分钟窗口+5%阈值"},
    "default": {"window_seconds": 300, "price_threshold": 0.02, "reason": "默认配置：5分钟窗口+2%阈值"},
}


@router.get("/signals/dedup-presets")
async def get_dedup_presets():
    """获取各策略的去重推荐配置"""
    return {"presets": _DEDUCK_PRESETS}


@router.put("/signals/dedup-config")
async def set_dedup_config(req: DedupConfigRequest, request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    return engine.set_dedup_config(req.window_seconds, req.price_threshold)


@router.get("/signals/health")
async def signals_health(request: Request):
    """信号引擎健康检查"""
    engine = getattr(request.app.state, "signal_engine", None)
    storage = getattr(request.app.state, "storage", None)
    from app.api.ws import active_market_connections, active_signal_connections, _ws_stats
    result: dict = {
        "engine_available": engine is not None,
        "storage_available": storage is not None,
    }
    if engine:
        result["active_strategies"] = engine.active_strategies
        result["current_signals_count"] = len(engine.current_signals)
        result["dedup_config"] = engine.get_dedup_config()
        result["cache_entries"] = len(engine._strategy_cache)
        result["auto_execute_threshold"] = engine._auto_execute_threshold
        result["executed_positions_count"] = len(engine._executed_positions)
    result["ws_connections"] = {
        "market": active_market_connections,
        "signals": active_signal_connections,
        "total": active_market_connections + active_signal_connections,
    }
    result["ws_stats_summary"] = {
        "market_messages": _ws_stats["market_messages_sent"],
        "signal_messages": _ws_stats["signal_messages_sent"],
        "disconnect_reasons": dict(_ws_stats["disconnect_reasons"]),
    }
    return result


@router.post("/signals/batch-execute")
async def batch_execute_signals(request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    trade_engine = getattr(request.app.state, "trade_engine", None)
    if not trade_engine:
        raise HTTPException(status_code=500, detail="Trade engine not available")
    signals = [s for s in engine.current_signals if not s.get("executed", False)]
    if not signals:
        return {"executed": 0, "orders": [], "message": "No pending signals"}
    # Sort: sells first (free cash), then buys
    signals.sort(key=lambda s: 0 if s["action"] == "sell" else 1)
    buy_signals = [s for s in signals if s["action"] == "buy"]
    buy_count = len(buy_signals)
    # 预分配资金：先计算总可分配现金，然后平均分配
    available_cash = trade_engine.account.cash
    buy_alloc = available_cash / max(buy_count, 1) if buy_count > 0 else 0
    results = []
    for sig in signals:
        from app.models.trade import OrderSide as Side
        side = Side.BUY if sig["action"] == "buy" else Side.SELL
        if side == Side.BUY:
            volume = max(1, int(buy_alloc / sig["price"]))
        else:
            pos = next((p for p in trade_engine.positions if p.code == sig["code"]), None)
            volume = pos.volume if pos else 10
        if side == Side.BUY:
            order = trade_engine.buy(code=sig["code"], name=sig["name"], price=sig["price"], volume=volume)
        else:
            order = trade_engine.sell(code=sig["code"], name=sig["name"], price=sig["price"], volume=volume)
        engine.mark_executed(sig["code"], sig["strategy"])
        results.append(order.model_dump())
    return {"executed": len(results), "orders": results}


class StrategyVerifyRequest(BaseModel):
    strategy: str
    start_date: str = ""
    end_date: str = ""


@router.post("/signals/verify-strategy")
async def verify_strategy(req: StrategyVerifyRequest, request: Request):
    """对信号策略进行 Walk-Forward 回测验证"""
    from app.strategies import get_strategy, list_strategies
    from app.strategies.walk_forward_backtest import WalkForwardValidator

    available = {s["id"] for s in list_strategies()}
    if req.strategy not in available:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")

    storage = getattr(request.app.state, "storage", None)
    if not storage:
        raise HTTPException(status_code=500, detail="Storage not available")

    try:
        strategy_cls = get_strategy(req.strategy)
        validator = WalkForwardValidator(
            strategy_class=strategy_cls,
            start_date=req.start_date or None,
            end_date=req.end_date or None,
        )
        validator.run_validation()
        summary = validator.get_summary()
        yearly = validator.get_yearly_performance()
        return {"strategy": req.strategy, "summary": summary, "yearly": yearly}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")


@router.post("/signals/{code}/execute")
async def execute_signal(code: str, request: Request):
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")
    trade_engine = getattr(request.app.state, "trade_engine", None)
    if not trade_engine:
        raise HTTPException(status_code=500, detail="Trade engine not available")
    signals = [s for s in engine.current_signals if s["code"] == code]
    if not signals:
        raise HTTPException(status_code=404, detail=f"No signal for {code}")
    buy_signals = [s for s in signals if s["action"] == "buy"]
    buy_count = len(buy_signals)
    buy_alloc = trade_engine.account.cash / max(buy_count, 1) if buy_count > 0 else 0
    results = []
    for sig in signals:
        from app.models.trade import OrderSide as Side
        side = Side.BUY if sig["action"] == "buy" else Side.SELL
        if side == Side.BUY:
            volume = max(1, int(buy_alloc / sig["price"]))
        else:
            pos = next((p for p in trade_engine.positions if p.code == sig["code"]), None)
            volume = pos.volume if pos else 10
        if side == Side.BUY:
            order = trade_engine.buy(code=sig["code"], name=sig["name"], price=sig["price"], volume=volume)
        else:
            order = trade_engine.sell(code=sig["code"], name=sig["name"], price=sig["price"], volume=volume)
        engine.mark_executed(sig["code"], sig["strategy"])
        results.append(order.model_dump())
    return {"executed": len(results), "orders": results}
