import pandas as pd
import numpy as np
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class MomentumStrategy(Strategy):
    """动量策略: 选取近期价格涨幅最大的 N 只可转债"""

    name = "动量策略"
    description = "计算过去N个交易日的价格涨幅，选取涨幅最大的可转债，趋势跟踪"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=10, min_val=1, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=10, min_val=5, max_val=30),
        StrategyParam(name="momentum_window", label="动量窗口(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=60, min_val=20, max_val=100),
    ]

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        self._dates = sorted(self._data['date'].unique())

        # Precompute momentum (price change ratio) for each bond
        window = self.get_param('momentum_window')
        self._data = self._data.sort_values(['code', 'date'])
        self._data['prev_price'] = self._data.groupby('code')['price'].shift(window)
        self._data['momentum'] = np.where(
            self._data['prev_price'] > 0,
            (self._data['price'] - self._data['prev_price']) / self._data['prev_price'],
            0
        )

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param('rebalance_days') != 0:
            return None

        day_data = data[data['date'] == current_date].copy()
        momentum_data = self._data[self._data['date'] == current_date].copy()

        if day_data.empty or momentum_data.empty:
            return None

        # Merge momentum into day_data
        day_data = day_data.merge(
            momentum_data[['code', 'momentum']], on='code', how='left'
        )

        # Filter
        day_data = day_data[
            (day_data['premium_ratio'] <= self.get_param('max_premium')) &
            (day_data['price'] > 0) &
            (day_data['momentum'].notna())
        ]

        if day_data.empty:
            return None

        # Pick highest momentum
        selected = day_data.nlargest(self.get_param('hold_count'), 'momentum')

        signals = []
        for _, row in selected.iterrows():
            signals.append({
                'code': row['code'],
                'action': 'buy',
                'price': float(row['price']),
                'reason': f'动量{row["momentum"]*100:.1f}%'
            })

        return signals
