from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from app.strategies import list_strategies

router = APIRouter()


@router.get("/signals")
async def get_signals(request: Request):
    """获取当前交易信号"""
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        return {"signals": [], "active_strategies": []}
    return {
        "signals": engine.current_signals,
        "active_strategies": engine.active_strategies,
        "total": len(engine.current_signals),
    }


class StrategiesRequest(BaseModel):
    strategies: list[str]


@router.post("/signals/strategies")
async def set_active_strategies(req: StrategiesRequest, request: Request):
    """设置活跃策略"""
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


@router.post("/signals/{code}/execute")
async def execute_signal(code: str, request: Request):
    """执行信号：创建对应的交易订单"""
    engine = getattr(request.app.state, "signal_engine", None)
    if not engine:
        raise HTTPException(status_code=500, detail="Signal engine not available")

    trade_engine = getattr(request.app.state, "trade_engine", None)
    if not trade_engine:
        raise HTTPException(status_code=500, detail="Trade engine not available")

    signals = [s for s in engine.current_signals if s["code"] == code]
    if not signals:
        raise HTTPException(status_code=404, detail=f"No signal for {code}")

    results = []
    for sig in signals:
        from app.models.trade import OrderSide as Side

        side = Side.BUY if sig["action"] == "buy" else Side.SELL
        volume = 10

        order = trade_engine.buy(
            code=sig["code"],
            name=sig["name"],
            price=sig["price"],
            volume=volume,
        )
        engine.mark_executed(sig["code"], sig["strategy"])
        results.append(order.model_dump())

    return {"executed": len(results), "orders": results}
