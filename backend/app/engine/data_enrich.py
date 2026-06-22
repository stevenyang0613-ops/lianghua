"""
可转债数据增强模块
从多个数据源补充转债的行业/评级/基本面等字段，
单次增量刷新，长时间缓存，失败不阻塞。
"""
import asyncio
import json
import logging
import math
import re
import os
import sys
import threading
import time
import traceback
import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import akshare as ak
import numpy as np
from app.adapters.tdx_adapter import get_tdx_adapter
from app.models.convertible import RATING_SCORE_MAP, RATING_SCORE_DEFAULT
from app.engine.data_enrich_utils import (
    load_cache as _load_cache_impl, save_cache as _save_cache_impl, fresh as _fresh_impl,
    safe_float as _sf_impl, record_refresh_metric, load_refresh_metrics,
    _lock_file_path, _acquire_file_lock,
)

logger = logging.getLogger(__name__)

# 保护所有全局缓存映射的写入（多线程后台刷新 vs 异步 enrich_quotes 读）
_cache_lock = threading.RLock()

_CACHE_DIR = Path(os.environ.get("HOME", ".")) / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_INDUSTRY_CACHE_TTL = 86400 * 7
_SPOT_CACHE_TTL = 300
_FIN_CACHE_TTL = 3600 * 24
_FUND_FLOW_CACHE_TTL = 300
_DEBT_CACHE_TTL = 3600 * 24
_VOL_CACHE_TTL = 3600 * 24
_MGMT_CACHE_TTL = 3600 * 24

_PLEDGE_CACHE_TTL = 3600 * 24
_MOMENTUM_CACHE_TTL = 86400
_EVENT_CACHE_TTL = 3600 * 24
_CONCEPT_CACHE_TTL = 86400 * 7
_BUYBACK_CACHE_TTL = 86400 * 3
_BOND_OUTSTANDING_CACHE_TTL = 3600 * 24
_CALL_STATUS_CACHE_TTL = 3600 * 24

_INDUSTRY_CACHE = _CACHE_DIR / "stock_industry.json"
_SPOT_CACHE = _CACHE_DIR / "stock_spot.json"
_FIN_CACHE = _CACHE_DIR / "stock_fin.json"
_FUND_FLOW_CACHE = _CACHE_DIR / "stock_fund_flow.json"
_DEBT_CACHE = _CACHE_DIR / "stock_debt.json"
_VOL_CACHE = _CACHE_DIR / "stock_volatility.json"
_BUYBACK_CACHE = _CACHE_DIR / "stock_buyback.json"
_MGMT_CACHE = _CACHE_DIR / "stock_mgmt.json"

_PLEDGE_CACHE = _CACHE_DIR / "stock_pledge.json"
_MOMENTUM_CACHE = _CACHE_DIR / "stock_momentum.json"
_EVENT_CACHE = _CACHE_DIR / "bond_event.json"
_CONCEPT_CACHE = _CACHE_DIR / "stock_concept.json"
_CONCEPT_SOURCE_CACHE = _CACHE_DIR / "stock_concept_source.json"
_BOND_OUTSTANDING_CACHE = _CACHE_DIR / "bond_outstanding.json"
_CALL_STATUS_CACHE = _CACHE_DIR / "bond_call_status.json"
_STOCK_NAME_CACHE = _CACHE_DIR / "stock_names.json"
_BOND_PRICE_CACHE = _CACHE_DIR / "bond_price.json"
_COUPON_RATE_CACHE = _CACHE_DIR / "bond_coupon_rate.json"
_MAIN_BIZ_CACHE = _CACHE_DIR / "stock_main_biz.json"
_ANALYST_RANK_CACHE = _CACHE_DIR / "stock_analyst_rank.json"
_MACRO_CPI_CACHE = _CACHE_DIR / "macro_cpi.json"
_MACRO_PPI_CACHE = _CACHE_DIR / "macro_ppi.json"
_MACRO_M2_CACHE = _CACHE_DIR / "macro_m2.json"
_MACRO_LPR_CACHE = _CACHE_DIR / "macro_lpr.json"

_industry_map: dict[str, str] = {}
_industry_loaded = False
_spot_map: dict[str, dict] = {}
_spot_loaded = False
_fin_map: dict[str, dict] = {}
_fin_loaded = False
_fund_flow_map: dict[str, dict] = {}
_fund_flow_loaded = False
_debt_map: dict[str, dict] = {}
_debt_loaded = False
_vol_map: dict[str, float] = {}
_vol_loaded = False
_buyback_map: dict[str, float] = {}
_buyback_loaded = False
_mgmt_map: dict[str, float] = {}
_mgmt_loaded = False

_pledge_map: dict[str, float] = {}
_pledge_loaded = False
_momentum_map: dict[str, dict] = {}
_momentum_loaded = False
_event_map: dict[str, dict] = {}
_event_loaded = False
_bond_outstanding_map: dict[str, float] = {}
_bond_outstanding_loaded = False
_call_status_map: dict[str, str] = {}
_call_status_loaded = False
_name_map: dict[str, str] = {}
_name_loaded = False
_concept_map: dict[str, list[str]] = {}
_concept_loaded = False
_concept_source_map: dict[str, dict[str, bool]] = {}
_concept_source_loaded = False
_bond_price_map: dict[str, dict] = {}
_bond_price_loaded = False
_coupon_rate_map: dict[str, float] = {}  # bond_code -> coupon_rate (独立缓存，不被 bond_price refresh 覆盖)
_coupon_rate_loaded = False
_main_biz_map: dict[str, str] = {}
_main_biz_loaded = False
_analyst_rank_map: dict[str, dict] = {}
_analyst_rank_loaded = False
_macro_cpi_map: dict = {}
_macro_cpi_loaded = False
_macro_ppi_map: dict = {}
_macro_ppi_loaded = False
_macro_m2_map: dict = {}
_macro_m2_loaded = False
_macro_lpr_map: dict = {}
_macro_lpr_loaded = False


# ── 共享工具函数（从 data_enrich_utils 导入，保持内部别名向后兼容）──
_load_cache = _load_cache_impl
_save_cache = _save_cache_impl
_fresh = _fresh_impl
_sf = _sf_impl


def _set_global_map(name: str, new_value, replace: bool = False):
    """线程安全地更新全局缓存映射。
    使用 copy-on-write：构建合并后的新 dict，一次性替换全局引用，
    避免在迭代过程中 del 已有 key 触发 RuntimeError。
    仍保持原地 dict 实例的协议（enrich_quotes 通过 globals().get(name) 获取最新引用）。
    Args:
        replace: 为 True 时直接替换（全量刷新场景），不保留旧 key。
    """
    global _cache_refresh_ts
    with _cache_lock:
        existing = globals().get(name)
        if existing is None:
            globals()[name] = new_value
        elif isinstance(existing, dict) and isinstance(new_value, dict):
            if replace:
                globals()[name] = new_value
            else:
                # 合并：保留 existing 中不在 new_value 的 key（不删除，新增覆盖）
                # 这样读者永远不会看到空 dict，也不会因迭代中 del 触发 RuntimeError
                merged = {**existing, **new_value}
                globals()[name] = merged
        else:
            globals()[name] = new_value
        _cache_refresh_ts[name] = time.time()


_cache_refresh_ts: dict[str, float] = {}

# 缓存刷新指标记录
_refresh_metrics: dict[str, dict] = {}
_METRICS_FILE = _CACHE_DIR / "refresh_metrics.json"


_METRICS_STALE_TTL = 86400  # 24h — 超过此时间的指标标记为 stale
_last_metrics_flush = 0.0   # 上次写入文件的时间戳
_METRICS_FLUSH_INTERVAL = 30.0  # 至少间隔 30s 才写入文件，避免频繁 I/O
_start_ts = float('-inf')  # start_background_refresh 调用时间，用于缩短首次 flush interval
_METRICS_FAST_FLUSH_WINDOW = 300.0  # 启动后前 5 分钟内 flush interval 缩短为 5s
_last_stale_check_ts = 0.0  # 上次 stale 标记遍历的时间戳（节流 _mark_stale_entries）
_METRICS_STALE_CHECK_INTERVAL = 60.0  # stale 标记遍历至少间隔 60s

# 全局 akshare 并发限制：防止高频调用触发 CDN 临时 IP 封禁
# 默认 8 并发：akshare 文档建议不超过 10，超过会触发 rate limit
# daemon thread 在 semaphore 保护下排队，避免瞬时风暴
# 可通过环境变量 LH_AKSHARE_MAX_CONCURRENCY 调整
import os as _os
_akshare_max_concurrency = int(_os.getenv("LH_AKSHARE_MAX_CONCURRENCY", "8"))
_akshare_semaphore = threading.Semaphore(_akshare_max_concurrency)
# semaphore 短超时（5s）：如果并发已满，等 5s 还拿不到 token 就放弃
# 避免被外层 join(timeout) 长时间阻塞，分离"排队"和"网络"超时
_akshare_semaphore_timeout = float(_os.getenv("LH_AKSHARE_SEM_TIMEOUT", "5.0"))

# 各接口的超时分级（按接口历史响应时间，AGENTS.md #39 推荐）
# fast: 已知稳定 < 10s；medium: 10-30s；slow: > 30s
_TIMEOUT_FAST = 15.0     # 已知快速接口（如 bond_zh_cov_info_ths）
_TIMEOUT_MEDIUM = 30.0   # 普通接口（fund_flow, fin, debt）
_TIMEOUT_SLOW = 60.0     # 慢接口（lhb 统计, stock_holder, margin）


def _run_with_timeout(fn, *args, timeout: float = 30.0, default=None, op_name: str = "", quiet_errors: bool = False):
    """在 daemon 线程中执行阻塞调用 fn(*args)，超时强制返回 default。
    目的：防止 akshare 网络调用 hang 死整个线程（导致后端进程无响应）。
    使用全局 semaphore 限制并发数，避免触发 akshare 频率限制。
    semaphore 释放通过 _release_done Event 确保：超时后外层立即返回，
    但 _runner 在 fn 完成（或异常）后一定会 release semaphore，避免泄漏。

    Args:
        fn: 要执行的同步函数（async def 会被拒绝，防止 coroutine 对象泄漏）
        timeout: 超时秒数（默认 30s）
        default: 超时后返回值（默认 None）
        op_name: 操作名称，用于日志
        quiet_errors: 已知易失败的接口（如 East Money 单股查询）报异常时降低日志级别为 DEBUG
    """
    # AGENTS.md #51: 防御 async def 传入 _run_with_timeout
    if asyncio.iscoroutinefunction(fn):
        logger.error(f"[DataEnrich] {op_name or fn.__name__} is async def, cannot run in _run_with_timeout")
        return default
    result_box = [default]
    error_box = [None]
    tb_box = [None]
    _release_done = threading.Event()

    def _runner():
        # semaphore 超时与 fn 超时分开：semaphore.acquire 用 5s 短超时，
        # 排队过长立即放弃，避免与外层 join(timeout) 30s 混淆
        acquired = _akshare_semaphore.acquire(timeout=_akshare_semaphore_timeout)
        if not acquired:
            logger.warning(f"[DataEnrich] {op_name or fn.__name__} semaphore 排队超时 "
                           f"{_akshare_semaphore_timeout}s（并发={_akshare_max_concurrency}）")
            _release_done.set()
            return
        try:
            result_box[0] = fn(*args)
        except Exception as e:
            error_box[0] = e
            tb_box[0] = traceback.format_exc()
        finally:
            # 无论 fn 是否完成 / 是否异常，都必须 release semaphore
            _akshare_semaphore.release()
            _release_done.set()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        logger.warning(f"[DataEnrich] {op_name or fn.__name__} 超时 {timeout}s, 返回 default")
        # 注意：不能 t.join() 阻塞等 fn 完成。semaphore release 由 daemon 线程
        # 完成后自己负责。daemon=True 保证主进程退出时不会泄漏线程。
        return default
    if error_box[0] is not None:
        log_fn = logger.debug if quiet_errors else logger.warning
        log_fn(
            f"[DataEnrich] {op_name or fn.__name__} 失败: {type(error_box[0]).__name__}: {error_box[0]}\n"
            f"{tb_box[0] or '(traceback unavailable)'}"
        )
        return default
    return result_box[0]


def _record_refresh_metric(name: str, elapsed_s: float, count: int, status: str = "ok", error: str = "", extra: dict = None):
    """记录单次缓存刷新的执行指标，并持久化到 refresh_metrics.json。
    stale 标记只在 flush 时计算，减少每次调用的遍历开销。
    改进 (2025-06-15ar): 从源头过滤 _inproc 内部实现条目，避免监控面板显示重复/混淆数据。
    改进 (2025-06-22): 使用带文件锁的共享 metrics 工具，兼容 runner 子进程并发写入。
    """
    if "_inproc" in name:
        return
    # 同步写入共享 metrics 文件（带文件锁，兼容 runner 子进程）
    record_refresh_metric(_METRICS_FILE, name, elapsed_s, count, status, error, extra)
    # 同时更新内存，保证 get_refresh_metrics 立即返回最新状态
    with _cache_lock:
        _refresh_metrics[name] = {
            "name": name,
            "elapsed_s": round(elapsed_s, 2),
            "count": count,
            "status": status,
            "error": error[:200] if error else "",
            "ts": datetime.now().isoformat(),
        }
        if extra:
            _refresh_metrics[name].update(extra)
    # 按原有 flush interval 限频回写文件，避免高频 I/O
    now = time.time()
    effective_interval = (
        5.0 if _start_ts and (now - _start_ts < _METRICS_FAST_FLUSH_WINDOW)
        else _METRICS_FLUSH_INTERVAL
    )
    if _last_metrics_flush <= 1e-9 or now - _last_metrics_flush >= effective_interval:
        _write_metrics_to_file()


def _mark_stale_entries(data: dict, now: float, force: bool = False):
    """遍历 metric 条目，为超过 _METRICS_STALE_TTL 的条目标记 stale=True。
    同时回写内存中的 _refresh_metrics，确保 get_refresh_metrics() 和文件内容一致。
    新增：对连续 empty/error 超过 10 分钟的数据源也标记 stale，
    避免监控页误显示"正常"状态。

    Args:
        data: 待检查的 dict（通常是 dict(_refresh_metrics) 浅拷贝）
        now: 当前时间戳
        force: 是否强制遍历（默认节流，仅在 60s 内首次调用时真正遍历）

    注意：data 的内嵌 dict 是浅拷贝引用，对 v["stale"] = True 的修改
    会直接反映到内存 _refresh_metrics 中，因此本函数同时也是回写操作。
    """
    global _last_stale_check_ts
    if not force and (now - _last_stale_check_ts < _METRICS_STALE_CHECK_INTERVAL):
        return
    _last_stale_check_ts = now
    # 空状态超时：连续 10 分钟 status=empty 或 error 视为 stale
    _EMPTY_STATE_STALE_TTL = 600.0  # 10 分钟
    for k, v in data.items():
        if not isinstance(v, dict) or not v.get("ts") or "stale" in v:
            continue
        try:
            ts = datetime.fromisoformat(v["ts"]).timestamp()
            if now - ts > _METRICS_STALE_TTL:
                v["stale"] = True
            elif (now - ts > _EMPTY_STATE_STALE_TTL
                  and v.get("status") in ("empty", "error")
                  and (v.get("count") or 0) == 0):
                # 空数据超过 10 分钟：标记 stale，便于监控页区分
                v["stale"] = True
        except (ValueError, OSError):
            # ts 解析失败时也标记 stale，避免永久显示为"正常"状态
            # (可能是数据源写入错误或时钟漂移)
            v["stale"] = True


def _write_metrics_to_file():
    """将内存中的 refresh metrics 持久化到 JSON 文件（含 stale 标记计算）。
    独立于 _record_refresh_metric 的限频逻辑，可随时强制写入。
    stale 标记同时回写内存，确保 get_refresh_metrics() 和文件内容一致。
    注意：pending 预注册占位符不写入文件，避免覆盖 runner 子进程的真实结果。
    加锁后读取文件并合并，防止与 runner 子进程的并发写产生 race condition。
    """
    now = time.time()
    try:
        with _cache_lock:
            mem_data = {k: dict(v) for k, v in _refresh_metrics.items() if v.get("status") != "pending"}
        if not mem_data:
            return
        # 写入文件时强制刷新 stale 标记（不节流）
        _mark_stale_entries(mem_data, now, force=True)
        # 加锁加载文件并合并，避免覆盖 runner 子进程新写入的结果
        lock_path = _lock_file_path(_METRICS_FILE)
        with _acquire_file_lock(lock_path, timeout=5.0):
            try:
                file_data = _load_cache_impl(_METRICS_FILE) or {}
            except Exception:
                file_data = {}
            if not isinstance(file_data, dict):
                file_data = {}
            # 用内存中的非 pending 条目覆盖文件中的同名条目
            # runner 写入的真实结果保留（内存中对应条目仍是 pending，不会覆盖）
            file_data.update(mem_data)
            # 再次清理可能从文件加载到的 pending 占位符
            file_data = {k: v for k, v in file_data.items() if isinstance(v, dict) and v.get("status") != "pending"}
            try:
                _save_cache_impl(_METRICS_FILE, file_data)
            except Exception as e:
                logger.warning(f"[DataEnrich] Metrics save failed: {e}")
        global _last_metrics_flush
        _last_metrics_flush = now
    except Exception as e:
        logger.debug(f"[DataEnrich] Metrics save failed: {e}")


def _load_metrics_from_file():
    """从共享 metrics 文件加载 runner 子进程写入的指标并合并到内存。"""
    try:
        runner_metrics = load_refresh_metrics(_METRICS_FILE)
    except Exception as e:
        logger.debug(f"[DataEnrich] Metrics load failed: {e}")
        return
    if not runner_metrics:
        return
    with _cache_lock:
        for name, entry in runner_metrics.items():
            mem = _refresh_metrics.get(name)
            # 内存中若是 pending 占位符，直接用文件中的真实结果替换
            if mem and mem.get("status") == "pending" and entry.get("status") != "pending":
                _refresh_metrics[name] = entry
                continue
            # 否则按时间戳较新为准
            if mem and mem.get("ts") and entry.get("ts"):
                try:
                    if mem["ts"] >= entry["ts"]:
                        continue
                except TypeError:
                    pass
            _refresh_metrics[name] = entry


def _flush_metrics():
    """强制将当前内存中的 refresh metrics 写入文件，不受 flush interval 限制。
    在 start_background_refresh 的所有 executor 任务完成后调用，
    确保首次启动后 metrics 文件立即可用（而非等待 30s flush interval）。
    直接调用 _write_metrics_to_file()，不再通过哨兵条目触发。
    """
    _write_metrics_to_file()


def _get_bond_or_fallback_codes() -> frozenset:
    """获取可转债正股代码集合，若 THS 不可用则回退到已加载的 _name_map 键。

    确保零填充和数据源覆盖率统计始终有可用的股票代码列表，
    即使在启动阶段 AKShare 信号量被争用导致 _ensure_bond_stock_codes 超时。
    """
    if _bond_stock_codes:
        with _cache_lock:
            return frozenset(_bond_stock_codes)
    # 回退：使用已从磁盘缓存加载的 _name_map 键
    if _name_map:
        with _cache_lock:
            codes = frozenset(
                k for k in _name_map.keys()
                if k and len(k) == 6 and k.isdigit()
            )
            if codes:
                return codes
    return frozenset()


def _with_metrics(fn):
    """装饰器：为 _refresh_* 函数自动记录执行时间和结果数量。
    status 语义：
      - "ok":    count > 0，数据源正常返回
      - "empty": count == 0，数据源可能挂掉或无数据（需关注）
      - "error": 函数抛出未捕获异常（漏网之鱼）
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        name = fn.__name__
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            elapsed = time.time() - t0
            # 优先使用函数主动返回的 count（int 类型）
            count = result if isinstance(result, int) and result >= 0 else None
            map_name = _METRICS_NAME_TO_MAP.get(name)
            if count is None:
                # 使用显式映射（避免脆弱字符串替换）
                if map_name:
                    with _cache_lock:
                        m = globals().get(map_name)
                        if isinstance(m, dict):
                            count = len([k for k in m if not k.startswith("_")])
                        elif isinstance(m, (set, list)):
                            count = len(m)
                        else:
                            count = 0
                else:
                    count = 0
            # 额外统计 bond_stock_codes 在该 map 中的覆盖率（核心业务指标）
            # 确保 _bond_stock_codes 已初始化（首次刷新时可能尚未填充）
            # 在锁内快照为 frozenset，避免迭代期间被其他线程修改导致 RuntimeError
            _bond_codes_snapshot = _get_bond_or_fallback_codes()
            bond_count = 0
            bond_total = len(_bond_codes_snapshot)
            if bond_total > 0 and map_name:
                with _cache_lock:
                    m = globals().get(map_name)
                    # AGENTS.md fix: bond-related maps use bond codes as keys, not stock codes
                    codes_to_check = _bond_codes if (map_name in _BOND_CODE_MAPS and _bond_codes) else _bond_codes_snapshot
                    if isinstance(m, dict):
                        bond_count = sum(1 for c in codes_to_check if c in m and m.get(c) is not None)
            status = "ok" if count and count > 0 else "empty"
            # 新增：completeness (bond_count / bond_total) 让前端知道数据完整度
            # 例如：north_cache 60s 内只完成 109/854，completeness=0.13
            # 注意：对于 bond_outstanding 这种聚合多数据源（数量 > bond_codes），会 > 100%
            # 用 min(1.0, ...) 截断到 100%，避免前端显示 "109%" 误导用户
            raw_completeness = bond_count / bond_total if bond_total > 0 else None
            completeness = round(min(1.0, raw_completeness), 3) if raw_completeness is not None else None
            # 新增：expected_count — 期望的目标条数
            # - 对于 bond-related maps，期望 = bond_total
            # - 对于全 A 股 maps，期望 = _name_map 大小（~5500）
            # - 对于其他 maps，期望 = count（已经达到）
            if map_name and bond_total > 0:
                expected_count = bond_total
            elif map_name and _name_map:
                expected_count = len(_name_map)
            else:
                expected_count = count if count else 0
            extra = {
                "bond_count": bond_count,
                "bond_total": bond_total,
                "completeness": completeness,
                "expected_count": expected_count,
            } if bond_total > 0 or expected_count > 0 else {}
            # 添加 completeness_raw 给前端调试用（聚合数据源会出现 >1.0）
            if raw_completeness is not None and raw_completeness > 1.001:
                extra["completeness_raw"] = round(raw_completeness, 3)
            # 新增：zero_fill 标识，让前端知道"没数据 vs 有数据但为 0"
            if map_name:
                with _cache_lock:
                    m = globals().get(map_name)
                    if isinstance(m, dict):
                        zero_fill_count = sum(1 for v in m.values()
                                              if isinstance(v, dict) and v.get("_data_source") == "zero_fill")
                        if zero_fill_count > 0:
                            extra["zero_fill_count"] = zero_fill_count
                            extra["zero_fill_pct"] = round(zero_fill_count / max(count, 1), 3)
            _record_refresh_metric(name, elapsed, count or 0, status=status, extra=extra)
            return result
        except Exception as e:
            elapsed = time.time() - t0
            _record_refresh_metric(name, elapsed, 0, status="error", error=str(e))
            raise
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    # 白名单标记：auto-discover 只扫描有此属性的函数
    # 这样未装饰的内部函数（如 _refresh_xxx_inproc）不会被错误注册
    wrapper._REGISTER_METRIC = True
    return wrapper


# 显式映射：refresh 函数名 → 全局 map 变量名（避免脆弱字符串替换 _refresh_xxx_cache → _xxx_map）
_METRICS_NAME_TO_MAP = {
    "_refresh_spot_cache": "_spot_map",
    "_refresh_fin_cache": "_fin_map",
    "_refresh_fund_flow_cache": "_fund_flow_map",
    "_refresh_debt_cache": "_debt_map",
    "_refresh_volatility_cache": "_vol_map",
    "_refresh_buyback_cache": "_buyback_map",
    "_refresh_mgmt_cache": "_mgmt_map",
    "_refresh_pledge_cache": "_pledge_map",
    "_refresh_momentum_cache": "_momentum_map",
    "_refresh_earnings_express_cache": "_earnings_express_map",
    "_refresh_event_cache": "_event_map",
    "_refresh_bond_outstanding_cache": "_bond_outstanding_map",
    "_refresh_call_status_cache": "_call_status_map",
    "_refresh_stock_name_cache": "_name_map",
    "_refresh_coupon_rate_cache": "_coupon_rate_map",
    "_build_industry_cache": "_industry_map",
    "_build_concept_cache": "_concept_map",
    "_refresh_bond_price_cache": "_bond_price_map",
    "_refresh_north_cache": "_north_map",
    "_refresh_margin_cache": "_margin_map",
    "_refresh_lhb_cache": "_lhb_map",
    "_refresh_block_trade_cache": "_block_trade_map",
    "_refresh_holder_num_cache": "_holder_num_map",
    "_refresh_earnings_forecast_cache": "_earnings_forecast_map",
    "_refresh_restricted_release_cache": "_restricted_release_map",
    "_refresh_main_biz_cache": "_main_biz_map",
    "_refresh_analyst_rank_cache": "_analyst_rank_map",
    "_refresh_macro_cpi_cache": "_macro_cpi_map",
    "_refresh_macro_ppi_cache": "_macro_ppi_map",
    "_refresh_macro_m2_cache": "_macro_m2_map",
    "_refresh_macro_lpr_cache": "_macro_lpr_map",
}


# 这些 map 的 key 是债券代码（而非正股代码），_with_metrics 统计 bond_count 时应使用 _bond_codes
_BOND_CODE_MAPS = {"_bond_outstanding_map", "_call_status_map", "_bond_price_map", "_coupon_rate_map", "_event_map"}


def get_cache_refresh_ts() -> dict[str, float]:
    """返回所有数据源的刷新时间戳（用于数据源健康检查页）"""
    with _cache_lock:
        return dict(_cache_refresh_ts)


def get_refresh_metrics() -> dict[str, dict]:
    """返回所有缓存刷新的执行指标（用于监控面板展示）。
    对未标记 stale 的条目做实时检查，确保 API 返回的 stale 状态与实际一致。
    改进 (2025-06-15ar): _inproc 过滤已下沉到 _record_refresh_metric，此处无需再过滤。
    改进 (2025-06-22): 加载 runner 子进程写入的共享 metrics 文件并合并，
                      解决 spot/vol/fund_flow/bond_price 等由 runner 刷新的数据源
                      在监控面板缺失的问题。
    """
    # 先合并 runner 子进程写入的指标
    _load_metrics_from_file()
    with _cache_lock:
        data = dict(_refresh_metrics)
    _mark_stale_entries(data, time.time())
    return data


# ==================== 公共读取接口 ====================


import functools


def get_industry(stock_code: str) -> Optional[str]:
    return _industry_map.get(stock_code)


def get_stock_spot(stock_code: str) -> dict:
    return _spot_map.get(stock_code, {})


def get_all_stock_change_pct() -> dict[str, float]:
    with _cache_lock:
        snap = dict(_spot_map)
    return {
        code: info.get("change_pct")
        for code, info in snap.items()
        if isinstance(info, dict) and info.get("change_pct") is not None
    }


def get_financial(code: str) -> dict:
    return _fin_map.get(code, {})


def get_fund_flow(code: str) -> dict:
    return _fund_flow_map.get(code, {})


def get_debt_info(stock_code: str) -> dict:
    return _debt_map.get(stock_code, {})


def get_volatility(stock_code: str) -> Optional[float]:
    return _vol_map.get(stock_code)


def get_buyback_amount(stock_code: str) -> Optional[float]:
    return _buyback_map.get(stock_code)


def get_mgmt_buy_price(stock_code: str) -> Optional[float]:
    return _mgmt_map.get(stock_code)


def _inject_spot_data(data: dict[str, dict]):
    if not data:
        return
    # 持有 _cache_lock 以避免与 _set_global_map 的并发 dict 替换产生竞态。
    # 否则 _set_global_map 替换 _spot_map 引用时，本函数会写入已被丢弃的旧 dict。
    with _cache_lock:
        for code, info in data.items():
            if code in _spot_map and isinstance(_spot_map[code], dict):
                _spot_map[code].update(info)
            else:
                _spot_map[code] = info
    logger.info(f"[DataEnrich] Injected {len(data)} Sina spot records into memory")


# ==================== 缓存加载 ====================


def _load_industry_cache():
    global _industry_map, _industry_loaded
    if _industry_loaded:
        return
    cached = _load_cache(_INDUSTRY_CACHE)
    if cached:
        _set_global_map("_industry_map", {k: v for k, v in cached.items() if k != "_ts"})
    _industry_loaded = True


def _load_spot_cache():
    global _spot_map, _spot_loaded
    if _spot_loaded:
        return
    cached = _load_cache(_SPOT_CACHE)
    if cached:
        _set_global_map("_spot_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
        has_pe = any(v.get("pe") is not None for v in _spot_map.values())
        if not has_pe:
            # Keep partial data (price/volume/turnover); background refresh
            # will fill PE/PB. Clearing would leave enrich_quotes with no
            # spot data for 5-10 minutes, expanding the gap.
            logger.warning("[DataEnrich] Cached spot data has no PE/PB; keeping partial data, will refresh in background")
    _spot_loaded = True


def _load_fin_cache():
    global _fin_map, _fin_loaded
    if _fin_loaded:
        return
    cached = _load_cache(_FIN_CACHE)
    if cached:
        _set_global_map("_fin_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
    _fin_loaded = True


def _load_fund_flow_cache():
    global _fund_flow_map, _fund_flow_loaded
    if _fund_flow_loaded:
        return
    cached = _load_cache(_FUND_FLOW_CACHE)
    if cached:
        _set_global_map("_fund_flow_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
    _fund_flow_loaded = True


def _load_debt_cache():
    global _debt_map, _debt_loaded
    if _debt_loaded:
        return
    cached = _load_cache(_DEBT_CACHE)
    if cached:
        _set_global_map("_debt_map", {k: v for k, v in cached.items() if k != "_ts" and isinstance(v, dict)})
    _debt_loaded = True


def _load_vol_cache():
    global _vol_map, _vol_loaded
    if _vol_loaded:
        return
    cached = _load_cache(_VOL_CACHE)
    if cached:
        _set_global_map("_vol_map", {k: v for k, v in cached.items() if k != "_ts"})
    _vol_loaded = True


def _load_buyback_cache():
    global _buyback_map, _buyback_loaded
    if _buyback_loaded:
        return
    cached = _load_cache(_BUYBACK_CACHE)
    if cached:
        _set_global_map("_buyback_map", {k: v for k, v in cached.items() if k != "_ts"})
    _buyback_loaded = True


def _load_mgmt_cache():
    global _mgmt_map, _mgmt_loaded
    if _mgmt_loaded:
        return
    cached = _load_cache(_MGMT_CACHE)
    if cached:
        _set_global_map("_mgmt_map", {k: v for k, v in cached.items() if k != "_ts"})
    _mgmt_loaded = True


# ==================== 后台刷新 ====================


@_with_metrics
def _build_industry_cache():
    try:
        logger.info("[DataEnrich] Building industry cache (may take minutes)...")
        df = ak.stock_board_industry_name_em()
        if df is None or len(df) == 0:
            logger.warning("[DataEnrich] Industry: stock_board_industry_name_em returned empty")
            return 0
        result = {}
        count = 0
        total = len(df)
        for _, board in df.iterrows():
            bcode = str(board.get("板块代码", "")).strip()
            bname = str(board.get("板块名称", "")).strip()
            if not bcode or not bname:
                continue
            try:
                cons = ak.stock_board_industry_cons_em(symbol=bcode)
                for _, c in cons.iterrows():
                    scode = str(c.get("代码", "")).strip()
                    if scode:
                        result[scode] = bname
                count += 1
                if count % 100 == 0:
                    logger.info(f"[DataEnrich] Industry: {count}/{total} boards")
            except Exception:
                continue
        _set_global_map("_industry_map", result, replace=True)
        _save_cache(_INDUSTRY_CACHE, result)
        logger.info(f"[DataEnrich] Industry built: {len(result)} stocks")

        # [TDX] fallback: 用 TDX 证券列表补充分类
        if len(result) < 500:
            try:
                logger.info('[DataEnrich][TDX] Industry: EM returned <500 stocks, checking TDX security list')
                adapter = get_tdx_adapter()
                tdx_securities = adapter.fetch_all_securities()
                filled = 0
                for code, name in tdx_securities.items():
                    if code not in result and name:
                        result[code] = name[:10]
                        filled += 1
                if filled:
                    _set_global_map('_industry_map', result, replace=True)
                    _save_cache(_INDUSTRY_CACHE, result)
                    logger.info(f'[DataEnrich][TDX] Industry: added {filled} stocks from TDX names')
            except Exception as tdx_e:
                logger.debug(f'[DataEnrich][TDX] Industry fallback failed: {tdx_e}')
    except Exception as e:
        logger.warning(f"[DataEnrich] Industry build failed: {e}")
    return len(_industry_map) if _industry_map else 0


def _fill_pe_pb_from_baidu(codes: list[str], pe_map: dict, pb_map: dict):
    try:
        from concurrent.futures import ThreadPoolExecutor

        def _baidu_one(code: str):
            try:
                df_pe = ak.stock_zh_valuation_baidu(symbol=code, indicator="市盈率(TTM)", period="近一年")
                pe_val = None
                if df_pe is not None and len(df_pe) > 0:
                    raw = df_pe["value"].iloc[-1]
                    pe_val = _sf(raw)
                df_pb = ak.stock_zh_valuation_baidu(symbol=code, indicator="市净率", period="近一年")
                pb_val = None
                if df_pb is not None and len(df_pb) > 0:
                    raw = df_pb["value"].iloc[-1]
                    pb_val = _sf(raw)
                return code, pe_val, pb_val
            except Exception:
                return code, None, None

        missing = [c for c in codes if c not in pe_map or c not in pb_map]
        if not missing:
            return
        logger.info(f"[DataEnrich] Baidu: fetching {len(missing)} stocks for PE/PB")
        filled = 0
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(_baidu_one, c) for c in missing]
            done, pending = concurrent.futures.wait(
                futures, timeout=300, return_when=concurrent.futures.ALL_COMPLETED
            )
            if pending:
                logger.warning(f"[DataEnrich] Baidu PE/PB: {len(pending)} (of {len(futures)}) futures unfinished after 300s")
                for fut in pending:
                    fut.cancel()
            for i, future in enumerate(done):
                code, pe_val, pb_val = future.result()
                if pe_val is not None and code not in pe_map:
                    pe_map[code] = pe_val
                    filled += 1
                if pb_val is not None and code not in pb_map:
                    pb_map[code] = pb_val
                if (i + 1) % 50 == 0:
                    time.sleep(1)
        logger.info(f"[DataEnrich] Baidu: filled {filled} PE, total PE={len(pe_map)}, PB={len(pb_map)}")
    except Exception as e:
        logger.warning(f"[DataEnrich] Baidu PE/PB fallback failed: {e}")


def _fill_pe_pb_from_ths(codes: list[str], pe_map: dict, pb_map: dict, sina_map: dict = None):
    """THS 财务摘要作为 PE/PB 三级后备。
    注意：THS 接口依赖 py_mini_racer，在 macOS Electron sandbox 中 dlsym 失败。
    若 sys.platform=='darwin' 且未设置 LH_MGMT_TRY_CNINFO=1，自动跳过（不浪费 2-3min）。
    """
    # AGENTS.md #48: macOS sandbox 中 py_mini_racer 不可用，跳过 THS 以免每个调用阻塞 5-10s
    # 非 macOS 环境自动启用，无需显式设置环境变量
    if sys.platform == 'darwin' and not os.environ.get('LH_MGMT_TRY_CNINFO'):
        logger.debug("[DataEnrich] THS PE/PB fallback skipped (macOS sandbox + no LH_MGMT_TRY_CNINFO)")
        return
    sina_map = sina_map or {}
    try:
        missing = [c for c in codes if c not in pe_map or c not in pb_map]
        if not missing:
            return
        logger.info(f"[DataEnrich] THS: fetching {len(missing)} stocks for EPS/BPS → PE/PB")
        filled = 0
        for i, code in enumerate(missing):
            try:
                df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
                if df is None or len(df) == 0:
                    continue
                for _, r in df.iterrows():
                    eps_raw = r.get("基本每股收益")
                    bps_raw = r.get("每股净资产")
                    if not eps_raw or eps_raw == "False" or not bps_raw or bps_raw == "False":
                        continue
                    eps = _sf(eps_raw)
                    bps = _sf(bps_raw)
                    spot = _spot_map.get(code, {})
                    price = spot.get("price") or _sf(sina_map.get(code, {}).get("price"))
                    if eps and eps > 0 and price and price > 0:
                        if code not in pe_map:
                            pe_map[code] = round(price / eps, 2)
                            filled += 1
                    if bps and bps > 0 and price and price > 0:
                        if code not in pb_map:
                            pb_map[code] = round(price / bps, 2)
                    break
            except Exception:
                continue
            if (i + 1) % 30 == 0:
                time.sleep(1)
        logger.info(f"[DataEnrich] THS: filled {filled} PE, total PE={len(pe_map)}, PB={len(pb_map)}")
    except Exception as e:
        logger.warning(f"[DataEnrich] THS PE/PB fallback failed: {e}")


def _fill_pe_pb_from_yfinance(codes: list[str], pe_map: dict, pb_map: dict):
    """用 yfinance 补充缺失的 PE/PB 数据 (Tier 4 兜底)
    优先使用 yf.download() 批量获取 (~5s for 200 stocks)，
    批量失败的股票再逐只 fallback (~0.2s/each, max 50)。
    """
    try:
        import yfinance as yf
        missing = [c for c in codes if c not in pe_map or c not in pb_map]
        if not missing:
            return
        batch = missing[:200]
        logger.info(f"[DataEnrich][yfinance] Fetching PE/PB for {len(batch)} stocks")

        tickers = []
        code_to_ticker = {}
        for code in batch:
            if code.startswith(('6', '9')):
                ticker = f"{code}.SS"
            else:
                ticker = f"{code}.SZ"
            tickers.append(ticker)
            code_to_ticker[ticker] = code

        filled = 0
        single_fallback_codes = []

        # ── Phase 1: 批量下载 fast_info (带重试) ──
        for ticker in tickers:
            code = code_to_ticker.get(ticker)
            if not code:
                continue
            info = None
            last_err = None
            for attempt in range(2):
                try:
                    info = yf.Ticker(ticker).fast_info
                    if info is not None:
                        break
                except Exception as e:
                    last_err = e
                    if attempt < 1:
                        time.sleep(1.0)
                        logger.debug(f"[DataEnrich][yfinance] Retry {ticker} after error: {e}")
            if info is None:
                if last_err:
                    logger.debug(f"[DataEnrich][yfinance] {ticker} failed after 2 attempts: {last_err}")
                single_fallback_codes.append(code)
                continue
            try:
                if code not in pe_map:
                    pe = getattr(info, 'trailing_pe', None) or getattr(info, 'forward_pe', None)
                    if pe and 0 < pe < 10000:
                        pe_map[code] = round(float(pe), 2)
                if code not in pb_map:
                    pb = getattr(info, 'price_to_book', None)
                    if pb and 0 < pb < 10000:
                        pb_map[code] = round(float(pb), 2)
                if code in pe_map or code in pb_map:
                    filled += 1
                else:
                    single_fallback_codes.append(code)
            except Exception:
                single_fallback_codes.append(code)

        logger.info(f"[DataEnrich][yfinance] Phase 1 filled {filled} stocks, total PE={len(pe_map)}, PB={len(pb_map)}")

        # ── Phase 2: 批量失败的股票逐只 fallback (use .info instead of .fast_info for different API path) ──
        if single_fallback_codes:
            phase2_codes = single_fallback_codes[:50]
            logger.info(f"[DataEnrich][yfinance] Phase 2: single fallback for {len(phase2_codes)} stocks")
            p2_filled = 0
            for code in phase2_codes:
                if code in pe_map and code in pb_map:
                    continue
                if code.startswith(('6', '9')):
                    ticker = f"{code}.SS"
                else:
                    ticker = f"{code}.SZ"
                try:
                    info = yf.Ticker(ticker).info  # .info instead of .fast_info for different API endpoint
                    if info is not None and isinstance(info, dict):
                        if code not in pe_map:
                            pe = info.get('trailingPe', None) or info.get('forwardPe', None)
                            if pe and 0 < pe < 10000:
                                pe_map[code] = round(float(pe), 2)
                        if code not in pb_map:
                            pb = info.get('priceToBook', None)
                            if pb and 0 < pb < 10000:
                                pb_map[code] = round(float(pb), 2)
                        if code in pe_map or code in pb_map:
                            p2_filled += 1
                except Exception:
                    pass
            logger.info(f"[DataEnrich][yfinance] Phase 2 filled {p2_filled} stocks")

    except ImportError:
        logger.debug("[DataEnrich][yfinance] yfinance not installed, skipping")
    except Exception as e:
        logger.warning(f"[DataEnrich][yfinance] PE/PB fallback failed: {e}")


_bond_stock_codes: set[str] = set()


def set_bond_stock_codes(codes: list[str]):
    """线程安全地更新可转债正股代码集合。
    持有 _cache_lock 防止与 _with_metrics 的 for-loop 迭代产生 RuntimeError。
    同时输入校验：只接受 6 位数字股票代码，过滤掉空值和非数字。
    """
    global _bond_stock_codes
    with _cache_lock:
        _bond_stock_codes = set(
            str(c) for c in codes if c and str(c).isdigit() and len(str(c)) == 6
        )
        logger.info(f"[DataEnrich] Bond stock codes set: {len(_bond_stock_codes)} stocks")


def _ensure_bond_stock_codes():
    """线程安全地确保 _bond_stock_codes 和 _bond_codes 已初始化。
    双重检查 + 锁内仅做引用赋值（不持有锁进行 I/O）。
    """
    global _bond_stock_codes, _bond_codes
    if _bond_stock_codes:
        return
    # 锁内仅做双重检查 —— I/O 在锁外执行，防止阻塞事件循环
    with _cache_lock:
        if _bond_stock_codes:
            return
    try:
        # 加超时（15s）：防止 THS 接口 hang 死导致整个 startup 卡住
        df = _run_with_timeout(ak.bond_zh_cov_info_ths, timeout=15.0,
                               default=None, op_name="bond_zh_cov_info_ths")
        if df is not None and len(df) > 0:
            stock_col = None
            for c in ["正股代码", "股票代码", "代码"]:
                if c in df.columns:
                    stock_col = c
                    break
            bond_col = None
            for c in ["债券代码", "转债代码", "可转债代码"]:
                if c in df.columns:
                    bond_col = c
                    break
            stock_codes = set()
            bond_codes = set()
            if stock_col:
                for v in df[stock_col].dropna():
                    s = str(v).strip()
                    if s and s.isdigit() and len(s) == 6 and not s.startswith(("8", "9")):
                        stock_codes.add(s)
            if bond_col:
                for v in df[bond_col].dropna():
                    s = str(v).strip()
                    # 债券代码通常是 6 位数字，以 11、12、13 开头
                    if s and s.isdigit() and len(s) == 6 and s.startswith(("11", "12", "13")):
                        bond_codes.add(s)
            # I/O 完成后，在锁内赋值
            with _cache_lock:
                _bond_stock_codes = stock_codes
                _bond_codes = bond_codes
            logger.info(f"[DataEnrich] Auto-loaded {len(stock_codes)} bond stock codes and {len(bond_codes)} bond codes from THS")
    except Exception as e:
        logger.debug(f"[DataEnrich] Auto-load bond stock codes failed: {e}")


_bond_codes: set[str] = set()  # 债券代码集合（用于 bond_count 统计）


@_with_metrics
def _refresh_spot_cache():
    try:
        logger.info("[DataEnrich] Refreshing stock spot via Sina + push2.eastmoney.com (PE/PB/turnover)...")
        import requests as _req
        import time as _time
        from concurrent.futures import ThreadPoolExecutor
        _headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

        df = ak.stock_zh_a_spot()
        if df is None or df.empty:
            logger.warning("[DataEnrich] stock_zh_a_spot returned empty, skipping spot refresh")
            return 0
        all_codes = set()
        sina_map = {}
        for _, r in df.iterrows():
            raw_code = str(r.get("代码", "")).strip().lower()
            if not raw_code or raw_code.startswith("bj"):
                continue
            s_code = raw_code[2:] if (raw_code.startswith("sz") or raw_code.startswith("sh")) else raw_code
            all_codes.add(s_code)
            sina_map[s_code] = {
                "change_pct": _sf(r.get("涨跌幅")),
                "price": _sf(r.get("最新价")),
                "volume": _sf(r.get("成交额")),
                # NOTE: Sina stock_zh_a_spot does NOT provide circ_mv (流通市值) in akshare 1.18.x.
                # circ_mv would need EM ulist.np/get (f20/f21) or a separate API call.
                # We keep volume as the liquidity proxy (AGENTS.md #44).
            }
        all_codes = list(all_codes)

        pe_map: dict[str, float] = {}
        pb_map: dict[str, float] = {}
        tr_map: dict[str, float] = {}

        def _fetch_batch(batch: list[str]) -> dict[str, dict]:
            secids = ','.join(
                f"{'1' if c.startswith('6') else '0'}.{c}" for c in batch
            )
            try:
                r = _run_with_timeout(
                    lambda: _req.get(
                        'https://push2.eastmoney.com/api/qt/ulist.np/get',
                        params={'fields': 'f12,f9,f23,f8,f20,f21',
                                'secids': secids, 'ut': 'bd1d9ddb04089700cf9c27f6f7426281'},
                        headers=_headers, timeout=15,
                    ),
                    timeout=30, default=None, op_name="spot_batch",
                    quiet_errors=True,
                )
                if r is None:
                    return {}
                data = r.json()
                result = {}
                if not isinstance(data, dict):
                    return result
                if data.get('data') and data['data'].get('diff'):
                    for item in data['data']['diff']:
                        code = item.get('f12', '')
                        if not code:
                            continue
                        result[code] = {
                            'pe': item.get('f9', 0),
                            'pb': item.get('f23', 0),
                            'tr': item.get('f8', 0),
                            'total_mv': item.get('f20', 0),
                            'circ_mv': item.get('f21', 0),
                        }
                return result
            except Exception:
                return {}

        batch_size = 50
        batches = [all_codes[i:i + batch_size] for i in range(0, len(all_codes), batch_size)]
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(_fetch_batch, b) for b in batches]
            done, pending = concurrent.futures.wait(
                futures, timeout=300, return_when=concurrent.futures.ALL_COMPLETED
            )
            if pending:
                logger.warning(f"[DataEnrich] Spot batch: {len(pending)} (of {len(futures)}) futures unfinished after 300s")
                for fut in pending:
                    fut.cancel()
            for i, future in enumerate(done):
                batch_result = future.result()
                for code, vals in batch_result.items():
                    if vals.get('pe') and vals['pe'] > 0:
                        pe_map[code] = round(vals['pe'], 2)
                    if vals.get('pb') and vals['pb'] > 0:
                        pb_map[code] = round(vals['pb'], 2)
                    if vals.get('tr') is not None and vals['tr'] >= 0:
                        tr_map[code] = round(vals['tr'], 2)
                    if vals.get('total_mv') and vals['total_mv'] > 0:
                        sina_map.setdefault(code, {})['total_mv'] = round(vals['total_mv'], 2)
                    if vals.get('circ_mv') and vals['circ_mv'] > 0:
                        sina_map.setdefault(code, {})['circ_mv'] = round(vals['circ_mv'], 2)
                if (i + 1) % 5 == 0:
                    _time.sleep(0.3)

        if len(pe_map) < len(all_codes) * 0.3:
            logger.info(f"[DataEnrich] ulist only got {len(pe_map)}/{len(all_codes)}, trying stock/get fallback")
            def _fetch_single(code: str) -> dict:
                secid = f"{'1' if code.startswith('6') else '0'}.{code}"
                try:
                    r = _run_with_timeout(
                        lambda: _req.get(
                            'https://push2.eastmoney.com/api/qt/stock/get',
                            params={'fields': 'f57,f162,f167,f168,f20,f21', 'secid': secid},
                            headers=_headers, timeout=8,
                        ),
                        timeout=25, default=None, op_name="spot_single",
                        quiet_errors=True,
                    )
                    if r is None:
                        return {}
                    # 防御性：r.json() 可能返回 None 或抛出 JSONDecodeError
                    try:
                        json_data = r.json()
                        if not isinstance(json_data, dict):
                            return {}
                        d = json_data.get('data') or {}
                    except Exception:
                        return {}
                    if d:
                        return {code: {
                            'pe': d.get('f162', 0),
                            'pb': d.get('f167', 0),
                            'tr': d.get('f168', 0),
                            'total_mv': d.get('f20', 0),
                            'circ_mv': d.get('f21', 0),
                        }}
                except Exception:
                    pass
                return {}

            missing = [c for c in all_codes if c not in pe_map or c not in pb_map]
            if not missing:
                pass  # all filled
            else:
                # Quick sample to test if endpoint is alive
                sample = missing[:5]
                sample_ok = 0
                for code in sample:
                    res = _fetch_single(code)
                    if res:
                        sample_ok += 1
                        for c, vals in res.items():
                            if vals.get('pe') and vals['pe'] > 0:
                                pe_map[c] = round(vals['pe'], 2)
                            if vals.get('pb') and vals['pb'] > 0:
                                pb_map[c] = round(vals['pb'], 2)
                            if vals.get('tr') is not None and vals['tr'] >= 0:
                                tr_map[c] = round(vals['tr'], 2)
                            if vals.get('total_mv') and vals['total_mv'] > 0:
                                sina_map.setdefault(c, {})['total_mv'] = round(vals['total_mv'], 2)
                            if vals.get('circ_mv') and vals['circ_mv'] > 0:
                                sina_map.setdefault(c, {})['circ_mv'] = round(vals['circ_mv'], 2)
                # If sample fails completely, skip individual fallback to avoid wasting 20+ min
                if sample_ok == 0:
                    logger.warning("[DataEnrich] EM stock/get sample all failed, skipping individual fallback")
                else:
                    remaining = [c for c in missing if c not in pe_map or c not in pb_map]
                    if remaining:
                        logger.info(f"[DataEnrich] Fallback: fetching {len(remaining)} stocks individually")
                        with ThreadPoolExecutor(max_workers=6) as ex:
                            futures = []
                            for i, code in enumerate(remaining):
                                futures.append(ex.submit(_fetch_single, code))
                                if (i + 1) % 30 == 0:
                                    _time.sleep(0.5)
                            done, pending = concurrent.futures.wait(
                                futures, timeout=180, return_when=concurrent.futures.ALL_COMPLETED
                            )
                            if pending:
                                logger.warning(f"[DataEnrich] Spot single fallback: {len(pending)} (of {len(futures)}) futures unfinished after 180s")
                                for fut in pending:
                                    fut.cancel()
                            for future in done:
                                res = future.result()
                                for code, vals in res.items():
                                    if vals.get('pe') and vals['pe'] > 0 and code not in pe_map:
                                        pe_map[code] = round(vals['pe'], 2)
                                    if vals.get('pb') and vals['pb'] > 0 and code not in pb_map:
                                        pb_map[code] = round(vals['pb'], 2)
                                    if vals.get('tr') is not None and vals['tr'] >= 0 and code not in tr_map:
                                        tr_map[code] = round(vals['tr'], 2)
                                    if vals.get('total_mv') and vals['total_mv'] > 0:
                                        sina_map.setdefault(code, {})['total_mv'] = round(vals['total_mv'], 2)
                                    if vals.get('circ_mv') and vals['circ_mv'] > 0:
                                        sina_map.setdefault(code, {})['circ_mv'] = round(vals['circ_mv'], 2)

        if _bond_stock_codes:
            bond_missing = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
        else:
            _ensure_bond_stock_codes()
            if _bond_stock_codes:
                bond_missing = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
            else:
                bond_missing = []
                logger.warning("[DataEnrich] _bond_stock_codes empty, skipping Baidu fallback")

        if bond_missing:
            logger.info(f"[DataEnrich] {len(bond_missing)} bond stocks missing PE/PB, trying Baidu fallback")
            _fill_pe_pb_from_baidu(bond_missing, pe_map, pb_map)

        if _bond_stock_codes:
            bond_missing2 = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
        else:
            _ensure_bond_stock_codes()
            if _bond_stock_codes:
                bond_missing2 = [c for c in _bond_stock_codes if c not in pe_map or c not in pb_map]
            else:
                # AGENTS.md #42: 不处理全A股，避免30+分钟fallback
                bond_missing2 = []
                logger.warning("[DataEnrich] _bond_stock_codes empty, skipping THS fallback")

        if bond_missing2:
            logger.info(f"[DataEnrich] {len(bond_missing2)} bond stocks still missing PE/PB, trying THS fallback")
            _fill_pe_pb_from_ths(bond_missing2, pe_map, pb_map, sina_map)

        # [yfinance] Tier 4: 仅对 bond stocks 补充，不处理全A股
        if _bond_stock_codes:
            all_missing_pe = [c for c in _bond_stock_codes if c not in pe_map]
            all_missing_pb = [c for c in _bond_stock_codes if c not in pb_map]
        else:
            all_missing_pe = []
            all_missing_pb = []
        all_missing = list(set(all_missing_pe + all_missing_pb))
        if all_missing and len(all_missing) > len(bond_missing2 or []):
            logger.info(f"[DataEnrich] {len(all_missing)} bond stocks still missing PE/PB, trying yfinance fallback")
            _fill_pe_pb_from_yfinance(all_missing[:300], pe_map, pb_map)

        result = {}
        for code in all_codes:
            sina = sina_map.get(code, {})
            entry = {
                "pe": pe_map.get(code),
                "pb": pb_map.get(code),
                "change_pct": sina.get("change_pct"),
                "price": sina.get("price"),
                "volume": sina.get("volume"),
                "turnover_rate": tr_map.get(code),
                "total_mv": sina.get("total_mv"),
                "circ_mv": sina.get("circ_mv"),
            }
            result[code] = entry

        if pe_map and len(pe_map) >= len(all_codes) * 0.1:
            _set_global_map("_spot_map", result, replace=True)
            _save_cache(_SPOT_CACHE, result)
            logger.info(f"[DataEnrich] Stock spot: {len(result)} stocks, {len(pe_map)} PE, {len(pb_map)} PB, {len(tr_map)} turnover")
            return len(result)
        else:
            logger.warning(f"[DataEnrich] Stock spot refresh poor quality ({len(pe_map)} PE / {len(all_codes)} stocks), merging with existing cache")
            if not _spot_map:
                _load_spot_cache()
            with _cache_lock:
                existing = dict(_spot_map) if _spot_map else {}
            merged = {}
            for code in all_codes:
                old = existing.get(code, {})
                new = result.get(code, {})
                merged[code] = {
                    "pe": new.get("pe") if new.get("pe") is not None else old.get("pe"),
                    "pb": new.get("pb") if new.get("pb") is not None else old.get("pb"),
                    "change_pct": new.get("change_pct") if new.get("change_pct") is not None else old.get("change_pct"),
                    "price": new.get("price") if new.get("price") is not None else old.get("price"),
                    "volume": new.get("volume") if new.get("volume") is not None else old.get("volume"),
                    "turnover_rate": new.get("turnover_rate") if new.get("turnover_rate") is not None else old.get("turnover_rate"),
                    "total_mv": new.get("total_mv") if new.get("total_mv") is not None else old.get("total_mv"),
                    "circ_mv": new.get("circ_mv") if new.get("circ_mv") is not None else old.get("circ_mv"),
                }
            _set_global_map("_spot_map", merged, replace=True)
            _save_cache(_SPOT_CACHE, merged)
            merged_pe = sum(1 for v in merged.values() if isinstance(v, dict) and v.get("pe") is not None)
            logger.info(f"[DataEnrich] Stock spot merged: {len(merged)} stocks, {merged_pe} PE (from cache)")
            return len(merged)
    except Exception as e:
        logger.warning(f"[DataEnrich] Stock spot refresh failed: {e}")
        _load_spot_cache()


@_with_metrics
def _refresh_fund_flow_cache():
    # 快速检查：缓存已有充足数据时（>4500 只），仅尝试 1 次 API 调用，失败就直接用缓存
    # 避免 3 次重试 + 多个 fallback 累计耗时 5+ 分钟
    has_cache = _fund_flow_map and len(_fund_flow_map) > 4500
    max_attempts = 1 if has_cache else 3
    for attempt in range(max_attempts):
        try:
            logger.info(f"[DataEnrich] Refreshing fund flow rank attempt {attempt+1}/{max_attempts}...")
            df = ak.stock_individual_fund_flow_rank(indicator="今日")
            if df is None or len(df) == 0:
                raise ValueError("stock_individual_fund_flow_rank returned empty")
            result = {}
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                if not code:
                    continue
                result[code] = {
                    "net_main": _sf(r.get("今日主力净流入-净额")),
                    "net_main_pct": _sf(r.get("今日主力净流入-净占比")),
                    "net_super": _sf(r.get("今日超大单净流入-净额")),
                    "net_big": _sf(r.get("今日大单净流入-净额")),
                }
            _set_global_map("_fund_flow_map", result, replace=True)
            _save_cache(_FUND_FLOW_CACHE, result)
            logger.info(f"[DataEnrich] Fund flow: {len(result)} stocks")
            return len(result)
        except Exception as e:
            logger.warning(f"[DataEnrich] Fund flow attempt {attempt+1} failed: {e}")
            time.sleep(5 * (attempt + 1))
    # 所有重试失败：先看是否有可用的磁盘缓存，避免做无用的 spot_em/individual fallback
    if not _fund_flow_map:
        _load_fund_flow_cache()
    if _fund_flow_map:
        logger.warning(f"[DataEnrich] Fund flow: using existing cache ({len(_fund_flow_map)} stocks) to avoid slow fallbacks")
        return len(_fund_flow_map)
    # 只有缓存完全为空时（首次启动），才做后续 fallback
    logger.warning("[DataEnrich] Fund flow: no cache, trying stock_zh_a_spot_em fallback...")
    # spot_em fallback
    logger.warning("[DataEnrich] Fund flow: trying stock_zh_a_spot_em fallback...")
    spot_em_result = _refresh_fund_flow_from_spot_em()
    if spot_em_result:
        merged = {**_fund_flow_map, **spot_em_result}
        _set_global_map("_fund_flow_map", merged)
        _save_cache(_FUND_FLOW_CACHE, merged)
        logger.info(f"[DataEnrich] Fund flow: spot_em merged {len(spot_em_result)} → total {len(merged)}")
        return len(merged)
    # Individual fallback
    ff_codes = list(_bond_stock_codes) if _bond_stock_codes else []
    if not ff_codes:
        _ensure_bond_stock_codes()
        ff_codes = list(_bond_stock_codes) if _bond_stock_codes else []
    if ff_codes:
        logger.info(f"[DataEnrich] Fund flow: trying individual fallback for {len(ff_codes)} bond stocks")
        individual_result = _refresh_fund_flow_individual(ff_codes)
        if individual_result:
            merged = dict(_fund_flow_map) if _fund_flow_map else {}
            for code, entry in individual_result.items():
                if code not in merged:
                    merged[code] = entry
            _set_global_map('_fund_flow_map', merged)
            _save_cache(_FUND_FLOW_CACHE, merged)
            logger.info(f"[DataEnrich] Fund flow: individual merged {len(individual_result)} → total {len(merged)}")
            return len(merged)
    # TDX fallback (skipped - no directional data)
    return len(_fund_flow_map) if _fund_flow_map else 0


def _refresh_fund_flow_from_spot_em():
    """填充资金流向数据 — 返回 dict，不直接修改全局 map，由父级决定如何合并"""
    try:
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or len(df) == 0:
                raise ValueError("stock_zh_a_spot_em returned empty")
            flow_cols = [c for c in df.columns if '主力' in str(c)]
            if not flow_cols:
                raise ValueError("No fund flow columns in stock_zh_a_spot_em")
            net_col = next((c for c in flow_cols if '净流入' in str(c) and '占比' not in str(c)), None)
            pct_col = next((c for c in flow_cols if '占比' in str(c)), None)
            if not net_col:
                raise ValueError("No net inflow column found")
            result = {}
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                if not code:
                    continue
                entry = {"net_main": _sf(r.get(net_col))}
                if pct_col:
                    entry["net_main_pct"] = _sf(r.get(pct_col))
                # Try to find super/big order columns
                super_col = next((c for c in df.columns if '超大单' in str(c) and '净流入' in str(c) and '占比' not in str(c)), None)
                big_col = next((c for c in df.columns if '大单' in str(c) and '净流入' in str(c) and '占比' not in str(c) and '超大单' not in str(c)), None)
                if super_col:
                    entry["net_super"] = _sf(r.get(super_col))
                if big_col:
                    entry["net_big"] = _sf(r.get(big_col))
                if entry["net_main"] is not None:
                    result[code] = entry
            if result:
                logger.info(f"[DataEnrich] Fund flow from spot_em: {len(result)} stocks (caller decides merge)")
            return result
        except Exception:
            # stock_zh_a_spot_em 失败时不使用成交额近似，避免方向错误（成交额无正负方向）
            return {}
    except Exception as e:
        logger.warning(f"[DataEnrich] Fund flow spot_em fallback failed: {e}")
        return {}


def _refresh_fund_flow_individual(codes: list[str]) -> dict:
    """用单只股票资金流向接口补充缺失数据 — 仅针对债券正股"""
    try:
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_one(code: str):
            try:
                market = "sh" if code.startswith("6") else "sz"
                df = ak.stock_individual_fund_flow(stock=code, market=market)
                if df is None or len(df) == 0:
                    return code, None
                # 取最新一条数据
                latest = df.iloc[0]
                entry = {
                    "net_main": _sf(latest.get("主力净流入-净额")),
                    "net_main_pct": _sf(latest.get("主力净流入-净占比")),
                }
                # 尝试获取超大单/大单数据
                if "超大单净流入-净额" in df.columns:
                    entry["net_super"] = _sf(latest.get("超大单净流入-净额"))
                if "大单净流入-净额" in df.columns:
                    entry["net_big"] = _sf(latest.get("大单净流入-净额"))
                if entry["net_main"] is not None:
                    return code, entry
            except Exception:
                pass
            return code, None

        result = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(_fetch_one, c) for c in codes]
            done, pending = concurrent.futures.wait(
                futures, timeout=180, return_when=concurrent.futures.ALL_COMPLETED
            )
            if pending:
                logger.warning(f"[DataEnrich] Fund flow individual: {len(pending)} (of {len(futures)}) futures unfinished after 180s")
                for fut in pending:
                    fut.cancel()
            for i, future in enumerate(done):
                code, entry = future.result()
                if entry:
                    result[code] = entry
                if (i + 1) % 30 == 0:
                    time.sleep(0.5)
        if result:
            logger.info(f"[DataEnrich] Fund flow individual: {len(result)} stocks")
        return result
    except Exception as e:
        logger.warning(f"[DataEnrich] Fund flow individual fallback failed: {e}")
        return {}


@_with_metrics
def _refresh_fin_cache():
    try:
        logger.info("[DataEnrich] Refreshing financial data...")
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"
        logger.info(f"[DataEnrich] Using financial date: {fin_date}")
        df = ak.stock_yjbb_em(date=fin_date)

        cagr_date = f"{int(fin_date[:4])-3}{fin_date[4:]}"
        logger.info(f"[DataEnrich] CAGR base date: {cagr_date}")
        df_old = None
        try:
            df_old = ak.stock_yjbb_em(date=cagr_date)
        except Exception as e:
            logger.warning(f"[DataEnrich] CAGR base data fetch failed: {e}")

        old_rev = {}
        if df_old is not None:
            for _, r in df_old.iterrows():
                code = str(r.get("股票代码", "")).strip()
                rev = _sf(r.get("营业总收入-营业总收入"))
                if code and rev and rev > 0:
                    old_rev[code] = rev

        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            entry = {
                "roe": _sf(r.get("净资产收益率")),
                "gpm": _sf(r.get("销售毛利率")),
                "industry": str(r.get("所处行业", "")).strip() or None,
                "eps": _sf(r.get("每股收益")),
                "bps": _sf(r.get("每股净资产")),
                "revenue_yoy": _sf(r.get("营业总收入-同比增长")),
                "profit_yoy": _sf(r.get("净利润-同比增长")),
            }

            cur_rev = _sf(r.get("营业总收入-营业总收入"))
            if cur_rev and cur_rev > 0 and code in old_rev:
                try:
                    cagr = (math.pow(cur_rev / old_rev[code], 1.0 / 3.0) - 1) * 100
                    if -100 < cagr < 500:
                        entry["cagr"] = round(cagr, 2)
                except (ValueError, ZeroDivisionError):
                    pass

            result[code] = entry

        # [TDX] fallback: 用 TDX 补充缺失的财务数据
        fin_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not fin_codes:
            _ensure_bond_stock_codes()
            fin_codes = list(_bond_stock_codes) if _bond_stock_codes else list(result.keys())[:500]
        if fin_codes:
            _try_tdx_fin_fallback(fin_codes, result)

        # [THS] fallback: 用同花顺补充缺失的 ROE/GPM
        missing_roe = [c for c in fin_codes if c not in result or result.get(c, {}).get("roe") is None]
        if missing_roe:
            _try_ths_fin_fallback(missing_roe, result)

        _set_global_map("_fin_map", result, replace=True)
        _save_cache(_FIN_CACHE, result)
        cagr_count = sum(1 for v in result.values() if isinstance(v, dict) and v.get("cagr") is not None)
        logger.info(f"[DataEnrich] Financial: {len(result)} stocks, {cagr_count} with CAGR")
        return len(result)
    except Exception as e:
        logger.warning(f"[DataEnrich] Financial refresh failed: {e}", exc_info=True)
        if not _fin_map:
            _load_fin_cache()
        return len(_fin_map) if _fin_map else 0


@_with_metrics
def _refresh_debt_cache():
    try:
        logger.info("[DataEnrich] Refreshing debt & current ratio...")
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"
        df = ak.stock_zcfz_em(date=fin_date)
        if df is None or len(df) == 0:
            logger.warning(f"[DataEnrich] zcfz returned empty df for {fin_date}, skipping")
            return 0
        logger.info(f"[DataEnrich] zcfz fetched {len(df)} rows")
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            debt_ratio = _sf(r.get("资产负债率"))
            cash = _sf(r.get("资产-货币资金")) or 0
            receivables = _sf(r.get("资产-应收账款")) or 0
            inventory = _sf(r.get("资产-存货")) or 0
            total_debt = _sf(r.get("负债-总负债")) or 0

            entry = {}
            if debt_ratio is not None:
                entry["debt_ratio"] = debt_ratio

            if total_debt > 0 and cash + receivables + inventory >= 0:
                approx_ca = cash + receivables + inventory
                if approx_ca > 0:
                    cr = approx_ca / (total_debt * 0.65)
                    if 0 < cr < 50 and cr == cr:
                        entry["current_ratio"] = round(cr, 2)

            if entry:
                result[code] = entry

        # [TDX] fallback: 用 TDX 资产负债表数据补充缺失的资产负债率
        # 注意：TDX 补充必须在 _set_global_map 之前，否则 TDX 填充的数据不会持久化
        debt_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not debt_codes:
            _ensure_bond_stock_codes()
            debt_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if debt_codes:
            tdx_missing = [c for c in debt_codes if c not in result or not result.get(c, {}).get('debt_ratio')]
            if tdx_missing:
                adapter = get_tdx_adapter()
                logger.info(f'[DataEnrich][TDX] Debt: fetching balance sheet for {len(tdx_missing)} stocks')
                tdx_fin = adapter.fetch_finance_batch(tdx_missing)
                filled = 0
                for code, info in tdx_fin.items():
                    ta = info.get('total_assets')
                    tl = info.get('total_liabilities')
                    if ta and tl and ta > 0:
                        dr2 = round(tl / ta * 100, 2)
                        if 0 < dr2 < 100:
                            if code not in result:
                                result[code] = {}
                            result[code]['debt_ratio'] = dr2
                            filled += 1
                if filled:
                    logger.info(f'[DataEnrich][TDX] Debt: filled debt_ratio for {filled} stocks')

        _set_global_map("_debt_map", result, replace=True)
        _save_cache(_DEBT_CACHE, result)
        dr = sum(1 for v in result.values() if isinstance(v, dict) and "debt_ratio" in v)
        cr = sum(1 for v in result.values() if isinstance(v, dict) and "current_ratio" in v)
        logger.info(f"[DataEnrich] Debt: {len(result)} stocks, {dr} dr, {cr} cr")
        return len(result)
    except Exception as e:
        logger.warning(f"[DataEnrich] Debt refresh failed: {e}", exc_info=True)
        if not _debt_map:
            _load_debt_cache()
        return len(_debt_map) if _debt_map else 0


@_with_metrics
def _refresh_volatility_cache():
    try:
        logger.info("[DataEnrich] Refreshing stock volatility...")
        source = _spot_map if _spot_map else {}
        if not source:
            logger.warning("[DataEnrich] No spot data for volatility calc, skipping")
            return 0
        # _spot_map entries are {pe, pb, change_pct, price, volume, turnover_rate, total_mv, circ_mv}
        # circ_mv is now fetched from EM ulist.np/get (f21) for precise liquidity ranking.
        def _liquidity_proxy(item):
            v = item[1] if isinstance(item[1], dict) else {}
            # Prefer precise circ_mv (f21) from EM, fallback to volume proxy (AGENTS.md #44)
            circ = v.get("circ_mv", 0) or 0
            if circ > 0:
                return float(circ)
            return float(v.get("volume", 0) or 0)

        # 只处理与可转债正股相关的股票代码，避免在5000+全A股上浪费时间
        _ensure_bond_stock_codes()
        if _bond_stock_codes:
            bond_items = [(c, s) for c, s in source.items() if c in _bond_stock_codes]
            sorted_stocks = sorted(bond_items, key=_liquidity_proxy, reverse=True)
        else:
            sorted_stocks = sorted(source.items(), key=_liquidity_proxy, reverse=True)
        logger.info(f"[DataEnrich] Volatility: {len(sorted_stocks)} bond-related stocks to process")

        result = dict(_vol_map)
        em_fail_count = 0

        def _fetch_one_vol(item):
            code, _ = item
            if not code:
                return code, None, False
            vol = None
            em_failed = False
            # 优先: Tencent hist (AGENTS.md #35: try TX first, EM as fallback)
            try:
                df_tx = ak.stock_zh_a_hist_tx(
                    symbol=f"sh{code}" if code.startswith(('6', '9')) else f"sz{code}",
                    start_date=(datetime.now() - timedelta(days=90)).strftime("%Y%m%d"),
                    end_date=time.strftime("%Y%m%d"),
                    adjust="qfq",
                )
                if df_tx is not None and len(df_tx) >= 20:
                    closes = df_tx["close"].astype(float).values
                    closes = closes[closes > 0]
                    if len(closes) >= 20:
                        returns = np.diff(closes) / closes[:-1]
                        v = float(np.std(returns) * np.sqrt(252) * 100)
                        if 0 < v < 300:
                            vol = v
            except Exception:
                pass

            # 后备: East Money (TX 被封时)
            if vol is None:
                try:
                    df = ak.stock_zh_a_hist(
                        symbol=code, period="daily",
                        start_date=(datetime.now() - timedelta(days=90)).strftime("%Y%m%d"),
                        end_date=time.strftime("%Y%m%d"),
                        adjust="qfq",
                    )
                    if len(df) >= 20:
                        closes = df["收盘"].astype(float).values
                        returns = np.diff(closes) / closes[:-1]
                        v = float(np.std(returns) * np.sqrt(252) * 100)
                        if 0 < v < 300:
                            vol = v
                    else:
                        em_failed = True
                except Exception:
                    em_failed = True

            return code, vol, em_failed

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(_fetch_one_vol, item) for item in sorted_stocks]
            # AGENTS.md fix: as_completed 无 timeout 时，如果 AKShare 接口 hang 住，
            # 线程池会无限等待。添加 180s 总超时，超时的 future 直接丢弃。
            done, pending = concurrent.futures.wait(
                futures, timeout=180, return_when=concurrent.futures.ALL_COMPLETED
            )
            if pending:
                logger.warning(f"[DataEnrich] Volatility: {len(pending)} (of {len(futures)}) futures unfinished after 180s, keeping {len(done)}")
                for fut in pending:
                    fut.cancel()
            for i, future in enumerate(done):
                code, vol, em_failed = future.result()
                if vol is not None:
                    result[code] = round(vol, 2)
                if em_failed:
                    em_fail_count += 1
                if (i + 1) % 50 == 0:
                    logger.info(f"[DataEnrich] Volatility: {i + 1}/{len(sorted_stocks)} (EM fails={em_fail_count})")
                    time.sleep(1)  # 节流，无中间保存（避免崩溃后磁盘残留部分数据）

        # [TDX] fallback: 补充 EM/TX 均未覆盖的波动率（先于最终 save）
        if _bond_stock_codes:
            missing_vol_codes = [c for c in _bond_stock_codes if c not in result or result.get(c) is None]
        else:
            missing_vol_codes = [c for c in list(source.keys())[:300] if c not in result or result.get(c) is None]
        if missing_vol_codes:
            _try_tdx_volatility_fallback(missing_vol_codes, result)

        _set_global_map("_vol_map", result, replace=True)
        _save_cache(_VOL_CACHE, result)
        logger.info(f"[DataEnrich] Volatility: {len(result)} stocks")
        return len(result)
    except Exception as e:
        logger.warning(f"[DataEnrich] Volatility refresh failed: {e}")
        if not _vol_map:
            _load_vol_cache()
        return len(_vol_map) if _vol_map else 0


@_with_metrics
def _refresh_buyback_cache():
    try:
        logger.info("[DataEnrich] Refreshing buyback data...")
        df = ak.stock_repurchase_em()
        if df is None or len(df) == 0:
            logger.warning("[DataEnrich] Buyback: stock_repurchase_em returned empty")
            return 0
        result = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip()
            if not code:
                continue
            done = _sf(r.get("已回购金额"))
            plan = _sf(r.get("计划回购金额区间-上限"))
            amount = done if done and done > 0 else plan
            if amount and amount > 0:
                result[code] = round(amount / 1e8, 2)

        # [TDX] fallback: TDX 不直接提供回购数据，标记无回购的股票为 0
        # 注意：TDX 补充必须在 _set_global_map 之前，否则 TDX 填充的数据不会持久化
        buyback_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if not buyback_codes:
            _ensure_bond_stock_codes()
            buyback_codes = list(_bond_stock_codes) if _bond_stock_codes else []
        if buyback_codes:
            tdx_missing = [c for c in buyback_codes if c not in result]
            if tdx_missing:
                adapter = get_tdx_adapter()
                logger.info(f'[DataEnrich][TDX] Buyback: {len(tdx_missing)} codes missing from EM repurchase list')
                tdx_q = adapter.fetch_quotes(tdx_missing)
                # 注意：TDX 无法提供回购数据，仅用于确认正股存在性。
                # 不再将无回购标记为 0（避免与"数据缺失"混淆），
                # 只保留实际有回购的数据。
                for code, q in tdx_q.items():
                    if code not in result and q.get('price', 0) > 0:
                        pass  # 正股存在但无回购数据，不写入 0

        _set_global_map("_buyback_map", result, replace=True)
        _save_cache(_BUYBACK_CACHE, result)
        logger.info(f"[DataEnrich] Buyback: {len(result)} stocks")
        return len(result)
    except Exception as e:
        logger.warning(f"[DataEnrich] Buyback refresh failed: {e}")
        if not _buyback_map:
            _load_buyback_cache()
        return len(_buyback_map) if _buyback_map else 0


@_with_metrics
def _refresh_mgmt_cache():
    try:
        logger.info("[DataEnrich] Refreshing mgmt buy price...")
        result = {}
        # 如果缓存已有数据先加载，防止外部数据源全部失败时丢失历史
        if _mgmt_map:
            result.update(_mgmt_map)

        # 三个数据源（em_detail 180s, em_ggcg 180s, cninfo 120s）改为并行执行，
        # 整体时间从串行的 ~480s 缩短到 ~180s（最慢那个的耗时）
        import threading as _threading
        _source_results: dict[str, list] = {}
        _source_lock = _threading.Lock()

        def _fetch_em_detail():
            try:
                df = _run_with_timeout(
                    ak.stock_hold_management_detail_em,
                    timeout=180.0, default=None,
                    op_name="mgmt_em_detail",
                )
                if df is None or getattr(df, 'empty', True):
                    raise ValueError("EM detail returned None/empty")
                with _source_lock:
                    _source_results["em_detail"] = df
            except Exception as e:
                logger.warning(f"[DataEnrich] Mgmt EM detail (primary) failed: {type(e).__name__}: {str(e)[:100]}")

        def _fetch_ggcg():
            try:
                df = _run_with_timeout(
                    lambda: ak.stock_ggcg_em(symbol="全部"),
                    timeout=180.0, default=None, op_name="mgmt_ggcg_em"
                )
                if df is None:
                    raise TimeoutError("stock_ggcg_em timed out (180s)")
                with _source_lock:
                    _source_results["ggcg"] = df
            except Exception as e:
                logger.warning(f"[DataEnrich] Mgmt EM ggcg (fallback) failed: {type(e).__name__}: {str(e)[:100]}")

        def _fetch_cninfo():
            # macOS sandbox 默认跳过 cninfo（py_mini_racer dlsym 错误）
            if sys.platform == 'darwin' and os.environ.get("LH_MGMT_TRY_CNINFO", "").lower() not in ("1", "true", "yes"):
                logger.debug("[DataEnrich] Mgmt cninfo skipped (macOS sandbox + no LH_MGMT_TRY_CNINFO)")
                return
            try:
                df = _run_with_timeout(
                    lambda: ak.stock_hold_management_detail_cninfo(symbol="增持"),
                    timeout=120.0, default=None, op_name="mgmt_cninfo",
                )
                if df is None or getattr(df, 'empty', True):
                    raise ValueError("cninfo returned None/empty")
                with _source_lock:
                    _source_results["cninfo"] = df
            except Exception as e:
                logger.info(f"[DataEnrich] Mgmt cninfo (opt-in) skipped: {type(e).__name__}: {str(e)[:80]}")

        # 并行启动三个数据源
        threads = [
            _threading.Thread(target=_fetch_em_detail, daemon=True),
            _threading.Thread(target=_fetch_ggcg, daemon=True),
            _threading.Thread(target=_fetch_cninfo, daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=200)  # 总体 200s 上限，比单源最长的 180s 多 20s 缓冲

        # 处理 em_detail（primary）
        if "em_detail" in _source_results:
            df_em_detail = _source_results["em_detail"]
            count_before = len(result)
            for _, r in df_em_detail.iterrows():
                code = str(r.get("代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                # 过滤方向：只保留增持/买入
                direction = str(r.get("变动方向", "")).strip()
                if direction and direction not in ("增持", "买入", "新增", "净增持"):
                    continue
                price = _sf(r.get("成交均价"))
                if code and price and price > 0:
                    last_price = result.get(code, 0)
                    if price > last_price:
                        result[code] = price
            logger.info(f"[DataEnrich] Mgmt EM detail (primary): {len(result)} stocks (added {len(result) - count_before})")
            if len(result) > 100:
                _set_global_map("_mgmt_map", result, replace=True)
                _save_cache(_MGMT_CACHE, result)

        # 处理 em_ggcg（fallback）
        if "ggcg" in _source_results and len(result) < 200:
            df_ggcg = _source_results["ggcg"]
            count_before = len(result)
            for _, r in df_ggcg.iterrows():
                code = str(r.get("代码", "")).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                direction = str(r.get("持股变动信息-增减", "")).strip()
                if direction != "增持":
                    continue
                price = _sf(r.get("成交均价"))
                if not price:
                    price = _sf(r.get("最新价"))
                if code and price and price > 0:
                    last_price = result.get(code, 0)
                    if price > last_price:
                        result[code] = price
            logger.info(f"[DataEnrich] Mgmt EM ggcg (增持 only, fallback): {len(result)} stocks (added {len(result) - count_before})")

        # 处理 cninfo（opt-in）
        if "cninfo" in _source_results:
            df_cninfo = _source_results["cninfo"]
            count_before = len(result)
            for _, r in df_cninfo.iterrows():
                code = str(r.get("证券代码", "")).strip()
                price = _sf(r.get("成交均价"))
                if code and price and price > 0:
                    last_price = result.get(code, 0)
                    if price > last_price:
                        result[code] = price
            logger.info(f"[DataEnrich] Mgmt cninfo (opt-in): added {len(result) - count_before}")

        # Zero-fill: 对所有已知的股票代码中无增持数据的股票填充 0
        # mgmt_map 格式特殊：直接存储增持均价（float），非嵌套 dict
        # 使用 _get_bond_or_fallback_codes() 而非 _ensure_bond_stock_codes()，
        # 避免启动阶段 AKShare 信号量争用导致超时
        for code in _get_bond_or_fallback_codes():
            if code not in result:
                result[code] = 0

        if result:
            _set_global_map("_mgmt_map", result, replace=True)
            _save_cache(_MGMT_CACHE, result)
            logger.info(f"[DataEnrich] Mgmt buy price: {len(result)} stocks (final)")
            return len(result)
        else:
            logger.warning("[DataEnrich] Mgmt: no data from any source")
            if not _mgmt_map:
                _load_mgmt_cache()
            return len(_mgmt_map) if _mgmt_map else 0

    except Exception as e:
        logger.warning(f"[DataEnrich] Mgmt buy price refresh failed: {e}")
        if not _mgmt_map:
            _load_mgmt_cache()
        return len(_mgmt_map) if _mgmt_map else 0


# ==================== TDX 数据源统一 fallback 辅助函数 ====================

def _try_tdx_fin_fallback(codes: list[str], fin_map: dict):
    """从 TDX 补充缺失的财务数据（ROE/GPM/EPS 等）"""
    if not codes:
        return
    missing = [c for c in codes if c not in fin_map or not fin_map.get(c, {}).get("roe")]
    if not missing:
        return
    adapter = get_tdx_adapter()
    logger.info(f'[DataEnrich][TDX] Fin fallback: fetching financial data for {len(missing)} stocks')
    tdx_fin = adapter.fetch_finance_batch(missing)
    filled = 0
    for code, info in tdx_fin.items():
        if code not in fin_map:
            fin_map[code] = {}
        # Only write fields that enrich_quotes actually reads from fin_map:
        # roe, gpm, cagr, eps, bps, revenue_yoy, profit_yoy, industry.
        # pe/pb are read from _spot_map, NOT _fin_map, so writing them here
        # was dead data. (Bug 4a audit finding.)
        for key in ("roe", "eps", "bps", "gpm", "cagr"):
            if info.get(key) is not None and fin_map[code].get(key) is None:
                fin_map[code][key] = info[key]
                if key == "roe":
                    filled += 1
    if filled:
        logger.info(f'[DataEnrich][TDX] Fin fallback: filled ROE for {filled} stocks')


def _try_tdx_volatility_fallback(codes: list[str], vol_map: dict):
    """从 TDX K-line 补充缺失的波动率数据"""
    if not codes:
        return
    missing = [c for c in codes if c not in vol_map or vol_map.get(c) is None]
    if not missing:
        return
    adapter = get_tdx_adapter()
    logger.info(f'[DataEnrich][TDX] Vol fallback: fetching K-line volatility for {len(missing)} stocks')
    kline_data = adapter.fetch_kline_batch(missing, days=20)
    filled = 0
    for code, klines in kline_data.items():
        closes = [k.get("close") for k in klines if k.get("close") and k["close"] > 0]
        if len(closes) >= 5:
            returns_np = np.diff(closes) / closes[:-1]
            vol_val = float(np.std(returns_np) * np.sqrt(252) * 100) if len(returns_np) > 0 else None
            if vol_val is not None and vol_val > 0 and (code not in vol_map or vol_map.get(code) is None):
                vol_val = max(5, min(200, round(vol_val, 2)))
                vol_map[code] = vol_val
                filled += 1
    if filled:
        logger.info(f'[DataEnrich][TDX] Vol fallback: filled volatility for {filled} stocks')


def _try_tdx_names_fallback(name_map: dict):
    """从 TDX 补充缺失的股票名称"""
    adapter = get_tdx_adapter()
    logger.info('[DataEnrich][TDX] Names fallback: fetching stock names from security list')
    tdx_names = adapter.fetch_all_securities()
    added = 0
    for code, name in tdx_names.items():
        if code not in name_map and name and len(code) == 6 and code.isdigit():
            name_map[code] = name
            added += 1
    # 日志移到循环外，避免每条记录重复打印（A 股 ~5000+ 条）
    if added:
        logger.info(f'[DataEnrich][TDX] Names fallback: added {added} stock names')


def _try_ths_fin_fallback(codes: list[str], fin_map: dict):
    """从同花顺财务摘要补充缺失的 ROE/净利润增长率 (3 线程并发)"""
    if not codes:
        return
    total_filled = 0
    missing = codes[:]

    def _fetch_one(code):
        """单只股票 THS 财务数据获取"""
        try:
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
            if df is None or df.empty:
                return None
            row = df.iloc[0]  # 最新年度
            entry = {}
            roe = _sf(row.get("净资产收益率"))
            if roe is not None:
                entry["roe"] = roe
            # 注意：THS 财务摘要无"销售毛利率"列，有"销售净利率";
            # 为保持语义一致，此处仅回填 ROE 与净利润增长率，不回填 GPM
            npg = _sf(row.get("净利润同比增长率"))
            if npg is not None:
                entry["profit_yoy"] = npg
            return entry if entry else None
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor, as_completed
    while missing:
        batch = missing[:200]
        missing = missing[200:]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_fetch_one, code): code for code in batch}
            done, pending = concurrent.futures.wait(
                futures, timeout=180, return_when=concurrent.futures.ALL_COMPLETED
            )
            if pending:
                logger.warning(f"[DataEnrich] THS fin fallback: {len(pending)} (of {len(futures)}) futures unfinished after 180s")
                for fut in pending:
                    fut.cancel()
            for future in done:
                code = futures[future]
                try:
                    result = future.result()
                    if result:
                        entry = fin_map.setdefault(code, {})
                        for k, v in result.items():
                            if entry.get(k) is None or entry.get(k) == "":
                                entry[k] = v
                        total_filled += 1
                except Exception:
                    pass
        if missing:
            import time as _time
            _time.sleep(1)
    if total_filled:
        logger.info(f'[DataEnrich][THS] Fin fallback: filled financial data for {total_filled} stocks')


def _load_pledge_cache():
    global _pledge_map, _pledge_loaded
    cached = _load_cache(_PLEDGE_CACHE)
    if cached:
        _set_global_map("_pledge_map", {k: v for k, v in cached.items() if k != "_ts"})
    _pledge_loaded = True


def _load_event_cache():
    global _event_map, _event_loaded
    cached = _load_cache(_EVENT_CACHE)
    if cached:
        _set_global_map("_event_map", {k: v for k, v in cached.items() if k != "_ts"})
    _event_loaded = True


def _load_momentum_cache():
    global _momentum_map, _momentum_loaded
    cached = _load_cache(_MOMENTUM_CACHE)
    if cached:
        _set_global_map("_momentum_map", {k: v for k, v in cached.items() if k != "_ts"})
    _momentum_loaded = True


def _load_bond_outstanding_cache():
    global _bond_outstanding_map, _bond_outstanding_loaded
    cached = _load_cache(_BOND_OUTSTANDING_CACHE)
    if cached:
        _set_global_map("_bond_outstanding_map", {k: v for k, v in cached.items() if k != "_ts"})
    _bond_outstanding_loaded = True


def _load_call_status_cache():
    global _call_status_map, _call_status_loaded
    cached = _load_cache(_CALL_STATUS_CACHE)
    if cached:
        _set_global_map("_call_status_map", {k: v for k, v in cached.items() if k != "_ts"})
    _call_status_loaded = True


def _load_stock_name_cache():
    global _name_map, _name_loaded
    cached = _load_cache(_STOCK_NAME_CACHE)
    if cached:
        _set_global_map("_name_map", {k: v for k, v in cached.items() if k != "_ts"})
    _name_loaded = True


def _load_main_biz_cache():
    global _main_biz_map, _main_biz_loaded
    cached = _load_cache(_MAIN_BIZ_CACHE)
    if cached:
        _set_global_map("_main_biz_map", {k: v for k, v in cached.items() if k != "_ts"})
    _main_biz_loaded = True


def _load_analyst_rank_cache():
    global _analyst_rank_map, _analyst_rank_loaded
    cached = _load_cache(_ANALYST_RANK_CACHE)
    if cached:
        _set_global_map("_analyst_rank_map", {k: v for k, v in cached.items() if k != "_ts"})
    _analyst_rank_loaded = True


def _load_macro_cpi_cache():
    global _macro_cpi_map, _macro_cpi_loaded
    cached = _load_cache(_MACRO_CPI_CACHE)
    if cached:
        _set_global_map("_macro_cpi_map", {k: v for k, v in cached.items() if k != "_ts"})
    _macro_cpi_loaded = True


def _load_macro_ppi_cache():
    global _macro_ppi_map, _macro_ppi_loaded
    cached = _load_cache(_MACRO_PPI_CACHE)
    if cached:
        _set_global_map("_macro_ppi_map", {k: v for k, v in cached.items() if k != "_ts"})
    _macro_ppi_loaded = True


def _load_macro_m2_cache():
    global _macro_m2_map, _macro_m2_loaded
    cached = _load_cache(_MACRO_M2_CACHE)
    if cached:
        _set_global_map("_macro_m2_map", {k: v for k, v in cached.items() if k != "_ts"})
    _macro_m2_loaded = True


def _load_macro_lpr_cache():
    global _macro_lpr_map, _macro_lpr_loaded
    cached = _load_cache(_MACRO_LPR_CACHE)
    if cached:
        _set_global_map("_macro_lpr_map", {k: v for k, v in cached.items() if k != "_ts"})
    _macro_lpr_loaded = True


@_with_metrics
def _refresh_coupon_rate_cache():
    """刷新 coupon_rate 缓存。
    
    优先级:
    1. JISILU 集思录 (含完整票面利率)
    2. East Money bond_zh_cov_info (部分覆盖)
    3. 现有缓存（不主动清理）
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("[DataEnrich][CouponRate] akshare not installed, skip")
        return 0

    result = dict(_coupon_rate_map)  # 保留已有值

    # 1) JISILU 集思录 (主源)
    try:
        logger.info("[DataEnrich][CouponRate] Fetching from JISILU...")
        jsl_df = ak.bond_cb_jsl()
        if jsl_df is not None and not jsl_df.empty:
            for _, r in jsl_df.iterrows():
                code = r.get("代码") or r.get("债券代码")
                cr = r.get("利率") or r.get("票面利率")
                if code and cr is not None:
                    try:
                        cr_val = float(str(cr).replace("%", "").strip())
                        # 统一：JSL 返回的票面利率可能是百分比整数（如 1.5）或百分比小数（如 0.015）
                        # 大于 0.5 视为百分比整数，除以 100；否则保持原样
                        if cr_val > 0.5: cr_val = cr_val / 100
                        if 0 < cr_val <= 1:
                            result[str(code)] = cr_val
                    except (ValueError, TypeError):
                        continue
            logger.info(f"[DataEnrich][CouponRate] JISILU: {len(result)} codes")
    except Exception as e:
        logger.warning(f"[DataEnrich][CouponRate] JISILU failed: {e}")

    # 2) East Money 主列表（兜底）
    try:
        em_df = ak.bond_zh_cov()
        if em_df is not None and not em_df.empty:
            added = 0
            for _, r in em_df.iterrows():
                code = r.get("债券代码") or r.get("代码")
                cr = r.get("票面利率")
                if code and cr is not None and str(code) not in result:
                    try:
                        cr_val = float(str(cr).replace("%", "").strip())
                        if cr_val > 1: cr_val = cr_val / 100
                        if 0 < cr_val < 1:
                            result[str(code)] = cr_val
                            added += 1
                    except (ValueError, TypeError):
                        continue
            if added > 0:
                logger.info(f"[DataEnrich][CouponRate] EM: +{added} codes")
    except Exception as e:
        logger.warning(f"[DataEnrich][CouponRate] EM failed: {e}")

    # 写回缓存（用 _set_global_map 走锁路径，避免并发 update）
    if result:
        _save_cache(_COUPON_RATE_CACHE, result)
        _set_global_map("_coupon_rate_map", result, replace=True)
        logger.info(f"[DataEnrich][CouponRate] Final: {len(result)} codes")
    return len(result)


def _load_coupon_rate_cache():
    global _coupon_rate_map, _coupon_rate_loaded
    cached = _load_cache(_COUPON_RATE_CACHE)
    if cached:
        loaded = {k: v for k, v in cached.items() if k != "_ts"}
        _set_global_map("_coupon_rate_map", loaded, replace=True)
        logger.info(f"[DataEnrich][CouponRate] Loaded {len(loaded)} entries from cache")
    _coupon_rate_loaded = True


def _load_bond_price_cache():
    global _bond_price_map, _bond_price_loaded, _coupon_rate_map
    cached = _load_cache(_BOND_PRICE_CACHE)
    if cached:
        # 保留现有内存中的 coupon_rate（防止被不含 coupon_rate 的磁盘缓存覆盖）
        old_bp = _bond_price_map.copy() if _bond_price_map else {}
        loaded = {k: v for k, v in cached.items() if k != "_ts"}
        for code, entry in loaded.items():
            if isinstance(entry, dict):
                old = old_bp.get(code, {})
                if isinstance(old, dict) and old.get("coupon_rate") is not None and entry.get("coupon_rate") is None:
                    entry["coupon_rate"] = old["coupon_rate"]
        _set_global_map("_bond_price_map", loaded, replace=True)
    # 从独立缓存加载 coupon_rate（runner 写入，不会被 bond_price refresh 覆盖）
    _load_coupon_rate_cache()
    _bond_price_loaded = True


def _merge_jsl_bond_data(result: dict):
    """将集思录债券数据合并到 result 中 (带 120s 超时保护 + daemon 线程防挂起)"""
    try:
        logger.info("[DataEnrich][BondPrice] Fetching JISILU bond data...")
        import threading

        # 使用 daemon 线程执行 ak.bond_cb_jsl，避免 ThreadPoolExecutor 线程挂起
        # daemon=True 保证进程退出时线程自动终止，不会阻塞 shutdown
        # _cancelled 事件防止超时后线程返回数据仍占据内存（DataFrame 可达数 MB）
        # ⚠️ _cancelled 是局部变量，每次调用 _merge_jsl_bond_data 都会创建新实例，
        #    因此天然线程安全，无需 .clear()。若未来重构为实例/类变量，
        #    必须在每次调用开始时 _cancelled.clear() 重置状态。
        # 此处与模块级 _run_with_timeout 功能等价，但保留因需精细控制
        # "超时后丢弃 DataFrame 节省内存" 的语义。
        jsl_result = [None]
        jsl_error = [None]
        _cancelled = threading.Event()

        def _fetch_jsl():
            try:
                data = ak.bond_cb_jsl()
                # 如果调用方已超时放弃，不保存结果，让 GC 回收 DataFrame
                if not _cancelled.is_set():
                    jsl_result[0] = data
            except Exception as e:
                if not _cancelled.is_set():
                    jsl_error[0] = e

        t = threading.Thread(target=_fetch_jsl, daemon=True, name="jsl-fetch")
        t.start()
        t.join(timeout=120)

        if t.is_alive():
            # 标记已超时，阻止后续返回的 DataFrame 占据内存
            _cancelled.set()
            logger.warning(
                f"[DataEnrich][BondPrice] JISILU fetch timed out (120s), "
                f"thread={t.ident} (daemon), skipping"
            )
            return

        if jsl_error[0] is not None:
            logger.warning(f"[DataEnrich][BondPrice] JISILU fetch failed: {jsl_error[0]}")
            return

        df_jsl = jsl_result[0]
        if df_jsl is None or df_jsl.empty:
            logger.warning("[DataEnrich][BondPrice] bond_cb_jsl returned empty")
            return
        jsl_codes = set()
        for _, r in df_jsl.iterrows():
            code = str(r.get("代码", "")).strip()
            if not code:
                continue
            jsl_codes.add(code)
            if code not in result:
                result[code] = {}
            entry = result[code]
            # Price: only override if not already set by EM
            if "price" not in entry:
                price = _sf(r.get("现价", 0))
                if price and price > 0 and abs(price - 100.0) > 0.01:
                    entry["price"] = price
            if "change_pct" not in entry:
                change_pct = _sf(r.get("涨跌幅", 0))
                if change_pct is not None:
                    entry["change_pct"] = change_pct
            if "volume" not in entry:
                volume = _sf(r.get("成交额", 0))
                if volume and volume > 0:
                    entry["volume"] = volume
            # Enriched fields from JISILU
            stock_price = _sf(r.get("正股价", 0))
            if stock_price and stock_price > 0:
                entry["stock_price"] = stock_price
            stock_change = _sf(r.get("正股涨跌", 0))
            if stock_change is not None:
                entry["stock_change_pct"] = stock_change
            conv_price = _sf(r.get("转股价", 0))
            if conv_price and conv_price > 0:
                entry["conversion_price"] = conv_price
            conv_value = _sf(r.get("转股价值", 0))
            if conv_value and conv_value > 0:
                entry["conversion_value"] = conv_value
            premium = _sf(r.get("转股溢价率", 0))
            if premium is not None:
                entry["premium_ratio"] = premium
            dual_low = _sf(r.get("双低", 0))
            if dual_low and dual_low > 0:
                entry["dual_low"] = dual_low
            ytm = _sf(r.get("到期税前收益", 0))
            if ytm is not None:
                entry["ytm"] = ytm
            remaining = _sf(r.get("剩余规模", 0))
            if remaining and remaining > 0:
                entry["outstanding_scale"] = remaining
            turnover = _sf(r.get("换手率", 0))
            if turnover and turnover > 0:
                entry["turnover_rate"] = turnover
            rating = r.get("债券评级", "")
            if rating:
                entry["bond_rating"] = str(rating).strip()
            remaining_years = _sf(r.get("剩余年限", 0))
            if remaining_years and remaining_years > 0:
                entry["remaining_years"] = remaining_years
            stock_pb = _sf(r.get("正股PB", 0))
            if stock_pb and stock_pb > 0:
                entry["stock_pb"] = stock_pb
        jsl_count = len(jsl_codes)
        total_count = len(result)
        logger.info(f"[DataEnrich][BondPrice] JISILU merged: {total_count} total bonds (JISILU contributed {jsl_count} bonds)")
    except Exception as jsl_err:
        logger.warning(f"[DataEnrich][BondPrice] JISILU fetch failed: {jsl_err}")


@_with_metrics
def _refresh_bond_price_cache():
    """刷新债券实时价格缓存 (EM + JISILU + TDX 三层)
    当 data_enrich_runner.py 子进程不可用时，主进程也能自行刷新债券价格
    """
    try:
        logger.info("[DataEnrich] Refreshing bond price cache (EM + JISILU + TDX)...")
        result = {}

        # ── Primary: East Money real-time spot ──
        try:
            logger.info("[DataEnrich][BondPrice] Fetching EM bond spot quotes...")
            df_em = ak.bond_zh_hs_cov_spot()
            if df_em is not None and not df_em.empty:
                for _, r in df_em.iterrows():
                    code = str(r.get("code", "")).strip()
                    if not code or not code.isdigit() or len(code) != 6:
                        continue
                    entry = {}
                    price = _sf(r.get("trade", 0))
                    if price and price > 0 and abs(price - 100.0) > 0.01:
                        entry["price"] = price
                    change_pct = _sf(r.get("changepercent", 0))
                    if change_pct is not None:
                        entry["change_pct"] = change_pct
                    volume = _sf(r.get("amount", 0))
                    if volume is not None and volume > 0:
                        entry["volume"] = volume
                    if entry:
                        result[code] = entry
                em_count = len(result)
                logger.info(f"[DataEnrich][BondPrice] EM spot: {em_count} bonds")
            else:
                logger.warning("[DataEnrich][BondPrice] EM spot returned empty")
        except Exception as em_err:
            logger.warning(f"[DataEnrich][BondPrice] EM spot failed: {em_err}")

        # ── Secondary: JISILU enriched data ──
        _merge_jsl_bond_data(result)

        # ── Tertiary: TDX fallback for missing prices ──
        try:
            adapter = get_tdx_adapter()
            missing_codes = [c for c in result if not result[c].get("price")]
            if missing_codes:
                tdx_q = adapter.fetch_quotes(missing_codes[:100])
                filled = 0
                for code, q in tdx_q.items():
                    price = q.get("price")
                    if price and price > 0 and code in result and not result[code].get("price"):
                        result[code]["price"] = price
                        filled += 1
                if filled:
                    logger.info(f"[DataEnrich][BondPrice] TDX filled {filled} missing prices")
        except Exception as tdx_err:
            logger.debug(f"[DataEnrich][BondPrice] TDX fallback skipped: {tdx_err}")

        # 保留 runner 子进程写入的 coupon_rate（主进程不重新获取）
        # 必须在 _set_global_map 之前，因为 _set_global_map 会用 result 替换旧 map
        old_bp = _bond_price_map.copy() if _bond_price_map else {}
        for code, entry in result.items():
            old = old_bp.get(code, {})
            if isinstance(old, dict) and old.get("coupon_rate") is not None and entry.get("coupon_rate") is None:
                entry["coupon_rate"] = old["coupon_rate"]

        _set_global_map("_bond_price_map", result, replace=True)
        _save_cache(_BOND_PRICE_CACHE, result)
        _bond_price_loaded = True
        total_count = len(result)
        logger.info(f"[DataEnrich][BondPrice] Total: {total_count} bonds")
        return total_count
    except Exception as e:
        logger.warning(f"[DataEnrich][BondPrice] Bond price refresh failed: {e}")
        if not _bond_price_map:
            _load_bond_price_cache()
        return len(_bond_price_map) if _bond_price_map else 0


def _load_concept_cache():
    global _concept_map, _concept_loaded, _concept_source_map, _concept_source_loaded
    cached = _load_cache(_CONCEPT_CACHE)
    if cached:
        # ── 清洗：剔除老缓存里残留的指数/通道/规模/持仓等非真正概念 ──
        raw_concept_map = {k: v for k, v in cached.items() if k != "_ts"}
        cleaned_concept_map: dict[str, list[str]] = {}
        filtered_concept_names: set[str] = set()
        for scode, clist in raw_concept_map.items():
            if not isinstance(clist, list):
                continue
            kept = []
            for cn in clist:
                if not isinstance(cn, str):
                    continue
                if _is_non_concept(cn):
                    filtered_concept_names.add(cn)
                    continue
                kept.append(cn)
            if kept:
                cleaned_concept_map[scode] = kept
        if filtered_concept_names:
            logger.info(
                f'[DataEnrich] Concept cache sanitized: removed {len(filtered_concept_names)} '
                f'non-concept names from {len(raw_concept_map) - len(cleaned_concept_map)} stocks'
            )
            # 回写清洗后的缓存(下次启动不必再清洗)
            try:
                _save_cache(_CONCEPT_CACHE, {**cleaned_concept_map, "_ts": cached.get("_ts", 0)})
            except Exception as save_e:
                logger.debug(f'[DataEnrich] Concept cache save-back failed: {save_e}')
        _set_global_map("_concept_map", cleaned_concept_map, replace=True)
    _concept_loaded = True
    cached2 = _load_cache(_CONCEPT_SOURCE_CACHE)
    if cached2:
        raw_src_map = {k: v for k, v in cached2.items() if k != "_ts"}
        cleaned_src_map = {k: v for k, v in raw_src_map.items() if not _is_non_concept(k)}
        if len(cleaned_src_map) != len(raw_src_map):
            logger.info(f'[DataEnrich] Concept source map sanitized: {len(raw_src_map) - len(cleaned_src_map)} non-concept entries removed')
            try:
                _save_cache(_CONCEPT_SOURCE_CACHE, {**cleaned_src_map, "_ts": cached2.get("_ts", 0)})
            except Exception:
                pass
        _set_global_map("_concept_source_map", cleaned_src_map, replace=True)
    _concept_source_loaded = True


# 概念名称→搜索关键词映射规则
_CONCEPT_KEYWORD_MAP: dict[str, list[str]] = {
    "AI": ["智能", "AI", "人工", "算法", "深度"],
    "芯片": ["芯片", "半导体", "集成", "微", "晶圆"],
    "新能源": ["新能源", "光伏", "风电", "锂电", "电池", "充电"],
    "汽车": ["汽车", "汽配", "整车", "新能源车", "电动"],
    "医药": ["医药", "药", "医疗", "生物", "基因", "健康"],
    "金融": ["银行", "保险", "证券", "金融", "信托", "期货"],
    "科技": ["科技", "信息", "软件", "数字", "数据", "互联", "计算"],
    "通信": ["通信", "5G", "6G", "光", "星", "卫星"],
    "军工": ["军工", "国防", "航天", "航空", "装备"],
    "消费": ["消费", "食品", "饮料", "酒", "乳", "零售"],
    "地产": ["地产", "房产", "物业", "园区"],
    "电力": ["电力", "能源", "电网", "发电", "电气"],
    "化工": ["化工", "化学", "化纤", "材料", "石化"],
    "金属": ["金属", "有色", "钢铁", "黄金", "矿业", "合金"],
    "传媒": ["传媒", "影视", "游戏", "广告", "文化", "娱乐"],
    "机械": ["机械", "设备", "装备", "精密", "制造"],
    "环保": ["环保", "环境", "节能", "减排", "碳"],
    "农业": ["农业", "牧", "渔", "种", "粮", "林"],
    "建筑": ["建筑", "工程", "建设", "基建", "路桥"],
}


def _extract_concept_keywords(concept_name: str) -> list[str]:
    """从概念名称中提取搜索关键词"""
    keywords = []
    # 检查是否有预定义映射
    for root, kws in _CONCEPT_KEYWORD_MAP.items():
        if root in concept_name:
            keywords.extend(kws)
    # 提取概念名称本身的词
    parts = concept_name.replace('/', ' ').replace('、', ' ').replace('·', ' ').split()
    for part in parts:
        part = part.strip()
        if len(part) >= 2 and part not in keywords:
            keywords.append(part)
    # 去重并限制数量
    seen = set()
    return [k for k in keywords if not (k in seen or seen.add(k))][:5]


# ═══════════════════════════════════════════════════════════════════════════════
# 非概念板块排除 — 指数/通道/分类/标签/规模等非真正概念
# 用户要求：以下都不是真概念，统统换成同花顺/东财的真概念股
#   • 融资融券、转融券、沪股通、深股通、港股通、陆股通、北向资金
#   • 专精特新、ST板块、退市、预增/预减/预盈/预亏、扭亏、高送转、破净、转板、新股、次新股
#   • 综指、中证、上证、深证、标准普尔、MSCI中国、富时罗素、道琼斯、纳斯达克、恒生
#   • 创业板综指、深证综指、上证380、创业板指、科创50、沪深300、上证50、中证500、中证1000、国证、申万
#   • 小盘股、中盘股、大盘股、微盘股
#   • 机构重仓、QFII重仓/QFII中仓、券商重仓、社保重仓、基金重仓、信托重仓、保险重仓、私募重仓
# ═══════════════════════════════════════════════════════════════════════════════
_CONCEPT_EXCLUDE_EXACT: set[str] = {
    # ── 通道/分类 ──
    "融资融券", "转融券", "沪股通", "深股通", "港股通", "陆股通", "北向资金", "南向资金",
    # ── 政策标签 ──
    "专精特新", "ST板块", "ST", "*ST", "退市", "预增", "预减", "预盈", "预亏",
    "扭亏", "高送转", "破净", "破发", "转板", "新股", "次新股", "科创次新股",
    # ── 规模分类 ──
    "小盘股", "中盘股", "大盘股", "微盘股",
    # ── 持仓分类 ──
    "机构重仓", "券商重仓", "社保重仓", "基金重仓", "信托重仓", "保险重仓", "私募重仓",
    "QFII重仓", "QFII中仓", "qfii重仓", "qfii中仓",
    # ── 指数（中证/标准普尔等） ──
    "MSCI中国", "MSCI", "富时罗素", "标准普尔", "道琼斯", "纳斯达克", "恒生指数",
    "创业板综指", "深证综指", "上证综指", "上证380",
    # ── 常见别名 ──
    "标普", "中证500", "中证1000", "沪深300", "上证50", "科创50", "创业板指",
}

_CONCEPT_EXCLUDE_PATTERNS: tuple[str, ...] = (
    # ── 指数通配 ──
    "综指", "中证", "上证", "深证", "标准普尔", "MSCI", "富时罗素", "道琼斯",
    "纳斯达克", "恒生", "创业板指", "科创50", "沪深300", "上证50", "中证500",
    "中证1000", "国证", "申万", "标普", "上证380",
    # ── 规模分类通配 ──
    "小盘股", "中盘股", "大盘股", "微盘股",
    # ── 持仓分类通配 ──
    "机构重仓", "QFII", "qfii", "券商重仓", "社保重仓", "基金重仓", "信托重仓",
    "保险重仓", "私募重仓", "险资重仓",
    # ── 通道/资金通配 ──
    "融资融券", "转融券", "沪股通", "深股通", "港股通", "陆股通", "北向", "南向",
    # ── 标签通配 ──
    "专精特新", "ST板块", "预增", "预减", "预盈", "预亏", "扭亏", "高送转",
    "破净", "破发", "转板", "次新股",
)


def _is_non_concept(name: str) -> bool:
    """判断是否为非概念板块（指数/分类/标签/规模/通道等非真正概念）

    返回 True 表示应当从概念缓存中剔除。
    """
    if not name:
        return True
    n = name.strip()
    if not n:
        return True
    if n in _CONCEPT_EXCLUDE_EXACT:
        return True
    n_lower = n.lower()
    for pat in _CONCEPT_EXCLUDE_PATTERNS:
        if pat.lower() in n_lower:
            return True
    return False


@_with_metrics
def _build_concept_cache():
    """Build concept cache with EM + THS + TDX keyword expansion"""
    # ── 保护：如果现有缓存足够大（已由 patch 脚本合并了 EM+THS），跳过重建 ──
    cached = _load_cache(_CONCEPT_CACHE)
    if cached:
        real = {k: v for k, v in cached.items() if k != '_ts'}
        # 检查概念丰富度：至少有 300 个不同概念名称且最大概念 > 100 只股票
        from collections import defaultdict
        _rev = defaultdict(int)
        for scodes in real.values():
            if isinstance(scodes, list):
                for cn in scodes:
                    _rev[cn] += 1
        total_pairs = sum(len(scodes) for scodes in real.values() if isinstance(scodes, list))
        if len(_rev) >= 300 and (max(_rev.values()) > 100 or total_pairs > 50000):
            logger.info(f'[DataEnrich] Concept cache already has {len(_rev)} concepts ({total_pairs} pairs), skipping rebuild')
            return len(real)

    try:
        logger.info('[DataEnrich] Building concept cache (EM + THS + TDX keyword expansion)...')
        result: dict[str, list[str]] = {}
        source_map: dict[str, dict[str, bool]] = {}
        tdx_concept_map: dict[str, list[str]] = {}  # concept_name -> [stock_codes from TDX]

        # Source 1: EastMoney
        try:
            df = ak.stock_board_concept_name_em()
            if df is None or len(df) == 0:
                logger.warning("[DataEnrich] Concept: stock_board_concept_name_em returned empty")
                raise ValueError("EM concept empty")
            em_count = 0
            em_skipped = 0
            em_concept_names: list[str] = []
            
            # Pre-filter valid boards
            valid_boards = []
            for _, board in df.iterrows():
                bcode = str(board.get('板块代码', '')).strip()
                bname = str(board.get('板块名称', '')).strip()
                if not bcode or not bname:
                    continue
                if _is_non_concept(bname):
                    em_skipped += 1
                    continue
                valid_boards.append((bcode, bname))
            
            # Parallel fetch concept constituents with ThreadPoolExecutor
            def _fetch_concept_cons(args):
                bcode, bname = args
                try:
                    cons = ak.stock_board_concept_cons_em(symbol=bcode)
                    scodes = []
                    for _, c in cons.iterrows():
                        scode = str(c.get('代码', '')).strip()
                        if scode:
                            scodes.append(scode)
                    return bname, scodes
                except Exception:
                    return bname, []
            
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_fetch_concept_cons, (bcode, bname)): (bcode, bname) for bcode, bname in valid_boards}
                done, pending = concurrent.futures.wait(
                    futures, timeout=300, return_when=concurrent.futures.ALL_COMPLETED
                )
                if pending:
                    logger.warning(f"[DataEnrich] Concept EM: {len(pending)} (of {len(futures)}) futures unfinished after 300s")
                    for fut in pending:
                        fut.cancel()
                for fut in done:
                    bname, scodes = fut.result()
                    if scodes:
                        for scode in scodes:
                            result.setdefault(scode, []).append(bname)
                        source_map.setdefault(bname, {'em': False, 'ths': False, 'tdx': False})['em'] = True
                        em_count += 1
                        em_concept_names.append(bname)
            logger.info(f'[DataEnrich] Concept EM: {em_count} boards kept, {em_skipped} non-concept boards filtered, {len(result)} stocks')
        except Exception as e:
            logger.warning(f'[DataEnrich] Concept EM failed: {e}')
            em_concept_names = []

        # Source 2: THS — stock_board_concept_cons_ths 在 akshare 1.18.x 中不存在
        # (py_mini_racer dlsym 错误)，仅获取概念名称列表，成分股通过 TDX 关键词补充
        ths_concept_names: list[str] = []
        try:
            df2 = ak.stock_board_concept_name_ths()
            if df2 is None or len(df2) == 0:
                raise ValueError("stock_board_concept_name_ths returned empty")
            ths_skipped = 0
            for _, board in df2.iterrows():
                bcode = str(board.get('代码', '')).strip()
                bname = str(board.get('名称', '')).strip()
                if not bcode or not bname:
                    continue
                if _is_non_concept(bname):
                    ths_skipped += 1
                    continue
                ths_concept_names.append(bname)
                source_map.setdefault(bname, {'em': False, 'ths': True, 'tdx': False})
            logger.info(f'[DataEnrich] Concept THS names: {len(ths_concept_names)} boards, {ths_skipped} filtered (cons API unavailable in akshare 1.18.x)')
        except Exception as e2:
            logger.warning(f'[DataEnrich] Concept THS name fetch failed: {e2}')

        # Source 3: TDX keyword expansion — 为每个概念用关键词搜索更多成分股
        try:
            adapter = get_tdx_adapter()
            all_concept_names = set(em_concept_names + ths_concept_names)
            tdx_total_added = 0
            tdx_concepts_filled = 0

            # 获取 TDX 全量证券列表用于名称匹配
            tdx_securities = adapter.fetch_all_securities()
            if tdx_securities:
                logger.info(f'[DataEnrich][TDX] Concept: expanding {len(all_concept_names)} concepts with TDX keyword search')

                for _ci, cname in enumerate(sorted(all_concept_names)):
                    keywords = _extract_concept_keywords(cname)
                    if not keywords:
                        continue

                    added_for_concept = 0
                    for kw in keywords:
                        # 从 TDX 证券列表中查找名称包含关键词的股票
                        # 排除指数代码: 399xxx(深证指数), 880xxx(行业指数), 950xxx(债券指数)
                        for code, name in tdx_securities.items():
                            if not code or len(code) != 6 or not code.isdigit():
                                continue
                            if not name:
                                continue
                            if code.startswith(('399', '880', '950')):
                                continue  # 跳过指数
                            if kw.lower() in name.lower():
                                # 检查该股票是否已在概念中
                                if code in result:
                                    if cname not in result[code]:
                                        result[code].append(cname)
                                        added_for_concept += 1
                                else:
                                    result[code] = [cname]
                                    added_for_concept += 1

                    if added_for_concept > 0:
                        source_map.setdefault(cname, {'em': False, 'ths': False, 'tdx': False})['tdx'] = True
                        tdx_total_added += added_for_concept
                        tdx_concepts_filled += 1

                    # 每 10 个概念暂停一下
                    if _ci % 10 == 9:
                        import time as _time
                        _time.sleep(0.1)

                if tdx_total_added:
                    logger.info(f'[DataEnrich][TDX] Concept: expanded {tdx_concepts_filled} concepts, added {tdx_total_added} stock-concept pairs')

        except Exception as tdx_e:
            logger.debug(f'[DataEnrich][TDX] Concept keyword expansion failed: {tdx_e}')

        if result:
            _set_global_map('_concept_map', result, replace=True)
            _save_cache(_CONCEPT_CACHE, result)
            if source_map:
                _set_global_map('_concept_source_map', source_map, replace=True)
                _save_cache(_CONCEPT_SOURCE_CACHE, source_map)
            # 统计
            concepts_with_tdx = sum(1 for s in source_map.values() if s.get('tdx'))
            logger.info(f'[DataEnrich] Concept total: {len(result)} stocks, {len(source_map)} concepts ({concepts_with_tdx} TDX-expanded)')
            return len(result)
    except Exception as e:
        logger.warning(f'[DataEnrich] Concept build failed: {e}')
    return len(_concept_map) if _concept_map else 0


def _compute_momentum_from_kline(stock_code: str, kline_dir: Path) -> Optional[dict]:
    """从 kline JSON 文件计算多周期动量"""
    try:
        kf = kline_dir / f'{stock_code}.json'
        if not kf.exists():
            return None
        with open(kf) as f:
            data = json.load(f)
        days = data.get('days', [])
        if not isinstance(days, list) or len(days) < 5:
            return None
        closes = [d['close'] for d in days if isinstance(d, dict) and d.get('close', 0) > 0]
        if len(closes) < 5:
            return None
        closes.reverse()
        today = closes[-1]
        if today <= 0:
            return None
        result = {}
        periods = {'5d': 5, '10d': 10, '20d': 20, '60d': 60}
        for label, n in periods.items():
            if len(closes) > n:
                prev = closes[-(n + 1)]
                if prev > 0:
                    result[label] = round((today - prev) / prev * 100, 2)
        return result if result else None
    except Exception:
        return None


@_with_metrics
def _refresh_momentum_cache():
    """从 kline 文件或 Tencent/TDX K-line 计算多周期动量"""
    try:
        logger.info('[DataEnrich] Refreshing multi-timeframe momentum...')
        result = {}
        kline_dir = _CACHE_DIR / 'kline'
        if kline_dir.exists() and list(kline_dir.iterdir()):
            kline_files = [f.stem for f in kline_dir.iterdir() if f.suffix == '.json']
            for sc in _bond_stock_codes or []:
                mom = _compute_momentum_from_kline(sc, kline_dir)
                if mom:
                    result[sc] = mom
            for sc in kline_files:
                if sc in result:
                    continue
                mom = _compute_momentum_from_kline(sc, kline_dir)
                if mom:
                    result[sc] = mom
        # Fallback: Tencent hist
        if len(result) < 50:
            missing = [c for c in (_bond_stock_codes or []) if c not in result]
            if missing:
                logger.info(f'[DataEnrich] Momentum fallback: computing from Tencent hist for {len(missing)} stocks')
                for code in missing[:200]:
                    try:
                        prefix = 'sh' if code.startswith('6') else 'sz'
                        df = ak.stock_zh_a_hist_tx(symbol=f'{prefix}{code}', adjust='hfq')
                        if df is None or df.empty:
                            continue
                        closes = df['close'].values.astype(float)
                        closes = closes[closes > 0]
                        if len(closes) < 10:
                            continue
                        today = closes[-1]
                        if today <= 0:
                            continue
                        mom = {}
                        periods = {'5d': 5, '10d': 10, '20d': 20, '60d': 60}
                        for label, n in periods.items():
                            if len(closes) > n:
                                prev = closes[-(n + 1)]
                                if prev > 0:
                                    mom[label] = round((today - prev) / prev * 100, 2)
                        if mom:
                            result[code] = mom
                    except Exception:
                        continue

        # [TDX] fallback: 用 TDX K-line 补充仍缺失的动量
        _ensure_bond_stock_codes()
        if _bond_stock_codes:
            missing_mom = [c for c in _bond_stock_codes if c not in result]
            if missing_mom:
                logger.info(f'[DataEnrich][TDX] Momentum: fetching K-line for {len(missing_mom)} stocks')
                adapter = get_tdx_adapter()
                klines = adapter.fetch_kline_batch(missing_mom, days=65)
                for code, kline in klines.items():
                    closes = [k.get('close') for k in kline if k.get('close') and k['close'] > 0]
                    if len(closes) > 5:
                        today = closes[-1]
                        mom = {}
                        periods = {'5d': 5, '10d': 10, '20d': 20, '60d': 60}
                        for label, n in periods.items():
                            if len(closes) > n:
                                prev = closes[-(n + 1)]
                                if prev > 0:
                                    mom[label] = round((today - prev) / prev * 100, 2)
                        if mom:
                            result[code] = mom

        # 合并：保留已有缓存 + 新计算结果，避免部分新数据丢失
        if result:
            existing = dict(_momentum_map) if _momentum_map else {}
            merged = {**existing, **result}
            _set_global_map('_momentum_map', merged)
            _save_cache(_MOMENTUM_CACHE, merged)
            logger.info(f'[DataEnrich][TDX] Momentum: {len(result)} new + {len(existing)} existing = {len(merged)} stocks (kline+tx+tdx)')
            return len(merged)
        else:
            logger.warning(f'[DataEnrich] Momentum: no new data, kept existing')
            _load_momentum_cache()
            return len(_momentum_map) if _momentum_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Momentum refresh failed: {e}')
        if not _momentum_map:
            _load_momentum_cache()
        return len(_momentum_map) if _momentum_map else 0


@_with_metrics
def _refresh_event_cache():
    """从 THS + TDX 补充债券到期事件"""
    result = {}
    now_ts = datetime.now()
    try:
        logger.info('[DataEnrich] Refreshing bond event data...')

        # Primary: THS bond info
        try:
            df = ak.bond_zh_cov_info_ths()
            if df is None or len(df) == 0:
                raise ValueError("bond_zh_cov_info_ths returned empty")
            for _, r in df.iterrows():
                bc = str(r.get('债券代码', '')).strip()
                if not bc or len(bc) != 6:
                    continue
                score = 0.5
                title = '正常'
                et = r.get('到期时间')
                if et and str(et) not in ('', 'NaT', 'None', 'nan'):
                    try:
                        mdt = datetime.strptime(str(et)[:10], '%Y-%m-%d')
                        days = (mdt - now_ts).days
                        if days < 30:
                            score = 0.95
                            title = f'即将到期 ({days}天)'
                        elif days < 90:
                            score = 0.85
                            title = f'临近到期 ({days}天)'
                        elif days < 180:
                            score = 0.7
                            title = f'半年内到期 ({days}天)'
                        else:
                            score = 0.4
                            title = f'正常 (剩余{days}天)'
                    except Exception:
                        pass
                result[bc] = {'score': score, 'title': title, 'date': now_ts.strftime('%Y%m%d')}
            if len(result) > 100:
                logger.info(f'[DataEnrich] Event: {len(result)} bonds (from THS)')
            else:
                raise ValueError(f'THS only returned {len(result)} bonds')
        except Exception as e:
            logger.warning(f'[DataEnrich] THS event failed: {e}')

            # [TDX] fallback: 从 TDX 补充债券代码
            if len(result) < 100:
                try:
                    logger.info('[DataEnrich][TDX] Event: checking TDX for bond codes')
                    adapter = get_tdx_adapter()
                    tdx_bonds = adapter.fetch_securities_by_name('转债')
                    for b in tdx_bonds:
                        bc = b.get('code', '')
                        if bc and len(bc) == 6 and bc not in result:
                            result[bc] = {
                                'score': 0.5,
                                'title': '[TDX] 正常 (无到期信息)',
                                'date': now_ts.strftime('%Y%m%d'),
                            }
                except Exception as tdx_e:
                    logger.debug(f'[DataEnrich][TDX] Event fallback failed: {tdx_e}')

        # AGENTS.md #48: 合并已有缓存（部分失败时不丢失之前数据）
        if _event_map and len(result) < len(_event_map):
            merged = {**dict(_event_map), **result}
            logger.info(f'[DataEnrich] Event: 合并缓存 {len(result)} + 已有 {len(_event_map)} = {len(merged)}')
            result = merged

        if result:
            _set_global_map('_event_map', result, replace=True)
            _save_cache(_EVENT_CACHE, result)  # 始终持久化，避免 TDX 补充数据丢失
            logger.info(f'[DataEnrich] Event: {len(result)} bonds published')
            return len(result)
        else:
            _load_event_cache()
            return len(_event_map) if _event_map else 0
    except Exception as outer_e:
        logger.warning(f'[DataEnrich] Event refresh outer error: {outer_e}')
        _load_event_cache()
        return len(_event_map) if _event_map else 0



@_with_metrics
def _refresh_pledge_cache():
    """刷新质押比例 — EM + CNINFO + [TDX] fin fallback"""
    try:
        logger.info('[DataEnrich] Refreshing pledge ratio...')
        df = ak.stock_gpzy_pledge_ratio_em()
        if df is None or len(df) == 0:
            logger.warning("[DataEnrich] Pledge: stock_gpzy_pledge_ratio_em returned empty, will try fallback")
            raise ValueError("EM pledge empty")
        result = {}
        for _, r in df.iterrows():
            code = str(r.get('股票代码', '')).strip()
            ratio = _sf(r.get('质押比例'))
            if code and ratio is not None:
                result[code] = ratio
        if len(result) > 100:
            _set_global_map('_pledge_map', result, replace=True)
            _save_cache(_PLEDGE_CACHE, result)
            logger.info(f'[DataEnrich] Pledge: {len(result)} stocks (from EM)')
            return len(result)
        logger.warning(f'[DataEnrich] Pledge EM: only {len(result)} stocks, trying CNINFO fallback...')
    except Exception as e:
        logger.warning(f'[DataEnrich] Pledge EM failed: {e}')

    # CNINFO fallback — 非 macOS 环境自动启用，macOS sandbox 需设 LH_PLEDGE_TRY_CNINFO=1
    if sys.platform != 'darwin' or os.environ.get("LH_PLEDGE_TRY_CNINFO", "").lower() in ("1", "true", "yes"):
        try:
            df2 = ak.stock_cg_equity_mortgage_cninfo()
            result2 = {}
            if df2 is not None and len(df2) > 0:
                for _, r in df2.iterrows():
                    code = str(r.get('证券代码', '')).strip()
                    # 修复：仅在有 ratio 字段时写入，避免质押股数（单位：股）与质押比例（单位：%）混淆
                    ratio = _sf(r.get('质押比例'))
                    if code and ratio is not None:
                        if code not in result2 or ratio > result2[code]:
                            result2[code] = ratio
            # AGENTS.md #48: 即使 CNINFO 返回数较少，也合并 EM 部分结果而非丢弃
            # CNINFO 优先（数值更新），EM 补缺；合并后只要总数 > 100 就接受
            merged = {**result, **result2}
            if len(merged) > 100:
                _set_global_map('_pledge_map', merged)
                _save_cache(_PLEDGE_CACHE, merged)
                logger.info(f'[DataEnrich] Pledge: {len(merged)} stocks (EM={len(result)}, CNINFO={len(result2)})')
                return len(merged)
        except Exception as e2:
            logger.warning(f'[DataEnrich] Pledge CNINFO failed: {e2}')
    else:
        logger.debug("[DataEnrich] Pledge CNINFO skipped (macOS sandbox + no LH_PLEDGE_TRY_CNINFO)")

    # [TDX] fallback: TDX 无法提供质押比例数据，仅做日志记录
    _ensure_bond_stock_codes()
    if _bond_stock_codes:
        tdx_missing = [c for c in _bond_stock_codes if c not in _pledge_map]
        if tdx_missing:
            logger.debug(f'[DataEnrich][TDX] Pledge: {len(tdx_missing)} stocks still missing (TDX has no pledge ratio data)')

    if not _pledge_map:
        _load_pledge_cache()
    return len(_pledge_map) if _pledge_map else 0


@_with_metrics
def _refresh_bond_outstanding_cache():
    """刷新债券剩余规模 — JSL + bond_zh_cov + [TDX]"""
    try:
        logger.info('[DataEnrich] Refreshing bond outstanding scale...')
        df = ak.bond_cb_redeem_jsl()
        if df is None or len(df) == 0:
            logger.warning('[DataEnrich] Bond outstanding: JSL returned empty df')
            df = None
        result = {}
        if df is not None:
            for _, r in df.iterrows():
                code = str(r.get('代码', '')).strip()
                remaining = float(r.get('剩余规模', 0) or 0)
                if code and remaining > 0:
                    result[code] = remaining
        if result:
            logger.info(f'[DataEnrich] Bond outstanding: {len(result)} bonds from JSL')
        else:
            logger.warning('[DataEnrich] Bond outstanding: JSL empty')

        # bond_zh_cov fallback — 仅用于确认债券存在性，不写入发行规模（原始规模 ≠ 剩余规模）
        try:
            df2 = ak.bond_zh_cov()
            if df2 is not None and not df2.empty:
                count_added = 0
                for _, r in df2.iterrows():
                    code = str(r.get('债券代码', '')).strip()
                    if not code or code in result:
                        continue
                    # bond_zh_cov 无“剩余规模”列，只有“发行规模”(原始发行规模)。
                    # 为避免误导（原始规模总是 ≥ 剩余规模），此处不回填数值，
                    # 仅将该债券标记为 0.0（表示“存在但剩余规模未知”）。
                    result[code] = 0.0
                    count_added += 1
                if count_added:
                    logger.info(f'[DataEnrich] Bond outstanding: {count_added} bonds confirmed via bond_zh_cov (scale unknown, marked 0)')
        except Exception as e2:
            logger.warning(f'[DataEnrich] bond_zh_cov fallback failed: {e2}')

        # [TDX] fallback: 用 TDX 确认债券存在性
        if len(result) < 100:
            try:
                adapter = get_tdx_adapter()
                tdx_bonds = adapter.fetch_securities_by_name('转债')
                logger.info(f'[DataEnrich][TDX] Bond outstanding: found {len(tdx_bonds)} bonds from TDX')
                for b in tdx_bonds:
                    bc = b.get('code', '')
                    if bc and len(bc) == 6 and bc not in result:
                        result[bc] = 0.0
                logger.info(f'[DataEnrich][TDX] Bond outstanding: total {len(result)} bonds after TDX check')
            except Exception as tdx_e:
                logger.debug(f'[DataEnrich][TDX] Bond outstanding fallback failed: {tdx_e}')

        if result:
            _set_global_map('_bond_outstanding_map', result, replace=True)
            _save_cache(_BOND_OUTSTANDING_CACHE, result)
            logger.info(f'[DataEnrich] Bond outstanding: total {len(result)} bonds')
            return len(result)
        else:
            logger.warning('[DataEnrich] Bond outstanding: all sources empty')
            if not _bond_outstanding_map:
                _load_bond_outstanding_cache()
            return len(_bond_outstanding_map) if _bond_outstanding_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Bond outstanding refresh failed: {e}')
        if not _bond_outstanding_map:
            _load_bond_outstanding_cache()
        return len(_bond_outstanding_map) if _bond_outstanding_map else 0


@_with_metrics
def _refresh_call_status_cache():
    """刷新强赎状态 — bond_zh_cov(全量默认"未触发") + JSL(覆盖实际状态)"""
    try:
        result = {}

        # Step 1: 从 bond_zh_cov 获取全部转债代码（~1024只），默认 "未触发"
        # 带重试：首次失败后等5s重试一次
        for _attempt in range(2):
            try:
                logger.info('[DataEnrich] Refreshing call status from bond_zh_cov...')
                df_all = ak.bond_zh_cov()
                if df_all is None or len(df_all) == 0:
                    raise ValueError("bond_zh_cov returned empty")
                for _, r in df_all.iterrows():
                    code = str(r.get("债券代码", "")).strip()
                    if code and len(code) == 6 and code.isdigit():
                        result[code] = "未触发"
                logger.info(f'[DataEnrich] Call status bond_zh_cov: {len(result)} total bonds')
                break
            except Exception as e_all:
                if _attempt == 0:
                    logger.warning(f'[DataEnrich] Call status bond_zh_cov attempt 1 failed: {e_all}, retrying in 5s...')
                    import time as _retry_t; _retry_t.sleep(5)
                else:
                    logger.warning(f'[DataEnrich] Call status bond_zh_cov attempt 2 failed: {e_all}')

        # Step 2: Overlay JSL redemption status (覆盖实际强赎状态)
        logger.info('[DataEnrich] Refreshing call status from JSL...')
        df = ak.bond_cb_redeem_jsl()
        jsl_count = 0
        if df is None or len(df) == 0:
            logger.warning('[DataEnrich] Call status: JSL returned empty df')
        else:
            for _, r in df.iterrows():
                code = str(r.get('代码', '')).strip()
                status = str(r.get('强赎状态', '')).strip()
                if code and status and status != '':
                    result[code] = status
                    jsl_count += 1
        logger.info(f'[DataEnrich] Call status JSL overlay: {jsl_count} bonds with active status')

        # [TDX] fallback: 仍然不足时补充
        if len(result) < 50:
            try:
                logger.info('[DataEnrich][TDX] Call status: <50 bonds, checking TDX')
                adapter = get_tdx_adapter()
                tdx_bonds = adapter.fetch_securities_by_name('转债')
                for b in tdx_bonds:
                    bc = b.get('code', '')
                    if bc and len(bc) == 6 and bc not in result:
                        result[bc] = '未公告'
                if len(result) > 0:
                    logger.info(f'[DataEnrich][TDX] Call status: {len(result)} bonds (incl. TDX fills)')
            except Exception as tdx_e:
                logger.debug(f'[DataEnrich][TDX] Call status fallback failed: {tdx_e}')

        if result:
            _set_global_map('_call_status_map', result, replace=True)
            _save_cache(_CALL_STATUS_CACHE, result)
            logger.info(f'[DataEnrich] Call status: {len(result)} bonds (JSL={jsl_count}, default=未触发={len(result)-jsl_count})')
            return len(result)
        else:
            if not _call_status_map:
                _load_call_status_cache()
            return len(_call_status_map) if _call_status_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Call status refresh failed: {e}')
        if not _call_status_map:
            _load_call_status_cache()
        return len(_call_status_map) if _call_status_map else 0


@_with_metrics
def _refresh_stock_name_cache():
    """刷新正股名称缓存 — Sina + THS + [TDX]"""
    try:
        logger.info('[DataEnrich] Refreshing stock names...')
        df = ak.stock_info_a_code_name()
        if df is None or len(df) == 0:
            logger.warning("[DataEnrich] Names: stock_info_a_code_name returned empty")
            return 0
        result = {}
        for _, r in df.iterrows():
            code = str(r.get('code', '')).strip().zfill(6)
            name = str(r.get('name', '')).strip()
            if code and name:
                result[code] = name
        # THS supplement
        try:
            df_ths = ak.bond_zh_cov_info_ths()
            if df_ths is not None and not df_ths.empty:
                for _, r in df_ths.iterrows():
                    sc = str(r.get('正股代码', '')).strip()
                    sn = str(r.get('正股简称', '')).strip()
                    if sc and sn and sc not in result:
                        result[sc] = sn
        except Exception:
            pass
        # [TDX] fallback: 用 TDX 补充缺失名称
        _try_tdx_names_fallback(result)

        if len(result) > 100:
            _set_global_map('_name_map', result, replace=True)
            _save_cache(_STOCK_NAME_CACHE, result)
            logger.info(f'[DataEnrich][TDX] Stock names: {len(result)} stocks')
            return len(result)
        else:
            logger.warning(f'[DataEnrich] Names: only {len(result)} names fetched, keeping existing cache')
            if not _name_map:
                _load_stock_name_cache()
            return len(_name_map) if _name_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Stock name refresh failed: {e}')
        if not _name_map:
            _load_stock_name_cache()
        return len(_name_map) if _name_map else 0


@_with_metrics
def _refresh_main_biz_cache():
    """刷新主营业务缓存 — 从 _industry_map 回退，或尝试 THS 行业明细"""
    global _main_biz_map
    try:
        logger.info('[DataEnrich] Refreshing main business...')
        result = {}
        # Step 1: 优先从已有的 _industry_map 回退（行业≈主营业务）
        if _industry_map:
            result = _industry_map.copy()
            logger.info(f'[DataEnrich] Main biz: {len(result)} from industry_map fallback')
        # Step 2: THS 行业明细补充（如有更细分的业务数据）
        if len(result) < 50:
            try:
                logger.info('[DataEnrich] Main biz: industry_map too small, trying THS industry detail')
                df = ak.stock_industry_detail_ths()
                if df is not None and len(df) > 0:
                    cols = set(df.columns.astype(str))
                    expected_cols = {'代码', '主营业务', '行业', '板块名称'}
                    if not any(c in cols for c in expected_cols):
                        logger.warning(f'[DataEnrich] Main biz THS columns mismatch: got {list(cols)[:10]}, expected any of {expected_cols}')
                    for _, r in df.iterrows():
                        code = str(r.get('代码', '')).strip()
                        biz = str(r.get('主营业务', '') or r.get('行业', '') or r.get('板块名称', '')).strip()
                        if code and biz and code not in result:
                            result[code] = biz
                    logger.info(f'[DataEnrich] Main biz THS overlay: {len(result)} total')
            except Exception as ths_e:
                logger.debug(f'[DataEnrich] Main biz THS fallback failed: {ths_e}')
        if result:
            _set_global_map('_main_biz_map', result, replace=True)
            _save_cache(_MAIN_BIZ_CACHE, result)
            logger.info(f'[DataEnrich] Main biz: {len(result)} entries')
            return len(result)
        else:
            if not _main_biz_map:
                _load_main_biz_cache()
            return len(_main_biz_map) if _main_biz_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Main biz refresh failed: {e}')
        if not _main_biz_map:
            _load_main_biz_cache()
        return len(_main_biz_map) if _main_biz_map else 0


@_with_metrics
def _refresh_analyst_rank_cache():
    """刷新分析师排名缓存 — 东方财富分析师指数"""
    global _analyst_rank_map
    try:
        logger.info('[DataEnrich] Refreshing analyst rank...')
        result = {}
        try:
            df = ak.stock_analyst_rank_em()
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    name = str(r.get('分析师名称', '') or r.get('分析师', '')).strip()
                    idx = str(r.get('年度指数', '') or r.get('指数', '')).strip()
                    ret = str(r.get('收益率', '') or r.get('年度收益率', '')).strip()
                    if name:
                        result[name] = {
                            'annual_index': idx,
                            'annual_return': ret,
                            'industry': str(r.get('行业', '')).strip(),
                        }
                logger.info(f'[DataEnrich] Analyst rank: {len(result)} analysts')
        except Exception as em_e:
            logger.warning(f'[DataEnrich] Analyst rank EM failed: {em_e}')
        if result:
            _set_global_map('_analyst_rank_map', result, replace=True)
            _save_cache(_ANALYST_RANK_CACHE, result)
            return len(result)
        else:
            if not _analyst_rank_map:
                _load_analyst_rank_cache()
            return len(_analyst_rank_map) if _analyst_rank_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Analyst rank refresh failed: {e}')
        if not _analyst_rank_map:
            _load_analyst_rank_cache()
        return len(_analyst_rank_map) if _analyst_rank_map else 0


@_with_metrics
def _refresh_macro_cpi_cache():
    """刷新宏观 CPI 缓存"""
    global _macro_cpi_map
    try:
        logger.info('[DataEnrich] Refreshing macro CPI...')
        result = {}
        try:
            df = ak.macro_china_cpi()
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    month = str(r.get('月份', '') or r.get('时间', '')).strip()
                    val = r.get('全国-当月', None)
                    yoy = r.get('全国-同比增长', None)
                    if month:
                        result[month] = {
                            'value': float(val) if val is not None and not (isinstance(val, float) and math.isnan(val)) else None,
                            'yoy': float(yoy) if yoy is not None and not (isinstance(yoy, float) and math.isnan(yoy)) else None,
                        }
                logger.info(f'[DataEnrich] Macro CPI: {len(result)} months')
        except Exception as cpi_e:
            logger.warning(f'[DataEnrich] Macro CPI failed: {cpi_e}')
        if result:
            _set_global_map('_macro_cpi_map', result, replace=True)
            _save_cache(_MACRO_CPI_CACHE, result)
            return len(result)
        else:
            if not _macro_cpi_map:
                _load_macro_cpi_cache()
            return len(_macro_cpi_map) if _macro_cpi_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Macro CPI refresh failed: {e}')
        if not _macro_cpi_map:
            _load_macro_cpi_cache()
        return len(_macro_cpi_map) if _macro_cpi_map else 0


@_with_metrics
def _refresh_macro_ppi_cache():
    """刷新宏观 PPI 缓存"""
    global _macro_ppi_map
    try:
        logger.info('[DataEnrich] Refreshing macro PPI...')
        result = {}
        try:
            df = ak.macro_china_ppi()
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    month = str(r.get('月份', '') or r.get('时间', '')).strip()
                    val = r.get('当月', None)
                    yoy = r.get('当月同比增长', None)
                    if month:
                        result[month] = {
                            'value': float(val) if val is not None and not (isinstance(val, float) and math.isnan(val)) else None,
                            'yoy': float(yoy) if yoy is not None and not (isinstance(yoy, float) and math.isnan(yoy)) else None,
                        }
                logger.info(f'[DataEnrich] Macro PPI: {len(result)} months')
        except Exception as ppi_e:
            logger.warning(f'[DataEnrich] Macro PPI failed: {ppi_e}')
        if result:
            _set_global_map('_macro_ppi_map', result, replace=True)
            _save_cache(_MACRO_PPI_CACHE, result)
            return len(result)
        else:
            if not _macro_ppi_map:
                _load_macro_ppi_cache()
            return len(_macro_ppi_map) if _macro_ppi_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Macro PPI refresh failed: {e}')
        if not _macro_ppi_map:
            _load_macro_ppi_cache()
        return len(_macro_ppi_map) if _macro_ppi_map else 0


@_with_metrics
def _refresh_macro_m2_cache():
    """刷新宏观 M2 缓存"""
    global _macro_m2_map
    try:
        logger.info('[DataEnrich] Refreshing macro M2...')
        result = {}
        try:
            df = ak.macro_china_m2_yearly()
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    date = str(r.get('日期', '') or r.get('时间', '') or r.get('月份', '')).strip()
                    val = r.get('今值', None)
                    pred = r.get('预测值', None)
                    prev = r.get('前值', None)
                    if date:
                        result[date] = {
                            'value': float(val) if val is not None and not (isinstance(val, float) and math.isnan(val)) else None,
                            'predicted': float(pred) if pred is not None and not (isinstance(pred, float) and math.isnan(pred)) else None,
                            'previous': float(prev) if prev is not None and not (isinstance(prev, float) and math.isnan(prev)) else None,
                        }
                logger.info(f'[DataEnrich] Macro M2: {len(result)} months')
        except Exception as m2_e:
            logger.warning(f'[DataEnrich] Macro M2 failed: {m2_e}')
        if result:
            _set_global_map('_macro_m2_map', result, replace=True)
            _save_cache(_MACRO_M2_CACHE, result)
            return len(result)
        else:
            if not _macro_m2_map:
                _load_macro_m2_cache()
            return len(_macro_m2_map) if _macro_m2_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Macro M2 refresh failed: {e}')
        if not _macro_m2_map:
            _load_macro_m2_cache()
        return len(_macro_m2_map) if _macro_m2_map else 0


@_with_metrics
def _refresh_macro_lpr_cache():
    """刷新宏观 LPR 缓存"""
    global _macro_lpr_map
    try:
        logger.info('[DataEnrich] Refreshing macro LPR...')
        result = {}
        try:
            df = ak.macro_china_lpr()
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    date = str(r.get('TRADE_DATE', '') or r.get('日期', '')).strip()
                    lpr1y = r.get('LPR1Y', None)
                    lpr5y = r.get('LPR5Y', None)
                    if date:
                        result[date] = {
                            'lpr1y': float(lpr1y) if lpr1y is not None and not (isinstance(lpr1y, float) and math.isnan(lpr1y)) else None,
                            'lpr5y': float(lpr5y) if lpr5y is not None and not (isinstance(lpr5y, float) and math.isnan(lpr5y)) else None,
                        }
                logger.info(f'[DataEnrich] Macro LPR: {len(result)} days')
        except Exception as lpr_e:
            logger.warning(f'[DataEnrich] Macro LPR failed: {lpr_e}')
        if result:
            _set_global_map('_macro_lpr_map', result, replace=True)
            _save_cache(_MACRO_LPR_CACHE, result)
            return len(result)
        else:
            if not _macro_lpr_map:
                _load_macro_lpr_cache()
            return len(_macro_lpr_map) if _macro_lpr_map else 0
    except Exception as e:
        logger.warning(f'[DataEnrich] Macro LPR refresh failed: {e}')
        if not _macro_lpr_map:
            _load_macro_lpr_cache()
        return len(_macro_lpr_map) if _macro_lpr_map else 0


# ==================== 全局状态 ====================

# ── 字段覆盖率自检 ──────────────────────────────────────────────────────
# 自检使用与 enrich_quotes 相同的语义：0 是 margin/lhb/bt/rr/pledge 的合法默认值
# None 才代表"缺失"。对于 gpm，-1 是银行标记，不算缺失。

_FIELD_LOADER_MAP: dict[str, callable] = {}
# 最近一次 enrich_quotes 的债券快照，供自检使用
_last_enriched_bonds: list = []


def _populate_field_loader_map():
    """延迟填充字段→缓存加载器映射（必须在所有 _load_* 函数定义之后调用）。"""
    if _FIELD_LOADER_MAP:
        return
    _FIELD_LOADER_MAP.update({
        "north_net": _load_north_cache,
        "margin_balance": _load_margin_cache,
        "lhb_count": _load_lhb_cache,
        "block_trade_amount": _load_block_trade_cache,
        "restricted_release_amount": _load_restricted_release_cache,
        "holder_num_change": _load_holder_num_cache,
        "bond_value": _load_bond_price_cache,
        "call_status": _load_call_status_cache,
        "pledge_ratio": _load_pledge_cache,
        "concepts": _load_concept_cache,
        "industry": _load_industry_cache,
        "pe": _load_spot_cache,
        "pb": _load_spot_cache,
        "roe": _load_fin_cache,
        "gpm": _load_fin_cache,
        "dual_low": _load_bond_price_cache,
        "ytm": _load_bond_price_cache,
        "remaining_years": _load_bond_price_cache,
        "premium_ratio": _load_bond_price_cache,
        "conversion_value": _load_bond_price_cache,
        # 扩展字段
        "turnover_rate": _load_spot_cache,
        "stock_price": _load_spot_cache,
        "stock_change_pct": _load_spot_cache,
        "eps_forecast": _load_earnings_forecast_cache,
        "mgmt_buy_price": _load_mgmt_cache,
        "buyback_amount": _load_buyback_cache,
        "iv": _load_vol_cache,
        "net_capital_flow": _load_fund_flow_cache,
        "debt_ratio": _load_debt_cache,
        "current_ratio": _load_debt_cache,
        "stock_name": _load_stock_name_cache,
        # momentum_*, event_score, outstanding_scale 字段在 _compute_field_coverage
        # 中跟踪覆盖率；以下加载器使 self_check_loop 能在覆盖率 <95% 时自动重载。
        "momentum_5d": _load_momentum_cache,
        "momentum_10d": _load_momentum_cache,
        "momentum_20d": _load_momentum_cache,
        "momentum_60d": _load_momentum_cache,
        "event_score": _load_event_cache,
        "outstanding_scale": _load_bond_outstanding_cache,
        "revenue_yoy": _load_earnings_express_cache,
        "profit_yoy": _load_earnings_express_cache,
    })


def _compute_field_coverage() -> dict[str, float]:
    """基于最近一次 enrich_quotes 的债券快照，计算各关键字段覆盖率(%)。

    语义与 enrich_quotes 一致：
    - 0 是 margin_balance/lhb_count/block_trade_amount/restricted_release_amount/
      pledge_ratio/holder_num_change/eps_forecast 的合法默认值，不算缺失
    - gpm=-1 是银行标记，不算缺失
    - None 或空字符串算缺失

    性能优化：批量提取每个 bond 的字段字典，避免 N×M 次 getattr。
    每个 bond 调用 vars() 一次（O(M)），后续每个字段 O(1) 字典查找。
    """
    bonds = _last_enriched_bonds
    if not bonds:
        return {}
    total = len(bonds)

    # 字段分类
    zero_valid = {
        "north_net", "margin_balance", "lhb_count", "block_trade_amount",
        "restricted_release_amount", "pledge_ratio", "holder_num_change",
        "eps_forecast", "revenue_yoy", "profit_yoy",
    }
    empty_string_valid = {"call_status", "concepts", "industry"}  # 空字符串/空列表也算缺失
    gpm_field = "gpm"  # -1 是银行标记，不算缺失

    fields = [
        "north_net", "margin_balance", "lhb_count", "block_trade_amount",
        "restricted_release_amount", "holder_num_change", "bond_value",
        "call_status", "pledge_ratio", "concepts", "ytm", "remaining_years",
        "industry", "pe", "pb", "roe", "gpm", "dual_low", "premium_ratio",
        "conversion_value", "revenue_yoy", "profit_yoy",
        # 扩展字段
        "turnover_rate", "outstanding_scale",
        # 重要：stock_price / stock_change_pct 不计入自检
        # 它们通常由 WebSocket 实时推送，而非缓存注入；
        # 自检无法区分"实时推送值"与"缓存注入的旧值"。
        "eps_forecast", "mgmt_buy_price", "buyback_amount", "iv",
        "net_capital_flow", "net_capital_flow_pct", "net_super_flow", "net_big_flow",
        "momentum_5d", "momentum_10d", "momentum_20d",
        "momentum_60d", "event_score", "event_detail", "debt_ratio", "current_ratio",
        "stock_name", "cagr", "eps", "bps",
    ]

    # 预提取每个 bond 的字段值（避免内层循环中反复 getattr）
    # 每字段预先生成一个 list of values
    field_values: dict[str, list] = {f: [] for f in fields}
    for b in bonds:
        # vars(b) 返回 __dict__ 快照，速度比 getattr 快约 3-5x
        # 缺失字段返回 None（与 getattr(b, f, None) 等价）
        obj_vars = vars(b) if hasattr(b, "__dict__") else {}
        for f in fields:
            field_values[f].append(obj_vars.get(f))

    result: dict[str, float] = {}
    for f in fields:
        values = field_values[f]
        if f == gpm_field:
            # -1 是银行标记，不算缺失；只有 None 算缺失
            missing = sum(1 for v in values if v is None)
        elif f in zero_valid:
            # 0 是合法默认值，只有 None 算缺失
            missing = sum(1 for v in values if v is None)
        elif f in empty_string_valid:
            # 空字符串、空列表也算缺失
            missing = sum(1 for v in values if v is None or v == "" or (isinstance(v, list) and len(v) == 0))
        else:
            # 0 代表缺失（如 bond_value=0, ytm=0 等）
            missing = sum(1 for v in values if v is None or v == 0)
        result[f] = (1 - missing / total) * 100

    return result

async def enrich_quotes(bonds: list) -> list:
    if not bonds:
        return bonds

    # 扩展缓存 reload 时间戳管理（per-cache dict，首次调用时初始化）
    if not hasattr(enrich_quotes, '_ext_cache_reload_ts_map'):
        enrich_quotes._ext_cache_reload_ts_map = {}

    # 惰性加载：如果关键缓存为空，从磁盘同步加载
    # 解决启动时 get_all_quotes 在 start_background_refresh 之前被调用的问题
    # 主缓存（有 _loaded 标志）
    # 每个 _load 独立 try/except，避免一个失败影响后续缓存加载
    for _loader_name, _loaded_flag in (
        ("_load_call_status_cache", "_call_status_loaded"),
        ("_load_bond_price_cache", "_bond_price_loaded"),
        ("_load_industry_cache", "_industry_loaded"),
        ("_load_fin_cache", "_fin_loaded"),
        ("_load_spot_cache", "_spot_loaded"),
        ("_load_concept_cache", "_concept_loaded"),
        ("_load_bond_outstanding_cache", "_bond_outstanding_loaded"),
        ("_load_stock_name_cache", "_name_loaded"),
        ("_load_pledge_cache", "_pledge_loaded"),
        ("_load_fund_flow_cache", "_fund_flow_loaded"),
        ("_load_main_biz_cache", "_main_biz_loaded"),
    ):
        if not globals().get(_loaded_flag):
            try:
                globals()[_loader_name]()
            except Exception as e:
                logger.warning(f"[DataEnrich] enrich_quotes lazy-load {_loader_name} failed: {e}")
    # 扩展缓存（无 _loaded 标志，用 map 为空/过小判断）
    # runner 子进程会写磁盘，主进程需要定期 reload
    # 使用 _cache_lock 保护 reload 时间戳和 global map 写入
    # 优化：缓存已足够大时跳过 reload（避免 sum() 遍历大 dict）
    # Per-cache reload TTL: 每个缓存独立计时，不再共享 120s 窗口。
    # 各自的上次 reload 时间记录在 enrich_quotes._ext_cache_reload_ts_map dict 中。
    _now = time.time()
    _ext_ts = getattr(enrich_quotes, "_ext_cache_reload_ts_map", None)
    if _ext_ts is None:
        _ext_ts = {}
        enrich_quotes._ext_cache_reload_ts_map = _ext_ts

    def _needs_reload(name: str, ttl: float, min_size: int = 0) -> bool:
        """Check if a per-cache reload is needed based on its own TTL and min size."""
        ref = globals().get(f"_{name}_map")
        if ref is None:
            return True
        if min_size > 0 and len(ref) < min_size:
            return True
        last_ts = _ext_ts.get(name, 0.0)
        return (_now - last_ts) > ttl

    # Cache-specific TTLs (in seconds). Each extended cache has its own schedule.
    # Values: 300 (5 min) for high-frequency, 3600 (1h) for mid, 86400 (24h+) for stable.
    loop = asyncio.get_event_loop()
    for _ext_name, _ext_loader, _ext_ttl, _ext_min in (
        ("north", _load_north_cache, 300, 500),
        ("margin", _load_margin_cache, 300, 500),
        ("lhb", _load_lhb_cache, 600, 10),
        ("block_trade", _load_block_trade_cache, 600, 10),
        ("holder_num", _load_holder_num_cache, 3600, 100),
        ("restricted_release", _load_restricted_release_cache, 3600, 10),
        ("earnings_forecast", _load_earnings_forecast_cache, 1800, 100),
        ("earnings_express", _load_earnings_express_cache, 1800, 100),
        ("buyback", _load_buyback_cache, 3600, 10),
        ("mgmt", _load_mgmt_cache, 3600, 100),
        ("momentum", _load_momentum_cache, 3600, 100),
        ("event", _load_event_cache, 3600, 10),
        ("vol", _load_vol_cache, 3600, 100),
        ("debt", _load_debt_cache, 3600, 100),
    ):
        if _needs_reload(_ext_name, _ext_ttl, min_size=_ext_min):
            try:
                await loop.run_in_executor(None, _ext_loader)
                _ext_ts[_ext_name] = _now
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[DataEnrich] enrich_quotes reload {_ext_name} failed: {e}")

    # CPython dict.copy() is thread-safe under GIL (atomic snapshot of the
    # outer dict). No lock needed; background thread updates via _set_global_map
    # replace the global reference, but our local copy remains valid for reading.
    # We only call .get() on these dicts, which is safe even if the nested
    # values are shared mutable dicts (we never write into them).
    spot_ref = _spot_map.copy() if _spot_map else {}
    industry_ref = _industry_map.copy() if _industry_map else {}
    fin_ref = _fin_map.copy() if _fin_map else {}
    fund_flow_ref = _fund_flow_map.copy() if _fund_flow_map else {}
    debt_ref = _debt_map.copy() if _debt_map else {}
    momentum_ref = _momentum_map.copy() if _momentum_map else {}
    event_ref = _event_map.copy() if _event_map else {}
    bond_outstanding_ref = _bond_outstanding_map.copy() if _bond_outstanding_map else {}
    call_status_ref = _call_status_map.copy() if _call_status_map else {}
    name_ref = _name_map.copy() if _name_map else {}
    concept_ref = _concept_map.copy() if _concept_map else {}
    pledge_ref = _pledge_map.copy() if _pledge_map else {}
    vol_ref = _vol_map.copy() if _vol_map else {}
    buyback_ref = _buyback_map.copy() if _buyback_map else {}
    mgmt_ref = _mgmt_map.copy() if _mgmt_map else {}
    bond_price_ref = _bond_price_map.copy() if _bond_price_map else {}
    north_ref = _north_map.copy() if _north_map else {}
    margin_ref = _margin_map.copy() if _margin_map else {}
    lhb_ref = _lhb_map.copy() if _lhb_map else {}
    block_trade_ref = _block_trade_map.copy() if _block_trade_map else {}
    holder_num_ref = _holder_num_map.copy() if _holder_num_map else {}
    earnings_forecast_ref = _earnings_forecast_map.copy() if _earnings_forecast_map else {}
    earnings_express_ref = _earnings_express_map.copy() if _earnings_express_map else {}
    restricted_release_ref = _restricted_release_map.copy() if _restricted_release_map else {}
    main_biz_ref = _main_biz_map.copy() if _main_biz_map else {}

    for b in bonds:
        stock_code = getattr(b, "stock_code", "") or ""
        if not stock_code and hasattr(b, "code"):
            stock_code = b.code[2:] if len(b.code) >= 3 else ""

        spot = spot_ref.get(stock_code, {})
        if spot:
            if spot.get("pe") is not None:
                b.pe = spot["pe"]
            if spot.get("pb") is not None:
                b.pb = spot["pb"]
            if spot.get("turnover_rate") is not None:
                b.turnover_rate = spot["turnover_rate"]
            if b.stock_price is None and spot.get("price") is not None:
                b.stock_price = spot["price"]
            if b.stock_change_pct is None and spot.get("change_pct") is not None:
                b.stock_change_pct = spot["change_pct"]

        if b.industry is None:
            industry = industry_ref.get(stock_code)
            if industry:
                b.industry = industry

        # Main business fallback: if industry is still missing, try main_biz cache
        if b.industry is None:
            main_biz = main_biz_ref.get(stock_code)
            if main_biz:
                b.industry = main_biz

        fin = fin_ref.get(stock_code, {})
        if fin.get("roe") is not None:
            b.roe = fin["roe"]
        if fin.get("gpm") is not None:
            b.gpm = fin["gpm"]
        elif b.industry and "银行" in str(b.industry):
            # 银行不报告毛利率，设置特殊标记值（前端可识别并显示"银行(无毛利率)"）
            if b.gpm is None:
                b.gpm = -1
        if fin.get("cagr") is not None:
            b.cagr = fin["cagr"]
        if fin.get("eps") is not None:
            b.eps = fin["eps"]
        if fin.get("bps") is not None:
            b.bps = fin["bps"]
        # PE fallback: if spot pe is None but fin has eps, compute PE = stock_price / EPS
        # Cap at 10000 to match East Money / yfinance fallback limits (line 729).
        # Skip negative EPS (loss-making companies) — negative PE has different meaning.
        if (b.pe is None or b.pe == 0) and fin.get("eps") and b.stock_price is not None and b.stock_price > 0:
            _eps = fin["eps"]
            if _eps > 0:
                _pe = round(b.stock_price / _eps, 2)
                if 0 < _pe <= 10000:
                    b.pe = _pe
        # PB fallback: if spot pb is None but fin has bps, compute PB = stock_price / BPS
        if (b.pb is None or b.pb == 0) and fin.get("bps") and b.stock_price is not None and b.stock_price > 0:
            _bps = fin["bps"]
            if _bps > 0:
                _pb = round(b.stock_price / _bps, 2)
                if 0 < _pb <= 10000:
                    b.pb = _pb
        if fin.get("revenue_yoy") is not None:
            b.revenue_yoy = fin["revenue_yoy"]
        if fin.get("profit_yoy") is not None:
            b.profit_yoy = fin["profit_yoy"]
        if fin.get("industry") and not b.industry:
            b.industry = fin["industry"]

        debt_info = debt_ref.get(stock_code, {})
        if debt_info.get("debt_ratio") is not None:
            b.debt_ratio = debt_info["debt_ratio"]
        if debt_info.get("current_ratio") is not None:
            b.current_ratio = debt_info["current_ratio"]

        vol = vol_ref.get(stock_code)
        if vol is not None:
            b.iv = vol
            b.iv_source = "hv_proxy"

        buyback = buyback_ref.get(stock_code)
        if buyback is not None:
            b.buyback_amount = buyback

        mgmt = mgmt_ref.get(stock_code)
        if mgmt is not None:
            b.mgmt_buy_price = mgmt

        flow = fund_flow_ref.get(stock_code, {})
        if flow.get("net_main") is not None:
            b.net_capital_flow = flow["net_main"]
        if flow.get("net_main_pct") is not None:
            b.net_capital_flow_pct = flow["net_main_pct"]
        if flow.get("net_super") is not None:
            b.net_super_flow = flow["net_super"]
        if flow.get("net_big") is not None:
            b.net_big_flow = flow["net_big"]

        # [TDX] Concept enrichment
        stock_concepts = concept_ref.get(stock_code)
        if stock_concepts:
            seen = set()
            unique = []
            for c in stock_concepts:
                if c not in seen:
                    seen.add(c)
                    unique.append(c)
            b.concepts = unique[:8]

        # Momentum enrichment
        mom = momentum_ref.get(stock_code, {})
        if mom:
            if mom.get("5d") is not None:
                b.momentum_5d = mom["5d"]
            if mom.get("10d") is not None:
                b.momentum_10d = mom["10d"]
            if mom.get("20d") is not None:
                b.momentum_20d = mom["20d"]
            if mom.get("60d") is not None:
                b.momentum_60d = mom["60d"]

        # Event enrichment
        evt = event_ref.get(b.code, {})
        if evt:
            if evt.get("score") is not None:
                b.event_score = evt["score"]
            if evt.get("title"):
                b.event_detail = evt["title"]

        # Outstanding scale from bond_outstanding map
        bond_outstanding = bond_outstanding_ref.get(b.code)
        if bond_outstanding is not None:
            b.outstanding_scale = bond_outstanding

        # Call status — default to "未触发" if not in cache
        call_status_val = call_status_ref.get(b.code)
        if call_status_val:
            b.call_status = call_status_val
        else:
            b.call_status = "未触发"

        # Pledge ratio from pledge map
        # stock_gpzy_pledge_ratio_em only returns stocks with active pledges;
        # stocks not in cache have pledge_ratio = 0 (no active pledges)
        pledge = pledge_ref.get(stock_code)
        if pledge is not None:
            b.pledge_ratio = pledge
        else:
            b.pledge_ratio = 0

        # Stock name from name map
        if not b.stock_name:
            sn = name_ref.get(stock_code)
            if sn:
                b.stock_name = sn

        # ── 集思录(JISILU)债券价格数据 enrichment ──
        bp = bond_price_ref.get(b.code, {})
        if bp:
            if bp.get("price") is not None and bp.get("price", 0) > 0 and b.price is None:
                b.price = bp["price"]
            if bp.get("change_pct") is not None and b.change_pct is None:
                b.change_pct = bp["change_pct"]
            if bp.get("stock_price") is not None and b.stock_price is None:
                b.stock_price = bp["stock_price"]
            if bp.get("stock_change_pct") is not None and b.stock_change_pct is None:
                b.stock_change_pct = bp["stock_change_pct"]
            if bp.get("conversion_price") is not None and bp.get("conversion_price", 0) > 0 and b.conversion_price is None:
                b.conversion_price = bp["conversion_price"]
            if bp.get("conversion_value") is not None and bp.get("conversion_value", 0) > 0 and b.conversion_value is None:
                b.conversion_value = bp["conversion_value"]
            if bp.get("premium_ratio") is not None and b.premium_ratio is None:
                b.premium_ratio = bp["premium_ratio"]
            if bp.get("dual_low") is not None and bp.get("dual_low", 0) > 0 and b.dual_low is None:
                b.dual_low = bp["dual_low"]
            # YTM: JSL ytm=0 可能是数据缺失而非真实 0%，
            # 使用 remaining_years > 0 作为启发式判断（未到期债券的 ytm=0 极罕见）
            _bp_ytm = bp.get("ytm")
            if _bp_ytm is not None and b.ytm is None:
                b.ytm = _bp_ytm
            elif _bp_ytm == 0 and bp.get("remaining_years", 0) > 0 and b.ytm is None:
                # 未到期债券 ytm=0 可能是有效数据，但标记为不确定
                b.ytm = 0.0
            if bp.get("volume") is not None and bp.get("volume", 0) > 0 and b.volume is None:
                b.volume = bp["volume"]
            if bp.get("turnover_rate") is not None and bp.get("turnover_rate", 0) > 0 and b.turnover_rate is None:
                b.turnover_rate = bp["turnover_rate"]
            if bp.get("outstanding_scale") is not None and bp.get("outstanding_scale", 0) > 0 and b.outstanding_scale is None:
                b.outstanding_scale = bp["outstanding_scale"]
            if bp.get("bond_rating") and not b.rating:
                b.rating = bp["bond_rating"]
            if bp.get("remaining_years") is not None and bp.get("remaining_years", 0) > 0 and b.remaining_years is None:
                b.remaining_years = bp["remaining_years"]
            if bp.get("stock_pb") is not None and b.pb is None:
                b.pb = bp["stock_pb"]
            # NOTE: stock_pe / maturity_date 曾是 legacy 字段，当前没有任何 refresh 函数写入它们，
            # 因此删除死代码以避免误导维护者（Audit 2026-06-22）。
        # Fallback: 计算 dual_low = price + premium_ratio（当 JISILU/缓存不提供时）
        # 必须在 if bp: 块外面，因为某些债券不在 bond_price 缓存中
        if b.dual_low is None and b.price is not None and b.premium_ratio is not None:
            b.dual_low = round(b.price + b.premium_ratio, 2)

        # North-bound capital enrichment
        # 标准化为"持股市值（亿元）"——这是横向比较股票最有意义的金融指标。
        # 优先级：hold_market_cap（直接）> hold_shares（×price 估算）> add_capital（0 fallback）
        # 字段模型语义统一为"北向资金持股市值(亿元)"
        north = north_ref.get(stock_code)
        if north is not None:
            if isinstance(north, dict):
                _hold_mc = north.get("hold_market_cap")
                _hold_shares = north.get("hold_shares")
                if _hold_mc is not None and _hold_mc > 0:
                    b.north_net = round(_hold_mc / 1e8, 4)
                elif _hold_shares is not None and _hold_shares > 0 and b.stock_price and b.stock_price > 0:
                    # hold_market_cap 缺失时用 stock_price × hold_shares 估算
                    b.north_net = round(_hold_shares * b.stock_price / 1e8, 4)
                elif "add_capital" in north and north["add_capital"] is not None:
                    # 仅作 fallback（变动资金本身无法精确转换为市值）
                    b.north_net = 0
            elif isinstance(north, (int, float)) and north > 0:
                # Legacy bare numeric — assume already in 亿元
                b.north_net = float(north)
            else:
                b.north_net = 0
        else:
            b.north_net = 0

        # Margin trading enrichment
        # 非融资融券标的 stock 不在 margin cache 中，margin_balance = 0
        margin = margin_ref.get(stock_code, {})
        if margin:
            if isinstance(margin, dict):
                val = margin.get("margin_balance")
                if val is not None and val > 0:
                    b.margin_balance = round(val / 1e8, 2) if val > 1e6 else val
                else:
                    # Fallback: 估算融资余额 = 融资比例 * 流通市值 / 100
                    rz_ratio = margin.get("rz_ratio")
                    if rz_ratio is not None and rz_ratio > 0:
                        sp = spot_ref.get(stock_code, {})
                        if isinstance(sp, dict):
                            # Prefer precise circ_mv from EM (f21), fallback to volume/turnover estimate
                            circ_mv = sp.get("circ_mv")
                            if not circ_mv:
                                if sp.get("volume") and sp.get("turnover_rate"):
                                    turnover_rate = sp["turnover_rate"]
                                    if turnover_rate and turnover_rate > 0:
                                        # 流通市值 ≈ 成交额 / (换手率/100)
                                        vol_val = sp["volume"]
                                        circ_mv = vol_val / (turnover_rate / 100)
                            if circ_mv and circ_mv > 0:
                                est_rzye = circ_mv * rz_ratio / 100
                                if est_rzye > 0:
                                    b.margin_balance = round(est_rzye / 1e8, 2)
            else:
                b.margin_balance = margin
        else:
            b.margin_balance = 0

        # Long-Hu-Bang enrichment
        # 非龙虎榜股票不在 cache 中，lhb_count = 0
        lhb = lhb_ref.get(stock_code)
        if lhb is not None:
            if isinstance(lhb, dict):
                b.lhb_count = lhb.get("lhb_count", 0)
            else:
                b.lhb_count = lhb
        else:
            b.lhb_count = 0

        # Block trade enrichment
        # 无大宗交易的股票不在 cache 中，block_trade_amount = 0
        bt = block_trade_ref.get(stock_code)
        if bt is not None:
            if isinstance(bt, dict):
                b.block_trade_amount = bt.get("block_trade_amount")
            else:
                b.block_trade_amount = bt
        else:
            b.block_trade_amount = 0

        # Holder number change enrichment
        # 0 is a valid value (股东户数无变化), not "missing"
        # 默认 0（与 sibling pledge_ratio/north_net/margin_balance 一致）
        hn = holder_num_ref.get(stock_code)
        if isinstance(hn, dict):
            b.holder_num_change = hn.get("holder_num_change") if hn.get("holder_num_change") is not None else 0
        elif hn is not None:
            b.holder_num_change = hn
        else:
            b.holder_num_change = 0  # 缺失时也默认为 0，与其他资金类字段一致

        # Earnings forecast enrichment
        # 默认 0（与 sibling pledge_ratio/north_net 一致）
        ef = earnings_forecast_ref.get(stock_code)
        if isinstance(ef, dict):
            b.eps_forecast = ef.get("yoy_change_pct", 0)
        elif ef is not None:
            b.eps_forecast = ef
        else:
            b.eps_forecast = 0  # 缺失时默认为 0，与其他资金类字段一致

        # Earnings express enrichment (业绩快报: 实际报告数据,补全 eps/bps/roe/revenue_yoy)
        # AGENTS.md 要求所有 loaded cache 必须在 enrich_quotes 中消费
        if earnings_express_ref:
            _ee = earnings_express_ref.get(stock_code)
            if isinstance(_ee, dict):
                # eps: 优先快报数据，已有值不覆盖
                if _ee.get("eps") is not None and (b.eps is None or b.eps == 0):
                    b.eps = _ee["eps"]
                # bps: 每股净资产（兼容 net_assets 字段名）
                if _ee.get("bps") is not None and (b.bps is None or b.bps == 0):
                    b.bps = _ee["bps"]
                elif _ee.get("net_assets") is not None and (b.bps is None or b.bps == 0):
                    b.bps = _ee["net_assets"]
                # roe: 净资产收益率（快报数据比 enrich cache 更及时）
                if _ee.get("roe") is not None:
                    b.roe = _ee["roe"]
                # revenue_yoy: 营收同比增长
                # 使用 is not None 判断，区分"0%增长"和"缺失"
                if _ee.get("revenue_yoy") is not None and b.revenue_yoy is None:
                    b.revenue_yoy = _ee["revenue_yoy"]
                # profit_yoy: 净利润同比增长（同上）
                if _ee.get("net_profit_yoy") is not None and b.profit_yoy is None:
                    b.profit_yoy = _ee["net_profit_yoy"]

        # Restricted release enrichment
        # 无限售解禁的股票不在 cache 中，restricted_release_amount = 0
        rr = restricted_release_ref.get(stock_code)
        if rr is not None:
            if isinstance(rr, dict):
                amt = rr.get("restricted_release_amount")
                b.restricted_release_amount = amt
            else:
                b.restricted_release_amount = rr
        else:
            b.restricted_release_amount = 0

        # Bond value (纯债价值) computation
        # 使用 PV(未来现金流) 方法：纯债价值 = Σ(票息/(1+ytm)^t) + 面值/(1+ytm)^T
        # ytm 可以为负（此时纯债价值 > 面值，说明持有到期比存银行更差，但纯债价值仍可计算）
        # 优先从独立 _coupon_rate_map 获取实际票面利率，回退到 bond_price 缓存，最后用 0.5% 默认
        _real_cr = _coupon_rate_map.get(b.code)
        bp_bv = bond_price_ref.get(b.code, {})
        # 当有实际 coupon_rate 时总是重新计算（覆盖 0.5% 默认值的结果）
        has_real_coupon = _real_cr is not None and _real_cr > 0
        if not b.bond_value or has_real_coupon:
            # 优先使用 bond 对象上已有的 ytm/remaining_years（覆盖率 100%）
            ytm = b.ytm if b.ytm is not None else None
            remaining_years = b.remaining_years if b.remaining_years and b.remaining_years > 0 else None
            # 回退到 bond_price 缓存
            if ytm is None and bp_bv:
                ytm = bp_bv.get("ytm")
            if remaining_years is None and bp_bv:
                remaining_years = bp_bv.get("remaining_years")
            if ytm is not None and ytm != 0 and remaining_years is not None and remaining_years > 0:
                # coupon_rate: 优先独立缓存 → bond_price 缓存 → 默认 0.5%
                coupon_rate = _real_cr
                if coupon_rate is None or coupon_rate <= 0:
                    coupon_rate = bp_bv.get("coupon_rate") if bp_bv else None
                if coupon_rate is None or coupon_rate <= 0:
                    coupon_rate = 0.5  # fallback 默认值
                ytm_dec = ytm / 100.0
                # 当 ytm < -100% 时，(1 + ytm_dec) < 0，分数次幂产生复数
                # 此时纯债价值无经济意义，用线性近似：face_value * (1 + |ytm_dec| * remaining_years)
                if ytm_dec <= -1.0:
                    # 极端负 YTM：用简单线性近似，cap at 500
                    bv = 100 * (1 + abs(ytm_dec) * remaining_years)
                    b.bond_value = min(round(bv, 2), 500.0)
                elif abs(ytm_dec) > 0.0001:
                    # 正常 YTM（含 -100% < ytm < 0 的情况）
                    # 负 YTM 时 (1 + ytm_dec) 仍在 (0, 1) 区间，数学上正常
                    # coupon_rate 是百分比小数（如 0.015 = 1.5%），需乘面值 100
                    pv_coupons = coupon_rate * 100 * (1 - 1 / (1 + ytm_dec) ** remaining_years) / ytm_dec
                    pv_face = 100 / (1 + ytm_dec) ** remaining_years
                    bv = pv_coupons + pv_face
                    # 负 YTM 时纯债价值可能很高，cap at 500
                    b.bond_value = min(round(bv, 2), 500.0)

        # ── 策略依赖字段补充（合并入主循环，避免二次遍历）──
        # 1. hv: 仅当 iv_source=="hv_proxy" 时 iv 即为 hv
        if b.iv is not None and getattr(b, "iv_source", "") == "hv_proxy":
            b.hv = b.iv

        # 2. rating_score: 评级字符串 → 0-100 数值（使用 convertible.RATING_SCORE_MAP）
        if getattr(b, "rating", None) and b.rating:
            rating_str = str(b.rating).strip().upper()
            b.rating_score = RATING_SCORE_MAP.get(rating_str, RATING_SCORE_DEFAULT)
        elif not getattr(b, "rating_score", None):
            b.rating_score = RATING_SCORE_DEFAULT

        # 3. pure_bond_premium_ratio = (price - bond_value) / bond_value * 100
        if b.price and getattr(b, "bond_value", None) and b.bond_value and b.bond_value > 0:
            b.pure_bond_premium_ratio = round((b.price - b.bond_value) / b.bond_value * 100, 2)

        # 4. forced_call_days / is_called 从 call_status 解析
        call_status = getattr(b, "call_status", None)
        if call_status:
            cs = str(call_status)
            if "已公告" in cs or "强制赎回" in cs:
                b.is_called = True
                _m = re.search(r"(\d+)天", cs)
                b.forced_call_days = int(_m.group(1)) if _m else 999
            elif "进入" in cs or "已满足" in cs:
                b.is_called = True
                b.forced_call_days = 0

    # 保存快照供自检使用（浅拷贝列表，bonds 对象本身是每次新创建的）
    # 空列表时跳过更新，避免自检误判覆盖率为 0%
    global _last_enriched_bonds
    if bonds:
        _last_enriched_bonds = list(bonds)

    return bonds


# ── _spot_then_vol: 同步刷新 spot + vol 缓存 ──────────────────────────────
# AGENTS.md #34: 将 spot 和 vol 缓存刷新绑定为一个 executor 任务，
# 避免 asyncio.sleep(30) 后再调用 vol 时 spot_map 仍未加载的时序竞争。
# 此函数由 _load_runner_caches_with_fallback 在缓存缺失时调用。
def _spot_then_vol():
    """同步执行 spot → vol 缓存刷新，确保 vol 刷新时 spot_map 已就绪。"""
    if len(_spot_map) < 1000:
        _refresh_spot_cache()
    if len(_vol_map) < 1000:
        _refresh_volatility_cache()


async def start_background_refresh():
    """异步加载 + 刷新后台数据缓存。

    ⚠️ 必须以 `await start_background_refresh()` 方式调用,否则 Python 会发出
    RuntimeWarning: coroutine 'start_background_refresh' was never awaited
    (见 AGENTS.md Rule 关于异步语义的说明)。

    防御: 在进入函数体后立刻断言当前上下文确实是 await,确保任何遗漏 await
    的调用方在第一时间收到 AttributeError 而不是静默警告。
    """
    # 防御性 guard: 阻止任何遗漏 await 的调用方被 GC 后再以 RuntimeWarning 形式
    # 暴露 (后者经常在解释器退出/事件循环 teardown 时才打印,不易定位)。
    if not asyncio.iscoroutinefunction(start_background_refresh):
        # 这种情况只会在 reload/动态替换后发生,防御即可。
        raise RuntimeError("start_background_refresh must remain async")
    loop = asyncio.get_event_loop()

    # 0. 急切加载可转债正股代码，确保所有刷新函数聚焦在目标范围内
    _ensure_bond_stock_codes()
    global _start_ts
    _start_ts = time.time()  # 每次调用都重置，确保热重载后也重新激活快速 flush interval

    # 启动心跳：用于诊断后端是否在规定时间内完成初始化。
    # 如果 startup 耗时异常（如 >30s），通常是某个 _load_* 函数阻塞。
    _startup_t0 = time.time()
    logger.info(f"[LHBE_STARTUP] DataEnrich begin at t=0")

    # 1. 并行加载所有磁盘缓存文件到内存（~300ms total vs 时序加载）
    def _load_all_caches():
        # 每个 _load 独立 try/except，避免一个失败导致后续全部跳过
        for _loader_name in (
            "_load_industry_cache", "_load_fin_cache", "_load_fund_flow_cache",
            "_load_debt_cache", "_load_vol_cache", "_load_buyback_cache",
            "_load_mgmt_cache", "_load_pledge_cache", "_load_momentum_cache",
            "_load_event_cache", "_load_bond_outstanding_cache",
            "_load_call_status_cache", "_load_stock_name_cache",
            "_load_concept_cache", "_load_spot_cache", "_load_bond_price_cache",
            "_load_coupon_rate_cache", "_load_north_cache", "_load_margin_cache",
            "_load_lhb_cache", "_load_block_trade_cache", "_load_holder_num_cache",
            "_load_earnings_forecast_cache", "_load_earnings_express_cache",
            "_load_restricted_release_cache", "_load_main_biz_cache",
            "_load_analyst_rank_cache", "_load_macro_cpi_cache",
            "_load_macro_ppi_cache", "_load_macro_m2_cache",
            "_load_macro_lpr_cache",
        ):
            try:
                globals()[_loader_name]()
            except Exception as e:
                logger.warning(f"[DataEnrich] {_loader_name} failed: {e}")

    await loop.run_in_executor(None, _load_all_caches)

    # 第一批：核心缓存刷新（主进程负责）
    # 注意：spot / vol / fund_flow / bond_price / coupon_rate 由 data_enrich_runner.py
    # 子进程负责（AKShare C 扩展 segfault 高风险），主进程只加载其输出的缓存文件。
    # 以下仅包含 enrich_quotes 所需、且可在主进程安全运行的核心数据源。
    # 额外加入 main_biz/analyst_rank 2 个之前只在 runner 里调用的数据源
    # macro_* 5 个在第二批错峰启动（避免 5 个同时跑 + 一次性占用所有线程）
    _core_futures = []
    for fn in (_build_industry_cache, _build_concept_cache, _refresh_fin_cache,
               _refresh_debt_cache, _refresh_buyback_cache, _refresh_mgmt_cache,
               _refresh_pledge_cache, _refresh_momentum_cache, _refresh_event_cache,
               _refresh_bond_outstanding_cache, _refresh_call_status_cache, _refresh_stock_name_cache,
               _refresh_coupon_rate_cache, _refresh_earnings_express_cache,
               _refresh_main_biz_cache, _refresh_analyst_rank_cache):
        _core_futures.append(loop.run_in_executor(None, fn))
    # 并行等待所有核心缓存刷新，捕获异常避免一个失败影响整体启动
    _core_results = await asyncio.gather(*_core_futures, return_exceptions=True)
    for _idx, _res in enumerate(_core_results):
        if isinstance(_res, Exception):
            logger.warning(f"[DataEnrich] Core cache refresh #{_idx} failed: {_res}")

    # 第二批：宏观数据源错峰启动（5 个 macro_*）
    # 每个 macro 数据源启动间隔 3 秒，避开 AKShare 信号量拥堵
    # macro_* 通常只 1-2 次 AKShare 调用，~3-7s 完成，错峰后总耗时约 25s
    # 用独立 executor 避免阻塞主线程
    def _refresh_macro_staggered():
        import time as _t
        _macro_fns = (
            (_refresh_macro_cpi_cache, 0),
            (_refresh_macro_lpr_cache, 3),
            (_refresh_macro_m2_cache, 6),
            (_refresh_macro_ppi_cache, 9),
        )
        for _fn, _delay in _macro_fns:
            _t.sleep(_delay)
            try:
                _fn()
            except Exception as e:
                logger.warning(f"[DataEnrich] Macro refresh {_fn.__name__} failed: {e}")
    loop.run_in_executor(None, _refresh_macro_staggered)

    # 第二批：扩展缓存刷新（7 个，原 data_enrich_runner 子进程，现已移入主进程）
    # 延迟 5 秒执行，避开第一批的 semaphore 拥堵
    # 使用独立 ThreadPoolExecutor 而非默认 executor，避免与第一批竞争 worker 槽位
    # 默认 executor 池大小 = min(32, os.cpu_count()+4)，若主线程繁忙会阻塞
    _extended_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="ext_refresh",
    )
    # 优雅关闭：进程退出时给 3s 等待完成（uvicorn 默认 5s 超时，留 2s buffer）
    # wait=True + timeout=3 比单纯 wait=False 更安全，能保存部分未完成任务结果
    # 用 threading.Thread + join(timeout) 实现 timeout 包装
    def _shutdown_ext_executor_inner(timeout_sec: float = 3.0):
        def _do_shutdown():
            try:
                _extended_executor.shutdown(wait=True)
            except Exception as e:
                logger.debug(f"[LHBE_SHUTDOWN] _extended_executor shutdown error: {e}")
        t = threading.Thread(target=_do_shutdown, daemon=True)
        t.start()
        t.join(timeout=timeout_sec)
        if t.is_alive():
            logger.warning(f"[LHBE_SHUTDOWN] _extended_executor shutdown 超时 {timeout_sec}s, 强制退出")

    import atexit as _atexit
    _atexit.register(_shutdown_ext_executor_inner)

    def _sigusr1_handler(signum, frame):
        logger.info(f"[LHBE_SHUTDOWN] Received SIGUSR1, shutting down _extended_executor")
        _shutdown_ext_executor_inner()

    import signal as _signal
    try:
        _prev_handler = _signal.signal(_signal.SIGUSR1, _sigusr1_handler)
        if _prev_handler not in (_signal.SIG_DFL, _signal.SIG_IGN, _sigusr1_handler):
            _signal.signal(_signal.SIGUSR1, _prev_handler)
            logger.debug("[LHBE_STARTUP] SIGUSR1 already has custom handler, skipping")
    except ValueError:
        pass

    def _refresh_extended_batch():
        import time as _t
        _t.sleep(5)
        futures = [
            _extended_executor.submit(fn)
            for fn in (_refresh_north_cache, _refresh_margin_cache, _refresh_lhb_cache,
                       _refresh_block_trade_cache, _refresh_holder_num_cache,
                       _refresh_earnings_forecast_cache, _refresh_restricted_release_cache,
                       # bond_price 在 runner 子进程里是最后一步（要等 spot→vol→fund_flow
                       # 全部完成），单独加到扩展执行器里并行执行，可让 bond_price 提前 ~5 分钟可用
                       _refresh_bond_price_cache)
        ]
        # 使用 wait() 替代 as_completed(timeout)，避免 TimeoutError 丢失已完成结果
        done, pending = concurrent.futures.wait(
            futures, timeout=300, return_when=concurrent.futures.ALL_COMPLETED
        )
        if pending:
            logger.warning(f"[DataEnrich] Extended batch: {len(pending)} (of {len(futures)}) futures unfinished after 300s")
            for fut in pending:
                fut.cancel()
        for f in done:
            try:
                f.result()
            except Exception as e:
                logger.debug(f"[DataEnrich] Extended refresh future failed: {e}")

    loop.run_in_executor(None, _refresh_extended_batch)

    # 后台加载 runner 子进程负责的缓存；若缓存缺失或过期，则主进程 fallback 刷新。
    # spot / vol / fund_flow / bond_price 使用 AKShare C 扩展，segfault 风险高，
    # 正常情况下由 data_enrich_runner.py 子进程刷新并写入磁盘；主进程只加载。
    def _load_runner_caches_with_fallback():
        # 1) 先尝试加载磁盘缓存（每个独立 try/except，避免一个失败影响后续）
        for _loader in (_load_spot_cache, _load_vol_cache, _load_fund_flow_cache,
                        _load_bond_price_cache, _load_coupon_rate_cache):
            try:
                _loader()
            except Exception as e:
                logger.warning(f"[DataEnrich] {_loader.__name__} failed: {e}")

        # 2) 检查是否有效；无效则主进程兜底刷新
        def _spot_ok():
            return len(_spot_map) >= 1000
        def _vol_ok():
            return len(_vol_map) >= 1000
        def _ff_ok():
            return len(_fund_flow_map) >= 100
        def _bp_ok():
            return len(_bond_price_map) >= 100

        if not _spot_ok() or not _vol_ok():
            logger.warning("[DataEnrich] Runner spot/vol cache missing/stale, falling back to _spot_then_vol")
            try:
                _spot_then_vol()
            except Exception as e:
                logger.error(f"[DataEnrich] _spot_then_vol fallback failed: {e}")
        if not _ff_ok():
            logger.warning("[DataEnrich] Runner fund_flow cache missing/stale, falling back to in-process refresh")
            try:
                _refresh_fund_flow_cache()
            except Exception as e:
                logger.error(f"[DataEnrich] In-process fund_flow refresh fallback failed: {e}")
        if not _bp_ok():
            logger.warning("[DataEnrich] Runner bond_price cache missing/stale, falling back to in-process refresh")
            try:
                _refresh_bond_price_cache()
            except Exception as e:
                logger.error(f"[DataEnrich] In-process bond_price refresh fallback failed: {e}")
        # 所有 runner 相关缓存处理完成后强制 flush metrics，确保前端监控页立即可用
        _flush_metrics()
    loop.run_in_executor(None, _load_runner_caches_with_fallback)

    # 预创建所有 refresh 函数的 metrics 条目（pending 状态）
    # 这样监控页从一开始就能显示完整数据源列表，而不是等首次刷新后才出现
    # 自动发现：通过 globals() 扫描带有 _REGISTER_METRIC=True 标记的可调用对象
    # 这是白名单机制：只有 @_with_metrics 装饰过的函数才会注册
    # 避免 _refresh_xxx_inproc 之类的内部实现被错误注册（曾经的 bug）
    _PRE_REGISTERED_METRICS = tuple(
        name for name, obj in globals().items()
        if callable(obj)
        and getattr(obj, "_REGISTER_METRIC", False) is True
    )
    # 先加载 runner 子进程已写入共享 metrics 文件的真实结果，
    # 避免随后补 pending 占位符时把 spot/vol/fund_flow/bond_price 等
    # 实际已完成的指标覆盖成 pending。
    _load_metrics_from_file()
    _startup_ts_iso = "1970-01-01T00:00:00"
    with _cache_lock:
        for name in _PRE_REGISTERED_METRICS:
            if name not in _refresh_metrics:
                _refresh_metrics[name] = {
                    "name": name,
                    "elapsed_s": 0.0,
                    "count": 0,
                    "status": "pending",  # 标记为等待首次执行
                    "ts": _startup_ts_iso,
                    "_data_source": "init",
                }

    # 启动心跳：所有 executor 任务已 dispatch，函数返回（不阻塞）。
    # 注意：实际缓存加载在后台线程进行，此处仅记录 dispatch 完成时间。
    _elapsed = time.time() - _startup_t0
    logger.info(f"[LHBE_STARTUP] DataEnrich ready in {_elapsed:.2f}s, "
                f"all executor tasks dispatched (loads=~30, metrics pre-registered=auto)")

    # 启动定期自检：每 5 分钟统计字段覆盖率并记录日志，<95% 时触发重刷
    async def _self_check_loop():
        """定期自检数据覆盖率，发现异常自动触发缓存重刷。"""
        _populate_field_loader_map()
        await asyncio.sleep(300)  # 首次延迟 5 分钟，等待缓存充分加载
        while True:
            try:
                await asyncio.sleep(300)  # 每 5 分钟检查一次
                coverage = _compute_field_coverage()
                if not coverage:
                    logger.debug("[SelfCheck] No enriched bonds snapshot yet, skipping")
                    continue
                low_fields = [f for f, pct in coverage.items() if pct < 95]
                if low_fields:
                    logger.warning(
                        "[SelfCheck] Low coverage fields: %s",
                        ", ".join(f"{f}={coverage[f]:.1f}%" for f in low_fields),
                    )
                    # 触发针对性重刷：重新加载磁盘缓存
                    for f in low_fields:
                        _loader = _FIELD_LOADER_MAP.get(f)
                        if _loader:
                            try:
                                _loader()
                                logger.info("[SelfCheck] Reloaded cache for field '%s'", f)
                            except Exception as e:
                                logger.error("[SelfCheck] Failed to reload cache for '%s': %s", f, e)
                    # 重刷后再次检查覆盖率，确认是否仍然低
                    new_coverage = _compute_field_coverage()
                    still_low = [f for f, pct in new_coverage.items() if pct < 95]
                    if still_low:
                        logger.warning(
                            "[SelfCheck] After reload, still low: %s — triggering runner subprocess",
                            ", ".join(f"{f}={new_coverage[f]:.1f}%" for f in still_low),
                        )
                        # Bug 6a fix: 触发 runner 子进程刷新磁盘缓存，否则
                        # 单纯的内存 reload 无法解决磁盘已 stale 的问题。
                        # 仅对仍 stale 的字段调用对应 flag，最小化资源消耗。
                        try:
                            import subprocess, sys as _sys
                            runner_script = str(Path(__file__).parent / "data_enrich_runner.py")
                            _field_to_flag = {
                                "north_net": "--north",
                                "margin_balance": "--margin",
                                "lhb_count": "--lhb",
                                "block_trade_amount": "--block-trade",
                                "holder_num_change": "--holder-num",
                                "restricted_release_amount": "--restricted-release",
                                "net_capital_flow": "--fund-flow",
                                "iv": "--vol",
                                "mgmt_buy_price": "--mgmt",
                                "eps_forecast": "--earnings-forecast",
                                "revenue_yoy": "--earnings-express",
                                "profit_yoy": "--earnings-express",
                            }
                            flags = sorted({_field_to_flag[f] for f in still_low if f in _field_to_flag})
                            if flags:
                                cmd = [_sys.executable, runner_script] + flags
                                loop = asyncio.get_event_loop()
                                proc = await loop.run_in_executor(
                                    None,
                                    lambda: subprocess.run(cmd, cwd=str(Path(__file__).parent.parent), capture_output=True, timeout=600)
                                )
                                logger.info("[SelfCheck] Runner subprocess finished (rc=%d) for flags %s", proc.returncode, flags)
                                # Reload affected caches
                                for f in still_low:
                                    _loader = _FIELD_LOADER_MAP.get(f)
                                    if _loader:
                                        try:
                                            _loader()
                                        except Exception:
                                            pass
                        except Exception as e:
                            logger.error("[SelfCheck] Failed to spawn runner subprocess: %s", e)
                    else:
                        logger.info("[SelfCheck] After reload, all fields recovered")
                else:
                    logger.info(
                        "[SelfCheck] All fields OK — worst: %s (%.1f%%)",
                        min(coverage, key=coverage.get) if coverage else "N/A",
                        min(coverage.values()) if coverage else 0,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[SelfCheck] Error in self-check loop: %s", e)

    # Bug 6c fix: 保存 Task 引用以便应用关闭时优雅取消。
    # 之前用 ensure_future 创建的 task 无法被外部取消，shutdown 时会泄漏。
    _self_check_task = asyncio.ensure_future(_self_check_loop())

    # 启动定期 runner 子进程重刷：每 30 分钟重新运行 data_enrich_runner
    # 确保扩展缓存（north/margin/lhb/block_trade/holder_num/restricted_release）
    # 不会因 runner 仅在启动时运行一次而变 stale
    async def _periodic_runner_loop():
        """定期重新运行 runner 子进程刷新扩展缓存到磁盘。"""
        await asyncio.sleep(60)  # 首次延迟 60 秒，快速恢复 runner 刷新
        while True:
            try:
                await asyncio.sleep(1800)  # 每 30 分钟运行一次
                import subprocess, sys as _sys
                runner_script = str(Path(__file__).parent / "data_enrich_runner.py")
                _log_dir = Path.home() / ".lianghua" / "logs"
                _log_dir.mkdir(parents=True, exist_ok=True)
                _log_path = _log_dir / "enrich_periodic.log"
                # 日志轮换：超过 1MB 时截断保留末尾 512KB
                try:
                    if _log_path.exists() and _log_path.stat().st_size > 1_048_576:
                        with open(_log_path, "rb") as f:
                            f.seek(-524_288, 2)
                            f.readline()  # 跳到下一个完整行
                            tail = f.read()
                        with open(_log_path, "wb") as f:
                            f.write(tail)
                except Exception:
                    pass  # 日志轮换失败不影响主流程
                _log = open(_log_path, "a")
                # AGENTS.md fix: 清理旧 runner 子进程，避免残留进程竞争资源
                try:
                    import subprocess as _sp
                    _sp.run(['pkill', '-f', 'data_enrich_runner.py'], capture_output=True, text=True, timeout=5)
                    # 短暂延迟，确保旧进程完全终止后再启动新进程
                    await asyncio.sleep(1)
                except Exception:
                    pass
                # 只刷新容易变 stale 的扩展缓存（spot/vol/fund_flow/bond_price 由 runner 子进程负责）
                cmd = [_sys.executable, runner_script,
                       "--north", "--margin", "--lhb", "--block-trade",
                       "--holder-num", "--restricted-release",
                       "--fund-flow", "--vol", "--mgmt", "--earnings-forecast",
                       "--earnings-express", "--spot", "--bond-price"]
                proc = None
                try:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(Path(__file__).parent.parent),
                        stdout=_log,
                        stderr=_log,
                    )
                    logger.info("[PeriodicRunner] Started runner subprocess (PID %d) for ext caches", proc.pid)
                    # 非阻塞等待子进程完成（最多 10 分钟），避免阻塞事件循环
                    loop = asyncio.get_event_loop()
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(None, proc.wait),
                            timeout=600,
                        )
                        logger.info("[PeriodicRunner] Runner subprocess completed (rc=%d)", proc.returncode)
                    except asyncio.TimeoutError:
                        proc.kill()
                        logger.warning("[PeriodicRunner] Runner subprocess timed out, killed")
                except Exception:
                    # Popen 失败时 proc 仍未绑定；不要在 except 后访问 proc
                    logger.error("[PeriodicRunner] Failed to spawn runner subprocess")
                finally:
                    # 关闭日志文件句柄，避免 fd 泄漏 — 在 Popen 失败时也要执行
                    try:
                        _log.close()
                    except Exception:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[PeriodicRunner] Error in periodic runner loop: %s", e)

    _periodic_runner_task = asyncio.ensure_future(_periodic_runner_loop())
    return _self_check_task, _periodic_runner_task


# ═══════════════════════════════════════════════════════════════════════════════
#  扩展数据源代理 — 桥接到 data_enrich_runner 的缓存
#  这些函数由 market.py 中的 API endpoints 调用。
#  data_enrich_runner 中的 _refresh_*_cache 负责实际数据获取，
#  这里提供 _load/get_ 接口，从 JSON 缓存文件中加载。
# ═══════════════════════════════════════════════════════════════════════════════

_NORTH_CACHE = _CACHE_DIR / "stock_north.json"
_MARGIN_CACHE = _CACHE_DIR / "stock_margin.json"
_LHB_CACHE = _CACHE_DIR / "stock_lhb.json"
_BLOCK_TRADE_CACHE = _CACHE_DIR / "stock_block_trade.json"
_HOLDER_NUM_CACHE = _CACHE_DIR / "stock_holder_num.json"
_EARNINGS_FORECAST_CACHE = _CACHE_DIR / "stock_earnings_forecast.json"
_EARNINGS_EXPRESS_CACHE = _CACHE_DIR / "stock_earnings_express.json"
_RESTRICTED_RELEASE_CACHE = _CACHE_DIR / "stock_restricted_release.json"


# 内存缓存
_north_map: dict = {}
_margin_map: dict = {}
_lhb_map: dict = {}
_block_trade_map: dict = {}
_holder_num_map: dict = {}
_earnings_forecast_map: dict = {}
_earnings_express_map: dict = {}
_restricted_release_map: dict = {}

_north_loaded = False
_margin_loaded = False
_lhb_loaded = False
_block_trade_loaded = False
_holder_num_loaded = False
_earnings_forecast_loaded = False
_earnings_express_loaded = False
_restricted_release_loaded = False
_industry_score_map: dict = {}
_industry_score_loaded = False


def _load_ext_cache_with_status(path: Path, ttl: int = 0) -> tuple[str, dict]:
    """一次完成状态检查和数据加载，避免 cache_status + _load_ext_cache 双重 I/O。

    Returns:
        (status, data) :
            status: "missing" | "corrupted" | "stale" | "fresh"
            data: 解析后的 dict（status == "fresh" 或 "stale" 时返回实际数据，
                  其余状态返回空 dict）
    """
    try:
        if not path.exists():
            return "missing", {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return "corrupted", {}
        if not isinstance(data, dict):
            return "corrupted", {}
        if ttl > 0:
            ts = data.get("_ts", 0)
            if ts > 0:
                if time.time() - ts >= ttl:
                    logger.debug(f"[DataEnrich] Cache {path.stem} stale by _ts (age={time.time() - ts:.0f}s, ttl={ttl}s)")
                    return "stale", data  # 返回数据，让调用者决定 stale 时是否加载旧数据
            else:
                mtime = path.stat().st_mtime
                if time.time() - mtime >= ttl:
                    logger.debug(f"[DataEnrich] Cache {path.stem} stale by mtime (age={time.time() - mtime:.0f}s, ttl={ttl}s)")
                    return "stale", data  # 返回数据，让调用者决定 stale 时是否加载旧数据
        return "fresh", data
    except Exception as e:
        logger.warning(f"[DataEnrich] Failed to load cache {path}: {e}")
        return "corrupted", {}


def _load_ext_cache(path: Path, ttl: int = 0) -> dict:
    """从 JSON 缓存文件加载，失败或过期返回空 dict。

    内部委托给 _load_ext_cache_with_status，避免重复打开文件。
    需要 status 时直接调用 _load_ext_cache_with_status 一次完成。
    """
    status, data = _load_ext_cache_with_status(path, ttl)
    return data if status == "fresh" else {}




def _is_loadable(status: str) -> bool:
    """Check if cache status should overwrite in-memory data.

    Rules:
    - "fresh": new data, overwrite
    - "missing": first boot, init empty
    - "corrupted": file corrupt, treat as missing (clear map)
    - "stale": handled explicitly by callers BEFORE this check;
               NOT included here to avoid ambiguity.
    """
    return status in ("fresh", "missing", "corrupted")




def _load_north_cache():
    global _north_map
    status, new_map = _load_ext_cache_with_status(_NORTH_CACHE, ttl=6 * 3600)  # north TTL: 6h
    with _cache_lock:
        _north_map = new_map
    msg = f"[DataEnrich] North: loaded {len([k for k in _north_map if not k.startswith('_')])} stocks"
    if status == "stale":
        logger.warning(f"{msg} (stale, will refresh in background)")
    else:
        logger.info(msg)

def get_north_map() -> dict:
    return _north_map


def _load_margin_cache():
    global _margin_map
    status, new_map = _load_ext_cache_with_status(_MARGIN_CACHE, ttl=12 * 3600)  # margin TTL: 12h
    with _cache_lock:
        _margin_map = new_map
    msg = f"[DataEnrich] Margin: loaded {len([k for k in _margin_map if not k.startswith('_')])} stocks"
    if status == "stale":
        logger.warning(f"{msg} (stale, will refresh in background)")
    else:
        logger.info(msg)

def get_margin_map() -> dict:
    return _margin_map


def _load_lhb_cache():
    global _lhb_map
    status, new_map = _load_ext_cache_with_status(_LHB_CACHE, ttl=12 * 3600)  # lhb TTL: 12h
    with _cache_lock:
        _lhb_map = new_map
    msg = f"[DataEnrich] LHB: loaded {len([k for k in _lhb_map if not k.startswith('_')])} stocks"
    if status == "stale":
        logger.warning(f"{msg} (stale, will refresh in background)")
    else:
        logger.info(msg)

def get_lhb_map() -> dict:
    return _lhb_map


def _load_block_trade_cache():
    global _block_trade_map
    status, new_map = _load_ext_cache_with_status(_BLOCK_TRADE_CACHE, ttl=12 * 3600)  # block_trade TTL: 12h
    with _cache_lock:
        _block_trade_map = new_map
    msg = f"[DataEnrich] BlockTrade: loaded {len([k for k in _block_trade_map if not k.startswith('_')])} stocks"
    if status == "stale":
        logger.warning(f"{msg} (stale, will refresh in background)")
    else:
        logger.info(msg)

def get_block_trade_map() -> dict:
    return _block_trade_map


def _load_holder_num_cache():
    global _holder_num_map
    status, new_map = _load_ext_cache_with_status(_HOLDER_NUM_CACHE, ttl=24 * 3600)  # holder_num TTL: 24h
    with _cache_lock:
        _holder_num_map = new_map
    msg = f"[DataEnrich] HolderNum: loaded {len([k for k in _holder_num_map if not k.startswith('_')])} stocks"
    if status == "stale":
        logger.warning(f"{msg} (stale, will refresh in background)")
    else:
        logger.info(msg)

def get_holder_num_map() -> dict:
    return _holder_num_map


def _load_earnings_forecast_cache():
    """加载 earnings forecast 缓存。

    Bug10 修复：只有当文件 _ts 比内存 _ts 更新时才覆盖内存，
    避免每 120s reload 时 race condition 导致数据回滚。
    """
    global _earnings_forecast_map
    status, new_map = _load_ext_cache_with_status(_EARNINGS_FORECAST_CACHE, ttl=7 * 24 * 3600)
    if status == "fresh":
        file_ts = new_map.get("_ts", 0)
        with _cache_lock:
            mem_ts = _earnings_forecast_map.get("_ts", 0) if isinstance(_earnings_forecast_map, dict) else 0
            if file_ts <= mem_ts:
                logger.info(f"[DataEnrich] EarningsForecast: file_ts={file_ts:.0f} <= mem_ts={mem_ts:.0f}, keeping in-memory (runner not updated)")
                return
            _earnings_forecast_map = new_map
        logger.info(f"[DataEnrich] EarningsForecast: loaded {len([k for k in _earnings_forecast_map if not k.startswith('_')])} stocks")
    elif status == "stale":
        with _cache_lock:
            _earnings_forecast_map = new_map
        logger.warning(f"[DataEnrich] EarningsForecast: loaded {len([k for k in _earnings_forecast_map if not k.startswith('_')])} stocks (stale, will refresh in background)")
    elif status == "missing":
        with _cache_lock:
            _earnings_forecast_map = {}
        logger.info(f"[DataEnrich] EarningsForecast: cache missing, init empty")
    elif _is_loadable(status):
        with _cache_lock:
            _earnings_forecast_map = {}
        logger.info(f"[DataEnrich] EarningsForecast: corrupted, cleared map")
    else:
        logger.debug(f"[DataEnrich] EarningsForecast: {status}, keeping {len([k for k in _earnings_forecast_map if not k.startswith('_')])} in-memory stocks")
def _load_earnings_express_cache():
    global _earnings_express_map
    status, new_map = _load_ext_cache_with_status(_EARNINGS_EXPRESS_CACHE, ttl=7 * 24 * 3600)
    if status == "fresh":
        file_ts = new_map.get("_ts", 0)
        with _cache_lock:
            mem_ts = _earnings_express_map.get("_ts", 0) if isinstance(_earnings_express_map, dict) else 0
            if file_ts <= mem_ts:
                logger.info(f"[DataEnrich] EarningsExpress: file_ts={file_ts:.0f} <= mem_ts={mem_ts:.0f}, keeping in-memory (runner not updated)")
                return
            _earnings_express_map = new_map
        logger.info(f"[DataEnrich] EarningsExpress: loaded {len([k for k in _earnings_express_map if not k.startswith('_')])} stocks")
    elif status == "stale":
        with _cache_lock:
            _earnings_express_map = new_map
        logger.warning(f"[DataEnrich] EarningsExpress: loaded {len([k for k in _earnings_express_map if not k.startswith('_')])} stocks (stale, will refresh in background)")
    elif status == "missing":
        with _cache_lock:
            _earnings_express_map = {}
        logger.info("[DataEnrich] EarningsExpress: cache missing, init empty")
    elif _is_loadable(status):
        # corrupted: 缓存损坏，清空
        with _cache_lock:
            _earnings_express_map = {}
        logger.info(f"[DataEnrich] EarningsExpress: corrupted, cleared map")
    else:
        # stale: 保留内存中的数据，不覆盖 (handled above)
        logger.debug(f"[DataEnrich] EarningsExpress: {status}, keeping {len([k for k in _earnings_express_map if not k.startswith('_')])} in-memory stocks")


def get_earnings_express_map() -> dict:
    return _earnings_express_map




@_with_metrics
def _refresh_earnings_express_cache():
    """刷新业绩快报缓存（stock_yjkb_em — 季度业绩摘要）。
    主源：East Money 业绩快报接口，支持按财报年度过滤。
    """
    try:
        import akshare as ak
        from datetime import date
        current_year = date.today().year
        result = {}
        # 获取最近3个年度（从旧到新，确保最新年度最后覆盖）
        for year in (current_year - 2, current_year - 1, current_year):
            try:
                df = ak.stock_yjkb_em(date=f"{year}1231")
                if df is None or df.empty:
                    continue
                for _, r in df.iterrows():
                    code = str(r.get("股票代码", "")).strip()
                    if not code or len(code) != 6 or not code.isdigit():
                        continue
                    eps = _sf(r.get("每股收益"))
                    revenue = _sf(r.get("营业收入-营业收入"))
                    revenue_yoy = _sf(r.get("营业收入-同比增长"))
                    net_profit = _sf(r.get("净利润-净利润"))
                    net_profit_yoy = _sf(r.get("净利润-同比增长"))
                    net_asset = _sf(r.get("每股净资产"))
                    roe = _sf(r.get("净资产收益率"))
                    industry = str(r.get("所处行业", "")).strip()
                    announcement = str(r.get("公告日期", "")).strip()

                    entry = {"year": year}
                    if eps is not None: entry["eps"] = eps
                    if revenue is not None: entry["revenue"] = revenue
                    if revenue_yoy is not None: entry["revenue_yoy"] = revenue_yoy
                    if net_profit is not None: entry["net_profit"] = net_profit
                    if net_profit_yoy is not None: entry["net_profit_yoy"] = net_profit_yoy
                    if net_asset is not None: entry["net_assets"] = net_asset
                    if roe is not None: entry["roe"] = roe
                    if industry: entry["industry"] = industry
                    if announcement: entry["announcement"] = announcement
                    # 只保留最新年度（新 entry 的 year >= 已有 entry 的 year 时才覆盖）
                    existing = result.get(code)
                    if existing is None or year >= existing.get("year", 0):
                        result[code] = entry
            except Exception as e:
                logger.debug(f"[DataEnrich] EarningsExpress year {year} failed: {e}")
                continue

        # Zero-fill: 对所有已知股票代码中无数据的股票填充 None
        for code in _get_bond_or_fallback_codes():
            if code not in result:
                result[code] = {
                    "revenue_yoy": None,
                    "net_profit_yoy": None,
                    "year": None,
                    "_data_source": "zero_fill",
                }

        if result:
            _save_cache(_EARNINGS_EXPRESS_CACHE, result)
            _set_global_map("_earnings_express_map", result, replace=True)
            logger.info(f"[DataEnrich] EarningsExpress: {len(result)} stocks refreshed")
            return len(result)
        else:
            logger.warning("[DataEnrich] EarningsExpress: no data fetched")
            return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] EarningsExpress refresh failed: {e}")
        return 0

def _load_restricted_release_cache():
    global _restricted_release_map
    status, new_map = _load_ext_cache_with_status(_RESTRICTED_RELEASE_CACHE, ttl=86400 * 3)
    if status == "fresh":
        file_ts = new_map.get("_ts", 0)
        with _cache_lock:
            mem_ts = _restricted_release_map.get("_ts", 0) if isinstance(_restricted_release_map, dict) else 0
            if file_ts <= mem_ts:
                logger.info(f"[DataEnrich] RestrictedRelease: file_ts={file_ts:.0f} <= mem_ts={mem_ts:.0f}, keeping in-memory (runner not updated)")
                return
            _restricted_release_map = new_map
        logger.info(f"[DataEnrich] RestrictedRelease: loaded {len([k for k in _restricted_release_map if not k.startswith('_')])} events")
    elif status == "stale":
        with _cache_lock:
            _restricted_release_map = new_map
        logger.warning(f"[DataEnrich] RestrictedRelease: loaded {len([k for k in _restricted_release_map if not k.startswith('_')])} events (stale, will refresh in background)")
    elif status == "missing":
        with _cache_lock:
            _restricted_release_map = {}
        logger.info("[DataEnrich] RestrictedRelease: cache missing, init empty")
    elif _is_loadable(status):
        with _cache_lock:
            _restricted_release_map = {}
        logger.info(f"[DataEnrich] RestrictedRelease: corrupted, cleared map")
    else:
        logger.debug(f"[DataEnrich] RestrictedRelease: {status}, keeping {len([k for k in _restricted_release_map if not k.startswith('_')])} in-memory events")

def get_restricted_release_map() -> dict:
    return _restricted_release_map


# ============================================================================
# In-process refresh functions for "extended" cache maps (北向/融资融券/LHB/...)
# 这些原本只在 data_enrich_runner.py 子进程中刷新，再写 JSON 文件被主进程读取。
# 现在在主进程中添加 in-process refresh，避免依赖 runner subprocess。
# 优点：不再有"runner 死了，extended cache 永远空"的单点故障。
# ============================================================================

@_with_metrics
def _refresh_north_cache():
    """主进程内刷新北向资金数据（替代 data_enrich_runner 子进程）

    数据来源：
    - 汇总：ak.stock_hsgt_fund_flow_summary_em（北向资金净流入）
    - 个股：ak.stock_hsgt_individual_em（按可转债正股代码逐股查询最新持股）
      因为批量 `stock_hsgt_hold_stock_em` 在 akshare 1.18.x / 当前网络环境下
      频繁返回 NoneType，改用稳定的单股接口。
    """
    try:
        # 汇总：北向资金净流入
        summary = _run_with_timeout(
            ak.stock_hsgt_fund_flow_summary_em,
            timeout=_TIMEOUT_MEDIUM, default=None, op_name="hsgt_fund_flow_summary_em",
        )
        result = {}
        if summary is not None and len(summary) > 0:
            for _, r in summary.iterrows():
                net_h = _sf(r.get("成交净买额"))
                if net_h is not None:
                    result["_summary"] = {
                        "net": net_h,
                        "date": str(r.get("交易日期", "")),
                        "type": "north",
                    }
        else:
            logger.warning("[DataEnrich] North: summary empty")

        # 个股北向持仓：对可转债正股逐股查询（单股接口稳定）
        #  always fetch all A-share codes for broad coverage (AGENTS.md #46)
        if not _bond_stock_codes:
            _ensure_bond_stock_codes()
        bond_codes = sorted(_bond_stock_codes) if _bond_stock_codes else []
        all_codes = bond_codes[:]
        # Extend to full A-share universe regardless of bond stock availability
        try:
            df_all = ak.stock_info_a_code_name()
            if df_all is not None and not df_all.empty:
                a_codes = [str(c).strip().zfill(6) for c in df_all["代码"].tolist() if str(c).strip().isdigit()]
                all_codes = list(dict.fromkeys(bond_codes + a_codes))  # preserve order, dedup
        except Exception as e:
            logger.debug(f"[DataEnrich] North: failed to get all A-share codes: {e}")
        if not all_codes:
            logger.debug("[DataEnrich] North: no codes available, skipping per-stock query")

        def _fetch_one(code: str):
            try:
                df = _run_with_timeout(
                    ak.stock_hsgt_individual_em, code,
                    timeout=_TIMEOUT_FAST, default=None,
                    op_name=f"north_{code}",
                    quiet_errors=True,
                )
                if df is None or len(df) == 0:
                    return None
                last = df.iloc[-1]
                market_val = _sf(last.get("持股市值"))
                net_buy = _sf(last.get("今日增持资金"))
                if market_val is None and net_buy is None:
                    return None
                entry = {}
                if market_val is not None:
                    entry["hold_market_cap"] = market_val
                if net_buy is not None:
                    entry["add_capital"] = net_buy  # 今日增持资金（注意：是资金而非股数）
                # 同时保留持股数量（如果 API 返回）
                # AKShare 返回列名：当日持股数量 / 当日累计持股数量
                hold_shares = _sf(last.get("当日持股数量")) or _sf(last.get("当日累计持股数量"))
                if hold_shares is not None and hold_shares > 0:
                    entry["hold_shares"] = hold_shares
                return code, entry
            except Exception:
                return None

        if all_codes:
            processed = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
                futures = {pool.submit(_fetch_one, c): c for c in all_codes}
                # 用 wait() + FIRST_COMPLETED + 60s 硬截止，按批处理 done futures。
                # 原 ALL_COMPLETED 让少量卡死的 future 拖慢整体 16+ 分钟。
                deadline = time.time() + 60
                while futures and time.time() < deadline:
                    done, futures = concurrent.futures.wait(
                        futures, timeout=10, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    for fut in done:
                        try:
                            r = fut.result()
                            if r:
                                result[r[0]] = r[1]
                                processed += 1
                        except Exception:
                            pass
                    if processed % 200 == 0:
                        _save_cache(_NORTH_CACHE, result)
                # 超时后取消剩余 futures，保留已完成的（多数股票已有数据）
                if futures:
                    logger.warning(f"[DataEnrich] North: {len(futures)} (of {len(all_codes)}) futures unfinished after 60s, keeping {len(result)} completed")
                    for fut in futures:
                        fut.cancel()

        # Zero-fill: 无论 API 是否成功，都对所有已知股票代码填充默认值
        # 使用 _get_bond_or_fallback_codes() 而非 _ensure_bond_stock_codes()，
        # 避免启动阶段 AKShare 信号量争用导致超时
        # Skip zero_fill to avoid polluting coverage stats
        # Missing codes will be handled as "no data" in enrich_quotes

        if result:
            _set_global_map("_north_map", result, replace=True)
            _save_cache(_NORTH_CACHE, result)
            count = len([k for k in result if not k.startswith("_")])
            logger.info(f"[DataEnrich] North: {count} stocks + summary refreshed")
            return count
        return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] North in-proc refresh failed: {e}")
        return 0


@_with_metrics
def _refresh_margin_cache():
    """主进程内刷新融资融券数据。

    采用交易所每日融资融券明细：
    - 深交所：ak.stock_margin_detail_szse(date)
    - 上交所：ak.stock_margin_detail_sse(date)
    自动回退最近 10 个交易日（节假日无数据）。
    """
    try:
        result = {}

        def _margin_detail_for_date(exchange: str, date_str: str):
            fn = ak.stock_margin_detail_szse if exchange == "szse" else ak.stock_margin_detail_sse
            return _run_with_timeout(
                lambda: fn(date=date_str),
                timeout=_TIMEOUT_MEDIUM, default=None,
                op_name=f"margin_detail_{exchange}_{date_str}",
                quiet_errors=True,  # East Money 融资明细接口在非交易日/某些日期不稳定，降低日志噪音
            )

        for exchange, code_col_candidates, balance_col_candidates in [
            ("szse", ["证券代码", "代码"], ["融资余额", "融资融券余额"]),
            ("sse", ["标的证券代码", "证券代码", "代码"], ["融资余额", "融资融券余额"]),
        ]:
            df = None
            date_str = None
            for days in range(10):
                date_str = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
                try:
                    df = _margin_detail_for_date(exchange, date_str)
                except Exception:
                    df = None
                if df is not None and len(df) > 0:
                    break
            if df is None or len(df) == 0:
                logger.warning(f"[DataEnrich] Margin: {exchange.upper()} no data for last 10 days")
                continue

            code_col = next((c for c in code_col_candidates if c in df.columns), None)
            balance_col = next((c for c in balance_col_candidates if c in df.columns), None)
            if not code_col:
                logger.warning(f"[DataEnrich] Margin: {exchange.upper()} missing code column")
                continue

            filled = 0
            for _, r in df.iterrows():
                code = str(r.get(code_col, "")).strip()
                if not code or len(code) != 6 or not code.isdigit():
                    continue
                balance = _sf(r.get(balance_col)) if balance_col else None
                # 若当前交易所已有数据，保留首次出现（通常 SSE/SZSE 不重叠）
                if code not in result:
                    result[code] = {
                        "margin_balance": balance,  # 保留 None 让前端区分"无数据"
                        "_data_source": f"{exchange}_{date_str}",
                    }
                    filled += 1
            logger.info(f"[DataEnrich] Margin {exchange.upper()}: {filled} stocks from {date_str}")

        # Zero-fill: 对所有已知股票代码中无数据的股票填充 0
        # 使用 _get_bond_or_fallback_codes() 而非 _ensure_bond_stock_codes()，
        # 避免启动阶段 AKShare 信号量争用导致超时
        for code in _get_bond_or_fallback_codes():
            if code not in result:
                result[code] = {
                    "margin_balance": None,  # 用 None 区分"无融资余额"和"0 元"
                    "_data_source": "zero_fill",
                }

        if result:
            # Add summary with total margin balance stats
            real_entries = [v for v in result.values() if isinstance(v, dict) and v.get("_data_source", "").startswith(("szse_", "sse_"))]
            total_balance = sum(v.get("margin_balance", 0) or 0 for v in real_entries)
            result["_summary"] = {
                "total_balance": round(total_balance, 2),
                "stock_count": len(real_entries),
                "date": datetime.now().strftime("%Y%m%d"),
            }
            _set_global_map("_margin_map", result, replace=True)
            _save_cache(_MARGIN_CACHE, result)
            logger.info(f"[DataEnrich] Margin: {len(result)} stocks refreshed (含 zero_fill)")
            return len(result)
        if _margin_map:
            logger.warning("[DataEnrich] Margin: all APIs returned empty, keeping existing cache")
            return len(_margin_map)
        return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] Margin in-proc refresh failed: {e}")
        return 0


@_with_metrics
def _refresh_lhb_cache():
    """主进程内刷新龙虎榜数据。

    语义说明：ak.stock_lhb_stock_statistic_em 返回"近一月上榜次数"（累计值），
    不是"当日上榜次数"。前端展示时应注明"近 1 月累计"。

    增量更新：保留上一次的 lhb_count 作为 _prev_count，新值作为 lhb_count。
    增量 _delta = lhb_count - _prev_count 表示本次刷新新增的上榜次数。
    """
    try:
        # ak.stock_lhb_stock_statistic_em: 龙虎榜个股统计（近一月）
        df = _run_with_timeout(
            ak.stock_lhb_stock_statistic_em,
            timeout=_TIMEOUT_SLOW, default=None, op_name="lhb_stock_statistic_em",
        )
        result = {}
        if df is None or len(df) == 0:
            logger.warning("[DataEnrich] LHB: empty result")
            # 不提前 return，让零填充处理后续
        else:
            # 增量：保留旧的 lhb_count 作为 _prev_count
            prev = _lhb_map if isinstance(_lhb_map, dict) else {}
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                if not code or len(code) != 6 or not code.isdigit():
                    continue
                cnt = _sf(r.get("上榜次数"))
                new_count = int(cnt) if cnt else 0
                old_entry = prev.get(code, {})
                old_count = old_entry.get("lhb_count", 0) if isinstance(old_entry, dict) else 0
                result[code] = {
                    "lhb_count": new_count,
                    "_prev_count": old_count,
                    "_delta": new_count - old_count,
                    "_data_source": "lhb_stock_statistic_em",
                }
        # Zero-fill: 未上榜的股票显式写入 lhb_count=0，区分"无上榜"与"数据缺失"
        # 放在 if result 外部，确保即使 API 失败也有基础数据
        # 使用 _get_bond_or_fallback_codes() 而非 _ensure_bond_stock_codes()，
        # 避免启动阶段 AKShare 信号量争用导致超时
        for code in _get_bond_or_fallback_codes():
            if code not in result:
                result[code] = {
                    "lhb_count": None,  # 用 None 区分"未上榜"和"上榜 0 次"
                    "_prev_count": 0,
                    "_delta": 0,
                    "_data_source": "zero_fill",
                }
        if result:
            _set_global_map("_lhb_map", result, replace=True)
            _save_cache(_LHB_CACHE, result)
            logger.info(f"[DataEnrich] LHB: {len(result)} stocks refreshed (含 _delta 增量)")
            return len(result)
        return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] LHB in-proc refresh failed: {e}")
        return 0


@_with_metrics
def _refresh_block_trade_cache():
    """主进程内刷新大宗交易数据

    使用 ak.stock_dzjy_mrmx(symbol='A股', start_date, end_date) 获取 A 股大宗交易明细，
    回退最近 5 个交易日（节假日无数据时向前查找）。
    """
    try:
        # 保留已有缓存，API 临时不可用时不会立即丢数据
        result = dict(_block_trade_map) if isinstance(_block_trade_map, dict) else {}
        df = None
        for days in range(5):
            end_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 2)).strftime("%Y%m%d")
            df = _run_with_timeout(
                lambda s=start_date, e=end_date: ak.stock_dzjy_mrmx(symbol="A股", start_date=s, end_date=e),
                timeout=_TIMEOUT_MEDIUM, default=None,
                op_name=f"dzjy_mrmx_{end_date}",
                quiet_errors=True,  # East Money 大宗交易明细接口不稳定，降低日志噪音
            )
            if df is not None and len(df) > 0:
                break
        if df is None or len(df) == 0:
            if result:
                logger.warning("[DataEnrich] BlockTrade: stock_dzjy_mrmx unavailable, keeping existing cache")
            else:
                logger.warning("[DataEnrich] BlockTrade: empty result and no existing cache")
            # 即使在 API 失败时也进行零填充
        else:
            for _, r in df.iterrows():
                code = str(r.get("证券代码", "")).strip()
                if not code or len(code) != 6:
                    continue
                amount = _sf(r.get("成交额"))
                if amount and amount > 0:
                    result[code] = {"block_trade_amount": amount}
        # Zero-fill: 无大宗交易的股票显式写入 0，区分"无交易"与"数据缺失"
        # 使用 _get_bond_or_fallback_codes() 而非 _ensure_bond_stock_codes()，
        # 避免启动阶段 AKShare 信号量争用导致超时
        for code in _get_bond_or_fallback_codes():
            if code not in result:
                result[code] = {"block_trade_amount": 0}
        if result:
            _set_global_map("_block_trade_map", result, replace=True)
            _save_cache(_BLOCK_TRADE_CACHE, result)
            logger.info(f"[DataEnrich] BlockTrade: {len(result)} stocks refreshed")
            return len(result)
        return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] BlockTrade in-proc refresh failed: {e}")
        return 0


@_with_metrics
def _refresh_holder_num_cache():
    """主进程内刷新股东人数数据。

    重要：akshare 1.18.x 没有批量"股东人数"接口（stock_holder_num_em 不存在），
    只有单股接口 stock_main_stock_holder(stock=code)。
    采用 10 并发线程池批量调用，优先覆盖 _bond_stock_codes，
    然后扩展到全 A 股（上限 1000 只），避免启动卡住太久。
    """
    try:
        if not callable(getattr(ak, "stock_main_stock_holder", None)):
            logger.warning("[DataEnrich] HolderNum: akshare 接口 stock_main_stock_holder 不可用")
            return 0
        if not _bond_stock_codes:
            _ensure_bond_stock_codes()
        bond_codes = sorted(_bond_stock_codes) if _bond_stock_codes else []
        all_codes = bond_codes[:]
        # 限制到 300 只股票（top 300 个按代码排序），避免单股 API 慢导致 5+ 分钟
        # periodic runner 后续会补全剩余 854 只
        MAX_HOLDER_CODES = 300
        if len(all_codes) < MAX_HOLDER_CODES:
            try:
                df_all = _run_with_timeout(
                    ak.stock_info_a_code_name,
                    timeout=30.0, default=None,
                    op_name="holder_stock_info_a_code_name",
                )
                if df_all is not None and not df_all.empty:
                    a_codes = [str(c).strip().zfill(6) for c in df_all["代码"].tolist() if str(c).strip().isdigit()]
                    seen = set(all_codes)
                    for c in a_codes:
                        if c not in seen and len(all_codes) < MAX_HOLDER_CODES:
                            all_codes.append(c)
                            seen.add(c)
            except Exception:
                pass
        if not all_codes:
            logger.debug("[DataEnrich] HolderNum: no codes available, skipping")
            return 0

        result = {}
        # 10 并发调用（akshare 文档建议不超过 10 触发 rate limit）
        def _fetch_one(code: str):
            try:
                df = _run_with_timeout(
                    ak.stock_main_stock_holder, code,
                    timeout=_TIMEOUT_FAST, default=None,
                    op_name=f"holder_{code}",
                )
                if df is None or len(df) == 0:
                    return None
                # 取最新一条股东记录（包含股东总数字段）
                last = df.iloc[0]
                # 修复：使用"股东总数"而非"持股数量"（后者是单个大股东持股）
                holders = _sf(last.get("股东总数"))
                return code, holders
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_one, c): c for c in all_codes}
            processed = 0
            # 用 wait() 配合 FIRST_COMPLETED，按批处理 done futures。
            # 避免 ALL_COMPLETED 让少量卡死的 future 拖慢整体。
            # 总超时 = 60s（远小于扩展执行器的 300s 限制），超时后保留已完成的
            # 缓存值，让 periodic runner 在下次循环继续补充。
            deadline = time.time() + 60
            while futures and time.time() < deadline:
                done, futures = concurrent.futures.wait(
                    futures, timeout=10, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for fut in done:
                    try:
                        r = fut.result()
                        if r:
                            code, holders = r
                            if holders and holders > 0:
                                # 用上一次缓存的 holder_num 计算真实 change
                                prev_entry = _holder_num_map.get(code, {}) if _holder_num_map else {}
                                prev_count = prev_entry.get("holder_num") if isinstance(prev_entry, dict) else None
                                if isinstance(prev_count, (int, float)) and prev_count > 0:
                                    holder_num_change = holders - prev_count
                                else:
                                    holder_num_change = None
                                result[code] = {
                                    "holder_num": holders,
                                    "holder_num_change": holder_num_change,
                                    "_data_source": "estimated",
                                }
                            processed += 1
                    except Exception:
                        pass
                    if processed % 100 == 0:
                        _save_cache(_HOLDER_NUM_CACHE, result)
            # 超时后：剩余 futures 取消（让线程退出），保留已完成的
            if futures:
                logger.warning(
                    f"[DataEnrich] HolderNum: {len(futures)} (of {len(all_codes)}) "
                    f"futures unfinished after 60s, keeping {len(result)} completed"
                )
                for fut in futures:
                    fut.cancel()

        # 若 result 为空（API 全部失败），回退到磁盘缓存
        # holder_num=0 在物理上不可能（任何公司都有股东），
        # 所以 zero_fill 没有意义，但缓存中的旧数据仍可作为 "上次成功值" 使用
        if not result and _holder_num_map:
            logger.warning(
                f"[DataEnrich] HolderNum: API returned empty, keeping existing cache "
                f"({len(_holder_num_map)} stocks)"
            )
            return len(_holder_num_map)
        if result:
            _set_global_map("_holder_num_map", result, replace=True)
            _save_cache(_HOLDER_NUM_CACHE, result)
            logger.info(f"[DataEnrich] HolderNum: {len(result)}/{len(all_codes)} stocks refreshed")
            return len(result)
        return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] HolderNum in-proc refresh failed: {e}")
        return 0


@_with_metrics
def _refresh_earnings_forecast_cache():
    """主进程内刷新业绩预告数据。

    字段语义说明：ak.stock_yjyg_em 返回"业绩变动幅度"（YoY % 变化），
    不是预测的 EPS 数值。我们存储为 yoy_change_pct 字段而非 eps_forecast，
    避免字段名误导下游消费方（如 Xuanji/Strategy 模块）。
    前端展示为"业绩预告同比变动"。

    接口需要传入财报发布日期（季度末），默认 20200331 已过时；
    这里自动计算当前季度末，若空数据则回退到上一季度。
    修复：合并所有 candidate_dates 的数据，而不是只取第一个有数据的 period。
    """
    try:
        import calendar
        now = datetime.now()
        quarter_months = [3, 6, 9, 12]
        current_quarter = (now.month - 1) // 3
        candidate_dates = []
        for i in range(4):
            q = (current_quarter - i) % 4
            year = now.year if i == 0 or q <= current_quarter else now.year - 1
            month = quarter_months[q]
            day = calendar.monthrange(year, month)[1]
            candidate_dates.append(f"{year}{month:02d}{day:02d}")

        result = {}
        for date_str in candidate_dates:
            try:
                df = _run_with_timeout(
                    ak.stock_yjyg_em, date_str,
                    timeout=_TIMEOUT_MEDIUM, default=None, op_name=f"yjyg_em_{date_str}",
                )
                if df is None or len(df) == 0:
                    continue
                count = 0
                for _, r in df.iterrows():
                    code = str(r.get("股票代码", "")).strip()
                    if not code or len(code) != 6:
                        continue
                    if code in result:
                        continue
                    change_pct = _sf(r.get("业绩变动幅度"))
                    if change_pct is not None:
                        entry = {
                            "yoy_change_pct": change_pct,
                            "_date": date_str,
                        }
                        # Try to extract change_desc and reason from various column names
                        for col_name in ["业绩预告摘要", "业绩变动原因", "变动原因", "业绩预告内容", "摘要"]:
                            val = r.get(col_name)
                            if val is not None and str(val).strip():
                                entry["change_desc"] = str(val).strip()
                                break
                        for col_name in ["业绩变动原因", "变动原因", "原因"]:
                            val = r.get(col_name)
                            if val is not None and str(val).strip():
                                if "change_desc" not in entry or str(val).strip() != entry["change_desc"]:
                                    entry["reason"] = str(val).strip()
                                    break
                        result[code] = entry
                        count += 1
                logger.info(f"[DataEnrich] EarningsForecast: {date_str}={count} entries, total={len(result)}")
                if len(result) >= 1000:
                    break
            except Exception as e:
                logger.debug(f"[DataEnrich] EarningsForecast: {date_str} failed: {e}")
                continue

        # Zero-fill: 对所有已知股票代码中无数据的股票填充 None
        # 使用 _get_bond_or_fallback_codes() 而非 _ensure_bond_stock_codes()，
        # 避免启动阶段 AKShare 信号量争用导致超时
        for code in _get_bond_or_fallback_codes():
            if code not in result:
                result[code] = {
                    "yoy_change_pct": None,
                    "_date": "",
                    "_data_source": "zero_fill",
                }

        if result:
            _set_global_map("_earnings_forecast_map", result, replace=True)
            _save_cache(_EARNINGS_FORECAST_CACHE, result)
            logger.info(f"[DataEnrich] EarningsForecast: {len(result)} stocks refreshed")
            return len(result)
        return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] EarningsForecast in-proc refresh failed: {e}")
        return 0


@_with_metrics
def _refresh_restricted_release_cache():
    """主进程内刷新限售解禁数据

    使用 ak.stock_restricted_release_detail_em(start_date, end_date) 批量获取
    未来 30 天解禁明细，并按股票代码聚合解禁数量/市值。
    """
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = datetime.now().strftime("%Y%m%d")
        # 获取未来 30 天（更宽窗口以增加命中概率）
        query_end = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
        df = _run_with_timeout(
            lambda: ak.stock_restricted_release_detail_em(start_date=start_date, end_date=query_end),
            timeout=_TIMEOUT_SLOW, default=None,
            op_name="restricted_release_detail_em",
            quiet_errors=True,  # EM 接口无数据时可能返回 NoneType
        )
        if df is None or len(df) == 0:
            logger.warning("[DataEnrich] RestrictedRelease: empty result")
            # 即使 API 返回空，也使用空 result 进行零填充
            result = {}
        else:
            result = {}
            for _, r in df.iterrows():
                code = str(r.get("股票代码", "")).strip()
                if not code or len(code) != 6:
                    continue
                amount = _sf(r.get("解禁数量")) or _sf(r.get("实际解禁市值"))
                if amount and amount > 0:
                    entry = result.setdefault(code, {"restricted_release_amount": 0})
                    entry["restricted_release_amount"] += amount
        # Zero-fill: 对所有已知股票代码中无数据的股票填充 0
        # 使用 _get_bond_or_fallback_codes() 而非 _ensure_bond_stock_codes()，
        # 避免启动阶段 AKShare 信号量争用导致超时
        for code in _get_bond_or_fallback_codes():
            if code not in result:
                result[code] = {
                    "restricted_release_amount": None,  # 用 None 区分"无解禁"和"解禁 0 股"
                    "_data_source": "zero_fill",
                }
        if result:
            _set_global_map("_restricted_release_map", result, replace=True)
            _save_cache(_RESTRICTED_RELEASE_CACHE, result)
            logger.info(f"[DataEnrich] RestrictedRelease: {len(result)} events refreshed")
            return len(result)
        return 0
    except Exception as e:
        logger.warning(f"[DataEnrich] RestrictedRelease in-proc refresh failed: {e}")
        return 0

# by the runner subprocess, not refreshed from main process.
def get_concept_sources() -> dict[str, dict[str, bool]]:
    """概念数据源归属：concept_name -> {"em": bool, "ths": bool}"""
    # TTL=7天：概念板块归属信息不会频繁变化，但定期刷新可确保新板块被纳入
    status, raw = _load_ext_cache_with_status(_CONCEPT_SOURCE_CACHE, ttl=86400 * 7)
    if status in ("fresh", "stale"):
        _concept_source_map.update(raw)
    return _concept_source_map



# ==================== 测试隔离 ====================
# 单元测试需要从一个干净的内存状态开始，而不是上一个测试写入的 dict。
# 这个函数被 conftest.py 的 autouse fixture 调用。

def reset_module_state_for_testing() -> None:
    """重置所有模块级全局状态（仅用于单元测试）

    警告：此函数会清空所有缓存。在生产代码中绝对不要调用。
    每次 pytest 测试结束后，autouse fixture 会调用此函数确保下一次测试
    从空白状态开始，避免模块级单例状态污染导致的 flaky tests。
    """
    global _industry_map, _industry_loaded
    global _spot_map, _spot_loaded
    global _fin_map, _fin_loaded
    global _fund_flow_map, _fund_flow_loaded
    global _debt_map, _debt_loaded
    global _vol_map, _vol_loaded
    global _buyback_map, _buyback_loaded
    global _mgmt_map, _mgmt_loaded
    global _pledge_map, _pledge_loaded
    global _momentum_map, _momentum_loaded
    global _event_map, _event_loaded
    global _bond_outstanding_map, _bond_outstanding_loaded
    global _call_status_map, _call_status_loaded
    global _name_map, _name_loaded
    global _concept_map, _concept_loaded
    global _concept_source_map
    global _industry_score_map, _industry_score_loaded
    global _holder_num_map, _holder_num_loaded
    global _analyst_rank_map, _analyst_rank_loaded
    global _main_biz_map, _main_biz_loaded
    global _macro_cpi_map, _macro_cpi_loaded
    global _macro_ppi_map, _macro_ppi_loaded
    global _macro_m2_map, _macro_m2_loaded
    global _macro_lpr_map, _macro_lpr_loaded
    global _north_map, _north_loaded
    global _margin_map, _margin_loaded
    global _lhb_map, _lhb_loaded
    global _block_trade_map, _block_trade_loaded
    global _earnings_forecast_map, _earnings_forecast_loaded
    global _earnings_express_map, _earnings_express_loaded
    global _restricted_release_map, _restricted_release_loaded
    global _bond_stock_codes, _bond_codes
    global _stock_name_map, _name_loaded

    # 重置所有 dict 与 _loaded 标记
    for name, val in list(globals().items()):
        if name.startswith('_') and isinstance(val, dict) and not name.startswith('__'):
            val.clear()
        elif name.endswith('_loaded') and isinstance(val, bool):
            globals()[name] = False
    _bond_stock_codes = set()
    _bond_codes = set()
    _stock_name_map = {}
