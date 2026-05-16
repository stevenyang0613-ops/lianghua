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
    """AKShare 可转债数据适配器"""

    def __init__(self, cache_ttl: int = 60, max_retries: int = 3, timeout: float = 60.0):
        self._cache: Optional[list[ConvertibleQuote]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = cache_ttl
        self._max_retries = max_retries
        self._timeout = timeout

    async def fetch_all_quotes(self) -> list[ConvertibleQuote]:
        """使用 AKShare 获取全市场可转债实时行情"""
        if self._cache and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds()
            if elapsed < self._cache_ttl:
                return self._cache

        for attempt in range(self._max_retries):
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_bond_data),
                    timeout=self._timeout
                )
                break
            except asyncio.TimeoutError:
                logger.warning(f"[AKShare] Timeout on attempt {attempt + 1}/{self._max_retries}")
                if attempt == self._max_retries - 1:
                    logger.error("[AKShare] All retries exhausted")
                    return self._cache or []
            except Exception as e:
                logger.error(f"[AKShare] Error on attempt {attempt + 1}: {e}")
                if attempt == self._max_retries - 1:
                    return self._cache or []
        else:
            return self._cache or []

        bonds = []
        for _, row in df.iterrows():
            try:
                bond = self._row_to_quote(row)
                if bond:
                    bonds.append(bond)
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"[AKShare] Skip row: {e}")
                continue

        self._cache = bonds
        self._cache_time = datetime.now()
        logger.info(f"[AKShare] Fetched {len(bonds)} convertible bonds")
        return bonds

    def _fetch_bond_data(self) -> pd.DataFrame:
        """同步获取可转债数据，优先使用实时行情接口（含成交量）"""
        try:
            # 尝试获取实时数据（含成交量）
            df_spot = ak.bond_zh_hs_cov_spot()
            if df_spot is not None and not df_spot.empty:
                df_spot = df_spot.rename(columns={
                    'symbol': '债券代码',
                    'name': '债券简称',
                    'trade': '债现价',
                    'volume': '成交额',
                })
                if '债券代码' in df_spot.columns and '债现价' in df_spot.columns:
                    logger.info(f"[AKShare] Using spot data: {len(df_spot)} records with volume")
                    return df_spot
        except Exception as e:
            logger.debug(f"[AKShare] Spot data unavailable: {e}")
        # 回退到集思录数据（无成交量，但数据更完整）
        logger.info("[AKShare] Falling back to cov data (no volume)")
        return ak.bond_zh_cov()

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

    def _row_to_quote(self, row: pd.Series) -> Optional[ConvertibleQuote]:
        """将 DataFrame 行转为 Quote 对象，适配不同版本的 AKShare 列名"""
        try:
            code = str(row.get("债券代码", row.get("代码", row.get("bond_code", ""))))
            if not code:
                return None

            # 直接使用 AKShare 提供的原始数据（AKShare 已计算好转股价值和溢价率）
            price = self._safe_float(row.get("债现价", row.get("最新价", row.get("price", 0))))
            conversion_value = self._safe_float(row.get("转股价值", 0))
            premium_ratio = self._safe_float(row.get("转股溢价率", 0))
            conversion_price = self._safe_float(row.get("转股价", 0))
            stock_price = self._safe_float(row.get("正股价", 0))
            dual_low = round(price + premium_ratio, 2) if price > 0 else 0.0

            return ConvertibleQuote(
                code=code,
                name=str(row.get("债券简称", row.get("转债名称", row.get("bond_name", "")))),
                price=price,
                change_pct=0.0,
                stock_price=stock_price,
                stock_change_pct=0.0,
                conversion_price=conversion_price,
                conversion_value=conversion_value,
                premium_ratio=premium_ratio,
                dual_low=dual_low,
                volume=self._safe_float(row.get("成交额", row.get("volume", 0))),
            )
        except (ValueError, TypeError, ZeroDivisionError):
            return None
