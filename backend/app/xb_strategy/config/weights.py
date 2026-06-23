"""不同市场环境下的因子权重方案

V3 简化版市场环境（基于月涨跌幅 > 5%）：
- BULL: 指数月涨 > 5%
- RANGE: 月波动 ±3%
- BEAR: 指数月跌 > 5%

V4 多维度综合择时模型（enhanced_timing_model.py）使用更细致的 5 档分类：
STRONG_BULL/BULL/RANGE/BEAR/STRONG_BEAR，基于 SSD/Bollinger/标准差。
当 V4 模型激活时，通过 map_v4_to_v3_regime() 将 5 档映射到此 3 档。
"""
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class MarketRegime(str, Enum):
    """市场环境（V3 简化版）"""
    BULL = "bull"        # 牛市：指数月涨 > 5%
    RANGE = "range"      # 震荡市：月波动 ±3%
    BEAR = "bear"        # 熊市：指数月跌 > 5%


@dataclass
class WeightScheme:
    """权重方案"""
    # 动量+技术 vs 基本面+波动率
    momentum_tech_weight: float
    fundamental_vol_weight: float
    # 正股 vs 转债
    stock_weight: float
    cb_weight: float
    # 高频 vs 中低频仓位比
    hft_ratio: float
    mlf_ratio: float

    # 正股子维度权重调整
    w_short_momentum: float
    w_sector_sentiment: float
    w_technical: float
    w_chip_structure: float
    w_volatility: float
    w_news_factor: float
    w_fundamentals: float

    # 转债子维度权重调整
    w_valuation: float
    w_clause_value: float
    w_liquidity: float
    w_credit: float


# 三种市场环境下的权重方案
WEIGHT_SCHEMES: Dict[MarketRegime, WeightScheme] = {
    MarketRegime.BULL: WeightScheme(
        # 动量+技术占主导
        momentum_tech_weight=0.75,
        fundamental_vol_weight=0.25,
        # 正股权重略高
        stock_weight=0.65,
        cb_weight=0.35,
        # 高频仓位较高
        hft_ratio=0.80,  # 4:1
        mlf_ratio=0.20,
        # 正股子维度 - 动量和技术面权重高
        w_short_momentum=0.35,
        w_sector_sentiment=0.20,
        w_technical=0.20,
        w_chip_structure=0.10,
        w_volatility=0.08,
        w_news_factor=0.05,
        w_fundamentals=0.02,
        # 转债子维度 - 估值和流动性优先
        w_valuation=0.40,
        w_clause_value=0.20,
        w_liquidity=0.25,
        w_credit=0.15,
    ),
    MarketRegime.RANGE: WeightScheme(
        # 相对均衡
        momentum_tech_weight=0.60,
        fundamental_vol_weight=0.40,
        # 略偏向转债属性
        stock_weight=0.55,
        cb_weight=0.45,
        # 高频中等仓位
        hft_ratio=0.714,  # 2.5:1
        mlf_ratio=0.286,
        # 正股子维度 - 相对均衡
        w_short_momentum=0.30,
        w_sector_sentiment=0.18,
        w_technical=0.18,
        w_chip_structure=0.12,
        w_volatility=0.12,
        w_news_factor=0.07,
        w_fundamentals=0.03,
        # 转债子维度 - 均衡
        w_valuation=0.38,
        w_clause_value=0.24,
        w_liquidity=0.20,
        w_credit=0.18,
    ),
    MarketRegime.BEAR: WeightScheme(
        # 基本面和波动率占主导
        momentum_tech_weight=0.45,
        fundamental_vol_weight=0.55,
        # 正股和转债权重均衡
        stock_weight=0.50,
        cb_weight=0.50,
        # 高频低仓位
        hft_ratio=0.50,  # 1:1
        mlf_ratio=0.50,
        # 正股子维度 - 波动率和基本面权重高
        w_short_momentum=0.22,
        w_sector_sentiment=0.15,
        w_technical=0.15,
        w_chip_structure=0.15,
        w_volatility=0.18,
        w_news_factor=0.08,
        w_fundamentals=0.07,
        # 转债子维度 - 信用和条款价值优先
        w_valuation=0.30,
        w_clause_value=0.30,
        w_liquidity=0.15,
        w_credit=0.25,
    ),
}


def get_weight_scheme(regime: MarketRegime) -> WeightScheme:
    """获取指定市场环境的权重方案"""
    return WEIGHT_SCHEMES.get(regime, WEIGHT_SCHEMES[MarketRegime.RANGE])


def detect_market_regime(
    index_month_change: float,
    index_volatility: float = 0.0
) -> MarketRegime:
    """检测市场环境（V3 简化版：仅基于月涨跌幅）

    Args:
        index_month_change: 指数月涨跌幅(%)
        index_volatility: 指数波动率(可选)

    Returns:
        MarketRegime: 市场环境
    """
    if index_month_change > 5.0:
        return MarketRegime.BULL
    elif index_month_change < -5.0:
        return MarketRegime.BEAR
    else:
        return MarketRegime.RANGE


def map_v4_to_v3_regime(v4_regime: Optional[str]) -> MarketRegime:
    """将 V4 模型的 5 档市场环境映射到 V3 的 3 档

    V4（EnhancedTimingModel）:
      STRONG_BULL（深度超买）→ V3 BULL
      BULL（轻度超买）       → V3 BULL
      RANGE                  → V3 RANGE
      BEAR（轻度超卖）       → V3 BEAR
      STRONG_BEAR（深度超卖）→ V3 BEAR

    当 V4 模型激活时，旧的权重方案（WEIGHT_SCHEMES）可以复用此映射
    来选择合适的因子权重，保持与 V4 择时信号一致的方向。

    Args:
        v4_regime: V4 模型输出的市场环境字符串（如 "STRONG_BEAR"），
                   或 None（表示未检测到）

    Returns:
        MarketRegime: V3 简化的市场环境
    """
    if v4_regime is None:
        return MarketRegime.RANGE

    v4_upper = v4_regime.upper()
    if v4_upper in ('STRONG_BULL', 'BULL'):
        return MarketRegime.BULL
    elif v4_upper in ('STRONG_BEAR', 'BEAR'):
        return MarketRegime.BEAR
    else:
        return MarketRegime.RANGE
