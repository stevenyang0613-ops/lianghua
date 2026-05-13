import asyncio
from datetime import date, timedelta, datetime
from typing import Optional
import logging
import pandas as pd

from app.engine.storage import DataStorage

logger = logging.getLogger(__name__)


class HistoricalDataLoader:
    """历史数据加载器 - 从AKShare获取历史行情并缓存到DuckDB"""

    def __init__(self, storage: DataStorage):
        self.storage = storage

    async def load_bond_history(self, code: str, days: int = 365) -> list[dict]:
        """加载单只可转债历史行情"""
        try:
            import akshare as ak

            df = await asyncio.wait_for(
                asyncio.to_thread(
                    ak.bond_zh_cov_hist,
                    code,
                    "",
                    (date.today() - timedelta(days=days)).strftime("%Y%m%d"),
                    date.today().strftime("%Y%m%d"),
                ),
                timeout=30,
            )

            records = []
            for _, row in df.iterrows():
                dt = row.get("日期")
                if isinstance(dt, str):
                    dt = date.fromisoformat(dt)
                records.append({
                    "code": code,
                    "name": str(row.get("转债名称", "")),
                    "open_price": float(row.get("开盘价", 0)),
                    "high_price": float(row.get("最高价", 0)),
                    "low_price": float(row.get("最低价", 0)),
                    "close_price": float(row.get("收盘价", 0)),
                    "volume": float(row.get("成交额", 0)),
                    "snapshot_date": dt,
                })
            return records
        except Exception as e:
            logger.warning(f"[Historical] Failed to load {code}: {e}")
            return []

    async def load_all_bonds_history(self, codes: list[str], days: int = 365) -> dict[str, list[dict]]:
        """批量加载多只可转债历史行情"""
        all_records: dict[str, list[dict]] = {}
        for code in codes:
            records = await self.load_bond_history(code, days)
            if records:
                all_records[code] = records
                logger.info(f"[Historical] Loaded {len(records)} days for {code}")
            await asyncio.sleep(0.5)
        return all_records

    def get_cached_history(self, start_date: date, end_date: date,
                           codes: Optional[list[str]] = None) -> pd.DataFrame:
        """从DuckDB获取缓存的历史数据"""
        rows = self.storage.conn.execute("""
            SELECT code, name, close_price as price, volume,
                   snapshot_date as date
            FROM daily_snapshots
            WHERE snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY code, snapshot_date
        """, (start_date, end_date)).fetchall()

        if not rows:
            return pd.DataFrame(columns=["code", "name", "date", "price", "volume"])

        df = pd.DataFrame(rows, columns=["code", "name", "date", "price", "volume"])
        df["premium_ratio"] = 0.0

        if codes:
            df = df[df["code"].isin(codes)]

        return df

    def get_available_dates(self) -> list[date]:
        rows = self.storage.conn.execute("""
            SELECT DISTINCT snapshot_date
            FROM daily_snapshots
            ORDER BY snapshot_date
        """).fetchall()
        return [row[0] for row in rows]

    async def seed_historical_data(self, codes: list[str], days: int = 365):
        """种子数据：为指定可转债加载历史数据并缓存"""
        all_records = await self.load_all_bonds_history(codes, days)
        saved = 0
        for code, records in all_records.items():
            for rec in records:
                self.storage.conn.execute("""
                    INSERT INTO daily_snapshots
                    (code, name, open_price, high_price, low_price, close_price, volume, snapshot_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_date, code) DO UPDATE SET
                        close_price = excluded.close_price,
                        high_price = GREATEST(high_price, excluded.high_price),
                        low_price = LEAST(low_price, excluded.low_price),
                        volume = excluded.volume
                """, (
                    code, rec["name"],
                    rec["open_price"], rec["high_price"],
                    rec["low_price"], rec["close_price"],
                    rec["volume"], rec["snapshot_date"],
                ))
                saved += 1
        logger.info(f"[Historical] Seeded {saved} records for {len(all_records)} bonds")
        return {"bonds": len(all_records), "records": saved}
