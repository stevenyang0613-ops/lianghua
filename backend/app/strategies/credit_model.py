"""
KMV信用评分模型 V3.0

八维度信用评分（满分100分）：
- 价格隐含违约概率（25分）
- 主体评级（10分）
- 资产负债率（15分）
- 流动比率（15分）
- 经营现金流/有息负债（15分）
- 对外担保比例（8分）
- 大股东质押率（7分）
- 行业景气度（5分）

风控规则：
- ≥80分：单只≤5%
- 60-79分：单只≤2%
- <60分：禁止买入，已持仓次日卖出
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class CreditScore:
    """信用评分结果"""
    total_score: float
    grade: str  # AAA/AA/A/BBB/BB/B/CCC
    risk_level: str  # low/medium/high
    details: dict
    veto: bool  # 是否触发一票否决


class KMVCreditModel:
    """KMV信用评分模型"""

    # 评级对应的分数
    RATING_SCORES = {
        'AAA': 10, 'AA+': 7, 'AA': 5, 'AA-': 3,
        'A+': 2, 'A': 1, 'A-': 0.5,
    }

    # 风险等级阈值
    RISK_THRESHOLDS = {
        'low': 80,
        'medium': 60,
        'high': 0,
    }

    def __init__(self):
        self._industry_pmis: dict[str, float] = {}

    def calc_price_implied_default(
        self,
        bond_price: float,
        pure_bond_value: float,
        stock_price: float,
        net_asset_per_share: float,
        market_cap: float,
        total_debt: float,
    ) -> dict:
        """
        计算价格隐含违约概率（简化KMV模型）
        满分25分
        """
        score = 25.0
        reasons = []

        # Step 1: 计算价格/纯债价值比
        if pure_bond_value > 0:
            price_ratio = bond_price / pure_bond_value
        else:
            price_ratio = 1.0

        # Step 2: 如果价格跌破纯债价值，说明市场认为存在违约风险
        if price_ratio < 0.8:
            deduction = (0.8 - price_ratio) * 50
            score -= deduction
            reasons.append(f"价格/纯债价值比{price_ratio:.2f}<0.8")

        # Step 3: 正股市值/总负债比
        if total_debt > 0:
            debt_coverage = market_cap / total_debt
            if debt_coverage < 0.5:
                score -= 10
                reasons.append(f"市值/负债比{debt_coverage:.2f}<0.5")
        else:
            debt_coverage = float('inf')

        # Step 4: 正股价跌破净资产
        if net_asset_per_share > 0:
            pb_ratio = stock_price / net_asset_per_share
            if pb_ratio < 0.7:
                score -= 5
                reasons.append(f"PB{pb_ratio:.2f}<0.7")

        return {
            'score': max(0, min(25, score)),
            'price_ratio': round(price_ratio, 3) if pure_bond_value > 0 else None,
            'debt_coverage': round(debt_coverage, 2) if total_debt > 0 else None,
            'reasons': reasons,
        }

    def calc_rating_score(self, rating: str) -> dict:
        """
        主体评级评分（满分10分）
        AAA=10, AA+=7, AA=5, AA-=3, A+及以下=0
        """
        score = self.RATING_SCORES.get(rating.upper(), 0)
        return {
            'score': score,
            'rating': rating,
            'max_score': 10,
        }

    def calc_debt_ratio_score(self, asset_liability_ratio: float) -> dict:
        """
        资产负债率评分（满分15分）
        <50%得满分，50-70%得一半，>70%得0分
        """
        if asset_liability_ratio < 50:
            score = 15
            detail = '低负债'
        elif asset_liability_ratio < 70:
            score = 7.5
            detail = '中等负债'
        else:
            score = 0
            detail = '高负债风险'

        return {
            'score': score,
            'ratio': round(asset_liability_ratio, 2),
            'detail': detail,
        }

    def calc_current_ratio_score(self, current_ratio: float) -> dict:
        """
        流动比率评分（满分15分）
        >2得满分，1-2得一半，<1得0分
        """
        if current_ratio > 2:
            score = 15
            detail = '流动性充裕'
        elif current_ratio > 1:
            score = 7.5
            detail = '流动性正常'
        else:
            score = 0
            detail = '流动性风险'

        return {
            'score': score,
            'ratio': round(current_ratio, 2),
            'detail': detail,
        }

    def calc_cashflow_score(
        self,
        operating_cashflow: float,
        interest_bearing_debt: float,
    ) -> dict:
        """
        经营现金流/有息负债评分（满分15分）
        >0.3得满分，0.1-0.3得一半，<0.1得0分
        """
        if interest_bearing_debt > 0:
            ratio = operating_cashflow / interest_bearing_debt
        else:
            ratio = float('inf')

        if ratio > 0.3:
            score = 15
            detail = '偿债能力强'
        elif ratio > 0.1:
            score = 7.5
            detail = '偿债能力一般'
        else:
            score = 0
            detail = '偿债压力'

        return {
            'score': score,
            'ratio': round(ratio, 3) if ratio != float('inf') else None,
            'detail': detail,
        }

    def calc_guarantee_score(self, guarantee_ratio: float) -> dict:
        """
        对外担保比例评分（满分8分）
        <10%得满分，10-30%得一半，>30%得0分
        """
        if guarantee_ratio < 10:
            score = 8
            detail = '担保风险低'
        elif guarantee_ratio < 30:
            score = 4
            detail = '担保风险中等'
        else:
            score = 0
            detail = '担保风险高'

        return {
            'score': score,
            'ratio': round(guarantee_ratio, 2),
            'detail': detail,
        }

    def calc_pledge_score(self, pledge_ratio: float) -> dict:
        """
        大股东质押率评分（满分7分）
        <30%得满分，30-60%得一半，>60%得0分
        """
        if pledge_ratio < 30:
            score = 7
            detail = '质押风险低'
        elif pledge_ratio < 60:
            score = 3.5
            detail = '质押风险中等'
        else:
            score = 0
            detail = '质押风险高'

        return {
            'score': score,
            'ratio': round(pledge_ratio, 2),
            'detail': detail,
        }

    def calc_industry_score(self, industry: str) -> dict:
        """
        行业景气度评分（满分5分）
        基于行业PMI或营收增速排名
        """
        pmi = self._industry_pmis.get(industry, 50)

        if pmi > 55:
            score = 5
            detail = '行业高景气'
        elif pmi > 50:
            score = 3
            detail = '行业景气正常'
        elif pmi > 45:
            score = 1
            detail = '行业景气偏弱'
        else:
            score = 0
            detail = '行业景气低迷'

        return {
            'score': score,
            'industry': industry,
            'pmi': pmi,
            'detail': detail,
        }

    def calc_total_score(
        self,
        bond_price: float,
        pure_bond_value: float,
        stock_price: float,
        net_asset_per_share: float,
        market_cap: float,
        total_debt: float,
        rating: str,
        asset_liability_ratio: float,
        current_ratio: float,
        operating_cashflow: float,
        interest_bearing_debt: float,
        guarantee_ratio: float,
        pledge_ratio: float,
        industry: str,
    ) -> CreditScore:
        """计算综合信用评分"""

        # 计算各维度得分
        implied_default = self.calc_price_implied_default(
            bond_price, pure_bond_value, stock_price,
            net_asset_per_share, market_cap, total_debt
        )
        rating_score = self.calc_rating_score(rating)
        debt_score = self.calc_debt_ratio_score(asset_liability_ratio)
        current_score = self.calc_current_ratio_score(current_ratio)
        cashflow_score = self.calc_cashflow_score(operating_cashflow, interest_bearing_debt)
        guarantee_score = self.calc_guarantee_score(guarantee_ratio)
        pledge_score = self.calc_pledge_score(pledge_ratio)
        industry_score = self.calc_industry_score(industry)

        # 总分
        total = (
            implied_default['score'] +
            rating_score['score'] +
            debt_score['score'] +
            current_score['score'] +
            cashflow_score['score'] +
            guarantee_score['score'] +
            pledge_score['score'] +
            industry_score['score']
        )

        # 确定等级
        if total >= 85:
            grade = 'AAA'
        elif total >= 75:
            grade = 'AA'
        elif total >= 65:
            grade = 'A'
        elif total >= 55:
            grade = 'BBB'
        elif total >= 45:
            grade = 'BB'
        else:
            grade = 'B'

        # 确定风险等级
        if total >= 80:
            risk_level = 'low'
        elif total >= 60:
            risk_level = 'medium'
        else:
            risk_level = 'high'

        return CreditScore(
            total_score=round(total, 2),
            grade=grade,
            risk_level=risk_level,
            details={
                'price_implied': implied_default,
                'rating': rating_score,
                'debt_ratio': debt_score,
                'current_ratio': current_score,
                'cashflow': cashflow_score,
                'guarantee': guarantee_score,
                'pledge': pledge_score,
                'industry': industry_score,
            },
            veto=total < 60,
        )

    def set_industry_pmi(self, industry: str, pmi: float) -> None:
        """设置行业PMI数据"""
        self._industry_pmis[industry] = pmi

    def get_position_limit(self, score: float) -> float:
        """根据信用评分获取持仓上限"""
        if score >= 80:
            return 0.05  # 5%
        elif score >= 60:
            return 0.02  # 2%
        else:
            return 0.0  # 禁止买入
