import asyncio
import pandas as pd
from datetime import date
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

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


@router.post("/run")
async def run_backtest(req: BacktestRequest, request: Request):
    # Get market engine for data
    market_engine = request.app.state.engine

    # Get all bonds data from market engine
    bonds = await market_engine.get_all_quotes()
    if not bonds:
        await market_engine.refresh()
        bonds = await market_engine.get_all_quotes()

    # Build mock historical data from current snapshot + random noise
    # (In production, load from DuckDB historical data)
    raw_data = []
    for bond in bonds:
        raw_data.append({
            'code': bond.code,
            'name': bond.name,
            'date': date.today(),
            'price': bond.price,
            'premium_ratio': bond.premium_ratio,
            'volume': bond.volume,
        })

    df = pd.DataFrame(raw_data)

    # Expand to multiple dates with price variation
    dfs = []
    start = pd.to_datetime(req.start_date)
    end = pd.to_datetime(req.end_date)

    import numpy as np
    for i, d in enumerate(pd.date_range(start, end, freq='D')):
        day = df.copy()
        day['date'] = d.date()
        day['price'] = day['price'] * (1 + np.random.randn(len(day)) * 0.005)
        day['premium_ratio'] = day['premium_ratio'] + np.random.randn(len(day)) * 0.5
        day['price'] = day['price'].clip(lower=80)
        dfs.append(day)

    full_data = pd.concat(dfs, ignore_index=True)

    try:
        strategy_cls = get_strategy(req.strategy)

        # 判断是否启用参数优化
        if req.optimization.enabled and req.optimization.param_ranges:
            engine = BacktestEngine(config=req.config)
            opt_result = engine.run_optimization(strategy_cls, full_data, req.optimization)
            return {
                "success": True,
                "type": "optimization",
                "result": opt_result.model_dump(mode="json"),
            }
        else:
            strategy = strategy_cls(**req.params)
            engine = BacktestEngine(config=req.config)
            result = engine.run(strategy, full_data)
            return {"success": True, "type": "backtest", "result": result.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/optimize")
async def optimize_params(req: BacktestRequest, request: Request):
    """参数优化专用端点"""
    market_engine = request.app.state.engine

    bonds = await market_engine.get_all_quotes()
    if not bonds:
        await market_engine.refresh()
        bonds = await market_engine.get_all_quotes()

    raw_data = []
    for bond in bonds:
        raw_data.append({
            'code': bond.code,
            'name': bond.name,
            'date': date.today(),
            'price': bond.price,
            'premium_ratio': bond.premium_ratio,
            'volume': bond.volume,
        })

    df = pd.DataFrame(raw_data)

    dfs = []
    start = pd.to_datetime(req.start_date)
    end = pd.to_datetime(req.end_date)

    import numpy as np
    for i, d in enumerate(pd.date_range(start, end, freq='D')):
        day = df.copy()
        day['date'] = d.date()
        day['price'] = day['price'] * (1 + np.random.randn(len(day)) * 0.005)
        day['premium_ratio'] = day['premium_ratio'] + np.random.randn(len(day)) * 0.5
        day['price'] = day['price'].clip(lower=80)
        dfs.append(day)

    full_data = pd.concat(dfs, ignore_index=True)

    try:
        strategy_cls = get_strategy(req.strategy)
        engine = BacktestEngine(config=req.config)

        # 如果未设置优化范围，使用策略参数默认范围
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
        return {"success": True, "result": result.model_dump(mode="json")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

