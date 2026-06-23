"""Shared utility functions for data_enrich.py and data_enrich_runner.py."""

import json
import logging
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent / "_cache"


def _ensure_cache_dir() -> Path:
    if not _CACHE_DIR.exists():
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return Path(tempfile.gettempdir()) / "lianghua_data_cache"
    return _CACHE_DIR


def load_cache(path, ttl: Optional[float] = None) -> Optional[dict]:
    """Load a JSON cache file. Returns None if not found, corrupted, or expired.

    改进 (2025-06-20): 支持 TTL 过期检查。若提供 ttl 且缓存中的 _ts 字段
    超过 ttl 秒，则返回 None 触发重新刷新。

    Args:
        path: 缓存文件路径
        ttl: 可选的过期时间（秒）。None 表示不检查过期。
    """
    try:
        p = Path(path)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        # TTL 过期检查
        if ttl is not None and isinstance(data, dict):
            ts = data.get("_ts")
            if ts is not None and (time.time() - ts) > ttl:
                logger.info(f"[DataEnrich] Cache expired: {path} (ttl={ttl}s, age={int(time.time() - ts)}s)")
                return None
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"[DataEnrich] Cache corrupted: {path} -> {e}")
        return None
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"[DataEnrich] Cache load error: {path} -> {e}")
        return None


def _sanitize_for_json(v):
    """递归清理 NaN/Inf，使数据结构可被 json.dump 序列化。

    处理：
      - float NaN/Inf → 删除（返回哨兵 _DROP 让调用方跳过）
      - dict → 递归清理每个 value
      - list → 递归清理每个元素（保留 list 类型）
      - tuple → 转为 list（json 不支持 tuple）
      - 其他 → 原样返回

    性能优化：list 用 walrus operator + 单次递归调用，避免判断+递归的双重开销。
    """
    if isinstance(v, float):
        return _DROP if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, dict):
        cleaned = {}
        for k, val in v.items():
            # Skip zero_fill debugging keys to reduce cache file size
            if k == "_data_source":
                continue
            cv = _sanitize_for_json(val)
            if cv is not _DROP:
                cleaned[k] = cv
        return cleaned
    if isinstance(v, (list, tuple)):
        # 单次遍历：用 walrus operator 一次性判断+递归
        # 替代原来的两次 _sanitize_for_json(item) 调用
        return [
            cv for item in v
            if (cv := _sanitize_for_json(item)) is not _DROP
        ]
    return v


# 哨兵：使用 Ellipsis (...) 而非 object()，因为：
# 1. ... 是 Python 内置单例，is 比较安全 (id 唯一)
# 2. ... 不可能被用户数据意外持有（用户几乎不会用 Ellipsis 作为值）
# 3. ... 可被 json.dump 序列化（但 save_cache 在清理由 _DROP 标记的对象前不会让 _DROP 进入输出）
_DROP = ...


def save_cache(path, data: dict, preserve_ts: bool = False) -> None:
    """Atomically save data to a JSON cache file with _ts timestamp.

    递归清理所有嵌套结构（dict/list/tuple）中的 NaN/Inf，
    防止 json.dump 抛出 "Out of range float values are not JSON compliant"。

    性能2：原地修改 _ts 而非 {**data, "_ts": t} 创建新 dict（节省一次全量复制）。
    @param preserve_ts: 若 True，保留 data 中已有的 _ts（不覆盖）。
                        默认 False 始终刷新 _ts（保证新鲜度反映当前时间）。
    """
    if not data or not isinstance(data, dict):
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 性能2：原地修改避免 dict spread（大 dict 时节省内存）
        if not preserve_ts:
            data["_ts"] = time.time()
        clean = _sanitize_for_json(data)
        # 移除 _DROP 哨兵对象（极少见：_ts 本身是 NaN 等极端情况）
        if isinstance(clean, dict) and _DROP in clean.values():
            clean = {k: v for k, v in clean.items() if v is not _DROP}
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(p)
    except TypeError as e:
        # Bug11: Ellipsis/Ellipsis-like 残留导致 JSON 序列化失败
        # 记录警告并尝试移除所有非基础 Python 类型
        logger.warning(f"[DataEnrich] Cache JSON serialize error (TypeError): {path} -> {e}")
        try:
            # 终极降级：过滤所有 _is_safe_for_json 的值
            def _recurse_safe(v):
                if isinstance(v, (str, int, float, bool, type(None))):
                    return v
                if isinstance(v, (list, tuple)):
                    result = [_recurse_safe(x) for x in v
                              if x is not _DROP and not isinstance(x, (type(Ellipsis), type(...)))]
                    return result
                if isinstance(v, dict):
                    return {k: _recurse_safe(val) for k, val in v.items()
                            if val is not _DROP and not isinstance(val, (type(Ellipsis), type(...)))}
                return None
            final_clean = _recurse_safe(clean)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(final_clean, f, ensure_ascii=False, separators=(",", ":"))
            tmp.replace(p)
            logger.warning(f"[DataEnrich] Save succeeded after Ellipsis filter for {path}")
        except Exception as e2:
            logger.error(f"[DataEnrich] Cache save failed even after Ellipsis filter: {path} -> {e2}")
    except Exception as e:
        logger.warning(f"[DataEnrich] Cache save error: {path} -> {e}")


def fresh(ttl: int, data, cache_path=None) -> bool:
    """Check if cached data is still fresh within TTL (seconds).

    If data has no _ts but cache_path is provided, fall back to the file's mtime.
    """
    if data is None:
        return False
    ts = data.get("_ts", 0) if isinstance(data, dict) else 0
    if not ts and cache_path is not None:
        try:
            p = Path(cache_path)
            if p.exists():
                ts = p.stat().st_mtime
        except Exception:
            pass
    return time.time() - ts < ttl


def safe_float(v, default=None) -> Optional[float]:
    """Safely convert any value to float; returns default for None/NaN/Inf/empty.
    Supports comma-separated numbers like "1,000.5"."""
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return default
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
            if v == "" or v == "-":
                return default
        fv = float(v)
        if fv != fv or math.isinf(fv):
            return default
        return fv
    except (ValueError, TypeError):
        return default


def safe_int(v, default=None) -> Optional[int]:
    """Safely convert any value to int; returns default for None/invalid/inf."""
    if v is None or v == "":
        return default
    try:
        f = float(v)
        if math.isinf(f) or math.isnan(f):
            return default
        return int(f)
    except (ValueError, TypeError, OverflowError):
        return default


def safe_str(v) -> str:
    """Safely convert any value to a stripped string; returns empty string for None/NaN."""
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    try:
        return str(v).strip()
    except Exception:
        return ""


# ── 跨进程共享 metrics 文件读写（带文件锁） ──
# data_enrich.py 主进程与 data_enrich_runner.py 子进程都会写入 refresh_metrics.json，
# 必须用锁避免并发写导致 JSON 损坏。

def _lock_file_path(path: Path) -> Path:
    """返回与目标文件配套的锁文件路径。"""
    return path.with_suffix(path.suffix + ".lock")


def _acquire_file_lock(lock_path: Path, timeout: float = 5.0):
    """尝试获取文件锁，返回一个应在 with 语句中使用的对象。

    优先使用 portalocker；不可用时在 Unix 上用 fcntl.flock；Windows 无 fcntl
    时退化为基于锁文件存在的忙等待（可靠性较低，但避免崩溃）。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import portalocker
        f = open(lock_path, "w")
        portalocker.lock(f, portalocker.LOCK_EX, timeout=timeout)
        return f
    except Exception:
        pass
    if hasattr(os, "O_EXLOCK"):
        # BSD/macOS 专用：打开时直接加排他锁
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | os.O_EXLOCK)
        return _BSDLock(fd)
    try:
        import fcntl
        f = open(lock_path, "w")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return f
    except Exception:
        # 最终降级：通过锁文件存在性做简单互斥（不 robust，但比直接并发写好）
        return _FallbackLock(lock_path, timeout=timeout)


class _BSDLock:
    def __init__(self, fd: int):
        self._fd = fd

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            os.close(self._fd)
        except Exception:
            pass


class _FallbackLock:
    def __init__(self, lock_path: Path, timeout: float = 5.0):
        self.lock_path = lock_path
        self.timeout = timeout

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                # 独占创建锁文件；若已存在则等待
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    return self  # 超时不再等待，直接执行
                time.sleep(0.05)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.lock_path.exists():
                self.lock_path.unlink()
        except Exception:
            pass


def record_refresh_metric(
    metrics_file: Path,
    name: str,
    elapsed_s: float,
    count: int,
    status: str = "ok",
    error: str = "",
    extra: Optional[dict] = None,
) -> None:
    """向共享 metrics 文件写入/更新一条刷新指标。

    该函数被 data_enrich.py 主进程和 data_enrich_runner.py 子进程共同使用，
    通过文件锁保证并发安全。_inproc 内部实现条目会被过滤。
    """
    if "_inproc" in name:
        return
    # Debug: track caller for metrics writes to diagnose stale/race issues
    import traceback as _tb
    _stack = _tb.extract_stack()
    _callers = [f"{s.filename.split('/')[-1]}:{s.lineno}({s.name})" for s in _stack[-4:-1]]
    logger.info(f"[MetricsTrace] record_refresh_metric({name}, count={count}, status={status}) callers={' <- '.join(_callers)}")
    metrics_file = Path(metrics_file)
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_file_path(metrics_file)
    entry = {
        "name": name,
        "elapsed_s": round(elapsed_s, 2),
        "count": int(count),
        "status": status,
        "error": error[:200] if error else "",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    }
    if extra:
        entry.update(extra)

    with _acquire_file_lock(lock_path, timeout=5.0):
        try:
            data = load_cache(metrics_file) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data[name] = entry
        try:
            save_cache(metrics_file, data, preserve_ts=True)
        except Exception as e:
            logger.warning(f"[Metrics] Failed to save {metrics_file}: {e}")


def load_refresh_metrics(metrics_file: Path) -> dict:
    """加载共享 metrics 文件，返回 name -> entry 的 dict（不含 _ts）。"""
    try:
        data = load_cache(metrics_file)
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k != "_ts" and isinstance(v, dict)}
    except Exception as e:
        logger.debug(f"[Metrics] Failed to load {metrics_file}: {e}")
        return {}


# ── 完整性保护：导入时自检 ──
# 防 AGENTS.md Rule 关于 linter/外部工具损坏文件的回归：
# 当文件被截断/重复时，所有预期导出都必须存在，否则立即报错。

_REQUIRED_EXPORTS = frozenset({
    "load_cache", "save_cache", "fresh",
    "safe_float", "safe_int", "safe_str",
    "record_refresh_metric", "load_refresh_metrics",
})


_REQUIRED_SIGNATURES: dict[str, int] = {
    "load_cache": 1,   # (path)
    "save_cache": 2,   # (path, data)
    "fresh": 1,        # (ttl, ...) — 至少 1 个位置参数
    "safe_float": 1,   # (v, ...) — 至少 1 个位置参数
    "safe_int": 1,     # (v, ...) — 至少 1 个位置参数
    "safe_str": 1,     # (v) — 至少 1 个位置参数
    "record_refresh_metric": 2,  # (metrics_file, name)
    "load_refresh_metrics": 1,   # (metrics_file)
}


def _self_integrity_check():
    """导入时执行，检查本文件是否被 linter/外部工具损坏/截断/重复。

    规则：
    1. 所有 _REQUIRED_EXPORTS 必须存在
    2. 每个函数必须是 callable（避免被替换为 None 或注释）
    3. 每个函数的签名必须至少有 _REQUIRED_SIGNATURES 规定的最小参数数量
    """
    import inspect as _inspect

    missing = [name for name in _REQUIRED_EXPORTS if name not in globals()]
    if missing:
        raise ImportError(
            f"[data_enrich_utils] Integrity check FAILED — missing exports: {missing}. "
            f"File may have been truncated or corrupted by an external tool/linter."
        )
    non_callable = [name for name in _REQUIRED_EXPORTS if not callable(globals()[name])]
    if non_callable:
        raise ImportError(
            f"[data_enrich_utils] Integrity check FAILED — non-callable exports: {non_callable}."
        )

    # 签名检查：参数被删除/截断时报错
    sig_violations = []
    for name, min_args in _REQUIRED_SIGNATURES.items():
        try:
            sig = _inspect.signature(globals()[name])
            # 计算必需的位置参数（POSITIONAL_ONLY + POSITIONAL_OR_KEYWORD 且无默认值）
            required_count = sum(
                1 for p in sig.parameters.values()
                if p.kind in (_inspect.Parameter.POSITIONAL_ONLY, _inspect.Parameter.POSITIONAL_OR_KEYWORD)
                and p.default is _inspect.Parameter.empty
            )
            if required_count < min_args:
                sig_violations.append(
                    f"{name}(requires {min_args}, got {required_count})"
                )
        except (TypeError, ValueError) as e:
            sig_violations.append(f"{name}(signature error: {e})")

    if sig_violations:
        raise ImportError(
            f"[data_enrich_utils] Integrity check FAILED — signature violations: {sig_violations}. "
            f"File may have been corrupted by an external tool/linter."
        )


_self_integrity_check()
