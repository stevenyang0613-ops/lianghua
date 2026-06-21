"""Shared utility functions for data_enrich.py and data_enrich_runner.py."""

import json
import logging
import math
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


def load_cache(path) -> Optional[dict]:
    """Load a JSON cache file. Returns None if not found or corrupted."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
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


def save_cache(path, data: dict) -> None:
    """Atomically save data to a JSON cache file with _ts timestamp.

    递归清理所有嵌套结构（dict/list/tuple）中的 NaN/Inf，
    防止 json.dump 抛出 "Out of range float values are not JSON compliant"。

    Bug5/Data5 修复：无论 data 中是否已有 _ts，都强制刷新为当前时间，
    保证 cache_status() 用 _ts 判断新鲜度时永远反映"文件最近写入时间"。
    """
    if not data or not isinstance(data, dict):
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 始终刷新 _ts（即使已存在也覆盖）— 见 docstring
        data = {**data, "_ts": time.time()}
        clean = _sanitize_for_json(data)
        # 移除 _DROP 哨兵对象（极少见：_ts 本身是 NaN 等极端情况）
        if isinstance(clean, dict) and _DROP in clean.values():
            clean = {k: v for k, v in clean.items() if v is not _DROP}
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(p)
    except Exception as e:
        logger.warning(f"[DataEnrich] Cache save error: {path} -> {e}")


def fresh(ttl: int, data) -> bool:
    """Check if cached data is still fresh within TTL (seconds)."""
    if data is None:
        return False
    ts = data.get("_ts", 0) if isinstance(data, dict) else 0
    return time.time() - ts < ttl


def safe_float(v, default=None) -> Optional[float]:
    """Safely convert any value to float; returns default for None/NaN/Inf/empty."""
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return default
    try:
        fv = float(v)
        if fv != fv:
            return default
        return fv
    except (ValueError, TypeError):
        return default


def safe_int(v, default=None) -> Optional[int]:
    """Safely convert any value to int; returns default for None/invalid."""
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
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



# ── 完整性保护：导入时自检 ──
# 防 AGENTS.md Rule 关于 linter/外部工具损坏文件的回归：
# 当文件被截断/重复时，所有预期导出都必须存在，否则立即报错。

_REQUIRED_EXPORTS = frozenset({
    "load_cache", "save_cache", "fresh",
    "safe_float", "safe_int", "safe_str",
})


# 函数签名要求：每个导出函数必须至少有指定数量的位置参数。
# 防止 linter 将 `safe_float(v, default=None)` 改为 `safe_float()` 而不报错。
_REQUIRED_SIGNATURES: dict[str, int] = {
    "load_cache": 1,   # (path)
    "save_cache": 2,   # (path, data)
    "fresh": 1,        # (ttl, ...) — 至少 1 个位置参数
    "safe_float": 1,   # (v, ...) — 至少 1 个位置参数
    "safe_int": 1,     # (v, ...) — 至少 1 个位置参数
    "safe_str": 1,     # (v) — 至少 1 个位置参数
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
