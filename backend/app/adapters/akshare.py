import asyncio
import math
from datetime import datetime
from typing import Optional
import logging

import akshare as ak
import pandas as pd

from app.adapters.base import DataSourceAdapter
from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


class AKShareAdapter(DataSourceAdapter):
    """AKShare 可转债数据适配器 - 多数据源融合

    数据来源:
    1. bond_zh_cov() - 东方财富，基础行情（转股价/溢价率/转股价值/正股价等）
    2. bond_zh_hs_cov_spot() - 新浪实时行情（涨跌幅/成交额）
    3. bond_zh_cov_info_ths() - 同花顺，到期时间（计算剩余年限）
    """

    def __init__(self, cache_ttl: int = 60, max_retries: int = 3, timeout: float = 180.0):
        self._cache: Optional[list[ConvertibleQuote]] = None
        self._eb_cache: Optional[list[ConvertibleQuote]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = cache_ttl
        self._max_retries = max_retries
        self._timeout = timeout

    def _backoff_delay(self, attempt: int) -> float:
        return min(1.0 * (2 ** attempt), 30.0)

    async def fetch_all_quotes(self) -> list[ConvertibleQuote]:
        if self._cache and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds()
            if elapsed < self._cache_ttl:
                return self._cache

        for attempt in range(self._max_retries):
            try:
                bonds, eb_bonds = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_and_merge),
                    timeout=self._timeout
                )
                break
            except asyncio.TimeoutError:
                logger.warning(f"[AKShare] Timeout on attempt {attempt + 1}/{self._max_retries}")
                if attempt == self._max_retries - 1:
                    logger.error("[AKShare] All retries exhausted")
                    return self._cache or []
                delay = self._backoff_delay(attempt)
                logger.info(f"[AKShare] Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"[AKShare] Error on attempt {attempt + 1}: {e}")
                if attempt == self._max_retries - 1:
                    return self._cache or []
                delay = self._backoff_delay(attempt)
                logger.info(f"[AKShare] Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
        else:
            return self._cache or []

        self._cache = bonds
        self._eb_cache = eb_bonds
        self._cache_time = datetime.now()
        logger.info(f"[AKShare] Fetched {len(bonds)} convertible bonds, {len(eb_bonds)} exchangeable bonds")
        return bonds

    async def fetch_exchangeable_bonds(self) -> list[ConvertibleQuote]:
        """获取可交换债数据"""
        if self._eb_cache is None:
            await self.fetch_all_quotes()
        return self._eb_cache or []

    def _fetch_and_merge(self) -> tuple[list[ConvertibleQuote], list[ConvertibleQuote]]:
        """获取并融合多个数据源"""
        # 1. 主数据源: 东方财富 bond_zh_cov
        try:
            df_cov = ak.bond_zh_cov()
        except Exception as e:
            logger.error(f"[AKShare] bond_zh_cov failed: {e}")
            return [], []

        # 2. 实时行情补充: bond_zh_hs_cov_spot (Sina实时价格/涨跌幅/成交额)
        spot_map: dict[str, dict] = {}
        try:
            df_spot = ak.bond_zh_hs_cov_spot()
            for _, r in df_spot.iterrows():
                code = str(r.get("code", "")).strip()
                if code and len(code) == 6 and code[0] in '12':
                    trade = self._safe_float(r.get("trade", 0))
                    if trade > 0:
                        spot_map[code] = {
                            "price": trade,
                            "open": self._safe_float(r.get("open", 0)),
                            "high": self._safe_float(r.get("high", 0)),
                            "low": self._safe_float(r.get("low", 0)),
                            "change_pct": self._safe_float(r.get("changepercent", 0)),
                            "amount": self._safe_float(r.get("amount", 0)),
                            "volume": self._safe_float(r.get("volume", 0)),
                        }
        except Exception as e:
            logger.warning(f"[AKShare] bond_zh_hs_cov_spot failed: {e}")

        # 3. 到期时间: bond_zh_cov_info_ths
        maturity_map: dict[str, str] = {}
        try:
            df_ths = ak.bond_zh_cov_info_ths()
            for _, r in df_ths.iterrows():
                code = str(r.get("债券代码", "")).strip()
                expire = r.get("到期时间", "")
                if code and expire and str(expire) not in ("", "NaT", "None", "nan"):
                    maturity_map[code] = str(expire)[:10]
        except Exception as e:
            logger.warning(f"[AKShare] bond_zh_cov_info_ths failed: {e}")

# 4. 正股行情: stock_zh_a_spot (新浪实时行情, 含涨跌幅/价格/成交量)
        # PE/PB/换手率由 data_enrich 后台任务从东财 push2 批量获取
        stock_chg_map: dict[str, float] = {}
        stock_price_map: dict[str, float] = {}
        stock_volume_map: dict[str, float] = {}
        stock_pe_map: dict[str, float] = {}
        stock_pb_map: dict[str, float] = {}
        stock_turnover_map: dict[str, float] = {}
        try:
            df_stock = ak.stock_zh_a_spot()
            for _, r in df_stock.iterrows():
                raw_code = str(r.get("代码", "")).strip()
                if not raw_code or raw_code.startswith("bj"):
                    continue
                s_code = raw_code[2:] if (raw_code.startswith("sz") or raw_code.startswith("sh")) else raw_code
                chg = self._safe_float(r.get("涨跌幅", 0))
                stock_chg_map[s_code] = chg
                sp_v = self._safe_float(r.get("最新价", 0))
                if sp_v:
                    stock_price_map[s_code] = sp_v
                sv_v = self._safe_float(r.get("成交额", 0))
                if sv_v:
                    stock_volume_map[s_code] = sv_v
            logger.info(f"[AKShare] Fetched {len(stock_chg_map)} stock change data from Sina ({len(stock_price_map)} prices)")

            # 尝试从 data_enrich 缓存拉取 PE/PB/换手率
            try:
                from app.engine.data_enrich import get_stock_spot
                for code in stock_price_map:
                    spot = get_stock_spot(code)
                    if spot:
                        pe = spot.get('pe')
                        pb = spot.get('pb')
                        tr = spot.get('turnover_rate')
                        if pe and pe > 0:
                            stock_pe_map[code] = pe
                        if pb and pb > 0:
                            stock_pb_map[code] = pb
                        if tr and tr > 0:
                            stock_turnover_map[code] = tr
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"[AKShare] stock_zh_a_spot (Sina) failed: {e}")

        # 5. 资金流向: stock_individual_fund_flow_rank
        # 失败时用 debug 级别，避免重复 5xx 刷屏
        fund_flow_map: dict[str, dict] = {}
        try:
            df_flow = ak.stock_individual_fund_flow_rank(indicator="今日")
            for _, r in df_flow.iterrows():
                f_code = str(r.get("代码", "")).strip()
                if not f_code:
                    continue
                fund_flow_map[f_code] = {
                    "net_main": self._safe_float(r.get("今日主力净流入-净额", 0)),
                    "net_main_pct": self._safe_float(r.get("今日主力净流入-净占比", 0)),
                }
            logger.info(f"[AKShare] Fetched fund flow: {len(fund_flow_map)} stocks")
        except Exception as e:
            logger.debug(f"[AKShare] fund flow failed: {e}")

        # 合并所有正股行情(价格/涨跌幅/PE/PB/换手率/资金流向)到 data_enrich 缓存
        if stock_price_map or stock_chg_map:
            try:
                from app.engine import data_enrich as _de
                existing = {}
                try:
                    import json, os
                    cache_path = os.path.expanduser("~/.lianghua/data_cache/stock_spot.json")
                    if os.path.exists(cache_path):
                        with open(cache_path) as f:
                            cached = json.load(f)
                            if isinstance(cached, dict):
                                existing = {k: v for k, v in cached.items() if k != "_ts"}
                except Exception:
                    pass
                all_stock_codes = set(stock_chg_map.keys()) | set(stock_price_map.keys()) | set(stock_pe_map.keys())
                for code in all_stock_codes:
                    if code not in existing:
                        existing[code] = {}
                    if code in stock_price_map:
                        existing[code]["price"] = stock_price_map[code]
                    existing[code]["change_pct"] = stock_chg_map.get(code, 0.0)
                    existing[code]["volume"] = stock_volume_map.get(code, 0.0)
                    if code in stock_pe_map:
                        existing[code]["pe"] = stock_pe_map[code]
                    if code in stock_pb_map:
                        existing[code]["pb"] = stock_pb_map[code]
                    if code in stock_turnover_map:
                        existing[code]["turnover_rate"] = stock_turnover_map[code]
                    if code in fund_flow_map:
                        existing[code]["net_main"] = fund_flow_map[code].get("net_main")
                        existing[code]["net_main_pct"] = fund_flow_map[code].get("net_main_pct")
                _de._inject_spot_data(existing)
            except Exception:
                pass

        # 6. 赎回/退市/可交换债 统一从 JSL bond_cb_redeem_jsl 拉取
        eb_bonds: list[ConvertibleQuote] = []
        redeem_map: dict[str, dict] = {}
        try:
            df_redeem = ak.bond_cb_redeem_jsl()
            for _, r in df_redeem.iterrows():
                code = str(r.get("代码", "")).strip()
                if not code:
                    continue

                call_status = str(r.get("强赎状态", "")).strip()
                last_trade_date = self._parse_iso_date(r.get("最后交易日", ""))
                maturity = self._parse_iso_date(r.get("到期日", ""))
                redemption_price = self._safe_float(r.get("强赎价", 0))
                jsl_price = self._safe_float(r.get("现价", 0))
                jsl_premium = self._safe_float(r.get("转股溢价率", 0))
                is_called = call_status in ("已公告强赎", "公告要强赎", "已满足强赎条件")
                # 强赎天计数 (格式: "0/15 | 30")
                forced_call_days = 0
                raw_fcd = str(r.get("强赎天计数", ""))
                if raw_fcd and raw_fcd not in ("", "nan"):
                    try:
                        forced_call_days = int(raw_fcd.split("/")[0])
                    except (ValueError, IndexError):
                        pass

                redeem_map[code] = {
                    "is_called": is_called,
                    "call_status": call_status,
                    "last_trade_date": last_trade_date,
                    "maturity_date": maturity,
                    "redemption_price": redemption_price,
                    "forced_call_days": forced_call_days,
                    "jsl_price": jsl_price,
                    "jsl_premium": jsl_premium,
                    "remaining_scale": self._safe_float(r.get("剩余规模")),
                }

                # 可交换债额外构建行情(EB 单独走另一条数据流)
                if not (code.startswith("132") or code.startswith("133")):
                    continue
                name = str(r.get("名称", "")).strip()
                # 从spot_map补充涨跌幅、成交额和价格
                spot = spot_map.get(code, {})
                sina_price_eb = float(spot.get("price", 0) or 0)
                jsl_price_eb = self._safe_float(r.get("现价", 0))
                price = sina_price_eb if sina_price_eb > 0 else jsl_price_eb
                stock_price = self._safe_float(r.get("正股价", 0))
                conversion_price = self._safe_float(r.get("转股价", 0))
                conversion_value = round(stock_price / conversion_price * 100, 2) if conversion_price > 0 else 0.0
                premium_ratio = round((price - conversion_value) / conversion_value * 100, 2) if conversion_value > 0 else 0.0
                dual_low = round(price + premium_ratio, 2) if price > 0 else 0.0
                remaining_years = self._calc_remaining_years(r.get("到期日", ""))
                forced_call_days = redeem_map.get(code, {}).get("forced_call_days", 0)
                change_pct = spot.get("change_pct", 0.0)
                raw_amount = spot.get("amount", 0.0)
                volume = round(raw_amount / 100000000, 4) if raw_amount > 0 else 0.0
                eb_stock_code = str(r.get("正股代码", "")).strip()
                stock_change_pct = stock_chg_map.get(eb_stock_code, 0.0)
                ff = fund_flow_map.get(eb_stock_code, {})
                eb_bonds.append(ConvertibleQuote(
                    code=code,
                    name=name,
                    stock_code=eb_stock_code,
                    price=price,
                    change_pct=change_pct,
                    stock_price=stock_price,
                    stock_change_pct=stock_change_pct,
                    conversion_price=conversion_price,
                    conversion_value=conversion_value,
                    premium_ratio=premium_ratio,
                    dual_low=dual_low,
                    ytm=self._calc_ytm(price, remaining_years),
                    volume=volume,
                    remaining_years=remaining_years,
                    forced_call_days=forced_call_days,
                    is_called=is_called,
                    call_status=call_status,
                    last_trade_date=last_trade_date,
                    maturity_date=maturity,
                    pe=stock_pe_map.get(eb_stock_code),
                    pb=stock_pb_map.get(eb_stock_code),
                    turnover_rate=stock_turnover_map.get(eb_stock_code),
                    net_capital_flow=ff.get("net_main"),
                    net_capital_flow_pct=ff.get("net_main_pct"),
                    redemption_price=redemption_price,
                    outstanding_scale=self._safe_float(r.get("剩余规模")),
                ))
            if eb_bonds:
                logger.info(f"[AKShare] Fetched {len(eb_bonds)} exchangeable bonds from JSL")
        except Exception as e:
            logger.warning(f"[AKShare] bond_cb_redeem_jsl failed: {e}")

        # 合并可转债数据（EB已从redeem_jsl单独获取）
        bonds = []
        for _, row in df_cov.iterrows():
            try:
                code = str(row.get("债券代码", row.get("代码", ""))).strip()
                if not code or code == 'nan':
                    continue
                name = str(row.get("债券简称", row.get("转债名称", ""))).strip()
                if self._is_delisted(code, name):
                    continue
                if self._is_exchangeable_bond(code):
                    continue
                rating = str(row.get("信用评级", "")).strip() or None
                bond = self._row_to_quote(row, spot_map, maturity_map, redeem_map.get(code), rating,
                                          stock_chg_map, stock_pe_map, stock_pb_map,
                                          stock_turnover_map, fund_flow_map)
                if bond:
                    bonds.append(bond)
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"[AKShare] Skip row: {e}")
                continue

        # TDX fallback: 补充缺失的转债价格和正股行情
        try:
            from app.adapters.tdx_adapter import get_tdx_adapter
            tdx = get_tdx_adapter()

            # TDX 补充转债价格
            missing_cb_codes = [b.code for b in bonds if not b.price or b.price <= 0]
            if missing_cb_codes:
                tdx_q = tdx.fetch_quotes(missing_cb_codes)
                if tdx_q:
                    filled = 0
                    for code, q in tdx_q.items():
                        price = q.get("price", 0)
                        if price and price > 0:
                            for b in bonds:
                                if b.code == code and (not b.price or b.price <= 0):
                                    b.price = price
                                    b.change_pct = q.get("change_pct")
                                    filled += 1
                                    break
                    if filled:
                        logger.info(f"[AKShare] TDX: filled {filled} CB prices")
        except Exception as e:
            logger.debug(f"[AKShare] TDX CB fallback failed: {e}")

        return bonds, eb_bonds

    async def fetch_quote(self, code: str) -> Optional[ConvertibleQuote]:
        if self._cache is None:
            await self.fetch_all_quotes()
        for bond in self._cache or []:
            if bond.code == code:
                return bond
        return None

    @staticmethod
    def _safe_float(value) -> float:
        if value is None or value == '' or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
            return 0.0
        try:
            v = float(value)
            if math.isnan(v) or math.isinf(v):
                return 0.0
            return v
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _calc_ytm(price: float, remaining_years: float) -> float:
        """
        估算到期收益率(YTM)
        使用简化的当前收益率 + 资本利得/损失摊销

        中国可转债通常采用阶梯利率（如0.3%、0.5%、1.0%、1.5%、1.8%、2.0%），
        根据剩余年限估算加权平均票面利率：剩余越长，用到的高息年份越多。
        """
        if price <= 0 or remaining_years <= 0:
            return 0.0
        face_value = 100.0
        coupon_rates = [0.3, 0.5, 1.0, 1.5, 1.8, 2.0]
        total_years = min(6, remaining_years)
        weighted_coupon = sum(coupon_rates[:int(total_years)]) / total_years if total_years > 0 else 1.5
        annual_interest = face_value * weighted_coupon / 100.0
        avg_price = (face_value + price) / 2.0
        capital_gain = (face_value - price) / remaining_years
        ytm = ((annual_interest + capital_gain) / avg_price) * 100.0
        return round(ytm, 2)

    @staticmethod
    def _calc_remaining_years(maturity_date) -> float:
        if not maturity_date:
            return 0.0
        try:
            s = str(maturity_date)[:10]
            maturity = datetime.strptime(s, '%Y-%m-%d')
            delta = maturity - datetime.now()
            return max(0.0, round(delta.days / 365, 2))
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _is_delisted(code: str, name: str) -> bool:
        """判断是否为退市整理期转债（代码404开头或名称含'退债'）"""
        return code.startswith('404') or '退债' in name

    @staticmethod
    def _is_stopped_trading(price: float, remaining_years: float,
                            last_trade_date=None, maturity_date=None,
                            volume: float = None, change_pct: float = None) -> bool:
        """判断转债是否已停止交易（到期/强赎后已退市），应从行情中移除"""
        # price=0 with remaining_years=0: likely missing data, not confirmed stopped
        # Only filter if we have explicit stop signals
        if remaining_years is None or remaining_years < 0:
            return True
        # Confirmed stopped: price < 1 AND remaining_years == 0 AND we have maturity info
        if remaining_years == 0.0 and price < 1.0:
            # If we have maturity_date, it's confirmed stopped
            if maturity_date is not None:
                return True
            # Otherwise, price=0 with no maturity data = missing data, keep it
            return False
        # 已到期转债：price=100 且无剩余年限 → 过滤掉
        if price == 100.0 and remaining_years == 0.0:
            return True
        # 尚未上市的新券：price=100, 无成交, 无涨跌, 剩余年限>2年
        if volume is not None and change_pct is not None:
            if price == 100.0 and volume == 0.0 and change_pct == 0.0 and remaining_years > 2.0:
                return True
        now = datetime.now().date()
        if last_trade_date is not None:
            try:
                ltd = last_trade_date.date() if hasattr(last_trade_date, 'date') else last_trade_date
                if isinstance(ltd, str):
                    ltd = datetime.strptime(str(ltd)[:10], '%Y-%m-%d').date()
                if ltd < now:
                    return True
            except (ValueError, TypeError, AttributeError):
                pass
        if maturity_date is not None:
            try:
                md = maturity_date.date() if hasattr(maturity_date, 'date') else maturity_date
                if isinstance(md, str):
                    md = datetime.strptime(str(md)[:10], '%Y-%m-%d').date()
                if md < now:
                    return True
            except (ValueError, TypeError, AttributeError):
                pass
        return False

    @staticmethod
    def _is_exchangeable_bond(code: str) -> bool:
        """判断是否为可交换债（EB），代码132/133开头"""
        return code.startswith('132') or code.startswith('133')

    @staticmethod
    @staticmethod
    def _parse_iso_date(value):
        """解析 JSL/THS 的日期字段为 date；空值/无效值返回 None"""
        if value is None:
            return None
        try:
            from datetime import datetime as _dt
            s = str(value).strip()
            if not s or s in ("nan", "NaT", "None"):
                return None
            # pandas.Timestamp 兼容
            if hasattr(value, "to_pydatetime"):
                try:
                    return value.to_pydatetime().date()
                except Exception:
                    pass
            if hasattr(value, "date"):
                return value.date()
            return _dt.strptime(s[:10].replace("/", "-"), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def _row_to_quote(self, row: pd.Series, spot_map: dict, maturity_map: dict,
                      redeem_info: Optional[dict] = None,
                      rating: Optional[str] = None,
                      stock_chg_map: Optional[dict] = None,
                      stock_pe_map: Optional[dict] = None,
                      stock_pb_map: Optional[dict] = None,
                      stock_turnover_map: Optional[dict] = None,
                      fund_flow_map: Optional[dict] = None) -> Optional[ConvertibleQuote]:
        """将主数据行与补充数据合并为 Quote 对象，过滤退市和到期转债"""
        try:
            code = str(row.get("债券代码", row.get("代码", ""))).strip()
            if not code or code == 'nan':
                return None

            name = str(row.get("债券简称", row.get("转债名称", ""))).strip()

            # 过滤退市整理期转债
            if self._is_delisted(code, name):
                return None

            # 过滤远古历史转债（东财bond_zh_cov全量数据库包含2008年至今所有已退市标的）
            issue_date = row.get("申购日期", "")
            if issue_date and str(issue_date) not in ("", "NaT", "nan", "None"):
                try:
                    issue_dt = datetime.strptime(str(issue_date)[:10], '%Y-%m-%d')
                    if (datetime.now() - issue_dt).days > 5 * 365:
                        return None
                except (ValueError, TypeError):
                    pass

            spot = spot_map.get(code, {})
            ri = redeem_info or {}

            # 价格优先级: Sina实时 > JSL现价 > 东财债现价
            sina_price = float(spot.get("price", 0) or 0)
            jsl_price = float(ri.get("jsl_price", 0) or 0)
            em_price = self._safe_float(row.get("债现价", 0))

            if sina_price > 0:
                price = sina_price
            elif jsl_price > 0:
                price = jsl_price
            elif em_price > 0:
                price = em_price
            else:
                price = 0.0

            conversion_value = self._safe_float(row.get("转股价值", 0))
            conversion_price = self._safe_float(row.get("转股价", 0))
            stock_price = self._safe_float(row.get("正股价", 0))
            stock_code = str(row.get("正股代码", "")).strip()

            # 溢价率优先级: JSL > 东财
            jsl_premium = float(ri.get("jsl_premium", 0) or 0)
            em_premium = self._safe_float(row.get("转股溢价率", 0))
            premium_ratio = jsl_premium if jsl_premium > 0 else em_premium

            # 重新计算转股价值（如果东财给的是NaN但正股价和转股价有值）
            if conversion_value == 0 and stock_price > 0 and conversion_price > 0:
                conversion_value = round(stock_price / conversion_price * 100, 2)

            dual_low = round(price + premium_ratio, 2) if price > 0 and premium_ratio > 0 else 0.0

            # 从实时行情补充涨跌幅和成交额
            change_pct = spot.get("change_pct", 0.0)
            raw_amount = spot.get("amount", 0.0)
            # amount 单位是元，转为亿元
            volume = round(raw_amount / 100000000, 4) if raw_amount > 0 else 0.0

            # 从同花顺补充到期时间，计算剩余年限
            maturity_str = maturity_map.get(code, "")
            remaining_years = self._calc_remaining_years(maturity_str)
            # 若同花顺无到期时间，用上市时间+6年推算
            if remaining_years == 0:
                list_date = row.get("上市时间", "")
                if list_date and str(list_date) not in ("", "NaT", "nan", "None"):
                    try:
                        ld = str(list_date)[:10]
                        list_dt = datetime.strptime(ld, '%Y-%m-%d')
                        est_maturity = list_dt.replace(year=list_dt.year + 6)
                        if est_maturity > datetime.now():
                            remaining_years = max(0.0, round((est_maturity - datetime.now()).days / 365, 2))
                    except (ValueError, TypeError):
                        pass
            # 兜底：使用赎回信息中的到期日
            if remaining_years == 0 and ri.get("maturity_date"):
                remaining_years = self._calc_remaining_years(ri["maturity_date"])
                maturity_str = str(ri["maturity_date"])[:10] if ri["maturity_date"] else ""

            maturity = self._parse_iso_date(maturity_str) or ri.get("maturity_date")

            # 过滤已停止交易的转债（已到期/强赎退市/价格异常/尚未上市新券）
            if self._is_stopped_trading(
                price, remaining_years,
                last_trade_date=ri.get("last_trade_date"),
                maturity_date=maturity or ri.get("maturity_date"),
                volume=volume,
                change_pct=change_pct,
            ):
                return None

            # 所有数据源均无真实价格 → price=0, 不丢弃（数据源缺失≠确认停牌）
            # _is_stopped_trading 会根据其他字段做进一步判断
            if price <= 0:
                price = 0.0

            # 无 Sina 无 JSL 价格（即东财默认100元）→ 数据源均不跟踪，过滤
            if sina_price <= 0 and jsl_price <= 0 and em_price == 100.0:
                return None

            return ConvertibleQuote(
                code=code,
                name=name,
                stock_code=stock_code,
                price=price,
                change_pct=change_pct,
                stock_price=stock_price,
                stock_change_pct=(stock_chg_map or {}).get(
                    stock_code, 0.0
                ),
                conversion_price=conversion_price,
                conversion_value=conversion_value,
                premium_ratio=premium_ratio,
                dual_low=dual_low,
                volume=volume,
                ytm=self._calc_ytm(price, remaining_years),
                remaining_years=remaining_years,
                forced_call_days=ri.get("forced_call_days", 0),
                is_called=bool(ri.get("is_called", False)),
                call_status=str(ri.get("call_status", "")),
                last_trade_date=ri.get("last_trade_date"),
                maturity_date=maturity,
                redemption_price=float(ri.get("redemption_price", 0.0) or 0.0),
                rating=rating,
                pe=(stock_pe_map or {}).get(stock_code),
                pb=(stock_pb_map or {}).get(stock_code),
                turnover_rate=(stock_turnover_map or {}).get(stock_code),
                net_capital_flow=((fund_flow_map or {}).get(stock_code) or {}).get("net_main"),
                net_capital_flow_pct=((fund_flow_map or {}).get(stock_code) or {}).get("net_main_pct"),
                outstanding_scale=ri.get("remaining_scale"),
            )
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logger.debug(f"[AKShare] _row_to_quote failed for row: {e}")
            return None
