"""宏观市场数据服务 V2.1

通过 AKShare 获取真实宏观市场数据：
- 10年期国债收益率曲线（含2年、5年、10年）
- 制造业PMI
- Shibor利率（隔夜、1周、1月）
- M2增速、社融增速
- CPI / PPI
- 信用利差（AA企业债 - 国债）
- 股市涨跌统计、涨停跌停数
- 转债市场统计数据（溢价率中位数、日均成交额）
- 指数均线数据
- 北向资金净流入
- 融资融券余额及买入占比
- 主力资金净流入
- 行业资金流向
- PE/PB中位数及历史分位数
- 工业增加值、社零、出口增速
- 认沽/认购比(PCR)、波动率指数(VIX)
- 新增开户数
- 技术指标自动计算（MA/MACD/RSI/BB/量比）
"""

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    import akshare as ak
except ImportError:
    ak = None

logger = logging.getLogger(__name__)


@dataclass
class MacroData:
    """宏观市场数据快照"""
    # === 国债收益率 ===
    treasury_10y_yield: float = 0.0
    treasury_5y_yield: float = 0.0
    treasury_2y_yield: float = 0.0
    credit_spread_aa: float = 0.0

    # === Shibor ===
    shibor_overnight: float = 0.0
    shibor_1w: float = 0.0
    shibor_1m: float = 0.0

    # === 宏观 ===
    pmi_current: float = 50.0
    pmi_prev: float = 50.0
    cpi: float = 2.0
    ppi: float = 0.0
    m2_growth: float = 10.0
    social_financing_growth: float = 10.0
    gdp_growth: float = 5.0

    # === 转债市场 ===
    cb_median_premium: float = 0.0
    cb_avg_daily_amount: float = 0.0
    cb_index_change: float = 0.0
    cb_index_current: float = 0.0
    cb_index_ma20: float = 0.0
    cb_index_ma60: float = 0.0
    cb_below_par_count: int = 0
    cb_median_price: float = 0.0
    cb_count: int = 0

    # === 正股市场 ===
    stock_index_current: float = 0.0
    stock_index_change: float = 0.0
    stock_index_ma20: float = 0.0
    stock_index_ma60: float = 0.0
    stock_pe_median: float = 0.0
    stock_pb_median: float = 0.0
    stock_pe_percentile: float = 50.0
    stock_pb_percentile: float = 50.0

    # === 资金流向 ===
    north_bound_net_flow: float = 0.0
    main_force_net_flow: float = 0.0
    margin_balance: float = 0.0
    margin_balance_change: float = 0.0
    margin_buy_ratio: float = 0.0
    industry_net_inflow: float = 50.0

    # === 宏观扩展 ===
    industrial_output: float = 0.0
    retail_sales: float = 0.0
    export_growth: float = 0.0

    # === 情绪扩展 ===
    pcr_ratio: float = 0.0
    vix_index: float = 0.0
    new_accounts: float = 0.0

    # === 技术指标（从指数日线自动计算）===
    ma_arrangement: str = "neutral"
    macd_signal: str = "neutral"
    rsi_14: float = 0.0
    bollinger_position: float = 0.0
    volume_ratio: float = 0.0

    # === 指数日线（用于技术指标计算）===
    stock_index_df: Optional[pd.DataFrame] = None
    cb_index_df: Optional[pd.DataFrame] = None

    # === 消息面/基本面扩展 ===
    institutional_holding_change: float = 0.0  # 机构持仓变化(%)
    earnings_surprise_ratio: float = 0.0       # 盈利超预期比例 0-1
    policy_signal_score: float = 50.0          # 政策信号评分 0-100
    event_impact_score: float = 50.0           # 事件冲击评分 0-100
    industry_cycle_score: float = 50.0         # 产业链景气评分 0-100
    limit_up_count: int = 0
    limit_down_count: int = 0
    advance_count: int = 0
    decline_count: int = 0
    new_high_60d: int = 0
    new_low_60d: int = 0
    market_turnover: float = 0.0

    updated_at: Optional[datetime] = None
    data_completeness: float = 0.0


class MacroDataService:
    """宏观市场数据服务 V2.1"""

    def __init__(self, cache_ttl: int = 1800):
        self._cache: Optional[MacroData] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = cache_ttl

    def _is_cache_valid(self) -> bool:
        if not self._cache_time or not self._cache:
            return False
        return (datetime.now() - self._cache_time).total_seconds() < self._cache_ttl

    async def fetch_macro_data(self, bonds=None) -> MacroData:
        """获取宏观市场数据（带缓存）"""
        if self._is_cache_valid():
            return self._cache

        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_all, bonds),
                timeout=90,
            )
            self._cache = data
            self._cache_time = datetime.now()
            return data
        except Exception as e:
            logger.error(f"[MacroData] Fetch failed: {e}")
            return self._cache or MacroData()

    def _fetch_all(self, bonds=None) -> MacroData:
        """同步获取所有宏观数据"""
        data = MacroData()

        # 1. 国债收益率曲线（10年、5年、2年）
        y10, y5, y2 = self._fetch_treasury_yields()
        data.treasury_10y_yield = y10
        data.treasury_5y_yield = y5
        data.treasury_2y_yield = y2

        # 2. PMI
        data.pmi_current, data.pmi_prev = self._fetch_pmi()

        # 3. CPI / PPI
        data.cpi, data.ppi = self._fetch_cpi_ppi()

        # 4. M2 增速
        data.m2_growth = self._fetch_m2_growth()

        # 5. 社融增速
        data.social_financing_growth = self._fetch_social_financing()

        # 6. GDP 增速
        data.gdp_growth = self._fetch_gdp_growth()

        # 7. Shibor
        data.shibor_overnight, data.shibor_1w, data.shibor_1m = self._fetch_shibor()

        # 8. 信用利差
        data.credit_spread_aa = self._fetch_credit_spread()

        # 9. 市场涨跌统计
        (data.limit_up_count, data.limit_down_count,
         data.advance_count, data.decline_count,
         data.new_high_60d, data.new_low_60d) = self._fetch_market_stats()

        # 10. 指数数据 (中证转债)
        (data.cb_index_current, data.cb_index_change,
         data.cb_index_ma20, data.cb_index_ma60,
         data.cb_index_df) = self._fetch_cb_index()

        # 11. 沪深300
        (data.stock_index_current, data.stock_index_change,
         data.stock_index_ma20, data.stock_index_ma60,
         data.stock_index_df) = self._fetch_stock_index()

        # 12. 转债市场统计（从实时行情计算）
        if bonds:
            self._calc_cb_stats(data, bonds)

        # 13. 北向资金
        data.north_bound_net_flow = self._fetch_north_bound_flow()

        # 14. 融资融券
        (data.margin_balance, data.margin_balance_change,
         data.margin_buy_ratio) = self._fetch_margin_data()

        # 15. 主力资金净流入
        data.main_force_net_flow = self._fetch_main_force_flow()

        # 16. 行业资金流向
        data.industry_net_inflow = self._fetch_industry_net_inflow()

        # 17. PE/PB 中位数 + 历史分位数
        (data.stock_pe_median, data.stock_pb_median,
         data.stock_pe_percentile, data.stock_pb_percentile) = self._fetch_pe_pb()

        # 18. 工业增加值
        data.industrial_output = self._fetch_industrial_output()

        # 19. 社零
        data.retail_sales = self._fetch_retail_sales()

        # 20. 出口增速
        data.export_growth = self._fetch_export_growth()

        # 21. 认沽/认购比
        data.pcr_ratio = self._fetch_pcr_ratio()

        # 22. 波动率指数
        data.vix_index = self._fetch_vix()

        # 23. 新增开户数
        data.new_accounts = self._fetch_new_accounts()

        # 24. 从指数日线自动计算技术指标
        self._compute_technical_indicators(data)

        # 25. 机构持仓变化（从北向资金+融资数据间接推算）
        data.institutional_holding_change = self._fetch_institutional_holding(data)

        # 26. 盈利超预期比例
        data.earnings_surprise_ratio = self._fetch_earnings_surprise()

        # 27. 产业链景气（从工业增加值+出口+CPI-PPI综合推算）
        data.industry_cycle_score = self._calc_industry_cycle(data)

        # 28. 政策信号+事件冲击（从市场表现间接推算）
        data.policy_signal_score, data.event_impact_score = self._calc_policy_event_scores(data)

        # 计算数据完整度
        data.data_completeness = self._calc_completeness(data)
        data.updated_at = datetime.now()

        logger.info(
            f"[MacroData] 国债10Y={data.treasury_10y_yield:.2f}%, "
            f"PMI={data.pmi_current:.1f}/{data.pmi_prev:.1f}, "
            f"Shibor隔夜={data.shibor_overnight:.2f}%, "
            f"CPI={data.cpi:.1f}%, PPI={data.ppi:.1f}%, "
            f"M2={data.m2_growth:.1f}%, "
            f"信用利差={data.credit_spread_aa:.0f}bp, "
            f"涨停={data.limit_up_count}/跌停={data.limit_down_count}, "
            f"溢价率中位={data.cb_median_premium:.2f}%, "
            f"北向={data.north_bound_net_flow:+.1f}亿, "
            f"融资余额={data.margin_balance:.0f}亿, "
            f"PE中位={data.stock_pe_median:.1f}, "
            f"完整度={data.data_completeness:.0%}"
        )
        return data

    def _calc_completeness(self, data: MacroData) -> float:
        """计算数据完整度（覆盖全部关键字段）"""
        checks = [
            ("treasury_10y", data.treasury_10y_yield > 0, 0.06),
            ("pmi", 0 < data.pmi_current < 100 and data.pmi_current != 50.0, 0.06),
            ("cpi_ppi", data.cpi != 2.0 or data.ppi != 0.0, 0.04),
            ("m2", data.m2_growth > 0 and data.m2_growth != 10.0, 0.05),
            ("social_fin", data.social_financing_growth > 0 and data.social_financing_growth != 10.0, 0.04),
            ("gdp", data.gdp_growth > 0 and data.gdp_growth != 5.0, 0.04),
            ("shibor", data.shibor_overnight > 0, 0.04),
            ("credit_spread", data.credit_spread_aa > 0, 0.04),
            ("market_stats", data.advance_count > 0 or data.decline_count > 0, 0.04),
            ("cb_index", data.cb_index_current > 0, 0.05),
            ("stock_index", data.stock_index_current > 0, 0.05),
            ("cb_stats", data.cb_median_premium > 0, 0.04),
            ("north_bound", data.north_bound_net_flow != 0, 0.05),
            ("margin", data.margin_balance > 0, 0.05),
            ("main_force", data.main_force_net_flow != 0, 0.04),
            ("industry_flow", data.industry_net_inflow != 50.0, 0.04),
            ("pe_pb", data.stock_pe_median > 0 and data.stock_pb_median > 0, 0.06),
            ("industrial", data.industrial_output != 0, 0.04),
            ("retail", data.retail_sales != 0, 0.04),
            ("export", data.export_growth != 0, 0.04),
            ("pcr", data.pcr_ratio > 0, 0.03),
            ("vix", data.vix_index > 0, 0.03),
            ("technical", data.rsi_14 > 0, 0.05),
            ("term_spread", data.treasury_10y_yield > 0 and data.treasury_2y_yield > 0, 0.04),
        ]
        total = sum(w for _, ok, w in checks if ok)
        return min(1.0, total)

    # ========== 数据获取方法 ==========

    def _fetch_treasury_yields(self) -> Tuple[float, float, float]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0
            end = datetime.now().strftime('%Y%m%d')
            start = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')
            df = ak.bond_china_yield(start_date=start, end_date=end)
            gov_df = df[df['曲线名称'] == '中债国债收益率曲线'].copy()
            if gov_df.empty:
                return 0.0, 0.0, 0.0
            gov_df = gov_df.sort_values('日期', ascending=False)
            latest = gov_df.iloc[0]
            y10 = float(latest.get('10年', 0))
            y5 = float(latest.get('5年', 0))
            y1 = float(latest.get('1年', 0))
            y3 = float(latest.get('3年', 0))
            y2 = (y1 + y3) / 2 if y1 > 0 and y3 > 0 else y3 if y3 > 0 else y1
            return round(y10, 4), round(y5, 4), round(y2, 4)
        except Exception as e:
            logger.warning(f"[MacroData] Treasury yields fetch failed: {e}")
            return 0.0, 0.0, 0.0

    def _fetch_pmi(self) -> Tuple[float, float]:
        try:
            if ak is None:
                return -1.0, -1.0
            df = ak.macro_china_pmi()
            pmi_col = '制造业-指数'
            if pmi_col not in df.columns:
                return -1.0, -1.0
            values = df[pmi_col].dropna()
            if len(values) < 2:
                return -1.0, -1.0
            return round(float(values.iloc[-1]), 1), round(float(values.iloc[-2]), 1)
        except Exception as e:
            logger.warning(f"[MacroData] PMI fetch failed: {e}")
            return -1.0, -1.0

    def _fetch_cpi_ppi(self) -> Tuple[float, float]:
        try:
            if ak is None:
                return 2.0, 0.0
            df = ak.macro_china_cpi()
            cpi_col = '全国-当月同比'
            cpi = 2.0
            if cpi_col in df.columns:
                vals = df[cpi_col].dropna()
                if len(vals) > 0:
                    cpi = float(vals.iloc[-1])
            ppi = 0.0
            try:
                ppi_df = ak.macro_china_ppi()
                ppi_col = '当月同比'
                if ppi_col in ppi_df.columns:
                    pvals = ppi_df[ppi_col].dropna()
                    ppi = float(pvals.iloc[-1]) if len(pvals) > 0 else 0.0
            except Exception as e:
                logger.warning(f"[MacroData] PPI fetch failed: {e}")
            return round(cpi, 1), round(ppi, 1)
        except Exception as e:
            logger.warning(f"[MacroData] CPI/PPI fetch failed: {e}")
            return 2.0, 0.0

    def _fetch_m2_growth(self) -> float:
        try:
            if ak is None:
                return 10.0
            df = ak.macro_china_money_supply()
            col = '货币和准货币(M2)-同比增长'
            if col in df.columns:
                vals = df[col].dropna()
                if len(vals) > 0:
                    return round(float(vals.iloc[-1]), 1)
            return 10.0
        except Exception as e:
            logger.warning(f"[MacroData] M2 fetch failed: {e}")
            return 10.0

    def _fetch_social_financing(self) -> float:
        try:
            if ak is None:
                return 10.0
            df = ak.macro_china_shrzgm()
            for col in ['社会融资规模增量-同比增长', '社会融资规模存量-同比增长']:
                if col in df.columns:
                    vals = df[col].dropna()
                    if len(vals) > 0:
                        return round(float(vals.iloc[-1]), 1)
            return 10.0
        except Exception as e:
            logger.warning(f"[MacroData] Social financing fetch failed: {e}")
            return 10.0

    def _fetch_gdp_growth(self) -> float:
        try:
            if ak is None:
                return 5.0
            df = ak.macro_china_gdp()
            col = '国内生产总值-同比增长'
            if col in df.columns:
                vals = df[col].dropna()
                if len(vals) > 0:
                    return round(float(vals.iloc[-1]), 1)
            return 5.0
        except Exception as e:
            logger.warning(f"[MacroData] GDP fetch failed: {e}")
            return 5.0

    def _fetch_shibor(self) -> Tuple[float, float, float]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0
            df = ak.macro_china_shibor_all()
            if df is None or df.empty:
                return 0.0, 0.0, 0.0
            latest = df.iloc[-1]
            overnight = float(latest.get('O/N-定价', 0) or 0)
            w1 = float(latest.get('1W-定价', 0) or 0)
            m1 = float(latest.get('1M-定价', 0) or 0)
            return round(overnight, 4), round(w1, 4), round(m1, 4)
        except Exception as e:
            logger.warning(f"[MacroData] Shibor fetch failed: {e}")
            return 0.0, 0.0, 0.0

    def _fetch_credit_spread(self) -> float:
        try:
            if ak is None:
                return 0.0
            end = datetime.now().strftime('%Y%m%d')
            start = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')
            df = ak.bond_china_yield(start_date=start, end_date=end)
            aa_df = df[df['曲线名称'].str.contains('AA', na=False)]
            gov_df = df[df['曲线名称'] == '中债国债收益率曲线']
            if aa_df.empty or gov_df.empty:
                return 0.0
            aa_latest = aa_df.sort_values('日期', ascending=False).iloc[0]
            gov_latest = gov_df.sort_values('日期', ascending=False).iloc[0]
            aa_5y = float(aa_latest.get('5年', 0))
            gov_5y = float(gov_latest.get('5年', 0))
            if aa_5y > 0 and gov_5y > 0:
                return round((aa_5y - gov_5y) * 100, 1)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] Credit spread fetch failed: {e}")
            return 0.0

    def _fetch_market_stats(self) -> Tuple[int, int, int, int, int, int]:
        try:
            if ak is None:
                return 0, 0, 0, 0, 0, 0
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return 0, 0, 0, 0, 0, 0
            limit_up = int((df['涨跌幅'] >= 9.9).sum()) if '涨跌幅' in df.columns else 0
            limit_down = int((df['涨跌幅'] <= -9.9).sum()) if '涨跌幅' in df.columns else 0
            advance = int((df['涨跌幅'] > 0).sum()) if '涨跌幅' in df.columns else 0
            decline = int((df['涨跌幅'] < 0).sum()) if '涨跌幅' in df.columns else 0
            high_60d = 0
            low_60d = 0
            if '60日涨跌幅' in df.columns:
                high_60d = int((df['60日涨跌幅'] > 20).sum())
                low_60d = int((df['60日涨跌幅'] < -20).sum())
            return limit_up, limit_down, advance, decline, high_60d, low_60d
        except Exception as e:
            logger.warning(f"[MacroData] Market stats fetch failed: {e}")
            return 0, 0, 0, 0, 0, 0

    def _fetch_cb_index(self) -> Tuple[float, float, float, float, Optional[pd.DataFrame]]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0, 0.0, None
            start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            df = ak.index_zh_a_hist(symbol="000832", period="daily", start_date=start)
            if df is None or df.empty:
                return 0.0, 0.0, 0.0, 0.0, None
            df = df.sort_values('日期', ascending=True)
            latest = df.iloc[-1]
            current = float(latest['收盘'])
            change = float(latest.get('涨跌幅', 0))
            ma20 = float(df['收盘'].tail(20).mean()) if len(df) >= 20 else current
            ma60 = float(df['收盘'].tail(60).mean()) if len(df) >= 60 else current
            return round(current, 2), round(change, 2), round(ma20, 2), round(ma60, 2), df
        except Exception as e:
            logger.warning(f"[MacroData] CB index fetch failed: {e}")
            return 0.0, 0.0, 0.0, 0.0, None

    def _fetch_stock_index(self) -> Tuple[float, float, float, float, Optional[pd.DataFrame]]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0, 0.0, None
            start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            df = ak.index_zh_a_hist(symbol="000300", period="daily", start_date=start)
            if df is None or df.empty:
                return 0.0, 0.0, 0.0, 0.0, None
            df = df.sort_values('日期', ascending=True)
            latest = df.iloc[-1]
            current = float(latest['收盘'])
            change = float(latest.get('涨跌幅', 0))
            ma20 = float(df['收盘'].tail(20).mean()) if len(df) >= 20 else current
            ma60 = float(df['收盘'].tail(60).mean()) if len(df) >= 60 else current
            return round(current, 2), round(change, 2), round(ma20, 2), round(ma60, 2), df
        except Exception as e:
            logger.warning(f"[MacroData] HS300 index fetch failed: {e}")
            return 0.0, 0.0, 0.0, 0.0, None

    def _calc_cb_stats(self, data: MacroData, bonds) -> None:
        premiums, volumes, prices = [], [], []
        for b in bonds:
            pr = getattr(b, 'premium_ratio', 0) or 0
            vol = getattr(b, 'volume', 0) or 0
            price = getattr(b, 'price', 0) or 0
            if price > 0:
                premiums.append(pr)
                volumes.append(vol)
                prices.append(price)
        if premiums:
            data.cb_median_premium = round(float(np.median(premiums)), 2)
        if prices:
            p_arr = np.array(prices)
            data.cb_below_par_count = int((p_arr < 100).sum())
            data.cb_median_price = round(float(np.median(p_arr)), 2)
            data.cb_count = len(prices)
        if volumes:
            total_vol = sum(volumes)
            data.cb_avg_daily_amount = round(total_vol / len(volumes), 2) if len(volumes) > 0 else 0

    def _fetch_north_bound_flow(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.stock_hsgt_hist_em(symbol="北向资金")
            if df is None or df.empty:
                return 0.0
            col = None
            for c in df.columns:
                if '净买' in c or '净流入' in c:
                    col = c
                    break
            if col is None:
                col = df.columns[-1]
            vals = df[col].dropna()
            if len(vals) > 0:
                raw = float(vals.iloc[-1])
                return round(raw / 10000 if abs(raw) > 1000 else raw, 2)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] North bound flow fetch failed: {e}")
            return 0.0

    def _fetch_margin_data(self) -> Tuple[float, float, float]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0
            d = (datetime.now() - timedelta(days=3)).strftime('%Y%m%d')
            try:
                df = ak.stock_margin_sse(start_date=d, end_date=d)
            except Exception:
                df = None
            if df is None or df.empty:
                try:
                    df = ak.stock_margin_szse(date=d)
                except Exception:
                    pass
            if df is None or df.empty:
                return 0.0, 0.0, 0.0
            balance_col = None
            for c in df.columns:
                if '融资余额' in c or '余额' in c:
                    balance_col = c
                    break
            if balance_col is None:
                return 0.0, 0.0, 0.0
            vals = df[balance_col].dropna()
            if len(vals) < 1:
                return 0.0, 0.0, 0.0
            current_balance = float(vals.iloc[-1])
            prev_balance = float(vals.iloc[-2]) if len(vals) >= 2 else current_balance
            change = current_balance - prev_balance
            buy_ratio = 0.0
            buy_col = None
            for c in df.columns:
                if '融资买入' in c:
                    buy_col = c
                    break
            if buy_col:
                buy_vals = df[buy_col].dropna()
                if len(buy_vals) > 0:
                    total_col = None
                    for c in df.columns:
                        if '成交金额' in c or '成交额' in c:
                            total_col = c
                            break
                    if total_col:
                        total_vals = df[total_col].dropna()
                        if len(total_vals) > 0 and float(total_vals.iloc[-1]) > 0:
                            buy_ratio = float(buy_vals.iloc[-1]) / float(total_vals.iloc[-1]) * 100
            return round(current_balance, 2), round(change, 2), round(buy_ratio, 2)
        except Exception as e:
            logger.warning(f"[MacroData] Margin data fetch failed: {e}")
            return 0.0, 0.0, 0.0

    def _fetch_main_force_flow(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.stock_individual_fund_flow_rank(indicator="今日")
            if df is None or df.empty:
                return 0.0
            col = None
            for c in df.columns:
                if '主力净流入' in c or '主力' in c:
                    col = c
                    break
            if col is None:
                return 0.0
            vals = df[col].dropna()
            if len(vals) > 0:
                return round(float(vals.sum()) / 10000, 2)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] Main force flow fetch failed: {e}")
            return 0.0

    def _fetch_industry_net_inflow(self) -> float:
        try:
            if ak is None:
                return 50.0
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
            if df is None or df.empty:
                return 50.0
            net_col = None
            for c in df.columns:
                if '净流入' in c or '净额' in c:
                    net_col = c
                    break
            if net_col is None:
                return 50.0
            vals = df[net_col].dropna()
            if len(vals) == 0:
                return 50.0
            positive_count = int((vals > 0).sum())
            total_count = len(vals)
            ratio = positive_count / total_count if total_count > 0 else 0.5
            return round(ratio * 100, 1)
        except Exception as e:
            logger.warning(f"[MacroData] Industry net inflow fetch failed: {e}")
            return 50.0

    def _fetch_pe_pb(self) -> Tuple[float, float, float, float]:
        try:
            if ak is None:
                return 0.0, 0.0, 50.0, 50.0
            pe_median, pb_median, pe_pct, pb_pct = 0.0, 0.0, 50.0, 50.0
            try:
                pe_df = ak.stock_index_pe_lg(symbol="沪深300")
                if pe_df is not None and not pe_df.empty:
                    col = None
                    for c in pe_df.columns:
                        if '滚动市盈率' in c and '等权' not in c and '中位' not in c:
                            col = c
                            break
                    if col is None:
                        for c in pe_df.columns:
                            if '市盈率' in c and '等权' not in c and '中位' not in c:
                                col = c
                                break
                    if col is None:
                        col = pe_df.columns[-1]
                    pe_vals = pe_df[col].dropna()
                    pe_vals = pe_vals[pe_vals > 0]
                    if len(pe_vals) > 0:
                        pe_median = round(float(pe_vals.iloc[-1]), 2)
                        if len(pe_vals) >= 60:
                            hist = pe_vals.iloc[-252:] if len(pe_vals) >= 252 else pe_vals
                            pe_pct = round(float((hist < pe_median).sum() / len(hist) * 100), 1)
            except Exception as e:
                logger.warning(f"[MacroData] PE fetch failed: {e}")
            try:
                pb_df = ak.stock_index_pb_lg(symbol="沪深300")
                if pb_df is not None and not pb_df.empty:
                    col = None
                    for c in pb_df.columns:
                        if '市净率' in c and '等权' not in c and '中位' not in c:
                            col = c
                            break
                    if col is None:
                        col = pb_df.columns[-1]
                    pb_vals = pb_df[col].dropna()
                    pb_vals = pb_vals[pb_vals > 0]
                    if len(pb_vals) > 0:
                        pb_median = round(float(pb_vals.iloc[-1]), 2)
                        if len(pb_vals) >= 60:
                            hist = pb_vals.iloc[-252:] if len(pb_vals) >= 252 else pb_vals
                            pb_pct = round(float((hist < pb_median).sum() / len(hist) * 100), 1)
            except Exception as e:
                logger.warning(f"[MacroData] PB fetch failed: {e}")
            return pe_median, pb_median, pe_pct, pb_pct
        except Exception as e:
            logger.warning(f"[MacroData] PE/PB fetch failed: {e}")
            return 0.0, 0.0, 50.0, 50.0

    def _fetch_industrial_output(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.macro_china_industrial_production_yoy()
            if df is None or df.empty:
                return 0.0
            col = None
            for c in df.columns:
                if '同比' in c or '增长' in c or '当月' in c:
                    col = c
                    break
            if col is None:
                col = df.columns[-1]
            vals = df[col].dropna() if col in df.columns else pd.Series()
            if len(vals) > 0:
                return round(float(vals.iloc[-1]), 1)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] Industrial output fetch failed: {e}")
            return 0.0

    def _fetch_retail_sales(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.macro_china_consumer_goods_retail()
            if df is None or df.empty:
                return 0.0
            col = None
            for c in df.columns:
                if '同比' in c or '增长' in c or '当月' in c:
                    col = c
                    break
            if col is None:
                col = df.columns[-1]
            vals = df[col].dropna() if col in df.columns else pd.Series()
            if len(vals) > 0:
                return round(float(vals.iloc[-1]), 1)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] Retail sales fetch failed: {e}")
            return 0.0

    def _fetch_export_growth(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.macro_china_exports_yoy()
            if df is None or df.empty:
                return 0.0
            col = None
            for c in df.columns:
                if '同比' in c or '增长' in c or '当月' in c:
                    col = c
                    break
            if col is None:
                col = df.columns[-1]
            vals = df[col].dropna() if col in df.columns else pd.Series()
            if len(vals) > 0:
                return round(float(vals.iloc[-1]), 1)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] Export growth fetch failed: {e}")
            return 0.0

    def _fetch_pcr_ratio(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.option_cffex_hs300_spot_sina()
            if df is None or df.empty:
                return 0.0
            if '成交量' not in df.columns:
                return 0.0
            name_col = df.get('合约名称', pd.Series(dtype=str))
            call_mask = name_col.str.contains('C|购|Call', case=False, na=False)
            put_mask = name_col.str.contains('P|沽|Put', case=False, na=False)
            call_vol = float(df.loc[call_mask, '成交量'].sum()) if call_mask.any() else 0
            put_vol = float(df.loc[put_mask, '成交量'].sum()) if put_mask.any() else 0
            if call_vol > 0:
                return round(put_vol / call_vol, 4)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] PCR ratio fetch failed: {e}")
            return 0.0

    def _fetch_vix(self) -> float:
        try:
            if ak is None:
                return 0.0
            start = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            df = ak.index_zh_a_hist(symbol="000300", period="daily", start_date=start)
            if df is None or df.empty or len(df) < 10:
                return 0.0
            if '收盘' in df.columns:
                close = df['收盘'].astype(float)
                rets = close.pct_change().dropna()
                if len(rets) >= 10:
                    vol = float(rets.tail(30).std()) * np.sqrt(252) * 100
                    return round(vol, 2)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] VIX calc failed: {e}")
            return 0.0

    def _fetch_new_accounts(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.stock_account_statistics_em()
            if df is None or df.empty:
                return 0.0
            col = None
            for c in df.columns:
                if '新增' in c or '开户' in c or '新增投资者' in c:
                    col = c
                    break
            if col is None:
                col = df.columns[-1]
            vals = df[col].dropna() if col in df.columns else pd.Series()
            if len(vals) > 0:
                return round(float(vals.iloc[-1]), 2)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] New accounts fetch failed: {e}")
            return 0.0

    def _compute_technical_indicators(self, data: MacroData) -> None:
        """从指数日线数据自动计算技术指标"""
        df = data.stock_index_df
        if df is None or df.empty or '收盘' not in df.columns:
            return
        try:
            close = df['收盘'].astype(float)
            n = len(close)
            if n < 5:
                return

            # MA排列
            if n >= 60:
                ma5 = float(close.tail(5).mean())
                ma20 = float(close.tail(20).mean())
                ma60 = float(close.tail(60).mean())
                if ma5 > ma20 > ma60:
                    data.ma_arrangement = "bullish"
                elif ma5 < ma20 < ma60:
                    data.ma_arrangement = "bearish"
                else:
                    data.ma_arrangement = "neutral"

            # MACD
            if n >= 35:
                ema12 = close.ewm(span=12, adjust=False).mean()
                ema26 = close.ewm(span=26, adjust=False).mean()
                dif = ema12 - ema26
                dea = dif.ewm(span=9, adjust=False).mean()
                macd_hist = (dif - dea) * 2
                if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
                    data.macd_signal = "bullish"
                elif dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
                    data.macd_signal = "bearish"
                elif macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2]:
                    data.macd_signal = "bullish"
                elif macd_hist.iloc[-1] < 0 and macd_hist.iloc[-1] < macd_hist.iloc[-2]:
                    data.macd_signal = "bearish"
                else:
                    data.macd_signal = "neutral"

            # RSI(14)
            if n >= 15:
                delta = close.diff()
                gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
                loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi = 100 - (100 / (1 + rs))
                data.rsi_14 = round(float(rsi.iloc[-1]), 2) if not np.isnan(rsi.iloc[-1]) else 0.0

            # 布林带位置
            if n >= 20:
                window = close.tail(20)
                mean_val = float(window.mean())
                std_val = float(window.std())
                if std_val > 0:
                    data.bollinger_position = round((float(close.iloc[-1]) - mean_val) / (2 * std_val) * 0.5 + 0.5, 4)
                    data.bollinger_position = max(0.0, min(1.0, data.bollinger_position))

            # 量比
            if '成交量' in df.columns:
                vol = df['成交量'].astype(float)
                if n >= 5 and vol.iloc[-1] > 0:
                    avg_vol = float(vol.iloc[-6:-1].mean())
                    if avg_vol > 0:
                        data.volume_ratio = round(float(vol.iloc[-1]) / avg_vol, 4)

        except Exception as e:
            logger.warning(f"[MacroData] Technical indicator computation failed: {e}")

    def _fetch_institutional_holding(self, data: MacroData) -> float:
        """从北向资金+融资余额变化间接推算机构持仓方向"""
        try:
            signals = []
            if data.north_bound_net_flow > 30:
                signals.append(1.0)
            elif data.north_bound_net_flow < -30:
                signals.append(-1.0)
            else:
                signals.append(0.0)
            if data.margin_balance_change > 50:
                signals.append(0.5)
            elif data.margin_balance_change < -50:
                signals.append(-0.5)
            else:
                signals.append(0.0)
            if not signals:
                return 0.0
            avg = sum(signals) / len(signals)
            return round(avg * 3, 2)
        except Exception as e:
            logger.warning(f"[MacroData] Institutional holding calc failed: {e}")
            return 0.0

    def _fetch_earnings_surprise(self) -> float:
        try:
            if ak is None:
                return 0.0
            from datetime import datetime
            now = datetime.now()
            candidates = []
            for q_month in [12, 9, 6, 3]:
                if now.month > q_month + 1:
                    candidates.append(f"{now.year}{q_month:02d}30")
            candidates.append(f"{now.year - 1}1230")
            candidates.append(f"{now.year - 1}0930")
            for date_str in candidates:
                try:
                    df = ak.stock_yjyg_em(date=date_str)
                    if df is not None and not df.empty:
                        type_col = None
                        for c in df.columns:
                            if '预告类型' in c:
                                type_col = c
                                break
                        if type_col is None:
                            continue
                        types = df[type_col].dropna().astype(str)
                        positive = int(types.str.contains('预增|略增|续盈|扭亏', na=False).sum())
                        negative = int(types.str.contains('预减|略减|首亏|续亏', na=False).sum())
                        total = positive + negative
                        if total > 0:
                            return round(positive / total, 4)
                        return 0.0
                except Exception:
                    continue
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] Earnings surprise fetch failed: {e}")
            return 0.0

    def _calc_industry_cycle(self, data: MacroData) -> float:
        """从宏观数据间接推算产业链景气度 0-100"""
        score = 50.0
        if data.industrial_output > 6:
            score += 10
        elif data.industrial_output > 4:
            score += 3
        elif data.industrial_output < 2:
            score -= 10
        if data.export_growth > 8:
            score += 8
        elif data.export_growth > 4:
            score += 3
        elif data.export_growth < 0:
            score -= 8
        cpi_ppi_gap = data.cpi - data.ppi if data.cpi != 2.0 or data.ppi != 0.0 else 0
        if cpi_ppi_gap > 2:
            score += 5
        elif cpi_ppi_gap < -2:
            score -= 5
        if data.pmi_current > 50:
            score += 8
        elif data.pmi_current < 48:
            score -= 8
        return round(max(0, min(100, score)), 1)

    def _calc_policy_event_scores(self, data: MacroData) -> Tuple[float, float]:
        """从市场表现间接推算政策信号和事件冲击 0-100"""
        policy = 50.0
        event = 50.0
        if data.stock_index_change > 3:
            policy += 15
            event += 10
        elif data.stock_index_change > 1:
            policy += 5
        elif data.stock_index_change < -3:
            policy -= 15
            event -= 10
        elif data.stock_index_change < -1:
            policy -= 5
        if data.credit_spread_aa > 200:
            event -= 15
        elif data.credit_spread_aa > 0 and data.credit_spread_aa < 80:
            event += 5
        if data.limit_up_count > 100 or data.limit_down_count > 100:
            event += 10 if data.limit_up_count > 100 else -10
        return round(max(0, min(100, policy)), 1), round(max(0, min(100, event)), 1)

    def invalidate_cache(self):
        """清除缓存，强制下次重新获取"""
        self._cache_time = None
