import pandas as pd
import numpy as np
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class MultiFactorStrategy(Strategy):
    """多因子策略: 综合双低、溢价率、动量、成交量等多因子评分"""

    name = "多因子策略"
    description = "综合双低值、溢价率、价格动量、成交量等多维度因子加权评分，选取总分最高的可转债"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=10, min_val=1, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="weight_dual_low", label="双低因子权重", type="float", default=0.4, min_val=0, max_val=1),
        StrategyParam(name="weight_premium", label="溢价率权重", type="float", default=0.2, min_val=0, max_val=1),
        StrategyParam(name="weight_momentum", label="动量权重", type="float", default=0.2, min_val=0, max_val=1),
        StrategyParam(name="weight_volume", label="成交量权重", type="float", default=0.1, min_val=0, max_val=1),
        StrategyParam(name="weight_price", label="价格权重", type="float", default=0.1, min_val=0, max_val=1),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=50, min_val=10, max_val=100),
    ]

    def _normalize_rank(self, series: pd.Series, ascending: bool = True) -> pd.Series:
        """将 Series 转换为 0~1 的排名分数"""
        ranks = series.rank(method='average', ascending=ascending)
        max_r = ranks.max()
        if max_r == 0:
            return pd.Series(0.5, index=series.index)
        return (ranks - 1) / max_r

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        self._data['dual_low'] = self._data['price'] + self._data['premium_ratio']

        # Precompute momentum
        window = 20
        self._data = self._data.sort_values(['code', 'date'])
        self._data['prev_price'] = self._data.groupby('code')['price'].shift(window)
        self._data['momentum'] = np.where(
            self._data['prev_price'] > 0,
            (self._data['price'] - self._data['prev_price']) / self._data['prev_price'],
            0
        )

        self._dates = sorted(self._data['date'].unique())

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param('rebalance_days') != 0:
            return None

        day_data = data[data['date'] == current_date].copy()
        factor_data = self._data[self._data['date'] == current_date].copy()

        if day_data.empty or factor_data.empty:
            return None

        # Merge factor data
        day_data = day_data.merge(
            factor_data[['code', 'dual_low', 'momentum']], on='code', how='left'
        )

        # Filter
        max_prem = self.get_param('max_premium')
        day_data = day_data[
            (day_data['premium_ratio'] <= max_prem) &
            (day_data['price'] > 80) &
            (day_data['momentum'].notna()) &
            (day_data['volume'] > 0)
        ]

        if day_data.empty or len(day_data) < self.get_param('hold_count'):
            return None

        # Compute factor scores (0~1 each, lower is better for dual_low and premium)
        score_dual_low = self._normalize_rank(day_data['dual_low'], ascending=True)
        score_premium = self._normalize_rank(day_data['premium_ratio'], ascending=True)
        score_momentum = self._normalize_rank(day_data['momentum'], ascending=False)
        score_volume = self._normalize_rank(day_data['volume'], ascending=False)
        score_price = self._normalize_rank(day_data['price'], ascending=True)  # lower price better

        # Weighted composite score
        w1 = self.get_param('weight_dual_low')
        w2 = self.get_param('weight_premium')
        w3 = self.get_param('weight_momentum')
        w4 = self.get_param('weight_volume')
        w5 = self.get_param('weight_price')
        total_w = w1 + w2 + w3 + w4 + w5

        day_data['score'] = (
            score_dual_low * w1 +
            score_premium * w2 +
            score_momentum * w3 +
            score_volume * w4 +
            score_price * w5
        ) / total_w

        # Pick highest composite score
        selected = day_data.nlargest(self.get_param('hold_count'), 'score')

        signals = []
        for _, row in selected.iterrows():
            signals.append({
                'code': row['code'],
                'action': 'buy',
                'price': float(row['price']),
                'reason': f'评分{row["score"]:.3f}'
            })

        return signals
