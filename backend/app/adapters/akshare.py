from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd

from app.adapters.base import DataSourceAdapter
from app.models.convertible import ConvertibleQuote


class AKShareAdapter(DataSourceAdapter):
    """AKShare 可转债数据适配器"""

    def __init__(self):
        self._cache: Optional[list[ConvertibleQuote]] = None
        self._cache_time: Optional[datetime] = None

    async def fetch_all_quotes(self) -> list[ConvertibleQuote]:
        """使用 AKShare 获取全市场可转债实时行情"""
        df = ak.bond_zh_cov()
        bonds = []
        for _, row in df.iterrows():
            try:
                bond = self._row_to_quote(row)
                if bond:
                    bonds.append(bond)
            except (KeyError, ValueError, TypeError):
                continue
        self._cache = bonds
        self._cache_time = datetime.now()
        return bonds

    async def fetch_quote(self, code: str) -> Optional[ConvertibleQuote]:
        if self._cache is None:
            await self.fetch_all_quotes()
        for bond in self._cache or []:
            if bond.code == code:
                return bond
        return None

    def _row_to_quote(self, row: pd.Series) -> Optional[ConvertibleQuote]:
        """将 DataFrame 行转为 Quote 对象，适配不同版本的 AKShare 列名"""
        try:
            code = str(row.get("代码", row.get("bond_code", "")))
            if not code:
                return None
            price = float(row.get("最新价", row.get("price", 0)))
            change_pct = float(row.get("涨跌幅", row.get("change_pct", 0)))

            conversion_price = float(row.get("转股价", row.get("conversion_price", 0)))
            stock_price = float(row.get("正股价", row.get("stock_price", 0)))
            conversion_value = round(100 / conversion_price * stock_price, 2) if conversion_price > 0 else 0.0
            premium = round((price - conversion_value) / conversion_value * 100, 2) if conversion_value > 0 else 0.0
            dual_low = round(price + premium, 2)

            return ConvertibleQuote(
                code=code,
                name=str(row.get("转债名称", row.get("bond_name", ""))),
                price=price,
                change_pct=change_pct,
                stock_price=stock_price,
                stock_change_pct=float(row.get("正股涨跌幅", row.get("stock_change_pct", 0))),
                conversion_price=conversion_price,
                conversion_value=conversion_value,
                premium_ratio=premium,
                dual_low=dual_low,
                volume=float(row.get("成交额", row.get("volume", 0))),
            )
        except (ValueError, TypeError, ZeroDivisionError):
            return None
