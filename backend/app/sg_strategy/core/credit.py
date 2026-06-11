"""松岗量化可转债策略 V3.0 信用风控模型

8维度信用评分模型(满分100分):
1. 价格隐含违约概率(KMV简化版) - 25分
2. 主体评级 - 10分
3. 资产负债率 - 15分
4. 流动比率 - 15分
5. 经营活动现金流/有息负债 - 15分
6. 对外担保比例 - 8分
7. 大股东质押率 - 7分
8. 行业景气度 - 5分

风控规则:
- ≥80分: 单只≤5%
- 60-79分: 单只≤2%
- <60分: 禁止买入，已持仓次日卖出，永久移出白名单
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional, Tuple
import logging

from app.sg_strategy.core.types import ConvertibleBondData, StockData, CreditScore
from app.sg_strategy.config.settings import params

logger = logging.getLogger(__name__)


class CreditScoringEngine:
    """信用评分引擎"""

    # 评级得分映射
    RATING_SCORES = {
        "AAA": 10.0,
        "AA+": 7.0,
        "AA": 5.0,
        "AA-": 3.0,
        "A+": 1.0,
        "A": 0.5,
        "A-": 0.0,
    }

    def __init__(self):
        """初始化"""
        self._history: Dict[str, List[CreditScore]] = {}

    def calculate_credit_score(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData] = None,
        industry_pmi: float = 50.0,
    ) -> CreditScore:
        """计算信用评分

        Args:
            cb: 可转债数据
            stock: 正股数据
            industry_pmi: 行业PMI

        Returns:
            CreditScore: 信用评分结果
        """
        score = CreditScore(cb_code=cb.code, date=cb.date)

        # 1. 价格隐含违约概率得分 (25分)
        score.implied_default_prob = self._score_implied_default_prob(cb)

        # 2. 主体评级得分 (10分)
        score.issuer_rating = self._score_issuer_rating(cb.issuer_rating)

        # 3. 资产负债率得分 (15分)
        if stock:
            score.debt_ratio = self._score_debt_ratio(stock.debt_ratio)

        # 4. 流动比率得分 (15分)
        if stock:
            score.current_ratio = self._score_current_ratio(stock.current_ratio)

        # 5. 现金流/有息负债得分 (15分)
        if stock:
            score.cf_to_debt = self._score_cf_to_debt(
                stock.operating_cf, stock.total_interest_debt
            )

        # 6. 对外担保比例得分 (8分)
        if stock:
            score.guarantee_ratio = self._score_guarantee_ratio(stock.guarantee_ratio)

        # 7. 大股东质押率得分 (7分)
        if stock:
            score.pledge_ratio = self._score_pledge_ratio(stock.pledge_ratio)

        # 8. 行业景气度得分 (5分)
        score.industry_outlook = self._score_industry_outlook(industry_pmi)

        # 总分
        score.total_score = (
            score.implied_default_prob
            + score.issuer_rating
            + score.debt_ratio
            + score.current_ratio
            + score.cf_to_debt
            + score.guarantee_ratio
            + score.pledge_ratio
            + score.industry_outlook
        )

        # 是否通过(>=60)
        score.is_pass = score.total_score >= params.min_credit_score

        # 保存历史
        if cb.code not in self._history:
            self._history[cb.code] = []
        self._history[cb.code].append(score)

        return score

    def _score_implied_default_prob(self, cb: ConvertibleBondData) -> float:
        """价格隐含违约概率得分(满分25分)

        KMV简化版:
        - 若转债价格 < 纯债价值×0.8 且正股价格 < 每股净资产×0.7: 0分
        - 价格/纯债价值 > 1.0: 25分
        - 线性插值
        """
        if cb.pure_bond_value <= 0:
            return 12.5  # 默认中等分数

        price_to_bond = cb.price_to_bond_ratio

        if price_to_bond <= 0:
            return 0.0

        # 危险信号: 价格严重低于纯债价值
        if price_to_bond < 0.8:
            return 0.0

        # 安全: 价格高于纯债价值
        if price_to_bond >= 1.0:
            return 25.0

        # 线性插值: 0.8-1.0 对应 0-25分
        return (price_to_bond - 0.8) / 0.2 * 25.0

    def _score_issuer_rating(self, rating: str) -> float:
        """主体评级得分(满分10分)

        AAA=10, AA+=7, AA=5, AA-=3, A+=1, A=0.5, A-及以下=0
        """
        return self.RATING_SCORES.get(rating.upper(), 0.0)

    def _score_debt_ratio(self, debt_ratio: float) -> float:
        """资产负债率得分(满分15分)

        - <50%: 满分
        - 50-60%: 12分
        - 60-70%: 8分
        - 70-80%: 4分
        - >80%: 0分
        """
        if debt_ratio <= 0:
            return 7.5  # 数据缺失，给中等分

        if debt_ratio < 50:
            return 15.0
        elif debt_ratio < 60:
            return 12.0
        elif debt_ratio < 70:
            return 8.0
        elif debt_ratio < 80:
            return 4.0
        else:
            return 0.0

    def _score_current_ratio(self, current_ratio: float) -> float:
        """流动比率得分(满分15分)

        - >2.0: 满分
        - 1.5-2.0: 12分
        - 1.0-1.5: 8分
        - 0.5-1.0: 4分
        - <0.5: 0分
        """
        if current_ratio <= 0:
            return 7.5

        if current_ratio >= 2.0:
            return 15.0
        elif current_ratio >= 1.5:
            return 12.0
        elif current_ratio >= 1.0:
            return 8.0
        elif current_ratio >= 0.5:
            return 4.0
        else:
            return 0.0

    def _score_cf_to_debt(
        self,
        operating_cf: float,
        total_interest_debt: float,
    ) -> float:
        """现金流/有息负债得分(满分15分)

        - >1.0: 满分
        - 0.5-1.0: 12分
        - 0.2-0.5: 8分
        - 0-0.2: 4分
        - <0: 0分
        """
        if total_interest_debt <= 0:
            return 10.0  # 无有息负债，给较高分

        if operating_cf <= 0:
            return 0.0

        ratio = operating_cf / total_interest_debt

        if ratio >= 1.0:
            return 15.0
        elif ratio >= 0.5:
            return 12.0
        elif ratio >= 0.2:
            return 8.0
        elif ratio > 0:
            return 4.0
        else:
            return 0.0

    def _score_guarantee_ratio(self, guarantee_ratio: float) -> float:
        """对外担保比例得分(满分8分)

        比例越高，风险越大
        - <10%: 满分
        - 10-30%: 6分
        - 30-50%: 3分
        - >50%: 0分
        """
        if guarantee_ratio < 10:
            return 8.0
        elif guarantee_ratio < 30:
            return 6.0
        elif guarantee_ratio < 50:
            return 3.0
        else:
            return 0.0

    def _score_pledge_ratio(self, pledge_ratio: float) -> float:
        """大股东质押率得分(满分7分)

        质押率越高，风险越大
        - <30%: 满分
        - 30-50%: 5分
        - 50-70%: 2分
        - >70%: 0分
        """
        if pledge_ratio < 30:
            return 7.0
        elif pledge_ratio < 50:
            return 5.0
        elif pledge_ratio < 70:
            return 2.0
        else:
            return 0.0

    def _score_industry_outlook(self, industry_pmi: float) -> float:
        """行业景气度得分(满分5分)

        基于行业PMI
        - >55: 满分
        - 50-55: 4分
        - 45-50: 2分
        - <45: 0分
        """
        if industry_pmi > 55:
            return 5.0
        elif industry_pmi >= 50:
            return 4.0
        elif industry_pmi >= 45:
            return 2.0
        else:
            return 0.0

    def get_position_limit(self, credit_score: CreditScore) -> Tuple[float, str]:
        """根据信用评分获取仓位上限

        Args:
            credit_score: 信用评分

        Returns:
            (仓位上限比例, 说明)
        """
        score = credit_score.total_score

        if score >= 80:
            return params.max_single_position, "优质信用"
        elif score >= 60:
            return params.max_single_position * 0.4, "一般信用"
        else:
            return 0.0, "禁止买入"

    def get_credit_history(
        self,
        cb_code: str,
        days: int = 30,
    ) -> List[CreditScore]:
        """获取信用评分历史

        Args:
            cb_code: 转债代码
            days: 天数

        Returns:
            历史评分列表
        """
        history = self._history.get(cb_code, [])
        return history[-days:] if history else []

    def detect_credit_deterioration(
        self,
        cb_code: str,
        threshold: float = 10.0,
    ) -> bool:
        """检测信用恶化

        Args:
            cb_code: 转债代码
            threshold: 评分下降阈值

        Returns:
            是否恶化
        """
        history = self._history.get(cb_code, [])
        if len(history) < 2:
            return False

        latest = history[-1].total_score
        prev = history[-2].total_score

        return (prev - latest) >= threshold


# 导入Tuple
from typing import Tuple


class EnhancedCreditEngine(CreditScoringEngine):
    """增强版信用评分引擎"""

    def calculate_credit_score(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData] = None,
        industry_pmi: float = 50.0,
    ) -> CreditScore:
        """计算信用评分(增强版)"""
        score = super().calculate_credit_score(cb, stock, industry_pmi)

        # 额外风险检查
        extra_risks = self._check_extra_risks(cb, stock)

        if extra_risks:
            # 发现额外风险，扣分
            score.total_score -= len(extra_risks) * 2
            score.total_score = max(0, score.total_score)
            score.is_pass = score.total_score >= params.min_credit_score
            logger.warning(
                f"[Credit] {cb.code} 额外风险: {extra_risks}, "
                f"评分调整后: {score.total_score:.1f}"
            )

        return score

    def _check_extra_risks(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData],
    ) -> List[str]:
        """检查额外风险

        Args:
            cb: 可转债数据
            stock: 正股数据

        Returns:
            风险列表
        """
        risks = []

        # 1. 检查是否临近到期且价格低于面值
        if cb.remaining_years < 0.5 and cb.close < 100:
            risks.append("临近到期且价格低于面值")

        # 2. 检查正股是否ST
        if stock and stock.is_st:
            risks.append("正股ST")

        # 3. 检查是否有强赎风险
        if cb.forced_call_days > 10:
            risks.append("强赎风险较高")

        # 4. 检查大股东减持
        if cb.has_major_sell:
            risks.append("大股东减持")

        return risks

    def get_credit_alert(
        self,
        cb_code: str,
    ) -> Optional[str]:
        """获取信用预警

        Args:
            cb_code: 转债代码

        Returns:
            预警信息
        """
        history = self._history.get(cb_code, [])
        if not history:
            return None

        latest = history[-1]

        if latest.total_score < 50:
            return f"信用评分过低({latest.total_score:.1f})，建议立即减仓"

        if self.detect_credit_deterioration(cb_code, 15):
            return f"信用评分快速下降，建议关注"

        return None
