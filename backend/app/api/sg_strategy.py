"""松岗量化可转债策略 V3.0 API接口"""
from fastapi import APIRouter, Request, HTTPException
from typing import Optional
from datetime import date
import logging

from app.sg_strategy.core.strategy import SGConvertibleStrategy
from app.sg_strategy.core.types import ConvertibleBondData, StockData
from app.sg_strategy.config.weights import MarketRegime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sg-strategy", tags=["松岗量化策略V3.0"])


# 全局策略实例
_strategy: Optional[SGConvertibleStrategy] = None


def get_strategy(aum: float = 10000.0) -> SGConvertibleStrategy:
    """获取策略实例"""
    global _strategy
    if _strategy is None:
        _strategy = SGConvertibleStrategy(aum)
    return _strategy


@router.get("/status")
async def get_status():
    """获取策略状态"""
    strategy = get_strategy()
    return {
        "status": "running",
        "aum": strategy.aum,
        "regime": strategy.regime.value,
        "whitelist_size": len(strategy.whitelist),
        "position_count": len(strategy.portfolio.positions),
    }


@router.get("/whitelist")
async def get_whitelist():
    """获取当前白名单"""
    strategy = get_strategy()
    return {
        "whitelist": strategy.whitelist,
        "buffer_zone": strategy.buffer_zone,
        "total": len(strategy.whitelist),
    }


@router.get("/scores")
async def get_scores(top: int = 20):
    """获取七维得分排名"""
    strategy = get_strategy()
    top_scores = strategy.scores[:top]
    return {
        "scores": [s.to_dict() for s in top_scores],
        "total": len(strategy.scores),
    }


@router.get("/positions")
async def get_positions():
    """获取当前持仓"""
    strategy = get_strategy()
    positions = [
        pos.to_dict() for pos in strategy.portfolio.positions.values()
    ]
    return {
        "positions": positions,
        "total_count": len(positions),
        "total_value": strategy.portfolio.total_market_value,
    }


@router.get("/timing")
async def get_timing():
    """获取择时信号"""
    strategy = get_strategy()
    if strategy.timing_signal:
        return strategy.timing_signal.to_dict()
    return {"message": "暂无择时信号"}


@router.get("/performance")
async def get_performance():
    """获取绩效汇总"""
    strategy = get_strategy()
    return strategy.get_performance_summary()


@router.post("/run-daily")
async def run_daily(request: Request):
    """运行每日策略"""
    try:
        data = await request.json()
        # 这里需要实际数据
        # strategy = get_strategy(data.get("aum", 10000))
        # report = strategy.run_daily(...)
        return {"message": "策略运行成功", "date": date.today().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-aum")
async def update_aum(request: Request):
    """更新资产规模"""
    try:
        data = await request.json()
        new_aum = data.get("aum", 10000)
        strategy = get_strategy()
        strategy.update_aum(new_aum)
        return {"message": f"AUM已更新为{new_aum}万"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events")
async def get_event_opportunities():
    """获取事件驱动机会"""
    strategy = get_strategy()
    opportunities = strategy.event_engine._opportunities
    return {
        "opportunities": [o.to_dict() for o in opportunities],
        "total": len(opportunities),
    }


@router.get("/hedge-status")
async def get_hedge_status():
    """获取对冲状态"""
    strategy = get_strategy()
    return strategy.hedge_engine.get_hedge_report()


@router.get("/monitor")
async def get_monitor_metrics():
    """获取监控指标"""
    strategy = get_strategy()
    summary = strategy.daily_monitor.get_summary()
    return summary


@router.get("/cost-report")
async def get_cost_report():
    """获取成本报告"""
    strategy = get_strategy()
    return strategy.execution_engine.cost_model.get_cost_report()


# ============ 详细接口 ============

@router.get("/credit-scores")
async def get_credit_scores(top: int = 20):
    """获取信用评分"""
    strategy = get_strategy()
    scores = [
        {"code": code, **score.to_dict()}
        for code, score in list(strategy.credit_scores.items())[:top]
    ]
    return {"scores": scores, "total": len(strategy.credit_scores)}


@router.get("/factor-analysis")
async def get_factor_analysis():
    """获取因子分析"""
    strategy = get_strategy()
    factors = strategy.factor_analyzer.get_factor_analysis()
    return {
        "factors": [f.to_dict() for f in factors],
        "validity": strategy.factor_analyzer.check_factor_validity(),
    }
