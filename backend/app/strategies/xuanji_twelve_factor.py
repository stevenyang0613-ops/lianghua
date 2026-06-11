import pandas as pd
import numpy as np
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class XuanjiTwelveFactorStrategy(Strategy):
    """璇玑十二因子指增策略: 12因子评分+5态市场自适应+Delta对冲+Alpha叠加"""

    name = "璇玑十二因子指增"
    description = "12因子(双低/HV/动量/YTM/期限/质量ROE/质量GPM/质量CAGR/估值PE/估值PB/事件/Delta)+5态市场自适应权重+波动率调权+Delta对冲候选"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=20, min_val=5, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="market_state", label="市场状态", type="select", default="mild_bull",
                      options=["extreme_bull", "mild_bull", "neutral", "mild_bear", "extreme_bear"],
                      description="5态市场: 极端牛/温和牛/震荡/温和熊/极端熊"),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=50, min_val=10, max_val=100),
        StrategyParam(name="min_price", label="价格下限", type="float", default=90, min_val=70, max_val=110),
        StrategyParam(name="max_price", label="价格上限", type="float", default=150, min_val=120, max_val=200),
        StrategyParam(name="enable_delta_hedge", label="启用Delta对冲", type="select", default="no",
                      options=["yes", "no"]),
        StrategyParam(name="vol_adjust", label="波动率调权系数", type="float", default=0.85, min_val=0.5, max_val=1.0),
    ]

    MARKET_WEIGHTS = {
        "extreme_bull": {"dual_low": 0.15, "momentum": 0.30, "hv": 0.15, "quality": 0.20, "valuation": 0.10, "ytm": 0.05, "event": 0.03, "delta": 0.02},
        "mild_bull":   {"dual_low": 0.25, "momentum": 0.25, "hv": 0.15, "quality": 0.15, "valuation": 0.10, "ytm": 0.05, "event": 0.03, "delta": 0.02},
        "neutral":     {"dual_low": 0.30, "momentum": 0.10, "hv": 0.20, "quality": 0.20, "valuation": 0.10, "ytm": 0.05, "event": 0.03, "delta": 0.02},
        "mild_bear":   {"dual_low": 0.40, "momentum": 0.05, "hv": 0.25, "quality": 0.15, "valuation": 0.10, "ytm": 0.00, "event": 0.03, "delta": 0.02},
        "extreme_bear":{"dual_low": 0.50, "momentum": 0.00, "hv": 0.30, "quality": 0.10, "valuation": 0.05, "ytm": 0.00, "event": 0.03, "delta": 0.02},
    }

    def _normalize_rank(self, series: pd.Series, ascending: bool = True) -> pd.Series:
        ranks = series.rank(method='average', ascending=ascending)
        max_r = ranks.max()
        if max_r == 0 or pd.isna(max_r):
            return pd.Series(0.5, index=series.index)
        return (ranks - 1) / max_r

    def _detect_market_state(self, day_data: pd.DataFrame) -> str:
        if 'price' not in day_data.columns or day_data.empty:
            return "neutral"
        median_price = day_data['price'].median()
        median_premium = day_data.get('premium_ratio', pd.Series([30])).median()
        if median_price > 140 and median_premium < 15:
            return "extreme_bull"
        if median_price > 125 and median_premium < 35:
            return "mild_bull"
        if median_price < 105:
            return "extreme_bear"
        if median_price < 110 or median_premium > 50:
            return "mild_bear"
        return "neutral"

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        self._data['dual_low'] = self._data['price'] + self._data['premium_ratio']

        self._data = self._data.sort_values(['code', 'date'])
        self._data['prev_price_5'] = self._data.groupby('code')['price'].shift(5)
        self._data['prev_price_10'] = self._data.groupby('code')['price'].shift(10)
        self._data['prev_price_20'] = self._data.groupby('code')['price'].shift(20)
        self._data['prev_price_60'] = self._data.groupby('code')['price'].shift(60)

        def _calc_momentum(row):
            parts = []
            for col in ['prev_price_5', 'prev_price_10', 'prev_price_20', 'prev_price_60']:
                if pd.notna(row[col]) and row[col] > 0:
                    parts.append((row['price'] - row[col]) / row[col])
            return np.mean(parts) if parts else 0

        self._data['momentum'] = self._data.apply(_calc_momentum, axis=1)

        if 'change_pct' in self._data.columns:
            window = 20
            self._data['hv'] = self._data.groupby('code')['change_pct'].transform(
                lambda x: x.rolling(window, min_periods=5).std() * np.sqrt(252) * 100
            )
        else:
            self._data['hv'] = 30.0

        self._data['hv'] = self._data['hv'].fillna(30.0)

        self._dates = sorted(self._data['date'].unique())
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param('rebalance_days') != 0:
            return None

        day_data = data.copy()
        if day_data.empty:
            return None

        if 'dual_low' not in day_data.columns:
            day_data['dual_low'] = day_data['price'] + day_data['premium_ratio']

        factor_data = self._date_data_map.get(current_date, pd.DataFrame()).copy()
        if factor_data.empty:
            return None

        merge_cols = ['code', 'momentum', 'hv']
        available_merge = [c for c in merge_cols if c in factor_data.columns]
        if available_merge:
            day_data = day_data.merge(factor_data[available_merge], on='code', how='left')

        max_prem = self.get_param('max_premium')
        min_price = self.get_param('min_price')
        max_price = self.get_param('max_price')

        day_data = day_data[
            (day_data['premium_ratio'] <= max_prem) &
            (day_data['price'] >= min_price) &
            (day_data['price'] <= max_price) &
            (day_data['momentum'].notna()) &
            (day_data['hv'].notna()) &
            (day_data['volume'] > 0)
        ]

        if day_data.empty or len(day_data) < self.get_param('hold_count'):
            return None

        market_state = self.get_param('market_state')
        if market_state == 'mild_bull':
            market_state = self._detect_market_state(day_data)

        weights = self.MARKET_WEIGHTS.get(market_state, self.MARKET_WEIGHTS['neutral'])

        score_dual_low = self._normalize_rank(day_data['dual_low'], ascending=True)
        score_momentum = self._normalize_rank(day_data['momentum'], ascending=False)
        score_hv = self._normalize_rank(day_data['hv'], ascending=True)

        if 'ytm' in day_data.columns:
            score_ytm = self._normalize_rank(day_data['ytm'].fillna(0), ascending=False)
        else:
            score_ytm = pd.Series(0.5, index=day_data.index)

        score_quality = pd.Series(0.5, index=day_data.index)
        for col, asc in [('roe', False), ('gpm', False), ('cagr', False), ('debt_ratio', True)]:
            if col in day_data.columns:
                score_quality = score_quality * 0.7 + self._normalize_rank(day_data[col].fillna(0), ascending=asc) * 0.3

        score_valuation = pd.Series(0.5, index=day_data.index)
        for col, asc in [('pe', True), ('pb', True)]:
            if col in day_data.columns:
                score_valuation = score_valuation * 0.6 + self._normalize_rank(day_data[col].fillna(50), ascending=asc) * 0.4

        score_event = pd.Series(0.5, index=day_data.index)
        for col in ['buyback_amount', 'mgmt_buy_price']:
            if col in day_data.columns:
                score_event = score_event * 0.7 + self._normalize_rank(day_data[col].fillna(0), ascending=False) * 0.3

        score_delta = pd.Series(0.5, index=day_data.index)
        if 'iv' in day_data.columns and 'hv' in day_data.columns:
            iv_hv_diff = (day_data['iv'].fillna(30) - day_data['hv']).clip(lower=0)
            score_delta = self._normalize_rank(iv_hv_diff, ascending=False)

        vol_adj = self.get_param('vol_adjust')
        hv_median = day_data['hv'].median()
        vol_factor = 1.0 / (1.0 + (day_data['hv'] / hv_median - 1.0).clip(lower=0) * (1 - vol_adj))

        composite = (
            score_dual_low * weights['dual_low'] +
            score_momentum * weights['momentum'] +
            score_hv * weights['hv'] +
            score_quality * weights['quality'] +
            score_valuation * weights['valuation'] +
            score_ytm * weights['ytm'] +
            score_event * weights['event'] +
            score_delta * weights['delta']
        ) * vol_factor

        day_data['score'] = composite

        selected = day_data.nlargest(self.get_param('hold_count'), 'score')
        new_codes = set(selected['code'].tolist())

        signals = []

        to_sell = self._prev_selected - new_codes
        if to_sell:
            sell_rows = day_data[day_data['code'].isin(to_sell)]
            signals.extend([
                {'code': code, 'action': 'sell', 'price': float(price), 'reason': f'璇玑调仓卖出(市场:{market_state})'}
                for code, price in zip(sell_rows['code'], sell_rows['price'])
            ])

        buy_list = selected[['code', 'price', 'score']].copy()
        buy_list['reason'] = buy_list['score'].apply(lambda x: f'璇玑评分{x:.3f}[{market_state}]')
        signals.extend([
            {'code': code, 'action': 'buy', 'price': float(price), 'reason': reason}
            for code, price, reason in zip(buy_list['code'], buy_list['price'], buy_list['reason'])
        ])

        self._prev_selected = new_codes
        return signals
