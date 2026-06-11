"""
因子数据源模块

接入外部数据源：
- 行业PMI数据
- 行业景气度排名
- 大股东质押率
- 对外担保比例
- 财务指标（资产负债率、流动比率、现金流）
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class FactorData:
    """因子数据"""
    code: str
    name: str
    factor_type: str
    factor_value: float
    factor_date: str
    source: str
    confidence: float = 1.0


class FactorDataSource:
    """因子数据源"""

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}
        self._cache_ts: dict[str, datetime] = {}
        self._cache_ttl = timedelta(hours=1)

    def _is_cache_valid(self, key: str) -> bool:
        """检查缓存是否有效"""
        if key not in self._cache_ts:
            return False
        return datetime.now() - self._cache_ts[key] < self._cache_ttl

    # ==================== 行业数据 ====================

    def get_industry_pmi(self, industry: str) -> Optional[float]:
        """
        获取行业PMI数据

        数据来源：国家统计局、财新PMI
        """
        # 实际实现需要接入真实数据源
        # 这里使用模拟数据
        industry_pmi_map = {
            '电子': 52.5,
            '计算机': 54.2,
            '通信': 51.8,
            '医药': 56.3,
            '化工': 49.5,
            '钢铁': 48.2,
            '有色': 50.1,
            '建材': 47.8,
            '机械': 51.5,
            '汽车': 53.2,
            '家电': 55.1,
            '食品饮料': 58.2,
            '纺织服装': 50.5,
            '银行': 62.5,
            '非银金融': 60.8,
            '房地产': 42.5,
            '建筑装饰': 45.2,
        }
        return industry_pmi_map.get(industry, 50.0)

    def get_industry_ranking(self, date: str = None) -> pd.DataFrame:
        """
        获取行业景气度排名

        返回：DataFrame with columns [industry, rank, score, trend]
        """
        industries = [
            '电子', '计算机', '通信', '医药', '化工',
            '钢铁', '有色', '建材', '机械', '汽车',
            '家电', '食品饮料', '纺织服装', '银行', '非银金融',
            '房地产', '建筑装饰',
        ]

        # 基于PMI模拟景气度评分
        scores = []
        for ind in industries:
            pmi = self.get_industry_pmi(ind)
            score = (pmi - 50) * 5 + 50  # 转换为0-100评分
            scores.append({
                'industry': ind,
                'pmi': pmi,
                'score': round(score, 1),
                'trend': 'up' if pmi > 52 else 'down' if pmi < 48 else 'neutral',
            })

        df = pd.DataFrame(scores)
        df = df.sort_values('score', ascending=False).reset_index(drop=True)
        df['rank'] = df.index + 1

        return df

    # ==================== 股东数据 ====================

    def get_shareholder_pledge_ratio(self, code: str) -> Optional[float]:
        """
        获取大股东质押率

        数据来源：中国证券登记结算公司、公告数据
        """
        # 实际实现需要接入真实数据源
        # 这里使用模拟数据
        # 返回质押股份/总股本比例
        return 25.0  # 模拟25%质押率

    def get_guarantee_ratio(self, code: str) -> Optional[float]:
        """
        获取对外担保比例

        数据来源：公司公告、财务报表
        """
        # 实际实现需要接入真实数据源
        # 返回担保金额/净资产比例
        return 15.0  # 模拟15%担保比例

    # ==================== 财务指标 ====================

    def get_financial_indicators(self, code: str) -> dict:
        """
        获取财务指标

        返回：资产负债率、流动比率、现金流等
        """
        # 实际实现需要接入Wind/同花顺等数据源
        # 这里使用模拟数据
        return {
            'asset_liability_ratio': 55.0,  # 资产负债率%
            'current_ratio': 1.5,            # 流动比率
            'quick_ratio': 1.2,              # 速动比率
            'operating_cashflow': 500000000, # 经营现金流（元）
            'interest_bearing_debt': 2000000000,  # 有息负债（元）
            'net_profit_growth': 15.0,       # 净利润增长率%
            'roe': 12.5,                     # ROE%
            'gross_margin': 35.0,            # 毛利率%
        }

    # ==================== 市场数据 ====================

    def get_market_sentiment(self) -> dict:
        """
        获取市场情绪指标
        """
        # 实际实现需要接入真实数据源
        return {
            'advance_decline_ratio': 1.2,    # 涨跌比
            'limit_up_count': 50,            # 涨停数
            'limit_down_count': 10,          # 跌停数
            'turnover_rate': 3.5,            # 换手率%
            'new_high_count': 100,           # 创新高数
            'new_low_count': 30,             # 创新低数
        }

    def get_bond_market_stats(self) -> dict:
        """
        获取转债市场统计
        """
        return {
            'total_count': 500,              # 转债总数
            'avg_premium': 35.5,             # 平均溢价率%
            'median_premium': 28.0,          # 中位数溢价率%
            'avg_price': 120.5,              # 平均价格
            'total_volume': 50000000000,     # 总成交额
            'new_issue_count': 5,            # 新发数量
        }

    # ==================== 因子计算 ====================

    def calc_composite_factor(
        self,
        code: str,
        factor_weights: dict[str, float],
    ) -> float:
        """
        计算综合因子得分

        factor_weights: 各因子权重
        """
        scores = {}

        # 获取各因子数据
        financial = self.get_financial_indicators(code)

        # 财务因子评分
        if financial['asset_liability_ratio'] < 50:
            scores['debt'] = 100
        elif financial['asset_liability_ratio'] < 70:
            scores['debt'] = 50
        else:
            scores['debt'] = 0

        if financial['current_ratio'] > 2:
            scores['liquidity'] = 100
        elif financial['current_ratio'] > 1:
            scores['liquidity'] = 50
        else:
            scores['liquidity'] = 0

        if financial['net_profit_growth'] > 20:
            scores['growth'] = 100
        elif financial['net_profit_growth'] > 0:
            scores['growth'] = 50
        else:
            scores['growth'] = 0

        # 股东因子评分
        pledge = self.get_shareholder_pledge_ratio(code)
        if pledge < 30:
            scores['pledge'] = 100
        elif pledge < 60:
            scores['pledge'] = 50
        else:
            scores['pledge'] = 0

        guarantee = self.get_guarantee_ratio(code)
        if guarantee < 10:
            scores['guarantee'] = 100
        elif guarantee < 30:
            scores['guarantee'] = 50
        else:
            scores['guarantee'] = 0

        # 加权平均
        total_weight = sum(factor_weights.values())
        if total_weight == 0:
            return 50

        composite = sum(
            scores.get(k, 50) * v
            for k, v in factor_weights.items()
        ) / total_weight

        return round(composite, 2)

    def get_factor_exposure(
        self,
        codes: list[str],
        factors: list[str],
    ) -> pd.DataFrame:
        """
        获取多只转债的因子暴露

        返回：DataFrame with index=code, columns=factors
        """
        data = []
        for code in codes:
            row = {'code': code}
            financial = self.get_financial_indicators(code)

            for factor in factors:
                if factor == 'debt':
                    row[factor] = financial['asset_liability_ratio']
                elif factor == 'liquidity':
                    row[factor] = financial['current_ratio']
                elif factor == 'growth':
                    row[factor] = financial['net_profit_growth']
                elif factor == 'roe':
                    row[factor] = financial['roe']
                elif factor == 'pledge':
                    row[factor] = self.get_shareholder_pledge_ratio(code) or 0
                elif factor == 'guarantee':
                    row[factor] = self.get_guarantee_ratio(code) or 0

            data.append(row)

        return pd.DataFrame(data).set_index('code')

    # ==================== 数据更新 ====================

    def update_cache(self, code: str, data: pd.DataFrame) -> None:
        """更新缓存"""
        self._cache[code] = data
        self._cache_ts[code] = datetime.now()

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()
        self._cache_ts.clear()
