import pandas as pd
import numpy as np
from typing import Optional
from collections import deque
import logging

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam

logger = logging.getLogger(__name__)


class XuanjiTwelveFactorStrategy(Strategy):
    """璇玑十二因子指增策略 v5.0: 
    新增: 一票否决制 + 缓冲带机制 + 追踪止损 + 流动性过滤 + 周频调仓
    """

    name = "璇玑十二因子指增"
    description = "v5.0: 12因子 + ICIR动态权重 + 正交化 + 行业中性 + 分层 + 波动率管理 + 一票否决 + 缓冲带 + 追踪止损"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=20, min_val=5, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=7, min_val=5, max_val=60),
        StrategyParam(name="market_state", label="市场状态", type="select", default="auto",
                      options=["auto", "extreme_bull", "mild_bull", "neutral", "mild_bear", "extreme_bear"]),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=50, min_val=10, max_val=100),
        StrategyParam(name="min_price", label="价格下限", type="float", default=90, min_val=70, max_val=110),
        StrategyParam(name="max_price", label="价格上限", type="float", default=150, min_val=120, max_val=200),
        StrategyParam(name="delta_hedge_pct", label="Delta对冲仓位%", type="int", default=10, min_val=0, max_val=25),
        StrategyParam(name="vol_adjust", label="波动率调权系数", type="float", default=0.80, min_val=0.5, max_val=1.0),
        StrategyParam(name="stop_loss_pct", label="止损线(%)", type="float", default=-8.0, min_val=-20.0, max_val=-2.0),
        StrategyParam(name="trailing_stop_pct", label="追踪止损(%)", type="float", default=-5.0, min_val=-15.0, max_val=-2.0),
        StrategyParam(name="portfolio_stop_loss", label="组合止损线(%)", type="float", default=-15.0, min_val=-30.0, max_val=-5.0),
        StrategyParam(name="icir_lookback", label="ICIR回溯期(天)", type="int", default=60, min_val=20, max_val=120),
        StrategyParam(name="buffer_size", label="缓冲带大小", type="int", default=3, min_val=0, max_val=10),
        StrategyParam(name="buffer_days", label="缓冲观察天数", type="int", default=3, min_val=1, max_val=7),
        StrategyParam(name="min_credit_score", label="最低信用评分", type="float", default=60, min_val=0, max_val=100),
        StrategyParam(name="min_liquidity", label="最小成交额(万元)", type="float", default=500, min_val=0, max_val=5000),
    ]

    MARKET_WEIGHTS = {
        "extreme_bull": {"dual_low": 0.14, "momentum": 0.28, "hv": 0.14, "quality": 0.19, "valuation": 0.10, "ytm": 0.05, "remaining_years": 0.04, "event": 0.04, "delta": 0.02},
        "mild_bull":   {"dual_low": 0.24, "momentum": 0.24, "hv": 0.14, "quality": 0.14, "valuation": 0.10, "ytm": 0.05, "remaining_years": 0.04, "event": 0.03, "delta": 0.02},
        "neutral":     {"dual_low": 0.29, "momentum": 0.10, "hv": 0.19, "quality": 0.19, "valuation": 0.10, "ytm": 0.04, "remaining_years": 0.04, "event": 0.03, "delta": 0.02},
        "mild_bear":   {"dual_low": 0.38, "momentum": 0.05, "hv": 0.24, "quality": 0.14, "valuation": 0.09, "ytm": 0.00, "remaining_years": 0.05, "event": 0.03, "delta": 0.02},
        "extreme_bear":{"dual_low": 0.47, "momentum": 0.00, "hv": 0.29, "quality": 0.09, "valuation": 0.05, "ytm": 0.00, "remaining_years": 0.06, "event": 0.02, "delta": 0.02},
    }

    LAYER_WEIGHT_ADJUST = {
        "equity_like": {"dual_low": 0.5, "momentum": 1.5, "hv": 0.8, "quality": 1.4, "valuation": 1.3, "ytm": 0.0, "remaining_years": 0.5, "event": 1.2, "delta": 1.5},
        "balanced":    {"dual_low": 1.0, "momentum": 1.0, "hv": 1.0, "quality": 1.0, "valuation": 1.0, "ytm": 1.0, "remaining_years": 1.0, "event": 1.0, "delta": 1.0},
        "bond_like":   {"dual_low": 1.5, "momentum": 0.3, "hv": 1.2, "quality": 0.6, "valuation": 0.6, "ytm": 1.5, "remaining_years": 1.4, "event": 0.5, "delta": 0.3},
    }

    FACTOR_KEYS = ["dual_low", "momentum", "hv", "quality", "valuation", "ytm", "remaining_years", "event", "delta"]

    # ============== 归一化 ==============

    def _normalize_rank(self, series: pd.Series, ascending: bool = True, stretch: float = 1.5) -> pd.Series:
        ranks = series.rank(method='average', ascending=ascending)
        max_r = ranks.max()
        if pd.isna(max_r) or max_r <= 1:
            return pd.Series(0.5, index=series.index)
        linear = (max_r - ranks) / (max_r - 1)
        if linear.std() == 0:
            return pd.Series(0.5, index=series.index)
        return linear ** stretch

    def _normalize_zscore(self, series: pd.Series, ascending: bool = True, winsorize_pct: float = 0.05) -> pd.Series:
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
        if ascending:
            return 1 / (1 + np.exp(z))
        else:
            return 1 / (1 + np.exp(-z))

    # ============== 一票否决制（v5.0 新增）==============

    def _check_veto(self, row: pd.Series) -> tuple[bool, list[str]]:
        """一票否决检查，满足任意一条直接排除"""
        reasons = []
        passed = True

        # 1. 信用评分
        credit_score = self._estimate_credit_score(row)
        min_cs = self.get_param('min_credit_score')
        if credit_score < min_cs:
            passed = False
            reasons.append(f"信用{credit_score:.0f}<{min_cs}")

        # 2. 溢价率
        max_prem = self.get_param('max_premium')
        if row.get('premium_ratio', 0) > max_prem:
            passed = False
            reasons.append(f"溢价{row['premium_ratio']:.0f}%>{max_prem}%")

        # 3. 强赎风险
        fcd = row.get('forced_call_days', 0)
        if fcd > 0 and fcd < 15:
            passed = False
            reasons.append(f"强赎倒计时{fcd:.0f}天")

        # 4. 剩余期限
        rem = row.get('remaining_years', 3)
        if rem < 0.5:
            passed = False
            reasons.append(f"剩余期限{rem*12:.0f}月<6月")

        # 5. 流动性
        min_liq = self.get_param('min_liquidity')
        volume = row.get('volume', 0)  # 手数
        if volume < min_liq:
            passed = False
            reasons.append(f"成交{volume:.0f}手<{min_liq}")

        # 6. 价格有效性
        price = row.get('price', 0)
        if price <= 0 or price > 300:
            passed = False
            reasons.append(f"价格异常{price}")

        return passed, reasons

    def _estimate_credit_score(self, row: pd.Series) -> float:
        """估算信用评分"""
        score = 100.0
        price = row.get('price', 100)
        premium = row.get('premium_ratio', 0)
        ytm = row.get('ytm', 0)
        dual_low = row.get('dual_low', 150)

        if price < 80:
            score -= (80 - price) * 2
        elif price < 90:
            score -= (90 - price)
        if dual_low < 100:
            score -= (100 - dual_low) * 0.5
        if ytm > 10:
            score -= (ytm - 10) * 2
        elif ytm > 5:
            score -= (ytm - 5)
        if premium > 80:
            score -= (premium - 80) * 0.5

        # 评级加分
        rating_score = row.get('rating_score', 75)
        score = score * 0.7 + rating_score * 0.3

        return max(0, min(100, score))

    # ============== 市场状态检测 ==============

    def _detect_market_state(self, day_data: pd.DataFrame) -> str:
        if 'price' not in day_data.columns or day_data.empty:
            return "neutral"
        prices = day_data['price'].dropna()
        if len(prices) < 5:
            return "neutral"

        median_price = float(prices.median())
        q25_price = float(prices.quantile(0.25))

        premium_col = 'premium_ratio' if 'premium_ratio' in day_data.columns else None
        median_premium = float(day_data[premium_col].dropna().median()) if premium_col and day_data[premium_col].notna().any() else 30.0

        up_ratio = float((day_data['change_pct'] > 0).mean()) if 'change_pct' in day_data.columns and day_data['change_pct'].notna().any() else 0.5

        bull_score = 0
        if median_price > 140 and q25_price > 125:
            bull_score += 3
        elif median_price > 125 and q25_price > 110:
            bull_score += 2
        elif median_price > 115:
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
        if median_price < 100:
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
        layers = pd.Series("balanced", index=day_data.index)
        if 'conversion_value' in day_data.columns and day_data['conversion_value'].notna().any():
            cv = day_data['conversion_value']
            price = day_data['price']
            mask = (cv > 0) & cv.notna() & price.notna()
            if mask.any():
                # 使用 pandas Series 保持索引对齐，避免 numpy array 与 Series 的广播问题
                _pp_values = np.where(cv[mask] > 0, (price[mask] / cv[mask] - 1) * 100, 0.0)
                parity_premium = pd.Series(_pp_values, index=day_data.index[mask])
                layers.loc[mask & (parity_premium < -20)] = "bond_like"
                layers.loc[mask & (parity_premium > 20)] = "equity_like"
        return layers

    # ============== 因子正交化 ==============

    @staticmethod
    def _gram_schmidt_orthogonalize(*arrays) -> list:
        if not arrays:
            return []
        expected_len = len(arrays[0])
        for i, arr in enumerate(arrays):
            if len(arr) != expected_len:
                raise ValueError(f"Gram-Schmidt: array[{i}] length mismatch")

        clean_arrays = []
        for arr in arrays:
            a = np.array(arr, dtype=float)
            if not np.isfinite(a).all():
                median_val = np.median(a[np.isfinite(a)]) if np.any(np.isfinite(a)) else 0.0
                a = np.where(np.isfinite(a), a, median_val)
            clean_arrays.append(a)

        result = []
        for i, arr in enumerate(clean_arrays):
            a = arr.copy()
            for j in range(i):
                prev = result[j]
                prev_norm_sq = np.dot(prev, prev)
                if prev_norm_sq > 1e-12:
                    a -= np.dot(a, prev) / prev_norm_sq * prev
            if np.allclose(a, 0) or not np.isfinite(a).all():
                a = arr - arr.mean()
                std = arr.std()
                if std > 1e-12:
                    a = a / std
                else:
                    a = np.zeros_like(arr)
            result.append(a)
        return result

    # ============== 行业中性化 ==============

    def _neutralize_industry(self, scores: pd.Series, industry_col: pd.Series) -> pd.Series:
        if industry_col.isna().all():
            return scores
        industry_filled = industry_col.fillna("其他")
        grouped = scores.groupby(industry_filled)
        neutralized = scores.copy()
        for grp_name, idx in grouped.groups.items():
            grp_scores = scores.loc[idx]
            if len(grp_scores) < 2:
                continue
            mu, sigma = grp_scores.mean(), grp_scores.std()
            if sigma > 0:
                neutralized.loc[idx] = (grp_scores - mu) / sigma
        n_min, n_max = neutralized.min(), neutralized.max()
        if n_max > n_min:
            neutralized = (neutralized - n_min) / (n_max - n_min)
        return neutralized.clip(0, 1)

    # ============== ICIR 动态权重 ==============

    def _compute_icir_weights(self, day_data: pd.DataFrame, factor_scores: dict, market_state: str) -> dict:
        base_weights = dict(self.MARKET_WEIGHTS.get(market_state, self.MARKET_WEIGHTS['neutral']))

        if not hasattr(self, '_ic_history') or not self._ic_history:
            return base_weights

        MIN_IC_HISTORY = 5
        max_history = max(len(v) for v in self._ic_history.values())
        if max_history < MIN_IC_HISTORY:
            return base_weights

        ic_stats = {}
        for key in self.FACTOR_KEYS:
            if key not in self._ic_history:
                continue
            ics = self._ic_history[key]
            if len(ics) < MIN_IC_HISTORY:
                continue
            ic_arr = np.array(list(ics))
            ic_mean = ic_arr.mean()
            ic_std = ic_arr.std() if len(ic_arr) > 1 else 0.0
            if ic_std > 0:
                icir = abs(ic_mean) / ic_std
                ic_stats[key] = round(icir, 4)
            elif ic_mean != 0:
                # 历史不足但方向稳定，给予中等权重
                ic_stats[key] = abs(ic_mean) * 5
            else:
                ic_stats[key] = 0.001

        if not ic_stats:
            return base_weights

        total_ic = sum(ic_stats.values())
        if total_ic <= 0:
            return base_weights

        ic_weights = {k: v / total_ic for k, v in ic_stats.items()}

        blended = {}
        for key in base_weights:
            ic_w = ic_weights.get(key, 0)
            base_w = base_weights.get(key, 0)
            blended[key] = 0.6 * ic_w + 0.4 * base_w

        total = sum(blended.values())
        if total > 0:
            return {k: v / total for k, v in blended.items()}
        return base_weights

    def _update_ic_history(self, day_data: pd.DataFrame, factor_scores: dict):
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

    # ============== 波动率管理 ==============

    def _compute_vol_factor(self, day_data: pd.DataFrame) -> pd.Series:
        vol_adj = self.get_param('vol_adjust')
        if 'hv' not in day_data.columns or day_data['hv'].isna().all():
            return pd.Series(1.0, index=day_data.index)

        hv = day_data['hv'].fillna(20.0).clip(3, 80)
        hv_median = hv.median()
        if hv_median <= 0 or pd.isna(hv_median):
            return pd.Series(1.0, index=day_data.index)

        vol_ratio = (hv / hv_median).clip(0.3, 3.0)
        vol_factor = 1.0 / (1.0 + (vol_ratio - 1.0).clip(lower=0) * (1 - vol_adj))
        extreme_mask = hv > hv_median * 2.5
        if extreme_mask.any():
            vol_factor[extreme_mask] *= 0.7

        return vol_factor.clip(0.2, 1.5)

    # ============== 缓冲带机制（v5.0 新增）==============

    def _should_hold_with_buffer(self, code: str, rank: int, was_held: bool) -> tuple[bool, str]:
        hold_count = self.get_param('hold_count')
        buffer_size = self.get_param('buffer_size')
        buffer_days = self.get_param('buffer_days')

        if rank <= hold_count:
            # 排名回到前hold_count，重置缓冲带计数器
            self._buffer_tracker.pop(code, None)
            return True, f"排名{rank}"

        if rank > hold_count + buffer_size:
            return False, f"排名{rank}>缓冲带"

        # 在缓冲带内
        if not hasattr(self, '_buffer_tracker'):
            self._buffer_tracker: dict[str, int] = {}
        days_below = self._buffer_tracker.get(code, 0) + 1
        self._buffer_tracker[code] = days_below

        if days_below >= buffer_days:
            return False, f"连续{days_below}日低于前{hold_count}"
        if was_held:
            return True, f"缓冲观察({days_below}/{buffer_days}日)"
        return False, f"缓冲带不买入"

    # ============== 生命周期 ==============

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

        # 动量计算
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

        # HV
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
        self._peak_prices: dict[str, float] = {}  # 追踪止损用
        self._prev_selected: set[str] = set()
        self._buffer_tracker: dict[str, int] = {}
        self._dates = sorted(d for d in self._data['date'].unique() if pd.notna(d))
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}
        self._portfolio_peak = 1.0
        self._portfolio_stopped = False
        self._portfolio_stop_trigger_idx = -1  # 触发止损的交易日索引
        self._portfolio_stop_cooldown = 5      # 止损后冷却5个交易日
        self._ic_history: dict[str, deque] = {}

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        day_data = data.copy()
        if day_data.empty:
            return None

        # 防御: 统一 code 列为字符串类型，避免 int64 vs str 的 isin 匹配失败
        if 'code' in day_data.columns:
            day_data['code'] = day_data['code'].astype(str)

        # 清理退市债券的缓冲状态
        active_codes = set(day_data['code'].values)
        self._buffer_tracker = {k: v for k, v in self._buffer_tracker.items() if k in active_codes}

        if 'dual_low' not in day_data.columns:
            day_data['dual_low'] = day_data['price'] + day_data.get('premium_ratio', 15)

        # === 组合层面最大回撤止损 ===
        portfolio_stop_loss = self.get_param('portfolio_stop_loss')
        if self._prev_selected and portfolio_stop_loss < 0:
            held_data = day_data[day_data['code'].isin(self._prev_selected)]
            if not held_data.empty:
                equity_ratios = []
                for _, row in held_data.iterrows():
                    code = row['code']
                    if code in self._buy_prices and self._buy_prices[code] > 0:
                        equity_ratios.append(float(row['price']) / self._buy_prices[code])
                if equity_ratios:
                    current_equity = np.mean(equity_ratios)
                    self._portfolio_peak = max(self._portfolio_peak, current_equity)
                    drawdown = (current_equity / self._portfolio_peak - 1) * 100
                    if drawdown <= portfolio_stop_loss and not self._portfolio_stopped:
                        self._portfolio_stopped = True
                        self._portfolio_stop_trigger_idx = idx
                        signals = [{'code': '__PORTFOLIO__', 'action': 'sell_all', 'price': 0.0,
                                    'reason': f'组合回撤{drawdown:.1f}%触发{portfolio_stop_loss}%止损'}]
                        for code in list(self._prev_selected):
                            if code in day_data['code'].values:
                                row = day_data[day_data['code'] == code].iloc[0]
                                signals.append({'code': code, 'action': 'sell', 'price': float(row['price']), 'reason': '组合止损清仓'})
                            self._buy_prices.pop(code, None)
                            self._peak_prices.pop(code, None)
                        self._prev_selected = set()
                        return signals

        if self._portfolio_stopped:
            # 止损冷却期：触发后N个交易日不再开仓，允许市场修复
            if idx - self._portfolio_stop_trigger_idx >= self._portfolio_stop_cooldown:
                self._portfolio_stopped = False
                self._portfolio_stop_trigger_idx = -1
                self._portfolio_peak = 1.0  # 重置峰值，避免旧基准影响新止损
                logger.info(f"[Xuanji] 组合止损冷却期结束，idx={idx}，恢复策略")
            else:
                return None

        # === 每天检查追踪止损（v5.0 改进）===
        rebalance_days = self.get_param('rebalance_days')
        is_rebalance_day = (rebalance_days > 0 and idx % rebalance_days == 0)
        trailing_stop_pct = self.get_param('trailing_stop_pct')

        if self._prev_selected:
            stop_signals = []
            for code in list(self._prev_selected):
                if code in day_data['code'].values:
                    row = day_data[day_data['code'] == code].iloc[0]
                    current_price = float(row['price'])
                    # 更新最高价
                    self._peak_prices[code] = max(self._peak_prices.get(code, current_price), current_price)
                    # 追踪止损
                    peak = self._peak_prices.get(code, current_price)
                    if peak > 0 and (current_price / peak - 1) * 100 <= trailing_stop_pct:
                        stop_signals.append({'code': code, 'action': 'sell', 'price': current_price,
                                            'reason': f'追踪止损{((current_price/peak-1)*100):.1f}%'})
                        self._prev_selected.discard(code)
                        self._buy_prices.pop(code, None)
                        self._peak_prices.pop(code, None)
            if stop_signals:
                return stop_signals

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

        # 市场状态
        market_state = self.get_param('market_state')
        if market_state == 'auto':
            market_state = self._detect_market_state(day_data.copy())

        # === 一票否决过滤（v5.0 新增）===
        veto_mask = pd.Series(True, index=day_data.index)
        for idx_row, row in day_data.iterrows():
            passed, _ = self._check_veto(row)
            veto_mask[idx_row] = passed
        day_data = day_data[veto_mask]
        if day_data.empty:
            return None

        # 基础筛选
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

        # === 因子得分 ===
        price_med = day_data['price'].median() if day_data['price'].notna().any() else 115
        if not price_med or price_med <= 0:
            price_med = 115
        day_data['dual_low_norm'] = day_data['price'] / price_med * 50 + day_data['premium_ratio']
        score_dual_low = self._normalize_zscore(day_data['dual_low_norm'], ascending=True)

        if 'momentum' in day_data.columns and day_data['momentum'].notna().any():
            day_data['momentum'] = day_data['momentum'].clip(-0.5, 0.5)
        score_momentum = self._normalize_zscore(day_data['momentum'], ascending=False)
        score_hv = self._normalize_zscore(day_data['hv'], ascending=True)

        if 'ytm' in day_data.columns and day_data['ytm'].notna().any():
            score_ytm = self._normalize_zscore(day_data['ytm'].fillna(0), ascending=False)
        else:
            score_ytm = pd.Series(0.5, index=day_data.index)

        # 质量因子
        quality_sub_scores = []
        for col, asc in [('roe', False), ('gpm', False), ('cagr', False), ('debt_ratio', True)]:
            if col in day_data.columns and day_data[col].notna().any():
                col_median = day_data[col].median()
                if pd.isna(col_median):
                    col_median = 0
                s = self._normalize_zscore(day_data[col].fillna(col_median), ascending=asc)
                quality_sub_scores.append(s.values)

        if quality_sub_scores:
            if len(quality_sub_scores) >= 2:
                orthogonalized = self._gram_schmidt_orthogonalize(*quality_sub_scores)
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
                score_quality = pd.Series(
                    (quality_sub_scores[0] - quality_sub_scores[0].min()) / max(quality_sub_scores[0].max() - quality_sub_scores[0].min(), 1e-9),
                    index=day_data.index
                )
        else:
            score_quality = pd.Series(0.5, index=day_data.index)

        # 估值因子
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
                    (valuation_sub_scores[0] - valuation_sub_scores[0].min()) / max(valuation_sub_scores[0].max() - valuation_sub_scores[0].min(), 1e-9),
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

        # 收集因子得分
        factor_scores = {
            'dual_low': score_dual_low, 'momentum': score_momentum, 'hv': score_hv,
            'quality': score_quality, 'valuation': score_valuation, 'ytm': score_ytm,
            'remaining_years': score_remaining_years, 'event': score_event, 'delta': score_delta,
        }

        # 行业中性化
        if 'industry' in day_data.columns:
            for key in factor_scores:
                factor_scores[key] = self._neutralize_industry(factor_scores[key], day_data['industry'])

        # IC追踪与动态权重
        self._update_ic_history(day_data, factor_scores)
        weights = self._compute_icir_weights(day_data, factor_scores, market_state)

        # 波动率因子
        vol_factor = self._compute_vol_factor(day_data)

        # 过滤不可用因子
        active_weights = dict(weights)
        for k in ['ytm', 'delta', 'remaining_years']:
            if k in active_weights:
                col = {'ytm': 'ytm', 'delta': 'iv', 'remaining_years': 'remaining_years'}[k]
                if col not in day_data.columns or day_data[col].isna().all():
                    active_weights.pop(k, None)

        total_w = sum(active_weights.values())
        if total_w > 0:
            for k in active_weights:
                active_weights[k] /= total_w
        elif active_weights:
            eq = 1.0 / len(active_weights)
            for k in active_weights:
                active_weights[k] = eq

        # 复合得分
        composite = pd.Series(0.0, index=day_data.index)
        for key in self.FACTOR_KEYS:
            if key in active_weights and key in factor_scores:
                layer_adj = bond_layers.map(
                    lambda layer: self.LAYER_WEIGHT_ADJUST.get(layer, self.LAYER_WEIGHT_ADJUST['balanced']).get(key, 1.0)
                )
                composite += factor_scores[key] * active_weights[key] * layer_adj

        composite = composite * vol_factor
        day_data['score'] = composite.clip(0, 10)
        score_nan = day_data['score'].isna()
        if score_nan.any():
            day_data.loc[score_nan, 'score'] = 0.5

        actual_hold = min(self.get_param('hold_count'), len(day_data))
        ranked = day_data.nlargest(actual_hold + self.get_param('buffer_size'), 'score')

        # === 缓冲带选股（v5.0 新增）===
        signals = []
        new_codes = set()
        new_selected_codes = set()

        for rank_i, (ridx, row) in enumerate(ranked.iterrows(), 1):
            code = row['code']
            was_held = code in self._prev_selected
            should_hold, reason = self._should_hold_with_buffer(code, rank_i, was_held)
            if should_hold:
                new_selected_codes.add(code)
                if not was_held and rank_i <= actual_hold:
                    signals.append({
                        'code': code, 'action': 'buy', 'price': float(row['price']),
                        'confidence': float(row['score']),
                        'score': float(row['score']),
                        'reason': f'璇玑v5评分{row["score"]:.3f}[{market_state}]{reason}'
                    })
                    self._buy_prices[code] = float(row['price'])
                    self._peak_prices[code] = float(row['price'])
                elif was_held:
                    new_codes.add(code)

        new_codes = new_codes | new_selected_codes

        # 卖出
        to_sell = self._prev_selected - new_codes
        if to_sell:
            sell_rows = day_data[day_data['code'].isin(to_sell)]
            for code, price in zip(sell_rows['code'], sell_rows['price']):
                signals.append({'code': code, 'action': 'sell', 'price': float(price),
                               'reason': f'璇玑v5调仓({market_state})'})
                self._buy_prices.pop(code, None)
                self._peak_prices.pop(code, None)

        self._prev_selected = new_codes
        return signals if signals else None
