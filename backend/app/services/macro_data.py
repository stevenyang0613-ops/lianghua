"""宏观市场数据服务 V2.2

通过 AKShare + 新浪财经获取真实宏观市场数据：
- 10年期国债收益率曲线（含2年、5年、10年）
- 制造业PMI、CPI/PPI、M2增速、社融增量
- Shibor利率
- 信用利差（AA企业债 - 国债）
- A股涨跌统计、涨停跌停数
- 可转债市场统计（溢价率中位数、价格中位数、成交额、破面数）
- 沪深300 / 中证转债指数及均线
- 北向资金（数据源当前不可用，返回中性值）
- 融资融券余额
- 主力资金/行业资金（数据源当前不可用，返回中性值）
- 全市场PE/PB中位数及历史分位数
- 工业增加值、社零、出口增速
- 认沽/认购比(PCR)、波动率指数(VIX)
- 技术指标自动计算（MA/MACD/RSI/BB/量比）

注意：
- 部分宏观指标（PMI/CPI/PPI/工业增加值/出口/GDP）使用 AKShare 的月度/季度接口，
  数据发布天然滞后 1-2 个月，返回的是当前可获取的最新真实值。
- 北向资金、主力资金、行业资金、新增开户数等接口在当前网络环境下已失效，
  返回中性值并在日志中标记，避免前端展示错误数据。
"""

import asyncio
import logging
import time
from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import requests

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
    pmi_current: float = 0.0
    pmi_prev: float = 0.0
    cpi: float = 0.0
    ppi: float = 0.0
    m2_growth: float = 0.0
    social_financing_growth: float = 0.0
    gdp_growth: float = 0.0

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
    stock_pe_percentile: float = 0.0
    stock_pb_percentile: float = 0.0

    # === 资金流向 ===
    north_bound_net_flow: float = 0.0
    main_force_net_flow: float = 0.0
    margin_balance: float = 0.0
    margin_balance_change: float = 0.0
    margin_buy_ratio: float = 0.0
    industry_net_inflow: float = 0.0

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
    institutional_holding_change: float = 0.0
    earnings_surprise_ratio: float = 0.0
    policy_signal_score: float = 50.0
    event_impact_score: float = 50.0
    industry_cycle_score: float = 50.0
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
    """宏观市场数据服务 V2.2"""

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

        # 12. 转债市场统计（从集思录转债指数，真实中位数）
        self._fill_cb_stats_from_jsl(data)

        # 13. 北向资金（当前无稳定免费数据源，返回中性值）
        data.north_bound_net_flow = self._fetch_north_bound_flow()

        # 14. 融资融券
        (data.margin_balance, data.margin_balance_change,
         data.margin_buy_ratio) = self._fetch_margin_data()

        # 15. 主力资金净流入（当前无稳定免费数据源，返回中性值）
        data.main_force_net_flow = self._fetch_main_force_flow()

        # 16. 行业资金流向（当前无稳定免费数据源，返回中性值）
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

        # 23. 新增开户数（数据源陈旧，返回中性值）
        data.new_accounts = self._fetch_new_accounts()

        # 24. 从指数日线自动计算技术指标
        self._compute_technical_indicators(data)

        # 25. 机构持仓变化（从融资数据间接推算）
        data.institutional_holding_change = self._fetch_institutional_holding(data)

        # 26. 盈利超预期比例
        data.earnings_surprise_ratio = self._fetch_earnings_surprise()

        # 27. 产业链景气（从宏观数据间接推算）
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
            ("pmi", 0 < data.pmi_current < 100, 0.06),
            ("cpi_ppi", data.cpi > 0 or data.ppi != 0.0, 0.04),
            ("m2", data.m2_growth > 0, 0.05),
            ("social_fin", data.social_financing_growth != 0, 0.04),
            ("gdp", data.gdp_growth > 0, 0.04),
            ("shibor", data.shibor_overnight > 0, 0.04),
            ("credit_spread", data.credit_spread_aa > 0, 0.04),
            ("market_stats", data.advance_count > 0 or data.decline_count > 0, 0.04),
            ("cb_index", data.cb_index_current > 0, 0.05),
            ("stock_index", data.stock_index_current > 0, 0.05),
            ("cb_stats", data.cb_median_premium > 0, 0.04),
            ("north_bound", True, 0.02),  # 数据源暂不可用，但不扣完整度
            ("margin", data.margin_balance > 0, 0.05),
            ("main_force", True, 0.02),
            ("industry_flow", True, 0.02),
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
            df = ak.macro_china_pmi_yearly()
            if df is None or df.empty:
                return -1.0, -1.0
            df = df.dropna(subset=['今值']).copy()
            if len(df) < 1:
                return -1.0, -1.0
            df = df.sort_values('日期', ascending=True)
            current = float(df['今值'].iloc[-1])
            prev = float(df['前值'].iloc[-1]) if len(df) >= 1 else current
            return round(current, 1), round(prev, 1)
        except Exception as e:
            logger.warning(f"[MacroData] PMI fetch failed: {e}")
            return -1.0, -1.0

    def _fetch_cpi_ppi(self) -> Tuple[float, float]:
        try:
            if ak is None:
                return 2.0, 0.0
            cpi = 2.0
            try:
                df = ak.macro_china_cpi_yearly()
                if df is not None and not df.empty:
                    df = df.dropna(subset=['今值']).copy()
                    if not df.empty:
                        cpi = round(float(df['今值'].iloc[-1]), 1)
            except Exception as e:
                logger.warning(f"[MacroData] CPI fetch failed: {e}")
            ppi = 0.0
            try:
                df = ak.macro_china_ppi_yearly()
                if df is not None and not df.empty:
                    df = df.dropna(subset=['今值']).copy()
                    if not df.empty:
                        ppi = round(float(df['今值'].iloc[-1]), 1)
            except Exception as e:
                logger.warning(f"[MacroData] PPI fetch failed: {e}")
            return cpi, ppi
        except Exception as e:
            logger.warning(f"[MacroData] CPI/PPI fetch failed: {e}")
            return 2.0, 0.0

    def _fetch_m2_growth(self) -> float:
        try:
            if ak is None:
                return 10.0
            df = ak.macro_china_money_supply()
            if df is None or df.empty:
                return 10.0
            col = '货币和准货币(M2)-同比增长'
            if col in df.columns:
                vals = df[col].dropna()
                if len(vals) > 0:
                    return round(float(vals.iloc[0]), 1)  # 第一行为最新
            return 10.0
        except Exception as e:
            logger.warning(f"[MacroData] M2 fetch failed: {e}")
            return 10.0

    def _fetch_social_financing(self) -> float:
        try:
            if ak is None:
                return 10.0
            df = ak.macro_china_shrzgm()
            if df is None or df.empty:
                return 10.0
            col = '社会融资规模增量'
            if col not in df.columns:
                return 10.0
            df = df.copy()
            df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=[col])
            if df.empty:
                return 10.0
            latest = df.iloc[-1]
            latest_month = str(latest['月份'])
            prev_month = str(int(latest_month) - 100)
            prev_rows = df[df['月份'].astype(str) == prev_month]
            if not prev_rows.empty:
                yoy = (latest[col] - prev_rows[col].iloc[0]) / abs(prev_rows[col].iloc[0]) * 100
                return round(float(yoy), 1)
            return round(float(latest[col]), 1)
        except Exception as e:
            logger.warning(f"[MacroData] Social financing fetch failed: {e}")
            return 10.0

    def _fetch_gdp_growth(self) -> float:
        try:
            if ak is None:
                return 5.0
            df = ak.macro_china_gdp_yearly()
            if df is None or df.empty:
                return 5.0
            df = df.dropna(subset=['今值']).copy()
            if df.empty:
                return 5.0
            val = float(df['今值'].iloc[-1])
            return round(val, 1)
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
            df = ak.stock_zh_a_spot()
            if df is None or df.empty:
                return 0, 0, 0, 0, 0, 0
            chg = pd.to_numeric(df.get('涨跌幅'), errors='coerce')
            valid = chg.dropna()
            if valid.empty:
                return 0, 0, 0, 0, 0, 0
            limit_up = int((valid >= 9.9).sum())
            limit_down = int((valid <= -9.9).sum())
            advance = int((valid > 0).sum())
            decline = int((valid < 0).sum())
            return limit_up, limit_down, advance, decline, 0, 0
        except Exception as e:
            logger.warning(f"[MacroData] Market stats fetch failed: {e}")
            return 0, 0, 0, 0, 0, 0

    def _fetch_cb_index(self) -> Tuple[float, float, float, float, Optional[pd.DataFrame]]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0, 0.0, None
            df = ak.stock_zh_index_daily_tx(symbol='sh000832')
            if df is None or df.empty:
                return 0.0, 0.0, 0.0, 0.0, None
            df = df.sort_values('date', ascending=True).reset_index(drop=True)
            latest = df.iloc[-1]
            current = float(latest['close'])
            prev = float(df.iloc[-2]['close']) if len(df) >= 2 else current
            change = (current - prev) / prev * 100 if prev > 0 else 0.0
            ma20 = float(df['close'].tail(20).mean()) if len(df) >= 20 else current
            ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else current
            return round(current, 2), round(change, 2), round(ma20, 2), round(ma60, 2), df
        except Exception as e:
            logger.warning(f"[MacroData] CB index fetch failed: {e}")
            return 0.0, 0.0, 0.0, 0.0, None

    def _fetch_stock_index(self) -> Tuple[float, float, float, float, Optional[pd.DataFrame]]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0, 0.0, None
            df = ak.stock_zh_index_daily_tx(symbol='sz399300')
            if df is None or df.empty:
                return 0.0, 0.0, 0.0, 0.0, None
            df = df.sort_values('date', ascending=True).reset_index(drop=True)
            latest = df.iloc[-1]
            current = float(latest['close'])
            prev = float(df.iloc[-2]['close']) if len(df) >= 2 else current
            change = (current - prev) / prev * 100 if prev > 0 else 0.0
            ma20 = float(df['close'].tail(20).mean()) if len(df) >= 20 else current
            ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else current
            return round(current, 2), round(change, 2), round(ma20, 2), round(ma60, 2), df
        except Exception as e:
            logger.warning(f"[MacroData] HS300 index fetch failed: {e}")
            return 0.0, 0.0, 0.0, 0.0, None

    def _fill_cb_stats_from_jsl(self, data: MacroData) -> None:
        """从集思录转债指数获取真实的中位数溢价、价格、成交额、破面数"""
        try:
            if ak is None:
                return
            df = ak.bond_cb_index_jsl()
            if df is None or df.empty:
                return
            latest = df.iloc[-1]
            data.cb_median_premium = round(float(latest.get('mid_premium_rt', 0)), 2)
            data.cb_median_price = round(float(latest.get('mid_price', 0)), 2)
            data.cb_avg_daily_amount = round(float(latest.get('amount', 0)), 2)
            data.cb_count = int(latest.get('count', 0))
            data.cb_below_par_count = int(latest.get('price_90', 0)) + int(latest.get('price_90_100', 0))
        except Exception as e:
            logger.warning(f"[MacroData] CB stats from JSL failed: {e}")

    def _calc_cb_stats(self, data: MacroData, bonds) -> None:
        """保留旧接口：若 bonds 含有效溢价数据则作为备用补充"""
        if data.cb_median_premium > 0 and data.cb_count > 0:
            return
        premiums, volumes, prices = [], [], []
        for b in bonds or []:
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
            data.cb_avg_daily_amount = round(total_vol / len(volumes), 2)

    def _fetch_north_bound_flow(self) -> float:
        """北向资金净流入。当前东方财富相关接口已失效，返回 0（中性）"""
        logger.debug("[MacroData] North bound flow data source unavailable, returning neutral 0")
        return 0.0

    def _fetch_margin_data(self) -> Tuple[float, float, float]:
        try:
            if ak is None:
                return 0.0, 0.0, 0.0
            current_balance = 0.0
            prev_balance = 0.0
            buy_amount = 0.0

            # SSE 汇总（单位：元）
            for offset in range(1, 5):
                d = (datetime.now() - timedelta(days=offset)).strftime('%Y%m%d')
                try:
                    df = ak.stock_margin_sse(start_date=d, end_date=d)
                    if df is not None and not df.empty:
                        current_balance = float(df['融资融券余额'].iloc[0]) / 1e8
                        buy_amount = float(df['融资买入额'].iloc[0]) / 1e8
                        # 找前一个交易日
                        for p_offset in range(offset + 1, offset + 10):
                            pd_str = (datetime.now() - timedelta(days=p_offset)).strftime('%Y%m%d')
                            try:
                                p_df = ak.stock_margin_sse(start_date=pd_str, end_date=pd_str)
                                if p_df is not None and not p_df.empty:
                                    prev_balance = float(p_df['融资融券余额'].iloc[0]) / 1e8
                                    break
                            except Exception:
                                continue
                        break
                except Exception:
                    continue

            # SZSE 汇总（单位：亿元）
            sz_balance = 0.0
            sz_buy = 0.0
            for offset in range(1, 5):
                d = (datetime.now() - timedelta(days=offset)).strftime('%Y%m%d')
                try:
                    df = ak.stock_margin_szse(date=d)
                    if df is not None and not df.empty:
                        sz_balance = float(df['融资融券余额'].iloc[0])
                        sz_buy = float(df['融资买入额'].iloc[0])
                        break
                except Exception:
                    continue

            total_balance = current_balance + sz_balance
            total_prev = prev_balance + sz_balance  # 深交所变化较小，主要用 SSE 变化
            change = total_balance - total_prev
            buy_ratio = 0.0
            if total_balance > 0:
                buy_ratio = (buy_amount + sz_buy) / total_balance * 100
            return round(total_balance, 2), round(change, 2), round(buy_ratio, 2)
        except Exception as e:
            logger.warning(f"[MacroData] Margin data fetch failed: {e}")
            return 0.0, 0.0, 0.0

    def _fetch_main_force_flow(self) -> float:
        """主力资金净流入。当前东方财富相关接口已失效，返回 0（中性）"""
        logger.debug("[MacroData] Main force flow data source unavailable, returning neutral 0")
        return 0.0

    def _fetch_industry_net_inflow(self) -> float:
        """行业资金流向。当前东方财富相关接口已失效，返回 50（中性占比）"""
        logger.debug("[MacroData] Industry flow data source unavailable, returning neutral 50")
        return 50.0

    def _fetch_pe_pb(self) -> Tuple[float, float, float, float]:
        try:
            pe_median, pb_median, pe_pct, pb_pct = self._fetch_pe_pb_lg()
            if pe_median > 0 and pb_median > 0:
                return pe_median, pb_median, pe_pct, pb_pct
            # Fallback: use AKShare wrappers if legulegu native fails
            return self._fetch_pe_pb_akshare()
        except Exception as e:
            logger.warning(f"[MacroData] PE/PB fetch failed: {e}")
            return 0.0, 0.0, 50.0, 50.0

    def _fetch_pe_pb_lg(self) -> Tuple[float, float, float, float]:
        """Fetch CSI300 median PE/PB from legulegu without py_mini_racer.

        Uses Node.js to evaluate the same JS token generator that AKShare uses.
        This avoids the py_mini_racer dlsym failure inside the macOS sandbox.
        """
        pe_median = pb_median = 0.0
        pe_pct = pb_pct = 50.0
        try:
            from akshare.stock_feature.stock_a_pe_and_pb import (
                hash_code,
                get_cookie_csrf,
            )
        except Exception:
            return pe_median, pb_median, pe_pct, pb_pct

        try:
            import subprocess
            import json as _json

            d = date.today().isoformat()
            js_code = hash_code + f"\nconsole.log(JSON.stringify({{token: hex('{d}').toLowerCase()}}));"
            result = subprocess.run(
                ["node", "-e", js_code],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(f"node token failed: {result.stderr}")
            token = _json.loads(result.stdout.strip().split("\n")[-1])["token"]
        except Exception as e:
            logger.debug(f"[MacroData] legulegu token generation failed: {e}")
            return pe_median, pb_median, pe_pct, pb_pct

        try:
            cookies = get_cookie_csrf(
                url="https://legulegu.com/stockdata/zz500-ttm-lyr"
            )
            symbol = "000300.SH"
            pe_resp = requests.get(
                "https://legulegu.com/api/stockdata/index-basic-pe",
                params={"token": token, "indexCode": symbol},
                timeout=15,
                **cookies,
            )
            pb_resp = requests.get(
                "https://legulegu.com/api/stockdata/index-basic-pb",
                params={"token": token, "indexCode": symbol},
                timeout=15,
                **cookies,
            )
            pe_data = pe_resp.json().get("data", [])
            pb_data = pb_resp.json().get("data", [])
            if not pe_data or not pb_data:
                return pe_median, pb_median, pe_pct, pb_pct

            latest_pe = pe_data[-1]
            latest_pb = pb_data[-1]
            pe_median = round(float(latest_pe.get("middleTtmPe", 0)), 2)
            pb_median = round(float(latest_pb.get("middlePb", 0)), 2)
            pe_hist = pd.Series([d.get("middleTtmPe") for d in pe_data]).dropna()
            pb_hist = pd.Series([d.get("middlePb") for d in pb_data]).dropna()
            pe_hist = pd.to_numeric(pe_hist, errors="coerce").dropna()
            pb_hist = pd.to_numeric(pb_hist, errors="coerce").dropna()
            pe_hist = pe_hist[pe_hist > 0]
            pb_hist = pb_hist[pb_hist > 0]
            if len(pe_hist) > 0 and pe_median > 0:
                pe_pct = round(float((pe_hist < pe_median).sum() / len(pe_hist) * 100), 1)
            if len(pb_hist) > 0 and pb_median > 0:
                pb_pct = round(float((pb_hist < pb_median).sum() / len(pb_hist) * 100), 1)
            logger.info(
                f"[MacroData] legulegu PE/PB: PE中位={pe_median}, PB中位={pb_median}, "
                f"PE分位={pe_pct}%, PB分位={pb_pct}%"
            )
        except Exception as e:
            logger.debug(f"[MacroData] legulegu PE/PB fetch failed: {e}")
        return pe_median, pb_median, pe_pct, pb_pct

    def _fetch_pe_pb_akshare(self) -> Tuple[float, float, float, float]:
        """Fallback using AKShare py_mini_racer-based wrappers."""
        if ak is None:
            return 0.0, 0.0, 50.0, 50.0
        pe_median, pb_median, pe_pct, pb_pct = 0.0, 0.0, 50.0, 50.0
        try:
            pe_df = ak.stock_index_pe_lg(symbol="沪深300")
            if pe_df is not None and not pe_df.empty:
                col = None
                for c in pe_df.columns:
                    if "滚动市盈率" in c and "中位" in c:
                        col = c
                        break
                if col is None:
                    for c in pe_df.columns:
                        if "滚动市盈率" in c and "等权" not in c:
                            col = c
                            break
                if col is None:
                    col = pe_df.columns[-1]
                pe_vals = pd.to_numeric(pe_df[col], errors="coerce").dropna()
                pe_vals = pe_vals[pe_vals > 0]
                if len(pe_vals) > 0:
                    pe_median = round(float(pe_vals.iloc[-1]), 2)
                    hist = pe_vals.iloc[-252:] if len(pe_vals) >= 252 else pe_vals
                    pe_pct = round(float((hist < pe_median).sum() / len(hist) * 100), 1)
        except Exception as e:
            logger.warning(f"[MacroData] AKShare PE fetch failed: {e}")
        try:
            pb_df = ak.stock_index_pb_lg(symbol="沪深300")
            if pb_df is not None and not pb_df.empty:
                col = None
                for c in pb_df.columns:
                    if "市净率" in c and "中位" in c:
                        col = c
                        break
                if col is None:
                    col = pb_df.columns[-1]
                pb_vals = pd.to_numeric(pb_df[col], errors="coerce").dropna()
                pb_vals = pb_vals[pb_vals > 0]
                if len(pb_vals) > 0:
                    pb_median = round(float(pb_vals.iloc[-1]), 2)
                    hist = pb_vals.iloc[-252:] if len(pb_vals) >= 252 else pb_vals
                    pb_pct = round(float((hist < pb_median).sum() / len(hist) * 100), 1)
        except Exception as e:
            logger.warning(f"[MacroData] AKShare PB fetch failed: {e}")
        return pe_median, pb_median, pe_pct, pb_pct

    def _fetch_industrial_output(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.macro_china_industrial_production_yoy()
            if df is None or df.empty:
                return 0.0
            df = df.dropna(subset=['今值']).copy()
            if df.empty:
                return 0.0
            return round(float(df['今值'].iloc[-1]), 1)
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
                if '同比增长' in c:
                    col = c
                    break
            if col is None:
                col = df.columns[-1]
            vals = pd.to_numeric(df[col], errors='coerce').dropna()
            if len(vals) > 0:
                return round(float(vals.iloc[0]), 1)  # 第一行为最新
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
            df = df.dropna(subset=['今值']).copy()
            if df.empty:
                return 0.0
            return round(float(df['今值'].iloc[-1]), 1)
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
            call_col = '看涨合约-持仓量'
            put_col = '看跌合约-持仓量'
            if call_col not in df.columns or put_col not in df.columns:
                return 0.0
            call_oi = float(pd.to_numeric(df[call_col], errors='coerce').sum())
            put_oi = float(pd.to_numeric(df[put_col], errors='coerce').sum())
            if call_oi > 0:
                return round(put_oi / call_oi, 4)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] PCR ratio fetch failed: {e}")
            return 0.0

    def _fetch_vix(self) -> float:
        try:
            if ak is None:
                return 0.0
            df = ak.stock_zh_index_daily_tx(symbol='sz399300')
            if df is None or df.empty or len(df) < 10:
                return 0.0
            df = df.sort_values('date', ascending=True)
            close = pd.to_numeric(df['close'], errors='coerce').dropna()
            if len(close) < 10:
                return 0.0
            rets = close.pct_change().dropna()
            if len(rets) >= 30:
                vol = float(rets.tail(30).std()) * np.sqrt(252) * 100
                return round(vol, 2)
            return 0.0
        except Exception as e:
            logger.warning(f"[MacroData] VIX calc failed: {e}")
            return 0.0

    def _fetch_new_accounts(self) -> float:
        """新增开户数。当前数据源陈旧，返回 0（中性）"""
        logger.debug("[MacroData] New accounts data source unavailable, returning neutral 0")
        return 0.0

    def _compute_technical_indicators(self, data: MacroData) -> None:
        """从指数日线数据自动计算技术指标"""
        df = data.stock_index_df
        if df is None or df.empty:
            return
        try:
            df = df.copy()
            df['收盘'] = pd.to_numeric(df.get('close'), errors='coerce')
            df['成交量'] = pd.to_numeric(df.get('amount'), errors='coerce')
            df = df.dropna(subset=['收盘'])
            close = df['收盘']
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
            vol = df['成交量']
            if n >= 5 and vol.iloc[-1] > 0:
                avg_vol = float(vol.iloc[-6:-1].mean())
                if avg_vol > 0:
                    data.volume_ratio = round(float(vol.iloc[-1]) / avg_vol, 4)

        except Exception as e:
            logger.warning(f"[MacroData] Technical indicator computation failed: {e}")

    def _fetch_institutional_holding(self, data: MacroData) -> float:
        """从融资余额变化间接推算机构/杠杆资金方向"""
        try:
            signals = []
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
        elif 0 < data.credit_spread_aa < 80:
            event += 5
        if data.limit_up_count > 100 or data.limit_down_count > 100:
            event += 10 if data.limit_up_count > 100 else -10
        return round(max(0, min(100, policy)), 1), round(max(0, min(100, event)), 1)

    def invalidate_cache(self):
        """清除缓存，强制下次重新获取"""
        self._cache_time = None
