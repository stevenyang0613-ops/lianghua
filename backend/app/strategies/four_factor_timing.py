"""
四因子动态择时模型 V3.0 (Legacy)

保留用于历史回测对比和向后兼容。
新系统请使用：app.strategies.enhanced_timing_model.EnhancedTimingModel
（多维度综合择时模型 V4.0：9 大类 40+ 子因子）

用于确定组合仓位上限：
- 全市场转债估值（40%）
- 市场情绪（25%）
- 市场流动性（20%）
- 宏观经济（15%）

择时得分对应仓位：
- ≥70分：80%仓位（积极配置）
- 50-69分：50-60%仓位（中性配置）
- 30-49分：20-35%仓位（防御配置）
- <30分：≤10%+启动对冲（极端防御）
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class TimingSignal:
    """择时信号"""
    score: float  # 综合得分 0-100
    position_limit: float  # 仓位上限
    market_env: str  # bull/bear/neutral
    should_hedge: bool  # 是否启动对冲
    details: dict  # 各因子详情
    ts: datetime


class FourFactorTiming:
    """四因子动态择时模型 V3 (Legacy) — 已由 EnhancedTimingModel 替代"""

    # 因子权重
    WEIGHTS = {
        'valuation': 0.40,   # 全市场估值
        'sentiment': 0.25,   # 市场情绪
        'liquidity': 0.20,   # 市场流动性
        'macro': 0.15,       # 宏观经济
    }

    # 择时得分与仓位对应表
    POSITION_MAP = {
        (70, 100): {'limit': 0.80, 'desc': '积极配置'},
        (50, 69): {'limit': 0.55, 'desc': '中性配置'},
        (30, 49): {'limit': 0.275, 'desc': '防御配置'},
        (0, 29): {'limit': 0.10, 'desc': '极端防御'},
    }

    def __init__(self):
        self._last_signal: Optional[TimingSignal] = None
        self._signal_history: list[TimingSignal] = []
        self._trend_confirmed: Optional[str] = None  # bull/bear/neutral
        self._trend_weeks: int = 0

    def calc_valuation_score(self, bonds_df: pd.DataFrame) -> dict:
        """
        全市场转债估值评分（满分40分）
        转股溢价率中位数 < 20%得满分；20%-30%得一半；> 30%得0分
        """
        if bonds_df.empty or 'premium_ratio' not in bonds_df.columns:
            return {'score': 20, 'median_premium': None, 'detail': '无数据'}

        median_premium = bonds_df['premium_ratio'].median()

        if median_premium < 20:
            score = 40
            detail = '低估区间'
        elif median_premium < 30:
            score = 20
            detail = '正常区间'
        else:
            score = 0
            detail = '高估区间'

        return {
            'score': score,
            'median_premium': round(median_premium, 2),
            'detail': detail,
            'threshold': {'low': 20, 'high': 30},
        }

    def calc_sentiment_score(self, total_volume: float, avg_daily_volume: float = 500) -> dict:
        """
        市场情绪评分（满分25分）
        转债日均成交额 > 600亿得满分；300-600亿得一半；< 300亿得0分
        """
        # total_volume单位为亿
        if total_volume > 600:
            score = 25
            detail = '情绪高涨'
        elif total_volume > 300:
            score = 12.5
            detail = '情绪正常'
        else:
            score = 0
            detail = '情绪低迷'

        return {
            'score': score,
            'total_volume': round(total_volume, 2),
            'detail': detail,
            'threshold': {'low': 300, 'high': 600},
        }

    def calc_liquidity_score(self, bond_yield_10y: float) -> dict:
        """
        市场流动性评分（满分20分）
        10年期国债收益率 < 2.5%得满分；2.5%-3.0%得一半；> 3.0%得0分
        """
        if bond_yield_10y < 2.5:
            score = 20
            detail = '流动性充裕'
        elif bond_yield_10y < 3.0:
            score = 10
            detail = '流动性中性'
        else:
            score = 0
            detail = '流动性收紧'

        return {
            'score': score,
            'bond_yield_10y': round(bond_yield_10y, 2),
            'detail': detail,
            'threshold': {'low': 2.5, 'high': 3.0},
        }

    def calc_macro_score(self, pmi_current: float, pmi_prev: Optional[float] = None) -> dict:
        """
        宏观经济评分（满分15分）
        PMI连续2月 > 50得满分；PMI > 50但仅1个月得一半；PMI < 50得0分
        """
        if pmi_current > 50 and pmi_prev and pmi_prev > 50:
            score = 15
            detail = '经济扩张（确认）'
        elif pmi_current > 50:
            score = 7.5
            detail = '经济扩张（待确认）'
        else:
            score = 0
            detail = '经济收缩'

        return {
            'score': score,
            'pmi_current': pmi_current,
            'pmi_prev': pmi_prev,
            'detail': detail,
            'threshold': 50,
        }

    def calc_total_score(
        self,
        bonds_df: pd.DataFrame,
        total_volume: float,
        bond_yield_10y: float,
        pmi_current: float,
        pmi_prev: Optional[float] = None,
    ) -> TimingSignal:
        """计算综合择时得分"""
        # 计算各因子得分
        valuation = self.calc_valuation_score(bonds_df)
        sentiment = self.calc_sentiment_score(total_volume)
        liquidity = self.calc_liquidity_score(bond_yield_10y)
        macro = self.calc_macro_score(pmi_current, pmi_prev)

        # 加权总分
        total_score = (
            valuation['score'] +
            sentiment['score'] +
            liquidity['score'] +
            macro['score']
        )

        # 确定仓位上限
        position_limit = 0.10
        env_desc = '极端防御'
        for (low, high), config in self.POSITION_MAP.items():
            if low <= total_score <= high:
                position_limit = config['limit']
                env_desc = config['desc']
                break

        # 判断市场环境
        market_env = self._detect_market_env(total_score, bonds_df)
        should_hedge = total_score < 30

        # 趋势确认（需要连续2周确认）
        self._update_trend_confirmation(market_env)

        signal = TimingSignal(
            score=round(total_score, 2),
            position_limit=position_limit,
            market_env=self._trend_confirmed or market_env,
            should_hedge=should_hedge,
            details={
                'valuation': valuation,
                'sentiment': sentiment,
                'liquidity': liquidity,
                'macro': macro,
                'env_desc': env_desc,
            },
            ts=datetime.now(),
        )

        self._last_signal = signal
        self._signal_history.append(signal)

        return signal

    def _detect_market_env(self, score: float, bonds_df: pd.DataFrame) -> str:
        """检测市场环境"""
        if score >= 60:
            return 'bull'
        elif score >= 40:
            return 'neutral'
        else:
            return 'bear'

    def _update_trend_confirmation(self, current_env: str) -> None:
        """更新趋势确认（连续2周确认才切换）"""
        if current_env == self._trend_confirmed:
            self._trend_weeks += 1
        else:
            if self._trend_weeks >= 2:
                self._trend_confirmed = current_env
                self._trend_weeks = 1
            else:
                self._trend_weeks = 1

    def get_position_limit(self, score: float) -> float:
        """根据得分获取仓位上限"""
        for (low, high), config in self.POSITION_MAP.items():
            if low <= score <= high:
                return config['limit']
        return 0.10

    def should_rebalance(self, new_signal: TimingSignal) -> bool:
        """判断是否需要调仓"""
        if not self._last_signal:
            return True

        # 得分变化超过10分触发调仓
        if abs(new_signal.score - self._last_signal.score) > 10:
            return True

        # 仓位上限变化超过20%触发调仓
        if abs(new_signal.position_limit - self._last_signal.position_limit) > 0.2:
            return True

        # 市场环境切换触发调仓
        if new_signal.market_env != self._last_signal.market_env:
            return True

        return False

    @property
    def last_signal(self) -> Optional[TimingSignal]:
        return self._last_signal

    def get_signal_history(self, days: int = 30) -> list[dict]:
        """获取历史择时信号"""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            {
                'score': s.score,
                'position_limit': s.position_limit,
                'market_env': s.market_env,
                'should_hedge': s.should_hedge,
                'ts': s.ts.isoformat(),
            }
            for s in self._signal_history
            if s.ts >= cutoff
        ]
