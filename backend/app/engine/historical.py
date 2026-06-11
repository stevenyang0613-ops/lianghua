import asyncio
from datetime import date, timedelta, datetime
from typing import Optional
import logging
import requests
import pandas as pd

from app.engine.storage import DataStorage

logger = logging.getLogger(__name__)


class HistoricalDataLoader:
    """历史数据加载器 - 从东方财富获取历史行情并缓存到DuckDB"""

    def __init__(self, storage: DataStorage):
        self.storage = storage

    async def load_bond_history(self, code: str, days: int = 365, max_retries: int = 3) -> list[dict]:
        """加载单只可转债历史行情（直接 HTTP 轮询东方财富，自动重试）"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        market = "1" if code.startswith(("11", "13")) else "0"
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={market}.{code}&fields1=f1,f2,f3,f4,f5"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
            f"&klt=101&fqt=0"
            f"&beg={start_date.strftime('%Y%m%d')}"
            f"&end={end_date.strftime('%Y%m%d')}"
        )
        alt_url = url.replace(f"secid={market}.", f"secid={('0' if market == '1' else '1')}.")

        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(requests.get, url, timeout=15),
                    timeout=20,
                )
                data = resp.json()
                klines = (data.get("data") or {}).get("klines") or []
                if not klines:
                    resp = await asyncio.wait_for(
                        asyncio.to_thread(requests.get, alt_url, timeout=15),
                        timeout=20,
                    )
                    data = resp.json()
                    klines = (data.get("data") or {}).get("klines") or []
                if not klines:
                    return []
                records = []
                for line in klines:
                    parts = line.split(",")
                    if len(parts) < 7:
                        continue
                    dt = date.fromisoformat(parts[0])
                    records.append({
                        "code": code,
                        "name": "",
                        "open_price": float(parts[1] or 0),
                        "close_price": float(parts[2] or 0),
                        "high_price": float(parts[3] or 0),
                        "low_price": float(parts[4] or 0),
                        "volume": float(parts[5] or 0),
                        "snapshot_date": dt,
                    })
                return records
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    wait = attempt * 1.0
                    logger.debug(f"[Historical] Retry {code} attempt {attempt+1}/{max_retries} after {wait}s: {e}")
                    await asyncio.sleep(wait)
        logger.warning(f"[Historical] Failed to load {code} after {max_retries} retries: {last_err}")
        return []

    async def load_all_bonds_history(self, codes: list[str], days: int = 365) -> dict[str, list[dict]]:
        """批量加载多只可转债历史行情"""
        sem = asyncio.Semaphore(5)
        total = len(codes)
        done = 0

        async def _load_one(code: str):
            nonlocal done
            async with sem:
                result = await self.load_bond_history(code, days)
                done += 1
                if result:
                    logger.info(f"[Historical] Loaded {len(result)} days for {code} ({done}/{total})")
                else:
                    logger.debug(f"[Historical] No data for {code} ({done}/{total})")
                await asyncio.sleep(0.1)
                return code, result

        tasks = [_load_one(code) for code in codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_records: dict[str, list[dict]] = {}
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Failed to load bond history: {r}")
                continue
            code, records = r
            if records:
                all_records[code] = records
        return all_records

    def get_cached_history(self, start_date: date, end_date: date,
                           codes: Optional[list[str]] = None) -> pd.DataFrame:
        cursor = self.storage.conn.execute("""
            SELECT code, name, close_price as price, volume,
                   snapshot_date as date
            FROM daily_snapshots
            WHERE snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY code, snapshot_date
        """, (start_date, end_date))
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        if not rows:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(rows, columns=columns)
        if "premium_ratio" not in df.columns:
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
        batch = 0
        total_bonds = len(all_records)
        for code, records in all_records.items():
            with self.storage._write() as conn:
                for rec in records:
                    conn.execute("""
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
            batch += 1
            if batch % 50 == 0:
                self.storage.checkpoint()
                logger.info(f"[Historical] Seed progress: {batch}/{total_bonds} bonds, {saved} records saved")
        self.storage.checkpoint()
        logger.info(f"[Historical] Seeded {saved} records for {total_bonds} bonds")
        return {"bonds": total_bonds, "records": saved}