"""西部量化可转债策略 V3.0 多因子择时引擎（Legacy V3）

旧版四因子维度（已由 V4 多维度综合模型替代，见 enhanced_timing_model.py）:
- 全市场转债估值 (40%): 转股溢价率中位数
- 市场情绪 (25%): 转债日均成交额
- 市场流动性 (20%): 10年期国债收益率
- 宏观经济 (15%): PMI

择时得分对应仓位:
- ≥70分: 80%
- 50-69分: 55%
- 30-49分: 30%
- <30分: ≤10% + 启动对冲

新版模型（9大类40+子因子）: app.strategies.enhanced_timing_model.EnhancedTimingModel
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional, Tuple
import logging

from app.xb_strategy.core.types import TimingSignal
from app.xb_strategy.config.settings import params
from app.xb_strategy.config.weights import MarketRegime, detect_market_regime

logger = logging.getLogger(__name__)


@dataclass
class MarketData:
    """市场数据"""
    date: date
    # 转债市场
    cb_median_premium: float = 0.0       # 转股溢价率中位数(%)
    cb_avg_daily_amount: float = 0.0     # 转债日均成交额(亿)
    cb_index_change: float = 0.0         # 转债指数涨跌幅(%)
    cb_index_ma20: float = 0.0           # 转债指数20日均线
    cb_index_current: float = 0.0        # 转债指数当前值
    # 债券市场
    treasury_10y_yield: float = 0.0      # 10年期国债收益率(%)
    # 宏观
    pmi: float = 50.0                    # PMI
    pmi_prev: float = 50.0               # 上月PMI


class TimingEngine:
    """多因子择时引擎 (Legacy V3 — 已由 EnhancedTimingEngine 替代)"""

    def __init__(self):
        """初始化"""
        self._history: List[TimingSignal] = []
        self._trend_confirm_count: int = 0
        self._prev_regime: Optional[MarketRegime] = None

    def calculate_timing(
        self,
        market_data: MarketData,
    ) -> TimingSignal:
        """计算择时信号

        Args:
            market_data: 市场数据

        Returns:
            TimingSignal: 择时信号
        """
        # 1. 估值得分 (40%)
        valuation_score = self._score_valuation(market_data.cb_median_premium)

        # 2. 情绪得分 (25%)
        sentiment_score = self._score_sentiment(market_data.cb_avg_daily_amount)

        # 3. 流动性得分 (20%)
        liquidity_score = self._score_liquidity(market_data.treasury_10y_yield)

        # 4. 宏观得分 (15%)
        macro_score = self._score_macro(market_data.pmi, market_data.pmi_prev)

        # 综合得分
        total_score = (
            valuation_score * 0.40
            + sentiment_score * 0.25
            + liquidity_score * 0.20
            + macro_score * 0.15
        )

        # 仓位比例
        position_ratio = params.get_position_ratio(total_score)

        # 市场环境
        regime = detect_market_regime(market_data.cb_index_change)

        # 对冲需求
        hedge_required = total_score < params.hedge_timing_threshold

        signal = TimingSignal(
            date=market_data.date,
            valuation_score=valuation_score,
            sentiment_score=sentiment_score,
            liquidity_score=liquidity_score,
            macro_score=macro_score,
            total_score=total_score,
            position_ratio=position_ratio,
            regime=regime,
            hedge_required=hedge_required,
        )

        # 保存历史
        self._history.append(signal)
        if len(self._history) > 60:
            self._history = self._history[-60:]

        logger.info(
            f"[Timing] 择时信号: 得分{total_score:.1f}, "
            f"仓位{position_ratio*100:.0f}%, 环境{regime.value}"
        )

        return signal

    def _score_valuation(self, median_premium: float) -> float:
        """估值得分(满分100)

        转股溢价率中位数:
        - <20%: 满分
        - 20-30%: 50分
        - >30%: 0分
        """
        if median_premium < 20:
            return 100.0
        elif median_premium < 30:
            return 50.0
        else:
            return 0.0

    def _score_sentiment(self, avg_daily_amount: float) -> float:
        """情绪得分(满分100)

        转债日均成交额:
        - >600亿: 满分
        - 300-600亿: 50分
        - <300亿: 0分
        """
        if avg_daily_amount > 600:
            return 100.0
        elif avg_daily_amount > 300:
            return 50.0
        else:
            return 0.0

    def _score_liquidity(self, treasury_yield: float) -> float:
        """流动性得分(满分100)

        10年期国债收益率:
        - <2.5%: 满分
        - 2.5-3.0%: 50分
        - >3.0%: 0分
        """
        if treasury_yield < 2.5:
            return 100.0
        elif treasury_yield < 3.0:
            return 50.0
        else:
            return 0.0

    def _score_macro(self, pmi: float, pmi_prev: float) -> float:
        """宏观得分(满分100)

        PMI:
        - 连续2月>50: 满分
        - PMI>50但仅1个月: 50分
        - PMI<50: 0分
        """
        if pmi > 50 and pmi_prev > 50:
            return 100.0
        elif pmi > 50:
            return 50.0
        else:
            return 0.0

    def check_trend_confirmation(
        self,
        current_regime: MarketRegime,
    ) -> Tuple[bool, int]:
        """检查趋势确认

        需要连续2周确认同一方向才切换

        Args:
            current_regime: 当前市场环境

        Returns:
            (是否确认, 连续周数)
        """
        if self._prev_regime is None:
            self._prev_regime = current_regime
            self._trend_confirm_count = 1
            return True, 1

        if current_regime == self._prev_regime:
            self._trend_confirm_count += 1
        else:
            self._trend_confirm_count = 1
            self._prev_regime = current_regime

        confirmed = self._trend_confirm_count >= params.dynamic_weight_confirm_weeks
        return confirmed, self._trend_confirm_count

    def get_regime_with_confirmation(
        self,
        market_data: MarketData,
    ) -> Tuple[MarketRegime, bool]:
        """获取带确认的市场环境

        Args:
            market_data: 市场数据

        Returns:
            (市场环境, 是否确认切换)
        """
        # 计算基于月度变化的市场环境
        regime = detect_market_regime(market_data.cb_index_change)

        # 检查趋势确认
        confirmed, weeks = self.check_trend_confirmation(regime)

        return regime, confirmed

    def get_average_score(self, days: int = 5) -> float:
        """获取N日平均择时得分

        Args:
            days: 天数

        Returns:
            平均得分
        """
        if not self._history:
            return 50.0

        recent = self._history[-days:] if len(self._history) >= days else self._history
        return sum(s.total_score for s in recent) / len(recent)

    def get_trend(self) -> str:
        """获取择时趋势

        Returns:
            "up" / "down" / "flat"
        """
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
        else:
            return "flat"


class EnhancedTimingEngine(TimingEngine):
    """增强版择时引擎"""

    def calculate_timing(
        self,
        market_data: MarketData,
    ) -> TimingSignal:
        """计算择时信号(增强版)"""
        signal = super().calculate_timing(market_data)

        # 增加额外判断
        # 1. 检查转债指数是否跌破20日均线
        if market_data.cb_index_current < market_data.cb_index_ma20:
            signal.position_ratio = min(signal.position_ratio, 0.5)
            logger.info("[Timing] 转债指数跌破20日均线，仓位限制50%")

        # 2. 检查连续下跌
        if self._is_consecutive_decline(3):
            signal.position_ratio = min(signal.position_ratio, 0.3)
            signal.hedge_required = True
            logger.info("[Timing] 连续3日下跌，启动防御模式")

        return signal

    def _is_consecutive_decline(self, days: int) -> bool:
        """检查是否连续下跌

        Args:
            days: 天数

        Returns:
            是否连续下跌
        """
        if len(self._history) < days:
            return False

        recent = self._history[-days:]
        for i in range(1, len(recent)):
            if recent[i].total_score >= recent[i - 1].total_score:
                return False
        return True

    def get_risk_alert(self) -> Optional[str]:
        """获取风险预警

        Returns:
            预警信息，无预警返回None
        """
        if not self._history:
            return None

        latest = self._history[-1]

        if latest.total_score < 30:
            return f"择时得分过低({latest.total_score:.1f})，建议降低仓位并启动对冲"

        if self._is_consecutive_decline(5):
            return "连续5日择时得分下降，市场可能转弱"

        return None
