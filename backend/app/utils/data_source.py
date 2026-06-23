"""
数据源标签 — 统一标记后端返回数据的真实来源

约定：
- "real":      直接来自交易所/官方 API（AKShare/TDX/Sina/THS/BaoStock）
- "estimated": 模型基于其他字段估算（如 IV 估算）
- "fallback":  上游数据缺失时由后端兜底生成的值
- "mock":      仅用于演示的合成数据（如 StrategyReplay 演示页）
- "missing":   数据缺失（NaN/空值）
"""
from enum import Enum
from typing import Any, Dict


class DataSource(str, Enum):
    """数据来源标签"""
    REAL = "real"
    ESTIMATED = "estimated"
    FALLBACK = "fallback"
    MOCK = "mock"
    MISSING = "missing"


def annotate_with_source(value: Any, source: DataSource) -> Dict[str, Any]:
    """把数据值包装为带 _source 标记的 dict

    用途：API 返回嵌套字段时，前端可读取 _source 字段判断真实性。
    """
    if isinstance(value, dict):
        out = dict(value)
        out["_source"] = source.value
        return out
    return {"value": value, "_source": source.value}


def is_real_source(source: str) -> bool:
    """判断数据源是否为真实数据"""
    return source == DataSource.REAL.value
