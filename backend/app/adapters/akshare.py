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

        # 2. 实时行情补充: bond_zh_hs_cov_spot (涨跌幅/成交额)
        spot_map: dict[str, dict] = {}
        try:
            df_spot = ak.bond_zh_hs_cov_spot()
            for _, r in df_spot.iterrows():
                code = str(r.get("code", "")).strip()
                if code and len(code) == 6 and code[0] in '12':
                    spot_map[code] = {
                        "change_pct": self._safe_float(r.get("changepercent", 0)),
                        "amount": self._safe_float(r.get("amount", 0)),
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

        # 4. 赎回/退市/可交换债 统一从 JSL bond_cb_redeem_jsl 拉取
        eb_bonds: list[ConvertibleQuote] = []
        # 赎回信息表: code -> {is_called, call_status, last_trade_date, redemption_price, maturity_date}
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
                }

                # 可交换债额外构建行情(EB 单独走另一条数据流)
                if not (code.startswith("132") or code.startswith("133")):
                    continue
                name = str(r.get("名称", "")).strip()
                price = self._safe_float(r.get("现价", 0))
                stock_price = self._safe_float(r.get("正股价", 0))
                conversion_price = self._safe_float(r.get("转股价", 0))
                conversion_value = round(stock_price / conversion_price * 100, 2) if conversion_price > 0 else 0.0
                premium_ratio = round((price - conversion_value) / conversion_value * 100, 2) if conversion_value > 0 else 0.0
                dual_low = round(price + premium_ratio, 2) if price > 0 else 0.0
                remaining_years = self._calc_remaining_years(r.get("到期日", ""))
                forced_call_days = redeem_map.get(code, {}).get("forced_call_days", 0)
                # 从spot_map补充涨跌幅和成交额
                spot = spot_map.get(code, {})
                change_pct = spot.get("change_pct", 0.0)
                raw_amount = spot.get("amount", 0.0)
                volume = round(raw_amount / 100000000, 4) if raw_amount > 0 else 0.0
                eb_stock_code = str(r.get("正股代码", "")).strip()
                stock_change_pct = 0.0
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
                    volume=volume,
                    remaining_years=remaining_years,
                    forced_call_days=forced_call_days,
                    is_called=is_called,
                    call_status=call_status,
                    last_trade_date=last_trade_date,
                    maturity_date=maturity,
                    redemption_price=redemption_price,
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
                bond = self._row_to_quote(row, spot_map, maturity_map, redeem_map.get(code), rating)
                if bond:
                    bonds.append(bond)
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"[AKShare] Skip row: {e}")
                continue

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
        v = float(value) if value is not None and value != '' else 0.0
        return 0.0 if math.isnan(v) or math.isinf(v) else v

    @staticmethod
    def _calc_ytm(price: float, remaining_years: float) -> float:
        """
        估算到期收益率(YTM)
        使用简化的当前收益率 + 资本利得/损失摊销

        中国可转债通常采用阶梯利率（如0.3%、0.5%、1.0%、1.5%、1.8%、2.0%），
        平均简化取1.5%作为票面利率近似值。
        """
        if price <= 0 or remaining_years <= 0:
            return 0.0
        face_value = 100.0
        coupon_rate = 1.5
        annual_interest = face_value * coupon_rate / 100.0
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
        if price <= 0:
            return True
        if remaining_years is None or remaining_years < 0:
            return True
        if remaining_years == 0.0 and price < 1.0:
            return True
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
    def _is_expired_bond(price: float, remaining_years: float) -> bool:
        """判断是否为已到期无交易价值的转债（price=100且无剩余年限）"""
        return price == 100.0 and remaining_years == 0.0

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
                      rating: Optional[str] = None) -> Optional[ConvertibleQuote]:
        """将主数据行与补充数据合并为 Quote 对象，过滤退市和到期转债"""
        try:
            code = str(row.get("债券代码", row.get("代码", ""))).strip()
            if not code or code == 'nan':
                return None

            name = str(row.get("债券简称", row.get("转债名称", ""))).strip()

            # 过滤退市整理期转债
            if self._is_delisted(code, name):
                return None
            price = self._safe_float(row.get("债现价", row.get("最新价", row.get("trade", 0))))
            conversion_value = self._safe_float(row.get("转股价值", 0))
            premium_ratio = self._safe_float(row.get("转股溢价率", 0))
            conversion_price = self._safe_float(row.get("转股价", 0))
            stock_price = self._safe_float(row.get("正股价", 0))
            dual_low = round(price + premium_ratio, 2) if price > 0 else 0.0

            # 从实时行情补充涨跌幅和成交额
            spot = spot_map.get(code, {})
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
            ri = redeem_info or {}
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

            return ConvertibleQuote(
                code=code,
                name=name,
                stock_code=str(row.get("正股代码", "")).strip(),
                price=price,
                change_pct=change_pct,
                stock_price=stock_price,
                stock_change_pct=0.0,
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
            )
            if rating:
                logger.debug(f"[AKShare] Rating for {code} ({name}): {rating}")
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logger.debug(f"[AKShare] _row_to_quote failed for row: {e}")
            return None
