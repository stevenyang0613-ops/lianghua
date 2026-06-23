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
        StrategyParam(name="hold_count", label="持有数量", type="int", default=10, min_val=1, max_val=100),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=10, min_val=5, max_val=30),
        StrategyParam(name="momentum_window", label="动量窗口(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=60, min_val=20, max_val=100),
    ]

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        # Defensive: ensure required columns exist with safe defaults
        if 'premium_ratio' not in self._data.columns:
            self._data['premium_ratio'] = 15.0
        self._data['premium_ratio'] = self._data['premium_ratio'].fillna(15.0)
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

        # 预构建日期索引，避免 on_data 中 O(n) 过滤
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param('rebalance_days') != 0:
            return None

        # data 已是当日行情子集，无需再按日期过滤
        day_data = data.copy()
        momentum_data = self._date_data_map.get(current_date, pd.DataFrame()).copy()

        if day_data.empty or momentum_data.empty:
            return None

        # Merge momentum into day_data
        if 'momentum' not in momentum_data.columns and 'price' in day_data.columns:
            # 无预计算动量时，用当日价格近似（所有 code momentum=0，靠其他因子排序）
            momentum_data['momentum'] = 0.0
        day_data = day_data.merge(
            momentum_data[['code', 'momentum']], on='code', how='left'
        )

        # Early return if merge produced no valid momentum (all codes unmatched)
        if 'momentum' not in day_data.columns or day_data['momentum'].isna().all():
            return None

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

        buy_list = selected[['code', 'price', 'momentum']].copy()
        buy_list['reason'] = buy_list['momentum'].apply(lambda x: f'动量{x*100:.1f}%')
        signals.extend([
            {'code': code, 'action': 'buy', 'price': float(price), 'reason': reason}
            for code, price, reason in zip(buy_list['code'], buy_list['price'], buy_list['reason'])
        ])

        self._prev_selected = new_codes
        return signals
