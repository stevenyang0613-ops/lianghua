"""
璇玑×西部 融合策略 V1.0

融合思路:
1. 璇玑多因子模型计算全市场得分
2. 西部一票否决制过滤风险标的
3. 取两个策略的交集(共识最强)
4. 缓冲带机制管理持仓轮换
5. 追踪止损控制回撤
"""

import pandas as pd
import numpy as np
from datetime import date, datetime
from typing import Optional
from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class FusionStrategy(Strategy):
    """璇玑×西部 融合策略"""

    name = "璇玑×西部融合策略"
    description = "v1.0: 璇玑选股 + 西部风控 + 交集共识 + 缓冲带"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=25, min_val=10, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=7, min_val=5, max_val=30),
        StrategyParam(name="xuanji_hold_count", label="璇玑初选数量", type="int", default=40, min_val=20, max_val=80),
        StrategyParam(name="xibu_hold_count", label="西部初选数量", type="int", default=30, min_val=20, max_val=80),
        StrategyParam(name="buffer_size", label="缓冲带大小", type="int", default=3, min_val=0, max_val=10),
        StrategyParam(name="buffer_days", label="缓冲观察天数", type="int", default=3, min_val=1, max_val=7),
        StrategyParam(name="min_credit_score", label="最低信用评分", type="float", default=60, min_val=0, max_val=100),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=60, min_val=10, max_val=150),
        StrategyParam(name="min_price", label="价格下限", type="float", default=90, min_val=70, max_val=110),
        StrategyParam(name="max_price", label="价格上限", type="float", default=150, min_val=120, max_val=200),
        StrategyParam(name="trailing_stop_pct", label="追踪止损(%)", type="float", default=-5.0, min_val=-15.0, max_val=-2.0),
        StrategyParam(name="portfolio_stop_loss", label="组合止损(%)", type="float", default=-15.0, min_val=-30.0, max_val=-5.0),
    ]

    FACTOR_KEYS = ["dual_low", "momentum", "hv", "quality", "valuation", "ytm", "remaining_years", "event", "delta"]

    def _normalize_zscore(self, series, ascending=True, winsorize_pct=0.05):
        s = series.dropna()
        if len(s) < 3:
            return pd.Series(0.5, index=series.index)
        lo = s.quantile(winsorize_pct)
        hi = s.quantile(1 - winsorize_pct)
        if lo >= hi:
            lo, hi = s.min(), s.max()
        w = s.clip(lo, hi)
        mu, sigma = w.mean(), w.std()
        if sigma <= 0:
            return pd.Series(0.5, index=series.index)
        z = (series.clip(lo, hi) - mu) / sigma
        z = z.clip(-3, 3)
        return (1 / (1 + np.exp(-z))) if not ascending else (1 / (1 + np.exp(z)))

    def _estimate_credit_score(self, row):
        score = 100.0
        price = row.get('price')
        if price is None or not np.isfinite(price):
            # 价格缺失时返回中性评分，避免默认100造成误判
            return 50.0
        premium = row.get('premium_ratio', 0)
        ytm = row.get('ytm', 0)
        if price < 80: score -= (80 - price) * 2
        elif price < 90: score -= (90 - price)
        if ytm > 10: score -= (ytm - 10) * 2
        elif ytm > 5: score -= (ytm - 5)
        if premium > 80: score -= (premium - 80) * 0.5
        rating_score = row.get('rating_score', 75)
        return max(0, min(100, score * 0.7 + rating_score * 0.3))

    def _check_veto(self, row):
        credit = self._estimate_credit_score(row)
        if credit < self.get_param('min_credit_score'):
            return False, [f"信用{credit:.0f}不达标"]
        if row.get('premium_ratio', 0) > self.get_param('max_premium'):
            return False, [f"溢价超标"]
        fcd = row.get('forced_call_days', 0)
        if fcd > 0 and fcd < 15:
            return False, [f"强赎倒计时{fcd:.0f}天"]
        price = row.get('price', 0)
        if price <= 0 or price > 300:
            return False, ["价格异常"]
        return True, []

    def _calc_xuanji_scores(self, day_data):
        if day_data.empty:
            return pd.Series(dtype=float)
        pm = day_data['price'].median() if day_data['price'].notna().any() else 115
        day_data['dual_low_norm'] = day_data['price'] / max(pm, 1) * 50 + day_data.get('premium_ratio', 15)
        s_dual = self._normalize_zscore(day_data['dual_low_norm'], ascending=True)
        s_mom = self._normalize_zscore(day_data.get('momentum', pd.Series(0, index=day_data.index)).fillna(0).clip(-0.5, 0.5), ascending=False)
        s_hv = self._normalize_zscore(day_data.get('hv', pd.Series(20, index=day_data.index)).fillna(20), ascending=True)
        # 防御 zero-fill: gpm < 0 视为缺失数据（zero-fill 标记或银行标记 -1，非真实毛利率）
        # 注意：gpm = 0 是可能的真实值（极低毛利），不替换为 NaN
        if 'gpm' in day_data.columns:
            day_data.loc[day_data['gpm'] < 0, 'gpm'] = float('nan')
        qual = []
        for col, asc in [('roe', False), ('gpm', False), ('cagr', False), ('debt_ratio', True)]:
            if col in day_data.columns and day_data[col].notna().any():
                m = day_data[col].median()
                qual.append(self._normalize_zscore(day_data[col].fillna(m if pd.notna(m) else 0), ascending=asc))
        s_qual = sum(qual) / len(qual) if qual else pd.Series(0.5, index=day_data.index)
        val = []
        for col, asc in [('pe', True), ('pb', True)]:
            if col in day_data.columns and day_data[col].notna().any():
                m = day_data[col].median()
                val.append(self._normalize_zscore(day_data[col].fillna(m if pd.notna(m) else 50), ascending=asc))
        s_val = sum(val) / len(val) if val else pd.Series(0.5, index=day_data.index)
        s_ytm = self._normalize_zscore(day_data.get('ytm', pd.Series(0, index=day_data.index)).fillna(0), ascending=False) if 'ytm' in day_data.columns else pd.Series(0.5, index=day_data.index)
        s_rem = self._normalize_zscore(day_data.get('remaining_years', pd.Series(3, index=day_data.index)).fillna(3), ascending=False) if 'remaining_years' in day_data.columns else pd.Series(0.5, index=day_data.index)
        s_evt = pd.Series(0.5, index=day_data.index)
        if 'iv' in day_data.columns and 'hv' in day_data.columns:
            iv_eff = np.maximum(day_data['iv'].fillna(0), day_data['hv'].fillna(20) * 1.2 + 3.0)
            s_delta = self._normalize_zscore((iv_eff - day_data['hv'].fillna(20)).clip(lower=0), ascending=False)
        else:
            s_delta = pd.Series(0.5, index=day_data.index)
        weights = {"dual_low": 0.29, "momentum": 0.10, "hv": 0.19, "quality": 0.19, "valuation": 0.10, "ytm": 0.04, "remaining_years": 0.04, "event": 0.03, "delta": 0.02}
        sc = {'dual_low': s_dual, 'momentum': s_mom, 'hv': s_hv, 'quality': s_qual, 'valuation': s_val, 'ytm': s_ytm, 'remaining_years': s_rem, 'event': s_evt, 'delta': s_delta}
        comp = pd.Series(0.0, index=day_data.index)
        for k, w in weights.items():
            if k in sc:
                comp += sc[k] * w
        return comp.clip(0, 1)

    def on_init(self, data):
        self._data = data.copy()
        for col, dv in [('premium_ratio', 15.0), ('change_pct', 0.0)]:
            if col not in self._data.columns:
                self._data[col] = dv
            self._data[col] = self._data[col].fillna(dv)
        self._data['dual_low'] = self._data['price'] + self._data['premium_ratio']
        self._data = self._data.sort_values(['code', 'date'])
        self._data['prev_price_5'] = self._data.groupby('code')['price'].shift(5)
        self._data['prev_price_20'] = self._data.groupby('code')['price'].shift(20)
        mask5 = self._data['prev_price_5'].notna() & (self._data['prev_price_5'] > 0)
        mask20 = self._data['prev_price_20'].notna() & (self._data['prev_price_20'] > 0)
        self._data['momentum'] = 0.0
        self._data.loc[mask5, 'momentum'] = (self._data.loc[mask5, 'price'] - self._data.loc[mask5, 'prev_price_5']) / self._data.loc[mask5, 'prev_price_5'] * 0.6
        self._data.loc[mask20, 'momentum'] += (self._data.loc[mask20, 'price'] - self._data.loc[mask20, 'prev_price_20']) / self._data.loc[mask20, 'prev_price_20'] * 0.4
        if 'change_pct' in self._data.columns:
            self._data['hv'] = self._data.groupby('code')['change_pct'].transform(lambda x: x.rolling(20, min_periods=5).std() * np.sqrt(252) * 100).fillna(20.0)
        else:
            self._data['hv'] = 20.0
        self._buy_prices: dict[str, float] = {}
        self._peak_prices: dict[str, float] = {}
        self._prev_selected: set[str] = set()
        self._buffer_tracker: dict[str, int] = {}
        # 修复: 统一 date 列为 datetime.date 类型，避免 mixed types 排序失败
        def _norm_date(d):
            if hasattr(d, 'date'):
                return d.date()
            if isinstance(d, str):
                try:
                    return datetime.strptime(d[:10], '%Y-%m-%d').date()
                except Exception as e:
                    logger.debug(f"[FusionStrategy] date parse failed: {e}")
                    return None
            return d if isinstance(d, date) else None
        self._data['date'] = self._data['date'].apply(_norm_date)
        self._data = self._data[self._data['date'].notna()]
        self._dates = sorted(self._data['date'].unique())
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}
        self._portfolio_peak = 1.0
        self._portfolio_stopped = False

    def on_data(self, data, idx):
        dd = data.copy()
        if dd.empty:
            return None
        active_codes = set(dd['code'].values)
        self._buffer_tracker = {k: v for k, v in self._buffer_tracker.items() if k in active_codes}

        # 组合止损
        psl = self.get_param('portfolio_stop_loss')
        if self._prev_selected and psl < 0:
            held = dd[dd['code'].isin(self._prev_selected)]
            if not held.empty:
                ratios = []
                for _, r in held.iterrows():
                    bp = self._buy_prices.get(r['code'], 0)
                    if bp > 0:
                        ratios.append(float(r['price']) / bp)
                if ratios:
                    eq = np.mean(ratios)
                    self._portfolio_peak = max(self._portfolio_peak, eq)
                    if (eq / self._portfolio_peak - 1) * 100 <= psl and not self._portfolio_stopped:
                        self._portfolio_stopped = True
                        # 只返回具体持仓的卖出信号，不推送 __PORTFOLIO__ 伪代码
                        sigs = []
                        for _, r in held.iterrows():
                            sigs.append({'code': r['code'], 'action': 'sell', 'price': float(r['price']), 'reason': '组合止损'})
                        self._prev_selected = set()
                        return sigs
        if self._portfolio_stopped:
            return None

        # 追踪止损
        tsp = self.get_param('trailing_stop_pct')
        if self._prev_selected and tsp < 0:
            stops = []
            for code in list(self._prev_selected):
                if code in dd['code'].values:
                    p = float(dd[dd['code'] == code].iloc[0]['price'])
                    self._peak_prices[code] = max(self._peak_prices.get(code, p), p)
                    peak = self._peak_prices.get(code, p)
                    if peak > 0 and (p / peak - 1) * 100 <= tsp:
                        stops.append({'code': code, 'action': 'sell', 'price': p, 'reason': f'追踪止损{((p/peak-1)*100):.1f}%'})
                        self._prev_selected.discard(code)
                        self._buy_prices.pop(code, None)
                        self._peak_prices.pop(code, None)
            if stops:
                return stops

        # 调仓频率
        if idx % self.get_param('rebalance_days') != 0:
            return None

        # 基础筛选
        dd = dd[(dd['premium_ratio'] <= self.get_param('max_premium')) &
                (dd['price'] >= self.get_param('min_price')) &
                (dd['price'] <= self.get_param('max_price')) &
                (dd['volume'] > 0)]
        if dd.empty:
            return None

        # 一票否决
        vm = pd.Series(True, index=dd.index)
        for i, row in dd.iterrows():
            ok, _ = self._check_veto(row)
            vm[i] = ok
        dd = dd[vm]
        if dd.empty:
            return None

        # 璇玑评分
        xj_scores = self._calc_xuanji_scores(dd)
        dd['xj_score'] = xj_scores
        xj_n = self.get_param('xuanji_hold_count')
        xb_n = self.get_param('xibu_hold_count')
        hold_n = self.get_param('hold_count')

        xj_top = set(dd.nlargest(xj_n, 'xj_score')['code'].tolist())
        dd['xb_score'] = (self._normalize_zscore(dd['dual_low'], True) * 0.4 +
                          self._normalize_zscore(dd.get('momentum', pd.Series(0, index=dd.index)).fillna(0), False) * 0.3 +
                          self._normalize_zscore(dd.get('ytm', pd.Series(0, index=dd.index)).fillna(0), False) * 0.3)
        xb_top = set(dd.nlargest(xb_n, 'xb_score')['code'].tolist())
        consensus = xj_top & xb_top
        if len(consensus) < hold_n:
            consensus = xj_top

        cd = dd[dd['code'].isin(consensus)]
        if cd.empty:
            return None

        ranked = cd.nlargest(min(hold_n + self.get_param('buffer_size'), len(cd)), 'xj_score')
        sigs, nc = [], set()
        bz = self.get_param('buffer_size')
        bd = self.get_param('buffer_days')

        for ri, (ridx, row) in enumerate(ranked.iterrows(), 1):
            code = row['code']
            wh = code in self._prev_selected
            if ri <= hold_n:
                nc.add(code)
                if not wh:
                    sigs.append({'code': code, 'action': 'buy', 'price': float(row['price']),
                                'confidence': float(row['xj_score']),
                                'score': float(row['xj_score']),
                                'reason': f'融合评分{row["xj_score"]:.3f}(#{ri})'})
                    self._buy_prices[code] = float(row['price'])
                    self._peak_prices[code] = float(row['price'])
            elif ri <= hold_n + bz and wh:
                self._buffer_tracker[code] = self._buffer_tracker.get(code, 0) + 1
                if self._buffer_tracker[code] <= bd:
                    nc.add(code)

        to_sell = self._prev_selected - nc
        for code in to_sell:
            r = dd[dd['code'] == code]
            if not r.empty:
                sigs.append({'code': code, 'action': 'sell', 'price': float(r.iloc[0]['price']), 'reason': '调仓'})
                self._buy_prices.pop(code, None)
                self._peak_prices.pop(code, None)

        self._prev_selected = nc
        return sigs if sigs else None
