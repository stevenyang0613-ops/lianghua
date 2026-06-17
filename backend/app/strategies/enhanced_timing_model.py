"""
综合多维度择时模型 V4.0

从估值面、基本面、筹码面、资金面、流动性面、技术面、情绪面、消息面、宏观面 9 大类
40+ 子因子构建综合择时信号。

核心改进（相对 V3 四因子模型，已弃用）：
1. 因子从 4 个扩充到 8 个大类 + 30+ 子因子
2. 连续型评分函数替代阶梯式评分
3. 多时间框架确认（日/周/月）
4. 基于市场环境的动态权重调整
5. 交叉验证信号消除假信号
6. 信号质量/置信度评分
7. 集成学习融合（加权/排序/投票）
8. 自适应参数更新

输出：
- 综合择时得分 0-100
- 仓位建议 0%-100%
- 每大类因子详细得分
- 风险预警信号
- 信号质量评估
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Tuple, Any
from enum import Enum
import numpy as np
import pandas as pd
import logging
import math
from collections import deque

logger = logging.getLogger(__name__)


# ==================== 枚举定义 ====================

class MarketRegime(str, Enum):
    """市场环境"""
    STRONG_BULL = "strong_bull"      # 强势牛市（月涨 > 10%）
    BULL = "bull"                     # 牛市（月涨 5%-10%）
    RANGE = "range"                   # 震荡（月涨 ±5%）
    BEAR = "bear"                     # 熊市（月跌 5%-10%）
    STRONG_BEAR = "strong_bear"       # 强势熊市（月跌 > 10%）


class SignalQuality(str, Enum):
    """信号质量"""
    EXCELLENT = "excellent"           # 极高置信度
    GOOD = "good"                     # 高置信度
    FAIR = "fair"                     # 中等置信度
    WEAK = "weak"                     # 低置信度
    UNRELIABLE = "unreliable"         # 不可靠


# ==================== 数据类 ====================

@dataclass
class FactorScore:
    """单因子得分"""
    name: str                         # 因子名称
    score: float                      # 得分 0-100
    weight: float                     # 权重
    category: str                     # 所属大类
    raw_value: Any = None             # 原始值
    description: str = ""             # 描述
    signal: str = "neutral"           # 信号方向: bullish/bearish/neutral
    confidence: float = 1.0           # 数据可靠度 0-1
    percentile: Optional[float] = None  # 历史分位数


@dataclass
class CategoryScore:
    """大类得分"""
    name: str                         # 大类名称（估值面/基本面/...）
    score: float                      # 加权得分 0-100
    weight: float                     # 大类权重
    sub_factors: List[FactorScore] = field(default_factory=list)
    description: str = ""
    regime_bias: float = 0.0          # 当前市场环境下该大类的偏向调整


@dataclass
class CrossValidationSignal:
    """交叉验证信号"""
    name: str
    signal: str                       # bullish/bearish/neutral
    strength: float                   # 0-1
    description: str
    confirming_factors: List[str] = field(default_factory=list)
    conflicting_factors: List[str] = field(default_factory=list)


@dataclass
class EnhancedTimingSignal:
    """增强择时信号"""
    date: date
    total_score: float                # 综合得分 0-100
    position_ratio: float             # 建议仓位 0-1
    market_regime: MarketRegime       # 市场环境
    
    # 各大类得分
    category_scores: Dict[str, CategoryScore] = field(default_factory=dict)
    
    # 交叉验证
    cross_validations: List[CrossValidationSignal] = field(default_factory=list)
    consensus_score: float = 0.0      # 一致性评分 0-100
    
    # 信号质量
    quality: SignalQuality = SignalQuality.FAIR
    confidence: float = 0.5           # 综合置信度 0-1
    
    # 预警
    risk_alerts: List[str] = field(default_factory=list)
    hedge_recommended: bool = False
    
    # 动态权重
    actual_weights: Dict[str, float] = field(default_factory=dict)
    
    # 时间
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if isinstance(self.date, date) else str(self.date),
            "totalScore": round(self.total_score, 2),
            "positionRatio": round(self.position_ratio, 4),
            "marketRegime": self.market_regime.value,
            "categoryScores": {
                k: {
                    "name": v.name,
                    "score": round(v.score, 2),
                    "weight": round(v.weight, 4),
                    "description": v.description,
                    "subFactors": [
                        {
                            "name": sf.name,
                            "score": round(sf.score, 2),
                            "weight": round(sf.weight, 4),
                            "signal": sf.signal,
                            "description": sf.description,
                            "confidence": round(sf.confidence, 4),
                        }
                        for sf in v.sub_factors
                    ],
                }
                for k, v in self.category_scores.items()
            },
            "consensusScore": round(self.consensus_score, 2),
            "quality": self.quality.value,
            "confidence": round(self.confidence, 4),
            "riskAlerts": self.risk_alerts,
            "hedgeRecommended": self.hedge_recommended,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class EnhancedMarketData:
    """扩展市场数据（兼容旧版 MarketData + 新增字段）"""
    date: date
    
    # === 转债市场 ===
    cb_median_premium: float = 0.0       # 转股溢价率中位数(%)
    cb_avg_premium: float = 0.0          # 转股溢价率均值(%)
    cb_median_price: float = 0.0         # 转债价格中位数
    cb_avg_daily_amount: float = 0.0     # 转债日均成交额(亿)
    cb_count: int = 0                    # 转债数量
    cb_ytm_median: float = 0.0           # 纯债YTM中位数(%)
    cb_index_change: float = 0.0         # 转债指数涨跌幅(%)
    cb_index_current: float = 0.0        # 转债指数当前值
    cb_index_ma20: float = 0.0           # 转债指数20日均线
    cb_index_ma60: float = 0.0           # 转债指数60日均线
    cb_below_par_count: int = 0          # 低于面值的转债数
    
    # === 正股市场 ===
    stock_index_change: float = 0.0      # 沪深300涨跌幅(%)
    stock_index_current: float = 0.0     # 沪深300当前值
    stock_index_ma20: float = 0.0        # 沪深300 20日均线
    stock_index_ma60: float = 0.0        # 沪深300 60日均线
    stock_pe_median: float = 0.0         # 全市场PE中位数
    stock_pb_median: float = 0.0         # 全市场PB中位数
    stock_pe_percentile: float = 0.0     # PE历史分位数(%)
    stock_pb_percentile: float = 0.0     # PB历史分位数(%)
    
    # === 技术指标 ===
    ma_arrangement: str = "neutral"      # MA排列: bullish/bearish/neutral
    macd_signal: str = "neutral"         # MACD信号
    rsi_14: float = 0.0                  # RSI(14)
    bollinger_position: float = 0.0      # 布林带位置 0-1
    volume_ratio: float = 0.0            # 量比
    
    # === 筹码/资金 ===
    main_force_net_flow: float = 0.0     # 主力净流入(亿)
    margin_balance_change: float = 0.0   # 融资余额变化(亿)
    north_bound_net_flow: float = 0.0    # 北向资金净流入(亿)
    institutional_holding_change: float = 0.0  # 机构持仓变化
    
    # === 债券/流动性 ===
    treasury_10y_yield: float = 0.0      # 10年期国债收益率(%)
    treasury_2y_yield: float = 0.0       # 2年期国债收益率(%)
    shibor_overnight: float = 0.0        # Shibor隔夜(%)
    credit_spread: float = 0.0           # 信用利差(bp)
    term_spread: float = 0.0             # 期限利差(bp)
    
    # === 宏观 ===
    pmi: float = 0.0                     # PMI当月（0=无数据，50=荣枯线）
    pmi_prev: float = 0.0                # PMI上月（0=无数据）
    cpi: float = 0.0                     # CPI当月同比(%)
    ppi: float = 0.0                     # PPI当月同比(%)
    m2_growth: float = 0.0              # M2同比增速(%)
    social_financing_growth: float = 0.0  # 社融同比增速(%)
    industrial_output: float = 0.0       # 工业增加值同比(%)
    retail_sales: float = 0.0            # 社零同比(%)
    export_growth: float = 0.0           # 出口同比(%)
    gdp_growth: float = 0.0              # GDP同比增速(%)
    
    # === 情绪 ===
    advance_decline_ratio: float = 0.0   # 涨跌比
    limit_up_count: int = 0              # 涨停数
    limit_down_count: int = 0            # 跌停数
    new_high_count: int = 0              # 60日新高数
    new_low_count: int = 0               # 60日新低数
    pcr_ratio: float = 0.0               # 认沽/认购比（0=无数据）
    vix_index: float = 0.0               # 波动率指数（0=无数据）
    new_accounts: float = 0.0            # 新增开户数(万)
    margin_buy_ratio: float = 0.0        # 融资买入占比(%)
    market_turnover: float = 0.0         # 全市场换手率(%)
    
    # === 消息/政策 ===
    policy_signal_score: float = 50.0     # 政策信号评分 0-100
    event_impact_score: float = 50.0      # 事件冲击评分 0-100
    industry_cycle_score: float = 50.0    # 产业链景气评分 0-100
    earnings_surprise_ratio: float = 0.0 # 盈利超预期比例

    # === 资金/流向专用字段 ===
    industry_net_inflow_ratio: float = 50.0  # 行业净流入占比评分 0-100
    
    # === 元数据 ===
    data_completeness: float = 0.0       # 数据完整度 0-1（默认0，需计算后才设置）
    updated_at: Optional[datetime] = None


# ==================== 评分函数工具 ====================

def linear_score(value: float, low: float, high: float, invert: bool = False) -> float:
    """线性归一化评分
    
    value 在 [low, high] 之间线性映射到 [0, 100]
    invert=True 时反向（值越小分越高）
    """
    if high == low:
        return 50.0
    score = (value - low) / (high - low) * 100
    score = max(0, min(100, score))
    return 100 - score if invert else score


def sigmoid_score(value: float, center: float, steepness: float = 1.0,
                  invert: bool = False) -> float:
    """Sigmoid 平滑评分
    
    value 在 center 附近平滑过渡
    steepness 越大曲线越陡
    """
    scaled = (value - center) * steepness
    score = 100 / (1 + math.exp(-scaled))
    return 100 - score if invert else score


def percentile_score(value: float, lower: float, upper: float) -> float:
    """基于区间的分位数评分
    
    低于 lower 得 100，高于 upper 得 0，中间线性插值
    """
    if value <= lower:
        return 100.0
    if value >= upper:
        return 0.0
    return 100 * (upper - value) / (upper - lower)


def step_score(value: float, thresholds: List[Tuple[float, float]]) -> float:
    """阶梯评分
    
    thresholds: [(threshold, score), ...] 按 threshold 升序排列
    第一个匹配的区间返回对应分数
    """
    for threshold, score in sorted(thresholds, key=lambda x: x[0], reverse=True):
        if value >= threshold:
            return score
    return 0.0


def zscore_to_percentile(zscore: float) -> float:
    """Z-score 转百分位数"""
    return (0.5 * (1 + math.erf(zscore / math.sqrt(2)))) * 100


def safe_score(value: float, score_fn, neutral: float = 50.0, has_data: bool = True) -> float:
    """当数据缺失或为0时返回中性分

    Args:
        value: 原始数据值
        score_fn: 评分函数（如 linear_score, sigmoid_score）
        neutral: 中性分数（默认50）
        has_data: 数据是否实际有效（外部可强制指定）

    Examples:
        safe_score(0, lambda v: linear_score(v, 10, 50, invert=True))  # 返回 50
        safe_score(25, lambda v: linear_score(v, 10, 50, invert=True))  # 调用评分函数
    """
    if not has_data or value == 0 or math.isnan(value):
        return neutral
    return score_fn(value)


# ==================== 主模型 ====================

class EnhancedTimingModel:
    """综合多维度择时模型 V4.0"""
    
    # ========== 默认大类权重（震荡市） ==========
    DEFAULT_CATEGORY_WEIGHTS = {
        'valuation': 0.14,       # 估值面
        'fundamental': 0.10,     # 基本面
        'chip': 0.08,            # 筹码面
        'capital_flow': 0.12,    # 资金面（成交额+净流入流出）
        'liquidity': 0.11,       # 流动性面（利率+货币）
        'technical': 0.14,       # 技术面
        'sentiment': 0.10,       # 情绪面
        'news': 0.07,            # 消息面
        'macro': 0.14,           # 宏观面
    }
    
    # ========== 各市场环境下的大类权重动态调整 ==========
    REGIME_WEIGHT_ADJUSTMENTS = {
        MarketRegime.STRONG_BULL: {
            'valuation': -0.02, 'fundamental': -0.01, 'chip': 0.02,
            'capital_flow': 0.01, 'liquidity': -0.01, 'technical': 0.03,
            'sentiment': 0.02, 'news': -0.01, 'macro': -0.03,
        },
        MarketRegime.BULL: {
            'valuation': -0.01, 'fundamental': 0.00, 'chip': 0.01,
            'capital_flow': 0.00, 'liquidity': 0.00, 'technical': 0.02,
            'sentiment': 0.01, 'news': -0.01, 'macro': -0.02,
        },
        MarketRegime.RANGE: {
            # 默认权重不变
        },
        MarketRegime.BEAR: {
            'valuation': 0.02, 'fundamental': 0.02, 'chip': -0.01,
            'capital_flow': 0.01, 'liquidity': 0.02, 'technical': -0.02,
            'sentiment': -0.01, 'news': 0.00, 'macro': -0.03,
        },
        MarketRegime.STRONG_BEAR: {
            'valuation': 0.03, 'fundamental': 0.03, 'chip': -0.02,
            'capital_flow': 0.01, 'liquidity': 0.03, 'technical': -0.03,
            'sentiment': -0.02, 'news': 0.01, 'macro': -0.04,
        },
    }
    
    # ========== 仓位映射 ==========
    POSITION_MAP = [
        (85, 1.00, "满仓积极配置"),
        (75, 0.90, "高仓位积极配置"),
        (65, 0.75, "中高仓位配置"),
        (55, 0.60, "中等仓位配置"),
        (45, 0.45, "中性偏防御"),
        (35, 0.30, "防御配置"),
        (25, 0.15, "高度防御"),
        (0, 0.05, "极端防御，启动对冲"),
    ]
    
    # 对冲触发阈值
    HEDGE_THRESHOLD = 30.0
    ALERT_LOW_SCORE = 35.0
    
    def __init__(self):
        self._history: List[EnhancedTimingSignal] = []
        self._factor_history: Dict[str, deque] = {}
        self._regime_history: deque = deque(maxlen=10)
        self._prev_regime: Optional[MarketRegime] = None
        self._regime_confirm_count: int = 0
        self._consecutive_days: Dict[str, int] = {}
        self._signal_quality_tracker: Dict[str, float] = {}
        
    # ========== 市场环境检测 ==========
    
    def detect_market_regime(self, data: EnhancedMarketData) -> MarketRegime:
        """检测当前市场环境"""
        change = data.stock_index_change
        
        if change > 10:
            regime = MarketRegime.STRONG_BULL
        elif change > 5:
            regime = MarketRegime.BULL
        elif change > -5:
            regime = MarketRegime.RANGE
        elif change > -10:
            regime = MarketRegime.BEAR
        else:
            regime = MarketRegime.STRONG_BEAR
        
        # 趋势确认
        self._regime_history.append(regime)
        if len(self._regime_history) >= 3:
            if all(r == regime for r in list(self._regime_history)[-3:]):
                if self._prev_regime != regime:
                    self._regime_confirm_count = 3
                else:
                    self._regime_confirm_count += 1
            else:
                self._regime_confirm_count = max(0, self._regime_confirm_count - 1)
        
        if self._regime_confirm_count >= 2:
            self._prev_regime = regime
        
        return self._prev_regime or regime
    
    def get_regime_weights(self, regime: MarketRegime) -> Dict[str, float]:
        """获取当前市场环境下的动态权重"""
        adjustments = self.REGIME_WEIGHT_ADJUSTMENTS.get(regime, {})
        weights = {}
        for cat, base_w in self.DEFAULT_CATEGORY_WEIGHTS.items():
            adj = adjustments.get(cat, 0.0)
            weights[cat] = round(max(0.03, min(0.30, base_w + adj)), 4)
        
        # 归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: round(v / total, 4) for k, v in weights.items()}
        
        return weights
    
    # ========== 1. 估值面 (14%) ==========
    
    def _score_valuation(self, data: EnhancedMarketData) -> CategoryScore:
        """估值面评分：转股溢价率 + 纯债YTM + 价格分布 + PE/PB分位"""
        sub_factors = []
        
        # 1.1 转债溢价率中位数评分
        premium = data.cb_median_premium
        if premium > 0:
            premium_score = linear_score(premium, 10, 50, invert=True)
            premium_signal = "bullish" if premium < 20 else "bearish" if premium > 35 else "neutral"
            premium_desc = f"溢价率中位数{premium:.1f}%，{'低' if premium<20 else '中' if premium<35 else '高'}估区间"
        else:
            premium_score = 50.0
            premium_signal = "neutral"
            premium_desc = "无溢价率数据"
        sub_factors.append(FactorScore(
            name="转股溢价率中位数", score=premium_score, weight=0.35,
            category="valuation", raw_value=premium,
            signal=premium_signal,
            description=premium_desc,
        ))
        
        # 1.2 纯债YTM中位数评分
        ytm = data.cb_ytm_median
        ytm_score = safe_score(ytm, lambda v: linear_score(v, -2, 5, invert=False))
        sub_factors.append(FactorScore(
            name="纯债YTM中位数", score=ytm_score, weight=0.20,
            category="valuation", raw_value=ytm,
            signal="bullish" if ytm > 4 else "bearish" if ytm < 0 else "neutral",
            description=f"纯债YTM中位数{ytm:.2f}%，{'债底厚' if ytm>3 else '债底薄' if ytm<0 else '适中'}",
        ))
        
        # 1.3 转债价格中位数评分
        price = data.cb_median_price
        if price > 0:
            price_score = linear_score(price, 105, 135, invert=True)
            price_signal = "bullish" if price < 110 else "bearish" if price > 130 else "neutral"
            price_desc = f"价格中位数{price:.1f}元，{'低位' if price<110 else '高位' if price>130 else '居中'}"
        else:
            price_score = 50.0
            price_signal = "neutral"
            price_desc = "无价格数据"
        sub_factors.append(FactorScore(
            name="转债价格中位数", score=price_score, weight=0.15,
            category="valuation", raw_value=price,
            signal=price_signal,
            description=price_desc,
        ))
        
        # 1.4 PE历史分位数评分
        pe_pct = data.stock_pe_percentile
        pe_score = safe_score(pe_pct, lambda v: linear_score(v, 10, 90, invert=True))
        sub_factors.append(FactorScore(
            name="PE历史分位数", score=pe_score, weight=0.15,
            category="valuation", raw_value=pe_pct,
            signal="bullish" if pe_pct < 30 else "bearish" if pe_pct > 70 else "neutral",
            description=f"PE处于历史{pe_pct:.0f}%分位",
        ))
        
        # 1.5 PB历史分位数评分
        pb_pct = data.stock_pb_percentile
        pb_score = safe_score(pb_pct, lambda v: linear_score(v, 10, 90, invert=True))
        sub_factors.append(FactorScore(
            name="PB历史分位数", score=pb_score, weight=0.15,
            category="valuation", raw_value=pb_pct,
            signal="bullish" if pb_pct < 30 else "bearish" if pb_pct > 70 else "neutral",
            description=f"PB处于历史{pb_pct:.0f}%分位",
        ))
        
        # 加权计算
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="估值面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['valuation'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["极度低估", "低估", "合理", "高估", "泡沫"]),
        )
    
    # ========== 2. 基本面 (10%) ==========
    
    def _score_fundamental(self, data: EnhancedMarketData) -> CategoryScore:
        """基本面评分：盈利增速 + 盈利质量 + 估值合理性"""
        sub_factors = []
        
        # 2.1 盈利超预期比例
        surprise = data.earnings_surprise_ratio
        surprise_score = safe_score(surprise, lambda v: sigmoid_score(v, 0.5, steepness=4))
        sub_factors.append(FactorScore(
            name="盈利超预期比例", score=surprise_score, weight=0.25,
            category="fundamental", raw_value=surprise,
            signal="bullish" if surprise > 0.6 else "bearish" if surprise < 0.4 else "neutral",
            description=f"盈利超预期公司占比{surprise*100:.0f}%",
        ))
        
        # 2.2 GDP增速贡献
        gdp = data.gdp_growth
        gdp_score = safe_score(gdp, lambda v: sigmoid_score(v, 5.0, steepness=2))
        sub_factors.append(FactorScore(
            name="GDP增速", score=gdp_score, weight=0.20,
            category="fundamental", raw_value=gdp,
            signal="bullish" if gdp > 5.5 else "bearish" if gdp < 4.5 else "neutral",
            description=f"GDP同比增速{gdp:.1f}%",
        ))
        
        # 2.3 工业增加值
        industrial = data.industrial_output
        ind_score = safe_score(industrial, lambda v: sigmoid_score(v, 5.0, steepness=2))
        sub_factors.append(FactorScore(
            name="工业增加值增速", score=ind_score, weight=0.20,
            category="fundamental", raw_value=industrial,
            signal="bullish" if industrial > 6 else "bearish" if industrial < 4 else "neutral",
            description=f"工业增加值同比{industrial:.1f}%",
        ))
        
        # 2.4 PE/PB综合估值得分
        pe = data.stock_pe_median
        pb = data.stock_pb_median
        if pe > 0 and pb > 0:
            pe_zscore = linear_score(pe, 10, 40, invert=True)
            pb_zscore = linear_score(pb, 1, 6, invert=True)
            pe_pb_score = (pe_zscore + pb_zscore) / 2
            pe_pb_signal = "bullish" if pe_pb_score > 60 else "bearish" if pe_pb_score < 40 else "neutral"
            pe_pb_desc = f"PE={pe:.1f}, PB={pb:.2f}"
        else:
            pe_pb_score = 50.0
            pe_pb_signal = "neutral"
            pe_pb_desc = "无PE/PB数据"
        sub_factors.append(FactorScore(
            name="PE/PB综合估值", score=pe_pb_score, weight=0.15,
            category="fundamental", raw_value={"pe": pe, "pb": pb},
            signal=pe_pb_signal,
            description=pe_pb_desc,
        ))
        
        # 2.5 股息率信号
        dividend_signal = 50.0  # 默认中性
        if data.stock_pe_median < 15:
            dividend_signal = 70.0
        elif data.stock_pe_median < 20:
            dividend_signal = 55.0
        elif data.stock_pe_median > 30:
            dividend_signal = 35.0
        sub_factors.append(FactorScore(
            name="股息吸引力", score=dividend_signal, weight=0.10,
            category="fundamental", raw_value=data.stock_pe_median,
            signal="bullish" if data.stock_pe_median < 15 else "neutral",
            description=f"基于PE推断股息吸引力，PE={data.stock_pe_median:.1f}",
        ))
        
        # 2.6 社零增速
        retail = data.retail_sales
        retail_score = safe_score(retail, lambda v: sigmoid_score(v, 5.0, steepness=2))
        sub_factors.append(FactorScore(
            name="社零增速", score=retail_score, weight=0.10,
            category="fundamental", raw_value=retail,
            signal="bullish" if retail > 6 else "bearish" if retail < 4 else "neutral",
            description=f"社会消费品零售同比{retail:.1f}%",
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="基本面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['fundamental'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["极度恶化", "衰退", "中性", "改善", "强劲"]),
        )
    
    # ========== 3. 筹码面 (8%) — 持仓结构 ==========
    
    def _score_chip(self, data: EnhancedMarketData) -> CategoryScore:
        """筹码面评分：机构持仓变化 + 大股东增减持 + 融资余额占比 + IPO节奏"""
        sub_factors = []
        
        # 3.1 机构持仓变化
        inst = data.institutional_holding_change
        inst_score = safe_score(inst, lambda v: sigmoid_score(v, 0, steepness=5))
        sub_factors.append(FactorScore(
            name="机构持仓变化", score=inst_score, weight=0.30,
            category="chip", raw_value=inst,
            signal="bullish" if inst > 1 else "bearish" if inst < -1 else "neutral",
            description=f"机构持仓{inst:+.2f}%，{'加仓' if inst>1 else '减仓' if inst<-1 else '持平'}",
        ))
        
        # 3.2 融资融券余额占比（过高=过热风险，过低=情绪冰点）
        mb_ratio = data.margin_buy_ratio
        if mb_ratio <= 0:
            mb_chip_score = 50.0
            mb_chip_signal = "neutral"
            mb_chip_desc = "无融资买入数据"
        elif 7 < mb_ratio < 11:
            mb_chip_score = 70
            mb_chip_signal = "neutral"
            mb_chip_desc = f"融资买入占比{mb_ratio:.1f}%，适中"
        elif 5 < mb_ratio < 7:
            mb_chip_score = 55
            mb_chip_signal = "neutral"
            mb_chip_desc = f"融资买入占比{mb_ratio:.1f}%，偏低"
        elif mb_ratio >= 12:
            mb_chip_score = 25
            mb_chip_signal = "bearish"
            mb_chip_desc = f"融资买入占比{mb_ratio:.1f}%，过热"
        else:
            mb_chip_score = 35
            mb_chip_signal = "neutral"
            mb_chip_desc = f"融资买入占比{mb_ratio:.1f}%，杠杆不足"
        sub_factors.append(FactorScore(
            name="融资余额占比", score=mb_chip_score, weight=0.20,
            category="chip", raw_value=mb_ratio,
            signal=mb_chip_signal,
            description=mb_chip_desc,
        ))
        
        # 3.3 转债破面比例（间接反映大股东减持压力/恐慌情绪）
        if data.cb_count > 0 and data.cb_below_par_count >= 0:
            pledge_ratio = data.cb_below_par_count / data.cb_count * 100
            pledge_score = safe_score(pledge_ratio, lambda v: linear_score(v, 5, 25, invert=True))
            pledge_signal = "bullish" if pledge_ratio > 15 else "bearish" if pledge_ratio < 5 else "neutral"
            pledge_desc = f"低于面值转债占比{pledge_ratio:.1f}%，{'恐慌筹码出清' if pledge_ratio>15 else '关注' if pledge_ratio<5 else '正常'}"
        else:
            pledge_ratio = 0
            pledge_score = 50.0
            pledge_signal = "neutral"
            pledge_desc = "无转债破面数据"
        sub_factors.append(FactorScore(
            name="转债破面比例", score=pledge_score, weight=0.25,
            category="chip", raw_value=pledge_ratio,
            signal=pledge_signal,
            description=pledge_desc,
        ))
        
        # 3.4 IPO/转债新发节奏（供给压力）
        # 用PE分位作为供给压力的间接指标
        supply_score = 50.0
        if data.stock_pe_percentile > 70 and data.stock_pe_percentile > 0:
            supply_score = 65  # 高PE环境，发行积极
        elif data.stock_pe_percentile < 30 and data.stock_pe_percentile > 0:
            supply_score = 40  # 低PE环境，发行受限
        sub_factors.append(FactorScore(
            name="供给压力评估", score=supply_score, weight=0.25,
            category="chip", raw_value=data.stock_pe_percentile,
            signal="bullish" if supply_score > 55 else "bearish" if supply_score < 45 else "neutral",
            description=f"基于PE分位{data.stock_pe_percentile:.0f}%评估供给压力",
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="筹码面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['chip'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["筹码松动", "偏空", "均衡", "偏多", "筹码集中"]),
        )
    
    # ========== 4. 资金面 (12%) — 成交额 + 资金净流入流出 ==========
    
    def _score_capital_flow(self, data: EnhancedMarketData) -> CategoryScore:
        """资金面评分：市场成交额、行业资金流向、主力净流入、北向资金、融资变化"""
        sub_factors = []
        
        # 4.1 转债市场日均成交额
        cb_amount = data.cb_avg_daily_amount
        if cb_amount > 0:
            cb_amount_score = sigmoid_score(cb_amount, 500, steepness=0.008)
            cb_amount_desc = f"转债日均成交额{cb_amount:.0f}亿，{'活跃' if cb_amount>600 else '低迷' if cb_amount<300 else '正常'}"
        else:
            cb_amount_score = 50.0
            cb_amount_desc = "无转债成交额数据"
        sub_factors.append(FactorScore(
            name="转债日均成交额", score=cb_amount_score, weight=0.20,
            category="capital_flow", raw_value=cb_amount,
            signal="bullish" if cb_amount > 600 else "bearish" if cb_amount < 300 else "neutral",
            description=cb_amount_desc,
        ))
        
        # 4.2 主力资金净流入
        main_flow = data.main_force_net_flow
        main_score = sigmoid_score(main_flow, 0, steepness=0.025)
        sub_factors.append(FactorScore(
            name="主力资金净流入", score=main_score, weight=0.18,
            category="capital_flow", raw_value=main_flow,
            signal="bullish" if main_flow > 50 else "bearish" if main_flow < -50 else "neutral",
            description=f"主力净流入{main_flow:+.1f}亿，{'大幅流入' if main_flow>50 else '大幅流出' if main_flow<-50 else '平衡'}",
        ))
        
        # 4.3 北向资金净流入（聪明钱）
        north = data.north_bound_net_flow
        north_score = sigmoid_score(north, 0, steepness=0.03)
        sub_factors.append(FactorScore(
            name="北向资金净流入", score=north_score, weight=0.18,
            category="capital_flow", raw_value=north,
            signal="bullish" if north > 30 else "bearish" if north < -30 else "neutral",
            description=f"北向资金{ north:+.1f}亿，{'持续流入' if north>30 else '持续流出' if north<-30 else '小幅波动'}",
        ))
        
        # 4.4 融资余额变化（杠杆资金方向）
        margin = data.margin_balance_change
        margin_score = sigmoid_score(margin, 0, steepness=0.025)
        sub_factors.append(FactorScore(
            name="融资余额变化", score=margin_score, weight=0.16,
            category="capital_flow", raw_value=margin,
            signal="bullish" if margin > 30 else "bearish" if margin < -30 else "neutral",
            description=f"融资余额{ margin:+.1f}亿，{'杠杆加仓' if margin>30 else '杠杆减仓' if margin<-30 else '平稳'}",
        ))
        
        # 4.5 全市场成交额趋势
        turnover = data.market_turnover
        if turnover > 0:
            if turnover > 5:
                t_score = 75  # 高度活跃
            elif turnover > 3:
                t_score = 65  # 活跃
            elif turnover > 1.5:
                t_score = 55  # 正常
            elif turnover > 0.8:
                t_score = 40  # 偏冷清
            else:
                t_score = 25  # 极度冷清
            t_signal = "bullish" if 1.5 < turnover < 5 else "bearish" if turnover < 0.8 else "neutral"
            t_desc = f"全市场换手率{turnover:.2f}%，{'交投活跃' if turnover>3 else '冷清' if turnover<1 else '正常'}"
        else:
            t_score = 50.0
            t_signal = "neutral"
            t_desc = "无换手率数据"
        sub_factors.append(FactorScore(
            name="全市场换手率", score=t_score, weight=0.14,
            category="capital_flow", raw_value=turnover,
            signal=t_signal,
            description=t_desc,
        ))
        
        # 4.6 行业资金流向（净流入行业占比）
        industry_flow = data.industry_net_inflow_ratio
        ind_flow_score = safe_score(industry_flow, lambda v: sigmoid_score(v, 50, steepness=0.06))
        ind_flow_signal = "bullish" if industry_flow > 60 else "bearish" if industry_flow < 40 else "neutral"
        ind_flow_desc = f"行业净流入占比{industry_flow:.0f}分，{'多数行业净流入' if industry_flow>60 else '多数行业净流出' if industry_flow<40 else '分化'}"
        sub_factors.append(FactorScore(
            name="行业资金流向", score=ind_flow_score, weight=0.14,
            category="capital_flow", raw_value=industry_flow,
            signal=ind_flow_signal,
            description=ind_flow_desc,
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="资金面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['capital_flow'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["大幅流出", "流出", "均衡", "流入", "大幅流入"]),
        )
    
    # ========== 5. 流动性面 (11%) ==========
    
    def _score_liquidity(self, data: EnhancedMarketData) -> CategoryScore:
        """流动性面评分：Shibor利率 + 国债收益率 + LPR + 银行间拆借 + 回购利率 + 美元流动性"""
        sub_factors = []
        
        # 5.1 Shibor隔夜利率（反向）
        shibor = data.shibor_overnight
        if shibor > 0:
            shibor_score = linear_score(shibor, 1.0, 3.5, invert=True)
            shibor_signal = "bullish" if shibor < 1.5 else "bearish" if shibor > 2.5 else "neutral"
            shibor_desc = f"Shibor隔夜{shibor:.2f}%，{'极度宽松' if shibor<1.5 else '正常' if shibor<2.5 else '偏紧'}"
        else:
            shibor_score = 50.0
            shibor_signal = "neutral"
            shibor_desc = "无Shibor数据"
        sub_factors.append(FactorScore(
            name="Shibor隔夜", score=shibor_score, weight=0.18,
            category="liquidity", raw_value=shibor,
            signal=shibor_signal,
            description=shibor_desc,
        ))
        
        # 5.2 10年期国债收益率（反向）
        yield_10y = data.treasury_10y_yield
        if yield_10y > 0:
            yield_score = linear_score(yield_10y, 2.0, 4.0, invert=True)
            yield_signal = "bullish" if yield_10y < 2.5 else "bearish" if yield_10y > 3.5 else "neutral"
            yield_desc = f"10年国债{yield_10y:.2f}%，{'流动性充裕' if yield_10y<2.5 else '中性' if yield_10y<3.0 else '流动性收紧'}"
        else:
            yield_score = 50.0
            yield_signal = "neutral"
            yield_desc = "无国债收益率数据"
        sub_factors.append(FactorScore(
            name="10年国债收益率", score=yield_score, weight=0.18,
            category="liquidity", raw_value=yield_10y,
            signal=yield_signal,
            description=yield_desc,
        ))
        
        # 5.3 2年期国债收益率（短期利率锚）
        yield_2y = data.treasury_2y_yield
        if yield_2y > 0:
            y2_score = linear_score(yield_2y, 1.5, 3.5, invert=True)
            y2_signal = "bullish" if yield_2y < 2.0 else "bearish" if yield_2y > 3.0 else "neutral"
            y2_desc = f"2年国债{yield_2y:.2f}%，短端利率{'低位' if yield_2y<2.0 else '偏高' if yield_2y>3.0 else '适中'}"
        else:
            y2_score = 50.0
            y2_signal = "neutral"
            y2_desc = "无2年期国债数据"
        sub_factors.append(FactorScore(
            name="2年国债收益率", score=y2_score, weight=0.12,
            category="liquidity", raw_value=yield_2y,
            signal=y2_signal,
            description=y2_desc,
        ))
        
        # 5.4 期限利差（长-短）
        ts = data.term_spread
        if ts > 0:
            ts_score = sigmoid_score(ts, 100, steepness=0.03)
            ts_signal = "bullish" if ts > 150 else "bearish" if ts < 50 else "neutral"
            ts_desc = f"期限利差{ts:.0f}bp，{'陡峭化(宽货币)' if ts>150 else '平坦化(紧货币)' if ts<50 else '正常'}"
        else:
            ts_score = 50.0
            ts_signal = "neutral"
            ts_desc = "无期限利差数据"
        sub_factors.append(FactorScore(
            name="期限利差(10Y-2Y)", score=ts_score, weight=0.15,
            category="liquidity", raw_value=ts,
            signal=ts_signal,
            description=ts_desc,
        ))
        
        # 5.5 信用利差（AA企业债-国债）
        spread = data.credit_spread
        if spread > 0:
            spread_score = linear_score(spread, 50, 200, invert=True)
            spread_signal = "bullish" if spread < 80 else "bearish" if spread > 150 else "neutral"
            spread_desc = f"信用利差{spread:.0f}bp，{'信用环境宽松' if spread<80 else '信用紧缩' if spread>150 else '正常'}"
        else:
            spread_score = 50.0
            spread_signal = "neutral"
            spread_desc = "无信用利差数据"
        sub_factors.append(FactorScore(
            name="信用利差", score=spread_score, weight=0.15,
            category="liquidity", raw_value=spread,
            signal=spread_signal,
            description=spread_desc,
        ))
        
        # 5.6 M2增速
        m2 = data.m2_growth
        m2_score = safe_score(m2, lambda v: sigmoid_score(v, 10, steepness=2))
        sub_factors.append(FactorScore(
            name="M2增速", score=m2_score, weight=0.12,
            category="liquidity", raw_value=m2,
            signal="bullish" if m2 > 11 else "bearish" if m2 < 9 else "neutral",
            description=f"M2同比{m2:.1f}%，{'货币宽松' if m2>11 else '正常' if m2>9 else '货币收紧'}",
        ))
        
        # 5.7 社融增速
        sf = data.social_financing_growth
        sf_score = safe_score(sf, lambda v: sigmoid_score(v, 10, steepness=2))
        sub_factors.append(FactorScore(
            name="社融增速", score=sf_score, weight=0.10,
            category="liquidity", raw_value=sf,
            signal="bullish" if sf > 11 else "bearish" if sf < 9 else "neutral",
            description=f"社融同比{sf:.1f}%，{'信贷扩张' if sf>11 else '信贷收缩' if sf<9 else '正常'}",
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="流动性面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['liquidity'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["流动性危机", "偏紧", "中性", "偏宽松", "极度宽松"]),
        )
    
    # ========== 6. 技术面 (14%) ==========
    
    def _score_technical(self, data: EnhancedMarketData) -> CategoryScore:
        """技术面评分：MA排列 + MACD + RSI + 布林带 + 量价关系 + 指数位置"""
        sub_factors = []
        
        # 5.1 MA排列评分
        ma_map = {'bullish': 85, 'bullish_diverging': 70, 'neutral': 50,
                  'bearish_diverging': 30, 'bearish': 15}
        ma_score = ma_map.get(data.ma_arrangement, 50)
        sub_factors.append(FactorScore(
            name="均线排列", score=ma_score, weight=0.20,
            category="technical", raw_value=data.ma_arrangement,
            signal=data.ma_arrangement if data.ma_arrangement in ('bullish', 'bearish') else 'neutral',
            description=f"均线{'多头' if 'bull' in data.ma_arrangement else '空头' if 'bear' in data.ma_arrangement else '交叉'}排列",
        ))
        
        # 5.2 MACD信号评分
        macd_map = {'bullish': 80, 'bullish_divergence': 70, 'neutral': 50,
                    'bearish_divergence': 30, 'bearish': 20}
        macd_score = macd_map.get(data.macd_signal, 50)
        sub_factors.append(FactorScore(
            name="MACD信号", score=macd_score, weight=0.18,
            category="technical", raw_value=data.macd_signal,
            signal=data.macd_signal if data.macd_signal in ('bullish', 'bearish') else 'neutral',
            description=f"MACD{'金叉' if 'bull' in data.macd_signal else '死叉' if 'bear' in data.macd_signal else '中性'}",
        ))
        
        # 5.3 RSI评分
        rsi = data.rsi_14
        if rsi <= 20:
            rsi_score = 90  # 超卖反弹机会
        elif rsi <= 40:
            rsi_score = linear_score(rsi, 20, 40, invert=False) * 0.5 + 50
        elif rsi <= 60:
            rsi_score = 60 + (rsi - 40) / 20 * 20
        elif rsi <= 80:
            rsi_score = 80 - (rsi - 60) / 20 * 50
        else:
            rsi_score = 10  # 超买风险
        sub_factors.append(FactorScore(
            name="RSI(14)", score=rsi_score, weight=0.15,
            category="technical", raw_value=rsi,
            signal="bullish" if rsi < 35 else "bearish" if rsi > 70 else "neutral",
            description=f"RSI={rsi:.1f}，{'超卖' if rsi<30 else '超买' if rsi>70 else '正常'}",
        ))
        
        # 5.4 布林带位置评分
        bb = data.bollinger_position
        if bb <= 0.1:
            bb_score = 80
        elif bb <= 0.3:
            bb_score = 65
        elif bb <= 0.7:
            bb_score = 55
        elif bb <= 0.9:
            bb_score = 35
        else:
            bb_score = 20
        sub_factors.append(FactorScore(
            name="布林带位置", score=bb_score, weight=0.12,
            category="technical", raw_value=bb,
            signal="bullish" if bb < 0.2 else "bearish" if bb > 0.8 else "neutral",
            description=f"布林带位置{bb:.1%}，{'下轨' if bb<0.2 else '上轨' if bb>0.8 else '中轨附近'}",
        ))
        
        # 5.5 量价关系评分
        vol_ratio = data.volume_ratio
        index_chg = data.stock_index_change
        if vol_ratio > 1.3 and index_chg > 0:
            vol_price_score = 80  # 放量上涨
        elif vol_ratio > 1.3 and index_chg < 0:
            vol_price_score = 30  # 放量下跌
        elif vol_ratio < 0.7 and index_chg > 0:
            vol_price_score = 55  # 缩量上涨
        elif vol_ratio < 0.7 and index_chg < 0:
            vol_price_score = 60  # 缩量下跌
        else:
            vol_price_score = 50
        sub_factors.append(FactorScore(
            name="量价关系", score=vol_price_score, weight=0.15,
            category="technical", raw_value={'volume_ratio': vol_ratio, 'index_change': index_chg},
            signal="bullish" if vol_price_score > 60 else "bearish" if vol_price_score < 40 else "neutral",
            description=f"量比{vol_ratio:.1f}，{'放量' if vol_ratio>1.2 else '缩量' if vol_ratio<0.8 else '正常'}，{'上涨' if index_chg>0 else '下跌' if index_chg<0 else '平盘'}",
        ))
        
        # 5.6 指数 vs 均线关系
        current = data.stock_index_current
        ma20 = data.stock_index_ma20
        ma60 = data.stock_index_ma60
        if current > ma20 and ma20 > ma60:
            ma_rel_score = 85
        elif current > ma20:
            ma_rel_score = 65
        elif current > ma60:
            ma_rel_score = 45
        elif ma20 > ma60:
            ma_rel_score = 30
        else:
            ma_rel_score = 15
        sub_factors.append(FactorScore(
            name="指数均线关系", score=ma_rel_score, weight=0.10,
            category="technical", raw_value={'current': current, 'ma20': ma20, 'ma60': ma60},
            signal="bullish" if ma_rel_score > 60 else "bearish" if ma_rel_score < 40 else "neutral",
            description=f"指数{current:.0f} {'高于' if current>ma20 else '低于'} MA20({ma20:.0f})",
        ))
        
        # 5.7 转债指数位置
        cb_current = data.cb_index_current
        cb_ma20 = data.cb_index_ma20
        cb_ma60 = data.cb_index_ma60
        if cb_current > cb_ma20 and cb_ma20 > cb_ma60:
            cb_rel_score = 80
        elif cb_current > cb_ma20:
            cb_rel_score = 60
        elif cb_current > cb_ma60:
            cb_rel_score = 40
        else:
            cb_rel_score = 20
        sub_factors.append(FactorScore(
            name="转债指数均线", score=cb_rel_score, weight=0.10,
            category="technical", raw_value={'cb_current': cb_current, 'cb_ma20': cb_ma20},
            signal="bullish" if cb_rel_score > 60 else "bearish" if cb_rel_score < 40 else "neutral",
            description=f"转债指数{'多头' if cb_current>cb_ma20 else '空头'}排列",
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="技术面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['technical'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["极度弱势", "弱势", "中性", "强势", "极度强势"]),
        )
    
    # ========== 7. 情绪面 (10%) ==========
    
    def _score_sentiment(self, data: EnhancedMarketData) -> CategoryScore:
        """情绪面评分：涨跌比 + 涨停跌停比 + 新高新低比 + PCR + VIX + 融资买入"""
        sub_factors = []
        
        # 6.1 涨跌比
        ad_ratio = data.advance_decline_ratio
        ad_score = safe_score(ad_ratio, lambda v: sigmoid_score(v, 1.0, steepness=3))
        sub_factors.append(FactorScore(
            name="涨跌比", score=ad_score, weight=0.20,
            category="sentiment", raw_value=ad_ratio,
            signal="bullish" if ad_ratio > 1.5 else "bearish" if ad_ratio < 0.7 else "neutral",
            description=f"涨跌比{ad_ratio:.2f}",
        ))
        
        # 6.2 涨停跌停比
        if data.limit_up_count > 0 or data.limit_down_count > 0:
            up = max(data.limit_up_count, 1)
            down = max(data.limit_down_count, 1)
            ld_ratio = up / down
            ld_score = safe_score(ld_ratio, lambda v: sigmoid_score(v, 2, steepness=1.5))
            ld_signal = "bullish" if ld_ratio > 3 else "bearish" if ld_ratio < 1 else "neutral"
            ld_desc = f"涨停{data.limit_up_count} vs 跌停{data.limit_down_count}"
        else:
            ld_score = 50.0
            ld_signal = "neutral"
            ld_desc = "无涨跌停数据"
        sub_factors.append(FactorScore(
            name="涨停/跌停比", score=ld_score, weight=0.18,
            category="sentiment", raw_value={'up': data.limit_up_count, 'down': data.limit_down_count},
            signal=ld_signal,
            description=ld_desc,
        ))
        
        # 6.3 新高新低比
        if data.new_high_count > 0 or data.new_low_count > 0:
            nh = max(data.new_high_count, 1)
            nl = max(data.new_low_count, 1)
            hl_ratio = nh / nl
            hl_score = safe_score(hl_ratio, lambda v: sigmoid_score(v, 1.5, steepness=2))
            hl_signal = "bullish" if hl_ratio > 2 else "bearish" if hl_ratio < 0.7 else "neutral"
            hl_desc = f"60日新高{data.new_high_count} vs 新低{data.new_low_count}"
        else:
            hl_score = 50.0
            hl_signal = "neutral"
            hl_desc = "无新高新低数据"
        sub_factors.append(FactorScore(
            name="新高/新低比", score=hl_score, weight=0.15,
            category="sentiment", raw_value={'high': data.new_high_count, 'low': data.new_low_count},
            signal=hl_signal,
            description=hl_desc,
        ))
        
        # 6.4 认沽/认购比（反向指标）
        pcr = data.pcr_ratio
        if pcr > 0:
            pcr_score = linear_score(pcr, 0.6, 1.4, invert=True)
            pcr_signal = "bullish" if pcr < 0.8 else "bearish" if pcr > 1.2 else "neutral"
            pcr_desc = f"PCR={pcr:.2f}，{'看多情绪浓' if pcr<0.8 else '恐慌情绪' if pcr>1.2 else '中性'}"
        else:
            pcr_score = 50.0
            pcr_signal = "neutral"
            pcr_desc = "无PCR数据"
        sub_factors.append(FactorScore(
            name="认沽/认购比", score=pcr_score, weight=0.15,
            category="sentiment", raw_value=pcr,
            signal=pcr_signal,
            description=pcr_desc,
        ))
        
        # 6.5 波动率指数（反向指标）
        vix = data.vix_index
        if vix > 0:
            vix_score = linear_score(vix, 12, 35, invert=True)
            vix_signal = "bullish" if vix < 18 else "bearish" if vix > 28 else "neutral"
            vix_desc = f"VIX={vix:.1f}，{'极度恐慌' if vix>30 else '恐慌' if vix>25 else '平静' if vix<18 else '正常'}"
        else:
            vix_score = 50.0
            vix_signal = "neutral"
            vix_desc = "无VIX数据"
        sub_factors.append(FactorScore(
            name="波动率指数", score=vix_score, weight=0.12,
            category="sentiment", raw_value=vix,
            signal=vix_signal,
            description=vix_desc,
        ))
        
        # 6.6 融资买入占比
        mb = data.margin_buy_ratio
        if mb <= 0:
            mb_score = 50.0
            mb_signal = "neutral"
            mb_desc = "无融资买入数据"
        elif mb > 12:
            mb_score = 20
            mb_signal = "bearish"
            mb_desc = f"融资买入占比{mb:.1f}%，过热"
        elif mb > 10:
            mb_score = 40
            mb_signal = "neutral"
            mb_desc = f"融资买入占比{mb:.1f}%，偏高"
        elif mb > 8:
            mb_score = 65
            mb_signal = "bullish"
            mb_desc = f"融资买入占比{mb:.1f}%，最优区间"
        elif mb > 6:
            mb_score = 55
            mb_signal = "neutral"
            mb_desc = f"融资买入占比{mb:.1f}%，正常"
        else:
            mb_score = 35
            mb_signal = "bearish"
            mb_desc = f"融资买入占比{mb:.1f}%，过冷"
        sub_factors.append(FactorScore(
            name="融资买入占比", score=mb_score, weight=0.10,
            category="sentiment", raw_value=mb,
            signal=mb_signal,
            description=mb_desc,
        ))
        
        # 6.7 新增开户数（情绪指标，区别于资金面的换手率）
        new_acc = data.new_accounts
        if new_acc > 0:
            if new_acc > 200:
                acc_score = 75  # 大量新入场
            elif new_acc > 100:
                acc_score = 60
            elif new_acc > 50:
                acc_score = 50
            elif new_acc > 20:
                acc_score = 35  # 入场减少
            else:
                acc_score = 20  # 无人问津
            acc_signal = "bullish" if 50 < new_acc < 200 else "bearish" if new_acc < 20 else "neutral"
            acc_desc = f"新增开户{new_acc:.0f}万，{'人气旺盛' if new_acc>100 else '人气低迷' if new_acc<20 else '正常'}"
        else:
            acc_score = 50.0
            acc_signal = "neutral"
            acc_desc = "无新增开户数据"
        sub_factors.append(FactorScore(
            name="新增开户数", score=acc_score, weight=0.10,
            category="sentiment", raw_value=new_acc,
            signal=acc_signal,
            description=acc_desc,
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="情绪面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['sentiment'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["极度恐慌", "偏悲观", "中性", "偏乐观", "极度亢奋"]),
        )
    
    # ========== 8. 消息面 (7%) ==========
    
    def _score_news(self, data: EnhancedMarketData) -> CategoryScore:
        """消息面评分：政策信号 + 事件冲击 + 产业链景气"""
        sub_factors = []
        
        # 7.1 政策信号评分
        policy = data.policy_signal_score
        sub_factors.append(FactorScore(
            name="政策信号", score=policy, weight=0.40,
            category="news", raw_value=policy,
            signal="bullish" if policy > 60 else "bearish" if policy < 40 else "neutral",
            description=f"政策信号评分{policy:.0f}，{'利好' if policy>60 else '利空' if policy<40 else '中性'}",
        ))
        
        # 7.2 事件冲击评分
        event = data.event_impact_score
        sub_factors.append(FactorScore(
            name="事件冲击", score=event, weight=0.30,
            category="news", raw_value=event,
            signal="bullish" if event > 60 else "bearish" if event < 40 else "neutral",
            description=f"事件冲击评分{event:.0f}",
        ))
        
        # 7.3 产业链景气
        industry = data.industry_cycle_score
        sub_factors.append(FactorScore(
            name="产业链景气", score=industry, weight=0.30,
            category="news", raw_value=industry,
            signal="bullish" if industry > 60 else "bearish" if industry < 40 else "neutral",
            description=f"产业链景气{industry:.0f}，{'上行' if industry>60 else '下行' if industry<40 else '平稳'}",
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="消息面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['news'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["重大利空", "偏空", "中性", "偏多", "重大利好"]),
        )
    
    # ========== 9. 宏观面 (14%) ==========
    
    def _score_macro(self, data: EnhancedMarketData) -> CategoryScore:
        """宏观面评分：PMI + CPI/PPI + 出口 + GDP"""
        sub_factors = []
        
        # 8.1 PMI 趋势评分（当月+上月确认）
        if data.pmi <= 0 or data.pmi_prev <= 0:
            pmi_score = 50.0
            pmi_desc = "无PMI数据"
        elif data.pmi > 50 and data.pmi_prev > 50:
            pmi_score = 85.0
            pmi_desc = "连续扩张"
        elif data.pmi > 50:
            pmi_score = 60.0
            pmi_desc = "单月扩张"
        elif data.pmi > 48:
            pmi_score = 40.0
            pmi_desc = "弱收缩"
        else:
            pmi_score = 15.0
            pmi_desc = "明显收缩"
        if data.pmi <= 0 or data.pmi_prev <= 0:
            pmi_signal = "neutral"
        else:
            pmi_signal = "bullish" if data.pmi > 50 else "bearish" if data.pmi < 48 else "neutral"
        sub_factors.append(FactorScore(
            name="PMI", score=pmi_score, weight=0.25,
            category="macro", raw_value={'current': data.pmi, 'prev': data.pmi_prev},
            signal=pmi_signal,
            description=f"PMI当月{data.pmi:.1f}/上月{data.pmi_prev:.1f}，{pmi_desc}",
        ))
        
        # 8.2 CPI-PPI 剪刀差
        cpi_ppi_gap = data.cpi - data.ppi
        if -2 < cpi_ppi_gap < 2:
            gap_score = 50  # 合理
        elif cpi_ppi_gap >= 2:
            gap_score = 65  # CPI高于PPI，下游利润改善
        else:
            gap_score = 35  # PPI高于CPI，上游挤压下游
        sub_factors.append(FactorScore(
            name="CPI-PPI剪刀差", score=gap_score, weight=0.15,
            category="macro", raw_value={'cpi': data.cpi, 'ppi': data.ppi},
            signal="bullish" if gap_score > 55 else "bearish" if gap_score < 45 else "neutral",
            description=f"CPI {data.cpi:.1f}% / PPI {data.ppi:.1f}%，剪刀差{cpi_ppi_gap:.1f}",
        ))
        
        # 8.3 出口增速
        export = data.export_growth
        export_score = safe_score(export, lambda v: sigmoid_score(v, 5, steepness=1.5))
        sub_factors.append(FactorScore(
            name="出口增速", score=export_score, weight=0.15,
            category="macro", raw_value=export,
            signal="bullish" if export > 8 else "bearish" if export < 2 else "neutral",
            description=f"出口同比{export:.1f}%",
        ))
        
        # 8.4 GDP增速
        gdp = data.gdp_growth
        gdp_score = safe_score(gdp, lambda v: sigmoid_score(v, 5.0, steepness=2))
        sub_factors.append(FactorScore(
            name="GDP增速", score=gdp_score, weight=0.20,
            category="macro", raw_value=gdp,
            signal="bullish" if gdp > 5.5 else "bearish" if gdp < 4.5 else "neutral",
            description=f"GDP同比{gdp:.1f}%",
        ))
        
        # 8.5 工业增加值
        io = data.industrial_output
        io_score = safe_score(io, lambda v: sigmoid_score(v, 5.0, steepness=2))
        sub_factors.append(FactorScore(
            name="工业增加值", score=io_score, weight=0.15,
            category="macro", raw_value=io,
            signal="bullish" if io > 6 else "bearish" if io < 4 else "neutral",
            description=f"工业增加值同比{io:.1f}%",
        ))
        
        # 8.6 社零
        retail = data.retail_sales
        retail_score = safe_score(retail, lambda v: sigmoid_score(v, 5.0, steepness=2))
        sub_factors.append(FactorScore(
            name="社零增速", score=retail_score, weight=0.10,
            category="macro", raw_value=retail,
            signal="bullish" if retail > 6 else "bearish" if retail < 4 else "neutral",
            description=f"社零同比{retail:.1f}%",
        ))
        
        total = sum(sf.score * sf.weight for sf in sub_factors)
        w_sum = sum(sf.weight for sf in sub_factors)
        cat_score = total / w_sum if w_sum > 0 else 50
        
        return CategoryScore(
            name="宏观面", score=cat_score, weight=self.DEFAULT_CATEGORY_WEIGHTS['macro'],
            sub_factors=sub_factors,
            description=self._category_desc(cat_score, ["衰退", "偏弱", "中性", "偏强", "强劲扩张"]),
        )
    
    # ========== 交叉验证 ==========
    
    def _cross_validate(self, category_scores: Dict[str, CategoryScore],
                        data: EnhancedMarketData) -> Tuple[List[CrossValidationSignal], float]:
        """交叉验证各因子信号一致性"""
        validations = []
        
        # C1: 技术面 vs 情绪面 验证
        tech_signal = self._cat_direction(category_scores.get('technical'))
        sent_signal = self._cat_direction(category_scores.get('sentiment'))
        if tech_signal == sent_signal and tech_signal != 'neutral':
            validations.append(CrossValidationSignal(
                name="技术-情绪共振", signal=tech_signal, strength=0.8,
                description=f"技术面和情绪面同向{'看多' if tech_signal=='bullish' else '看空'}，信号增强",
                confirming_factors=["technical", "sentiment"],
            ))
        elif tech_signal != sent_signal and tech_signal != 'neutral' and sent_signal != 'neutral':
            validations.append(CrossValidationSignal(
                name="技术-情绪背离", signal="neutral", strength=0.3,
                description="技术面和情绪面背离，需警惕假信号",
                conflicting_factors=["technical", "sentiment"],
            ))
        
        # C2: 资金面 vs 筹码面 验证
        cap_signal = self._cat_direction(category_scores.get('capital_flow'))
        chip_signal = self._cat_direction(category_scores.get('chip'))
        if cap_signal == chip_signal and cap_signal != 'neutral':
            validations.append(CrossValidationSignal(
                name="资金-筹码共振", signal=cap_signal, strength=0.75,
                description=f"资金面和筹码面同向，{'增量资金入场' if cap_signal=='bullish' else '资金撤出'}",
                confirming_factors=["capital_flow", "chip"],
            ))
        
        # C3: 估值面 vs 宏观面 验证
        val_signal = self._cat_direction(category_scores.get('valuation'))
        macro_signal = self._cat_direction(category_scores.get('macro'))
        if val_signal == macro_signal and val_signal == 'bullish':
            validations.append(CrossValidationSignal(
                name="估值-宏观双击", signal='bullish', strength=0.85,
                description="低估+宏观改善，最佳配置窗口",
                confirming_factors=["valuation", "macro"],
            ))
        elif val_signal == 'bullish' and macro_signal == 'bearish':
            validations.append(CrossValidationSignal(
                name="估值陷阱预警", signal='neutral', strength=0.4,
                description="估值低但宏观恶化，可能是价值陷阱",
                conflicting_factors=["valuation", "macro"],
            ))
        
        # C4: 利率-股市联动验证
        if data.treasury_10y_yield > 0 and data.stock_index_change != 0:
            yield_down = data.treasury_10y_yield < 2.5
            stock_up = data.stock_index_change > 0
            if yield_down and stock_up:
                validations.append(CrossValidationSignal(
                    name="利率-股市同向", signal='bullish', strength=0.7,
                    description="利率下行+股市上涨，流动性驱动行情",
                    confirming_factors=["capital_flow", "technical"],
                ))
            elif not yield_down and not stock_up:
                validations.append(CrossValidationSignal(
                    name="利率-股市同向", signal='bearish', strength=0.7,
                    description="利率上行+股市下跌，流动性收紧冲击",
                    confirming_factors=["capital_flow", "technical"],
                ))
        
        # C5: 低于面值转债数量信号（极端恐慌/贪婪指标）
        if data.cb_below_par_count > 0:
            below_ratio = data.cb_below_par_count / max(data.cb_count, 1)
            if below_ratio > 0.15:
                validations.append(CrossValidationSignal(
                    name="转债破面恐慌", signal='bullish', strength=0.6,
                    description=f"{data.cb_below_par_count}只转债低于面值({below_ratio*100:.0f}%)，极端恐慌可能见底",
                    confirming_factors=["valuation"],
                ))
        
        # 计算一致性评分
        bullish_count = sum(1 for v in validations if v.signal == 'bullish')
        bearish_count = sum(1 for v in validations if v.signal == 'bearish')
        neutral_count = sum(1 for v in validations if v.signal == 'neutral')
        total_cv = len(validations)
        
        if total_cv == 0:
            consensus = 50.0
        else:
            consensus = (bullish_count * 100 + neutral_count * 50) / max(total_cv, 1)
        
        return validations, consensus
    
    def _cat_direction(self, cat: Optional[CategoryScore]) -> str:
        """判断大类方向"""
        if not cat:
            return 'neutral'
        if cat.score >= 60:
            return 'bullish'
        elif cat.score <= 40:
            return 'bearish'
        return 'neutral'
    
    # ========== 综合计算 ==========
    
    def calculate(self, data: EnhancedMarketData) -> EnhancedTimingSignal:
        """计算综合择时信号"""
        risk_alerts = []
        
        # 检测市场环境
        regime = self.detect_market_regime(data)
        
        # 获取动态权重
        actual_weights = self.get_regime_weights(regime)
        
        # 计算各因子大类得分
        category_scores = {}
        
        # 1. 估值面
        cat_val = self._score_valuation(data)
        cat_val.weight = actual_weights.get('valuation', cat_val.weight)
        category_scores['valuation'] = cat_val
        if cat_val.score < 30:
            risk_alerts.append(f"估值面得分过低({cat_val.score:.0f})，市场整体高估")
        elif cat_val.score > 80:
            risk_alerts.append(f"估值面极度低估({cat_val.score:.0f})，历史性配置机会")
        
        # 2. 基本面
        cat_fund = self._score_fundamental(data)
        cat_fund.weight = actual_weights.get('fundamental', cat_fund.weight)
        category_scores['fundamental'] = cat_fund
        if cat_fund.score < 30:
            risk_alerts.append("基本面恶化，企业盈利承压")
        
        # 3. 筹码面
        cat_chip = self._score_chip(data)
        cat_chip.weight = actual_weights.get('chip', cat_chip.weight)
        category_scores['chip'] = cat_chip
        if cat_chip.score < 25:
            risk_alerts.append("筹码面恶化，资金大量流出")
        
        # 4. 资金面
        cat_cap = self._score_capital_flow(data)
        cat_cap.weight = actual_weights.get('capital_flow', cat_cap.weight)
        category_scores['capital_flow'] = cat_cap
        if cat_cap.score < 25:
            risk_alerts.append("资金面极度紧缩，流动性危机风险")
        
        # 5. 流动性面
        cat_liq = self._score_liquidity(data)
        cat_liq.weight = actual_weights.get('liquidity', cat_liq.weight)
        category_scores['liquidity'] = cat_liq
        if cat_liq.score < 25:
            risk_alerts.append("流动性极度紧张，警惕系统性风险")
        elif cat_liq.score > 80:
            risk_alerts.append("流动性极度宽松，资金充裕")
        
        # 6. 技术面
        cat_tech = self._score_technical(data)
        cat_tech.weight = actual_weights.get('technical', cat_tech.weight)
        category_scores['technical'] = cat_tech
        if cat_tech.score < 25:
            risk_alerts.append("技术面严重破位，趋势向下")
        
        # 7. 情绪面
        cat_sent = self._score_sentiment(data)
        cat_sent.weight = actual_weights.get('sentiment', cat_sent.weight)
        category_scores['sentiment'] = cat_sent
        if cat_sent.score < 20:
            risk_alerts.append("市场极度恐慌，注意恐慌性抛售")
        elif cat_sent.score > 85:
            risk_alerts.append("市场情绪过度亢奋，警惕回调风险")
        
        # 8. 消息面
        cat_news = self._score_news(data)
        cat_news.weight = actual_weights.get('news', cat_news.weight)
        category_scores['news'] = cat_news
        
        # 9. 宏观面
        cat_macro = self._score_macro(data)
        cat_macro.weight = actual_weights.get('macro', cat_macro.weight)
        category_scores['macro'] = cat_macro
        
        # 交叉验证
        cross_validations, consensus = self._cross_validate(category_scores, data)
        
        # 加权综合得分
        total = sum(cat.score * cat.weight for cat in category_scores.values())
        w_sum = sum(cat.weight for cat in category_scores.values())
        if w_sum > 0:
            total_score = total / w_sum
        else:
            total_score = 50.0
        
        # 一致性调整：如果交叉验证强烈一致，适当调整总分
        if consensus > 70 and total_score > 55:
            total_score += 3  # 一致看多，加分
        elif consensus < 30 and total_score < 45:
            total_score -= 3  # 一致看空，减分
        
        total_score = max(5, min(95, total_score))
        
        # 仓位映射
        position_ratio = self._get_position_ratio(total_score)
        
        # 对冲推荐
        hedge_recommended = total_score < self.HEDGE_THRESHOLD
        if hedge_recommended:
            risk_alerts.append(f"择时得分{total_score:.0f}低于{self.HEDGE_THRESHOLD:.0f}，建议启动对冲")
        
        # 信号质量评估
        quality, confidence = self._assess_quality(category_scores, cross_validations,
                                                    data.data_completeness)
        
        # 创建信号
        signal = EnhancedTimingSignal(
            date=data.date,
            total_score=total_score,
            position_ratio=position_ratio,
            market_regime=regime,
            category_scores=category_scores,
            cross_validations=cross_validations,
            consensus_score=consensus,
            quality=quality,
            confidence=confidence,
            risk_alerts=risk_alerts,
            hedge_recommended=hedge_recommended,
            actual_weights=actual_weights,
        )
        
        self._history.append(signal)
        if len(self._history) > 252:
            self._history = self._history[-252:]
        
        logger.info(
            f"[EnhancedTiming] 综合得分={total_score:.1f}, "
            f"仓位={position_ratio*100:.0f}%, 环境={regime.value}, "
            f"质量={quality.value}, 置信度={confidence:.2f}"
        )
        
        return signal
    
    def _get_position_ratio(self, score: float) -> float:
        """根据得分获取仓位比例"""
        for threshold, ratio, _ in self.POSITION_MAP:
            if score >= threshold:
                return ratio
        return 0.05
    
    def _assess_quality(
        self,
        category_scores: Dict[str, CategoryScore],
        cross_validations: List[CrossValidationSignal],
        data_completeness: float,
    ) -> Tuple[SignalQuality, float]:
        """评估信号质量和置信度"""
        # 数据完整度
        completeness_score = data_completeness
        
        # 方向一致性
        directions = [self._cat_direction(c) for c in category_scores.values()]
        bullish = sum(1 for d in directions if d == 'bullish')
        bearish = sum(1 for d in directions if d == 'bearish')
        neutral = sum(1 for d in directions if d == 'neutral')
        total = len(directions)
        
        if total > 0:
            # 一致性比例
            agreement = max(bullish, bearish, neutral) / total
        else:
            agreement = 0.5
        
        # 交叉验证强度
        avg_cv_strength = np.mean([v.strength for v in cross_validations]) if cross_validations else 0.5
        
        # 综合置信度
        confidence = completeness_score * 0.4 + agreement * 0.35 + avg_cv_strength * 0.25
        
        # 质量等级
        if confidence > 0.8:
            quality = SignalQuality.EXCELLENT
        elif confidence > 0.65:
            quality = SignalQuality.GOOD
        elif confidence > 0.5:
            quality = SignalQuality.FAIR
        elif confidence > 0.35:
            quality = SignalQuality.WEAK
        else:
            quality = SignalQuality.UNRELIABLE
        
        return quality, confidence
    
    # ========== 辅助方法 ==========
    
    def _category_desc(self, score: float, labels: List[str]) -> str:
        """根据得分返回描述"""
        n = len(labels)
        if n == 0:
            return ""
        idx = int(score / 100 * n)
        idx = max(0, min(n - 1, idx))
        return labels[idx]
    
    def get_history(self, days: int = 60) -> List[dict]:
        """获取历史信号"""
        cutoff = datetime.now() - timedelta(days=days)
        return [s.to_dict() for s in self._history if s.timestamp >= cutoff]
    
    def get_trend(self) -> str:
        """获取择时趋势"""
        if len(self._history) < 5:
            return "flat"
        recent = self._history[-5:]
        first_avg = sum(s.total_score for s in recent[:2]) / 2
        last_avg = sum(s.total_score for s in recent[-2:]) / 2
        diff = last_avg - first_avg
        if diff > 5:
            return "up"
        elif diff < -5:
            return "down"
        return "flat"
    
    def get_consecutive_direction(self) -> Tuple[str, int]:
        """获取连续方向天数"""
        if len(self._history) < 2:
            return "flat", 0
        
        direction = "up" if self._history[-1].total_score >= self._history[-2].total_score else "down"
        count = 1
        for i in range(len(self._history) - 2, -1, -1):
            prev_dir = "up" if self._history[i + 1].total_score >= self._history[i].total_score else "down"
            if prev_dir == direction:
                count += 1
            else:
                break
        return direction, count
    
    def should_rebalance(self, new_signal: EnhancedTimingSignal) -> bool:
        """判断是否需要调仓"""
        if not self._history:
            return True
        
        last = self._history[-1]
        if abs(new_signal.total_score - last.total_score) > 8:
            return True
        if abs(new_signal.position_ratio - last.position_ratio) > 0.15:
            return True
        if new_signal.market_regime != last.market_regime:
            return True
        
        return False
    
    @property
    def last_signal(self) -> Optional[EnhancedTimingSignal]:
        return self._history[-1] if self._history else None

    # ========== 集成学习方法 ==========

    def calculate_ensemble(self, data: EnhancedMarketData) -> EnhancedTimingSignal:
        """集成学习综合择时：使用多种方法融合

        三种评分方法：
        1. 加权求和（Weighted Sum, WS）
        2. 排序平均（Rank Average, RA）
        3. 波动率调整加权（Volatility-Adjusted Weighted, VAW）

        最终得分 = WS * 0.5 + RA * 0.3 + VAW * 0.2
        """
        # 先计算标准得分（WS方法）
        ws_signal = self.calculate(data)
        ws_score = ws_signal.total_score  # 保存原始WS得分

        # RA方法：基于各因子排名的综合得分
        ra_score = self._rank_average_score(ws_signal.category_scores)

        # VAW方法：基于波动率调整
        vaw_score = self._vol_adjusted_score(ws_signal.category_scores, data)

        # 融合
        ensemble_score = ws_score * 0.5 + ra_score * 0.3 + vaw_score * 0.2
        ensemble_score = max(5, min(95, ensemble_score))

        # 更新信号
        ws_signal.total_score = ensemble_score
        ws_signal.position_ratio = self._get_position_ratio(ensemble_score)
        ws_signal.hedge_recommended = ensemble_score < self.HEDGE_THRESHOLD

        # 更新置信度（集成方法通常有更高置信度）
        if ws_signal.confidence > 0:
            ws_signal.confidence = min(1.0, ws_signal.confidence * 1.05)

        self._history[-1] = ws_signal

        logger.info(
            f"[EnsembleTiming] WS={ws_score:.1f}, RA={ra_score:.1f}, "
            f"VAW={vaw_score:.1f}, 集成={ensemble_score:.1f}"
        )

        return ws_signal

    def _rank_average_score(self, category_scores: Dict[str, CategoryScore]) -> float:
        """排序平均法评分

        将各因子得分转换为排序，取排序均值
        对极端值有更好鲁棒性
        """
        if not category_scores:
            return 50.0

        scores = [(k, v.score) for k, v in category_scores.items()]
        scores.sort(key=lambda x: x[1])

        n = len(scores)
        if n == 0:
            return 50.0

        # 给每个因子排序分（最低=1/n，最高=1）
        rank_scores = {}
        for rank, (key, _) in enumerate(scores):
            rank_scores[key] = (rank + 1) / n * 100

        # 按原始权重加权
        total = 0.0
        w_sum = 0.0
        for key, cat in category_scores.items():
            w = cat.weight
            total += rank_scores.get(key, 50) * w
            w_sum += w

        return total / w_sum if w_sum > 0 else 50.0

    def _vol_adjusted_score(self, category_scores: Dict[str, CategoryScore],
                           data: EnhancedMarketData) -> float:
        """波动率调整加权评分

        高波动环境下降低高波动因子的权重（如技术面、情绪面）
        低波动环境下提高趋势类因子权重
        """
        if not category_scores:
            return 50.0

        # 估算当前市场波动率（基于涨跌比和指数变化）
        vol_proxy = 0.0
        if data.stock_index_change != 0:
            vol_proxy = abs(data.stock_index_change)
        if data.advance_decline_ratio > 0:
            ad_vol = abs(data.advance_decline_ratio - 1) * 10
            vol_proxy = max(vol_proxy, ad_vol)

        # 波动率因子（0-1，越高越波动）
        vol_factor = min(1.0, vol_proxy / 10 if vol_proxy > 0 else 0.3)

        # 高波动下给低波动因子加权
        high_vol_cats = {'technical', 'sentiment', 'chip'}
        low_vol_cats = {'valuation', 'fundamental', 'macro', 'liquidity'}

        total = 0.0
        w_sum = 0.0
        for key, cat in category_scores.items():
            base_weight = cat.weight
            if key in high_vol_cats:
                adj_weight = base_weight * (1.0 - vol_factor * 0.3)
            elif key in low_vol_cats:
                adj_weight = base_weight * (1.0 + vol_factor * 0.2)
            else:
                adj_weight = base_weight

            total += cat.score * adj_weight
            w_sum += adj_weight

        return total / w_sum if w_sum > 0 else 50.0

    # ========== 信号稳定性追踪 ==========

    def get_signal_stability(self) -> Dict[str, Any]:
        """计算信号稳定性指标"""
        if len(self._history) < 10:
            return {"stable": True, "volatility": 0, "trend": "flat"}

        recent = self._history[-20:]
        scores = [s.total_score for s in recent]
        volatility = float(np.std(scores))
        trend = self.get_trend()

        # 稳定性：波动率低于5分视为稳定
        stable = volatility < 8

        return {
            "stable": stable,
            "volatility": round(volatility, 2),
            "trend": trend,
            "avg_score": round(float(np.mean(scores)), 1),
            "min_score": round(min(scores), 1),
            "max_score": round(max(scores), 1),
            "samples": len(scores),
        }

    def get_factor_contribution(self, signal: EnhancedTimingSignal = None) -> Dict[str, float]:
        """计算各因子对总分的贡献度"""
        if signal is None:
            signal = self.last_signal
        if signal is None:
            return {}

        contributions = {}
        total = signal.total_score
        if total <= 0:
            return {}

        for key, cat in signal.category_scores.items():
            contrib = (cat.score * cat.weight) / total * 100 if total > 0 else 0
            contributions[key] = round(contrib, 1)

        return contributions

    def get_risk_score(self) -> float:
        """计算独立风险评分（0-100，越高风险越大）

        基于：信号波动率 + 连续下跌天数 + 方向一致性 + 因子分散度
        """
        risk = 50.0  # 中性

        # 信号波动率
        stability = self.get_signal_stability()
        vol = stability.get('volatility', 0)
        if vol > 10:
            risk += (vol - 10) * 2
        elif vol < 3:
            risk -= 5

        # 连续下跌
        direction, days = self.get_consecutive_direction()
        if direction == 'down' and days >= 3:
            risk += days * 3
        elif direction == 'up' and days >= 3:
            risk -= days * 2

        # 低分环境
        if self.last_signal and self.last_signal.total_score < 40:
            risk += (40 - self.last_signal.total_score) * 1.5

        return max(0, min(100, risk))


# ==================== 工厂函数 ====================

def create_enhanced_timing_model() -> EnhancedTimingModel:
    """创建增强择时模型实例"""
    return EnhancedTimingModel()


# ==================== 从旧版 MarketData 转换 ====================

def convert_from_legacy_data(
    legacy_data=None,
    bonds_df: Optional[pd.DataFrame] = None,
    macro_data=None,
) -> EnhancedMarketData:
    """从旧版数据格式转换为 EnhancedMarketData"""
    data = EnhancedMarketData(date=date.today())
    
    # 从旧版 MarketData 填充
    if legacy_data:
        data.cb_median_premium = getattr(legacy_data, 'cb_median_premium', 0) or 0
        data.cb_avg_daily_amount = getattr(legacy_data, 'cb_avg_daily_amount', 0) or 0
        data.cb_index_change = getattr(legacy_data, 'cb_index_change', 0) or 0
        data.cb_index_current = getattr(legacy_data, 'cb_index_current', 0) or 0
        data.cb_index_ma20 = getattr(legacy_data, 'cb_index_ma20', 0) or 0
        data.treasury_10y_yield = getattr(legacy_data, 'treasury_10y_yield', 0) or 0
        data.pmi = getattr(legacy_data, 'pmi', 0) or 0
        data.pmi_prev = getattr(legacy_data, 'pmi_prev', 0) or 0
    
    # 从 MacroData 补充（扩展版 V2.0）
    if macro_data:
        if data.treasury_10y_yield <= 0:
            data.treasury_10y_yield = getattr(macro_data, 'treasury_10y_yield', 0) or 0
        data.treasury_2y_yield = getattr(macro_data, 'treasury_2y_yield', 0) or 0
        if data.pmi <= 0 or data.pmi == 50.0:
            val = getattr(macro_data, 'pmi_current', 0)
            if val > 0:
                data.pmi = val
        if data.pmi_prev <= 0 or data.pmi_prev == 50.0:
            val = getattr(macro_data, 'pmi_prev', 0)
            if val > 0:
                data.pmi_prev = val
        # Shibor / 流动性
        data.shibor_overnight = getattr(macro_data, 'shibor_overnight', 0) or 0
        data.cpi = getattr(macro_data, 'cpi', 0) or 0
        data.ppi = getattr(macro_data, 'ppi', 0) or 0
        data.m2_growth = getattr(macro_data, 'm2_growth', 0) or 0
        data.social_financing_growth = getattr(macro_data, 'social_financing_growth', 0) or 0
        data.gdp_growth = getattr(macro_data, 'gdp_growth', 0) or 0
        data.credit_spread = getattr(macro_data, 'credit_spread_aa', 0) or 0
        data.term_spread = (data.treasury_10y_yield - data.treasury_2y_yield) * 100 if data.treasury_10y_yield > 0 and data.treasury_2y_yield > 0 else 0
        # 市场情绪
        data.limit_up_count = getattr(macro_data, 'limit_up_count', 0) or 0
        data.limit_down_count = getattr(macro_data, 'limit_down_count', 0) or 0
        adv = getattr(macro_data, 'advance_count', 0) or 0
        dec = getattr(macro_data, 'decline_count', 0) or 0
        if adv > 0 or dec > 0:
            data.advance_decline_ratio = adv / max(dec, 1)
        data.market_turnover = getattr(macro_data, 'market_turnover', 0) or 0
        data.new_high_count = getattr(macro_data, 'new_high_60d', 0) or 0
        data.new_low_count = getattr(macro_data, 'new_low_60d', 0) or 0
        # 股票指数
        data.stock_index_current = getattr(macro_data, 'stock_index_current', 0) or 0
        data.stock_index_change = getattr(macro_data, 'stock_index_change', 0) or 0
        data.stock_index_ma20 = getattr(macro_data, 'stock_index_ma20', 0) or 0
        data.stock_index_ma60 = getattr(macro_data, 'stock_index_ma60', 0) or 0
        # === 新增：从 MacroData V2.1 填充所有先前硬编码的字段 ===
        # PE/PB
        val = getattr(macro_data, 'stock_pe_median', 0)
        if val > 0:
            data.stock_pe_median = val
        val = getattr(macro_data, 'stock_pb_median', 0)
        if val > 0:
            data.stock_pb_median = val
        val = getattr(macro_data, 'stock_pe_percentile', 0)
        if val > 0:
            data.stock_pe_percentile = val
        val = getattr(macro_data, 'stock_pb_percentile', 0)
        if val > 0:
            data.stock_pb_percentile = val
        # 资金流向
        data.north_bound_net_flow = getattr(macro_data, 'north_bound_net_flow', 0) or 0
        data.main_force_net_flow = getattr(macro_data, 'main_force_net_flow', 0) or 0
        data.margin_balance_change = getattr(macro_data, 'margin_balance_change', 0) or 0
        val = getattr(macro_data, 'margin_buy_ratio', 0)
        if val > 0:
            data.margin_buy_ratio = val
        val = getattr(macro_data, 'industry_net_inflow', 0)
        if val > 0:
            data.industry_net_inflow_ratio = val
        # 宏观扩展
        val = getattr(macro_data, 'industrial_output', 0)
        if val != 0:
            data.industrial_output = val
        val = getattr(macro_data, 'retail_sales', 0)
        if val != 0:
            data.retail_sales = val
        val = getattr(macro_data, 'export_growth', 0)
        if val != 0:
            data.export_growth = val
        # 情绪扩展
        val = getattr(macro_data, 'pcr_ratio', 0)
        if val > 0:
            data.pcr_ratio = val
        val = getattr(macro_data, 'vix_index', 0)
        if val > 0:
            data.vix_index = val
        data.new_accounts = getattr(macro_data, 'new_accounts', 0) or 0
        # 技术指标（从 MacroDataService 自动计算）
        val = getattr(macro_data, 'ma_arrangement', '')
        if val and val != 'neutral':
            data.ma_arrangement = val
        val = getattr(macro_data, 'macd_signal', '')
        if val and val != 'neutral':
            data.macd_signal = val
        val = getattr(macro_data, 'rsi_14', 0)
        if val > 0:
            data.rsi_14 = val
        val = getattr(macro_data, 'bollinger_position', 0)
        if val > 0:
            data.bollinger_position = val
        val = getattr(macro_data, 'volume_ratio', 0)
        if val > 0:
            data.volume_ratio = val
        # 机构持仓/盈利超预期/消息面
        val = getattr(macro_data, 'institutional_holding_change', 0)
        if val != 0:
            data.institutional_holding_change = val
        val = getattr(macro_data, 'earnings_surprise_ratio', 0)
        if val > 0:
            data.earnings_surprise_ratio = val
        val = getattr(macro_data, 'policy_signal_score', 0)
        if val > 0:
            data.policy_signal_score = val
        val = getattr(macro_data, 'event_impact_score', 0)
        if val > 0:
            data.event_impact_score = val
        val = getattr(macro_data, 'industry_cycle_score', 0)
        if val > 0:
            data.industry_cycle_score = val
    
    # 从 bonds_df 计算补充指标
    if bonds_df is not None and not bonds_df.empty:
        if 'premium_ratio' in bonds_df.columns:
            premiums = bonds_df['premium_ratio'].dropna()
            if len(premiums) > 0:
                data.cb_median_premium = data.cb_median_premium or float(premiums.median())
                data.cb_avg_premium = float(premiums.mean())
        
        if 'price' in bonds_df.columns:
            prices = bonds_df['price'].dropna()
            if len(prices) > 0:
                data.cb_median_price = data.cb_median_price or float(prices.median())
                data.cb_below_par_count = int((prices < 100).sum())
            data.cb_count = len(bonds_df)
        
        if 'ytm' in bonds_df.columns:
            ytms = bonds_df['ytm'].dropna()
            if len(ytms) > 0:
                data.cb_ytm_median = float(ytms.median())
        
        if 'volume' in bonds_df.columns:
            volumes = bonds_df['volume'].dropna()
            if len(volumes) > 0 and data.cb_avg_daily_amount <= 0:
                data.cb_avg_daily_amount = float(volumes.sum() / len(volumes))
    
    data.data_completeness = min(1.0, sum([
        0.05 if data.cb_median_premium > 0 else 0,
        0.05 if data.treasury_10y_yield > 0 else 0,
        0.04 if 0 < data.pmi < 100 else 0,
        0.04 if data.cb_avg_daily_amount > 0 else 0,
        0.04 if data.cb_index_current > 0 else 0,
        0.04 if data.stock_index_current > 0 else 0,
        0.04 if data.cb_median_price > 0 else 0,
        0.03 if data.cb_count > 0 else 0,
        0.04 if data.shibor_overnight > 0 else 0,
        0.04 if data.m2_growth > 0 else 0,
        0.04 if data.cpi > 0 or data.ppi != 0 else 0,
        0.03 if data.social_financing_growth > 0 else 0,
        0.03 if data.gdp_growth > 0 else 0,
        0.04 if data.credit_spread > 0 else 0,
        0.03 if data.term_spread > 0 else 0,
        0.04 if data.north_bound_net_flow != 0 else 0,
        0.04 if data.main_force_net_flow != 0 else 0,
        0.03 if data.margin_balance_change != 0 else 0,
        0.03 if data.margin_buy_ratio > 0 else 0,
        0.03 if data.industry_net_inflow_ratio > 0 else 0,
        0.04 if data.stock_pe_median > 0 and data.stock_pb_median > 0 else 0,
        0.03 if data.industrial_output != 0 else 0,
        0.03 if data.retail_sales != 0 else 0,
        0.03 if data.export_growth != 0 else 0,
        0.02 if data.pcr_ratio > 0 else 0,
        0.02 if data.vix_index > 0 else 0,
        0.02 if data.new_accounts > 0 else 0,
        0.03 if data.rsi_14 > 0 else 0,
        0.02 if data.bollinger_position > 0 else 0,
        0.02 if data.volume_ratio > 0 else 0,
        0.02 if data.advance_decline_ratio > 0 else 0,
    ]))
    
    data.updated_at = datetime.now()
    return data
