"""西部量化可转债策略 V3.0 七维打分引擎

核心逻辑：转债价格 = 债底价值 + 转股价值 + 期权价值 + 波动率溢价
正股七维评分占 55%，转债自身评分占 45%

正股七维(55分):
- 短期动量(16.5分): Z-score(涨幅)×0.4 + Z-score(量比)×0.3 + Z-score(换手率)×0.3
- 板块情绪(9.9分): 板块涨幅排名 + 板块涨停家数/成分股数
- 技术面(9.9分): 突破级别 + 均线形态 + MACD周线趋势
- 筹码面(6.6分): 获利盘比例 + 筹码集中度
- 波动率(6.6分): 隐含波动率分位数 + 历史波动率分位数 + 波动率偏度
- 消息面(3.85分): 行业政策 + 公司公告 + 转债条款消息
- 基本面(1.65分): 净利润增速 + 经营现金流/营收比

转债自身(45分):
- 估值指标(17.1分): 转股溢价率
- 条款价值(10.8分): 下修概率得分
- 流动性(9.0分): 三档打分，与AUM分档联动
- 信用评分(8.1分): 信用模型得分折算

性能优化:
- Numba加速数值计算
- 向量化批量处理
- 结果缓存
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional, Tuple
from functools import lru_cache
import numpy as np
import pandas as pd
import logging

try:
    from numba import jit, prange
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    prange = range

from app.xb_strategy.core.types import (
    ConvertibleBondData, StockData, SevenDimScore, CreditScore, DownwardRevisionScore
)
from app.xb_strategy.config.settings import params
from app.xb_strategy.config.weights import MarketRegime, get_weight_scheme, WeightScheme

logger = logging.getLogger(__name__)


# ============ 性能优化函数 ============

@jit(nopython=True, cache=True)
def _zscore_numba(arr: np.ndarray) -> np.ndarray:
    """Numba加速的Z-score计算"""
    mean = np.mean(arr)
    std = np.std(arr)
    if std == 0 or np.isnan(std):
        return np.zeros_like(arr)
    return (arr - mean) / std


@jit(nopython=True, cache=True)
def _percentile_rank_numba(arr: np.ndarray) -> np.ndarray:
    """Numba加速的百分位排名计算"""
    n = len(arr)
    result = np.zeros(n)
    sorted_indices = np.argsort(arr)
    for i in range(n):
        result[sorted_indices[i]] = (i + 1) / n
    return result


@jit(nopython=True, parallel=True, cache=True)
def _batch_score_numba(
    changes: np.ndarray,
    volume_ratios: np.ndarray,
    turnover_rates: np.ndarray,
    premiums: np.ndarray,
) -> np.ndarray:
    """批量计算得分核心部分"""
    n = len(changes)
    scores = np.zeros(n)

    for i in prange(n):
        # 动量得分
        change_score = 0.4 if changes[i] > 5 else 0.35 if changes[i] > 2 else 0.25 if changes[i] > 0 else 0.15 if changes[i] > -2 else 0.05
        volume_score = 0.3 if volume_ratios[i] > 3 else 0.25 if volume_ratios[i] > 2 else 0.2 if volume_ratios[i] > 1.5 else 0.15 if volume_ratios[i] > 1 else 0.1
        turnover_score = 0.3 if turnover_rates[i] > 10 else 0.25 if turnover_rates[i] > 5 else 0.2 if turnover_rates[i] > 3 else 0.15 if turnover_rates[i] > 1 else 0.1
        momentum = (change_score + volume_score + turnover_score) * 16.5

        # 估值得分
        valuation = 17.1 if premiums[i] < 15 else 17.1 * 0.5 if premiums[i] < 25 else 0.0

        scores[i] = momentum + valuation

    return scores


def zscore(series: pd.Series) -> pd.Series:
    """计算Z-score (支持Numba加速)"""
    arr = series.values.astype(np.float64)
    if NUMBA_AVAILABLE and len(arr) > 100:
        result = _zscore_numba(arr)
        return pd.Series(result, index=series.index)
    else:
        mean = series.mean()
        std = series.std()
        if std == 0 or pd.isna(std):
            return pd.Series(0.0, index=series.index)
        return (series - mean) / std


def percentile_rank(series: pd.Series) -> pd.Series:
    """计算百分位排名(0-1) (支持Numba加速)"""
    arr = series.values.astype(np.float64)
    if NUMBA_AVAILABLE and len(arr) > 100:
        result = _percentile_rank_numba(arr)
        return pd.Series(result, index=series.index)
    return series.rank(pct=True)


class SevenDimScoringEngine:
    """七维打分引擎"""

    # 正股七维满分
    STOCK_TOTAL_SCORE = 55.0

    # 各维度满分
    DIM_SHORT_MOMENTUM = 16.5
    DIM_SECTOR_SENTIMENT = 9.9
    DIM_TECHNICAL = 9.9
    DIM_CHIP_STRUCTURE = 6.6
    DIM_VOLATILITY = 6.6
    DIM_NEWS_FACTOR = 3.85
    DIM_FUNDAMENTALS = 1.65

    # 转债自身满分
    CB_TOTAL_SCORE = 45.0

    # 转债各维度满分
    DIM_VALUATION = 17.1
    DIM_CLAUSE_VALUE = 10.8
    DIM_LIQUIDITY = 9.0
    DIM_CREDIT = 8.1

    def __init__(
        self,
        regime: MarketRegime = MarketRegime.RANGE,
        aum: float = 10000.0,
    ):
        """初始化打分引擎

        Args:
            regime: 市场环境
            aum: 资产规模(万元)
        """
        self.regime = regime
        self.aum = aum
        self.weight_scheme = get_weight_scheme(regime)

    def score_bond(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData] = None,
        credit_score: Optional[CreditScore] = None,
        revision_score: Optional[DownwardRevisionScore] = None,
    ) -> SevenDimScore:
        """计算单只可转债的七维得分

        Args:
            cb: 可转债数据
            stock: 正股数据
            credit_score: 信用评分
            revision_score: 下修概率评分

        Returns:
            SevenDimScore: 七维打分结果
        """
        score = SevenDimScore(cb_code=cb.code, date=cb.date)

        # 1. 计算正股七维得分
        if stock:
            score.short_momentum = self._score_short_momentum(stock)
            score.sector_sentiment = self._score_sector_sentiment(stock)
            score.technical = self._score_technical(stock)
            score.chip_structure = self._score_chip_structure(stock)
            score.volatility = self._score_volatility(cb, stock)
            score.news_factor = self._score_news_factor(stock)
            score.fundamentals = self._score_fundamentals(stock)
        else:
            # 正股数据缺失时，给予中性分(60%满分)
            # 数据缺失时不应给出高分，避免掩盖风险
            score.short_momentum = self.DIM_SHORT_MOMENTUM * 0.60
            score.sector_sentiment = self.DIM_SECTOR_SENTIMENT * 0.60
            score.technical = self.DIM_TECHNICAL * 0.60
            score.chip_structure = self.DIM_CHIP_STRUCTURE * 0.60
            score.volatility = self.DIM_VOLATILITY * 0.60
            score.news_factor = self.DIM_NEWS_FACTOR * 0.60
            score.fundamentals = self.DIM_FUNDAMENTALS * 0.60
            logger.warning(f"[Scoring] {cb.code} 正股数据缺失，使用中性分数(60%)并标记风险")

        score.stock_total = (
            score.short_momentum
            + score.sector_sentiment
            + score.technical
            + score.chip_structure
            + score.volatility
            + score.news_factor
            + score.fundamentals
        )

        # 2. 计算转债自身得分
        score.valuation = self._score_valuation(cb)
        score.clause_value = self._score_clause_value(cb, revision_score)
        score.liquidity = self._score_liquidity(cb)
        score.credit = self._score_credit(credit_score)

        score.cb_total = (
            score.valuation
            + score.clause_value
            + score.liquidity
            + score.credit
        )

        # 3. 计算综合得分
        scheme = self.weight_scheme
        score.total_score = (
            score.stock_total * scheme.stock_weight
            + score.cb_total * scheme.cb_weight
        )

        return score

    def _score_short_momentum(self, stock: StockData) -> float:
        """计算短期动量得分(满分16.5分)

        计算: Z-score(涨幅)×0.4 + Z-score(量比)×0.3 + Z-score(换手率)×0.3
        然后归一化到满分
        """
        # 涨幅贡献 (0-40%)
        change_score = 0.0
        if stock.change_pct > 5:
            change_score = 0.4
        elif stock.change_pct > 2:
            change_score = 0.35
        elif stock.change_pct > 0:
            change_score = 0.25
        elif stock.change_pct > -2:
            change_score = 0.15
        else:
            change_score = 0.05

        # 量比贡献 (0-30%)
        volume_score = 0.0
        if stock.volume_ratio > 3:
            volume_score = 0.3
        elif stock.volume_ratio > 2:
            volume_score = 0.25
        elif stock.volume_ratio > 1.5:
            volume_score = 0.2
        elif stock.volume_ratio > 1:
            volume_score = 0.15
        else:
            volume_score = 0.1

        # 换手率贡献 (0-30%)
        turnover_score = 0.0
        if stock.turnover_rate > 10:
            turnover_score = 0.3
        elif stock.turnover_rate > 5:
            turnover_score = 0.25
        elif stock.turnover_rate > 3:
            turnover_score = 0.2
        elif stock.turnover_rate > 1:
            turnover_score = 0.15
        else:
            turnover_score = 0.1

        # 合并得分
        raw_score = change_score + volume_score + turnover_score
        return min(raw_score * self.DIM_SHORT_MOMENTUM, self.DIM_SHORT_MOMENTUM)

    def _score_sector_sentiment(self, stock: StockData) -> float:
        """计算板块情绪得分(满分9.9分)

        计算: 板块涨幅排名百分位 + 板块涨停家数/成分股数
        """
        score = 0.0

        # 板块涨幅贡献
        if stock.sector_change_pct > 3:
            score += 0.5
        elif stock.sector_change_pct > 1:
            score += 0.4
        elif stock.sector_change_pct > 0:
            score += 0.3
        elif stock.sector_change_pct > -1:
            score += 0.2
        else:
            score += 0.1

        # 板块涨停家数贡献
        if stock.sector_total_count > 0:
            limit_up_ratio = stock.sector_limit_up_count / stock.sector_total_count
            if limit_up_ratio > 0.1:
                score += 0.5
            elif limit_up_ratio > 0.05:
                score += 0.4
            elif limit_up_ratio > 0.02:
                score += 0.3
            elif limit_up_ratio > 0:
                score += 0.2
            else:
                score += 0.1
        else:
            score += 0.2  # 默认分

        return min(score * self.DIM_SECTOR_SENTIMENT, self.DIM_SECTOR_SENTIMENT)

    def _score_technical(self, stock: StockData) -> float:
        """计算技术面得分(满分9.9分)

        包括: 突破级别 + 均线形态 + MACD周线趋势
        """
        score = 0.0

        # 突破级别(0-40%)
        if stock.breakthrough_level >= 3:
            score += 0.4
        elif stock.breakthrough_level == 2:
            score += 0.3
        elif stock.breakthrough_level == 1:
            score += 0.2
        else:
            score += 0.1

        # 均线形态(0-35%): 价格在主要均线上方
        if stock.close > stock.ma5 > stock.ma10 > stock.ma20:
            score += 0.35  # 多头排列
        elif stock.close > stock.ma20:
            score += 0.25  # 站上20日线
        elif stock.close > stock.ma60:
            score += 0.2  # 站上60日线
        else:
            score += 0.1

        # MACD趋势(0-25%)
        if stock.macd_hist > 0 and stock.macd > stock.macd_signal:
            score += 0.25  # 金叉且红柱
        elif stock.macd_hist > 0:
            score += 0.2  # 红柱
        elif stock.macd > stock.macd_signal:
            score += 0.15  # 金叉
        else:
            score += 0.1

        return min(score * self.DIM_TECHNICAL, self.DIM_TECHNICAL)

    def _score_chip_structure(self, stock: StockData) -> float:
        """计算筹码面得分(满分6.6分)

        包括: 获利盘比例 + 筹码集中度(股东户数变化率)
        """
        score = 0.0

        # 获利盘比例(0-60%)
        if stock.profit_ratio > 80:
            score += 0.6
        elif stock.profit_ratio > 60:
            score += 0.5
        elif stock.profit_ratio > 40:
            score += 0.4
        elif stock.profit_ratio > 20:
            score += 0.3
        else:
            score += 0.2

        # 股东户数变化率(负值表示集中度提高)(0-40%)
        if stock.shareholder_change_pct < -10:
            score += 0.4  # 高度集中
        elif stock.shareholder_change_pct < -5:
            score += 0.35
        elif stock.shareholder_change_pct < 0:
            score += 0.3
        elif stock.shareholder_change_pct < 5:
            score += 0.25
        else:
            score += 0.15

        return min(score * self.DIM_CHIP_STRUCTURE, self.DIM_CHIP_STRUCTURE)

    def _score_volatility(
        self,
        cb: ConvertibleBondData,
        stock: StockData,
    ) -> float:
        """计算波动率得分(满分6.6分)

        包括: 隐含波动率分位数 + 历史波动率分位数 + 波动率偏度
        中等偏高的波动率+正偏度=最佳期权属性
        """
        score = 0.0

        # 隐含波动率分位数(0-3分)
        iv_pct = cb.implied_vol_percentile
        if iv_pct is None:
            score += 1.5  # 数据缺失时给中性分
        elif params.iv_percentile_low <= iv_pct <= params.iv_percentile_high:
            score += 3.0  # 中等分位最佳
        elif params.iv_percentile_low * 0.5 <= iv_pct < params.iv_percentile_low:
            score += 1.5
        elif params.iv_percentile_high < iv_pct <= params.iv_percentile_high * 1.125:
            score += 1.5
        else:
            score += 0.0  # 极端分位

        # 历史波动率分位数(0-2分)
        hv_pct = stock.hist_vol_percentile
        if hv_pct is None:
            score += 1.0  # 数据缺失时给中性分
        elif params.hv_percentile_low <= hv_pct <= params.hv_percentile_high:
            score += 2.0
        elif params.hv_percentile_low * 0.5 <= hv_pct < params.hv_percentile_low:
            score += 1.0
        elif params.hv_percentile_high < hv_pct <= params.hv_percentile_high * 1.3:
            score += 1.0
        else:
            score += 0.0

        # 波动率偏度(0-1.6分)
        # 正偏度意味着上涨弹性好
        vol_skew = cb.vol_skew
        if vol_skew is None:
            score += 0.8  # 数据缺失时给中性分
        elif vol_skew > 0:
            score += 1.6
        elif vol_skew > -0.5:
            score += 0.8
        else:
            score += 0.0

        return min(score, self.DIM_VOLATILITY)

    def _score_news_factor(self, stock: StockData) -> float:
        """计算消息面得分(满分3.85分)

        包括: 行业政策 + 公司公告
        注: 需要外部数据支持，当前返回中性分
        """
        # TODO: 接入新闻情绪分析数据源
        # 实际应结合新闻情绪分析、行业政策、公司公告等
        return self.DIM_NEWS_FACTOR * 0.5  # 中性分，等待外部数据

    def _score_fundamentals(self, stock: StockData) -> float:
        """计算基本面得分(满分1.65分)

        包括: 净利润增速 + 经营现金流/营收比
        """
        score = 0.0

        # 净利润增速(0-60%)
        if stock.net_profit_yoy > 30:
            score += 0.6
        elif stock.net_profit_yoy > 10:
            score += 0.45
        elif stock.net_profit_yoy > 0:
            score += 0.3
        elif stock.net_profit_yoy > -10:
            score += 0.2
        else:
            score += 0.1

        # 现金流/有息负债(0-40%)
        if stock.total_interest_debt > 0:
            cf_ratio = stock.operating_cf / stock.total_interest_debt
            if cf_ratio > 1:
                score += 0.4
            elif cf_ratio > 0.5:
                score += 0.35
            elif cf_ratio > 0.2:
                score += 0.25
            else:
                score += 0.15
        else:
            score += 0.3

        return min(score * self.DIM_FUNDAMENTALS, self.DIM_FUNDAMENTALS)

    def _score_valuation(self, cb: ConvertibleBondData) -> float:
        """计算估值指标得分(满分17.1分)

        转股溢价率打分:
        - <15%: 满分
        - 15-25%: 一半
        - >25%: 0分
        """
        premium = cb.conversion_premium

        if premium < params.conversion_premium_tier1:
            return self.DIM_VALUATION
        elif premium < params.conversion_premium_tier2:
            return self.DIM_VALUATION * 0.5
        else:
            return 0.0

    def _score_clause_value(
        self,
        cb: ConvertibleBondData,
        revision_score: Optional[DownwardRevisionScore] = None,
    ) -> float:
        """计算条款价值得分(满分10.8分)

        主要来自下修概率得分
        """
        score = 0.0

        # 下修概率贡献
        if revision_score:
            # 下修概率得分转换为条款价值得分
            revision_contribution = (revision_score.total_score / 100) * 0.8
            score += revision_contribution * self.DIM_CLAUSE_VALUE
        else:
            # 默认基于转债属性估算
            if cb.remaining_years < 1:
                score += self.DIM_CLAUSE_VALUE * 0.3
            elif cb.remaining_years < 2:
                score += self.DIM_CLAUSE_VALUE * 0.5
            else:
                score += self.DIM_CLAUSE_VALUE * 0.3

        return min(score, self.DIM_CLAUSE_VALUE)

    def _score_liquidity(self, cb: ConvertibleBondData) -> float:
        """计算流动性得分(满分9.0分)

        三档打分，与AUM分档联动
        """
        daily_amount = cb.daily_amount_20d
        threshold = params.get_liquidity_threshold(self.aum)

        if daily_amount >= threshold * 4:
            return self.DIM_LIQUIDITY  # 满分
        elif daily_amount >= threshold * 2:
            return self.DIM_LIQUIDITY * 0.75
        elif daily_amount >= threshold:
            return self.DIM_LIQUIDITY * 0.5
        else:
            return self.DIM_LIQUIDITY * 0.25

    def _score_credit(self, credit_score: Optional[CreditScore]) -> float:
        """计算信用得分(满分8.1分)

        基于信用评分模型结果
        """
        if credit_score is None:
            return self.DIM_CREDIT * 0.5  # 数据缺失时给中性分，避免高估

        # 信用评分映射(0-100 -> 0-8.1)
        return credit_score.total_score / 100 * self.DIM_CREDIT

    def score_all_bonds(
        self,
        bonds: List[ConvertibleBondData],
        stocks: Optional[Dict[str, StockData]] = None,
        credit_scores: Optional[Dict[str, CreditScore]] = None,
        revision_scores: Optional[Dict[str, DownwardRevisionScore]] = None,
    ) -> List[SevenDimScore]:
        """批量计算所有可转债的七维得分

        Args:
            bonds: 可转债列表
            stocks: 正股数据字典
            credit_scores: 信用评分字典
            revision_scores: 下修概率评分字典

        Returns:
            七维得分列表
        """
        scores = []

        for cb in bonds:
            stock = stocks.get(cb.stock_code) if stocks else None
            credit = credit_scores.get(cb.code) if credit_scores else None
            revision = revision_scores.get(cb.code) if revision_scores else None

            score = self.score_bond(cb, stock, credit, revision)
            scores.append(score)

        # 按总分排序并设置排名
        scores.sort(key=lambda x: x.total_score, reverse=True)
        for i, s in enumerate(scores):
            s.rank = i + 1

        return scores

    def update_regime(self, regime: MarketRegime) -> None:
        """更新市场环境

        Args:
            regime: 新的市场环境
        """
        self.regime = regime
        self.weight_scheme = get_weight_scheme(regime)
        logger.info(f"[Scoring] 市场环境更新: {regime.value}")

    def score_all_bonds_optimized(
        self,
        bonds: List[ConvertibleBondData],
        stocks: Optional[Dict[str, StockData]] = None,
        credit_scores: Optional[Dict[str, CreditScore]] = None,
        revision_scores: Optional[Dict[str, DownwardRevisionScore]] = None,
    ) -> List[SevenDimScore]:
        """批量计算所有可转债的七维得分 (优化版本)

        使用Numba加速和向量化操作，适合大批量计算

        Args:
            bonds: 可转债列表
            stocks: 正股数据字典
            credit_scores: 信用评分字典
            revision_scores: 下修概率评分字典

        Returns:
            七维得分列表
        """
        n = len(bonds)
        if n == 0:
            return []

        # 预分配数组
        changes = np.zeros(n)
        volume_ratios = np.ones(n)
        turnover_rates = np.zeros(n)
        premiums = np.zeros(n)

        for i, cb in enumerate(bonds):
            stock = stocks.get(cb.stock_code) if stocks else None
            if stock:
                changes[i] = stock.change_pct
                volume_ratios[i] = stock.volume_ratio
                turnover_rates[i] = stock.turnover_rate
            premiums[i] = cb.conversion_premium

        # 使用Numba加速批量计算
        if NUMBA_AVAILABLE and n > 50:
            base_scores = _batch_score_numba(changes, volume_ratios, turnover_rates, premiums)
        else:
            base_scores = np.zeros(n)
            for i, cb in enumerate(bonds):
                stock = stocks.get(cb.stock_code) if stocks else None
                if stock:
                    base_scores[i] = self._score_short_momentum(stock)
                base_scores[i] += self._score_valuation(cb)

        # 创建得分对象
        scores = []
        for i, cb in enumerate(bonds):
            stock = stocks.get(cb.stock_code) if stocks else None
            credit = credit_scores.get(cb.code) if credit_scores else None
            revision = revision_scores.get(cb.code) if revision_scores else None

            score = self.score_bond(cb, stock, credit, revision)
            scores.append(score)

        # 按总分排序并设置排名
        scores.sort(key=lambda x: x.total_score, reverse=True)
        for i, s in enumerate(scores):
            s.rank = i + 1

        return scores

    @lru_cache(maxsize=1000)
    def _get_cached_score(
        self,
        cb_code: str,
        date_str: str,
        premium: float,
        remaining_years: float,
    ) -> Tuple[float, float, float]:
        """缓存转债基础得分

        Args:
            cb_code: 转债代码
            date_str: 日期字符串
            premium: 转股溢价率
            remaining_years: 剩余期限

        Returns:
            (估值得分, 条款价值得分, 流动性得分)
        """
        # 创建临时对象计算
        class TempCB:
            def __init__(self, premium, remaining_years):
                self.conversion_premium = premium
                self.remaining_years = remaining_years
                self.daily_amount_20d = 5000.0
                self.implied_vol_percentile = 50.0
                self.vol_skew = 0.0

        temp_cb = TempCB(premium, remaining_years)
        valuation = self._score_valuation(temp_cb)
        clause = self._score_clause_value(temp_cb, None)
        liquidity = self._score_liquidity(temp_cb)

        return (valuation, clause, liquidity)


class BatchScoringEngine(SevenDimScoringEngine):
    """批量打分引擎 - 支持DataFrame输入"""

    def score_from_dataframe(
        self,
        cb_df: pd.DataFrame,
        stock_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """从DataFrame计算七维得分

        Args:
            cb_df: 可转债数据DataFrame
            stock_df: 正股数据DataFrame

        Returns:
            包含七维得分的DataFrame
        """
        results = []

        for _, cb_row in cb_df.iterrows():
            cb = ConvertibleBondData(
                code=cb_row.get("code", ""),
                name=cb_row.get("name", ""),
                stock_code=cb_row.get("stock_code", ""),
                stock_name=cb_row.get("stock_name", ""),
                date=cb_row.get("date", date.today()),
                close=cb_row.get("close", 0),
                conversion_premium=cb_row.get("premium_ratio", 0),
                remaining_years=cb_row.get("remaining_years", 0),
                daily_amount_20d=cb_row.get("daily_amount_20d", cb_row.get("volume", 0) * 100),
                implied_vol_percentile=cb_row.get("implied_vol_percentile", 50),
                vol_skew=cb_row.get("vol_skew", 0),
            )

            stock = None
            if stock_df is not None:
                stock_data = stock_df[stock_df["code"] == cb.stock_code]
                if not stock_data.empty:
                    s = stock_data.iloc[0]
                    stock = StockData(
                        code=s.get("code", ""),
                        date=s.get("date", date.today()),
                        close=s.get("close", 0),
                        change_pct=s.get("change_pct", 0),
                        volume_ratio=s.get("volume_ratio", 1),
                        turnover_rate=s.get("turnover_rate", 0),
                        sector_change_pct=s.get("sector_change_pct", 0),
                        sector_limit_up_count=s.get("sector_limit_up_count", 0),
                        sector_total_count=s.get("sector_total_count", 1),
                    )

            score = self.score_bond(cb, stock)
            results.append(score.to_dict())

        return pd.DataFrame(results)
