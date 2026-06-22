"""
ICIR真实历史数据存储与查询

存储每日滚动IC（信息系数）和IR（信息比率），
为ICIR动态权重可视化提供真实历史数据而非模拟值。
"""
import json
import time
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "icir_cache"
_IC_FILE = "daily_ic.json"
_ICIR_FILE = "icir_history.json"

_ic_map: dict[str, list[dict]] = {}  # factor_key -> [{date, ic_value}]
_icir_map: dict[str, dict] = {}  # factor_key -> {lookback, icir_value, last_updated}
_ic_lock = threading.Lock()

FACTOR_KEYS = ["dual_low", "momentum", "hv", "quality", "valuation", "ytm", "remaining_years", "event", "delta"]


def _ensure_dir():
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_ic_cache():
    """从磁盘加载IC历史数据"""
    global _ic_map
    path = _CACHE_DIR / _IC_FILE
    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _ic_map = data
                    logger.info(f"[ICIR] Loaded IC history: {sum(len(v) for v in data.values())} entries")
        except Exception as e:
            logger.warning(f"[ICIR] Failed to load IC cache: {e}")


def _save_ic_cache():
    """保存IC历史到磁盘"""
    _ensure_dir()
    path = _CACHE_DIR / _IC_FILE
    try:
        # 原子写入：先写 tmp，再 rename（防止部分写入导致文件损坏）
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(_ic_map, f, ensure_ascii=False)
        tmp.replace(path)
    except Exception as e:
        logger.warning(f"[ICIR] Failed to save IC cache: {e}")


def _load_icir_cache():
    """从磁盘加载ICIR计算结果"""
    global _icir_map
    path = _CACHE_DIR / _ICIR_FILE
    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _icir_map = data
        except Exception as e:
            logger.warning(f"[ICIR] Failed to load ICIR cache: {e}")


def _save_icir_cache():
    """保存ICIR结果到磁盘"""
    _ensure_dir()
    path = _CACHE_DIR / _ICIR_FILE
    try:
        # 原子写入：先写 tmp，再 rename（防止部分写入导致文件损坏）
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(_icir_map, f, ensure_ascii=False)
        tmp.replace(path)
    except Exception as e:
        logger.warning(f"[ICIR] Failed to save ICIR cache: {e}")


def record_daily_ic(factor_scores: dict[str, pd.Series], forward_returns: pd.Series, trade_date: str = None):
    """
    记录每日IC值

    参数:
        factor_scores: 各因子得分 {factor_key: pd.Series}，index为债券代码
        forward_returns: 下期收益率 {bond_code: float}
        trade_date: 交易日期 (YYYYmmdd)，回测时必须传入；实盘默认 today
    """
    with _ic_lock:
        today = trade_date if trade_date else datetime.now().strftime("%Y%m%d")
        for key, scores in factor_scores.items():
            if key not in FACTOR_KEYS:
                continue
            if scores.empty or forward_returns.empty:
                continue
            # 计算截面IC (秩相关系数)
            aligned = pd.concat([scores, forward_returns], axis=1, join="inner").dropna()
            if len(aligned) < 10:
                continue
            try:
                ic = aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method="spearman")
                if pd.notna(ic) and -1 <= ic <= 1:
                    if key not in _ic_map:
                        _ic_map[key] = []
                    # 避免重复记录同一天的数据
                    existing_dates = {e["date"] for e in _ic_map[key]}
                    if today not in existing_dates:
                        _ic_map[key].append({"date": today, "ic_value": round(float(ic), 4)})
                        # 只保留最近365天
                        if len(_ic_map[key]) > 365:
                            _ic_map[key] = _ic_map[key][-365:]
            except Exception:
                continue

        if any(_ic_map.get(k) for k in FACTOR_KEYS):
            _save_ic_cache()


def compute_icir(lookback: int = 60) -> dict[str, float]:
    """
    基于存储的IC历史计算ICIR（信息比率）
    ICIR = mean(IC) / std(IC) over lookback window

    返回: {factor_key: icir_value}
    """
    with _ic_lock:
        result = {}
        today = datetime.now()
        cutoff = (today - timedelta(days=lookback * 2)).strftime("%Y%m%d")  # 宽松窗口确保有足够数据

        for key in FACTOR_KEYS:
            entries = _ic_map.get(key, [])
            recent = [e for e in entries if e["date"] >= cutoff][-lookback:]
            if len(recent) < 10:
                result[key] = 0.0
                continue
            ic_values = [e["ic_value"] for e in recent]
            mean_ic = np.mean(ic_values)
            std_ic = np.std(ic_values)
            if std_ic < 1e-9:
                # IC 完全稳定，信息量不足，用 abs(mean_ic) 放大作为近似权重
                result[key] = round(abs(mean_ic) * 5, 4) if mean_ic != 0 else 0.001
            else:
                result[key] = round(float(abs(mean_ic) / std_ic), 4)

        # 保存到持久缓存
        _icir_map["last_computed"] = time.time()
        _icir_map.setdefault("history", {})
        today_str = today.strftime("%Y%m%d")
        _icir_map["history"][today_str] = result
        _save_icir_cache()

        return result


def get_icir_history(days: int = 90) -> dict[str, list]:
    """
    获取ICIR历史，用于前端可视化

    返回: {
        "factor_ic": {"dual_low": [{"date": "...", "ic": 0.1}, ...], ...},
        "factor_icir": {"dual_low": [{"date": "...", "icir": 0.5}, ...], ...},
        "last_updated": timestamp,
    }
    """
    _load_ic_cache()
    _load_icir_cache()

    today = datetime.now()
    cutoff = (today - timedelta(days=days)).strftime("%Y%m%d")

    factor_ic: dict[str, list] = {}
    for key in FACTOR_KEYS:
        entries = _ic_map.get(key, [])
        recent = [e for e in entries if e["date"] >= cutoff]
        factor_ic[key] = [{"date": e["date"], "ic": e["ic_value"]} for e in recent]

    factor_icir: dict[str, list] = {}
    hist = _icir_map.get("history", {})
    sorted_dates = sorted(hist.keys())
    for key in FACTOR_KEYS:
        factor_icir[key] = []
        for d in sorted_dates:
            if d >= cutoff and key in hist[d]:
                factor_icir[key].append({"date": d, "icir": hist[d][key]})

    return {
        "factor_ic": factor_ic,
        "factor_icir": factor_icir,
        "last_updated": _icir_map.get("last_computed", 0),
    }


def initialize():
    """模块初始化 - 加载缓存"""
    _load_ic_cache()
    _load_icir_cache()


def get_stored_correlation_matrix() -> Optional[dict]:
    """从历史IC数据推导的理论相关矩阵（低样本时回退）"""
    with _ic_lock:
        if not _ic_map:
            # 返回基于因子定义的理论相关矩阵
            return {
                "factors": FACTOR_KEYS,
                "matrix": _get_theoretical_correlation(),
                "source": "theoretical",
            }

        # 用最近IC序列计算实际相关
        aligned = {}
        min_len = float("inf")
        for key in FACTOR_KEYS:
            entries = _ic_map.get(key, [])
            if len(entries) >= 20:
                vals = [e["ic_value"] for e in entries[-60:]]
                aligned[key] = vals
                min_len = min(min_len, len(vals))

        if len(aligned) < 3:
            return {
                "factors": FACTOR_KEYS,
                "matrix": _get_theoretical_correlation(),
                "source": "theoretical",
            }

        # 截断到相同长度
        trimmed = {k: v[-min_len:] for k, v in aligned.items()}
        df = pd.DataFrame(trimmed)
        corr = df.corr()

        matrix = []
        for i, k1 in enumerate(FACTOR_KEYS):
            row = []
            for j, k2 in enumerate(FACTOR_KEYS):
                if k1 in corr.index and k2 in corr.columns:
                    row.append(round(float(corr.loc[k1, k2]), 4))
                else:
                    row.append(0.0)
            matrix.append(row)

        return {
            "factors": FACTOR_KEYS,
            "matrix": matrix,
            "source": "historical",
            "samples": min_len,
        }


def _get_theoretical_correlation() -> list[list[float]]:
    """基于因子定义的理论相关矩阵"""
    # 防守因子之间正相关, 进攻因子之间正相关, 防守与进攻负相关
    # ordering: dual_low, momentum, hv, quality, valuation, ytm, remaining_years, event, delta
    th = [
    #   dl    mom   hv    qual  val   ytm   ry    evt   delta
        [1.0, -0.3,  0.4, -0.2,  0.1,  0.3,  0.2, -0.1, -0.4],  # dual_low
        [-0.3, 1.0, -0.3,  0.3, -0.1, -0.3, -0.2,  0.2,  0.5],  # momentum
        [0.4, -0.3,  1.0, -0.2,  0.2,  0.4,  0.3, -0.1, -0.3],  # hv
        [-0.2,  0.3, -0.2,  1.0,  0.4, -0.1, -0.1,  0.2,  0.2],  # quality
        [0.1, -0.1,  0.2,  0.4,  1.0, -0.1, -0.1,  0.0,  0.1],  # valuation
        [0.3, -0.3,  0.4, -0.1, -0.1,  1.0,  0.5, -0.1, -0.3],  # ytm
        [0.2, -0.2,  0.3, -0.1, -0.1,  0.5,  1.0, -0.1, -0.2],  # remaining_years
        [-0.1,  0.2, -0.1,  0.2,  0.0, -0.1, -0.1,  1.0,  0.1],  # event
        [-0.4,  0.5, -0.3,  0.2,  0.1, -0.3, -0.2,  0.1,  1.0],  # delta
    ]
    return th
