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
        StrategyParam(name="hold_count", label="持有数量", type="int", default=10, min_val=1, max_val=100),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="max_dual_low", label="双低上限", type="float", default=180, min_val=100, max_val=300),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=50, min_val=10, max_val=100),
    ]

    def on_init(self, data: pd.DataFrame) -> None:
        # data 需包含字段: code, date, price, premium_ratio
        self._data = data.copy()
        # Defensive: ensure required columns exist with safe defaults
        if 'premium_ratio' not in self._data.columns:
            self._data['premium_ratio'] = 15.0  # reasonable default
        self._data['premium_ratio'] = self._data['premium_ratio'].fillna(15.0)
        self._data['dual_low'] = self._data['price'] + self._data['premium_ratio']
        self._dates = sorted(self._data['date'].unique())
        # 预构建日期索引，避免 on_data 中 O(n) 过滤
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param('rebalance_days') != 0:
            return None

        day_data = self._date_data_map.get(current_date, pd.DataFrame()).copy()

        # 过滤
        filter_mask = (
            (day_data['dual_low'] <= self.get_param('max_dual_low')) &
            (day_data['premium_ratio'] <= self.get_param('max_premium'))
        )

        # 添加条款过滤: 排除已公告强赎/即将强赎的转债
        if 'is_called' in day_data.columns:
            filter_mask = filter_mask & (~day_data['is_called'].fillna(False))
        if 'call_status' in day_data.columns:
            status_mask = day_data['call_status'].fillna('').str.contains('强赎|赎回', na=False)
            filter_mask = filter_mask & (~status_mask)
        if 'forced_call_days' in day_data.columns:
            # 强赎倒计时不足 3 日视为不可交易
            call_days = day_data['forced_call_days'].fillna(999)
            filter_mask = filter_mask & ((call_days >= 3) | (call_days > 900))
        # 排查可交换债
        if 'code' in day_data.columns:
            eb_codes = day_data['code'].str.match(r'^(EB|132|133)', na=False)
            filter_mask = filter_mask & (~eb_codes)
        if 'name' in day_data.columns:
            eb_names = day_data['name'].str.contains('可交换债', na=False)
            filter_mask = filter_mask & (~eb_names)

        day_data = day_data[filter_mask]

        if day_data.empty:
            return None

        # 选取双低最小的 N 只
        selected = day_data.nsmallest(self.get_param('hold_count'), 'dual_low')
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

        buy_list = selected[['code', 'price', 'dual_low']].copy()
        buy_list['reason'] = buy_list['dual_low'].apply(lambda x: f'双低{x:.1f}')
        signals.extend([
            {'code': code, 'action': 'buy', 'price': float(price), 'reason': reason}
            for code, price, reason in zip(buy_list['code'], buy_list['price'], buy_list['reason'])
        ])

        self._prev_selected = new_codes
        return signals
