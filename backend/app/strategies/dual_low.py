import pandas as pd
import numpy as np
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class DualLowStrategy(Strategy):
    """双低策略: 定期选取双低值最小的 N 只可转债"""

    name = "双低策略"
    description = "定期选取双低值(价格+溢价率×100)最小的N只可转债，持有固定周期后调仓"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=10, min_val=1, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="max_dual_low", label="双低上限", type="float", default=180, min_val=100, max_val=300),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=50, min_val=10, max_val=100),
    ]

    def on_init(self, data: pd.DataFrame) -> None:
        # data 需包含字段: code, date, price, premium_ratio
        self._data = data.copy()
        self._data['dual_low'] = self._data['price'] + self._data['premium_ratio']
        self._dates = sorted(self._data['date'].unique())

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param('rebalance_days') != 0:
            return None

        day_data = data[data['date'] == current_date].copy()

        # 过滤
        day_data = day_data[
            (day_data['dual_low'] <= self.get_param('max_dual_low')) &
            (day_data['premium_ratio'] <= self.get_param('max_premium'))
        ]

        if day_data.empty:
            return None

        # 选取双低最小的 N 只
        selected = day_data.nsmallest(self.get_param('hold_count'), 'dual_low')

        signals = []
        for _, row in selected.iterrows():
            signals.append({
                'code': row['code'],
                'action': 'buy',
                'price': float(row['price']),
                'reason': f'双低{row["dual_low"]:.1f}'
            })

        return signals
