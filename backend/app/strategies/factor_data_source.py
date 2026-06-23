"""
因子数据源模块

接入外部数据源（AKShare + 妙想 MX）：
- 行业PMI/景气度数据 (macro_china_pmi + sw_index_third_info)
- 行业景气度排名
- 大股东质押率 (stock_gpzy_pledge_ratio_em)
- 财务指标 (stock_zyjs_ths 个股主要指标)
- 市场情绪指标 (ak.stock_market_activity_legu + stock_zt_pool_em)
- 妙想 MX (东方财富官方 API) — 补充因子数据查询
  - mx-data: 自然语言查询财务/行业/估值因子
  - mx-search: 资讯搜索辅助情绪判断
  - 需 MX_APIKEY 配置
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np
import logging
import threading
import time
from app.engine.data_enrich_utils import safe_float, safe_int

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
        """行业景气度：聚合 enrichment 行业缓存的 PE/PB/ROE 数据，辅以 PMI 基准"""
        with self._industry_pmi_lock:
            if time.time() - self._industry_pmi_ts < 3600 and self._industry_pmi_map:
                return self._industry_pmi_map
            try:
                from app.engine import data_enrich as _de

                # 使用公共 API 获取批量数据快照，避免直接访问内部缓存
                _spot_data = _de.get_all_spot_data()
                _fin_data = _de.get_all_fin_data()
                _industry_data = _de.get_all_industry_map()

                industry_pe: dict[str, list[float]] = {}
                for sc, info in list(_spot_data.items()):
                    if not isinstance(info, dict):
                        continue
                    pe = info.get("pe")
                    if pe is None or not (5 < float(pe) < 200):
                        continue
                    ind = _industry_data.get(str(sc).strip())
                    if not ind:
                        continue
                    industry_pe.setdefault(ind, []).append(float(pe))

                industry_roe: dict[str, list[float]] = {}
                for sc, info in list(_fin_data.items()):
                    if not isinstance(info, dict):
                        continue
                    roe = info.get("roe")
                    if roe is None:
                        continue
                    ind = _industry_data.get(str(sc).strip())
                    if not ind:
                        continue
                    industry_roe.setdefault(ind, []).append(float(roe))

                result: dict[str, float] = {}
                for ind, pes in industry_pe.items():
                    avg_pe = sum(pes) / len(pes)
                    roes = industry_roe.get(ind, [])
                    avg_roe = sum(roes) / len(roes) if roes else 0.0
                    pe_score = max(0, min(50, 50 - (avg_pe - 30) * 0.5))
                    roe_score = max(0, min(50, avg_roe * 2))
                    result[ind] = round(50 + (pe_score + roe_score - 50) * 0.2, 2)

                if not result and ak:
                    base_pmi = 50.0
                    try:
                        pmi_df = ak.macro_china_pmi()
                        if pmi_df is not None and not pmi_df.empty:
                            for col in ['今值', '制造业PMI', 'value']:
                                if col in pmi_df.columns:
                                    v = pmi_df.iloc[0][col]
                                    if pd.notna(v) and 30 < float(v) < 70:
                                        base_pmi = float(v)
                                        break
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass
                    result = {"default": base_pmi}

                self._industry_pmi_map = result
                self._industry_pmi_ts = time.time()
                logger.info(f"[FactorDS] 行业景气度: {len(result)} 个行业 (聚合 enrichment)")
                return result
            except Exception as e:
                logger.warning(f"[FactorDS] 行业景气度刷新失败: {e}")
                return self._industry_pmi_map

    def get_industry_pmi(self, industry: str) -> Optional[float]:
        """获取行业景气度评分 (基于 enrichment 缓存的 PE/ROE 聚合)"""
        if not industry:
            return None
        if not self._industry_pmi_map:
            self._refresh_industry_pmi()
        if industry in self._industry_pmi_map:
            return self._industry_pmi_map[industry]
        for k, v in self._industry_pmi_map.items():
            if industry in k or k in industry:
                return v
        return 50.0

    def get_industry_ranking(self, date: str = None) -> pd.DataFrame:
        """
        获取行业景气度排名（基于 enrichment 行业缓存聚合）

        返回：DataFrame with columns [industry, rank, score, trend, pe, roe, stock_count]
        """
        try:
            from app.engine import data_enrich as _de
            if not self._industry_pmi_map:
                self._refresh_industry_pmi()

            # 使用公共 API 获取批量数据快照
            _spot_data = _de.get_all_spot_data()
            _fin_data = _de.get_all_fin_data()
            _industry_data = _de.get_all_industry_map()

            industry_stats: dict[str, dict] = {}
            for sc, info in list(_spot_data.items()):
                if not isinstance(info, dict):
                    continue
                pe = info.get("pe")
                ind = _industry_data.get(str(sc).strip())
                if not ind:
                    continue
                stats = industry_stats.setdefault(ind, {"pe": [], "change_pct": [], "count": 0})
                if pe is not None and 5 < float(pe) < 200:
                    stats["pe"].append(float(pe))
                ch = info.get("change_pct")
                if ch is not None:
                    stats["change_pct"].append(float(ch))
                stats["count"] += 1

            for sc, info in list(_fin_data.items()):
                if not isinstance(info, dict):
                    continue
                roe = info.get("roe")
                ind = _industry_data.get(str(sc).strip())
                if not ind or roe is None:
                    continue
                stats = industry_stats.setdefault(ind, {"pe": [], "change_pct": [], "count": 0})
                stats.setdefault("roe", []).append(float(roe))

            scores = []
            for name, s in industry_stats.items():
                avg_pe = sum(s["pe"]) / len(s["pe"]) if s["pe"] else 25.0
                avg_chg = sum(s["change_pct"]) / len(s["change_pct"]) if s["change_pct"] else 0.0
                pmi = self._industry_pmi_map.get(name, 50.0)
                score = max(0, min(100, pmi * 1.0 - (avg_pe - 25) * 0.3 + avg_chg * 2))
                scores.append({
                    'industry': name,
                    'pmi': pmi,
                    'pe': round(avg_pe, 2),
                    'change_pct': round(avg_chg, 2),
                    'stock_count': s["count"],
                    'score': round(score, 1),
                    'trend': 'up' if avg_chg > 0.5 else 'down' if avg_chg < -0.5 else 'neutral',
                })

            if not scores:
                return pd.DataFrame(columns=['industry', 'rank', 'score', 'trend', 'pmi', 'pe', 'change_pct', 'stock_count'])

            df = pd.DataFrame(scores)
            df = df.sort_values('score', ascending=False).reset_index(drop=True)
            df['rank'] = df.index + 1
            return df
        except Exception as e:
            logger.warning(f"[FactorDS] 行业排名失败: {e}")
            return pd.DataFrame(columns=['industry', 'rank', 'score', 'trend', 'pmi', 'pe', 'change_pct', 'stock_count'])

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
                df = ak.stock_gpzy_pledge_ratio_em()
                if df is not None and not df.empty:
                    for _, r in df.iterrows():
                        code = str(r.get("股票代码", "")).strip()
                        pct = r.get("质押比例", None)
                        if code and pct is not None and pd.notna(pct):
                            try:
                                self._pledge_map[code] = float(pct)
                            except (ValueError, TypeError):
                                pass
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
        except Exception as e:
            logger.debug(f"[FactorDataSource] fetch_guarantee_ratio failed: {e}")
            return None

    # ==================== 财务指标 ====================

    def get_financial_indicators(self, code: str) -> dict:
        """
        获取财务指标（来自同花顺个股主要指标 stock_zyjs_ths）
        当 THS 失败时，兜底妙想 MX 自然语言查询
        """
        if not code or not ak:
            return {}
        prefix = code[:2].lower()
        clean = code[2:] if prefix in ('sh', 'sz', 'bj') and len(code) > 2 else code
        try:
            df = ak.stock_zyjs_ths(symbol=clean)
            if df is None or df.empty:
                return self._get_financial_indicators_mx(code)
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
            logger.debug(f"[FactorDS] {code} THS 财务指标拉取失败: {e}, 尝试 MX 兜底")
            return self._get_financial_indicators_mx(code)

    def _get_financial_indicators_mx(self, code: str) -> dict:
        """通过妙想 MX 自然语言查询获取财务指标 (fallback)"""
        try:
            import asyncio
            from app.data.adapters.mx_adapter import MXAdapter
            from app.data.adapters.base import DataSourceConfig

            async def _query():
                mx = MXAdapter(DataSourceConfig(name="mx"))
                await mx.connect()
                query_text = f"{code} 资产负债率 流动比率 速动比率 净资产收益率 毛利率 净利润增长率"
                resp = await mx.query_natural(query_text, "financial")
                if not resp.get("success"):
                    return {}
                rows = resp.get("data", [])
                if not rows:
                    return {}
                row = rows[0]
                result = {}
                mapping = {
                    'asset_liability_ratio': ['资产负债率', 'debt_ratio', 'asset_liability_ratio'],
                    'current_ratio': ['流动比率', 'current_ratio'],
                    'quick_ratio': ['速动比率', 'quick_ratio'],
                    'roe': ['净资产收益率', 'ROE', 'roe'],
                    'gross_margin': ['毛利率', 'gross_margin', '销售毛利率'],
                    'net_profit_growth': ['净利润增长率', 'net_profit_growth', '净利润增长'],
                    'operating_cashflow': ['经营现金流', 'operating_cashflow', '每股经营现金流'],
                }
                for dst, src_keys in mapping.items():
                    for k in src_keys:
                        if k in row and row[k] is not None:
                            try:
                                v = float(row[k])
                                if not (np.isnan(v) or np.isinf(v)):
                                    result[dst] = v
                                    break
                            except (ValueError, TypeError):
                                pass
                return result

            try:
                return asyncio.run(_query())
            except RuntimeError:
                import threading
                result_holder = {}
                def _run():
                    result_holder["data"] = asyncio.run(_query())
                t = threading.Thread(target=_run)
                t.start()
                t.join(timeout=15)
                return result_holder.get("data", {})
        except Exception as e:
            logger.debug(f"[FactorDS] {code} MX 财务指标也失败: {e}")
            return {}

    # ==================== 市场数据 ====================

    _market_sentiment_cache: dict = {}
    _market_sentiment_ts: float = 0.0
    _market_sentiment_lock = threading.Lock()

    def get_market_sentiment(self) -> dict:
        """
        市场情绪指标（基于 enrichment 缓存的 spot 数据实时聚合涨跌数）
        """
        with self._market_sentiment_lock:
            if time.time() - self._market_sentiment_ts < 60 and self._market_sentiment_cache:
                return self._market_sentiment_cache
            try:
                from app.engine import data_enrich as _de
                advance = 0
                decline = 0
                flat = 0
                total_change = 0.0
                valid_change_count = 0
                stock_count = 0
                _spot_iter = _de.get_all_spot_data()
                for sc, info in list(_spot_iter.items()):
                    if not isinstance(info, dict):
                        continue
                    ch = info.get("change_pct")
                    if ch is not None:
                        try:
                            ch_f = float(ch)
                            if ch_f == ch_f:
                                total_change += ch_f
                                valid_change_count += 1
                        except (ValueError, TypeError):
                            pass
                    if ch is not None and str(ch) != 'nan':
                        try:
                            fch = float(ch)
                            if fch > 0.5:
                                advance += 1
                            elif fch < -0.5:
                                decline += 1
                            else:
                                flat += 1
                        except (ValueError, TypeError):
                            pass
                    stock_count += 1

                result = {
                    'advance_decline_ratio': round(advance / decline, 2) if decline > 0 else 0.0,
                    'advance_count': advance,
                    'decline_count': decline,
                    'flat_count': flat,
                    'stock_count': stock_count,
                    'avg_change_pct': round(total_change / valid_change_count, 2) if valid_change_count > 0 else 0.0,
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
                except Exception as e:
                    logger.debug(f"[FactorDataSource] market_engine.get_quotes failed: {e}")
                    quotes = []
            if not quotes:
                return {
                    'total_count': 0,
                    'avg_premium': 0.0,
                    'median_premium': 0.0,
                    'avg_price': 0.0,
                    'total_volume': 0.0,
                }
            premiums = [safe_float(getattr(q, 'premium_ratio', None), default=0.0) for q in quotes]
            prices = [safe_float(getattr(q, 'price', None), default=0.0) for q in quotes]
            volumes = [safe_float(getattr(q, 'volume', None), default=0.0) for q in quotes]
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

        debt_ratio = financial.get('asset_liability_ratio', 50)
        if debt_ratio < 50:
            scores['debt'] = 100
        elif debt_ratio < 70:
            scores['debt'] = 50
        else:
            scores['debt'] = 0

        current_ratio = financial.get('current_ratio', 1.0)
        if current_ratio > 2:
            scores['liquidity'] = 100
        elif current_ratio > 1:
            scores['liquidity'] = 50
        else:
            scores['liquidity'] = 0

        net_profit_growth = financial.get('net_profit_growth', 0)
        if net_profit_growth > 20:
            scores['growth'] = 100
        elif net_profit_growth > 0:
            scores['growth'] = 50
        else:
            scores['growth'] = 0

        pledge = self.get_shareholder_pledge_ratio(code)
        if pledge is None:
            scores['pledge'] = 50
        elif pledge < 30:
            scores['pledge'] = 100
        elif pledge < 60:
            scores['pledge'] = 50
        else:
            scores['pledge'] = 0

        guarantee = self.get_guarantee_ratio(code)
        if guarantee is None:
            scores['guarantee'] = 50
        elif guarantee < 10:
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
                    row[factor] = financial.get('asset_liability_ratio', 0)
                elif factor == 'liquidity':
                    row[factor] = financial.get('current_ratio', 0)
                elif factor == 'growth':
                    row[factor] = financial.get('net_profit_growth', 0)
                elif factor == 'roe':
                    row[factor] = financial.get('roe', 0)
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
