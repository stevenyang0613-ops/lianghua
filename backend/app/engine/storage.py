import duckdb
from datetime import datetime, date
from pathlib import Path
from typing import Optional
import logging

from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


class DataStorage:
    """DuckDB数据持久化存储"""

    def __init__(self, db_path: str = "data/market.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(db_path)
        self._init_tables()
        logger.info(f"[Storage] Connected to {db_path}")

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS quotes_history (
                id INTEGER PRIMARY KEY,
                code VARCHAR,
                name VARCHAR,
                price DOUBLE,
                change_pct DOUBLE,
                stock_price DOUBLE,
                stock_change_pct DOUBLE,
                conversion_price DOUBLE,
                conversion_value DOUBLE,
                premium_ratio DOUBLE,
                dual_low DOUBLE,
                ytm DOUBLE,
                volume DOUBLE,
                remaining_years DOUBLE,
                forced_call_days INTEGER,
                timestamp TIMESTAMP
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                id INTEGER PRIMARY KEY,
                code VARCHAR,
                name VARCHAR,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price DOUBLE,
                close_price DOUBLE,
                volume DOUBLE,
                snapshot_date DATE,
                UNIQUE(snapshot_date, code)
            )
        """)

        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_code ON quotes_history(code)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_timestamp ON quotes_history(timestamp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_snapshots(snapshot_date)")

    def save_quote(self, quote: ConvertibleQuote) -> None:
        self.conn.execute("""
            INSERT INTO quotes_history
            (code, name, price, change_pct, stock_price, stock_change_pct,
             conversion_price, conversion_value, premium_ratio, dual_low,
             ytm, volume, remaining_years, forced_call_days, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            quote.code, quote.name, quote.price, quote.change_pct,
            quote.stock_price, quote.stock_change_pct, quote.conversion_price,
            quote.conversion_value, quote.premium_ratio, quote.dual_low,
            quote.ytm, quote.volume, quote.remaining_years, quote.forced_call_days,
            quote.timestamp
        ))

    def save_quotes_batch(self, quotes: list[ConvertibleQuote]) -> None:
        for quote in quotes:
            self.save_quote(quote)
        logger.debug(f"[Storage] Saved {len(quotes)} quotes")

    def save_daily_snapshot(self, quotes: list[ConvertibleQuote], snapshot_date: Optional[date] = None) -> None:
        snapshot_date = snapshot_date or date.today()
        for quote in quotes:
            self.conn.execute("""
                INSERT INTO daily_snapshots
                (code, name, open_price, high_price, low_price, close_price, volume, snapshot_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, code) DO UPDATE SET
                    close_price = excluded.close_price,
                    high_price = GREATEST(high_price, excluded.high_price),
                    low_price = LEAST(low_price, excluded.low_price),
                    volume = excluded.volume
            """, (
                quote.code, quote.name, quote.price, quote.price, quote.price,
                quote.price, quote.volume, snapshot_date
            ))
        logger.info(f"[Storage] Saved daily snapshot for {snapshot_date}, {len(quotes)} bonds")

    def get_quote_history(self, code: str, limit: int = 100) -> list[dict]:
        result = self.conn.execute("""
            SELECT * FROM quotes_history
            WHERE code = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (code, limit)).fetchall()
        columns = [desc[0] for desc in self.conn.execute("SELECT * FROM quotes_history WHERE 1=0").description]
        return [dict(zip(columns, row)) for row in result]

    def get_daily_history(self, code: str, days: int = 30) -> list[dict]:
        result = self.conn.execute("""
            SELECT * FROM daily_snapshots
            WHERE code = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (code, days)).fetchall()
        columns = [desc[0] for desc in self.conn.execute("SELECT * FROM daily_snapshots WHERE 1=0").description]
        return [dict(zip(columns, row)) for row in result]

    def get_latest_quotes(self) -> list[dict]:
        result = self.conn.execute("""
            WITH latest AS (
                SELECT code, MAX(timestamp) as max_ts
                FROM quotes_history
                GROUP BY code
            )
            SELECT q.* FROM quotes_history q
            JOIN latest l ON q.code = l.code AND q.timestamp = l.max_ts
            ORDER BY q.code
        """).fetchall()
        columns = [desc[0] for desc in self.conn.execute("SELECT * FROM quotes_history WHERE 1=0").description]
        return [dict(zip(columns, row)) for row in result]

    def cleanup_old_data(self, keep_days: int = 30) -> int:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=keep_days)
        result = self.conn.execute("DELETE FROM quotes_history WHERE timestamp < ?", (cutoff,))
        deleted = result.fetchone()[0] if result else 0
        logger.info(f"[Storage] Cleaned up {deleted} old records")
        return deleted

    def close(self):
        self.conn.close()
        logger.info("[Storage] Connection closed")
