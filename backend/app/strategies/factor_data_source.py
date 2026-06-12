"""
因子数据源模块

接入外部数据源（AKShare）：
- 行业PMI/景气度数据 (macro_china_pmi + sw_index_third_info)
- 行业景气度排名
- 大股东质押率 (stock_gpzy_pledge_ratio_em)
- 财务指标 (stock_zyjs_ths 个股主要指标)
- 市场情绪指标 (ak.stock_market_activity_legu + stock_zt_pool_em)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np
import logging
import threading
import time

try:
    import akshare as ak
except ImportError:
    ak = None

logger = logging.getLogger(__name__)

_CACHE_DIR_FACTOR = None
_INDUSTRY_PMI_FILE = "factor_industry_pmi.json"
_FIN_INDICATOR_FILE = "factor_fin_indicator.json"
_PLEDGE_FILE = "factor_pledge.json"
_MARKET_SENTIMENT_FILE = "factor_market_sentiment.json"


@dataclass
class FactorData:
    """因子数据"""
    code: str
    name: str
    factor_type: str
    factor_value: float
    factor_date: str
    source: str
    confidence: float = 1.0


class FactorDataSource:
    """因子数据源"""

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}
        self._cache_ts: dict[str, datetime] = {}
        self._cache_ttl = timedelta(hours=1)

    def _is_cache_valid(self, key: str) -> bool:
        """检查缓存是否有效"""
        if key not in self._cache_ts:
            return False
        return datetime.now() - self._cache_ts[key] < self._cache_ttl

    # ==================== 行业数据 ====================

    _industry_pmi_map: dict[str, float] = {}
    _industry_pmi_ts: float = 0.0
    _industry_pmi_lock = threading.Lock()

    def _refresh_industry_pmi(self) -> dict[str, float]:
        """从申万行业指数 + 制造业 PMI 推导行业景气度"""
        if not ak:
            return {}
        with self._industry_pmi_lock:
            if time.time() - self._industry_pmi_ts < 3600 and self._industry_pmi_map:
                return self._industry_pmi_map
            try:
                base_pmi = 50.0
                try:
                    pmi_df = ak.macro_china_pmi()
                    if pmi_df is not None and not pmi_df.empty:
                        latest = pmi_df.iloc[0]
                        for col in ['今值', '制造业PMI', 'value', 'pmi']:
                            if col in latest.index:
                                v = latest[col]
                                if pd.notna(v) and isinstance(v, (int, float)) and 30 < v < 70:
                                    base_pmi = float(v)
                                    break
                except Exception as e:
                    logger.debug(f"[FactorDS] PMI 拉取失败, 使用基线: {e}")

                sw_df = ak.sw_index_third_info() if hasattr(ak, 'sw_index_third_info') else None
                result: dict[str, float] = {}
                if sw_df is not None and not sw_df.empty:
                    industry_codes = sw_df['行业代码'].astype(str).unique() if '行业代码' in sw_df.columns else []
                    import random
                    for code in industry_codes[:50]:
                        try:
                            hist = ak.sw_index_third_info(index_code=code) if False else None
                        except Exception:
                            hist = None
                        row = sw_df[sw_df['行业代码'].astype(str) == str(code)].iloc[0]
                        name = str(row.get('行业名称', code))
                        pe = row.get('静态市盈率-加权平均', None)
                        if pe is not None and pd.notna(pe) and isinstance(pe, (int, float)):
                            offset = max(-5.0, min(5.0, (50.0 - float(pe)) * 0.1))
                            result[name] = round(base_pmi + offset, 2)
                self._industry_pmi_map = result
                self._industry_pmi_ts = time.time()
                logger.info(f"[FactorDS] 行业景气度: {len(result)} 个行业, base_pmi={base_pmi}")
                return result
            except Exception as e:
                logger.warning(f"[FactorDS] 行业 PMI 刷新失败: {e}")
                return self._industry_pmi_map

    def get_industry_pmi(self, industry: str) -> Optional[float]:
        """
        获取行业景气度评分

        数据来源：申万行业指数 + 制造业 PMI
        """
        if not industry:
            return None
        if not self._industry_pmi_map:
            self._refresh_industry_pmi()
        for k, v in self._industry_pmi_map.items():
            if industry in k or k in industry:
                return v
        return 50.0

    def get_industry_ranking(self, date: str = None) -> pd.DataFrame:
        """
        获取行业景气度排名（来自申万一级行业涨跌幅）

        返回：DataFrame with columns [industry, rank, score, trend]
        """
        if not ak:
            return pd.DataFrame(columns=['industry', 'rank', 'score', 'trend', 'pmi'])
        try:
            if not self._industry_pmi_map:
                self._refresh_industry_pmi()

            sw_df = ak.sw_index_first_info()
            if sw_df is None or sw_df.empty:
                return pd.DataFrame(columns=['industry', 'rank', 'score', 'trend', 'pmi'])

            scores = []
            for _, row in sw_df.iterrows():
                name = str(row.get('行业名称', row.get('名称', '')))
                change_pct = row.get('涨跌幅', None) or row.get('今日涨跌幅', None)
                if change_pct is None or pd.isna(change_pct):
                    change_pct = 0.0
                pmi = self.get_industry_pmi(name) or 50.0
                score = max(0, min(100, (pmi - 50) * 5 + 50 + float(change_pct) * 3))
                scores.append({
                    'industry': name,
                    'pmi': pmi,
                    'score': round(score, 1),
                    'change_pct': float(change_pct),
                    'trend': 'up' if pmi > 52 else 'down' if pmi < 48 else 'neutral',
                })

            df = pd.DataFrame(scores)
            df = df.sort_values('score', ascending=False).reset_index(drop=True)
            df['rank'] = df.index + 1
            return df
        except Exception as e:
            logger.warning(f"[FactorDS] 行业排名失败: {e}")
            return pd.DataFrame(columns=['industry', 'rank', 'score', 'trend', 'pmi'])

    # ==================== 股东数据 ====================

    _pledge_map: dict[str, float] = {}
    _pledge_ts: float = 0.0
    _pledge_lock = threading.Lock()

    def _refresh_pledge(self):
        """从东方财富全市场质押数据刷新"""
        if not ak or not hasattr(ak, 'stock_gpzy_pledge_ratio_em'):
            return
        with self._pledge_lock:
            if time.time() - self._pledge_ts < 3600 and self._pledge_map:
                return
            try:
                from datetime import datetime
                today = datetime.now().strftime("%Y%m%d")
                for offset in range(7):
                    date_str = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
                    try:
                        df = ak.stock_gpzy_pledge_ratio_em(date=date_str)
                        if df is not None and not df.empty:
                            for _, r in df.iterrows():
                                code = str(r.get("股票代码", "")).strip()
                                pct = r.get("质押比例", None)
                                if code and pct is not None and pd.notna(pct):
                                    try:
                                        self._pledge_map[code] = float(pct)
                                    except (ValueError, TypeError):
                                        pass
                            break
                    except Exception:
                        continue
                self._pledge_ts = time.time()
                logger.info(f"[FactorDS] 质押比例: {len(self._pledge_map)} 股票")
            except Exception as e:
                logger.warning(f"[FactorDS] 质押数据刷新失败: {e}")

    def get_shareholder_pledge_ratio(self, code: str) -> Optional[float]:
        """
        获取大股东质押率(%)
        数据来源：东方财富 stock_gpzy_pledge_ratio_em
        """
        if not code:
            return None
        if not self._pledge_map:
            self._refresh_pledge()
        for prefix in (code, code[2:] if code.startswith(('sh', 'sz', 'bj')) else code):
            if prefix in self._pledge_map:
                return self._pledge_map[prefix]
        return None

    def get_guarantee_ratio(self, code: str) -> Optional[float]:
        """
        获取对外担保比例(%)
        数据来源：上市公司临时公告(ak.stock_company_notice_report_em)
        """
        if not code or not ak or not hasattr(ak, 'stock_company_notice_report_em'):
            return None
        try:
            from app.services.enrichment_finance import fetch_guarantee_ratio
            return fetch_guarantee_ratio(code)
        except Exception:
            return None

    # ==================== 财务指标 ====================

    def get_financial_indicators(self, code: str) -> dict:
        """
        获取财务指标（来自同花顺个股主要指标 stock_zyjs_ths）
        """
        if not code or not ak:
            return {}
        clean = code[2:] if code.startswith(('sh', 'sz', 'bj')) else code
        try:
            df = ak.stock_zyjs_ths(symbol=clean)
            if df is None or df.empty:
                return {}
            result = {}
            for _, r in df.iterrows():
                name = str(r.get('指标', ''))
                value = r.get('值', None)
                if value is None or pd.isna(value):
                    continue
                try:
                    fv = float(value)
                except (ValueError, TypeError):
                    continue
                if '资产负债率' in name:
                    result['asset_liability_ratio'] = fv
                elif name in ('流动比率',):
                    result['current_ratio'] = fv
                elif name in ('速动比率',):
                    result['quick_ratio'] = fv
                elif '经营现金流' in name or '经营活动现金流' in name:
                    result['operating_cashflow'] = fv
                elif 'ROE' in name or '净资产收益率' in name:
                    result['roe'] = fv
                elif '毛利率' in name:
                    result['gross_margin'] = fv
                elif '净利润' in name and '增长' in name:
                    result['net_profit_growth'] = fv
            return result
        except Exception as e:
            logger.debug(f"[FactorDS] {code} 财务指标拉取失败: {e}")
            return {}

    # ==================== 市场数据 ====================

    _market_sentiment_cache: dict = {}
    _market_sentiment_ts: float = 0.0
    _market_sentiment_lock = threading.Lock()

    def get_market_sentiment(self) -> dict:
        """
        市场情绪指标（来自东方财富涨跌停 + 实时行情聚合）
        """
        if not ak:
            return {}
        with self._market_sentiment_lock:
            if time.time() - self._market_sentiment_ts < 60 and self._market_sentiment_cache:
                return self._market_sentiment_cache
            try:
                from datetime import datetime
                today_str = datetime.now().strftime("%Y%m%d")
                limit_up = 0
                limit_down = 0
                try:
                    zt_df = ak.stock_zt_pool_em(date=today_str)
                    if zt_df is not None and not zt_df.empty:
                        limit_up = len(zt_df)
                except Exception:
                    pass
                try:
                    dt_df = ak.stock_zt_pool_dtgc_em(date=today_str)
                    if dt_df is not None and not dt_df.empty:
                        limit_down = len(dt_df)
                except Exception:
                    pass

                advance = 0
                decline = 0
                total_turnover = 0.0
                stock_count = 0
                try:
                    spot_df = ak.stock_zh_a_spot()
                    if spot_df is not None and not spot_df.empty:
                        for _, r in spot_df.iterrows():
                            code = str(r.get('代码', ''))
                            if not code or code.startswith('bj'):
                                continue
                            ch = r.get('涨跌幅', 0)
                            try:
                                ch = float(ch)
                            except (ValueError, TypeError):
                                continue
                            if ch > 0:
                                advance += 1
                            elif ch < 0:
                                decline += 1
                            stock_count += 1
                except Exception:
                    pass

                result = {
                    'advance_decline_ratio': round(advance / decline, 2) if decline > 0 else 0.0,
                    'limit_up_count': limit_up,
                    'limit_down_count': limit_down,
                    'advance_count': advance,
                    'decline_count': decline,
                    'stock_count': stock_count,
                }
                self._market_sentiment_cache = result
                self._market_sentiment_ts = time.time()
                return result
            except Exception as e:
                logger.warning(f"[FactorDS] 市场情绪刷新失败: {e}")
                return self._market_sentiment_cache

    def get_bond_market_stats(self) -> dict:
        """
        转债市场统计（从当前内存中的 quotes 实时聚合）
        """
        try:
            from app.main import market_engine
            quotes = []
            if market_engine is not None:
                try:
                    quotes = list(market_engine.get_quotes() or [])
                except Exception:
                    quotes = []
            if not quotes:
                return {
                    'total_count': 0,
                    'avg_premium': 0.0,
                    'median_premium': 0.0,
                    'avg_price': 0.0,
                    'total_volume': 0.0,
                }
            premiums = [float(getattr(q, 'premium_ratio', 0) or 0) for q in quotes]
            prices = [float(getattr(q, 'price', 0) or 0) for q in quotes]
            volumes = [float(getattr(q, 'volume', 0) or 0) for q in quotes]
            sorted_p = sorted(premiums)
            median = sorted_p[len(sorted_p) // 2] if sorted_p else 0.0
            return {
                'total_count': len(quotes),
                'avg_premium': round(sum(premiums) / len(premiums), 2) if premiums else 0.0,
                'median_premium': round(median, 2),
                'avg_price': round(sum(prices) / len(prices), 2) if prices else 0.0,
                'total_volume': round(sum(volumes), 2),
            }
        except Exception as e:
            logger.debug(f"[FactorDS] 转债市场统计失败: {e}")
            return {}

    # ==================== 因子计算 ====================

    def calc_composite_factor(
        self,
        code: str,
        factor_weights: dict[str, float],
    ) -> float:
        """
        计算综合因子得分

        factor_weights: 各因子权重
        """
        scores = {}

        # 获取各因子数据
        financial = self.get_financial_indicators(code)

        # 财务因子评分
        if financial['asset_liability_ratio'] < 50:
            scores['debt'] = 100
        elif financial['asset_liability_ratio'] < 70:
            scores['debt'] = 50
        else:
            scores['debt'] = 0

        if financial['current_ratio'] > 2:
            scores['liquidity'] = 100
        elif financial['current_ratio'] > 1:
            scores['liquidity'] = 50
        else:
            scores['liquidity'] = 0

        if financial['net_profit_growth'] > 20:
            scores['growth'] = 100
        elif financial['net_profit_growth'] > 0:
            scores['growth'] = 50
        else:
            scores['growth'] = 0

        # 股东因子评分
        pledge = self.get_shareholder_pledge_ratio(code)
        if pledge < 30:
            scores['pledge'] = 100
        elif pledge < 60:
            scores['pledge'] = 50
        else:
            scores['pledge'] = 0

        guarantee = self.get_guarantee_ratio(code)
        if guarantee < 10:
            scores['guarantee'] = 100
        elif guarantee < 30:
            scores['guarantee'] = 50
        else:
            scores['guarantee'] = 0

        # 加权平均
        total_weight = sum(factor_weights.values())
        if total_weight == 0:
            return 50

        composite = sum(
            scores.get(k, 50) * v
            for k, v in factor_weights.items()
        ) / total_weight

        return round(composite, 2)

    def get_factor_exposure(
        self,
        codes: list[str],
        factors: list[str],
    ) -> pd.DataFrame:
        """
        获取多只转债的因子暴露

        返回：DataFrame with index=code, columns=factors
        """
        data = []
        for code in codes:
            row = {'code': code}
            financial = self.get_financial_indicators(code)

            for factor in factors:
                if factor == 'debt':
                    row[factor] = financial['asset_liability_ratio']
                elif factor == 'liquidity':
                    row[factor] = financial['current_ratio']
                elif factor == 'growth':
                    row[factor] = financial['net_profit_growth']
                elif factor == 'roe':
                    row[factor] = financial['roe']
                elif factor == 'pledge':
                    row[factor] = self.get_shareholder_pledge_ratio(code) or 0
                elif factor == 'guarantee':
                    row[factor] = self.get_guarantee_ratio(code) or 0

            data.append(row)

        return pd.DataFrame(data).set_index('code')

    # ==================== 数据更新 ====================

    def update_cache(self, code: str, data: pd.DataFrame) -> None:
        """更新缓存"""
        self._cache[code] = data
        self._cache_ts[code] = datetime.now()

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()
        self._cache_ts.clear()
