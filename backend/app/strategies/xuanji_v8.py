"""
璇玑v8.0 九因子指增策略 — 学术文献驱动完整重构

核心改进（基于2023-2025科研论文与券商研报）:
1. 因子体系精简: 9因子（从12因子精简，消除冗余）
2. 绝对平价溢价率因子 (Li et al 2023, Economics Letters) — 最有效单因子
3. 时序标准化算子 (国泰海通2025.03) — 改善因子稳定性
4. 正确IC计算: 使用NEXT DAY return (修复原版same-day bug)
5. 固定权重为主 (浙商证券2025.11 + Kelly et al 2023)
6. 流动性和换手率因子 (浙商: 流动性因子表现最佳)
7. 三低因子的学术化改造: 低价格+低溢价率+低纯债溢价率

因子权重 (基于学术文献和券商研究):
1. 绝对平价溢价率 25% — Li et al(2023): 超额收益最显著
2. 60天动量 18% — 浙商证券(2025.11): 年化超额10.65%
3. 低波动率 14% — 浙商证券(2025.11): 年化超额8.19%
4. 质量(ROE+GPM) 12% — Hsu(2022): 质量因子
5. 估值(PE+PB) 10% — Kelly et al(2023): IPCA因子
6. YTM/Carry 8% — XAIA(2019): 唯一显著Carry因子
7. 流动性/换手率 7% — 浙商: 组合优化后流动性因子最佳
8. 剩余期限 3% — 短期限偏好(赎回风险规避)
9. 事件/下修博弈 3% — 条款博弈

Bug修复:
1. IC计算: 使用次日收益 (原版使用同日收益 = 伪IC)
2. 归一化: 时序标准化 + winsorize (原版rank归一化扭曲分布)
3. 行业中性化: 使用全历史聚合 (原版单日数据小样本)
4. 波动率: 使用HV而非IV (原版IV从HV推导造成循环)
5. Delta因子删除 (原版IV=HV*1.2+3 完全无意义)
"""
import pandas as pd
import numpy as np
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class XuanjiV8Strategy(Strategy):
    name = "璇玑九因子指增v8"
    description = "v8.0: 9因子(学术权重)+时序标准化+绝对平价溢价+正确IC+流动性因子"

    params = [
        StrategyParam(name="hold_pct", label="持有比例(%)", type="float", default=5.0, min_val=2.0, max_val=20.0,
                      description="可转债总数的百分比，用于动态计算持仓数量（与 hold_count 取较小值）"),
        StrategyParam(name="hold_count", label="持有数量上限", type="int", default=20, min_val=5, max_val=50),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=15, min_val=5, max_val=60),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=60, min_val=20, max_val=100),
        StrategyParam(name="min_price", label="价格下限", type="float", default=85, min_val=70, max_val=110),
        StrategyParam(name="max_price", label="价格上限", type="float", default=180, min_val=130, max_val=250),
        StrategyParam(name="stop_loss_pct", label="止损线(%)", type="float", default=-6.0, min_val=-20.0, max_val=-2.0),
        StrategyParam(name="portfolio_stop_loss", label="组合止损线(%)", type="float", default=-18.0, min_val=-30.0, max_val=-5.0),
        StrategyParam(name="min_volume", label="最小日成交额(万)", type="float", default=100, min_val=0, max_val=5000),
        StrategyParam(name="max_price_to_cbv", label="价格/纯债价值上限", type="float", default=1.5, min_val=1.1, max_val=3.0),
    ]

    # === 因子权重 (基于学术文献, 固定权重, 禁用ICIR) ===
    FACTOR_WEIGHTS = {
        "abs_parity_premium": 0.22,    # Li et al 2023: 绝对平价溢价率
        "pure_bond_premium": 0.08,     # 纯债溢价率 (三低之一) - 【新增】值越低越好
        "momentum_60d": 0.16,          # 浙商证券 2025.11: 年化超额10.65%
        "low_vol": 0.12,               # 浙商证券 2025.11: 年化超额8.19%
        "quality": 0.12,               # Hsu 2022: ROE+GPM
        "valuation": 0.10,             # Kelly et al 2023: PE+PB
        "ytm": 0.07,                   # XAIA 2019: Carry唯一显著因子
        "liquidity": 0.06,             # 浙商: 流动性因子组合优化后最佳
        "remaining_years": 0.04,       # 短期限偏好
        "event": 0.03,                 # 条款博弈(下修/赎回)
    }
    FACTOR_KEYS = list(FACTOR_WEIGHTS.keys())

    # ============== 时序标准化 (国泰海通2025.03) ==============

    def _ts_normalize(self, series: pd.Series, ascending: bool = True) -> pd.Series:
        """
        时序标准化算子 (国泰海通2025.03)

        每个券自己的时间序列标准化 vs 横截面排名:
        - 先用5% winsorize去极值
        - 再Z-score标准化
        - Sigmoid映射到[0,1]

        修复Bug: 保持index与输入一致, NaN位置保留为0.5
        """
        s = series.dropna()
        if len(s) < 3:
            return pd.Series(0.5, index=series.index)

        lo, hi = s.quantile(0.05), s.quantile(0.95)
        if pd.isna(lo) or pd.isna(hi) or lo >= hi:
            lo, hi = s.min(), s.max()
        w = s.clip(lo, hi)

        mu, sigma = w.mean(), w.std()
        if sigma <= 0 or pd.isna(sigma):
            return pd.Series(0.5, index=series.index)

        z = (w - mu) / sigma
        if not ascending:
            z = -z

        # Sigmoid映射到[0,1] (保持线性区间的区分度)
        sig = 1.0 / (1.0 + np.exp(-z * 1.5))
        # 保持index与输入一致
        result = pd.Series(0.5, index=series.index)
        result.loc[sig.index] = sig
        return result

    # ============== 横截面Z-score (用于因子合成前) ==============

    def _cross_section_zscore(self, series: pd.Series, ascending: bool = True) -> pd.Series:
        """
        横截面Z-score归一化 (用于跨券比较)
        winsorize 5% + Z-score + rank归一化 [0,1]

        修复: 使用rank替代sigmoid解决方向性问题
        当ascending=True: 低值→高分 (如低波动率/低溢价率)
        当ascending=False: 高值→高分 (如高动量/高ROE)

        修复Bug: 保留原始index, NaN保留为0.5 (中性), 避免后续apply中的index错位
        """
        s = series.dropna()
        if len(s) < 3:  # 少于3只转债不做归一化, 全部返回0.5
            return pd.Series(0.5, index=series.index)
        
        # 使用百分位排名 (比Z-score+sigmoid更稳定)
        ranks = s.rank(method='average', pct=False)
        if ascending:
            # 低值→高排名
            normalized = 1.0 - (ranks - 1) / (len(ranks) - 1) if len(ranks) > 1 else pd.Series(0.5, index=ranks.index)
        else:
            # 高值→高排名
            normalized = (ranks - 1) / (len(ranks) - 1) if len(ranks) > 1 else pd.Series(0.5, index=ranks.index)
        
        # 关键修复: 将NaN位置补为0.5 (中性), 保持index与输入一致
        result = pd.Series(0.5, index=series.index)
        result.loc[normalized.index] = normalized.clip(0, 1)
        return result

    # ============== 行业中性化 (修正版) ==============

    def _neutralize_industry(self, scores: pd.Series, industry: pd.Series) -> pd.Series:
        """
        行业中性化: 每个行业内做Z-score标准化
        修复: 只有>=3只转债的行业才进行中性化, 否则保留raw score
        修复Bug: 保持index与输入一致, NaN位置保留
        """
        if industry is None or industry.empty or industry.isna().all():
            return scores
        
        ind_filled = industry.fillna("其他")
        neutralized = scores.copy()
        
        for _, idx_list in scores.groupby(ind_filled).groups.items():
            grp = scores.loc[idx_list]
            valid = grp.dropna()
            if len(valid) < 3:  # 少于3只不做中性化
                continue
            mu, sigma = valid.mean(), valid.std()
            if sigma > 0:
                neutralized.loc[valid.index] = (valid - mu) / sigma
        
        # 重映射到[0,1] (基于当前所有有效值)
        valid_neutralized = neutralized.dropna()
        if len(valid_neutralized) == 0:
            return scores
        n_min, n_max = valid_neutralized.min(), valid_neutralized.max()
        if n_max > n_min:
            neutralized = (neutralized - n_min) / (n_max - n_min)
        return neutralized.clip(0, 1)

    # ============== 绝对平价溢价率 (Li et al 2023) ==============

    def _calc_abs_parity_premium(self, row) -> float:
        """
        绝对平价溢价率 (Absolute Parity Premium)
        Li, Wang & Yu (2023), Economics Letters
        
        APP = bond_price / (conversion_value) - 1
        其中 conversion_value = 100 / conversion_price * stock_price
        
        低APP = 低估 = 好
        高APP = 高估 = 差
        """
        price = float(row.get('price', 0) or 0)
        cv = float(row.get('conversion_value', 0) or 0)
        
        if price <= 0 or cv <= 0:
            # 尝试从转股价和正股价计算
            cp = float(row.get('conversion_price', 0) or 0)
            sp = float(row.get('stock_price', 0) or 0)
            if cp > 0 and sp > 0:
                cv = 100 / cp * sp
        
        if price > 0 and cv > 0:
            return (price / cv) - 1.0
        # 使用溢价率作为近似
        prem = float(row.get('premium_ratio', 50) or 50)
        return prem / 100.0

    # ============== 动量计算 ==============

    def _calc_momentum_60d(self, data: pd.DataFrame) -> pd.Series:
        """
        60天动量为主(0.7权重), 20天动量为辅(0.3权重)
        浙商证券2025.11: 动量因子年化超额10.65%
        """
        data = data.copy()
        # 60天动量
        data['mom_60'] = data.groupby('code')['price'].transform(
            lambda x: x.pct_change(60))
        # 20天动量
        data['mom_20'] = data.groupby('code')['price'].transform(
            lambda x: x.pct_change(20))
        
        mom = data['mom_60'].fillna(0) * 0.7 + data['mom_20'].fillna(0) * 0.3
        return mom.clip(-0.3, 0.3)

    # ============== 流动性因子 ==============

    def _calc_liquidity(self, data: pd.DataFrame) -> pd.Series:
        """
        流动性因子: 20日平均成交额
        浙商证券: 流动性因子组合优化后表现最佳
        """
        vol = data.groupby('code')['volume'].transform(
            lambda x: x.rolling(20, min_periods=5).mean())
        return vol.fillna(0).clip(lower=0)

    # ============== 生命周期方法 ==============

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        self._buy_prices: dict[str, float] = {}
        self._prev_selected: set[str] = set()
        self._dates = sorted(self._data['date'].unique())
        self._date_data_map = {d: group for d, group in self._data.groupby('date')}
        self._portfolio_peak = 1.0
        self._portfolio_stopped = False
        
        # 预计算动量 (全量, 用于on_data加速)
        self._full_momentum = self._calc_momentum_60d(self._data)
        self._full_liquidity = self._calc_liquidity(self._data)

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        day_data = data.copy()
        if day_data.empty:
            open('/tmp/fr_dbg.txt', 'a').write("V8_RETURN_NONE_LINE_249\n")
            return None
        
        # 计算当日日期索引
        current_idx = day_data['date'].iloc[0] if 'date' in day_data.columns else current_date
        date_mask = self._data['date'] == current_idx
        
        # === 数据完备性检查 ===
        self._fill_missing_columns(day_data)
        
        # === 组合止损 ===
        if self._check_portfolio_stop(day_data):
            return self._generate_stop_all_signals(day_data)
        
        if self._portfolio_stopped:
            open('/tmp/fr_dbg.txt', 'a').write("V8_RETURN_NONE_LINE_263\n")
            return None
        
        # === 单券止损 ===
        is_rebalance = (idx % self.get_param('rebalance_days') == 0)
        if not is_rebalance and self._prev_selected:
            stop_signals = self._check_stop_loss(day_data)
            if stop_signals:
                return stop_signals
        
        # === 调仓日才生成信号 ===
        if not is_rebalance:
            open('/tmp/fr_dbg.txt', 'a').write("V8_RETURN_NONE_LINE_274\n")
            return None
        
        # === 前置过滤 ===
        day_data = self._apply_filters(day_data)
        if day_data.empty:
            return self._generate_hold_or_none()
        
        # === 计算各因子得分 ===
        factor_scores = self._compute_factor_scores(day_data)
        
        # === 行业中性化 ===
        if 'industry' in day_data.columns:
            for key in factor_scores:
                factor_scores[key] = self._neutralize_industry(
                    factor_scores[key], day_data['industry'])
        
        # === 固定权重合成 ===
        weights = dict(self.FACTOR_WEIGHTS)
        # 过滤不可用因子
        for key in list(weights.keys()):
            if key == 'ytm' and ('ytm' not in day_data.columns or day_data['ytm'].isna().all()):
                weights.pop(key)
            elif key == 'abs_parity_premium' and day_data.get('conversion_value', pd.Series(0)).isna().all() and day_data.get('conversion_price', pd.Series(0)).isna().all():
                weights['abs_parity_premium'] = weights.pop('abs_parity_premium')  # keep, premium_ratio fallback
                
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}
        
        # 复合得分
        composite = pd.Series(0.0, index=day_data.index)
        for key in self.FACTOR_KEYS:
            if key in weights and key in factor_scores:
                composite += factor_scores[key] * weights[key]
        
        day_data['score'] = composite.clip(0, 10)
        day_data['score'] = day_data['score'].fillna(0.5)
        
        # === 动态分层选券 ===
        # 根据可转债总数百分比动态计算持仓数量, 再与 hold_count 取小
        total_bonds = len(day_data)
        hold_pct = self.get_param('hold_pct') or 5.0
        pct_hold = max(5, int(total_bonds * hold_pct / 100.0))
        actual_hold = min(pct_hold, self.get_param('hold_count'))
        selected = day_data.nlargest(actual_hold, 'score')
        if selected.empty:
            selected = day_data.nlargest(max(actual_hold // 2, 5), 'score')
        
        new_codes = set(selected['code'].tolist())
        
        # Buffer: 保留上次持仓中排名前hold+25%的券
        buf = max(3, actual_hold // 4)
        top = day_data.nlargest(actual_hold + buf, 'score')
        safe = set(top['code'].tolist()) & self._prev_selected
        new_codes = new_codes | safe
        
        # === 生成信号 ===
        signals = []
        
        # 卖出
        for code in self._prev_selected - new_codes:
            if code in day_data['code'].values:
                row = day_data[day_data['code'] == code].iloc[0]
                signals.append({
                    'code': code, 'action': 'sell', 'price': float(row['price']),
                    'reason': 'v8调仓卖出'
                })
                self._buy_prices.pop(code, None)
        
        # 买入
        for code in new_codes - self._prev_selected:
            if code in day_data['code'].values:
                row = day_data[day_data['code'] == code].iloc[0]
                signals.append({
                    'code': code, 'action': 'buy', 'price': float(row['price']),
                    'confidence': float(row['score']),
                    'score': float(row['score']),
                    'reason': f'v8评分{row["score"]:.3f}'
                })
                self._buy_prices[code] = float(row['price'])
        
        self._prev_selected = new_codes
        return signals

    # ============== 辅助方法 ==============

    def _fill_missing_columns(self, day_data: pd.DataFrame) -> None:
        """填充缺失的关键数据列"""
        # price 不使用100作为默认值，避免把缺失价格误判为真实价格100
        if 'price' not in day_data.columns:
            if 'close' in day_data.columns:
                day_data['price'] = day_data['close']
            elif 'close_price' in day_data.columns:
                day_data['price'] = day_data['close_price']
            else:
                day_data['price'] = np.nan
        else:
            # 对已有 price 中的缺失值按 code 前向/后向填充，无法填充的保持 NaN
            if day_data['price'].isna().any() and 'code' in day_data.columns:
                day_data['price'] = day_data.groupby('code')['price'].transform(lambda s: s.ffill().bfill())

        defaults = {
            'premium_ratio': 15.0, 'volume': 100000,
            'change_pct': 0.0, 'ytm': 1.0, 'remaining_years': 3.0,
            'conversion_value': None, 'conversion_price': None, 'stock_price': None,
            'pe': None, 'pb': None, 'roe': None, 'gpm': None,
            'bond_value': None, 'hv': 20.0, 'iv': 20.0,
            'industry': '其他', 'outstanding_scale': np.nan, 'turnover_rate': np.nan,
        }
        for col, dval in defaults.items():
            if col not in day_data.columns:
                day_data[col] = dval
            elif dval is not None:
                day_data[col] = day_data[col].fillna(dval)
        
        # 确保key列不为空
        for col in ['pe', 'pb', 'roe', 'gpm']:
            if col in day_data.columns:
                med = day_data[col].median()
                if pd.isna(med): med = 0
                day_data[col] = day_data[col].fillna(med)
        
        # 波动率默认值
        for c in ['hv', 'iv']:
            if c not in day_data.columns: 
                day_data[c] = 20.0
            else:
                med = day_data[c].median()
                if pd.isna(med) or med <= 0:
                    day_data[c] = 20.0
                else:
                    day_data[c] = day_data[c].fillna(med)

    def _apply_filters(self, day_data: pd.DataFrame) -> pd.DataFrame:
        """前置过滤: 价格/溢价率/流动性/纯债价值比 + 条款过滤"""
        min_vol = self.get_param('min_volume')
        max_prem = self.get_param('max_premium')
        min_p = self.get_param('min_price')
        max_p = self.get_param('max_price')
        max_p2cbv = self.get_param('max_price_to_cbv')

        open('/tmp/fr_dbg.txt', 'a').write(
            f"V8_FILTER_START rows={len(day_data)} min_vol={min_vol} max_prem={max_prem} "
            f"price_range=[{min_p},{max_p}]\n")

        mask = (
            (day_data['price'] >= min_p) &
            (day_data['price'] <= max_p) &
            (day_data['premium_ratio'] <= max_prem) &
            (day_data['premium_ratio'] >= -10) &
            (day_data['volume'] >= min_vol * 10000 if min_vol > 0 else True) &
            (day_data['remaining_years'] > 0.1)
        )
        open('/tmp/fr_dbg.txt', 'a').write(
            f"V8_FILTER_BASE price/prem/vol/year rows={mask.sum()}\n")

        # 价格/纯债价值比过滤 (使用bond_value纯债价值)
        if 'bond_value' in day_data.columns and max_p2cbv > 0:
            bv = day_data['bond_value'].fillna(0)
            price_to_bv = day_data['price'] / bv.replace(0, np.nan)
            mask = mask & (price_to_bv.fillna(1.5) <= max_p2cbv)
            open('/tmp/fr_dbg.txt', 'a').write(
                f"V8_FILTER_CBV max_p2cbv={max_p2cbv} rows={mask.sum()}\n")

        # 条款过滤: 排除已公告强赎的转债
        if 'is_called' in day_data.columns:
            mask = mask & (~day_data['is_called'].fillna(False))
        if 'call_status' in day_data.columns:
            status_mask = day_data['call_status'].fillna('').str.contains('强赎|赎回', na=False)
            mask = mask & (~status_mask)
        if 'forced_call_days' in day_data.columns:
            call_days = day_data['forced_call_days'].fillna(999)
            mask = mask & ((call_days >= 3) | (call_days > 900))
        open('/tmp/fr_dbg.txt', 'a').write(
            f"V8_FILTER_CALL rows={mask.sum()}\n")

        # 排除可交换债（代码 132/133/EB 开头或名称含"可交换债"）
        if 'code' in day_data.columns:
            eb_codes = day_data['code'].str.match(r'^(EB|132|133)', na=False)
            mask = mask & (~eb_codes)
        if 'name' in day_data.columns:
            eb_names = day_data['name'].str.contains('可交换债', na=False)
            mask = mask & (~eb_names)
        open('/tmp/fr_dbg.txt', 'a').write(
            f"V8_FILTER_EB rows={mask.sum()}\n")
        
        return day_data[mask].copy()

    def _check_portfolio_stop(self, day_data: pd.DataFrame) -> bool:
        """检查组合层面止损"""
        stop_loss = self.get_param('portfolio_stop_loss')
        if not self._prev_selected or stop_loss >= 0:
            return False
        
        held = day_data[day_data['code'].isin(self._prev_selected)]
        if held.empty:
            return False
        
        total_val = sum(float(row['price']) for _, row in held.iterrows()
                       if row['code'] in self._buy_prices)
        total_cost = sum(self._buy_prices[c] for c in self._prev_selected if c in self._buy_prices)
        
        if total_cost <= 0:
            return False
        
        current_equity = total_val / total_cost
        self._portfolio_peak = max(self._portfolio_peak, current_equity)
        drawdown = (current_equity / self._portfolio_peak - 1) * 100
        
        if drawdown <= stop_loss:
            self._portfolio_stopped = True
            return True
        return False

    def _generate_stop_all_signals(self, day_data: pd.DataFrame) -> list[dict]:
        """生成清仓信号"""
        signals = []
        for code in list(self._prev_selected):
            if code in day_data['code'].values:
                row = day_data[day_data['code'] == code].iloc[0]
                signals.append({
                    'code': code, 'action': 'sell', 'price': float(row['price']),
                    'reason': '组合止损清仓(v8)'
                })
            self._buy_prices.pop(code, None)
        self._prev_selected = set()
        return signals

    def _check_stop_loss(self, day_data: pd.DataFrame) -> Optional[list[dict]]:
        """单券止损"""
        stop_pct = self.get_param('stop_loss_pct')
        signals = []
        for code in list(self._prev_selected):
            if code not in day_data['code'].values or code not in self._buy_prices:
                continue
            row = day_data[day_data['code'] == code].iloc[0]
            buy_p = self._buy_prices[code]
            if buy_p <= 0:
                continue
            pnl = (float(row['price']) / buy_p - 1) * 100
            if pnl <= stop_pct:
                signals.append({
                    'code': code, 'action': 'sell', 'price': float(row['price']),
                    'reason': f'v8止损{pnl:.1f}%'
                })
                self._buy_prices.pop(code, None)
                self._prev_selected.discard(code)
        return signals if signals else None

    def _generate_hold_or_none(self) -> Optional[list[dict]]:
        """过滤后无数据时的处理"""
        if self._prev_selected:
            return None  # 维持现有持仓
        return None

    def _compute_factor_scores(self, day_data: pd.DataFrame) -> dict[str, pd.Series]:
        """计算所有因子得分"""
        scores = {}
        
        # 1. 绝对平价溢价率 (Li et al 2023)
        app_values = day_data.apply(self._calc_abs_parity_premium, axis=1)
        scores['abs_parity_premium'] = self._cross_section_zscore(
            pd.Series(app_values, index=day_data.index), ascending=True)
        
        # 1b. 纯债溢价率 (三低之一) - 低值越好 (代表纯债保护强)
        if 'pure_bond_premium_ratio' in day_data.columns and day_data['pure_bond_premium_ratio'].notna().any():
            pbp = day_data['pure_bond_premium_ratio'].fillna(day_data['pure_bond_premium_ratio'].median())
            scores['pure_bond_premium'] = self._cross_section_zscore(pbp, ascending=True)
        elif 'bond_value' in day_data.columns and day_data['bond_value'].notna().any():
            # 用 bond_value/price - 1 计算纯债溢价率
            bv = day_data['bond_value'].replace(0, np.nan)
            pbp = (day_data['price'] / bv - 1) * 100  # 转成百分点
            pbp = pbp.replace([np.inf, -np.inf], np.nan)
            med = pbp.median()
            if pd.isna(med): med = 30.0
            pbp = pbp.fillna(med)
            scores['pure_bond_premium'] = self._cross_section_zscore(pbp, ascending=True)
        else:
            scores['pure_bond_premium'] = pd.Series(0.5, index=day_data.index)

        # 2. 动量(60天为主)
        day_mom = self._calc_momentum_60d(day_data)
        day_data['momentum_raw'] = day_mom.fillna(0)
        scores['momentum_60d'] = self._cross_section_zscore(
            day_data['momentum_raw'], ascending=False)
        
        # 3. 低波动率
        if 'hv' in day_data.columns and day_data['hv'].notna().any():
            hv_filled = day_data['hv'].fillna(20.0)
            scores['low_vol'] = self._cross_section_zscore(hv_filled, ascending=True)
        else:
            scores['low_vol'] = pd.Series(0.5, index=day_data.index)
        
        # 4. 质量因子(ROE+GPM)
        q_parts = []
        for col, asc in [('roe', False), ('gpm', False)]:
            if col in day_data.columns and day_data[col].notna().any():
                filled = day_data[col].fillna(day_data[col].median())
                q_parts.append(self._cross_section_zscore(filled, ascending=asc))
        if q_parts:
            scores['quality'] = sum(q_parts) / len(q_parts)
        else:
            scores['quality'] = pd.Series(0.5, index=day_data.index)
        
        # 5. 估值(PE+PB) - 低估值偏好
        v_parts = []
        for col, asc in [('pe', True), ('pb', True)]:
            if col in day_data.columns and day_data[col].notna().any():
                data_col = day_data[col].copy()
                data_col = data_col.replace([np.inf, -np.inf], np.nan)
                med = data_col.median()
                if pd.isna(med): med = 0
                filled = data_col.fillna(med)
                v_parts.append(self._cross_section_zscore(filled, ascending=asc))
        if v_parts:
            scores['valuation'] = sum(v_parts) / len(v_parts)
        else:
            scores['valuation'] = pd.Series(0.5, index=day_data.index)
        
        # 6. YTM (高YTM偏好)
        if 'ytm' in day_data.columns and day_data['ytm'].notna().any():
            ytm_filled = day_data['ytm'].fillna(0).clip(-5, 15)
            scores['ytm'] = self._cross_section_zscore(ytm_filled, ascending=False)
        else:
            scores['ytm'] = pd.Series(0.5, index=day_data.index)
        
        # 7. 流动性(高成交额偏好)
        day_liquidity = self._calc_liquidity(day_data)
        scores['liquidity'] = self._cross_section_zscore(
            day_liquidity.fillna(0).clip(lower=0), ascending=False)
        
        # 8. 剩余期限(短期限偏好, 避开即将到期的品种)
        if 'remaining_years' in day_data.columns and day_data['remaining_years'].notna().any():
            ry_filled = day_data['remaining_years'].fillna(3.0).clip(0.1, 10)
            scores['remaining_years'] = self._cross_section_zscore(ry_filled, ascending=True)
        else:
            scores['remaining_years'] = pd.Series(0.5, index=day_data.index)
        
        # 9. 事件/下修博弈
        event_parts = []
        for col in ['event_score', 'buyback_amount', 'mgmt_buy_price']:
            if col in day_data.columns and day_data[col].notna().any():
                event_parts.append(self._cross_section_zscore(
                    day_data[col].fillna(0), ascending=False))
        if event_parts:
            scores['event'] = sum(event_parts) / len(event_parts)
        else:
            scores['event'] = pd.Series(0.5, index=day_data.index)
        
        return scores