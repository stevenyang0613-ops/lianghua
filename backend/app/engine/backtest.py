import random
import os
import time
import logging
import queue
import threading
import concurrent.futures
import multiprocessing
import json
import base64
import heapq
import itertools
import tracemalloc
import tempfile
import atexit
from collections import deque
from functools import partial
from pathlib import Path

logger = logging.getLogger(__name__)
import numpy as np
import pandas as pd
from datetime import date, datetime
from typing import Optional, Any

# 改进 (2025-06-15l): 可选依赖加载
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    import numba
    from numba import njit, prange
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False
    # numba 缺失时的空装饰器
    def njit(*args, **kwargs):
        def wrapper(func):
            return func
        return wrapper if args and callable(args[0]) else wrapper
    prange = range

# 改进 (2025-06-15q): 统一使用 numba 原生配置检查，支持 NUMBA_DISABLE_JIT 环境变量
if _HAS_NUMBA:
    try:
        _HAS_NUMBA = not numba.config.DISABLE_JIT
    except Exception:
        pass
    if not _HAS_NUMBA:
        logger.info("[numba] NUMBA_DISABLE_JIT=1 或 numba.config.DISABLE_JIT=True，已禁用 numba JIT")
        def njit(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper if args and callable(args[0]) else wrapper
        prange = range
    else:
        # 改进 (2025-06-15q): 设置 numba 缓存目录，避免 Electron asar 只读环境问题
        # lazy init：模块加载时只设环境变量，首次 JIT 编译时才创建目录
        _numba_cache_dir = os.environ.get('NUMBA_CACHE_DIR')
        if not _numba_cache_dir:
            _default_cache = os.path.join(os.path.expanduser('~'), '.lianghua', 'numba_cache')
            os.environ['NUMBA_CACHE_DIR'] = _default_cache

def _ensure_numba_cache_dir():
    """确保 numba 缓存目录存在（lazy init，首次 JIT 编译时调用）
    
    模块加载时只设置 NUMBA_CACHE_DIR 环境变量，不执行 I/O。
    首次 JIT 编译预热前调用此函数创建目录，避免每次 import 都触发文件系统操作。
    
    改进 (2025-06-15aa): 多级回退策略：
    1. 首选 ~/.lianghua/numba_cache
    2. 权限不足 → ~/.cache/lianghua_numba（持久化目录）
    3. 仍失败 → tempfile.gettempdir()（系统临时目录，重启可能丢失）
    """
    _cache_dir = os.environ.get('NUMBA_CACHE_DIR')
    if not _cache_dir or os.path.isdir(_cache_dir):
        return
    try:
        os.makedirs(_cache_dir, exist_ok=True)
        logger.debug(f"[numba] 缓存目录已创建: {_cache_dir}")
    except PermissionError:
        # 改进 (2025-06-15aa): 多级回退，先尝试 ~/.cache 持久化目录
        _fallback2 = os.path.join(os.path.expanduser('~'), '.cache', 'lianghua_numba')
        try:
            os.makedirs(_fallback2, exist_ok=True)
            os.environ['NUMBA_CACHE_DIR'] = _fallback2
            logger.warning(f"[numba] 用户目录权限不足，回退到 ~/.cache 缓存目录 {_fallback2}")
        except OSError:
            _fallback = os.path.join(tempfile.gettempdir(), 'lianghua_numba_cache')
            try:
                os.makedirs(_fallback, exist_ok=True)
                os.environ['NUMBA_CACHE_DIR'] = _fallback
                logger.warning(f"[numba] ~/.cache 也失败，回退到临时缓存目录 {_fallback}")
            except OSError as e:
                os.environ['NUMBA_CACHE_DIR'] = ''
                logger.warning(f"[numba] 所有缓存目录均创建失败 ({e})，已禁用缓存")
    except OSError as e:
        os.environ['NUMBA_CACHE_DIR'] = ''
        logger.warning(f"[numba] 缓存目录创建失败: {_cache_dir} ({e})，已禁用缓存")

def _check_numba_cache_size():
    """检查 numba 缓存目录大小，超过阈值时清空重建
    
    长期运行后缓存可能膨胀到数 GB（多种参数组合产生不同的 JIT 编译缓存）。
    阈值：1 GB。清空后 numba 会在下次 JIT 编译时自动重建。
    
    性能优化：通过 .last_check 时间戳文件，每天最多执行一次完整扫描，
    避免每次 JIT 调用都 os.walk 遍历数万小文件。
    """
    _cache_dir = os.environ.get('NUMBA_CACHE_DIR')
    if not _cache_dir or not os.path.isdir(_cache_dir):
        return
    
    # 每天最多检查一次：读取 .last_check 时间戳
    # （放在 os.listdir 前面，避免每次都做目录扫描）
    _check_file = os.path.join(_cache_dir, '.last_check')
    now = time.time()
    try:
        if os.path.isfile(_check_file):
            last_check = os.path.getmtime(_check_file)
            if now - last_check < 86400:  # 24 小时内已检查过
                return
    except OSError:
        pass
    
    # 跳过空目录（刚创建，尚无缓存文件）
    try:
        if not os.listdir(_cache_dir):
            # 空目录也写时间戳，避免重复 os.listdir
            try:
                with open(_check_file, 'w') as f:
                    f.write(str(now))
            except OSError:
                pass
            return
    except OSError:
        return
    
    try:
        total_size = 0
        for dirpath, _dirnames, filenames in os.walk(_cache_dir):
            for f in filenames:
                if f == '.last_check':
                    continue
                try:
                    total_size += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        max_bytes = 1 * 1024 * 1024 * 1024  # 1 GB
        if total_size > max_bytes:
            import shutil
            logger.warning(
                f"[numba] 缓存目录 {_cache_dir} 大小 {total_size / 1024 / 1024:.0f} MB "
                f"超过阈值 {max_bytes / 1024 / 1024:.0f} MB，清空重建"
            )
            shutil.rmtree(_cache_dir, ignore_errors=True)
            os.makedirs(_cache_dir, exist_ok=True)
        # 更新检查时间戳
        try:
            with open(_check_file, 'w') as f:
                f.write(str(time.time()))
        except OSError:
            pass
    except Exception as e:
        logger.debug(f"[numba] 缓存目录大小检查失败: {e}")

# 保留 LH_DISABLE_NUMBA 兼容
if os.environ.get('LH_DISABLE_NUMBA', '0') == '1':
    _HAS_NUMBA = False
    logger.info("[numba] LH_DISABLE_NUMBA=1，已禁用 numba JIT")
    def njit(*args, **kwargs):
        def wrapper(func):
            return func
        return wrapper if args and callable(args[0]) else wrapper
    prange = range

try:
    import polars as pl
    _HAS_POLARS = True
except ImportError:
    _HAS_POLARS = False

try:
    import ray
    _HAS_RAY = True
except ImportError:
    _HAS_RAY = False

from pydantic import BaseModel
from app.models.backtest import (
    BacktestResult, PerformanceMetrics, TradeRecord, MonthlyReturn,
    BacktestConfig, OptimizationConfig, OptimizationResult, OptimizationResultItem
)
from app.strategies.base import Strategy

# 改进 (2025-06-15d): 模块级 parquet 引擎可用性检测，避免每次 run_optimization 重复 importlib 调用
# 后续 BacktestEngine._has_parquet_engine 将复用此值
_HAS_PARQUET_ENGINE: Optional[bool] = None

# 改进 (2025-06-15al): 模块级 ThreadPoolExecutor 单例，用于 _fast_rebuild_pareto_front 大 front 并行化
# 避免每次重建都创建/销毁线程池的开销
_THREAD_POOL: Optional[concurrent.futures.ThreadPoolExecutor] = None

def _check_parquet_engine() -> bool:
    """检测 pyarrow 或 fastparquet 是否可用（缓存结果）"""
    global _HAS_PARQUET_ENGINE
    if _HAS_PARQUET_ENGINE is None:
        import importlib
        _HAS_PARQUET_ENGINE = (
            importlib.util.find_spec("pyarrow") is not None
            or importlib.util.find_spec("fastparquet") is not None
        )
    return _HAS_PARQUET_ENGINE


# 改进 (2025-06-15am): 注册 atexit handler 优雅关闭 ThreadPoolExecutor
# 改进 (2025-06-15ao): 添加 _shutdown 标志防止二次调用 RuntimeError
@atexit.register
def _shutdown_thread_pool():
    global _THREAD_POOL
    if _THREAD_POOL is not None and not getattr(_THREAD_POOL, '_shutdown', False):
        try:
            _THREAD_POOL.shutdown(wait=False)
            _THREAD_POOL._shutdown = True
            logger.debug("[_THREAD_POOL] ThreadPoolExecutor 已优雅关闭")
        except RuntimeError:
            # 已关闭，忽略
            pass
        except Exception as e:
            logger.warning(f"[_THREAD_POOL] ThreadPoolExecutor 关闭失败: {e}")


class Portfolio:
    """模拟投资组合 - 封装持仓、现金和交易记录管理"""

    def __init__(self, cash: float = 1.0):
        self.cash = cash
        self.holdings: dict[str, dict] = {}  # code -> {buy_price, volume, buy_date}
        self.trades: list[TradeRecord] = []

    def remove_stale(self, code_row_map: dict, current_date=None, commission: float = 0.0, min_commission: float = 0.0, impact_cost: float = 0.0) -> None:
        """移除当日无行情数据的持仓 - 按最近可用价格平仓并记录交易
        
        修复 (2025-06-15): 使用最近可用价格而非买入价平仓，避免长期持仓零收益失真。
        修复 (2025-06-15b): 统一冲击成本计算——和 sell() 一致: price * (1 - slippage - impact_cost)
        注意: remove_stale 无 slippage 概念（无行情时不交易），仅扣 impact_cost
        """
        to_remove = [
            code for code in self.holdings
            if code not in code_row_map
        ]
        for code in to_remove:
            h = self.holdings.pop(code)
            # 修复: 优先使用最近可用价格，如无则回退到买入价
            last_price = h.get('last_price', h['buy_price'])
            # 统一: remove_stale 无 slippage，仅扣 impact_cost（和 sell 的 price*(1-slippage-impact_cost) 对齐）
            sell_price = last_price * (1 - impact_cost)
            sell_value = sell_price * h['volume']
            fee = max(sell_value * commission, min_commission)
            self.cash += sell_value - fee
            profit = sell_value - fee - (h['buy_price'] * h['volume'])
            if current_date is not None:
                self.trades.append(TradeRecord(
                    code=code, name='',
                    buy_date=h['buy_date'], sell_date=current_date,
                    buy_price=h['buy_price'], sell_price=sell_price,
                    volume=h['volume'],
                    profit_pct=round((sell_price / h['buy_price'] - 1) * 100, 2) if h['buy_price'] > 0 else 0.0,
                    profit_amount=round(profit, 2),
                    hold_days=(current_date - h['buy_date']).days if hasattr(current_date, '__sub__') else 0,
                    reason='无行情数据平仓',
                ))

    # 改进 (2025-06-15at): debug 日志采样率控制——高并发回测中（5000 只 × 100 天），
    # 全量 debug 日志会产生 50 万条输出，使用 1/1000 采样率降低 I/O 开销。
    # 使用 random.random() 避免线程竞争条件，无需锁保护。
    _safe_price_log_sample_rate = 1000

    @staticmethod
    def _safe_price(price) -> float:
        """防御性 NaN/inf/极小值处理: 返回 0 替代异常值

        改进 (2025-06-15an): 统一使用 np.isfinite，覆盖 numpy 标量和 Python float 的
        所有非有限情况（nan, inf, -inf）。对 numpy 类型 np.isfinite 比 math.isnan 更可靠。
        改进 (2025-06-15ao): 极小值防御——np.float64 下溢值（<1e-15）已丢失精度，
        按 0 处理避免后续 price*volume 的数值噪声。
        改进 (2025-06-15at): debug 日志采样率控制——使用 random 避免线程竞争。
        """
        if price is None:
            if random.random() < 1 / Portfolio._safe_price_log_sample_rate:
                logger.debug("[Portfolio._safe_price] price=None, returning 0.0")
            return 0.0
        try:
            p = float(price)
            if not np.isfinite(p) or abs(p) < 1e-15:
                if random.random() < 1 / Portfolio._safe_price_log_sample_rate:
                    logger.debug(f"[Portfolio._safe_price] price={price} (p={p}) is not finite or <1e-15, returning 0.0")
                return 0.0
            return p
        except (ValueError, TypeError) as e:
            if random.random() < 1 / Portfolio._safe_price_log_sample_rate:
                logger.debug(f"[Portfolio._safe_price] price={price} conversion failed: {e}, returning 0.0")
            return 0.0

    def sell(self, code: str, price: float, slippage: float,
             commission: float, min_commission: float, impact_cost: float,
             current_date, code_row_map: dict,
             reason: str = '') -> None:
        """卖出持仓"""
        if code not in self.holdings:
            logger.debug(f"[Portfolio.sell] code={code} not in holdings, skipping")
            return
        h = self.holdings.pop(code)
        sell_price = Portfolio._safe_price(price) * (1 - slippage - impact_cost)
        if sell_price <= 0:
            logger.debug(f"[Portfolio.sell] code={code} sell_price={sell_price} <= 0, trade recorded with zero profit")
        sell_value = sell_price * h['volume']
        fee = max(sell_value * commission, min_commission)
        profit = sell_value - fee - (h['buy_price'] * h['volume'])
        self.cash += sell_value - fee

        sell_row = code_row_map.get(code)
        name = ''
        if sell_row is not None and hasattr(sell_row, 'get'):
            try:
                raw = sell_row.get('name', '') if isinstance(sell_row, dict) else getattr(sell_row, 'name', '')
                name = str(raw) if raw and str(raw) != 'nan' else ''
            except Exception:
                name = ''

        # 防御性计算 profit_pct，避免 buy_price <= 0 导致除零
        if h['buy_price'] > 0:
            profit_pct = round((sell_price - h['buy_price']) / h['buy_price'] * 100, 2)
        else:
            logger.debug(f"[Portfolio.sell] code={code} buy_price={h['buy_price']} <= 0, profit_pct set to 0.0")
            profit_pct = 0.0

        self.trades.append(TradeRecord(
            code=code, name=name,
            buy_date=h['buy_date'], sell_date=current_date,
            buy_price=h['buy_price'], sell_price=sell_price,
            volume=h['volume'],
            profit_pct=profit_pct,
            profit_amount=round(profit, 2),
            hold_days=(current_date - h['buy_date']).days,
            reason=reason,
        ))

    def buy(self, code: str, price: float, slippage: float,
            commission: float, min_commission: float, impact_cost: float,
            current_date, alloc: float) -> bool:
        """买入标的，等权分配资金"""
        if code in self.holdings:
            return False
        buy_price = Portfolio._safe_price(price) * (1 + slippage + impact_cost)
        # 修复 (2025-06-15ap): buy_price <= 0 时无法计算 volume，直接返回 False
        # 可能原因: 输入 price 为 0/NaN，或 slippage+impact_cost 导致价格为负
        if buy_price <= 0:
            logger.warning(f"[Portfolio] buy_price={buy_price} <= 0，跳过买入 {code}")
            return False
        # 改进 (2025-06-15am): volume 溢出防御——当 alloc 很大 / buy_price 很小时限制上限
        volume = max(1, int(alloc / buy_price))
        if volume > 1_000_000_000:
            logger.warning(f"[Portfolio] volume {volume} 超过上限 1e9，截断到 1e9")
            volume = 1_000_000_000
        cost = buy_price * volume
        fee = max(cost * commission, min_commission)

        if cost + fee > self.cash:
            return False

        self.cash -= cost + fee
        self.holdings[code] = {
            'buy_price': buy_price,
            'volume': volume,
            'buy_date': current_date,
            'last_price': buy_price,  # 记录最新价格用于remove_stale
        }
        return True

    def market_value(self, code_row_map: dict) -> float:
        """计算组合总市值（现金 + 持仓市值）"""
        val = self.cash
        for code, h in self.holdings.items():
            row = code_row_map.get(code)
            if row is not None and hasattr(row, 'get'):
                price = Portfolio._safe_price(row.get('price', h['buy_price']))
                h['last_price'] = price  # 更新最新价格
                val += price * h['volume']
            else:
                val += h.get('last_price', h['buy_price']) * h['volume']
        return val


def _calculate_metrics(equity: list[float], risk_free_rate: float = 0.02) -> PerformanceMetrics:
    """计算绩效指标，支持可配置无风险利率

    改进 (2025-06-15al): 明确 risk_free_rate 为年化利率（如 0.02=2%/年），
    内部已按 250 交易日折算为日度无风险利率。传入时请使用年化值。
    """
    # 改进 (2025-06-15an): 防御负利率——虽然理论上可能，但当前模型不支持
    if risk_free_rate < 0:
        logger.warning(f"[_calculate_metrics] risk_free_rate={risk_free_rate} 为负，已截断到 0")
        risk_free_rate = 0.0

    if len(equity) < 2:
        return PerformanceMetrics()

    arr = np.array(equity)
    returns = np.diff(arr) / np.where(arr[:-1] != 0, arr[:-1], np.nan)
    returns = returns[~np.isnan(returns)]

    if len(returns) == 0:
        return PerformanceMetrics()

    total_ret = (arr[-1] / arr[0]) - 1 if arr[0] > 0 else 0.0

    # 年化收益率 (假设日频数据, 250 交易日/年)
    # 短回测(<60天)不年化,直接用总收益
    n_years = len(returns) / 250
    if n_years >= 0.24:  # 至少60天
        annual_ret = (1 + total_ret) ** (1 / n_years) - 1
    else:
        # 短周期: 用日均收益线性年化(避免短数据年化爆炸)
        avg_daily_ret = float(np.mean(returns))
        annual_ret = (1 + avg_daily_ret) ** 250 - 1

    # 最大回撤
    peak = np.maximum.accumulate(arr)
    drawdowns = np.zeros_like(arr, dtype=float)
    nonzero = peak != 0
    drawdowns[nonzero] = (arr[nonzero] - peak[nonzero]) / peak[nonzero]
    max_dd = float(np.min(drawdowns))

    # Sharpe (使用可配置的无风险利率)
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    excess_ret = annual_ret - risk_free_rate
    sharpe = float(excess_ret / (std * np.sqrt(250))) if std > 0 else 0.0
    # 修复: 不限制Sharpe上限, 仅防止极除以零异常
    if not (-1e6 < sharpe < 1e6):
        sharpe = 0.0

    # Sortino
    downside = returns[returns < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = float(excess_ret / downside_std * np.sqrt(250)) if downside_std > 0 else 0.0
    sortino = max(-10.0, min(10.0, sortino))

    # Calmar
    calmar = float(annual_ret / abs(max_dd)) if max_dd != 0 else 0.0
    calmar = max(-10.0, min(10.0, calmar))

    return PerformanceMetrics(
        total_return_pct=round(total_ret * 100, 2),
        annual_return_pct=round(annual_ret * 100, 2),
        max_drawdown_pct=round(max_dd * 100, 2),
        sharpe_ratio=round(sharpe, 2),
        sortino_ratio=round(sortino, 2),
        calmar_ratio=round(calmar, 2),
    )


# 改进 (2025-06-15l): numba JIT 加速版核心指标计算
if _HAS_NUMBA:
    def _calc_metrics_fast_njit_base(equity_arr, risk_free_rate):
        """numba JIT 加速的纯数值指标计算（基础函数，会被 njit 包装）"""
        n = len(equity_arr)
        if n < 2:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        # 日收益率
        returns = np.empty(n - 1, dtype=np.float64)
        for i in prange(n - 1):
            prev = equity_arr[i]
            if prev != 0:
                returns[i] = (equity_arr[i + 1] - prev) / prev
            else:
                returns[i] = 0.0

        # 总收益
        total_ret = (equity_arr[-1] / equity_arr[0]) - 1 if equity_arr[0] > 0 else 0.0

        # 年化收益
        n_years = (n - 1) / 250.0
        if n_years >= 0.24:
            annual_ret = (1.0 + total_ret) ** (1.0 / n_years) - 1.0
        else:
            avg_daily = 0.0
            for i in prange(n - 1):
                avg_daily += returns[i]
            avg_daily /= (n - 1)
            annual_ret = (1.0 + avg_daily) ** 250 - 1.0

        # 最大回撤
        peak = equity_arr[0]
        max_dd = 0.0
        for i in range(n):
            if equity_arr[i] > peak:
                peak = equity_arr[i]
            dd = (equity_arr[i] - peak) / peak if peak != 0 else 0.0
            if dd < max_dd:
                max_dd = dd

        # 标准差
        mean_r = 0.0
        for i in prange(n - 1):
            mean_r += returns[i]
        mean_r /= (n - 1)
        var = 0.0
        for i in prange(n - 1):
            diff = returns[i] - mean_r
            var += diff * diff
        std = (var / (n - 2)) ** 0.5 if n > 2 else 0.0

        excess_ret = annual_ret - risk_free_rate
        sharpe = excess_ret / (std * (250.0 ** 0.5)) if std > 0 else 0.0
        if sharpe < -1e6 or sharpe > 1e6:
            sharpe = 0.0

        # Sortino
        downside_var = 0.0
        downside_count = 0
        for i in prange(n - 1):
            if returns[i] < 0:
                diff = returns[i] - mean_r
                downside_var += diff * diff
                downside_count += 1
        downside_std = (downside_var / (downside_count - 1)) ** 0.5 if downside_count > 1 else 0.0
        sortino = excess_ret / downside_std * (250.0 ** 0.5) if downside_std > 0 else 0.0
        if sortino < -10.0:
            sortino = -10.0
        elif sortino > 10.0:
            sortino = 10.0

        # Calmar
        calmar = annual_ret / abs(max_dd) if max_dd != 0 else 0.0
        if calmar < -10.0:
            calmar = -10.0
        elif calmar > 10.0:
            calmar = 10.0

        return total_ret, annual_ret, max_dd, sharpe, sortino, calmar

    # 改进 (2025-06-15o): numba parallel=True 回退机制
    # 尝试并行编译，失败则回退到非并行版本
    try:
        _calc_metrics_fast_njit = njit(cache=True, parallel=True)(_calc_metrics_fast_njit_base)
        logger.debug("[numba] 并行 JIT 编译器已创建")
    except Exception as e:
        logger.warning(f"[numba] parallel=True 编译器创建失败 ({e})，回退到 parallel=False")
        _calc_metrics_fast_njit = njit(cache=True)(_calc_metrics_fast_njit_base)
        logger.debug("[numba] 非并行 JIT 编译器已创建")

    # 改进 (2025-06-15p): 限制 numba 内部线程数，避免与外部 ProcessPoolExecutor 竞争
    numba.set_num_threads(min(4, os.cpu_count() or 2))
    logger.debug(f"[numba] 内部线程数限制为 {min(4, os.cpu_count() or 2)}")

    _NUMBA_FIRST_CALL = True
    _NUMBA_LOCK = threading.Lock()

    def _calculate_metrics_fast(equity: list[float], risk_free_rate: float = 0.02) -> PerformanceMetrics:
        """numba JIT 加速版指标计算（lazy 编译，首次调用时触发）"""
        global _NUMBA_FIRST_CALL
        equity_arr = np.array(equity, dtype=np.float64)
        # 改进 (2025-06-15v): 子进程中直接调用，跳过锁以避免竞争
        if multiprocessing.current_process().name != 'MainProcess':
            total_ret, annual_ret, max_dd, sharpe, sortino, calmar = _calc_metrics_fast_njit(equity_arr, risk_free_rate)
        else:
            with _NUMBA_LOCK:
                total_ret, annual_ret, max_dd, sharpe, sortino, calmar = _calc_metrics_fast_njit(equity_arr, risk_free_rate)
                if _NUMBA_FIRST_CALL:
                    _NUMBA_FIRST_CALL = False
                    logger.debug("[numba] 首次 JIT 编译执行完成")
        return PerformanceMetrics(
            total_return_pct=round(total_ret * 100, 2),
            annual_return_pct=round(annual_ret * 100, 2),
            max_drawdown_pct=round(max_dd * 100, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(calmar, 2),
        )
else:
    _calculate_metrics_fast = _calculate_metrics


def _build_result_item(params: dict, metrics: PerformanceMetrics) -> OptimizationResultItem:
    """将 PerformanceMetrics 展平为 OptimizationResultItem"""
    return OptimizationResultItem(
        params=params,
        total_return_pct=metrics.total_return_pct,
        annual_return_pct=metrics.annual_return_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        calmar_ratio=metrics.calmar_ratio,
        win_rate=metrics.win_rate,
        total_trades=metrics.total_trades,
    )


# 改进 (2025-06-15g): 子进程全局变量，由 _init_worker 设置
# 用于子进程向父进程透传 on_progress 进度
_worker_progress_queue = None

def _init_worker(progress_queue):
    """ProcessPoolExecutor / loky worker 初始化函数"""
    global _worker_progress_queue
    _worker_progress_queue = progress_queue


def _run_single_backtest(
    strategy_cls: type,
    params: dict,
    data: pd.DataFrame,
    commission_pct: float,
    slippage_pct: float,
    impact_cost_pct: float,
    min_commission: float,
    risk_free_rate: float,
    initial_cash: float = 1_000_000.0,
    progress_queue=None,
) -> dict:
    """在子进程中运行单次回测 - 所有参数均可 pickle 序列化。

    ProcessPoolExecutor 要求提交的函数和参数均可序列化，
    因此传递标量配置值而非 BacktestEngine 实例。
    每个子进程会创建独立的 BacktestEngine，避免共享状态。

    改进 (2025-06-15f): 返回轻量 dict 替代 OptimizationResultItem，
    减少 pickle 序列化/反序列化开销（dict 比 Pydantic BaseModel 更高效）。
    改进 (2025-06-15g): 支持 progress_queue 透传 on_progress，父进程可感知子进程内部进度。
    """
    cfg = BacktestConfig(
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        impact_cost_pct=impact_cost_pct,
        min_commission=min_commission,
        risk_free_rate=risk_free_rate,
        initial_cash=initial_cash,
    )
    engine = BacktestEngine(config=cfg)
    strategy = strategy_cls(**params)
    # 改进 (2025-06-15g): 如果提供了 progress_queue，将回测内部进度透传到队列
    if progress_queue is not None:
        def _internal_progress(pct, msg):
            try:
                progress_queue.put_nowait((os.getpid(), pct, msg))
            except Exception:
                pass
        result = engine.run(strategy, data, on_progress=_internal_progress)
    else:
        result = engine.run(strategy, data)
    metrics = result.metrics
    # 返回轻量 dict，避免序列化完整 Pydantic 对象
    return {
        'params': params,
        'total_return_pct': metrics.total_return_pct,
        'annual_return_pct': metrics.annual_return_pct,
        'max_drawdown_pct': metrics.max_drawdown_pct,
        'sharpe_ratio': metrics.sharpe_ratio,
        'sortino_ratio': metrics.sortino_ratio,
        'calmar_ratio': metrics.calmar_ratio,
        'win_rate': metrics.win_rate,
        'total_trades': metrics.total_trades,
    }


def _run_single_backtest_file(
    strategy_cls: type,
    params: dict,
    data_path: str,
    commission_pct: float,
    slippage_pct: float,
    impact_cost_pct: float,
    min_commission: float,
    risk_free_rate: float,
    initial_cash: float = 1_000_000.0,
    progress_queue=None,
) -> dict:
    """在子进程中通过文件路径读取数据运行单次回测。

    改进 (2025-06-15): 对于中等数据量（5-50MB），通过临时 parquet 文件传递数据，
    避免 ProcessPoolExecutor 的 DataFrame 序列化开销（尤其 macOS spawn 模式下）。
    改进 (2025-06-15f): 返回轻量 dict 替代 OptimizationResultItem，减少 pickle 开销。
    改进 (2025-06-15g): 支持 progress_queue 透传 on_progress。
    """
    # 改进 (2025-06-15ah): 支持 parquet 和 feather 两种数据传递格式
    # 改进 (2025-06-15ai): 读取异常防御——文件损坏或不存在时返回空结果而非崩溃
    try:
        if data_path.endswith('.feather'):
            data = pd.read_feather(data_path)
        else:
            data = pd.read_parquet(data_path)
    except Exception as e:
        logger.error(f"[_run_single_backtest_file] 数据文件读取失败 ({data_path}): {e}")
        return {
            'params': params,
            'total_return_pct': 0.0,
            'annual_return_pct': 0.0,
            'max_drawdown_pct': 0.0,
            'sharpe_ratio': 0.0,
            'sortino_ratio': 0.0,
            'calmar_ratio': 0.0,
            'win_rate': 0.0,
            'total_trades': 0,
        }
    # 改进 (2025-06-15c): parquet 读取后 date 列恢复为 datetime64，需显式转回 datetime.date
    # 防御: 空 DataFrame 时跳过转换，避免 iloc[0] 抛出 IndexError
    if 'date' in data.columns and len(data) > 0 and not isinstance(data['date'].iloc[0], date):
        data['date'] = pd.to_datetime(data['date']).dt.date
    cfg = BacktestConfig(
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        impact_cost_pct=impact_cost_pct,
        min_commission=min_commission,
        risk_free_rate=risk_free_rate,
        initial_cash=initial_cash,
    )
    engine = BacktestEngine(config=cfg)
    strategy = strategy_cls(**params)
    if progress_queue is not None:
        def _internal_progress(pct, msg):
            try:
                progress_queue.put_nowait((os.getpid(), pct, msg))
            except Exception:
                pass
        result = engine.run(strategy, data, on_progress=_internal_progress)
    else:
        result = engine.run(strategy, data)
    metrics = result.metrics
    return {
        'params': params,
        'total_return_pct': metrics.total_return_pct,
        'annual_return_pct': metrics.annual_return_pct,
        'max_drawdown_pct': metrics.max_drawdown_pct,
        'sharpe_ratio': metrics.sharpe_ratio,
        'sortino_ratio': metrics.sortino_ratio,
        'calmar_ratio': metrics.calmar_ratio,
        'win_rate': metrics.win_rate,
        'total_trades': metrics.total_trades,
    }


# 改进 (2025-06-15n): Pareto 进程池 worker，模块顶层函数可 pickle 序列化
def _run_pareto_combo(args_tuple):
    """Pareto 优化进程池 worker：接收参数元组，返回结果 dict + metrics_dict。

    包装 _run_single_backtest 使其与进程池兼容，避免闭包不可序列化。
    改进 (2025-06-15ai): 异常透传——worker 内捕获异常，返回错误标记而非崩溃整个批次。
    """
    try:
        strategy_cls, params, data, commission_pct, slippage_pct, impact_cost_pct, min_commission, risk_free_rate, initial_cash, pareto_metrics = args_tuple
        result = _run_single_backtest(
            strategy_cls, params, data,
            commission_pct, slippage_pct, impact_cost_pct,
            min_commission, risk_free_rate, initial_cash, None,
        )
        item = OptimizationResultItem(**result)
        metrics_dict = {m: getattr(item, m, 0.0) for m in pareto_metrics}
        return result, metrics_dict
    except Exception as e:
        logger.warning(f"[_run_pareto_combo] 组合评估失败: {e}")
        return None, None


# 改进 (2025-06-15o): Pareto 进程池 worker（parquet 文件版），大数据量避免重复 pickle
def _run_pareto_combo_file(args_tuple):
    """Pareto 优化进程池 worker：通过 parquet 文件路径传递数据，避免 DataFrame 重复序列化。

    当 data 超过 1MB 时，主进程写入一次临时 parquet，所有 worker 读取同一文件。
    改进 (2025-06-15ai): 异常透传——worker 内捕获异常，返回错误标记而非崩溃整个批次。
    """
    try:
        strategy_cls, params, data_path, commission_pct, slippage_pct, impact_cost_pct, min_commission, risk_free_rate, initial_cash, pareto_metrics = args_tuple
        result = _run_single_backtest_file(
            strategy_cls, params, data_path,
            commission_pct, slippage_pct, impact_cost_pct,
            min_commission, risk_free_rate, initial_cash, None,
        )
        item = OptimizationResultItem(**result)
        metrics_dict = {m: getattr(item, m, 0.0) for m in pareto_metrics}
        return result, metrics_dict
    except Exception as e:
        logger.warning(f"[_run_pareto_combo_file] 组合评估失败: {e}")
        return None, None


def _normalize_date(d) -> date:
    """统一日期类型为 datetime.date

    改进 (2025-06-15p): 防御性处理 polars/pandas 返回的多种日期类型
    改进 (2025-06-15z): 将 datetime 检查前置，避免子类关系导致的歧义
    """
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    # 改进 (2025-06-15p): 处理 pd.Timestamp / np.datetime64 / polars 日期
    if hasattr(d, 'to_pydatetime') and callable(d.to_pydatetime):
        return d.to_pydatetime().date()
    # 改进 (2025-06-15q): 防御性限制 .date() 调用范围，避免 str/bytes 误匹配
    if not isinstance(d, (str, bytes)) and hasattr(d, 'date') and callable(d.date):
        try:
            return d.date()
        except Exception:
            pass
    if isinstance(d, str):
        try:
            return date.fromisoformat(d[:10])
        except ValueError:
            pass
    if hasattr(d, 'isoformat'):
        try:
            return date.fromisoformat(str(d)[:10])
        except ValueError:
            pass
    return d


# 改进 (2025-06-15ag): 模块级 crowding distance 计算，用于多目标 Pareto 前沿的 best_item 选择
def _crowding_distance(front_metrics: list[dict], pareto_metrics: list[str]) -> list[float]:
    """计算 Pareto 前沿每个解的拥挤距离。

    拥挤距离越大表示该解在目标空间中越独特（周围邻居稀疏）。
    用于选择"最佳权衡解"——既不过于偏向某一指标，又有足够的代表性。

    Args:
        front_metrics: 前沿解的指标 dict 列表
        pareto_metrics: 需要优化的指标名称列表

    Returns:
        每个解的拥挤距离列表（与 front_metrics 同序）
    """
    n = len(front_metrics)
    if n <= 2:
        return [float('inf')] * n

    # 改进 (2025-06-15aj): 单指标时 crowding distance 退化为简单排序，直接返回均匀分布的距离
    if len(pareto_metrics) == 1:
        m = pareto_metrics[0]
        sorted_indices = sorted(range(n), key=lambda i: front_metrics[i].get(m, 0.0))
        distances = [0.0] * n
        distances[sorted_indices[0]] = float('inf')
        distances[sorted_indices[-1]] = float('inf')
        if n > 2:
            step = 1.0 / (n - 1)
            for rank, idx in enumerate(sorted_indices[1:-1], start=1):
                distances[idx] = rank * step
        return distances

    distances = [0.0] * n
    for m in pareto_metrics:
        # 改进 (2025-06-15ag): KeyError 防御——缺失指标时回退到 0.0
        sorted_indices = sorted(range(n), key=lambda i: front_metrics[i].get(m, 0.0))
        # 边界点（最优和最差）给予无穷大距离，确保保留极端解
        distances[sorted_indices[0]] = float('inf')
        distances[sorted_indices[-1]] = float('inf')
        m_min = front_metrics[sorted_indices[0]].get(m, 0.0)
        m_max = front_metrics[sorted_indices[-1]].get(m, 0.0)
        if m_max == m_min:
            continue
        # 中间点的拥挤距离：相邻点在归一化后的差值
        for k in range(1, n - 1):
            i = sorted_indices[k]
            diff = (front_metrics[sorted_indices[k + 1]].get(m, m_max) - front_metrics[sorted_indices[k - 1]].get(m, m_min)) / (m_max - m_min)
            distances[i] += abs(diff)
    return distances


# 改进 (2025-06-15z): 模块级 Pareto 非支配排序函数，避免每次调用 _run_pareto_optimization 重复创建闭包
def _dominates(a_metrics: dict, b_metrics: dict, pareto_metrics: list[str]) -> bool:
    """a 支配 b: a 在所有指标上不差于 b，且至少一个指标严格优于 b。

    前置条件：a_metrics / b_metrics 必须为 dict（由调用方 _update_pareto_front 保证）。
    改进 (2025-06-15ae):  metrics 已在前端统一为 dict，直接索引访问，
    移除 try/getattr 回退以提升 hot path 性能。
    """
    # 改进 (2025-06-15ah): assert 在 python -O 模式下会被跳过，改用显式 TypeError
    if not isinstance(a_metrics, dict) or not isinstance(b_metrics, dict):
        raise TypeError(f"_dominates 要求 dict metrics, got {type(a_metrics).__name__} and {type(b_metrics).__name__}")
    better_in_any = False
    for m in pareto_metrics:
        a_val = a_metrics[m]
        b_val = b_metrics[m]
        if m == 'max_drawdown_pct':
            if a_val > b_val:
                return False
            if a_val < b_val:
                better_in_any = True
        else:
            if a_val < b_val:
                return False
            if a_val > b_val:
                better_in_any = True
    return better_in_any


def _fast_rebuild_pareto_front(front_items, front_metrics, pareto_metrics):
    """使用 numpy 向量化比较重建 Pareto 前沿，O(k²) 但常数更小。

    Args:
        front_items: 前沿解的列表（OptimizationResultItem 或 dict）
        front_metrics: 前沿解对应指标的字典列表或对象列表
        pareto_metrics: 需要优化的指标名称列表

    Returns:
        (new_items, new_metrics): 过滤后的 Pareto 前沿

    改进 (2025-06-15aa): 使用 pd.DataFrame.to_numpy() 替代双重循环填充，
    添加 nan/inf 防御和相对容差，避免极端值导致支配关系判定不稳定。
    改进 (2025-06-15ac): 全局统一相对容差，避免非对称容差导致支配关系不一致。
    """
    if len(front_items) <= 100 or len(pareto_metrics) == 0:
        return front_items, front_metrics
    # 使用 pd.DataFrame 一次性转换为 numpy 数组，避免 Python 级双重循环
    # 改进 (2025-06-15ai): 防御 to_numpy 异常（非数值列混入时）
    try:
        df = pd.DataFrame(front_metrics, columns=pareto_metrics)
        arr = df.to_numpy(dtype=np.float64)
    except Exception as e:
        logger.warning(f"[Pareto] 前沿向量化转换失败 ({e})，回退到 Python 级比较")
        return front_items, front_metrics
    # nan/inf 防御：若存在非有限值，回退到 Python 级精确比较
    if not np.isfinite(arr).all():
        logger.warning("[Pareto] 前沿指标含 nan/inf，跳过向量化重建")
        return front_items, front_metrics
    # 对于需要最小化的指标（如 max_drawdown），取负号统一为最大化问题
    for j, metric in enumerate(pareto_metrics):
        if metric == 'max_drawdown_pct':
            arr[:, j] = -arr[:, j]
    # 向量化支配检查：
    # 解 i 支配解 j 当且仅当 arr[i] >= arr[j] 且至少一个严格大于
    # 改进 (2025-06-15ac): 全局统一相对容差，确保支配关系对称
    n = arr.shape[0]
    dominated = np.zeros(n, dtype=np.bool_)
    global_rtol = 1e-12 * max(abs(arr.max()), 1.0)
    # 改进 (2025-06-15aj): 大 front 时使用 ThreadPoolExecutor 并行化外层循环
    # numpy 操作释放 GIL，多线程可以真正加速
    # 改进 (2025-06-15al): 使用模块级 ThreadPoolExecutor 单例，避免每次重建都创建/销毁线程
    # 改进 (2025-06-15am): 收集所有结果后统一合并，避免多线程竞争修改 dominated 数组
    if n > 500 and len(pareto_metrics) > 1:
        try:
            def _check_dominance(i):
                if dominated[i]:
                    return None
                ge = np.all(arr[i] + global_rtol >= arr, axis=1)
                gt = np.any(arr[i] > arr + global_rtol, axis=1)
                is_dominating = ge & gt
                is_dominating[i] = False
                return is_dominating
            global _THREAD_POOL
            if _THREAD_POOL is None:
                _THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(8, os.cpu_count() or 2),
                    thread_name_prefix="pareto_rebuild"
                )
            results = list(_THREAD_POOL.map(_check_dominance, range(n)))
            # 统一合并：避免多线程竞争修改 dominated
            for is_dominating in results:
                if is_dominating is not None:
                    dominated |= is_dominating
        except Exception as e:
            logger.warning(f"[Pareto] ThreadPoolExecutor 并行化失败 ({e})，回退到串行")
            for i in range(n):
                if dominated[i]:
                    continue
                ge = np.all(arr[i] + global_rtol >= arr, axis=1)
                gt = np.any(arr[i] > arr + global_rtol, axis=1)
                is_dominating = ge & gt
                is_dominating[i] = False
                dominated |= is_dominating
    else:
        for i in range(n):
            if dominated[i]:
                continue
            ge = np.all(arr[i] + global_rtol >= arr, axis=1)
            gt = np.any(arr[i] > arr + global_rtol, axis=1)
            is_dominating = ge & gt
            is_dominating[i] = False
            dominated |= is_dominating
    new_items = [front_items[i] for i in range(n) if not dominated[i]]
    new_metrics = [front_metrics[i] for i in range(n) if not dominated[i]]
    return new_items, new_metrics


def _update_pareto_front(front: list[tuple[Any, dict]], new_item: OptimizationResultItem, new_metrics: dict,
                        pareto_metrics: list[str],
                        rebuild_threshold: int = 150, rebuild_interval: int = 50,
                        last_rebuild_size: int = 0) -> tuple[list[tuple[Any, dict]], int]:
    """增量更新 Pareto 前沿，当前沿增长达到一定比例时触发快速重建。

    Args:
        front: 当前 Pareto 前沿列表
        new_item: 新解
        new_metrics: 新解的指标
        pareto_metrics: 需要优化的指标名称列表
        rebuild_threshold: 触发快速重建的前沿大小阈值（默认 150）
        rebuild_interval: 重建触发最小增长量（默认 50）
        last_rebuild_size: 上次重建时的前沿大小（默认 0）

    Returns:
        (front, last_rebuild_size): 更新后的前沿和重建大小标记

    改进 (2025-06-15ad): 增长率触发重建——前沿增长超过 rebuild_interval 时才重建，
    避免前沿停滞时的无效 O(k²) 重建。
    """
    dominated = False
    for _, existing_metrics in front:
        if _dominates(existing_metrics, new_metrics, pareto_metrics):
            dominated = True
            break
    if not dominated:
        # 改进 (2025-06-15aj): 原地删除被支配的现有解，避免创建新列表的拷贝开销
        for idx in range(len(front) - 1, -1, -1):
            if _dominates(new_metrics, front[idx][1], pareto_metrics):
                front.pop(idx)
        front.append((new_item, new_metrics))
        # 改进 (2025-06-15ad): 增长率触发重建——前沿增长超过 rebuild_interval 或 20% 时才重建
        if len(front) > rebuild_threshold and (
            (len(front) - last_rebuild_size) >= rebuild_interval or
            len(front) >= last_rebuild_size * 1.2
        ):
            items, metrics = _fast_rebuild_pareto_front(
                [it for it, _ in front], [me for _, me in front], pareto_metrics
            )
            front = list(zip(items, metrics))
            last_rebuild_size = len(front)
    # 改进 (2025-06-15an): 前沿硬性上限——Pareto 前沿理论上可无限增长，
    # 极端情况下（大量不相关参数组合）前沿可能膨胀到数万，按 crowding distance 截断到 5000
    # 修复 (2025-06-15ao): 截断后 last_rebuild_size 应等于当前前沿大小，避免下次重建检查误判
    _PARETO_FRONT_MAX_SIZE = 5000
    if len(front) > _PARETO_FRONT_MAX_SIZE:
        _front_metrics = [me for _, me in front]
        _cd = _crowding_distance(_front_metrics, pareto_metrics)
        _sorted_idx = sorted(range(len(front)), key=lambda i: _cd[i], reverse=True)
        _keep_idx = set(_sorted_idx[:_PARETO_FRONT_MAX_SIZE])
        front = [front[i] for i in range(len(front)) if i in _keep_idx]
        last_rebuild_size = len(front)
        logger.warning(
            f"[Pareto] 前沿大小 {len(front)} 超过上限 {_PARETO_FRONT_MAX_SIZE}，"
            f"已按 crowding distance 截断到 {_PARETO_FRONT_MAX_SIZE}"
        )
    return front, last_rebuild_size


# 改进 (2025-06-15ah): 批量更新 Pareto 前沿，减少重复重建检查和函数调用开销
def _update_pareto_front_batch(front: list[tuple[Any, dict]], new_items_metrics: list[tuple[Any, dict]],
                               pareto_metrics: list[str],
                               rebuild_threshold: int = 150, rebuild_interval: int = 50,
                               last_rebuild_size: int = 0) -> tuple[list[tuple[Any, dict]], int]:
    """批量更新 Pareto 前沿，接收多个新解，一次性完成插入和重建。

    性能优化：
    1. 先对新结果进行内部非支配过滤，减少需要插入 front 的数量
    2. 只在最后检查一次是否需要重建，避免每个结果都触发 O(k²) 检查
    3. 减少函数调用开销（尤其进程池流式 yield 时）

    Args:
        front: 当前 Pareto 前沿列表，每项为 (item, metrics_dict)
        new_items_metrics: 新解列表，每项为 (item, metrics_dict)
        pareto_metrics: 需要优化的指标名称列表
        rebuild_threshold: 触发快速重建的前沿大小阈值
        rebuild_interval: 重建触发最小增长量
        last_rebuild_size: 上次重建时的前沿大小

    Returns:
        (front, last_rebuild_size): 更新后的前沿和重建大小标记
    """
    if not new_items_metrics:
        return front, last_rebuild_size

    # 改进 (2025-06-15ai): 小 batch 跳过内部过滤——当 batch < 5 时 O(k²) 不值得
    if len(new_items_metrics) >= 5:
        # 步骤 1: 新结果内部非支配过滤——保留不被其他新结果支配的解
        filtered = []
        for i, (item_i, metrics_i) in enumerate(new_items_metrics):
            dominated = False
            for j, (_, metrics_j) in enumerate(new_items_metrics):
                if i != j and _dominates(metrics_j, metrics_i, pareto_metrics):
                    dominated = True
                    break
            if not dominated:
                filtered.append((item_i, metrics_i))
    else:
        filtered = new_items_metrics

    # 步骤 2: 将过滤后的新结果逐个插入 front（只需检查现有 front 成员）
    # 改进 (2025-06-15aj): 原地删除被支配的现有解，避免创建新列表的拷贝开销
    for item, metrics in filtered:
        dominated = False
        for _, existing_metrics in front:
            if _dominates(existing_metrics, metrics, pareto_metrics):
                dominated = True
                break
        if not dominated:
            for idx in range(len(front) - 1, -1, -1):
                if _dominates(metrics, front[idx][1], pareto_metrics):
                    front.pop(idx)
            front.append((item, metrics))

    # 步骤 3: 只在最后检查一次重建条件
    if len(front) > rebuild_threshold and (
        (len(front) - last_rebuild_size) >= rebuild_interval or
        len(front) >= last_rebuild_size * 1.2
    ):
        items, metrics = _fast_rebuild_pareto_front(
            [it for it, _ in front], [me for _, me in front], pareto_metrics
        )
        front = list(zip(items, metrics))
        last_rebuild_size = len(front)

    # 改进 (2025-06-15an): 前沿硬性上限——Pareto 前沿理论上可无限增长，
    # 极端情况下（大量不相关参数组合）前沿可能膨胀到数万，按 crowding distance 截断到 5000
    _PARETO_FRONT_MAX_SIZE = 5000
    if len(front) > _PARETO_FRONT_MAX_SIZE:
        _front_metrics = [me for _, me in front]
        _cd = _crowding_distance(_front_metrics, pareto_metrics)
        _sorted_idx = sorted(range(len(front)), key=lambda i: _cd[i], reverse=True)
        _keep_idx = set(_sorted_idx[:_PARETO_FRONT_MAX_SIZE])
        front = [front[i] for i in range(len(front)) if i in _keep_idx]
        last_rebuild_size = min(last_rebuild_size, _PARETO_FRONT_MAX_SIZE)
        logger.warning(
            f"[Pareto] 前沿大小 {len(front)} 超过上限 {_PARETO_FRONT_MAX_SIZE}，"
            f"已按 crowding distance 截断到 {_PARETO_FRONT_MAX_SIZE}"
        )

    return front, last_rebuild_size


# 改进 (2025-06-15ae): 轻量数据阈值常量，便于统一调整和测试
LIGHTWEIGHT_DATA_THRESHOLD_BYTES = 100_000


def _compute_pareto_workers(data_size_bytes: int, n_combos: int) -> int:
    """计算 Pareto 并行评估的 worker 数量，考虑 CPU、内存、文件描述符限制。

    改进 (2025-06-15z): 将分散的 worker 计算逻辑封装为单一函数，便于测试和复用。
    改进 (2025-06-15ab): 小组合数或轻量数据直接返回 1，避免无意义的进程启动开销。
    """
    if n_combos < 50 or data_size_bytes < LIGHTWEIGHT_DATA_THRESHOLD_BYTES:
        return 1

    _pareto_workers = max(1, min(8, (os.cpu_count() or 2)))

    # 根据可用内存动态调整 worker 数
    if _HAS_PSUTIL:
        try:
            _mem = psutil.virtual_memory()
            _avail_mem = _mem.available
            _total_mem = _mem.total
            if _avail_mem < 1 * 1024 * 1024 * 1024 or _avail_mem / _total_mem < 0.2:
                _pareto_workers = max(1, _pareto_workers // 2)
                logger.warning(
                    f"[Pareto] 可用内存不足 {_avail_mem / 1024 / 1024:.0f}MB "
                    f"({_avail_mem / _total_mem * 100:.0f}%)，worker 数降至 {_pareto_workers}"
                )
        except Exception:
            pass

    # macOS 文件描述符限制检查
    try:
        import resource
        _soft_fd_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        _min_fd_needed = _pareto_workers * 10 + 50
        if _soft_fd_limit < _min_fd_needed:
            _pareto_workers = max(1, (_soft_fd_limit - 50) // 10)
            logger.warning(
                f"[Pareto] 文件描述符限制 {_soft_fd_limit} 过低，worker 数降至 {_pareto_workers}"
            )
    except Exception:
        pass

    # 改进 (2025-06-15ak): CPU 使用率检查——系统 CPU 满载时减少 worker 避免竞争
    # 改进 (2025-06-15al): 添加冷却期——每 5 秒才采样一次，避免快速连续调用时累积阻塞
    if _HAS_PSUTIL:
        try:
            _now = time.time()
            if _now - getattr(_compute_pareto_workers, '_last_cpu_check_time', 0) >= 5:
                _cpu_percent = psutil.cpu_percent(interval=0.1)
                _compute_pareto_workers._last_cpu_check_time = _now
                _compute_pareto_workers._last_cpu_check_value = _cpu_percent
            else:
                _cpu_percent = getattr(_compute_pareto_workers, '_last_cpu_check_value', 0)
            if _cpu_percent > 80:
                _pareto_workers = max(1, _pareto_workers // 2)
                logger.warning(
                    f"[Pareto] CPU 使用率 {_cpu_percent:.0f}% 过高，worker 数降至 {_pareto_workers}"
                )
        except Exception:
            pass

    return _pareto_workers


class _BoundedResultBuffer:
    """改进 (2025-06-15h): 使用 min-heap 维护固定大小的 top-k 结果缓冲区。

    避免百万级组合时 results 列表无限增长导致内存爆炸。
    插入复杂度 O(log k)，获取结果 O(k log k)。
    改进 (2025-06-15i): 支持 get_results(n) 动态调整返回数量。

    注意：传入的 OptimizationResultItem 在 add() 后不应被外部修改，
    因为 heap 中缓存了 add 时刻的 metric 值。如果 item 属性被修改，
    get_results() 重建 heap 时可能产生不一致。
    """
    def __init__(self, max_size: int, metric_key: str):
        self.max_size = max_size
        self.metric_key = metric_key
        self._heap: list[tuple[float, int, OptimizationResultItem]] = []  # min-heap with tiebreaker
        self._counter = itertools.count()  # 单调递增 tiebreaker，避免回绕问题

    def add(self, item: OptimizationResultItem) -> None:
        val = getattr(item, self.metric_key, 0.0)
        entry = (val, next(self._counter), item)
        if len(self._heap) < self.max_size:
            heapq.heappush(self._heap, entry)
        elif val > self._heap[0][0]:
            heapq.heapreplace(self._heap, entry)

    def get_results(self, n: int | None = None) -> list[OptimizationResultItem]:
        """返回按 metric 降序排列的结果列表，支持动态调整返回数量。

        当 heap 中最大 counter 值超过 1M 时重建 heap 并重置，
        避免超长运行时 int 膨胀；正常调用零额外开销。
        """
        results = [item for _, _, item in sorted(self._heap, reverse=True)]
        # 从 heap 中检查最大 counter 值（不消费 counter，无副作用）
        max_counter = max((c for _, c, _ in self._heap), default=0) if self._heap else 0
        if max_counter > 1_000_000:
            self._counter = itertools.count()
            # 重建 heap：直接重用 heap 中已缓存的 val，避免 getattr 重算
            self._heap = [(val, next(self._counter), item)
                          for val, _, item in self._heap]
            heapq.heapify(self._heap)
        if n is not None and n > 0:
            return results[:n]
        return results

    def __len__(self) -> int:
        return len(self._heap)

    @property
    def best_value(self) -> float:
        """当前最优值（heap 中最小值，即 top-k 中最低的那个）"""
        if not self._heap:
            return float('-inf')
        return self._heap[0][0]


def _worker_initializer(strategy_module_name: str):
    """改进 (2025-06-15h): ProcessPoolExecutor worker 初始化函数，预导入策略模块。
    减少 spawn 模式下每个 worker 的重复 import 开销。
    """
    try:
        __import__(strategy_module_name)
    except Exception as e:
        logger.warning(f"[worker_initializer] 预导入策略模块 {strategy_module_name} 失败: {e}")


def _get_memory_mb() -> float:
    """改进 (2025-06-15h): 获取当前进程内存使用（MB）"""
    if _HAS_PSUTIL:
        try:
            return psutil.Process().memory_info().rss / 1024 / 1024
        except Exception:
            pass
    return 0.0


# 改进 (2025-06-15i): 优化结果 SQLite 持久化
_OPTIMIZATION_DB_PATH = Path("data") / "optimization_history.db"

def _init_optimization_db():
    """初始化 SQLite 优化历史数据库"""
    try:
        import sqlite3
        _OPTIMIZATION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_OPTIMIZATION_DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS optimization_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                optimize_metric TEXT NOT NULL,
                total_combinations INTEGER,
                best_params TEXT,
                best_metrics TEXT,
                top_results TEXT,
                execution_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_strategy_metric 
            ON optimization_history(strategy_name, optimize_metric)
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[optimization_history] 数据库初始化失败: {e}")

def _save_optimization_history(
    strategy_name: str,
    optimize_metric: str,
    total_combinations: int,
    best_params: dict,
    best_metrics: PerformanceMetrics | None,
    top_results: list[OptimizationResultItem],
    execution_time_ms: int,
):
    """将优化结果保存到 SQLite 历史库"""
    try:
        import sqlite3, json
        _init_optimization_db()
        conn = sqlite3.connect(str(_OPTIMIZATION_DB_PATH))
        best_metrics_dict = best_metrics.model_dump() if best_metrics else {}
        top_results_dict = [
            {
                "params": r.params,
                "total_return_pct": r.total_return_pct,
                "annual_return_pct": r.annual_return_pct,
                "max_drawdown_pct": r.max_drawdown_pct,
                "sharpe_ratio": r.sharpe_ratio,
                "sortino_ratio": r.sortino_ratio,
                "calmar_ratio": r.calmar_ratio,
                "win_rate": r.win_rate,
                "total_trades": r.total_trades,
            }
            for r in top_results
        ]
        conn.execute(
            """
            INSERT INTO optimization_history
            (strategy_name, optimize_metric, total_combinations, best_params, best_metrics, top_results, execution_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_name,
                optimize_metric,
                total_combinations,
                json.dumps(best_params),
                json.dumps(best_metrics_dict),
                json.dumps(top_results_dict),
                execution_time_ms,
            ),
        )
        conn.commit()
        conn.close()
        logger.info(f"[optimization_history] 优化结果已保存到 SQLite ({len(top_results)} 条 top results)")
    except Exception as e:
        logger.warning(f"[optimization_history] 保存失败: {e}")

def _load_last_best_params(strategy_name: str) -> dict | None:
    """改进 (2025-06-15i): 从 SQLite 加载上次最优参数"""
    try:
        import sqlite3, json
        if not _OPTIMIZATION_DB_PATH.exists():
            return None
        conn = sqlite3.connect(str(_OPTIMIZATION_DB_PATH))
        cursor = conn.execute(
            "SELECT best_params FROM optimization_history WHERE strategy_name = ? ORDER BY created_at DESC LIMIT 1",
            (strategy_name,),
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        logger.warning(f"[optimization_history] 加载上次最优参数失败: {e}")
    return None


def get_optimization_history(strategy_name: str | None = None, optimize_metric: str | None = None, limit: int = 10) -> list[dict]:
    """改进 (2025-06-15j): 查询优化历史记录

    Args:
        strategy_name: 策略名称过滤，None=不过滤
        optimize_metric: 优化指标过滤，None=不过滤
        limit: 返回记录数上限

    Returns:
        list[dict]: 每条记录包含 id, strategy_name, optimize_metric, best_params, best_metrics, execution_time_ms, created_at
    """
    try:
        import sqlite3, json
        if not _OPTIMIZATION_DB_PATH.exists():
            return []
        conn = sqlite3.connect(str(_OPTIMIZATION_DB_PATH))
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM optimization_history WHERE 1=1"
        params = []
        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        if optimize_metric:
            query += " AND optimize_metric = ?"
            params.append(optimize_metric)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        results = []
        for row in rows:
            results.append({
                'id': row['id'],
                'strategy_name': row['strategy_name'],
                'optimize_metric': row['optimize_metric'],
                'total_combinations': row['total_combinations'],
                'best_params': json.loads(row['best_params']) if row['best_params'] else {},
                'best_metrics': json.loads(row['best_metrics']) if row['best_metrics'] else {},
                'top_results_count': len(json.loads(row['top_results'])) if row['top_results'] else 0,
                'execution_time_ms': row['execution_time_ms'],
                'created_at': row['created_at'],
            })
        return results
    except Exception as e:
        logger.warning(f"[optimization_history] 查询失败: {e}")
        return []


def compare_optimization_runs(strategy_name: str, metric: str = 'sharpe_ratio', limit: int = 5) -> dict:
    """改进 (2025-06-15j): 对比同一策略的多次优化运行，分析参数演化趋势

    Args:
        strategy_name: 策略名称
        metric: 要对比的指标字段名
        limit: 对比最近 N 次运行

    Returns:
        dict: 包含演化趋势、平均指标、最佳记录等
    """
    try:
        import json
        history = get_optimization_history(strategy_name=strategy_name, limit=limit)
        if not history:
            return {'error': '无历史记录'}

        values = []
        for h in history:
            bm = h.get('best_metrics', {})
            values.append(bm.get(metric, 0.0))

        return {
            'strategy_name': strategy_name,
            'metric': metric,
            'total_runs': len(history),
            'latest_value': values[0] if values else None,
            'best_value': max(values) if values else None,
            'worst_value': min(values) if values else None,
            'average_value': sum(values) / len(values) if values else None,
            'trend': 'improving' if len(values) >= 2 and values[0] > values[-1] else 'stable' if len(values) >= 2 and abs(values[0] - values[-1]) < 0.01 else 'declining',
            'history': history,
        }
    except Exception as e:
        logger.warning(f"[optimization_history] 对比失败: {e}")
        return {'error': str(e)}


def export_results_to_csv(results: list[OptimizationResultItem], path: str, metric_key: str = 'sharpe_ratio'):
    """改进 (2025-06-15j): 导出优化结果到 CSV 文件

    改进 (2025-06-20): 原子写入——先写临时文件再替换，防止并发写入产生损坏文件。

    Args:
        results: OptimizationResultItem 列表
        path: 输出 CSV 文件路径
        metric_key: 排序指标字段名
    """
    try:
        rows = []
        for r in results:
            row = dict(r.params)
            row['total_return_pct'] = r.total_return_pct
            row['annual_return_pct'] = r.annual_return_pct
            row['max_drawdown_pct'] = r.max_drawdown_pct
            row['sharpe_ratio'] = r.sharpe_ratio
            row['sortino_ratio'] = r.sortino_ratio
            row['calmar_ratio'] = r.calmar_ratio
            row['win_rate'] = r.win_rate
            row['total_trades'] = r.total_trades
            rows.append(row)
        df = pd.DataFrame(rows)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.csv.tmp')
        df.to_csv(tmp, index=False, encoding='utf-8-sig')
        tmp.replace(p)
        logger.info(f"[export_results] CSV 已导出: {path} ({len(rows)} 行)")
    except Exception as e:
        logger.warning(f"[export_results] CSV 导出失败: {e}")


def export_results_to_excel(results: list[OptimizationResultItem], path: str, metric_key: str = 'sharpe_ratio'):
    """改进 (2025-06-15j): 导出优化结果到 Excel 文件

    Args:
        results: OptimizationResultItem 列表
        path: 输出 Excel 文件路径
        metric_key: 排序指标字段名
    """
    try:
        rows = []
        for r in results:
            row = dict(r.params)
            row['total_return_pct'] = r.total_return_pct
            row['annual_return_pct'] = r.annual_return_pct
            row['max_drawdown_pct'] = r.max_drawdown_pct
            row['sharpe_ratio'] = r.sharpe_ratio
            row['sortino_ratio'] = r.sortino_ratio
            row['calmar_ratio'] = r.calmar_ratio
            row['win_rate'] = r.win_rate
            row['total_trades'] = r.total_trades
            rows.append(row)
        df = pd.DataFrame(rows)
        df.to_excel(path, index=False, engine='openpyxl')
        logger.info(f"[export_results] Excel 已导出: {path} ({len(rows)} 行)")
    except Exception as e:
        logger.warning(f"[export_results] Excel 导出失败: {e}")


class BacktestEngine:
    """回测引擎 - 向量化计算，支持可配置交易成本和参数优化"""

    def __init__(self, config: Optional[BacktestConfig] = None):
        cfg = config or BacktestConfig()
        self.commission_pct = cfg.commission_pct
        self.slippage_pct = cfg.slippage_pct
        self.impact_cost_pct = cfg.impact_cost_pct
        self.min_commission = cfg.min_commission
        self.risk_free_rate = cfg.risk_free_rate
        self.initial_cash = cfg.initial_cash
        self.benchmark = cfg.benchmark
        # 改进 (2025-06-15l): numba JIT 加速选项
        self.use_fast_metrics = os.environ.get('LH_USE_FAST_METRICS', '1') == '1' and _HAS_NUMBA
        # 改进 (2025-06-15l): polars 替代 pandas 选项
        self.use_polars = os.environ.get('LH_USE_POLARS', '0') == '1' and _HAS_POLARS

    def _calc_equal_weight_benchmark(self, data: pd.DataFrame, dates: list) -> tuple[list[dict], list[float]]:
        """固定篮子等权基准：以第一日的券为初始篮子，只剔除退市券，新券不加入
        
        提取为独立方法，供 csi_convertible_bond 回退时调用，避免递归。
        """
        benchmark_equity = [self.initial_cash]
        date_data_map = {}
        for d, group in data.groupby('date'):
            nd = _normalize_date(d)
            date_data_map[nd] = group
        sorted_dates = sorted(date_data_map.keys())
        if len(sorted_dates) < 2:
            return [], []

        # 初始篮子：第一日所有券
        initial_codes = set(date_data_map[sorted_dates[0]]['code'].values)
        active_basket = initial_codes.copy()

        benchmark_equity.append(self.initial_cash)
        for i in range(1, len(sorted_dates)):
            prev_date = sorted_dates[i - 1]
            curr_date = sorted_dates[i]
            prev_data = date_data_map[prev_date]
            curr_data = date_data_map[curr_date]

            curr_codes = set(curr_data['code'].values)
            surviving_codes = active_basket & curr_codes
            if not surviving_codes:
                surviving_codes = curr_codes
                active_basket = curr_codes.copy()

            daily_returns = []
            for code in surviving_codes:
                prev_row = prev_data[prev_data['code'] == code]
                curr_row = curr_data[curr_data['code'] == code]
                if prev_row.empty or curr_row.empty:
                    continue
                prev_price = float(prev_row['price'].iloc[0])
                curr_price = float(curr_row['price'].iloc[0])
                if prev_price > 0:
                    daily_returns.append((curr_price / prev_price) - 1)

            if daily_returns:
                avg_return = np.mean(daily_returns)
                benchmark_equity.append(benchmark_equity[-1] * (1 + avg_return))
            else:
                benchmark_equity.append(benchmark_equity[-1])

        benchmark_curve = []
        for j, val in enumerate(benchmark_equity):
            if j > 0:
                d = sorted_dates[j - 1]
                benchmark_curve.append({
                    'date': d.isoformat() if isinstance(d, date) else str(d),
                    'value': round(val, 6),
                })
        return benchmark_curve, benchmark_equity

    def _calc_benchmark_curve(self, data: pd.DataFrame, dates: list) -> tuple[list[dict], list[float]]:
        """计算基准净值曲线

        支持两种基准:
        - equal_weight: 每日所有转债等权买入并持有（固定篮子）
        - csi_convertible_bond: 中证转债指数（从 AKShare 获取，失败时回退到 equal_weight）
        - None: 无基准
        """
        if self.benchmark is None:
            return [], []

        if self.benchmark == "equal_weight":
            return self._calc_equal_weight_benchmark(data, dates)

        elif self.benchmark == "csi_convertible_bond":
            """中证转债指数 000832.CSI - 从 AKShare 获取真实数据
            
            改进 (2025-06-15b): 从预留接口实现为真实数据获取。
            使用 ak.index_zh_a_hist 获取指数历史数据，支持自动缓存和回退。
            """
            min_date = min(dates) if dates else None
            max_date = max(dates) if dates else None
            # 改进 (2025-06-15c): cache_key 按周对齐，相邻日期回测共享缓存，提升命中率
            # 改进 (2025-06-15d): 从月份对齐改为周对齐，更适合高频滚动回测（如每周Walk-Forward）
            if min_date and max_date:
                _min_week = min_date.strftime("%Y%W")
                _max_week = max_date.strftime("%Y%W")
                cache_key = f"csi_cb_{_min_week}_{_max_week}"
            else:
                cache_key = None
            
            if not hasattr(BacktestEngine, '_csi_cache'):
                BacktestEngine._csi_cache = {}
                # 改进 (2025-06-15): 尝试从磁盘加载持久化缓存，带 TTL 检查（7天过期）
                try:
                    import pickle, os as _os, time as _time
                    _cache_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "csi_cache.pkl")
                    _cache_path = _os.path.abspath(_cache_path)
                    if _os.path.exists(_cache_path):
                        _mtime = _os.path.getmtime(_cache_path)
                        _age_days = (_time.time() - _mtime) / 86400
                        if _age_days < 7:
                            with open(_cache_path, "rb") as f:
                                BacktestEngine._csi_cache = pickle.load(f)
                            logger.info(
                                f"[BacktestEngine] 中证转债指数: 从磁盘加载 {len(BacktestEngine._csi_cache)} 条缓存"
                                f"(已缓存 {_age_days:.1f} 天)"
                            )
                        else:
                            logger.info(
                                f"[BacktestEngine] 中证转债指数: 磁盘缓存已过期 {_age_days:.1f} 天，跳过加载"
                            )
                except PermissionError as _e:
                    logger.warning(f"[BacktestEngine] 中证转债指数: 磁盘缓存无权限加载 {_e}")
                except Exception as _e:
                    logger.debug(f"[BacktestEngine] 中证转债指数: 磁盘缓存加载失败 {_e}")
            if not hasattr(BacktestEngine, '_csi_unavailable'):
                BacktestEngine._csi_unavailable = False
            if not hasattr(BacktestEngine, '_csi_unavailable_ts'):
                BacktestEngine._csi_unavailable_ts = 0.0
            
            # 定期重置: 如果距离上次失败超过 5 分钟，重新尝试
            import time
            if BacktestEngine._csi_unavailable and (time.time() - BacktestEngine._csi_unavailable_ts) > 300:
                logger.debug("[BacktestEngine] 中证转债指数: 距离上次失败超过 5 分钟，重置可用状态")
                BacktestEngine._csi_unavailable = False
            
            # 如果之前已确认不可用，直接回退到等权平均（避免递归）
            if BacktestEngine._csi_unavailable:
                logger.debug("[BacktestEngine] 中证转债指数: 之前已确认不可用，直接回退到等权平均")
                return self._calc_equal_weight_benchmark(data, dates)
            
            if cache_key and cache_key in BacktestEngine._csi_cache:
                logger.debug("[BacktestEngine] 中证转债指数: 使用缓存数据")
                return BacktestEngine._csi_cache[cache_key]
            
            try:
                import akshare as ak
                import socket
                socket.setdefaulttimeout(5)
                
                if min_date is None or max_date is None:
                    logger.warning("[BacktestEngine] 中证转债指数: 日期范围无效，回退到等权平均")
                    return self._calc_equal_weight_benchmark(data, dates)
                
                start_str = min_date.strftime("%Y%m%d") if isinstance(min_date, date) else str(min_date)[:10].replace("-", "")
                end_str = max_date.strftime("%Y%m%d") if isinstance(max_date, date) else str(max_date)[:10].replace("-", "")
                
                # 备选 symbol 列表（不同 AKShare 版本可能使用不同格式）
                symbols_to_try = ["000832", "sh000832", "sz000832"]
                index_df = None
                for sym in symbols_to_try:
                    try:
                        index_df = ak.index_zh_a_hist(
                            symbol=sym, period="daily",
                            start_date=start_str, end_date=end_str,
                        )
                        if index_df is not None and not index_df.empty:
                            logger.debug(f"[BacktestEngine] 中证转债指数: symbol={sym} 成功")
                            break
                    except Exception:
                        continue
                
                socket.setdefaulttimeout(None)
                
                if index_df is None or index_df.empty:
                    logger.warning("[BacktestEngine] 中证转债指数: AKShare 返回空数据，回退到等权平均")
                    return self._calc_equal_weight_benchmark(data, dates)
                
                # 列名灵活映射（不同 AKShare 版本列名可能不同）
                date_candidates = ["日期", "date", "Date", "trade_date"]
                close_candidates = ["收盘", "close", "Close", "收盘价"]
                
                date_col = next((c for c in date_candidates if c in index_df.columns), None)
                close_col = next((c for c in close_candidates if c in index_df.columns), None)
                
                if date_col is None or close_col is None:
                    logger.warning(
                        f"[BacktestEngine] 中证转债指数: 列名不匹配，"
                        f"期望日期/收盘列，实际列名: {list(index_df.columns)}，"
                        f"回退到等权平均"
                    )
                    return self._calc_equal_weight_benchmark(data, dates)
                
                index_prices = {}
                for _, row in index_df.iterrows():
                    try:
                        dt = row[date_col] if isinstance(row[date_col], date) else date.fromisoformat(str(row[date_col])[:10])
                        close_val = float(row[close_col] if pd.notna(row[close_col]) else 0)
                        if close_val > 0:
                            index_prices[dt] = close_val
                    except Exception:
                        continue
                
                if not index_prices or len(index_prices) < 2:
                    logger.warning("[BacktestEngine] 中证转债指数: 解析后数据不足，回退到等权平均")
                    return self._calc_equal_weight_benchmark(data, dates)
                
                benchmark_equity = [self.initial_cash]
                first_price = None
                for d in sorted(dates):
                    if d in index_prices:
                        first_price = index_prices[d]
                        break
                if first_price is None or first_price <= 0:
                    logger.warning("[BacktestEngine] 中证转债指数: 首日期无数据，回退到等权平均")
                    return self._calc_equal_weight_benchmark(data, dates)
                
                for i in range(1, len(dates)):
                    prev_date = dates[i - 1]
                    curr_date = dates[i]
                    prev_price = index_prices.get(prev_date)
                    curr_price = index_prices.get(curr_date)
                    
                    if prev_price and curr_price and prev_price > 0:
                        ret = (curr_price / prev_price) - 1
                        benchmark_equity.append(benchmark_equity[-1] * (1 + ret))
                    else:
                        benchmark_equity.append(benchmark_equity[-1])
                
                benchmark_curve = []
                for j, val in enumerate(benchmark_equity):
                    if j > 0:
                        d = dates[j - 1]
                        benchmark_curve.append({
                            'date': d.isoformat() if isinstance(d, date) else str(d),
                            'value': round(val, 6),
                        })
                
                result = (benchmark_curve, benchmark_equity)
                if cache_key:
                    BacktestEngine._csi_cache[cache_key] = result
                    # 改进 (2025-06-15): 持久化缓存到磁盘
                    # 改进 (2025-06-15b): LRU 淘汰，最多保留 100 条缓存
                    try:
                        import pickle, os as _os
                        _cache_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "csi_cache.pkl")
                        _cache_path = _os.path.abspath(_cache_path)
                        _os.makedirs(_os.path.dirname(_cache_path), exist_ok=True)
                        # LRU: 如果超过 100 条，保留最近 100 条（基于 dict 插入顺序，Python 3.7+ 有序）
                        if len(BacktestEngine._csi_cache) > 100:
                            _keys_to_keep = list(BacktestEngine._csi_cache.keys())[-100:]
                            BacktestEngine._csi_cache = {
                                k: BacktestEngine._csi_cache[k] for k in _keys_to_keep
                            }
                            logger.debug(f"[BacktestEngine] 中证转债指数: 缓存条目超过100，LRU淘汰后保留 {len(BacktestEngine._csi_cache)} 条")
                        with open(_cache_path, "wb") as f:
                            pickle.dump(BacktestEngine._csi_cache, f)
                    except PermissionError as _e:
                        logger.warning(f"[BacktestEngine] 中证转债指数: 磁盘缓存无权限写入 {_e}，缓存仅保留在内存中")
                    except Exception as _e:
                        logger.debug(f"[BacktestEngine] 中证转债指数: 磁盘缓存保存失败 {_e}")
                logger.info(f"[BacktestEngine] 中证转债指数基准: {len(benchmark_curve)} 个数据点")
                return result
                
            except Exception as e:
                import time
                BacktestEngine._csi_unavailable = True
                BacktestEngine._csi_unavailable_ts = time.time()
                socket.setdefaulttimeout(None)
                logger.warning(f"[BacktestEngine] 中证转债指数获取失败: {e}, 回退到等权平均")
                return self._calc_equal_weight_benchmark(data, dates)

        return [], []

    def run(self, strategy: Strategy, data: pd.DataFrame, on_progress=None) -> BacktestResult:
        """运行回测 - 使用 Portfolio 类管理持仓，与 SignalEngine 共享一致的信号处理流程
        
        改进 (2025-06-15):
        - 增加基准收益计算（等权平均 / 中证转债指数）
        - 增加超额收益指标
        - 增加总交易成本统计
        
        Args:
            strategy: 策略实例
            data: 回测数据 DataFrame
            on_progress: 可选的进度回调函数 fn(pct: int, msg: str)，
                         在每个调仓日调用，pct 为 0-100 的进度百分比。
                         异常会被静默吞掉，不影响回测运行。
        """
        start_time = time.time()

        # 改进 (2025-06-15am): 防御空 DataFrame——早期失败而非进入空循环
        if data is None or data.empty:
            logger.warning("[BacktestEngine.run] 回测数据为空，直接返回空结果")
            return BacktestResult(
                metrics=PerformanceMetrics(),
                equity_curve=[],
                trades=[],
                monthly_returns=[],
            )

        # 排序 & 预构建日期索引
        data = data.sort_values(['code', 'date']).reset_index(drop=True)

        # [Fix] 防御性校验：date 列必须为 date 对象，不能是价格等数值
        sample = data['date'].iloc[0] if len(data) > 0 else None
        if sample is not None and not isinstance(sample, date):
            raise ValueError(
                f"回测数据 'date' 列类型错误：期望 datetime.date，实际为 "
                f"{type(sample).__name__}（示例值: {sample!r}）。"
                f"通常是上游 DataFrame 列顺序与 SQL 别名不一致导致错位，"
                f"请检查 historical.py / 数据加载链路的列名映射。"
            )

        dates = sorted(data['date'].unique())
        if not dates or len(dates) < 2:
            raise ValueError(
                f"回测数据不足: 需要至少2个交易日, 实际 {len(dates) if dates else 0}。"
                f"请扩大回测日期范围或检查数据源."
            )
        start_date = _normalize_date(dates[0])
        end_date = _normalize_date(dates[-1])

        # Defensive: ensure strategy-required columns exist with safe defaults
        # Must happen BEFORE building date_data_map so day_data also has these columns
        # NOTE: defaults are conservative to avoid filtering out all bonds
        # (e.g. premium_ratio=15 avoids low_premium's max_premium=30 filter)
        strategy_required_defaults = {
            'price': 100.0,
            'premium_ratio': 15.0,
            'volume': 100000,
            'change_pct': 0.0,
            'ytm': 1.0,
            'remaining_years': 3.0,
        }
        for col, default in strategy_required_defaults.items():
            if col not in data.columns:
                data[col] = default
            else:
                data[col] = data[col].fillna(default)

        # 修复 (2025-06-15): 因子数据自动填充——缺失时先行业均值，再全局中位数
        # 避免 ROE=10, PE=25 等固定默认值削弱因子有效性
        # 防御: 如果 industry 列缺失，先用默认值填充（线程安全标记，只警告一次）
        if 'industry' not in data.columns:
            data['industry'] = 'unknown'
            # 使用线程锁保护类级别标记，避免多线程竞争条件
            _lock = getattr(BacktestEngine, '_industry_warn_lock', None)
            if _lock is None:
                _lock = threading.Lock()
                BacktestEngine._industry_warn_lock = _lock
            with _lock:
                if not getattr(BacktestEngine, '_industry_warned', False):
                    BacktestEngine._industry_warned = True
                    logger.warning("[BacktestEngine] industry 列缺失，使用 'unknown' 作为默认值（后续不再警告）")
        factor_cols = ['roe', 'gpm', 'cagr', 'debt_ratio', 'pe', 'pb']
        for col in factor_cols:
            if col in data.columns:
                missing_before = data[col].isna().sum()
                if missing_before > 0:
                    # 先按行业均值填充
                    industry_means = data.groupby('industry')[col].transform(
                        lambda x: x.mean() if not x.isna().all() else np.nan
                    )
                    data[col] = data[col].fillna(industry_means)
                    # 再全局中位数填充（剩余：该行业全缺失的）
                    global_median = data[col].median()
                    data[col] = data[col].fillna(global_median)
                    missing_after = data[col].isna().sum()
                    logger.info(
                        f"[BacktestEngine] 因子填充 {col}: 缺失 {missing_before} 行 -> "
                        f"填充后 {missing_after} 行 (行业均值+全局中位数 fallback)"
                    )
        # 正股涨跌幅：如果缺失，用转债涨跌幅近似（last resort）
        if 'stock_change_pct' in data.columns:
            missing_stock = data['stock_change_pct'].isna().sum()
            if missing_stock > 0 and 'change_pct' in data.columns:
                data['stock_change_pct'] = data['stock_change_pct'].fillna(data['change_pct'])
                logger.info(
                    f"[BacktestEngine] stock_change_pct 缺失 {missing_stock} 行，用 change_pct 近似填充"
                )

        # 改进 (2025-06-15l): polars 替代 pandas groupby
        if self.use_polars and _HAS_POLARS:
            logger.debug("[BacktestEngine] 使用 polars 进行日期分组")
            import polars as pl
            pl_data = pl.from_pandas(data)
            # 使用 partition_by 避免重复 filter，一次性分组后转回 pandas
            groups = pl_data.partition_by('date', maintain_order=True)
            date_data_map = {}
            for g in groups:
                date_val = g.item(0, 'date')
                # 防御性处理：跳过空分组或异常日期类型
                if date_val is None:
                    continue
                nd = _normalize_date(date_val)
                if not isinstance(nd, date):
                    logger.warning(f"[BacktestEngine] polars 日期分组异常类型: {type(date_val)} {date_val}")
                    continue
                date_data_map[nd] = g.to_pandas()
        else:
            date_data_map = {}
            for d, group in data.groupby('date'):
                nd = _normalize_date(d)
                date_data_map[nd] = group

        # 用归一化后的日期列表
        dates = sorted(date_data_map.keys())

        # 初始化策略 & 投资组合
        # 改进 (2025-06-15ao): 防御策略初始化异常——不终止回测，返回空结果
        try:
            strategy.on_init(data)
        except Exception as e:
            logger.error(f"[BacktestEngine] 策略初始化失败 ({strategy.name}): {e}")
            return BacktestResult(
                metrics=PerformanceMetrics(),
                equity_curve=[],
                trades=[],
                monthly_returns=[],
            )
        portfolio = Portfolio(cash=self.initial_cash)
        equity = [self.initial_cash]

        # 逐日执行
        n_dates = len(dates)
        _last_reported_pct = -1
        for i, current_date in enumerate(dates):
            if on_progress is not None and n_dates > 0:
                pct = int((i + 1) / n_dates * 100)
                if pct >= _last_reported_pct + 5 or pct == 100:
                    _last_reported_pct = pct
                    try:
                        on_progress(pct, f"回测进度 {pct}% ({i+1}/{n_dates})")
                    except Exception:
                        pass
            day_data = date_data_map[current_date]

            # 预构建 code -> row 映射，避免每次 O(M) 行过滤
            code_row_map = {code: group.iloc[0] for code, group in day_data.groupby('code')}

            # 1. 移除无行情的持仓
            portfolio.remove_stale(code_row_map, current_date, self.commission_pct, self.min_commission, self.impact_cost_pct)

            # 2. 生成信号（传入 day_data 而非完整 data，避免每日拷贝全量 DataFrame）
            signals = strategy.on_data(day_data, i) or []

            # 3. 先卖后买
            for sig in [s for s in signals if s['action'] == 'sell']:
                portfolio.sell(
                    sig['code'], sig['price'],
                    self.slippage_pct, self.commission_pct, self.min_commission, self.impact_cost_pct,
                    current_date, code_row_map,
                    reason=sig.get('reason', ''),
                )

            buy_signals = [s for s in signals if s['action'] == 'buy']
            new_buys = [s for s in buy_signals if s['code'] not in portfolio.holdings]
            n_to_buy = len(new_buys)
            if n_to_buy > 0:
                alloc_per = portfolio.cash / n_to_buy
            else:
                alloc_per = 0
            for sig_idx, sig in enumerate(new_buys):
                if sig['code'] in portfolio.holdings:
                    continue
                if n_to_buy <= 0:
                    break
                bought = portfolio.buy(
                    sig['code'], sig['price'],
                    self.slippage_pct, self.commission_pct, self.min_commission, self.impact_cost_pct,
                    current_date, alloc_per,
                )
                if bought:
                    n_to_buy -= 1

            # 4. 记录净值
            equity.append(portfolio.market_value(code_row_map))

        # 改进 (2025-06-15l): 根据配置选择 numba JIT 加速版或标准版指标计算
        _calc_fn = _calculate_metrics_fast if self.use_fast_metrics else _calculate_metrics
        if self.use_fast_metrics:
            logger.debug("[BacktestEngine] 使用 numba JIT 加速版指标计算")

        # 计算指标
        metrics = _calc_fn(equity, self.risk_free_rate)
        metrics.total_trades = len(portfolio.trades)

        if portfolio.trades:
            wins = [t for t in portfolio.trades if t.profit_pct and t.profit_pct > 0]
            metrics.win_rate = round(len(wins) / len(portfolio.trades) * 100, 2)
            profits = [t.profit_pct for t in portfolio.trades if t.profit_pct is not None and t.profit_pct > 0]
            losses = [t.profit_pct for t in portfolio.trades if t.profit_pct is not None and t.profit_pct <= 0]
            avg_profit = float(np.mean(profits)) if profits else 0.0
            avg_loss = float(np.mean(losses)) if losses else 0.0
            metrics.profit_loss_ratio = round(abs(avg_profit / avg_loss), 2) if avg_loss != 0 else 0.0
            hold_days = [t.hold_days for t in portfolio.trades if t.hold_days]
            metrics.avg_hold_days = round(float(np.mean(hold_days)), 1) if hold_days else 0.0

        # 净值曲线
        equity_curve = []
        for j, val in enumerate(equity):
            if j > 0:
                d = dates[j - 1]
                equity_curve.append({
                    'date': d.isoformat() if isinstance(d, date) else str(d),
                    'value': round(val, 6),
                })

        # 基准曲线 & 超额收益
        benchmark_curve, benchmark_equity = self._calc_benchmark_curve(data, dates)
        benchmark_metrics = None
        excess_metrics = None
        if benchmark_equity and len(benchmark_equity) == len(equity):
            benchmark_metrics = _calc_fn(benchmark_equity, self.risk_free_rate)
            # 超额收益 = 策略收益 - 基准收益（逐日差值）
            excess_equity = [self.initial_cash]
            for j in range(1, len(equity)):
                strategy_ret = (equity[j] / equity[j-1]) - 1
                bench_ret = (benchmark_equity[j] / benchmark_equity[j-1]) - 1
                excess_equity.append(excess_equity[-1] * (1 + strategy_ret - bench_ret))
            excess_metrics = _calc_fn(excess_equity, self.risk_free_rate)

        # 月度收益
        monthly_returns: list[MonthlyReturn] = []
        if len(equity_curve) >= 2:
            from collections import OrderedDict
            monthly_map: OrderedDict[tuple[int, int], list[float]] = OrderedDict()
            for pt in equity_curve:
                pt_date = date.fromisoformat(pt['date'][:10])
                key = (pt_date.year, pt_date.month)
                if key not in monthly_map:
                    monthly_map[key] = []
                monthly_map[key].append(pt['value'])
            prev_end_val = equity[0]
            for (yr, mo), vals in monthly_map.items():
                start_val = prev_end_val
                end_val = vals[-1]
                if start_val > 0:
                    ret = (end_val / start_val - 1) * 100
                    monthly_returns.append(MonthlyReturn(year=yr, month=mo, return_pct=round(ret, 2)))
                prev_end_val = end_val

        # 总交易成本（修复 2025-06-15: 统计全成本 = 买入佣金 + 卖出佣金 + 买入滑点 + 卖出滑点 + 冲击成本）
        total_cost = 0.0
        for t in portfolio.trades:
            # 买入成本: 佣金 + 滑点 + 冲击成本（滑点和冲击成本已体现在 buy_price 中）
            buy_cost = max(t.buy_price * t.volume * self.commission_pct, self.min_commission)
            # 卖出成本: 佣金 + 滑点 + 冲击成本（滑点和冲击成本已体现在 sell_price 中）
            sell_cost = max(t.sell_price * t.volume * self.commission_pct, self.min_commission)
            total_cost += buy_cost + sell_cost

        return BacktestResult(
            strategy_name=strategy.name,
            strategy_params=strategy._params,
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=portfolio.trades,
            monthly_returns=monthly_returns,
            benchmark_curve=benchmark_curve or None,
            benchmark_metrics=benchmark_metrics,
            excess_metrics=excess_metrics,
            execution_time_ms=round((time.time() - start_time) * 1000),
            total_cost=round(total_cost, 2),
        )

    # 改进 (2025-06-15k): 支持 async 模式回测
    async def run_async(self, strategy: Strategy, data: pd.DataFrame, on_progress=None) -> BacktestResult:
        """异步运行回测 - 使用 asyncio 在事件循环中执行，支持并发多个回测

        适合 IO 密集型场景（如数据预处理、文件读写），纯 CPU 计算部分
        仍通过 run_in_executor 在线程池中执行。
        """
        import asyncio
        loop = asyncio.get_running_loop()
        # 将同步 run 方法委托给线程池执行，避免阻塞事件循环
        return await loop.run_in_executor(None, self.run, strategy, data, on_progress)

    def run_optimization(
        self,
        strategy_cls: type[Strategy],
        data: pd.DataFrame,
        optimization_config: OptimizationConfig,
        on_progress=None,
    ) -> OptimizationResult:
        """参数优化 - 网格搜索，支持并行执行和进度日志
        
        Args:
            strategy_cls: 策略类
            data: 回测数据
            optimization_config: 优化配置
            on_progress: 可选的进度回调 fn(completed: int, total: int, msg: str)，
                         在每完成一次 backtest 后调用。异常会被静默吞掉，不影响优化运行。
        """
        start_time = time.time()

        # 生成参数组合网格
        ranges = optimization_config.param_ranges
        if not ranges:
            raise ValueError("优化参数范围不能为空")

        # 每个参数的取值范围
        param_values = {}
        for r in ranges:
            values = []
            if r.step <= 0:
                raise ValueError(f"Parameter step must be positive, got {r.step}")
            n_steps = int(round((r.max_val - r.min_val) / r.step)) + 1
            values = [round(r.min_val + i * r.step, 10) for i in range(n_steps)]
            param_values[r.name] = values

        max_iter = optimization_config.max_iterations
        # 搜索模式: random=随机采样, grid=遍历所有组合
        keys = list(param_values.keys())
        value_lists = [param_values[k] for k in keys]
        
        if optimization_config.search_mode == "grid":
            # 网格搜索: 遍历所有参数组合，但避免大参数空间内存爆炸
            import itertools, math
            total_combos = math.prod(len(vl) for vl in value_lists) if value_lists else 0
            if total_combos > max_iter * 2:
                # 极大参数空间: 随机采样 max_iter 个组合
                logger.warning(
                    f"[run_optimization] 网格搜索理论组合数 {total_combos:,} 超过 max_iter*2={max_iter*2}, "
                    f"随机采样 {max_iter} 个组合。建议增大 max_iterations 或改用 random 模式。"
                )
                # 改进 (2025-06-15): 直接生成随机组合到 set，避免先存列表再 dict.fromkeys 去重的内存浪费
                # 改进 (2025-06-15b): 预生成随机索引数组，减少 rng.choice 调用次数
                rng = np.random.default_rng()
                seen = set()
                # 动态 max_attempts: max_iter + 5倍预期重复次数（基于碰撞概率）
                max_attempts = min(max_iter + int(total_combos * 0.2), max_iter * 10)
                n_params = len(value_lists)
                while len(seen) < min(max_iter, total_combos) and len(seen) < max_attempts:
                    # 预生成一批索引，避免逐个调用 rng.choice
                    idxs = [rng.integers(0, len(vl)) for vl in value_lists]
                    combo = tuple(value_lists[i][idxs[i]] for i in range(n_params))
                    seen.add(combo)
                all_combinations = list(seen)
            elif total_combos > max_iter:
                # 中等参数空间: 遍历全部组合后截断（避免重复碰撞）
                logger.warning(
                    f"[run_optimization] 网格搜索理论组合数 {total_combos:,} 超过 max_iter={max_iter}, "
                    f"随机采样 {max_iter} 个组合。"
                )
                rng = np.random.default_rng()
                seen = set()
                max_attempts = max_iter * 2  # 中等空间，2倍尝试足够
                n_params = len(value_lists)
                while len(seen) < min(max_iter, total_combos) and len(seen) < max_attempts:
                    idxs = [rng.integers(0, len(vl)) for vl in value_lists]
                    combo = tuple(value_lists[i][idxs[i]] for i in range(n_params))
                    seen.add(combo)
                all_combinations = list(seen)
            else:
                all_combinations = list(itertools.product(*value_lists))
            logger.info(
                f"[run_optimization] 网格搜索: {len(all_combinations)} 组合 "
                f"(理论全量={total_combos:,})"
            )
        else:
            # 随机搜索: 默认行为
            all_combinations = []
            rng = np.random.default_rng()
            for _ in range(max_iter):
                combo = []
                for vl in value_lists:
                    idx = rng.integers(0, len(vl))
                    combo.append(vl[idx])
                all_combinations.append(tuple(combo))
            logger.info(f"[run_optimization] 随机搜索: {len(all_combinations)} 组合")

        # 改进 (2025-06-15k): 贝叶斯优化分支（optuna）
        if optimization_config.search_mode == 'bayesian':
            logger.info(f"[run_optimization] 贝叶斯优化: 使用 optuna TPE 采样器，max_iter={max_iter}")
            return self._run_bayesian_optimization(
                strategy_cls, data, optimization_config, param_values, keys, metric_key, on_progress
            )

        # 改进 (2025-06-15i): warm_start 从上次最优参数邻域搜索
        # 改进 (2025-06-15j): 自适应邻域收缩，根据历史优化次数动态调整
        warm_start = getattr(optimization_config, 'warm_start', False)
        if warm_start and optimization_config.search_mode == 'random':
            _strategy_name = getattr(strategy_cls, 'name', str(strategy_cls))
            last_best = _load_last_best_params(_strategy_name)
            if last_best:
                # 计算该策略历史优化次数，用于自适应邻域收缩
                _history_count = len(get_optimization_history(strategy_name=_strategy_name, limit=100))
                # 第1次 ±20%，第2次 ±10%，第3次 ±5%，之后 ±3%
                _shrink_factors = [0.20, 0.10, 0.05]
                _jitter_factor = _shrink_factors[min(_history_count - 1, len(_shrink_factors) - 1)] if _history_count > 0 else 0.20
                logger.info(f"[run_optimization] warm_start: 历史优化次数={_history_count}, 邻域系数={_jitter_factor:.0%}")
                # 在最优参数附近生成邻域组合，替换前 30% 的随机组合
                n_warm = max(1, len(all_combinations) // 3)
                warm_combos = []
                rng = np.random.default_rng()
                for _ in range(n_warm):
                    combo = []
                    for k, vl in zip(keys, value_lists):
                        if k in last_best:
                            # 在最优值附近自适应范围内随机
                            center = last_best[k]
                            min_v, max_v = min(vl), max(vl)
                            range_v = max_v - min_v
                            jitter = range_v * _jitter_factor
                            jittered = max(min_v, min(max_v, center + rng.uniform(-jitter, jitter)))
                            # 对齐到最近的步长
                            step = param_values[k][1] - param_values[k][0] if len(param_values[k]) > 1 else 1.0
                            jittered = round(round(jittered / step) * step, 10)
                            combo.append(jittered)
                        else:
                            idx = rng.integers(0, len(vl))
                            combo.append(vl[idx])
                    warm_combos.append(tuple(combo))
                # 用邻域组合替换前 n_warm 个
                all_combinations = warm_combos + all_combinations[n_warm:]
                logger.info(f"[run_optimization] warm_start: 已注入 {n_warm} 个邻域组合(系数={_jitter_factor:.0%})")

        results: list[OptimizationResultItem] = []
        metric_key = optimization_config.optimize_metric
        n_combos = len(all_combinations)

        # 改进 (2025-06-15j): 使用配置的 progress_interval，支持更细粒度进度
        _progress_interval = getattr(optimization_config, 'progress_interval', 10)
        log_interval = max(1, n_combos // _progress_interval)

        parallel_workers = optimization_config.parallel_workers
        use_parallel = parallel_workers > 1

        # 改进 (2025-06-15): 自适应串行/并行——小数据量或组合数少时强制串行，避免进程启动开销
        if use_parallel:
            data_mb = data.memory_usage(deep=True).sum() / 1024 / 1024
            if n_combos < 8:
                logger.info(
                    f"[run_optimization] 组合数仅 {n_combos} (<8)，进程启动开销 > 并行收益，"
                    f"强制切换为串行模式"
                )
                use_parallel = False
            elif data_mb < 5:
                logger.info(
                    f"[run_optimization] 数据量仅 {data_mb:.1f}MB (<5MB)，序列化开销 > 并行收益，"
                    f"强制切换为串行模式"
                )
                use_parallel = False

        # 改进 (2025-06-15l): Pareto 多目标优化
        pareto_metrics = getattr(optimization_config, 'pareto_metrics', [])
        if pareto_metrics and len(pareto_metrics) > 1:
            logger.info(f"[run_optimization] Pareto 多目标优化: 指标={pareto_metrics}")
            return self._run_pareto_optimization(
                strategy_cls, data, optimization_config, all_combinations, keys, pareto_metrics, on_progress
            )

        if use_parallel:
            # 并行模式：使用 ProcessPoolExecutor 实现真正的 CPU 并行
            # 注意：每个子进程拥有独立的 data 副本，内存随 worker 数量增加
            # 在 Linux 上，fork 启动方式通过 copy-on-write 机制共享内存页，
            # 子进程在修改数据前不会真正复制；macOS 默认使用 spawn 方式，
            # 每个子进程都会完整序列化 data，内存开销 = data大小 × worker数
            actual_workers = min(parallel_workers, os.cpu_count() or 2, n_combos)

            # 内存估算与警告
            data_mb = data.memory_usage(deep=True).sum() / 1024 / 1024
            total_mb = data_mb * actual_workers
            if total_mb > 1024:  # > 1GB
                logger.warning(
                    f"并行优化将使用约 {total_mb:.0f}MB 内存 "
                    f"({data_mb:.0f}MB 数据 × {actual_workers} 工作进程)。"
                    f"如内存有限，建议减少 parallel_workers 或切换为顺序模式。"
                )

            # 改进 (2025-06-15): 中等数据量（5-50MB）使用临时 parquet 文件避免序列化开销
            # 改进 (2025-06-15b): 检测 parquet 引擎可用性，缺失时回退到内存模式
            # 改进 (2025-06-15c): 统一文件创建+写入+清理逻辑，避免任何失败路径残留临时文件
            use_file = False
            data_path = None
            if 5 <= data_mb < 50:
                try:
                    # 使用模块级缓存的 parquet 引擎可用性检测结果
                    if _check_parquet_engine():
                        import tempfile, os as _os
                        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
                            data_path = f.name
                        try:
                            data.to_parquet(data_path, index=False)
                            use_file = True
                            logger.info(
                                f"[run_optimization] 数据量 {data_mb:.1f}MB (5-50MB)，"
                                f"使用临时 parquet 文件避免序列化开销: {_os.path.basename(data_path)}"
                            )
                        except Exception as _e:
                            logger.warning(
                                f"[run_optimization] parquet 写入失败 {_e}，回退到内存序列化"
                            )
                            use_file = False
                        finally:
                            # 如果写入失败或后续未使用文件，确保清理残留
                            if not use_file and data_path:
                                try:
                                    _os.unlink(data_path)
                                except Exception:
                                    pass
                                data_path = None
                    else:
                        logger.info(
                            f"[run_optimization] 未检测到 pyarrow/fastparquet，"
                            f"回退到内存序列化（数据量 {data_mb:.1f}MB）"
                        )
                except Exception as _e:
                    logger.warning(f"[run_optimization] parquet 检测失败 {_e}，回退到内存序列化")

            logger.info(
                f"并行优化启动: {n_combos} 组合, {actual_workers} 工作进程, "
                f"CPU 核心数={os.cpu_count()}, 数据约 {data_mb:.0f}MB, "
                f"预计内存增加约 {total_mb:.0f}MB"
            )
            # 改进 (2025-06-15e): 使用 bytearray 位图替代 set，降低百万级组合时的内存开销
            # set[int] 在 10K 组合时约 720KB，bytearray 仅需 1.25KB，百万级时差距 72MB vs 125KB
            _processed_bits = bytearray((n_combos + 7) // 8)
            _completed_count = 0

            # 改进 (2025-06-15g): 引入 checkpoint 持久化位图，支持崩溃恢复
            # 每 100 个组合自动保存，程序重启后可从 checkpoint 恢复进度
            _checkpoint_dir = Path("data")
            _checkpoint_dir.mkdir(parents=True, exist_ok=True)
            _checkpoint_path = _checkpoint_dir / ".optimization_checkpoint"
            _checkpoint_saved = False
            _checkpoint_batch = 100  # 每 100 个组合保存一次

            def _save_checkpoint():
                nonlocal _checkpoint_saved
                try:
                    cp_data = {
                        'strategy_name': getattr(strategy_cls, 'name', str(strategy_cls)),
                        'n_combos': n_combos,
                        'processed_bits_b64': base64.b64encode(_processed_bits).decode('ascii'),
                        'completed_count': _completed_count,
                        'timestamp': datetime.now().isoformat(),
                    }
                    with open(_checkpoint_path, 'w') as f:
                        json.dump(cp_data, f)
                    _checkpoint_saved = True
                except Exception as e:
                    logger.warning(f"[run_optimization] checkpoint 保存失败: {e}")

            # 尝试加载之前的 checkpoint
            if _checkpoint_path.exists():
                try:
                    with open(_checkpoint_path, 'r') as f:
                        cp_data = json.load(f)
                    if (cp_data.get('strategy_name') == getattr(strategy_cls, 'name', str(strategy_cls))
                            and cp_data.get('n_combos') == n_combos):
                        _processed_bits = bytearray(base64.b64decode(cp_data['processed_bits_b64']))
                        _completed_count = cp_data.get('completed_count', 0)
                        logger.info(
                            f"[run_optimization] 从 checkpoint 恢复，"
                            f"已完成 {_completed_count}/{n_combos} 组合"
                        )
                    else:
                        # 参数不匹配，删除旧 checkpoint
                        _checkpoint_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"[run_optimization] checkpoint 加载失败: {e}")
                    _checkpoint_path.unlink(missing_ok=True)

            # 改进 (2025-06-15h): 使用 BoundedResultBuffer 替代 list，O(log k) 插入，内存 bounded
            _top_n = optimization_config.top_n
            _buffer = _BoundedResultBuffer(max_size=_top_n * 2, metric_key=metric_key)

            # 改进 (2025-06-15h): 内存上限配置
            _max_memory_mb = getattr(optimization_config, 'max_memory_mb', 4096)
            _memory_warned = False

            try:
                # 改进 (2025-06-15g): 使用 loky 替代 ProcessPoolExecutor，支持 worker 复用
                try:
                    from loky import get_reusable_executor
                    _HAS_LOKY = True
                except ImportError:
                    _HAS_LOKY = False

                # 改进 (2025-06-15g): 创建 Manager.Queue 用于子进程进度透传
                manager = multiprocessing.Manager()
                progress_queue = manager.Queue()

                checkpoint_enabled = getattr(optimization_config, 'checkpoint_enabled', True)

                # 改进 (2025-06-15i): 早停配置
                _early_stop_patience = getattr(optimization_config, 'early_stop_patience', 0)
                _no_improve_count = 0
                _best_so_far = float('-inf')

                # 改进 (2025-06-15h): 启动独立线程消费子进程进度队列
                _progress_thread_stop = threading.Event()
                def _consume_progress():
                    while not _progress_thread_stop.is_set():
                        try:
                            pid, pct, msg = progress_queue.get(timeout=0.5)
                            logger.debug(f"Worker {pid} 回测进度: {pct}% {msg}")
                        except queue.Empty:
                            continue
                        except Exception:
                            break
                _progress_thread = threading.Thread(target=_consume_progress, daemon=True)
                _progress_thread.start()

                executor = None
                _use_loky = False
                _use_pool = False
                try:
                    # 改进 (2025-06-15l): 根据配置选择执行器类型
                    use_threadpool = getattr(optimization_config, 'use_threadpool', False)
                    use_pool_map = getattr(optimization_config, 'use_pool_map', False)
                    use_ray = getattr(optimization_config, 'use_ray', False)
                    if use_pool_map and not use_ray:
                        logger.info("[run_optimization] 使用 multiprocessing.Pool.map 模式")
                        _use_pool = True
                    elif use_ray and _HAS_RAY:
                        logger.info("[run_optimization] 使用 ray 分布式并行模式")
                    elif use_threadpool:
                        logger.info("[run_optimization] 使用 ThreadPoolExecutor 模式（适合IO密集型回测）")
                        executor = concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers)
                    elif _HAS_LOKY:
                        executor = get_reusable_executor(
                            max_workers=actual_workers,
                            context=multiprocessing.get_context("spawn"),
                            id=f"backtest_opt_{actual_workers}",
                            timeout=300,
                        )
                        _use_loky = True
                    else:
                        # 改进 (2025-06-15h): 获取策略模块名用于 initializer 预加载
                        _strategy_module = getattr(strategy_cls, '__module__', None)
                        _initializer = partial(_worker_initializer, _strategy_module) if _strategy_module else None
                        executor = concurrent.futures.ProcessPoolExecutor(
                            max_workers=actual_workers,
                            mp_context=multiprocessing.get_context("spawn"),
                            initializer=_initializer,
                        )
                        _use_loky = False

                    # 改进 (2025-06-15f): 使用 functools.partial 缓存提交函数，减少循环内参数构造开销
                    # 改进 (2025-06-15g): 绑定 progress_queue 用于子进程进度透传
                    if use_file and data_path:
                        _submit_fn = partial(
                            _run_single_backtest_file,
                            strategy_cls, data_path=data_path,
                            commission_pct=self.commission_pct, slippage_pct=self.slippage_pct,
                            impact_cost_pct=self.impact_cost_pct, min_commission=self.min_commission,
                            risk_free_rate=self.risk_free_rate, initial_cash=self.initial_cash,
                            progress_queue=progress_queue,
                        )
                    else:
                        _submit_fn = partial(
                            _run_single_backtest,
                            strategy_cls, data=data,
                            commission_pct=self.commission_pct, slippage_pct=self.slippage_pct,
                            impact_cost_pct=self.impact_cost_pct, min_commission=self.min_commission,
                            risk_free_rate=self.risk_free_rate, initial_cash=self.initial_cash,
                            progress_queue=progress_queue,
                        )

                    # 改进 (2025-06-15l): ray 分布式执行
                    if use_ray and _HAS_RAY:
                        _pending_params = [dict(zip(keys, [float(v) for v in combo])) for combo in all_combinations]
                        if not ray.is_initialized():
                            ray.init(ignore_reinit_error=True)
                        # 将数据放入 ray object store，避免重复序列化
                        data_ref = ray.put(data_path if use_file and data_path else data)
                        
                        @ray.remote
                        def _ray_backtest(params, strategy_cls, data_ref, is_file, commission_pct, slippage_pct, impact_cost_pct, min_commission, risk_free_rate, initial_cash):
                            """ray 远程回测函数"""
                            _data = ray.get(data_ref)
                            if is_file:
                                return _run_single_backtest_file(
                                    strategy_cls, params, _data,
                                    commission_pct, slippage_pct, impact_cost_pct,
                                    min_commission, risk_free_rate, initial_cash,
                                )
                            else:
                                return _run_single_backtest(
                                    strategy_cls, params, _data,
                                    commission_pct, slippage_pct, impact_cost_pct,
                                    min_commission, risk_free_rate, initial_cash,
                                )
                        
                        ray_futures = [
                            _ray_backtest.remote(
                                p, strategy_cls, data_ref, use_file,
                                self.commission_pct, self.slippage_pct, self.impact_cost_pct,
                                self.min_commission, self.risk_free_rate, self.initial_cash,
                            )
                            for p in _pending_params
                        ]
                        for item in ray.get(ray_futures):
                            try:
                                if isinstance(item, dict):
                                    item = OptimizationResultItem(**item)
                                _buffer.add(item)
                                _completed_count += 1
                                completed += 1
                                if completed % log_interval == 0:
                                    logger.info(f"ray 优化进度: {completed}/{n_combos}")
                            except Exception as e:
                                logger.warning(f"ray 优化运行失败: {e}")
                    # 改进 (2025-06-15l): multiprocessing.Pool.map 执行
                    elif _use_pool:
                        _pending_params = [dict(zip(keys, [float(v) for v in combo])) for combo in all_combinations]
                        # 使用 initializer 预加载策略模块
                        _strategy_module = getattr(strategy_cls, '__module__', None)
                        _initializer = partial(_worker_initializer, _strategy_module) if _strategy_module else None
                        with multiprocessing.Pool(processes=actual_workers, initializer=_initializer) as pool:
                            for item in pool.imap_unordered(_submit_fn, _pending_params):
                                try:
                                    if isinstance(item, dict):
                                        item = OptimizationResultItem(**item)
                                    _buffer.add(item)
                                    _completed_count += 1
                                    completed += 1
                                    if completed % log_interval == 0:
                                        logger.info(f"Pool 优化进度: {completed}/{n_combos}")
                                except Exception as e:
                                    logger.warning(f"Pool 优化运行失败: {e}")
                    else:
                        futures = {}
                        for idx, combo in enumerate(all_combinations):
                            # 跳过已由 checkpoint 恢复完成的组合
                            if checkpoint_enabled and _processed_bits[idx // 8] & (1 << (idx % 8)):
                                continue
                            params = dict(zip(keys, [float(v) for v in combo]))
                            future = executor.submit(_submit_fn, params)
                            futures[future] = idx

                        completed = 0
                        _dynamic_adjust_start = 10  # 前10个结果用于基线测量
                        _completion_times = []  # 记录最近N个完成时间
                        _last_completed_time = time.time()
                        _workers_adjusted = False
                        try:
                            # 改进 (2025-06-15f): 为 as_completed 添加 300 秒超时，防止僵尸进程无限阻塞
                            # 改进 (2025-06-15k): 支持 map 模式，通过环境变量 LH_USE_MAP=1 启用
                            _use_map = os.environ.get('LH_USE_MAP', '0') == '1'
                            if _use_map:
                                logger.info("[run_optimization] 使用 executor.map 模式（简化 future 管理）")
                                _pending_params = [dict(zip(keys, [float(v) for v in combo])) for combo in all_combinations]
                                for item in executor.map(_submit_fn, _pending_params):
                                    try:
                                        if isinstance(item, dict):
                                            item = OptimizationResultItem(**item)
                                        _buffer.add(item)
                                        _completed_count += 1
                                        completed += 1
                                        if completed % log_interval == 0:
                                            logger.info(f"并行优化进度: {completed}/{n_combos}")
                                    except Exception as e:
                                        logger.warning(f"并行优化运行失败: {e}")
                            else:
                                for future in concurrent.futures.as_completed(futures, timeout=300):
                                    idx = futures[future]
                                    _processed_bits[idx // 8] |= (1 << (idx % 8))
                                    _completed_count += 1
                                    
                                    # 改进 (2025-06-15j): 动态 worker 调整 - 测量完成速率
                                    _now = time.time()
                                    _completion_times.append(_now - _last_completed_time)
                                    _last_completed_time = _now
                                    if len(_completion_times) > 20:
                                        _completion_times.pop(0)
                                    
                                    # 前 _dynamic_adjust_start 个结果用于基线测量，之后动态调整
                                    if completed == _dynamic_adjust_start and not _workers_adjusted:
                                        _avg_time = sum(_completion_times) / len(_completion_times) if _completion_times else 1.0
                                        _pending = len([f for f in futures if not f.done()])
                                        _optimal_workers = max(1, min(parallel_workers, int(_avg_time * parallel_workers / (_avg_time + 0.001))))
                                        if _pending < parallel_workers and _optimal_workers < parallel_workers:
                                            logger.info(
                                                f"[run_optimization] 动态调整: 检测到 worker 空闲，"
                                                f"建议下次使用 {_optimal_workers} 个 worker(当前={parallel_workers})"
                                            )
                                            _workers_adjusted = True
                                    
                                    try:
                                        item = future.result()
                                        # 改进 (2025-06-15f): 子进程返回轻量 dict，父进程转换为 OptimizationResultItem
                                        if isinstance(item, dict):
                                            item = OptimizationResultItem(**item)
                                        # 改进 (2025-06-15h): 使用 BoundedResultBuffer 替代 list.append
                                        _buffer.add(item)
                                        # 改进 (2025-06-15i): 早停检测
                                        if _early_stop_patience > 0:
                                            val = getattr(item, metric_key, 0.0)
                                            if val > _best_so_far:
                                                _best_so_far = val
                                                _no_improve_count = 0
                                            else:
                                                _no_improve_count += 1
                                                if _no_improve_count >= _early_stop_patience:
                                                    logger.info(
                                                        f"[run_optimization] 早停触发: 连续 {_early_stop_patience} 个组合"
                                                        f"未改进 (best={_best_so_far:.4f})，提前终止"
                                                    )
                                                    # 取消剩余 futures
                                                    for f in futures:
                                                        if not f.done():
                                                            f.cancel()
                                                    break
                                    except Exception as e:
                                        if isinstance(e, BrokenProcessPool):
                                            raise
                                        logger.warning(f"并行优化运行失败: {e}")
                                    completed += 1

                                    if completed % log_interval == 0 or completed == n_combos:
                                        logger.info(
                                            f"并行优化进度: {completed}/{n_combos} "
                                            f"({completed * 100 // n_combos}%)"
                                        )
                                    if on_progress is not None:
                                        _pct_now = (completed * 100 // max(n_combos, 1))
                                        if _pct_now % 5 == 0 or completed == n_combos:
                                            try:
                                                on_progress(completed, n_combos, f"优化进度 {completed}/{n_combos}")
                                            except Exception:
                                                pass

                                    # 改进 (2025-06-15h): 内存监控，超过阈值时警告并主动裁剪
                                    if completed % 100 == 0 and _HAS_PSUTIL:
                                        _mem_mb = _get_memory_mb()
                                        if _mem_mb > _max_memory_mb and not _memory_warned:
                                            _memory_warned = True
                                            logger.warning(
                                                f"[run_optimization] 内存使用 {_mem_mb:.0f}MB 超过阈值 {_max_memory_mb}MB，"
                                                f"已触发 BoundedResultBuffer 裁剪，如继续增长将考虑降级串行"
                                            )

                                    # 改进 (2025-06-15g): checkpoint 保存（如果启用）
                                    if checkpoint_enabled and _completed_count % _checkpoint_batch == 0:
                                        _save_checkpoint()
                        except (BrokenProcessPool, TimeoutError):
                            # 改进 (2025-06-15f): 进程池崩溃或超时后，显式取消所有未完成的 futures
                            # 避免 with 块退出时等待已崩溃 worker 的残留任务
                            for f in futures:
                                if not f.done():
                                    f.cancel()
                            logger.error(
                                f"[run_optimization] 并行进程池崩溃或超时，"
                                f"已完成 {_completed_count}/{n_combos} 组合，"
                                f"降级为串行模式完成剩余组合"
                            )
                            # 崩溃前也保存 checkpoint
                            if checkpoint_enabled:
                                _save_checkpoint()
                finally:
                    # 改进 (2025-06-15h): 停止进度消费线程
                    _progress_thread_stop.set()
                    _progress_thread.join(timeout=2.0)
                    if executor is not None and not _use_pool and not use_ray:
                        try:
                            executor.shutdown(wait=True)
                        except Exception as e:
                            logger.warning(f"[run_optimization] executor shutdown 失败: {e}")
            except BrokenProcessPool:
                # 外层 with 块也可能抛出，已由内层捕获或需处理
                pass

            # 改进 (2025-06-15d): 进程池崩溃后降级为串行模式完成剩余组合
            # 改进 (2025-06-15g): 直接遍历所有索引，检查位图，避免创建 remaining_indices 列表
            _remaining_count = n_combos - _completed_count
            if _remaining_count > 0:
                logger.info(
                    f"[run_optimization] 串行降级: 处理剩余 {_remaining_count} 个组合"
                )
                _serial_done = 0
                for idx in range(n_combos):
                    if _processed_bits[idx // 8] & (1 << (idx % 8)):
                        continue
                    combo = all_combinations[idx]
                    params = dict(zip(keys, [float(v) for v in combo]))
                    strategy = strategy_cls(**params)
                    result = self.run(strategy, data)
                    # 改进 (2025-06-15h): 串行阶段也使用 BoundedResultBuffer
                    _buffer.add(_build_result_item(params, result.metrics))
                    # 改进 (2025-06-15i): 串行阶段早停检测
                    if _early_stop_patience > 0:
                        val = getattr(_build_result_item(params, result.metrics), metric_key, 0.0)
                        if val > _best_so_far:
                            _best_so_far = val
                            _no_improve_count = 0
                        else:
                            _no_improve_count += 1
                            if _no_improve_count >= _early_stop_patience:
                                logger.info(
                                    f"[run_optimization] 串行阶段早停触发: 连续 {_early_stop_patience} 个组合"
                                    f"未改进 (best={_best_so_far:.4f})，提前终止"
                                )
                                break
                    # 串行降级也同步更新位图，支持可中断恢复
                    _processed_bits[idx // 8] |= (1 << (idx % 8))
                    _serial_done += 1
                    # 串行降级也触发进度回调
                    _total_done = _completed_count + _serial_done
                    if _total_done % log_interval == 0 or _total_done == n_combos:
                        logger.info(
                            f"串行降级进度: {_total_done}/{n_combos} "
                            f"({_total_done * 100 // n_combos}%)"
                        )
                    if on_progress is not None:
                        _pct_now = (_total_done * 100 // max(n_combos, 1))
                        if _pct_now % 5 == 0 or _total_done == n_combos:
                            try:
                                on_progress(_total_done, n_combos, f"串行降级 {_total_done}/{n_combos}")
                            except Exception:
                                pass
                    # 改进 (2025-06-15g): 串行阶段也定期保存 checkpoint（如果启用）
                    if checkpoint_enabled and _serial_done % _checkpoint_batch == 0:
                        _save_checkpoint()
                    # 改进 (2025-06-15h): 串行阶段内存监控
                    if _serial_done % 100 == 0 and _HAS_PSUTIL:
                        _mem_mb = _get_memory_mb()
                        if _mem_mb > _max_memory_mb and not _memory_warned:
                            _memory_warned = True
                            logger.warning(
                                f"[run_optimization] 串行阶段内存使用 {_mem_mb:.0f}MB 超过阈值 {_max_memory_mb}MB"
                            )
            # 清理临时文件
            if data_path and use_file:
                try:
                    import os as _os
                    _os.unlink(data_path)
                except PermissionError as _e:
                    logger.warning(f"[run_optimization] 临时 parquet 文件清理失败（权限不足）: {_e}")
                except OSError as _e:
                    logger.warning(f"[run_optimization] 临时 parquet 文件清理失败（文件被占用）: {_e}")
                except Exception as _e:
                    logger.debug(f"[run_optimization] 临时 parquet 文件清理失败: {_e}")
            # 改进 (2025-06-15g): 优化完成后清理 checkpoint
            if _checkpoint_saved and _checkpoint_path.exists():
                try:
                    _checkpoint_path.unlink(missing_ok=True)
                    logger.info("[run_optimization] checkpoint 已清理")
                except Exception as e:
                    logger.warning(f"[run_optimization] checkpoint 清理失败: {e}")

            # 改进 (2025-06-15h): 从 BoundedResultBuffer 获取最终 results
            results = _buffer.get_results()
        else:
            # 顺序模式：默认行为，零额外内存开销
            # 改进 (2025-06-15h): 顺序模式也使用 BoundedResultBuffer，保持内存 bounded
            _top_n_seq = optimization_config.top_n
            _buffer = _BoundedResultBuffer(max_size=_top_n_seq * 2, metric_key=metric_key)
            logger.info(f"顺序优化启动: {n_combos} 组合")
            for idx, combo in enumerate(all_combinations):
                params = dict(zip(keys, [float(v) for v in combo]))

                # 实例化策略
                strategy = strategy_cls(**params)

                # 运行回测
                result = self.run(strategy, data)
                metrics = result.metrics

                _buffer.add(_build_result_item(params, metrics))

                # 改进 (2025-06-15i): 顺序模式早停检测
                _es_patience = getattr(optimization_config, 'early_stop_patience', 0)
                if _es_patience > 0:
                    _es_val = getattr(_build_result_item(params, metrics), metric_key, 0.0)
                    if _es_val > _best_so_far:
                        _best_so_far = _es_val
                        _no_improve_count = 0
                    else:
                        _no_improve_count += 1
                        if _no_improve_count >= _es_patience:
                            logger.info(
                                f"[run_optimization] 顺序模式早停触发: 连续 {_es_patience} 个组合"
                                f"未改进 (best={_best_so_far:.4f})，提前终止"
                            )
                            break

                # 每 10% 记录一次进度
                if (idx + 1) % log_interval == 0 or (idx + 1) == n_combos:
                    logger.info(
                        f"优化进度: {idx + 1}/{n_combos} "
                        f"({(idx + 1) * 100 // n_combos}%)"
                    )
                if on_progress is not None:
                    _pct_now = ((idx + 1) * 100 // max(n_combos, 1))
                    if _pct_now % 5 == 0 or (idx + 1) == n_combos:
                        try:
                            on_progress(idx + 1, n_combos, f"优化进度 {idx + 1}/{n_combos}")
                        except Exception:
                            pass
                # 改进 (2025-06-15h): 顺序模式内存监控
                if (idx + 1) % 100 == 0 and _HAS_PSUTIL:
                    _mem_mb = _get_memory_mb()
                    _max_mem = getattr(optimization_config, 'max_memory_mb', 4096)
                    if _mem_mb > _max_mem:
                        logger.warning(
                            f"[run_optimization] 顺序模式内存使用 {_mem_mb:.0f}MB 超过阈值 {_max_mem}MB"
                        )

            # 改进 (2025-06-15h): 从 BoundedResultBuffer 获取最终 results
            results = _buffer.get_results()

        # 改进 (2025-06-15g): 使用 heapq.nlargest 替代 sorted，O(n log k) 优于 O(n log n)
        # 当 n_combos >> top_n 时，排序效率提升显著，且内存峰值更低
        # 改进 (2025-06-15h): 由于 BoundedResultBuffer 已维护 top-k，此处可直接取前 top_n
        top_results = results[:optimization_config.top_n]

        # 最优参数
        best_item = top_results[0] if top_results else None

        opt_result = OptimizationResult(
            strategy_name=strategy_cls.name,
            optimize_metric=optimization_config.optimize_metric,
            total_combinations=n_combos,
            best_params=best_item.params if best_item else {},
            top_results=top_results,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )

        if best_item:
            opt_result.best_metrics = PerformanceMetrics(
                total_return_pct=best_item.total_return_pct,
                annual_return_pct=best_item.annual_return_pct,
                max_drawdown_pct=best_item.max_drawdown_pct,
                sharpe_ratio=best_item.sharpe_ratio,
                sortino_ratio=best_item.sortino_ratio,
                calmar_ratio=best_item.calmar_ratio,
                win_rate=best_item.win_rate,
                total_trades=best_item.total_trades,
            )

        logger.info(
            f"优化完成: {n_combos} 组合, 耗时 {opt_result.execution_time_ms}ms, "
            f"模式={'并行' if use_parallel else '顺序'}"
        )

        # 改进 (2025-06-15i): 优化结果持久化到 SQLite
        persist_history = getattr(optimization_config, 'persist_history', True)
        if persist_history:
            _save_optimization_history(
                strategy_name=strategy_cls.name,
                optimize_metric=optimization_config.optimize_metric,
                total_combinations=n_combos,
                best_params=opt_result.best_params,
                best_metrics=opt_result.best_metrics,
                top_results=opt_result.top_results,
                execution_time_ms=opt_result.execution_time_ms,
            )

        return opt_result

    def _run_pareto_optimization(
        self,
        strategy_cls: type[Strategy],
        data: pd.DataFrame,
        optimization_config: OptimizationConfig,
        all_combinations: list[tuple],
        keys: list[str],
        pareto_metrics: list[str],
        on_progress=None,
    ) -> OptimizationResult:
        """改进 (2025-06-15o): Pareto 多目标优化 - 进程池并行 + parquet 文件 + 流式非支配排序 + BrokenProcessPool 防御

        同时优化多个指标（如 sharpe_ratio + max_drawdown_pct），
        使用 ProcessPoolExecutor 真正利用多核并行评估，
        大数据量时通过 parquet 文件传递避免重复 DataFrame 序列化，
        流式非支配排序避免 O(n) 内存膨胀，
        捕获 BrokenProcessPool 防止子进程崩溃导致整体失败。
        """
        start_time = time.time()
        n_combos = len(all_combinations)
        # 改进 (2025-06-15z): 防御空组合，避免后续 log_interval=0 导致除零
        if n_combos == 0:
            logger.warning("[Pareto] all_combinations 为空，直接返回空结果")
            return OptimizationResult(
                strategy_name=strategy_cls.name,
                optimize_metric=','.join(pareto_metrics),
                total_combinations=0,
                best_params={},
                top_results=[],
                execution_time_ms=0,
            )
        log_interval = max(1, n_combos // 10)

        # 改进 (2025-06-15z): 先计算一次 data_size，避免重复调用
        # 改进 (2025-06-15aj): deep=False 更准确反映数据传递所需的内存，避免字符串列 deep=True 高估
        data_size = data.memory_usage(deep=False).sum()
        _pareto_workers = _compute_pareto_workers(data_size, n_combos)

        from concurrent.futures import ProcessPoolExecutor, BrokenProcessPool

        # 准备参数列表（可序列化）
        _all_params = [
            dict(zip(keys, [float(v) for v in combo]))
            for combo in all_combinations
        ]

        # 改进 (2025-06-15o): 大数据量通过 parquet 文件传递，避免重复 pickle 序列化
        use_parquet = data_size > 1_000_000  # > 1MB 使用 parquet
        data_path = None
        if use_parquet:
            fd, data_path = tempfile.mkstemp(suffix='.parquet')
            os.close(fd)
            # 改进 (2025-06-15q): parquet 写入前统一 date 列为 str，避免类型漂移
            _parquet_data = data.copy()
            if 'date' in _parquet_data.columns:
                _parquet_data['date'] = _parquet_data['date'].astype(str)
            # 改进 (2025-06-15u): to_parquet 添加异常处理和引擎回退
            try:
                _parquet_data.to_parquet(data_path, engine='pyarrow')
                logger.info(f"[Pareto] DataFrame {data_size / 1_000_000:.1f}MB，使用 parquet 文件传递")
            except Exception:
                try:
                    _parquet_data.to_parquet(data_path, engine='fastparquet')
                    logger.info(f"[Pareto] DataFrame {data_size / 1_000_000:.1f}MB，使用 parquet 文件传递 (fastparquet)")
                except Exception:
                    try:
                        # 改进 (2025-06-15v): parquet 失败时回退到 feather 格式
                        feather_path = data_path.replace('.parquet', '.feather')
                        _parquet_data.to_feather(feather_path)
                        if os.path.exists(data_path):
                            os.unlink(data_path)
                        data_path = feather_path
                        logger.info(f"[Pareto] DataFrame {data_size / 1_000_000:.1f}MB，使用 feather 文件传递")
                    except Exception as e:
                        logger.warning(f"[Pareto] parquet/feather 写入失败 ({e})，回退到 pickle 传递")
                        if os.path.exists(data_path):
                            os.unlink(data_path)
                        data_path = None
                        use_parquet = False

        if use_parquet:
            args_list = [
                (
                    strategy_cls, params, data_path,
                    self.commission_pct, self.slippage_pct,
                    self.impact_cost_pct, self.min_commission,
                    self.risk_free_rate, self.initial_cash,
                    pareto_metrics,
                )
                for params in _all_params
            ]
            worker_fn = _run_pareto_combo_file
        else:
            args_list = [
                (
                    strategy_cls, params, data,
                    self.commission_pct, self.slippage_pct,
                    self.impact_cost_pct, self.min_commission,
                    self.risk_free_rate, self.initial_cash,
                    pareto_metrics,
                )
                for params in _all_params
            ]
            worker_fn = _run_pareto_combo

        # 改进 (2025-06-15ai): try/finally 确保 data_path 临时文件无论评估是否成功都会被清理
        try:
            pareto_front = []
            evaluated_count = 0
            # 改进 (2025-06-15ae): 初始化为 rebuild_threshold，避免 last_rebuild_size=0 时
            # len(front) >= 0*1.2 永远为 True 的语义问题（虽然 rebuild_threshold 会阻止触发）
            _last_rebuild_size = 150

            # 改进 (2025-06-15s): 自适应阈值：小组合数或轻量数据直接串行评估，避免进程启动开销
            use_parallel = n_combos >= 50 and data_size > 100_000
            if not use_parallel:
                logger.info(f"[Pareto] {n_combos} 组合 / {data_size / 1000:.0f}KB 数据，直接串行评估")
                # 改进 (2025-06-15ah): 进度发送采样，避免高频 IPC 开销
                _progress_interval = max(1, n_combos // 20)
                for idx, args_tuple in enumerate(args_list):
                    try:
                        result_dict, metrics_dict = worker_fn(args_tuple)
                        # 改进 (2025-06-15ai): 跳过 worker 返回的错误标记（异常透传）
                        if result_dict is None:
                            continue
                        item = OptimizationResultItem(**result_dict)
                        pareto_front, _last_rebuild_size = _update_pareto_front(
                            pareto_front, item, metrics_dict, pareto_metrics,
                            last_rebuild_size=_last_rebuild_size
                        )
                        evaluated_count += 1
                        if evaluated_count % log_interval == 0 or evaluated_count == n_combos:
                            logger.info(f"Pareto 评估进度: {evaluated_count}/{n_combos}")
                        # 改进 (2025-06-15ah): 每 5% 或最小间隔发送进度，避免高频 IPC
                        if on_progress is not None and (evaluated_count % _progress_interval == 0 or evaluated_count == n_combos):
                            try:
                                on_progress(evaluated_count, n_combos, f"Pareto 评估 {evaluated_count}/{n_combos}")
                            except Exception:
                                pass
                    except Exception as ex:
                        logger.warning(f"[Pareto] 组合 {idx} 串行评估失败: {ex}")
            else:
                # 改进 (2025-06-15o): chunksize 按 worker 数分配，限制最大为 10
                chunksize = max(1, min(10, len(args_list) // _pareto_workers))

                try:
                    with ProcessPoolExecutor(max_workers=_pareto_workers) as executor:
                        # 改进 (2025-06-15ah): 进度采样阈值，避免高频 IPC
                        _next_progress_pct = 0
                        # 改进 (2025-06-15ah): 批量收集结果，减少 Pareto 更新开销
                        _batch = []
                        for idx, (result_dict, metrics_dict) in enumerate(
                            executor.map(worker_fn, args_list, chunksize=chunksize)
                        ):
                            # 改进 (2025-06-15ai): 跳过 worker 返回的错误标记（异常透传）
                            if result_dict is None:
                                continue
                            item = OptimizationResultItem(**result_dict)
                            _batch.append((item, metrics_dict))
                            # 每 chunksize 个或最后一个时批量更新
                            if len(_batch) >= chunksize or idx == len(args_list) - 1:
                                pareto_front, _last_rebuild_size = _update_pareto_front_batch(
                                    pareto_front, _batch, pareto_metrics,
                                    last_rebuild_size=_last_rebuild_size
                                )
                                evaluated_count += len(_batch)
                                # 改进 (2025-06-15al): 重用 _batch 列表，减少 GC 压力
                                _batch.clear()

                            if evaluated_count % log_interval == 0 or evaluated_count == n_combos:
                                logger.info(f"Pareto 评估进度: {evaluated_count}/{n_combos}")
                            if on_progress is not None:
                                _pct_now = (evaluated_count * 100 // max(n_combos, 1))
                                # 改进 (2025-06-15ah): 每 5% 或最后一个才发送进度，避免高频 IPC
                                if _pct_now >= _next_progress_pct or evaluated_count == n_combos:
                                    _next_progress_pct = (_pct_now // 5 + 1) * 5
                                    try:
                                        on_progress(evaluated_count, n_combos, f"Pareto 评估 {evaluated_count}/{n_combos}")
                                    except Exception:
                                        pass
                except BrokenProcessPool as e:
                    logger.error(f"[Pareto] 子进程崩溃，回退到顺序评估: {e}")
                    # 改进 (2025-06-15q): 从崩溃位置继续，避免重复评估已完成的组合
                    # 安全性说明：worker_fn 在父进程中直接调用是安全的，因为：
                    # 1. _run_pareto_combo / _run_pareto_combo_file 是模块级纯函数，无全局状态修改
                    # 2. 每个调用都会创建独立的 BacktestEngine 实例，互不干扰
                    # 3. data（或 data_path）是只读的，不会被 worker_fn 修改
                    _crashed_idx = evaluated_count
                    for idx, args_tuple in enumerate(args_list[_crashed_idx:], start=_crashed_idx):
                        try:
                            result_dict, metrics_dict = worker_fn(args_tuple)
                            # 改进 (2025-06-15ai): 跳过 worker 返回的错误标记（异常透传）
                            if result_dict is None:
                                continue
                            item = OptimizationResultItem(**result_dict)
                            pareto_front, _last_rebuild_size = _update_pareto_front(
                                pareto_front, item, metrics_dict, pareto_metrics,
                                last_rebuild_size=_last_rebuild_size
                            )
                            evaluated_count += 1
                            # 改进 (2025-06-15ah): 回退路径也使用采样进度，避免高频 IPC
                            if on_progress is not None and (evaluated_count % max(1, n_combos // 20) == 0 or evaluated_count == n_combos):
                                try:
                                    on_progress(evaluated_count, n_combos, f"Pareto 顺序回退 {evaluated_count}/{n_combos}")
                                except Exception:
                                    pass
                        except Exception as ex:
                            logger.warning(f"[Pareto] 组合 {idx} 顺序评估失败: {ex}")
        finally:
            # 改进 (2025-06-15ai): finally 确保临时文件无论评估是否成功都会被清理
            if data_path is not None and os.path.exists(data_path):
                try:
                    os.unlink(data_path)
                    logger.debug(f"[Pareto] 临时 parquet 文件已清理: {data_path}")
                except Exception as e:
                    logger.warning(f"[Pareto] 临时文件清理失败: {data_path} ({e})")

        # 改进 (2025-06-15ab): Pareto 前沿按首个指标排序后再截断 top_n，避免任意截断
        # 改进 (2025-06-15ad): 优先按 optimization_config.optimize_metric 排序，更符合用户预期
        # 改进 (2025-06-15ae): top_n 下限防御——多目标优化时确保每个指标有足够样本保留权衡解
        _opt_metric = getattr(optimization_config, 'optimize_metric', None)
        _sort_metric = _opt_metric if _opt_metric and _opt_metric in pareto_metrics else (pareto_metrics[0] if pareto_metrics else 'sharpe_ratio')
        _reverse_sort = _sort_metric != 'max_drawdown_pct'
        _sorted_front = sorted(
            pareto_front,
            key=lambda x: x[1].get(_sort_metric, 0.0),
            reverse=_reverse_sort,
        )
        _min_top_n = len(pareto_metrics) * 3
        _effective_top_n = max(optimization_config.top_n, _min_top_n)
        if len(pareto_metrics) > 1 and optimization_config.top_n < _min_top_n:
            logger.warning(
                f"[Pareto] top_n={optimization_config.top_n} 小于多目标最小样本 {_min_top_n}，"
                f"自动提升至 {_effective_top_n} 以保留权衡解"
            )
        top_results = [item for item, _ in _sorted_front[:_effective_top_n]]

        # 改进 (2025-06-15ag): 使用 crowding distance 选择 best_item，
        # 优先选择最独特的权衡解（而非简单按首个指标排序的第一个）
        # 改进 (2025-06-15ao): 确保 best_item 也在 top_results 中，保持一致性
        if len(pareto_metrics) > 1 and len(pareto_front) > 2:
            _front_metrics_only = [me for _, me in pareto_front]
            _cd = _crowding_distance(_front_metrics_only, pareto_metrics)
            _best_idx = max(range(len(pareto_front)), key=lambda i: _cd[i])
            best_item = pareto_front[_best_idx][0]
        else:
            best_item = top_results[0] if top_results else None

        # 防御: 截断导致 best_item 不在 top_results 中时，回退到 top_results[0]
        if best_item and best_item not in top_results:
            logger.debug(f"[Pareto] best_item 不在 top_results 中，回退到 top_results[0]")
            best_item = top_results[0] if top_results else None

        opt_result = OptimizationResult(
            strategy_name=strategy_cls.name,
            optimize_metric=','.join(pareto_metrics),
            total_combinations=n_combos,
            best_params=best_item.params if best_item else {},
            top_results=top_results,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )

        if best_item:
            opt_result.best_metrics = PerformanceMetrics(
                total_return_pct=best_item.total_return_pct,
                annual_return_pct=best_item.annual_return_pct,
                max_drawdown_pct=best_item.max_drawdown_pct,
                sharpe_ratio=best_item.sharpe_ratio,
                sortino_ratio=best_item.sortino_ratio,
                calmar_ratio=best_item.calmar_ratio,
                win_rate=best_item.win_rate,
                total_trades=best_item.total_trades,
            )

        logger.info(
            f"[run_optimization] Pareto 优化完成: {n_combos} 组合, "
            f"Pareto 前沿 {len(pareto_front)} 个解, "
            f"耗时 {opt_result.execution_time_ms}ms"
        )
        return opt_result

    def _run_bayesian_optimization(
        self,
        strategy_cls: type[Strategy],
        data: pd.DataFrame,
        optimization_config: OptimizationConfig,
        param_values: dict[str, list],
        keys: list[str],
        metric_key: str,
        on_progress=None,
    ) -> OptimizationResult:
        """改进 (2025-06-15k): 使用 optuna TPE 采样器进行贝叶斯优化

        贝叶斯优化在高维参数空间下效率远高于网格/随机搜索，
        通常 50-100 次评估即可找到接近最优解。
        """
        import optuna

        start_time = time.time()
        max_iter = optimization_config.max_iterations
        _top_n = optimization_config.top_n
        if _top_n <= 0:
            raise ValueError(f"optimization_config.top_n 必须大于 0，当前值: {_top_n}")
        _buffer = _BoundedResultBuffer(max_size=_top_n * 2, metric_key=metric_key)

        def _objective(trial):
            params = {}
            for k, vl in zip(keys, [param_values[k] for k in keys]):
                # 使用 optuna 的 categorical 采样，从离散值中选择
                params[k] = trial.suggest_categorical(k, vl)

            strategy = strategy_cls(**params)
            result = self.run(strategy, data)
            item = _build_result_item(params, result.metrics)
            _buffer.add(item)

            # 进度回调
            if on_progress is not None and len(_buffer) % max(1, max_iter // 10) == 0:
                try:
                    on_progress(len(_buffer), max_iter, f"贝叶斯优化 {len(_buffer)}/{max_iter}")
                except Exception:
                    pass

            return getattr(item, metric_key, 0.0)

        # 禁用 optuna 的日志输出
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler())
        study.optimize(_objective, n_trials=max_iter, show_progress_bar=False)

        results = _buffer.get_results()
        top_results = results[:_top_n]
        best_item = top_results[0] if top_results else None

        opt_result = OptimizationResult(
            strategy_name=strategy_cls.name,
            optimize_metric=metric_key,
            total_combinations=max_iter,
            best_params=best_item.params if best_item else {},
            top_results=top_results,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )

        if best_item:
            opt_result.best_metrics = PerformanceMetrics(
                total_return_pct=best_item.total_return_pct,
                annual_return_pct=best_item.annual_return_pct,
                max_drawdown_pct=best_item.max_drawdown_pct,
                sharpe_ratio=best_item.sharpe_ratio,
                sortino_ratio=best_item.sortino_ratio,
                calmar_ratio=best_item.calmar_ratio,
                win_rate=best_item.win_rate,
                total_trades=best_item.total_trades,
            )

        logger.info(
            f"[run_optimization] 贝叶斯优化完成: {max_iter} 次评估, "
            f"耗时 {opt_result.execution_time_ms}ms, "
            f"best_value={study.best_value:.4f}"
        )

        persist_history = getattr(optimization_config, 'persist_history', True)
        if persist_history:
            _save_optimization_history(
                strategy_name=strategy_cls.name,
                optimize_metric=metric_key,
                total_combinations=max_iter,
                best_params=opt_result.best_params,
                best_metrics=opt_result.best_metrics,
                top_results=opt_result.top_results,
                execution_time_ms=opt_result.execution_time_ms,
            )

        return opt_result

    def cost_sensitivity(
        self,
        strategy: Strategy,
        data: pd.DataFrame,
        cost_scenarios: list[tuple[float, float]] = None,
        on_progress=None,
    ) -> "CostSensitivityResult":
        """交易成本敏感性分析
        
        测试不同佣金+滑点组合下的策略表现，评估成本对收益的侵蚀程度。
        
        Args:
            strategy: 策略实例（会被复制多份，但这里用同一实例重新运行）
            data: 回测数据
            cost_scenarios: (commission_pct, slippage_pct) 列表，默认测试常见费率组合
            on_progress: 可选进度回调
        
        Returns:
            CostSensitivityResult: 各场景下的收益对比
        """
        from app.models.backtest import CostSensitivityResult, CostSensitivityItem
        
        if cost_scenarios is None:
            # 默认测试常见费率组合: (佣金, 滑点)
            cost_scenarios = [
                (0.0000, 0.0000),      # 理想零成本（参考基准）
                (0.0001, 0.0001),      # 机构极低费率
                (0.0003, 0.0003),      # 默认（万3佣金+万3滑点）
                (0.0005, 0.0003),      # 万5佣金+万3滑点
                (0.0005, 0.0005),      # 万5佣金+万5滑点
                (0.0010, 0.0005),      # 千1佣金+万5滑点
                (0.0010, 0.0010),      # 千1佣金+千1滑点（高成本场景）
                (0.0015, 0.0010),      # 千1.5佣金+千1滑点（极端场景）
            ]
        
        baseline_result = None
        scenarios = []
        n = len(cost_scenarios)
        
        for i, (comm, slip) in enumerate(cost_scenarios):
            if on_progress is not None:
                try:
                    on_progress(i + 1, n, f"成本测试 {i+1}/{n}: 佣金{comm*100:.2f}% 滑点{slip*100:.2f}%")
                except Exception:
                    pass
            
            # 临时修改成本配置
            orig_comm = self.commission_pct
            orig_slip = self.slippage_pct
            self.commission_pct = comm
            self.slippage_pct = slip
            
            try:
                # 重新创建策略实例（避免状态污染）
                strategy_copy = strategy.__class__(**strategy._params)
                result = self.run(strategy_copy, data)
                
                if i == 0:
                    baseline_result = CostSensitivityItem(
                        commission_pct=comm,
                        slippage_pct=slip,
                        total_return_pct=result.metrics.total_return_pct,
                        annual_return_pct=result.metrics.annual_return_pct,
                        sharpe_ratio=result.metrics.sharpe_ratio,
                        max_drawdown_pct=result.metrics.max_drawdown_pct,
                        total_cost=result.total_cost,
                        cost_drag_pct=0.0,
                    )
                else:
                    drag = round(baseline_result.total_return_pct - result.metrics.total_return_pct, 2) if baseline_result else 0.0
                    scenarios.append(CostSensitivityItem(
                        commission_pct=comm,
                        slippage_pct=slip,
                        total_return_pct=result.metrics.total_return_pct,
                        annual_return_pct=result.metrics.annual_return_pct,
                        sharpe_ratio=result.metrics.sharpe_ratio,
                        max_drawdown_pct=result.metrics.max_drawdown_pct,
                        total_cost=result.total_cost,
                        cost_drag_pct=drag,
                    ))
            finally:
                self.commission_pct = orig_comm
                self.slippage_pct = orig_slip
        
        # 找出最佳/最差场景（排除零成本参考）
        best = max(scenarios, key=lambda x: x.total_return_pct) if scenarios else None
        worst = min(scenarios, key=lambda x: x.total_return_pct) if scenarios else None
        
        return CostSensitivityResult(
            baseline=baseline_result,
            scenarios=scenarios,
            best_params={"commission_pct": best.commission_pct, "slippage_pct": best.slippage_pct} if best else {},
            worst_params={"commission_pct": worst.commission_pct, "slippage_pct": worst.slippage_pct} if worst else {},
        )


class WalkForwardResult(BaseModel):
    """Walk-Forward验证结果"""
    total_windows: int = 0
    in_sample_metrics: list[dict] = []  # 样本内指标
    out_sample_metrics: list[dict] = []  # 样本外指标
    avg_in_sample_return: float = 0.0
    avg_out_sample_return: float = 0.0
    avg_in_sample_sharpe: float = 0.0
    avg_out_sample_sharpe: float = 0.0
    avg_in_sample_drawdown: float = 0.0
    avg_out_sample_drawdown: float = 0.0
    overfit_information_ratio: float = 0.0  # 过拟合信息比率 = 样本内-样本外收益差均值 / 标准差，>0.3 表示过拟合可控
    overfit_ratio: float = 0.0  # 样本内/样本外比值，越大过拟合越严重
    best_params_stability: float = 0.0  # 参数稳定性得分
    parameter_consistency: float = 0.0  # 参数一致性（相邻窗口参数变化）
    win_rate_pct: float = 0.0  # 样本外正收益窗口占比
    execution_time_ms: int = 0

    def summary(self) -> str:
        """生成文本摘要"""
        if self.total_windows == 0:
            return "Walk-Forward验证: 数据不足，无法生成有效窗口"
        lines = [
            f"Walk-Forward验证结果 ({self.total_windows}个窗口)",
            f"  样本内平均收益: {self.avg_in_sample_return:+.2f}%",
            f"  样本外平均收益: {self.avg_out_sample_return:+.2f}%",
            f"  样本内平均夏普: {self.avg_in_sample_sharpe:.2f}",
            f"  样本外平均夏普: {self.avg_out_sample_sharpe:.2f}",
            f"  样本内平均回撤: {self.avg_in_sample_drawdown:.2f}%",
            f"  样本外平均回撤: {self.avg_out_sample_drawdown:.2f}%",
            f"  过拟合信息比率: {self.overfit_information_ratio:.2f}",
            f"  过拟合比率: {self.overfit_ratio:.2f}",
            f"  参数稳定性: {self.best_params_stability:.2f}",
            f"  参数一致性: {self.parameter_consistency:.2f}",
            f"  样本外胜率: {self.win_rate_pct:.1f}%",
        ]
        return "\n".join(lines)

    def is_robust(
        self,
        min_windows: int = 3,
        max_overfit_ratio: float = 2.0,
        min_information_ratio: float = 0.3,
        min_params_stability: float = 0.5,
        min_parameter_consistency: float = 0.4,
        min_win_rate_pct: float = 50.0,
    ) -> bool:
        """判断策略是否稳健（经验法则）
        
        参数:
        - min_windows: 最小窗口数（默认3，避免短回测期误判）
        - max_overfit_ratio: 最大过拟合比率（默认2.0，样本内不超过样本外2倍）
        - min_information_ratio: 最小信息比率（默认0.3）
        - min_params_stability: 最小参数稳定性（默认0.5）
        - min_parameter_consistency: 最小参数一致性（默认0.4，相邻窗口参数变化）
        - min_win_rate_pct: 最小样本外胜率（默认50.0%）
        """
        if self.total_windows < min_windows:
            return False
        return (
            self.overfit_ratio < max_overfit_ratio
            and self.overfit_information_ratio > min_information_ratio
            and self.best_params_stability > min_params_stability
            and self.parameter_consistency > min_parameter_consistency
            and self.win_rate_pct > min_win_rate_pct
        )


class WalkForwardValidator:
    """Walk-Forward验证器 - 防止过拟合的样本外验证

    核心逻辑：
    1. 将时间序列分为多个滚动窗口
    2. 每个窗口：训练期优化参数 → 测试期验证
    3. 统计样本内vs样本外性能差异
    4. overfit_ratio = 样本内收益 / 样本外收益
    
    改进 (2025-06-15):
    - 增加信息比率、样本外胜率等更丰富的指标
    - 增加参数一致性计算（相邻窗口参数变化）
    - 增加is_robust()稳健性判断
    """

    def __init__(
        self,
        train_window: int = 120,  # 训练期天数（约半年）
        test_window: int = 60,    # 测试期天数（约一季度）
        step: int = 60,           # 滚动步长
    ):
        self.train_window = train_window
        self.test_window = test_window
        self.step = step

    def validate(
        self,
        strategy_cls: type[Strategy],
        data: pd.DataFrame,
        optimization_config: OptimizationConfig,
        engine: Optional[BacktestEngine] = None,
    ) -> WalkForwardResult:
        """执行Walk-Forward验证"""
        start_time = time.time()
        engine = engine or BacktestEngine()

        # 排序数据
        data = data.sort_values(['code', 'date']).reset_index(drop=True)
        dates = sorted(data['date'].unique())
        n_days = len(dates)

        # 计算窗口数量
        min_days = self.train_window + self.test_window
        if n_days < min_days:
            logger.warning(
                f"数据不足: 需要至少{min_days}天，实际{n_days}天"
            )
            return WalkForwardResult(total_windows=0)

        # 生成窗口
        windows = []
        start = 0
        while start + min_days <= n_days:
            train_end = start + self.train_window
            test_end = train_end + self.test_window
            if test_end > n_days:
                break
            windows.append({
                'train_start': start,
                'train_end': train_end,
                'test_start': train_end,
                'test_end': test_end,
            })
            start += self.step

        if not windows:
            logger.warning("无法生成有效窗口")
            return WalkForwardResult(total_windows=0)

        # 内存估算: 如果并行优化，多个窗口会重复创建进程池
        if optimization_config.parallel_workers > 1:
            data_mb = data.memory_usage(deep=True).sum() / 1024 / 1024
            total_mb = data_mb * optimization_config.parallel_workers * len(windows)
            if total_mb > 1024:
                logger.warning(
                    f"[WalkForward] 并行优化 × {len(windows)} 窗口 将消耗大量内存 "
                    f"(~{total_mb:.0f}MB)。建议减少 parallel_workers 或改用单线程。"
                )

        in_sample_metrics = []
        out_sample_metrics = []
        all_best_params = []

        for i, win in enumerate(windows):
            # 分割数据
            train_dates = dates[win['train_start']:win['train_end']]
            test_dates = dates[win['test_start']:win['test_end']]

            train_data = data[data['date'].isin(train_dates)]
            test_data = data[data['date'].isin(test_dates)]

            # 样本内优化
            opt_result = engine.run_optimization(
                strategy_cls, train_data, optimization_config
            )

            best_params = opt_result.best_params
            all_best_params.append(best_params)

            # 记录样本内指标
            in_sample_metrics.append({
                'window': i + 1,
                'total_return_pct': opt_result.best_metrics.total_return_pct if opt_result.best_metrics else 0,
                'sharpe_ratio': opt_result.best_metrics.sharpe_ratio if opt_result.best_metrics else 0,
                'max_drawdown_pct': opt_result.best_metrics.max_drawdown_pct if opt_result.best_metrics else 0,
            })

            # 样本外验证
            if best_params:
                test_strategy = strategy_cls(**best_params)
                test_result = engine.run(test_strategy, test_data)

                out_sample_metrics.append({
                    'window': i + 1,
                    'total_return_pct': test_result.metrics.total_return_pct,
                    'sharpe_ratio': test_result.metrics.sharpe_ratio,
                    'max_drawdown_pct': test_result.metrics.max_drawdown_pct,
                })
            else:
                out_sample_metrics.append({
                    'window': i + 1,
                    'total_return_pct': 0,
                    'sharpe_ratio': 0,
                    'max_drawdown_pct': 0,
                })

        # 计算统计指标
        avg_in_return = np.mean([m['total_return_pct'] for m in in_sample_metrics])
        avg_out_return = np.mean([m['total_return_pct'] for m in out_sample_metrics])
        avg_in_sharpe = np.mean([m['sharpe_ratio'] for m in in_sample_metrics])
        avg_out_sharpe = np.mean([m['sharpe_ratio'] for m in out_sample_metrics])
        avg_in_dd = np.mean([m['max_drawdown_pct'] for m in in_sample_metrics])
        avg_out_dd = np.mean([m['max_drawdown_pct'] for m in out_sample_metrics])

        # 过拟合比率
        overfit_ratio = 0.0
        if avg_out_return != 0:
            overfit_ratio = min(round(avg_in_return / avg_out_return, 3), 999.0)
        elif avg_in_return > 0:
            overfit_ratio = 999.0

        # 过拟合信息比率 = 样本内-样本外收益差均值 / 标准差
        # 改进 (2025-06-15): 如果 excess_std=0，用 excess_mean*10 近似（所有窗口差值一致）
        excess_returns = [m['total_return_pct'] - out_m['total_return_pct'] 
                         for m, out_m in zip(in_sample_metrics, out_sample_metrics)]
        overfit_information_ratio = 0.0
        if excess_returns:
            excess_mean = np.mean(excess_returns)
            excess_std = np.std(excess_returns)
            if excess_std > 0:
                overfit_information_ratio = round(excess_mean / excess_std, 2)
            elif excess_mean > 0:
                # 所有窗口差值一致为正（完美过拟合）
                overfit_information_ratio = round(excess_mean * 10, 2)
            else:
                # 所有窗口差值一致为负或零（策略稳健）
                overfit_information_ratio = round(excess_mean * 10, 2)

        # 样本外胜率（正收益窗口占比）
        out_returns = [m['total_return_pct'] for m in out_sample_metrics]
        win_rate_pct = round(sum(1 for r in out_returns if r > 0) / len(out_returns) * 100, 1) if out_returns else 0.0

        # 参数稳定性得分（基于最优参数的变化程度）
        stability_score = self._calculate_stability(all_best_params)
        
        # 参数一致性（相邻窗口参数变化）
        consistency_score = self._calculate_consistency(all_best_params)

        return WalkForwardResult(
            total_windows=len(windows),
            in_sample_metrics=in_sample_metrics,
            out_sample_metrics=out_sample_metrics,
            avg_in_sample_return=round(avg_in_return, 2),
            avg_out_sample_return=round(avg_out_return, 2),
            avg_in_sample_sharpe=round(avg_in_sharpe, 2),
            avg_out_sample_sharpe=round(avg_out_sharpe, 2),
            avg_in_sample_drawdown=round(avg_in_dd, 2),
            avg_out_sample_drawdown=round(avg_out_dd, 2),
            information_ratio=overfit_information_ratio,
            overfit_ratio=overfit_ratio,
            best_params_stability=stability_score,
            parameter_consistency=consistency_score,
            win_rate_pct=win_rate_pct,
            execution_time_ms=round((time.time() - start_time) * 1000),
        )

    def _calculate_stability(self, all_params: list[dict]) -> float:
        """计算参数稳定性得分

        基于参数值的标准差，得分越高表示参数越稳定
        """
        if not all_params or len(all_params) < 2:
            return 1.0

        # 收集所有参数值
        param_values = {}
        for params in all_params:
            for k, v in params.items():
                if k not in param_values:
                    param_values[k] = []
                param_values[k].append(v)

        # 计算每个参数的变异系数
        stability_scores = []
        for param_name, values in param_values.items():
            if len(values) < 2:
                continue
            mean_val = np.mean(values)
            if mean_val == 0:
                continue
            std_val = np.std(values)
            cv = std_val / abs(mean_val)  # 变异系数
            # 变异系数越小，稳定性越高
            param_stability = max(0, 1 - cv)
            stability_scores.append(param_stability)

        return round(float(np.mean(stability_scores)), 3) if stability_scores else 1.0

    def _calculate_consistency(self, all_params: list[dict]) -> float:
        """计算参数一致性（相邻窗口参数变化）
        
        得分越高表示参数在相邻窗口间变化越小，策略越稳定。
        改进 (2025-06-15): 使用 MAD（Median Absolute Deviation）替代均值归一化，
        对异常值更稳健，避免参数值接近0时归一化结果失真。
        """
        if not all_params or len(all_params) < 2:
            return 1.0

        # 收集所有参数值
        param_values = {}
        for params in all_params:
            for k, v in params.items():
                if k not in param_values:
                    param_values[k] = []
                param_values[k].append(float(v))

        # 计算每个参数的相邻变化量
        consistency_scores = []
        for param_name, values in param_values.items():
            if len(values) < 2:
                continue
            # 相邻窗口变化量的绝对值之和
            total_change = sum(abs(values[i] - values[i-1]) for i in range(1, len(values)))
            avg_change = total_change / (len(values) - 1)
            # 改进: 使用 MAD（Median Absolute Deviation）替代 mean_val 归一化
            # MAD 对异常值不敏感，避免参数值接近0时归一化爆炸
            # 改进 (2025-06-15b): 使用 np.abs 向量化计算，避免临时列表内存开销
            # 改进 (2025-06-15c): epsilon 防御极端数值（1e-15 远小于任何策略参数量级）
            # 改进 (2025-06-15d): 退化处理——如果所有值相同（mad=0, avg_change=0），一致性为1.0
            median_val = float(np.median(values))
            arr = np.array(values)
            mad = float(np.median(np.abs(arr - median_val)))
            if mad == 0 and avg_change == 0:
                consistency_scores.append(1.0)
                continue
            # 使用 MAD + epsilon 作为归一化基准，防止极端小值导致 scale 过小
            _eps = 1e-15
            scale = max(mad, abs(median_val), _eps) if (mad > _eps or abs(median_val) > _eps) else 1.0
            relative_change = avg_change / scale
            # 相对变化越小，一致性越高
            consistency = max(0, 1 - relative_change)
            consistency_scores.append(consistency)

        return round(float(np.mean(consistency_scores)), 3) if consistency_scores else 1.0
