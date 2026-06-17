import pandas as pd
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class LowPremiumStrategy(Strategy):
    """低溢价策略: 定期选取溢价率最低的 N 只可转债"""

    name = "低溢价策略"
    description = "定期选取溢价率最低的N只可转债，溢价率越低股性越强，跟随正股上涨弹性越大"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=10, min_val=1, max_val=100),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=30, min_val=5, max_val=80),
        StrategyParam(name="min_price", label="最低价格", type="float", default=90, min_val=80, max_val=150),
    ]

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        # Defensive: ensure required columns exist with safe defaults
        if 'premium_ratio' not in self._data.columns:
            self._data['premium_ratio'] = 15.0
        self._data['premium_ratio'] = self._data['premium_ratio'].fillna(15.0)
        self._dates = sorted(self._data['date'].unique())
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param('rebalance_days') != 0:
            return None

        # data 已是当日行情子集，无需再按日期过滤
        day_data = data.copy()

        # Filter
        day_data = day_data[
            (day_data['premium_ratio'] <= self.get_param('max_premium')) &
            (day_data['price'] >= self.get_param('min_price')) &
            (day_data['price'] > 0)
        ]

        if day_data.empty:
            return None

        # Select bonds with lowest premium ratio
        selected = day_data.nsmallest(self.get_param('hold_count'), 'premium_ratio')
        new_codes = set(selected['code'].tolist())

        signals = []

        # 卖出不再持有的标的
        to_sell = self._prev_selected - new_codes
        if to_sell:
            sell_rows = day_data[day_data['code'].isin(to_sell)]
            signals.extend([
                {'code': code, 'action': 'sell', 'price': float(price), 'reason': '调仓卖出'}
                for code, price in zip(sell_rows['code'], sell_rows['price'])
            ])

        buy_list = selected[['code', 'price', 'premium_ratio']].copy()
        buy_list['reason'] = buy_list['premium_ratio'].apply(lambda x: f'溢价{x:.1f}%')
        signals.extend([
            {'code': code, 'action': 'buy', 'price': float(price), 'reason': reason}
            for code, price, reason in zip(buy_list['code'], buy_list['price'], buy_list['reason'])
        ])

        self._prev_selected = new_codes
        return signals
