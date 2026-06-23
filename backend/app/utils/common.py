"""Common utilities for the lianghua backend."""
import math
from typing import Any, Optional


def is_missing(val: Any) -> bool:
    """
    Check if a value represents missing/invalid data.

    Returns True for:
    - None
    - float('nan') / math.nan
    - Empty string ""
    - Empty list []

    Returns False for:
    - 0, 0.0 (legitimate zero values)
    - False (legitimate boolean)
    - Non-empty strings, lists, dicts
    """
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str) and val == "":
        return True
    if isinstance(val, list) and len(val) == 0:
        return True
    return False


def safe_float(val: Any, default: float = 0.0) -> float:
    """
    Safely convert a value to float, returning default for missing/invalid data.

    Handles:
    - None → default
    - float('nan') → default
    - Empty string "" → default
    - Non-numeric strings → default
    """
    if is_missing(val):
        return default
    if isinstance(val, (int, float)):
        if math.isnan(val):
            return default
        return float(val)
    try:
        f = float(val)
        if math.isnan(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def safe_int(val: Any, default: int = 0) -> int:
    """
    Safely convert a value to int, returning default for missing/invalid data.
    """
    if is_missing(val):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_divide(numerator: Optional[float], denominator: Optional[float], default: float = 0.0) -> float:
    """
    Safely divide two numbers, returning default if either is missing or denominator is zero.
    """
    if is_missing(numerator) or is_missing(denominator):
        return default
    if denominator == 0:
        return default
    return numerator / denominator
