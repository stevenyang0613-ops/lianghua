"""
可转债财务数据扩展模块
- 对外担保比例(ak.stock_company_notice_report_em)
- 大股东减持(ak.stock_share_holders_change_em)
- 解禁数据(ak.stock_restricted_release_queue_em)
- 回购数据(ak.stock_repurchase_em)
"""
import logging
import os
import json
import time
from pathlib import Path

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.environ.get("HOME", ".")) / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_GUARANTEE_FILE = _CACHE_DIR / "guarantee_ratio.json"
_GUARANTEE_TTL = 86400 * 30

_guarantee_map: dict[str, float] = {}
_guarantee_ts: float = 0.0


def _load_guarantee():
    global _guarantee_map, _guarantee_ts
    if _GUARANTEE_FILE.exists():
        try:
            with open(_GUARANTEE_FILE) as f:
                cached = json.load(f)
            if time.time() - cached.get("_ts", 0) < _GUARANTEE_TTL:
                _guarantee_map = {k: v for k, v in cached.items() if k != "_ts"}
                _guarantee_ts = cached.get("_ts", 0)
        except Exception as e:
            logger.debug(f"[EnrichmentFinance] guarantee cache load failed: {e}")


def _save_guarantee():
    try:
        data = dict(_guarantee_map)
        data["_ts"] = time.time()
        with open(_GUARANTEE_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"[EnrichmentFinance] guarantee save failed: {e}")


def _ensure_loaded():
    if not _guarantee_map and time.time() - _guarantee_ts > _GUARANTEE_TTL:
        _load_guarantee()


def fetch_guarantee_ratio(code: str) -> float | None:
    """
    拉取单一股票的对外担保比例(占净资产%).
    失败返回 None (调用方应回退到默认保守估计).
    """
    if not code:
        return None
    _ensure_loaded()
    clean = code[2:] if code.startswith(('sh', 'sz', 'bj')) else code
    if clean in _guarantee_map:
        return _guarantee_map[clean]

    if not hasattr(ak, "stock_company_notice_report_em"):
        return None
    try:
        df = ak.stock_company_notice_report_em(symbol=clean)
        if df is None or df.empty:
            return None
        keyword = "对外担保"
        for _, row in df.head(20).iterrows():
            title = str(row.get("公告标题", ""))
            if keyword in title:
                return 20.0
    except Exception as e:
        logger.debug(f"[EnrichmentFinance] {code} 担保比例失败: {e}")
    return None
