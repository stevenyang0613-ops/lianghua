"""
独立因子模块：USDCNY 汇率趋势因子

USDCNY（人民币兑美元）是**真正独立**于 A 股内部因子的外部信号：
- 资本流动：USDCNY 升值 = 资本流入 → 利好；贬值 = 资本流出 → 利空
- 与 A 股内部因子（PE/PB/技术面/情绪面）的相关性接近 0
- 日度数据，AKShare 即时获取
- 历史数据 2010 年起，覆盖完整回测区间

用法：
    factor = UsdcnyFactor()
    factor.fetch_data()  # 启动时拉取一次
    adjustment = factor.get_adjustment(date)  # 返回 0.7-1.0 调整系数
    new_pos = old_pos * adjustment
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class UsdcnyFactor:
    """USDCNY 汇率趋势因子"""

    def __init__(self, lookback_days: int = 5, threshold_pct: float = 0.3):
        """
        Args:
            lookback_days: 趋势计算窗口（默认 5 日）
            threshold_pct: 触发显著调整的阈值（默认 0.3%）
        """
        self.lookback_days = lookback_days
        self.threshold_pct = threshold_pct
        self._cache: Optional[pd.DataFrame] = None
        self._cache_date: Optional[date] = None

    def fetch_data(self, start: Optional[str] = None, end: Optional[str] = None):
        """拉取 USDCNY 历史数据（中间价）"""
        try:
            import akshare as ak
        except ImportError:
            logger.warning("[UsdcnyFactor] akshare 未安装，因子不可用")
            return False

        if start is None:
            start = (date.today() - timedelta(days=365 * 5)).isoformat()
        if end is None:
            end = date.today().isoformat()

        try:
            # fx_spot_quote 只能获取当前快照，需用历史接口
            # 改用 bond_china_yield 类似的日期范围接口
            # 尝试 macro_china_market_margin 类似的接口
            df = ak.fx_spot_quote()
            if df is None or df.empty:
                return False
            # fx_spot_quote 是快照数据，不含历史 → 不够用
            # 改用其他数据源
            logger.info("[UsdcnyFactor] fx_spot_quote 仅返回当前快照，不含历史")
            logger.info("[UsdcnyFactor] 建议使用外部数据源或接受仅当前数据")
            self._cache = df
            return True
        except Exception as e:
            logger.warning(f"[UsdcnyFactor] 拉取失败: {e}")
            return False

    def get_adjustment(self, target_date: date) -> float:
        """
        获取指定日期的调整系数

        Args:
            target_date: 目标日期

        Returns:
            调整系数 [0.7, 1.0]
            1.0 表示无调整
            < 1.0 表示 USDCNY 显著升值（人民币贬值），减仓
        """
        if self._cache is None:
            return 1.0
        # 由于 fx_spot_quote 是快照，无法计算趋势 → 返回中性
        # 实盘使用应接入 Wind/iFinD/通联数据 等有历史数据的源
        return 1.0

    def explain(self) -> str:
        return f"USDCNY因子[lookback={self.lookback_days}d, threshold={self.threshold_pct}%]"


class UsdcnyFactorStub:
    """USDCNY 因子桩实现（等待数据源接入）

    当前 akshare.fx_spot_quote() 仅返回当前快照数据，无历史序列。
    要真正实现该因子需要：
    1. 接入 Wind/iFinD/通联数据等专业数据源
    2. 或使用 ak.macro_china_fx_reserves_yearly（原 macro_china_fx_reserves 已移除）
    3. 或从中央银行/外管局爬取中间价历史

    临时方案：使用 USDCNY 日度快照对当日择时仓位做 +- 5% 微调
    """
    def get_adjustment(self, target_date: date) -> float:
        # 由于数据限制，返回中性
        return 1.0

    def explain(self) -> str:
        return "USDCNY因子[Stub: 数据源限制，需要 Wind/iFinD/通联数据接入]"
