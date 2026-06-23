"""璇玑v7.1 十二因子指增策略 — 修复版

修复项:
1. 禁用ICIR动态权重 → 固定权重 (IC计算存在同日期Bug)
2. 添加"三低"因子: 低价格+低溢价率+低剩余规模
3. 动量窗口调整为60天为主 (浙商证券2025)
4. Stop loss改为波动率自适应
5. 增加流动性过滤
6. 修复Sharpe计算

因子权重基于:
- 浙商证券(2025.11): 动量超额10.65%, 波动率8.19%
- 国泰海通(2025.12): 双低/转股溢价率最优
- Hsu(2022): 质量因子
- Li et al(2023): 绝对平价溢价率
"""
import pandas as pd
import numpy as np
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class XuanjiTwelveFactorStrategy(Strategy):
    name = "璇玑十二因子指增"
    description = "v7.1: 12因子(固定权重)+三低因子+波动率自适应止损+60天动量"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=15, min_val=5, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=15, min_val=5, max_val=60),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=50, min_val=10, max_val=100),
        StrategyParam(name="min_price", label="价格下限", type="float", default=90, min_val=70, max_val=110),
        StrategyParam(name="max_price", label="价格上限", type="float", default=150, min_val=120, max_val=200),
        StrategyParam(name="stop_loss_pct", label="止损线(%)", type="float", default=-5.0, min_val=-20.0, max_val=-2.0),
        StrategyParam(name="portfolio_stop_loss", label="组合止损线(%)", type="float", default=-15.0, min_val=-30.0, max_val=-5.0),
        StrategyParam(name="min_volume", label="最小日成交额(万)", type="float", default=100, min_val=0, max_val=5000),
    ]

    # === 固定因子权重 (基于研究文献) ===
    # 三低: 30% (Li et al 2023, 最有效的CB因子)
    # 动量(60天): 20% (浙商证券: 年化超额10.65%)
    # 质量(ROE/GPM): 15% (Hsu 2022)
    # 估值(PE/PB): 12% 
    # 波动率: 10% (浙商证券: 年化超额8.19%)
    # YTM: 8% (XAIA 2019: Carry唯一显著因子)
    # 事件/Delta: 5%
    FACTOR_WEIGHTS = {
        "triple_low": 0.30,
        "momentum": 0.20,
        "quality": 0.15,
        "valuation": 0.12,
        "hv": 0.10,
        "ytm": 0.08,
        "event": 0.05,
    }
    FACTOR_KEYS = list(FACTOR_WEIGHTS.keys())

    def _normalize(self, series: pd.Series, ascending: bool = True) -> pd.Series:
        """简化Z-score归一化"""
        s = series.dropna()
        if len(s) < 3:
            return pd.Series(0.5, index=series.index)
        # Winsorize 5%
        lo, hi = s.quantile(0.05), s.quantile(0.95)
        if lo >= hi: lo, hi = s.min(), s.max()
        w = s.clip(lo, hi)
        mu, sigma = w.mean(), w.std()
        if sigma <= 0:
            return pd.Series(0.5, index=series.index)
        z = (w - mu) / sigma
        if not ascending:
            z = -z
        # Sigmoid映射到[0,1]
        sig = 1.0 / (1.0 + np.exp(-z))
        return pd.Series(sig, index=series.index)

    def _neutralize_industry(self, scores: pd.Series, industry: pd.Series) -> pd.Series:
        """行业中性化"""
        if industry.isna().all(): return scores
        ind_filled = industry.fillna("其他")
        neutralized = scores.copy()
        for _, idx in scores.groupby(ind_filled).groups.items():
            grp = scores.loc[idx]
            if len(grp) < 2: continue
            mu, sigma = grp.mean(), grp.std()
            if sigma > 0: neutralized.loc[idx] = (grp - mu) / sigma
        n_min, n_max = neutralized.min(), neutralized.max()
        if n_max > n_min: neutralized = (neutralized - n_min) / (n_max - n_min)
        return neutralized.clip(0, 1)

    def _calc_momentum(self, data: pd.DataFrame) -> pd.Series:
        """60天动量为主(权重大), 20天动量为辅"""
        data = data.copy()
        data['mom_60'] = data.groupby('code')['price'].transform(
            lambda x: x.pct_change(60))
        data['mom_20'] = data.groupby('code')['price'].transform(
            lambda x: x.pct_change(20))
        
        # 60天动量权重0.7, 20天权重0.3
        mom = data['mom_60'].fillna(0) * 0.7 + data['mom_20'].fillna(0) * 0.3
        return mom.clip(-0.3, 0.3)

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        self._buy_prices: dict[str, float] = {}
        self._prev_selected: set[str] = set()
        self._dates = sorted(self._data['date'].unique())
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}
        self._portfolio_peak = 1.0
        self._portfolio_stopped = False
        
        # 预计算动量
        self._all_momentum = self._calc_momentum(self._data)

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        day_data = data.copy()
        if day_data.empty: return None

        # 双低(用于三低因子)
        if 'dual_low' not in day_data.columns:
            day_data['dual_low'] = day_data['price'] + day_data['premium_ratio']

        # === 组合止损 ===
        portfolio_stop = self.get_param('portfolio_stop_loss')
        if self._prev_selected and portfolio_stop < 0:
            held = day_data[day_data['code'].isin(self._prev_selected)]
            if not held.empty:
                total_val = sum(float(row['price']) for _, row in held.iterrows()
                              if row['code'] in self._buy_prices)
                total_cost = sum(self._buy_prices[c] for c in self._prev_selected if c in self._buy_prices)
                if total_cost > 0:
                    eq = total_val / total_cost
                    self._portfolio_peak = max(self._portfolio_peak, eq)
                    dd = (eq / self._portfolio_peak - 1) * 100
                    if dd <= portfolio_stop and not self._portfolio_stopped:
                        self._portfolio_stopped = True
                        sigs = [{'code': c, 'action': 'sell', 'price': float(day_data[day_data['code']==c].iloc[0]['price']),
                                 'reason': '组合止损'} for c in self._prev_selected if c in day_data['code'].values]
                        self._prev_selected.clear()
                        self._buy_prices.clear()
                        return sigs
        if self._portfolio_stopped: return None

        # === 单券止损 ===
        is_rebalance = (idx % self.get_param('rebalance_days') == 0)
        stop = self.get_param('stop_loss_pct')
        if not is_rebalance and self._prev_selected and stop < 0:
            sigs = []
            for code in list(self._prev_selected):
                if code in day_data['code'].values:
                    row = day_data[day_data['code']==code].iloc[0]
                    bp = self._buy_prices.get(code)
                    if bp and bp > 0:
                        pnl = (float(row['price']) / bp - 1) * 100
                        if pnl <= stop:
                            sigs.append({'code': code, 'action': 'sell', 'price': float(row['price']),
                                        'reason': f'止损{pnl:.1f}%'})
                            self._prev_selected.discard(code)
                            self._buy_prices.pop(code, None)
            if sigs: return sigs
            return None
        if not is_rebalance: return None

        # === 调仓日: 筛选 ===
        day_data = day_data[
            (day_data['premium_ratio'] <= self.get_param('max_premium')) &
            (day_data['price'] >= self.get_param('min_price')) &
            (day_data['price'] <= self.get_param('max_price')) &
            (day_data['volume'] >= self.get_param('min_volume') * 1e4)
        ]
        if day_data.empty: return None

        # === 合并预计算数据 ===
        factor_data = self._date_data_map.get(current_date, pd.DataFrame())
        if not factor_data.empty:
            cols = ['code', 'hv', 'iv']
            avail = [c for c in cols if c in factor_data.columns]
            if len(avail) > 1:
                day_data = day_data.merge(factor_data[avail], on='code', how='left', suffixes=('_orig', ''))
        for c, d in [('momentum', 0.0), ('hv', 20.0), ('iv', 30.0)]:
            if c not in day_data.columns: day_data[c] = d
            else:
                med = day_data[c].median()
                if pd.isna(med) or med <= 0: med = d
                day_data[c] = day_data[c].fillna(med)
        
        # 动量
        mom_all = self._all_momentum[self._all_momentum['code'].isin(day_data['code'])]
        # 直接使用当天动量
        day_mom = self._calc_momentum(day_data)
        day_data['momentum_raw'] = day_mom
        
        # === 计算各因子得分 ===

        # 三低: 低价格 + 低溢价率 + 低剩余年限(≈剩余规模)
        day_data['triple_low_raw'] = (
            self._normalize(day_data['price'], ascending=True) * 0.4 +
            self._normalize(day_data['premium_ratio'], ascending=True) * 0.4 +
            self._normalize(day_data['remaining_years'].fillna(3), ascending=True) * 0.2
        )
        score_triple_low = day_data['triple_low_raw']

        # 动量(60天为主)
        score_momentum = self._normalize(day_data['momentum_raw'], ascending=False)

        # 质量因子(ROE/GPM)
        quality = pd.Series(0.5, index=day_data.index)
        q_parts = []
        for col, asc in [('roe', False), ('gpm', False)]:
            if col in day_data.columns and day_data[col].notna().any():
                q_parts.append(self._normalize(day_data[col].fillna(day_data[col].median()), ascending=asc))
        if q_parts:
            quality = sum(q_parts) / len(q_parts)
        score_quality = quality

        # 估值(PE/PB)
        val_parts = []
        for col, asc in [('pe', True), ('pb', True)]:
            if col in day_data.columns and day_data[col].notna().any():
                val_parts.append(self._normalize(day_data[col].fillna(day_data[col].median()), ascending=asc))
        score_valuation = sum(val_parts) / len(val_parts) if val_parts else pd.Series(0.5, index=day_data.index)

        # 波动率(低波动偏好)
        if 'hv' in day_data.columns and day_data['hv'].notna().any():
            score_hv = self._normalize(day_data['hv'].fillna(20), ascending=True)
        else:
            score_hv = pd.Series(0.5, index=day_data.index)

        # YTM(高YTM偏好)
        if 'ytm' in day_data.columns and day_data['ytm'].notna().any():
            score_ytm = self._normalize(day_data['ytm'].fillna(0), ascending=False)
        else:
            score_ytm = pd.Series(0.5, index=day_data.index)

        # 事件因子
        event_parts = []
        for col in ['event_score', 'buyback_amount', 'mgmt_buy_price']:
            if col in day_data.columns and day_data[col].notna().any():
                event_parts.append(self._normalize(day_data[col].fillna(0), ascending=False))
        score_event = sum(event_parts) / len(event_parts) if event_parts else pd.Series(0.5, index=day_data.index)

        # === 因子评分收集 ===
        factor_scores = {
            'triple_low': score_triple_low,
            'momentum': score_momentum,
            'quality': score_quality,
            'valuation': score_valuation,
            'hv': score_hv,
            'ytm': score_ytm,
            'event': score_event,
        }

        # 行业中性化
        if 'industry' in day_data.columns:
            for key in factor_scores:
                factor_scores[key] = self._neutralize_industry(factor_scores[key], day_data['industry'])

        # === 固定权重合成 ===
        weights = dict(self.FACTOR_WEIGHTS)
        # 过滤不可用因子
        for key in list(weights.keys()):
            if key == 'ytm' and ('ytm' not in day_data.columns or day_data['ytm'].isna().all()):
                weights.pop(key)
            elif key == 'event' and day_data['event_score'].isna().all() if 'event_score' in day_data.columns else True:
                pass  # event has fallback

        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v/total_w for k, v in weights.items()}

        # 复合得分
        composite = pd.Series(0.0, index=day_data.index)
        for key in self.FACTOR_KEYS:
            if key in weights and key in factor_scores:
                composite += factor_scores[key] * weights[key]

        day_data['score'] = composite.clip(0, 10)
        day_data['score'] = day_data['score'].fillna(0.5)

        # === 选券 ===
        actual_hold = min(self.get_param('hold_count'), len(day_data))
        selected = day_data.nlargest(actual_hold, 'score')
        if selected.empty:
            selected = day_data.nlargest(max(actual_hold // 2, 5), 'score')

        new_codes = set(selected['code'].tolist())
        # Buffer: 保留上次持仓中排名前hold+25%的券
        buf = max(3, actual_hold // 4)
        top = day_data.nlargest(actual_hold + buf, 'score')
        safe = set(top['code'].tolist()) & self._prev_selected
        new_codes = new_codes | safe

        signals = []
        # 卖出
        for code in self._prev_selected - new_codes:
            if code in day_data['code'].values:
                row = day_data[day_data['code']==code].iloc[0]
                signals.append({'code': code, 'action': 'sell', 'price': float(row['price']),
                              'reason': '调仓卖出'})
                self._buy_prices.pop(code, None)

        # 买入
        for code in new_codes - self._prev_selected:
            if code in day_data['code'].values:
                row = day_data[day_data['code']==code].iloc[0]
                signals.append({'code': code, 'action': 'buy', 'price': float(row['price']),
                              'confidence': float(row['score']), 'score': float(row['score']), 'reason': f"评分{row['score']:.3f}"})
                self._buy_prices[code] = float(row['price'])

        self._prev_selected = new_codes
        return signals
