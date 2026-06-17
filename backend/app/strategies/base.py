from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

from app.models.backtest import StrategyParam


class Strategy(ABC):
    """策略基类 - 所有策略继承此类"""

    name: str = "BaseStrategy"
    description: str = ""
    params: list[StrategyParam] = []

    def __init__(self, **kwargs):
        self._params = {}
        self._param_type_map: dict[str, str] = {}
        for p in self.params:
            self._params[p.name] = kwargs.get(p.name, p.default)
            self._param_type_map[p.name] = p.type
        self._prev_selected: set[str] = set()

    def get_param(self, name: str):
        val = self._params.get(name)
        ptype = self._param_type_map.get(name)
        if val is None:
            # 尝试从 param 定义获取默认值
            for p in self.params:
                if p.name == name:
                    val = p.default
                    self._params[name] = val
                    break
            if val is None:
                return None
        if ptype == "int":
            try:
                return int(val)
            except (TypeError, ValueError):
                return 0
        if ptype == "float":
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0
        return val

    @abstractmethod
    def on_init(self, data: pd.DataFrame) -> None:
        """策略初始化，计算指标"""
        ...

    @abstractmethod
    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        """
        在每个时间点生成交易信号

        Args:
            data: 当日行情数据（仅包含当前交易日的行），无需再按日期过滤
            idx: 当前交易日索引（从0开始）

        Returns: [{"code": str, "action": "buy"|"sell", "price": float, "reason": str}]
        """
        ...

    def on_destroy(self):
        """策略清理"""
        pass
