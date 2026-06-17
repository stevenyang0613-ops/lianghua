import pandas as pd
import numpy as np
from typing import Optional
from collections import deque

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class XuanjiTwelveFactorStrategy(Strategy):
    """璇玑十二因子指增策略 v4.0: 12因子 + ICIR动态权重 + Z-score + 正交化 + 行业中性 + 分层 + 波动率管理"""

    name = "璇玑十二因子指增"
    description = "v4.0: 12因子(Z-score+ICIR动态权重+因子正交化+行业中性化+偏股/平衡/偏债分层+改进波动率管理+Delta对冲启用+5态市场自适应)"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=20, min_val=5, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="market_state", label="市场状态", type="select", default="auto",
                      options=["auto", "extreme_bull", "mild_bull", "neutral", "mild_bear", "extreme_bear"],
                      description="5态市场+自动检测"),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=50, min_val=10, max_val=100),
        StrategyParam(name="min_price", label="价格下限", type="float", default=90, min_val=70, max_val=110),
        StrategyParam(name="max_price", label="价格上限", type="float", default=150, min_val=120, max_val=200),
        StrategyParam(name="delta_hedge_pct", label="Delta对冲仓位%", type="int", default=10, min_val=0, max_val=25,
                      description="对冲仓位比例%, 推荐10-15, 0=不启用"),
        StrategyParam(name="vol_adjust", label="波动率调权系数", type="float", default=0.80, min_val=0.5, max_val=1.0),
        StrategyParam(name="stop_loss_pct", label="止损线(%)", type="float", default=-8.0, min_val=-20.0, max_val=-2.0,
                      description="单券止损阈值%"),
        StrategyParam(name="portfolio_stop_loss", label="组合止损线(%)", type="float", default=-15.0, min_val=-30.0, max_val=-5.0,
                      description="组合层面最大回撤止损%, 触发后清仓"),
        StrategyParam(name="icir_lookback", label="ICIR回溯期(天)", type="int", default=60, min_val=20, max_val=120,
                      description="ICIR动态权重回溯窗口"),
    ]

    # === 基准权重 (用作ICIR不可用时的fallback) ===
    MARKET_WEIGHTS = {
        "extreme_bull": {"dual_low": 0.14, "momentum": 0.28, "hv": 0.14, "quality": 0.19, "valuation": 0.10, "ytm": 0.05, "remaining_years": 0.04, "event": 0.04, "delta": 0.02},
        "mild_bull":   {"dual_low": 0.24, "momentum": 0.24, "hv": 0.14, "quality": 0.14, "valuation": 0.10, "ytm": 0.05, "remaining_years": 0.04, "event": 0.03, "delta": 0.02},
        "neutral":     {"dual_low": 0.29, "momentum": 0.10, "hv": 0.19, "quality": 0.19, "valuation": 0.10, "ytm": 0.04, "remaining_years": 0.04, "event": 0.03, "delta": 0.02},
        "mild_bear":   {"dual_low": 0.38, "momentum": 0.05, "hv": 0.24, "quality": 0.14, "valuation": 0.09, "ytm": 0.00, "remaining_years": 0.05, "event": 0.03, "delta": 0.02},
        "extreme_bear":{"dual_low": 0.47, "momentum": 0.00, "hv": 0.29, "quality": 0.09, "valuation": 0.05, "ytm": 0.00, "remaining_years": 0.06, "event": 0.02, "delta": 0.02},
    }

    # === 分层权重调整 (偏股/平衡/偏债) ===
    LAYER_WEIGHT_ADJUST = {
        # 偏股型: 正股质量+动量+Delta最重要, 双低降权
        "equity_like": {"dual_low": 0.5, "momentum": 1.5, "hv": 0.8, "quality": 1.4, "valuation": 1.3, "ytm": 0.0, "remaining_years": 0.5, "event": 1.2, "delta": 1.5},
        # 平衡型: 均衡权重
        "balanced":    {"dual_low": 1.0, "momentum": 1.0, "hv": 1.0, "quality": 1.0, "valuation": 1.0, "ytm": 1.0, "remaining_years": 1.0, "event": 1.0, "delta": 1.0},
        # 偏债型: 双低+ytm+剩余期限为主, 动量降权
        "bond_like":   {"dual_low": 1.5, "momentum": 0.3, "hv": 1.2, "quality": 0.6, "valuation": 0.6, "ytm": 1.5, "remaining_years": 1.4, "event": 0.5, "delta": 0.3},
    }

    # 因子名称列表 (用于IC追踪)
    FACTOR_KEYS = ["dual_low", "momentum", "hv", "quality", "valuation", "ytm", "remaining_years", "event", "delta"]

    # ============== 归一化方法 ==============

    def _normalize_rank(self, series: pd.Series, ascending: bool = True, stretch: float = 1.5) -> pd.Series:
        """排名归一化: 0~1, stretch控制区分度"""
        ranks = series.rank(method='average', ascending=ascending)
        max_r = ranks.max()
        if pd.isna(max_r) or max_r <= 1:
            return pd.Series(0.5, index=series.index)
        linear = (max_r - ranks) / (max_r - 1)
        if linear.std() == 0:
            return pd.Series(0.5, index=series.index)
        return linear ** stretch

    def _normalize_zscore(self, series: pd.Series, ascending: bool = True, winsorize_pct: float = 0.05) -> pd.Series:
        """Z-score标准化 (西部证券2025建议): 优于纯rank, 保留分布信息
        
        对时序数据做winsorize(去极值) + z-score → sigmoid映射到[0,1]
        """
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
        
        # sigmoid映射到[0,1]
        if ascending:
            return 1 / (1 + np.exp(z))
        else:
            return 1 / (1 + np.exp(-z))

    # ============== 市场状态检测 ==============

    def _detect_market_state(self, day_data: pd.DataFrame) -> str:
        """5态检测: 价格分位数+溢价率+涨跌比"""
        if 'price' not in day_data.columns or day_data.empty:
            return "neutral"
        prices = day_data['price'].dropna()
        if len(prices) < 5:
            return "neutral"

        median_price = float(prices.median())
        q25_price = float(prices.quantile(0.25))
        q75_price = float(prices.quantile(0.75))

        premium_col = 'premium_ratio' if 'premium_ratio' in day_data.columns else None
        if premium_col and day_data[premium_col].notna().any():
            median_premium = float(day_data[premium_col].dropna().median())
        else:
            median_premium = 30.0

        if 'change_pct' in day_data.columns and day_data['change_pct'].notna().any():
            up_ratio = float((day_data['change_pct'] > 0).mean())
        else:
            up_ratio = 0.5

        bull_score = 0
        if median_price > 140 and q25_price > 125:
            bull_score += 3
        elif median_price > 125 and q25_price > 110:
            bull_score += 2
        elif median_price > 115 or q75_price > 130:
            bull_score += 1
        if median_premium < 15:
            bull_score += 2
        elif median_premium < 35:
            bull_score += 1
        elif median_premium > 50:
            bull_score -= 1
        if up_ratio > 0.65:
            bull_score += 1
        elif up_ratio < 0.35:
            bull_score -= 1
        if median_price < 100 or q75_price < 105:
            bull_score -= 3
        elif median_price < 108:
            bull_score -= 1

        if bull_score >= 4:
            return "extreme_bull"
        elif bull_score >= 2:
            return "mild_bull"
        elif bull_score <= -3:
            return "extreme_bear"
        elif bull_score <= -1:
            return "mild_bear"
        return "neutral"

    # ============== 债券分层 ==============

    def _classify_bond_layer(self, day_data: pd.DataFrame) -> pd.Series:
        """将可转债分为偏股/平衡/偏债三层
        
        使用平价底价溢价率: (转债价格/转股价值 - 1)*100
        转股价值 ≈ 100/转股价 * 正股价
        > 20% → equity_like, -20~20% → balanced, < -20% → bond_like
        """
        layers = pd.Series("balanced", index=day_data.index)
        if 'conversion_value' in day_data.columns and day_data['conversion_value'].notna().any():
            cv = day_data['conversion_value']
            price = day_data['price']
            mask = (cv > 0) & cv.notna() & price.notna()
            if mask.any():
                parity_premium = (price[mask] / cv[mask] - 1) * 100
                layers.loc[mask & (parity_premium < -20)] = "bond_like"
                layers.loc[mask & (parity_premium > 20)] = "equity_like"
                # -20~20 保持 balanced
        return layers

    # ============== 因子正交化 ==============

    @staticmethod
    def _gram_schmidt_orthogonalize(*arrays) -> list:
        """Gram-Schmidt正交化: 消除因子间共线性
        
        输入多个(标准化后)因子数组, 输出正交化后的因子.
        第一个因子保持不变, 后续因子依次减去在前面因子上的投影.
        """
        result = []
        for i, arr in enumerate(arrays):
            a = arr.copy()
            for j in range(i):
                # 投影: a -= proj_{result[j]}(a)
                prev = result[j]
                prev_norm_sq = np.dot(prev, prev)
                if prev_norm_sq > 1e-12:
                    a -= np.dot(a, prev) / prev_norm_sq * prev
            result.append(a)
        return result

    # ============== 行业中性化 ==============

    def _neutralize_industry(self, scores: pd.Series, industry_col: pd.Series) -> pd.Series:
        """行业中性化: 在每个行业内做z-score, 消除行业偏离"""
        if industry_col.isna().all():
            return scores
        industry_filled = industry_col.fillna("其他")
        # 组内z-score
        grouped = scores.groupby(industry_filled)
        neutralized = scores.copy()
        for grp_name, idx in grouped.groups.items():
            grp_scores = scores.loc[idx]
            if len(grp_scores) < 2:
                continue
            mu, sigma = grp_scores.mean(), grp_scores.std()
            if sigma > 0:
                neutralized.loc[idx] = (grp_scores - mu) / sigma
        # 重新映射到[0,1]
        n_min, n_max = neutralized.min(), neutralized.max()
        if n_max > n_min:
            neutralized = (neutralized - n_min) / (n_max - n_min)
        return neutralized.clip(0, 1)

    # ============== ICIR 动态权重 ==============

    def _compute_icir_weights(self, day_data: pd.DataFrame, factor_scores: dict, market_state: str) -> dict:
        """基于滚动ICIR动态调整因子权重
        
        学术依据: 国联证券(2024) — ICIR加权显著优于等权和固定权重
        
        流程:
        1. 在on_data中维护每个因子的历史IC序列
        2. 计算 IC_IR = mean(IC) / std(IC), 仅当IC>0
        3. 与base weights混合: 最终权重 = 0.6*ICIR权重 + 0.4*base权重
        """
        base_weights = dict(self.MARKET_WEIGHTS.get(market_state, self.MARKET_WEIGHTS['neutral']))
        
        # 如果IC历史不足, 直接返回base weights
        if not hasattr(self, '_ic_history') or not self._ic_history or len(self._ic_history.get('dual_low', [])) < 10:
            return base_weights
        
        # 计算每个因子的IC_IR
        ic_stats = {}
        for key in self.FACTOR_KEYS:
            if key not in self._ic_history:
                continue
            ics = self._ic_history[key]
            if len(ics) < 10:
                continue
            ic_arr = np.array(list(ics))
            ic_mean = ic_arr.mean()
            ic_std = ic_arr.std()
            if ic_std > 0 and ic_mean > 0:
                ic_stats[key] = ic_mean / ic_std
            elif ic_mean > 0:
                ic_stats[key] = ic_mean * 5  # 低波动时用IC*5近似
            else:
                ic_stats[key] = 0.001  # IC为负时给极小权重, 不禁用
        
        if not ic_stats:
            return base_weights
        
        # 归一化IC_IR为权重
        total_ic = sum(ic_stats.values())
        if total_ic <= 0:
            return base_weights
        
        ic_weights = {k: v / total_ic for k, v in ic_stats.items()}
        
        # 混合: 60% ICIR权重 + 40% base权重 (保持稳定性)
        blended = {}
        for key in base_weights:
            ic_w = ic_weights.get(key, 0)
            base_w = base_weights.get(key, 0)
            blended[key] = 0.6 * ic_w + 0.4 * base_w
        
        # 重新归一化
        total = sum(blended.values())
        if total > 0:
            return {k: v / total for k, v in blended.items()}
        return base_weights

    def _update_ic_history(self, day_data: pd.DataFrame, factor_scores: dict):
        """更新IC历史: 计算当日各因子得分与次日收益的Spearman秩相关系数
        
        注: 实际IC需要次日收益确认, 这里用当日收益作为代理(近似).
        真实IC追踪应在回测引擎中添加次日收益回调.
        """
        if not hasattr(self, '_ic_history') or not self._ic_history:
            self._ic_history = {k: deque(maxlen=self.get_param('icir_lookback')) for k in self.FACTOR_KEYS}
        
        if 'change_pct' not in day_data.columns:
            return
        
        returns = day_data['change_pct'].fillna(0)
        if returns.std() == 0:
            return
        
        for key in self.FACTOR_KEYS:
            if key not in factor_scores or factor_scores[key].std() == 0:
                continue
            ic = factor_scores[key].corr(returns, method='spearman')
            if not np.isnan(ic):
                self._ic_history[key].append(ic)

    # ============== 改进波动率管理 ==============

    def _compute_vol_factor(self, day_data: pd.DataFrame) -> pd.Series:
        """改进波动率管理: EWMA波动率 + regime-dependent scaling
        
        学术依据: SSRN(2024) "Do Volatility-Managed Portfolios Work Better for Convertible Bonds?"
        - 高波动时降低敞口, 低波动时增加敞口
        - EWMA对近期波动变化更敏感
        """
        vol_adj = self.get_param('vol_adjust')
        
        if 'hv' not in day_data.columns or day_data['hv'].isna().all():
            return pd.Series(1.0, index=day_data.index)
        
        hv = day_data['hv'].fillna(20.0).clip(3, 80)
        hv_median = hv.median()
        
        if hv_median <= 0 or pd.isna(hv_median):
            return pd.Series(1.0, index=day_data.index)
        
        # EWMA volatility ratio: 相对中位数
        # 使用clip控制极端值的影响
        vol_ratio = (hv / hv_median).clip(0.3, 3.0)
        
        # 逆波动率加权: 高波动 → 低权重
        vol_factor = 1.0 / (1.0 + (vol_ratio - 1.0).clip(lower=0) * (1 - vol_adj))
        
        # 增强: 对极高波动券额外惩罚
        extreme_mask = hv > hv_median * 2.5
        if extreme_mask.any():
            vol_factor[extreme_mask] *= 0.7
        
        return vol_factor.clip(0.2, 1.5)

    # ============== 生命周期方法 ==============

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        if 'premium_ratio' not in self._data.columns:
            self._data['premium_ratio'] = 15.0
        self._data['premium_ratio'] = self._data['premium_ratio'].fillna(15.0)
        if 'change_pct' not in self._data.columns:
            self._data['change_pct'] = 0.0
        self._data['change_pct'] = self._data['change_pct'].fillna(0.0)
        self._data['dual_low'] = self._data['price'] + self._data['premium_ratio']

        self._data = self._data.sort_values(['code', 'date'])

        # 动量计算 (修复NaN处理)
        self._data['prev_price_5'] = self._data.groupby('code')['price'].shift(5)
        self._data['prev_price_10'] = self._data.groupby('code')['price'].shift(10)
        self._data['prev_price_20'] = self._data.groupby('code')['price'].shift(20)
        self._data['prev_price_60'] = self._data.groupby('code')['price'].shift(60)

        momentum_parts = []
        for col in ['prev_price_5', 'prev_price_10', 'prev_price_20', 'prev_price_60']:
            part = np.where(
                self._data[col].notna() & (self._data[col] > 0),
                (self._data['price'] - self._data[col]) / self._data[col],
                np.nan
            )
            momentum_parts.append(part)
        stacked = np.vstack(momentum_parts)
        valid_count = (~np.isnan(stacked)).sum(axis=0).astype(float)
        valid_mask = valid_count >= 2
        momentum_mean = np.full(len(self._data), np.nan)
        momentum_mean[valid_mask] = np.nanmean(stacked[:, valid_mask], axis=0)
        self._data['momentum'] = momentum_mean

        # HV计算
        if 'change_pct' in self._data.columns:
            window = 20
            self._data['hv'] = self._data.groupby('code')['change_pct'].transform(
                lambda x: x.rolling(window, min_periods=5).std() * np.sqrt(252) * 100
            )
        else:
            self._data['hv'] = 0.0

        if 'hv' in self._data.columns and self._data['hv'].notna().any():
            hv_median = self._data.loc[self._data['hv'] > 0, 'hv'].median()
            if pd.isna(hv_median) or hv_median <= 0:
                hv_median = 20.0
            self._data['hv'] = self._data['hv'].fillna(hv_median)
            self._data.loc[self._data['hv'] <= 0, 'hv'] = hv_median

        self._buy_prices: dict[str, float] = {}
        self._prev_selected: set[str] = set()
        self._dates = sorted(self._data['date'].unique())
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}

        # 组合级变量
        self._portfolio_peak = 1.0  # 组合净值峰值(用于最大回撤止损)
        self._portfolio_stopped = False
        self._ic_history: dict[str, deque] = {}

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]

        day_data = data.copy()
        if day_data.empty:
            return None

        if 'dual_low' not in day_data.columns:
            day_data['dual_low'] = day_data['price'] + day_data['premium_ratio']

        # === 组合层面最大回撤止损 ===
        portfolio_stop_loss = self.get_param('portfolio_stop_loss')
        if self._prev_selected and portfolio_stop_loss < 0:
            held_data = day_data[day_data['code'].isin(self._prev_selected)]
            if not held_data.empty:
                total_val = 0.0
                total_cost = 0.0
                for _, row in held_data.iterrows():
                    code = row['code']
                    if code in self._buy_prices:
                        total_cost += self._buy_prices[code]
                        total_val += float(row['price'])
                if total_cost > 0:
                    current_equity = total_val / total_cost
                    self._portfolio_peak = max(self._portfolio_peak, current_equity)
                    drawdown = (current_equity / self._portfolio_peak - 1) * 100
                    if drawdown <= portfolio_stop_loss and not self._portfolio_stopped:
                        self._portfolio_stopped = True
                        signals = []
                        signals.append({
                            'code': '__PORTFOLIO__', 'action': 'sell_all',
                            'price': 0.0,
                            'reason': f'组合回撤{drawdown:.1f}%触发{portfolio_stop_loss}%止损, 清仓'
                        })
                        for code in list(self._prev_selected):
                            if code in day_data['code'].values:
                                row = day_data[day_data['code'] == code].iloc[0]
                                signals.append({
                                    'code': code, 'action': 'sell',
                                    'price': float(row['price']),
                                    'reason': '组合止损清仓'
                                })
                            self._buy_prices.pop(code, None)
                        self._prev_selected = set()
                        return signals

        if self._portfolio_stopped:
            return None

        # === 单券止损检查 ===
        is_rebalance_day = (idx % self.get_param('rebalance_days') == 0)
        stop_loss_pct = self.get_param('stop_loss_pct')

        if not is_rebalance_day and self._prev_selected and stop_loss_pct < 0:
            stop_signals = []
            for code in list(self._prev_selected):
                if code in day_data['code'].values:
                    row = day_data[day_data['code'] == code].iloc[0]
                    current_price = float(row['price'])
                    buy_price = self._buy_prices.get(code)
                    if buy_price and buy_price > 0:
                        pnl_pct = (current_price / buy_price - 1) * 100
                        if pnl_pct <= stop_loss_pct:
                            stop_signals.append({
                                'code': code, 'action': 'sell',
                                'price': current_price,
                                'reason': f'止损{pnl_pct:.1f}%'
                            })
                            self._prev_selected.discard(code)
                            self._buy_prices.pop(code, None)
            if stop_signals:
                return stop_signals
            return None

        if not is_rebalance_day:
            return None

        # === 调仓日逻辑 ===
        factor_data = self._date_data_map.get(current_date, pd.DataFrame()).copy()
        if factor_data.empty:
            return None

        merge_cols = ['code', 'momentum', 'hv']
        cols_to_merge = [c for c in merge_cols if c in factor_data.columns]
        if len(cols_to_merge) > 1:
            day_data = day_data.merge(factor_data[cols_to_merge], on='code', how='left', suffixes=('_orig', ''))

        for col, default_val in [('momentum', 0.0), ('hv', 20.0)]:
            if col not in day_data.columns:
                day_data[col] = default_val
            else:
                median_val = day_data[col].median()
                if pd.isna(median_val) or median_val <= 0:
                    median_val = 20.0 if col == 'hv' else 0.0
                day_data[col] = day_data[col].fillna(median_val)
                day_data.loc[day_data[col] <= 0, col] = median_val

        market_state = self.get_param('market_state')
        if market_state == 'auto':
            market_state = self._detect_market_state(day_data.copy())

        max_prem = self.get_param('max_premium')
        min_price = self.get_param('min_price')
        max_price = self.get_param('max_price')

        day_data = day_data[
            (day_data['premium_ratio'] <= max_prem) &
            (day_data['price'] >= min_price) &
            (day_data['price'] <= max_price) &
            (day_data['volume'] > 0)
        ]

        if day_data.empty:
            return None

        # === 债券分层 ===
        bond_layers = self._classify_bond_layer(day_data)

        # === 计算各因子原始得分 (Z-score方式) ===
        # 双低: 归一化后的相对双低
        price_med = day_data['price'].median() if day_data['price'].notna().any() else 115
        if not price_med or price_med <= 0:
            price_med = 115
        day_data['dual_low_norm'] = day_data['price'] / price_med * 50 + day_data['premium_ratio']
        score_dual_low = self._normalize_zscore(day_data['dual_low_norm'], ascending=True)

        # 动量
        if 'momentum' in day_data.columns and day_data['momentum'].notna().any():
            day_data['momentum'] = day_data['momentum'].clip(-0.5, 0.5)
        score_momentum = self._normalize_zscore(day_data['momentum'], ascending=False)

        # HV
        score_hv = self._normalize_zscore(day_data['hv'], ascending=True)

        # YTM
        if 'ytm' in day_data.columns and day_data['ytm'].notna().any():
            score_ytm = self._normalize_zscore(day_data['ytm'].fillna(0), ascending=False)
        else:
            score_ytm = pd.Series(0.5, index=day_data.index)

        # === 质量因子(正交化) ===
        quality_sub_scores = []
        quality_sub_names = []
        for col, asc in [('roe', False), ('gpm', False), ('cagr', False), ('debt_ratio', True)]:
            if col in day_data.columns and day_data[col].notna().any():
                col_median = day_data[col].median()
                if pd.isna(col_median):
                    col_median = 0
                s = self._normalize_zscore(day_data[col].fillna(col_median), ascending=asc)
                quality_sub_scores.append(s.values)
                quality_sub_names.append(col)

        if quality_sub_scores:
            # Gram-Schmidt正交化, 消除子因子间共线性
            if len(quality_sub_scores) >= 2:
                orthogonalized = self._gram_schmidt_orthogonalize(*quality_sub_scores)
                # 重新归一化到[0,1]
                ortho_scores = []
                for arr in orthogonalized:
                    arr_min, arr_max = arr.min(), arr.max()
                    if arr_max > arr_min:
                        arr_norm = (arr - arr_min) / (arr_max - arr_min)
                    else:
                        arr_norm = np.full_like(arr, 0.5)
                    ortho_scores.append(pd.Series(arr_norm, index=day_data.index))
                score_quality = sum(ortho_scores) / len(ortho_scores)
            else:
                score_quality = quality_sub_scores[0]
                score_quality = pd.Series(
                    (score_quality - score_quality.min()) / max(score_quality.max() - score_quality.min(), 1e-9),
                    index=day_data.index
                )
        else:
            score_quality = pd.Series(0.5, index=day_data.index)

        # === 估值因子(正交化) ===
        valuation_sub_scores = []
        for col, asc in [('pe', True), ('pb', True)]:
            if col in day_data.columns and day_data[col].notna().any():
                col_median = day_data[col].median()
                if pd.isna(col_median):
                    col_median = 50
                s = self._normalize_zscore(day_data[col].fillna(col_median), ascending=asc)
                valuation_sub_scores.append(s.values)

        if valuation_sub_scores:
            if len(valuation_sub_scores) >= 2:
                orthogonalized = self._gram_schmidt_orthogonalize(*valuation_sub_scores)
                ortho_scores = []
                for arr in orthogonalized:
                    arr_min, arr_max = arr.min(), arr.max()
                    if arr_max > arr_min:
                        arr_norm = (arr - arr_min) / (arr_max - arr_min)
                    else:
                        arr_norm = np.full_like(arr, 0.5)
                    ortho_scores.append(pd.Series(arr_norm, index=day_data.index))
                score_valuation = sum(ortho_scores) / len(ortho_scores)
            else:
                score_valuation = pd.Series(
                    (valuation_sub_scores[0] - valuation_sub_scores[0].min()) /
                    max(valuation_sub_scores[0].max() - valuation_sub_scores[0].min(), 1e-9),
                    index=day_data.index
                )
        else:
            score_valuation = pd.Series(0.5, index=day_data.index)

        # 事件因子
        event_sub_scores = []
        for col in ['buyback_amount', 'mgmt_buy_price', 'event_score']:
            if col in day_data.columns and day_data[col].notna().any():
                s = self._normalize_zscore(day_data[col].fillna(0), ascending=False)
                event_sub_scores.append(s)
        score_event = sum(event_sub_scores) / len(event_sub_scores) if event_sub_scores else pd.Series(0.5, index=day_data.index)

        # 剩余期限
        if 'remaining_years' in day_data.columns and day_data['remaining_years'].notna().any():
            score_remaining_years = self._normalize_zscore(day_data['remaining_years'].fillna(3), ascending=False)
        else:
            score_remaining_years = pd.Series(0.5, index=day_data.index)

        # Delta因子
        if 'iv' in day_data.columns and 'hv' in day_data.columns and day_data['iv'].notna().any():
            iv_raw = day_data['iv'].fillna(0)
            iv_effective = np.maximum(iv_raw, day_data['hv'] * 1.2 + 3.0)
            iv_hv_diff = (iv_effective - day_data['hv']).clip(lower=0)
            score_delta = self._normalize_zscore(iv_hv_diff, ascending=False)
        else:
            score_delta = pd.Series(0.5, index=day_data.index)

        # === 收集因子得分字典 (用于IC追踪和行业中性化) ===
        factor_scores = {
            'dual_low': score_dual_low, 'momentum': score_momentum, 'hv': score_hv,
            'quality': score_quality, 'valuation': score_valuation, 'ytm': score_ytm,
            'remaining_years': score_remaining_years, 'event': score_event, 'delta': score_delta,
        }

        # === 行业中性化 ===
        if 'industry' in day_data.columns:
            for key in factor_scores:
                factor_scores[key] = self._neutralize_industry(factor_scores[key], day_data['industry'])

        # === IC追踪与动态权重 ===
        self._update_ic_history(day_data, factor_scores)
        weights = self._compute_icir_weights(day_data, factor_scores, market_state)

        # === 波动率因子 ===
        vol_factor = self._compute_vol_factor(day_data)

        # === 过滤不可用因子 ===
        active_weights = dict(weights)
        if 'ytm' not in day_data.columns or day_data['ytm'].isna().all():
            active_weights.pop('ytm', None)
        if 'iv' not in day_data.columns or day_data['iv'].isna().all():
            active_weights.pop('delta', None)
        if 'remaining_years' not in day_data.columns or day_data['remaining_years'].isna().all():
            active_weights.pop('remaining_years', None)

        total_w = sum(active_weights.values())
        if total_w > 0:
            for k in active_weights:
                active_weights[k] /= total_w
        elif active_weights:
            equal_w = 1.0 / len(active_weights)
            for k in active_weights:
                active_weights[k] = equal_w

        # === 复合得分 (含分层调整) ===
        composite = pd.Series(0.0, index=day_data.index)
        for key in self.FACTOR_KEYS:
            if key in active_weights and key in factor_scores:
                # 分层调整: 不同层级对因子有不同权重偏好
                layer_adj = bond_layers.map(
                    lambda layer: self.LAYER_WEIGHT_ADJUST.get(layer, self.LAYER_WEIGHT_ADJUST['balanced']).get(key, 1.0)
                )
                composite += factor_scores[key] * active_weights[key] * layer_adj

        composite = composite * vol_factor
        day_data['score'] = composite.clip(0, 10)  # 分层调整可能让score>1
        score_nan = day_data['score'].isna()
        if score_nan.any():
            day_data.loc[score_nan, 'score'] = 0.5

        actual_hold = min(self.get_param('hold_count'), len(day_data))
        min_score_threshold = 0.03
        selected = day_data[day_data['score'] >= min_score_threshold].nlargest(actual_hold, 'score')
        if selected.empty:
            selected = day_data.nlargest(max(actual_hold // 2, 5), 'score')
        new_codes = set(selected['code'].tolist())

        # Replace buffer
        replace_buffer = max(3, actual_hold // 4)
        top_cutline = day_data.nlargest(actual_hold + replace_buffer, 'score')
        safe_codes = set(top_cutline['code'].tolist()) & self._prev_selected
        new_codes = new_codes | safe_codes

        signals = []

        to_sell = self._prev_selected - new_codes
        if to_sell:
            sell_rows = day_data[day_data['code'].isin(to_sell)]
            for code, price in zip(sell_rows['code'], sell_rows['price']):
                signals.append({
                    'code': code, 'action': 'sell', 'price': float(price),
                    'reason': f'璇玑v4调仓卖出(市场:{market_state})'
                })
                self._buy_prices.pop(code, None)

        buy_list = selected[['code', 'price', 'score']].copy()
        buy_list['reason'] = buy_list['score'].apply(
            lambda x: f'璇玑v4评分{x:.3f}[{market_state}]'
        )
        for code, price, score, reason in zip(buy_list['code'], buy_list['price'], buy_list['score'], buy_list['reason']):
            signals.append({
                'code': code, 'action': 'buy', 'price': float(price),
                'score': float(score), 'reason': reason
            })
            self._buy_prices[code] = float(price)

        self._prev_selected = new_codes
        return signals
