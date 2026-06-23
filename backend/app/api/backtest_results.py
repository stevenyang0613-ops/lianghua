"""三大策略回测结果 API — 璇玑十二因子 / 西部七维 / 融合策略

从 2020-01-01 至今的完整回测结果，用于左侧栏「三大策略回测情况」展示。
"""
import asyncio
import json
import logging
import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.strategies import get_strategy, STRATEGY_REGISTRY
from app.engine.backtest import BacktestEngine
from app.models.backtest import BacktestConfig

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 缓存目录（持久化回测结果避免每次重算） ──
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".lianghua", "backtest_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)


_STRATEGY_KEYS = ["xuanji_twelve", "xibu_seven", "fusion"]
_STRATEGY_NAMES = {
    "xuanji_twelve": "璇玑十二因子",
    "xibu_seven": "西部七维",
    "fusion": "融合策略",
}


def _week_start(d: date) -> date:
    """将日期对齐到 ISO 周起始（周一），使用 isocalendar 确保跨周一致性。

    原 weekday() 方案（周一=0）对同一自然周的不同日期会产生相同 key，
    但跨周时边界不一致；isocalendar 的 year-week 始终从周一开始，更稳定。
    """
    y, w, _ = d.isocalendar()
    return date.fromisocalendar(y, w, 1)


def _cache_path(strategy_key: str, start_date: date, end_date: date) -> str:
    """生成缓存文件路径（周对齐，避免每天生成新缓存）"""
    start_week = _week_start(start_date)
    end_week = _week_start(end_date)
    return os.path.join(_CACHE_DIR, f"{strategy_key}_{start_week.isoformat()}_{end_week.isoformat()}.json")


def _load_cache(strategy_key: str, start_date: date, end_date: date) -> Optional[dict]:
    """从缓存加载回测结果"""
    path = _cache_path(strategy_key, start_date, end_date)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[BacktestCache] Failed to load cache for {strategy_key}: {e}")
        return None


def _save_cache(strategy_key: str, start_date: date, end_date: date, data: dict) -> None:
    """保存回测结果到缓存"""
    path = _cache_path(strategy_key, start_date, end_date)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"[BacktestCache] Failed to save cache for {strategy_key}: {e}")


@router.get("/strategy-results")
async def get_strategy_backtest_results(
    request: Request,
    start_date: str = "2020-01-01",
    end_date: str = None,
    force_refresh: bool = False,
):
    """获取三大策略回测结果（2020-01-01 至今）

    Args:
        start_date: 回测开始日期 (YYYY-MM-DD), 默认 2020-01-01
        end_date: 回测结束日期 (YYYY-MM-DD), 默认今天
        force_refresh: 是否强制重新计算（忽略缓存）

    Returns:
        {
            "xuanji_twelve": { ...backtest result... },
            "xibu_seven": { ...backtest result... },
            "fusion": { ...backtest result... },
        }
    """
    try:
        start = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid start_date: {start_date}")

    if end_date:
        try:
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid end_date: {end_date}")
    else:
        end = date.today()

    results = {}

    for key in _STRATEGY_KEYS:
        # 尝试读取缓存
        if not force_refresh:
            cached = _load_cache(key, start, end)
            if cached:
                results[key] = cached
                continue

        # 运行回测
        try:
            result = await _run_single_backtest(request, key, start, end)
            results[key] = result
            _save_cache(key, start, end, result)
        except Exception as e:
            logger.error(f"[StrategyBacktest] {key} failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results[key] = {
                "strategy_id": key,
                "strategy_name": _STRATEGY_NAMES[key],
                "error": str(e),
            }

    return JSONResponse(content={"results": results, "date_range": {"start": start.isoformat(), "end": end.isoformat()}})


async def _run_single_backtest(request: Request, strategy_key: str, start: date, end: date) -> dict:
    """运行单个策略回测"""
    from app.api.backtest import _build_data

    logger.info(f"[StrategyBacktest] Running {strategy_key} from {start} to {end}")

    # 构建数据
    full_data = await _build_data(request, start, end, strategy_name=strategy_key)
    data_source = getattr(full_data, "_backtest_data_source", "unknown")
    data_warning = getattr(full_data, "_backtest_data_warning", None)
    total_rows = len(full_data)
    n_dates = full_data["date"].nunique() if "date" in full_data.columns and not full_data.empty else 0

    logger.info(f"[StrategyBacktest] {strategy_key}: data_source={data_source}, rows={total_rows}, dates={n_dates}")

    # 获取策略类
    strategy_cls = get_strategy(strategy_key)

    # 使用最优参数
    from app.engine.paper_trade_manager import PaperTradeManager
    optimal_params = PaperTradeManager.get_optimal_params(strategy_key)

    # 创建策略实例
    strategy = strategy_cls(**optimal_params)

    # 回测配置
    config = BacktestConfig(
        initial_cash=100_000_000.0,  # 1亿初始资金
        commission_pct=0.0001,
        slippage_pct=0.001,
    )

    # 运行回测
    engine = BacktestEngine(config=config)
    result = await asyncio.to_thread(engine.run, strategy, full_data)

    # 转换为字典
    raw_dict = result.model_dump(mode="json") if hasattr(result, "model_dump") else result.to_dict()

    # 提取指标
    metrics = raw_dict.get("metrics", {}) or {}
    bm_metrics = raw_dict.get("benchmark_metrics", {}) or {}
    ex_metrics = raw_dict.get("excess_metrics", {}) or {}

    # 转换交易记录格式（买/卖分开）
    transformed_trades = []
    for t in raw_dict.get("trades", []) or []:
        # 买入记录
        transformed_trades.append({
            "date": t.get("buy_date", ""),
            "code": t.get("code", ""),
            "action": "buy",
            "price": t.get("buy_price", 0),
            "quantity": t.get("volume", 0),
            "cost": 0,  # 买入成本在Portfolio中已体现在buy_price，此处不重复计算
        })
        # 卖出记录（如有）
        if t.get("sell_date") and t.get("sell_price") is not None:
            transformed_trades.append({
                "date": t.get("sell_date", ""),
                "code": t.get("code", ""),
                "action": "sell",
                "price": t.get("sell_price", 0),
                "quantity": t.get("volume", 0),
                "cost": 0,
            })
    # 按日期排序
    transformed_trades.sort(key=lambda x: x["date"])

    # 转换净值曲线
    equity_curve = raw_dict.get("equity_curve", []) or []
    daily_values = [
        {
            "date": pt.get("date", ""),
            "value": pt.get("value", 0),
            "cash": 0,  # 回测引擎不记录每日现金，置0
            "positions": 0,  # 回测引擎不记录每日持仓数，置0
        }
        for pt in equity_curve
    ]

    # 计算换手率（简化：总交易金额 / 平均资产市值）
    total_trade_value = sum(
        (t.get("buy_price", 0) + (t.get("sell_price") or 0)) * t.get("volume", 0)
        for t in raw_dict.get("trades", []) or []
    )
    avg_equity = sum(pt.get("value", 0) for pt in equity_curve) / max(len(equity_curve), 1)
    turnover_rate = round(total_trade_value / max(avg_equity, 1) * 100, 2) if avg_equity > 0 else 0.0

    result_dict = {
        "returns": metrics.get("total_return_pct", 0),
        "benchmark_returns": bm_metrics.get("total_return_pct", 0),
        "excess_returns": ex_metrics.get("total_return_pct", 0),
        "max_drawdown": metrics.get("max_drawdown_pct", 0),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0),
        "win_rate": metrics.get("win_rate", 0),
        "trade_count": metrics.get("total_trades", 0),
        "total_cost": raw_dict.get("total_cost", 0),
        "turnover_rate": turnover_rate,
        "daily_values": daily_values,
        "trades": transformed_trades,
        # 保留原始详细数据供前端高级展示
        "_raw": raw_dict,
    }

    return {
        "strategy_id": strategy_key,
        "strategy_name": _STRATEGY_NAMES[strategy_key],
        "optimal_params": optimal_params,
        "data_source": data_source,
        "data_warning": data_warning,
        "total_rows": total_rows,
        "n_dates": n_dates,
        "result": result_dict,
    }


# 改进 (2026-06-23): 回测状态/预估接口，供前端首次加载时展示 Skeleton + 进度提示
@router.get("/status")
async def get_backtest_status(
    start_date: str = "2020-01-01",
    end_date: str = None,
):
    """查询三大策略回测缓存状态，用于前端首次加载时的进度/Skeleton 展示。

    Returns:
        {
            "cached": {"xuanji_twelve": true, ...},
            "estimated_seconds": 600,  // 无缓存时的预估耗时（秒）
            "all_ready": false,
            "date_range": {"start": "2020-01-01", "end": "2024-06-23"}
        }
    """
    try:
        start = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid start_date: {start_date}")
    if end_date:
        try:
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid end_date: {end_date}")
    else:
        end = date.today()

    cached = {}
    for key in _STRATEGY_KEYS:
        cached[key] = _load_cache(key, start, end) is not None

    all_ready = all(cached.values())
    # 预估耗时：单策略约 3-5 分钟（数据构建 + 回测），三策略串行约 8-12 分钟
    estimated_seconds = 0 if all_ready else (8 * 60)

    return JSONResponse(content={
        "cached": cached,
        "estimated_seconds": estimated_seconds,
        "all_ready": all_ready,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
    })
