import asyncio
import pandas as pd
from datetime import date
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, field_validator

from app.strategies import get_strategy, list_strategies
from app.engine.backtest import BacktestEngine
from app.models.backtest import BacktestConfig, OptimizationConfig


router = APIRouter()


@router.get("/strategies")
async def get_strategies():
    return {"strategies": list_strategies()}


class BacktestRequest(BaseModel):
    strategy: str
    params: dict = {}
    start_date: str = "2024-01-01"
    end_date: str = "2025-12-31"
    config: BacktestConfig = BacktestConfig()
    optimization: OptimizationConfig = OptimizationConfig()

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f'Invalid date format: {v}, expected YYYY-MM-DD')
        return v


async def _build_data(request: Request, start_date: date, end_date: date) -> pd.DataFrame:
    """Build backtest data: try DuckDB cache first, fall back to simulated data"""
    storage = getattr(request.app.state, "storage", None)
    if storage:
        from app.engine.historical import HistoricalDataLoader
        loader = HistoricalDataLoader(storage)
        cached = loader.get_cached_history(start_date, end_date)
        if not cached.empty and len(cached) > 100:
            # Use cached data, add premium_ratio estimate from current snapshot
            current_bonds = await request.app.state.engine.get_all_quotes()
            premium_map = {b.code: b.premium_ratio for b in current_bonds}
            cached["premium_ratio"] = cached["code"].map(lambda c: premium_map.get(c, 0.0))
            import numpy as np
            cached["premium_ratio"] = cached["premium_ratio"] + np.random.randn(len(cached)) * 0.5
            return cached

    # Fallback: simulated data from current snapshot
    market_engine = request.app.state.engine
    bonds = await market_engine.get_all_quotes()
    if not bonds:
        await market_engine.refresh()
        bonds = await market_engine.get_all_quotes()

    raw_data = []
    for bond in bonds:
        raw_data.append({
            'code': bond.code, 'name': bond.name,
            'date': date.today(), 'price': bond.price,
            'premium_ratio': bond.premium_ratio, 'volume': bond.volume,
        })

    df = pd.DataFrame(raw_data)
    dfs = []
    import numpy as np
    for i, d in enumerate(pd.date_range(pd.Timestamp(start_date), pd.Timestamp(end_date), freq='D')):
        day = df.copy()
        day['date'] = d.date()
        day['price'] = day['price'] * (1 + np.random.randn(len(day)) * 0.005)
        day['premium_ratio'] = day['premium_ratio'] + np.random.randn(len(day)) * 0.5
        day['price'] = day['price'].clip(lower=80)
        dfs.append(day)

    return pd.concat(dfs, ignore_index=True)


@router.post("/run")
async def run_backtest(req: BacktestRequest, request: Request):
    try:
        start = date.fromisoformat(req.start_date)
        end = date.fromisoformat(req.end_date)
        full_data = await _build_data(request, start, end)

        strategy_cls = get_strategy(req.strategy)

        data_source = getattr(full_data, '_backtest_data_source', 'unknown')
        if req.optimization.enabled and req.optimization.param_ranges:
            engine = BacktestEngine(config=req.config)
            opt_result = engine.run_optimization(strategy_cls, full_data, req.optimization)
            return {
                "success": True,
                "type": "optimization",
                "data_source": data_source,
                "result": opt_result.model_dump(mode="json"),
            }
        else:
            strategy = strategy_cls(**req.params)
            engine = BacktestEngine(config=req.config)
            result = engine.run(strategy, full_data)
            return {"success": True, "type": "backtest", "data_source": data_source, "result": result.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/optimize")
async def optimize_params(req: BacktestRequest, request: Request):
    """参数优化专用端点"""
    try:
        start = date.fromisoformat(req.start_date)
        end = date.fromisoformat(req.end_date)
        full_data = await _build_data(request, start, end)

        strategy_cls = get_strategy(req.strategy)
        engine = BacktestEngine(config=req.config)

        opt_config = req.optimization
        if not opt_config.param_ranges:
            from app.models.backtest import OptimizationParamRange
            param_defs = strategy_cls.params
            opt_config.param_ranges = [
                OptimizationParamRange(
                    name=p.name,
                    min_val=float(p.min_val or p.default * 0.5),
                    max_val=float(p.max_val or p.default * 1.5),
                    step=float((p.max_val - p.min_val) / 5) if p.max_val is not None and p.min_val is not None else 1.0,
                )
                for p in param_defs
                if p.type in ("int", "float")
            ]

        result = engine.run_optimization(strategy_cls, full_data, opt_config)
        data_source = getattr(full_data, '_backtest_data_source', 'unknown')
        return {"success": True, "data_source": data_source, "result": result.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))