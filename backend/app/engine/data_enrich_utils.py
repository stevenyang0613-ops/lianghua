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


def save_cache(path, data: dict) -> None:
    """Atomically save data to a JSON cache file with _ts timestamp."""
    if not data or not isinstance(data, dict):
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if "_ts" not in data:
            data = {**data, "_ts": time.time()}
        clean = {}
        for k, v in data.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                continue
            elif isinstance(v, dict):
                inner = {}
                for ik, iv in v.items():
                    if isinstance(iv, float) and (math.isnan(iv) or math.isinf(iv)):
                        continue
                    inner[ik] = iv
                v = inner
            clean[k] = v
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
