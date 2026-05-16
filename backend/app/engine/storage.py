import threading

import duckdb
from datetime import datetime, date, timedelta
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
        self._write_lock = threading.Lock()
        self._init_tables()
        logger.info(f"[Storage] Connected to {db_path}")

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS quotes_history (
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
        try:
            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_unique ON quotes_history(code, timestamp)")
        except duckdb.ConstraintException:
            # Deduplicate existing data then retry
            self.conn.execute("DELETE FROM quotes_history WHERE rowid NOT IN (SELECT MAX(rowid) FROM quotes_history GROUP BY code, timestamp)")
            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_unique ON quotes_history(code, timestamp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_snapshots(snapshot_date)")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                strategy VARCHAR,
                code VARCHAR,
                name VARCHAR,
                action VARCHAR,
                price DOUBLE,
                reason VARCHAR,
                confidence DOUBLE,
                executed BOOLEAN DEFAULT FALSE,
                ts TIMESTAMP
            )
        """)

        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_unique ON signal_history(strategy, code, ts)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_ts ON signal_history(ts)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_code ON signal_history(code)")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS executed_positions (
                code VARCHAR,
                name VARCHAR,
                side VARCHAR,
                price DOUBLE,
                volume INTEGER,
                ts TIMESTAMP
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_pos_ts ON executed_positions(ts)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_pos_code ON executed_positions(code)")

        # 评分历史表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS score_history (
                code VARCHAR,
                name VARCHAR,
                score DOUBLE,
                score_dual_low DOUBLE,
                score_premium DOUBLE,
                score_momentum DOUBLE,
                score_volume DOUBLE,
                score_price DOUBLE,
                price DOUBLE,
                premium_ratio DOUBLE,
                dual_low DOUBLE,
                volume DOUBLE,
                snapshot_date DATE,
                UNIQUE(snapshot_date, code)
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_score_date ON score_history(snapshot_date)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_score_code ON score_history(code)")

        # 评分预警表
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS score_alerts_id_seq START 1")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS score_alerts (
                id INTEGER PRIMARY KEY DEFAULT nextval('score_alerts_id_seq'),
                code VARCHAR,
                name VARCHAR,
                alert_type VARCHAR,
                threshold DOUBLE,
                direction VARCHAR,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP,
                triggered_at TIMESTAMP,
                UNIQUE(code, alert_type, threshold, direction)
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_score_alerts_code ON score_alerts(code)")

        # 组合预警表（支持多条件组合）
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS combo_alerts_id_seq START 1")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS combo_alerts (
                id INTEGER PRIMARY KEY DEFAULT nextval('combo_alerts_id_seq'),
                name VARCHAR,
                description VARCHAR,
                conditions VARCHAR,
                logic VARCHAR DEFAULT 'AND',
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP,
                triggered_at TIMESTAMP
            )
        """)

        # 预警历史记录表
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS alert_history_id_seq START 1")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY DEFAULT nextval('alert_history_id_seq'),
                alert_id INTEGER,
                alert_type VARCHAR,
                code VARCHAR,
                name VARCHAR,
                threshold DOUBLE,
                current_value DOUBLE,
                triggered_at TIMESTAMP,
                acknowledged BOOLEAN DEFAULT FALSE
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_ts ON alert_history(triggered_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_code ON alert_history(code)")

        # 回测结果表
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS backtest_results_id_seq START 1")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY DEFAULT nextval('backtest_results_id_seq'),
                run_ts TIMESTAMP,
                start_date VARCHAR,
                end_date VARCHAR,
                top_n INTEGER,
                hold_days INTEGER,
                avg_return_pct DOUBLE,
                win_rate DOUBLE,
                total_periods INTEGER,
                params_json VARCHAR
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_ts ON backtest_results(run_ts)")

        # 回测详情表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_details (
                backtest_id INTEGER,
                date VARCHAR,
                end_date VARCHAR,
                top_n INTEGER,
                avg_return_pct DOUBLE,
                win_rate DOUBLE,
                max_return DOUBLE,
                min_return DOUBLE,
                max_drawdown DOUBLE DEFAULT 0
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_detail_id ON backtest_details(backtest_id)")

        # 通用配置表（键值存储）
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key VARCHAR PRIMARY KEY,
                value VARCHAR,
                updated_at TIMESTAMP
            )
        """)

    def _rows_to_dicts(self, table: str, rows: list) -> list[dict]:
        if not rows:
            return []
        columns = [desc[0] for desc in self.conn.execute(f"SELECT * FROM {table} WHERE 1=0").description]
        return [dict(zip(columns, row)) for row in rows]

    def save_quote(self, quote: ConvertibleQuote) -> None:
        with self._write_lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO quotes_history
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
        if not quotes:
            return
        rows = [
            (q.code, q.name, q.price, q.change_pct,
             q.stock_price, q.stock_change_pct, q.conversion_price,
             q.conversion_value, q.premium_ratio, q.dual_low,
             q.ytm, q.volume, q.remaining_years, q.forced_call_days,
             q.timestamp)
            for q in quotes
        ]
        try:
            with self._write_lock:
                self.conn.executemany("""
                    INSERT INTO quotes_history
                    (code, name, price, change_pct, stock_price, stock_change_pct,
                     conversion_price, conversion_value, premium_ratio, dual_low,
                     ytm, volume, remaining_years, forced_call_days, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                """, rows)
            logger.debug(f"[Storage] Saved {len(quotes)} quotes")
        except Exception as e:
            logger.error(f"Batch insert failed: {e}")

    def save_daily_snapshot(self, quotes: list[ConvertibleQuote], snapshot_date: Optional[date] = None) -> None:
        snapshot_date = snapshot_date or date.today()
        with self._write_lock:
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
        return self._rows_to_dicts("quotes_history", result)

    def get_daily_history(self, code: str, days: int = 30) -> list[dict]:
        result = self.conn.execute("""
            SELECT * FROM daily_snapshots
            WHERE code = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (code, days)).fetchall()
        return self._rows_to_dicts("daily_snapshots", result)

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
        return self._rows_to_dicts("quotes_history", result)

    def cleanup_old_data(self, keep_days: int = 30) -> int:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff - timedelta(days=keep_days)
        with self._write_lock:
            count_before = self.conn.execute(
                "SELECT COUNT(*) FROM quotes_history WHERE timestamp < ?", (cutoff,)
            ).fetchone()[0]
            if count_before > 0:
                self.conn.execute("DELETE FROM quotes_history WHERE timestamp < ?", (cutoff,))
        logger.info(f"[Storage] Cleaned up {count_before} old records")
        return count_before

    def cleanup_signal_history(self, keep_days: int = 30) -> int:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff - timedelta(days=keep_days)
        with self._write_lock:
            count_before = self.conn.execute(
                "SELECT COUNT(*) FROM signal_history WHERE ts < ?", (cutoff,)
            ).fetchone()[0]
            if count_before > 0:
                self.conn.execute("DELETE FROM signal_history WHERE ts < ?", (cutoff,))
        if count_before:
            logger.info(f"[Storage] Cleaned up {count_before} old signal records")
        return count_before

    def save_signals_batch(self, signals: list[dict]) -> None:
        if not signals:
            return
        with self._write_lock:
            self.conn.executemany("""
                INSERT INTO signal_history
                (strategy, code, name, action, price, reason, confidence, executed, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, [
                (s.get("strategy", ""), s.get("code", ""), s.get("name", ""),
                 s.get("action", ""), s.get("price", 0.0), s.get("reason", ""),
                 s.get("confidence", 0.0), s.get("executed", False), s.get("ts", datetime.now()))
                for s in signals
            ])
        logger.debug(f"[Storage] Saved {len(signals)} signals")

    def get_signal_history(self, strategy: str = "", code: str = "",
                            limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        conditions = []
        params = []
        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)
        if code:
            conditions.append("code = ?")
            params.append(code)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        total = self.conn.execute(f"SELECT COUNT(*) FROM signal_history {where}", params).fetchone()[0]
        result = self.conn.execute(f"""
            SELECT * FROM signal_history {where}
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
        """, (*params, limit, offset)).fetchall()
        return self._rows_to_dicts("signal_history", result), total

    def get_signal_stats(self) -> dict:
        """获取信号统计信息"""
        total = self.conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0]
        executed = self.conn.execute("SELECT COUNT(*) FROM signal_history WHERE executed = TRUE").fetchone()[0]
        by_strategy = self.conn.execute("""
            SELECT strategy, COUNT(*) as cnt,
                   SUM(CASE WHEN executed THEN 1 ELSE 0 END) as executed_cnt
            FROM signal_history GROUP BY strategy
        """).fetchall()
        return {
            "total": total,
            "executed": executed,


            "strategy_stats": [{"strategy": r[0], "count": r[1], "executed": r[2]} for r in by_strategy]
        }

    def save_executed_position(self, pos: dict) -> None:
        with self._write_lock:
            self.conn.execute("""
                INSERT INTO executed_positions (code, name, side, price, volume, ts)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (pos.get('code', ''), pos.get('name', ''), pos.get('side', ''),
                  pos.get('price', 0.0), pos.get('volume', 0), pos.get('ts', datetime.now())))

    def save_executed_positions_batch(self, positions: list[dict]) -> None:
        if not positions:
            return
        with self._write_lock:
            self.conn.executemany(
                "INSERT INTO executed_positions (code, name, side, price, volume, ts) VALUES (?, ?, ?, ?, ?, ?)",
                [(p.get('code', ''), p.get('name', ''), p.get('side', ''),
                  p.get('price', 0.0), p.get('volume', 0), p.get('ts', datetime.now()))
                 for p in positions]
            )

    def get_executed_positions(self, limit: int = 100, offset: int = 0) -> list[dict]:
        result = self.conn.execute("""
            SELECT * FROM executed_positions ORDER BY ts DESC LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        return self._rows_to_dicts('executed_positions', result)

    def cleanup_executed_positions(self, keep_days: int = 30) -> int:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=keep_days)
        with self._write_lock:
            count = self.conn.execute("SELECT COUNT(*) FROM executed_positions WHERE ts < ?", (cutoff,)).fetchone()[0]
            if count > 0:
                self.conn.execute("DELETE FROM executed_positions WHERE ts < ?", (cutoff,))
        return count

    # ── 评分历史 ──

    def save_score_snapshot(self, scores: list[dict], snapshot_date: Optional[date] = None) -> None:
        """保存每日评分快照"""
        snapshot_date = snapshot_date or date.today()
        if not scores:
            return
        with self._write_lock:
            for s in scores:
                self.conn.execute("""
                    INSERT INTO score_history
                    (code, name, score, score_dual_low, score_premium, score_momentum,
                     score_volume, score_price, price, premium_ratio, dual_low, volume, snapshot_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_date, code) DO UPDATE SET
                        score = excluded.score,
                        score_dual_low = excluded.score_dual_low,
                        score_premium = excluded.score_premium,
                        score_momentum = excluded.score_momentum,
                        score_volume = excluded.score_volume,
                        score_price = excluded.score_price,
                        price = excluded.price,
                        premium_ratio = excluded.premium_ratio,
                        dual_low = excluded.dual_low,
                        volume = excluded.volume
                """, (
                    s.get('code', ''), s.get('name', ''), s.get('score', 0),
                    s.get('score_dual_low', 0), s.get('score_premium', 0),
                    s.get('score_momentum', 0), s.get('score_volume', 0),
                    s.get('score_price', 0), s.get('price', 0),
                    s.get('premium_ratio', 0), s.get('dual_low', 0),
                    s.get('volume', 0), snapshot_date
                ))
        logger.info(f"[Storage] Saved score snapshot for {snapshot_date}, {len(scores)} bonds")

    def get_score_history(self, code: str, days: int = 30) -> list[dict]:
        """获取某只转债的评分历史"""
        result = self.conn.execute("""
            SELECT * FROM score_history
            WHERE code = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (code, days)).fetchall()
        return self._rows_to_dicts("score_history", result)

    def get_score_history_batch(self, codes: list[str], days: int = 30) -> dict[str, list[dict]]:
        """批量获取多只转债的评分历史"""
        if not codes:
            return {}
        placeholders = ",".join(["?" for _ in codes])
        result = self.conn.execute(f"""
            SELECT * FROM score_history
            WHERE code IN ({placeholders})
            ORDER BY code, snapshot_date DESC
        """, codes).fetchall()

        data = {}
        for row in result:
            row_dict = dict(zip([desc[0] for desc in self.conn.execute("SELECT * FROM score_history WHERE 1=0").description], row))
            code = row_dict['code']
            if code not in data:
                data[code] = []
            # 只取最近N天的数据
            if len(data[code]) < days:
                data[code].append(row_dict)
        return data

    def get_daily_score_ranking(self, snapshot_date: date, top_n: int = 60) -> list[dict]:
        """获取某日的评分排名"""
        result = self.conn.execute("""
            SELECT * FROM score_history
            WHERE snapshot_date = ?
            ORDER BY score DESC
            LIMIT ?
        """, (snapshot_date, top_n)).fetchall()
        return self._rows_to_dicts("score_history", result)

    def get_score_dates(self, limit: int = 30) -> list[str]:
        """获取有评分数据的日期列表"""
        result = self.conn.execute("""
            SELECT DISTINCT snapshot_date FROM score_history
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [str(r[0]) for r in result]

    # ── 回测结果持久化 ──

    def save_backtest_result(self, summary: dict, details: list[dict], params: dict) -> int:
        """保存回测结果，返回backtest_id"""
        import json
        with self._write_lock:
            self.conn.execute("""
                INSERT INTO backtest_results
                (run_ts, start_date, end_date, top_n, hold_days,
                 avg_return_pct, win_rate, total_periods, params_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(), params.get("startDate", ""),
                params.get("endDate", ""), params.get("topN", 20),
                params.get("holdDays", 5),
                summary.get("avg_return_pct", 0), summary.get("avg_win_rate", 0),
                summary.get("total_periods", 0), json.dumps(params),
            ))
            backtest_id = self.conn.execute("SELECT currval('backtest_results_id_seq')").fetchone()[0]
            if details:
                # Calculate running max drawdown for each detail row
                cum = 0.0
                peak = 0.0
                for d in details:
                    cum += d.get("avg_return_pct", 0)
                    if cum > peak:
                        peak = cum
                    dd = peak - cum
                    d["_max_drawdown"] = max(dd, d.get("_max_drawdown", 0))
                # Second pass to compute cumulative max drawdown per row
                cum = 0.0
                peak = 0.0
                running_max_dd = 0.0
                for d in details:
                    cum += d.get("avg_return_pct", 0)
                    if cum > peak:
                        peak = cum
                    dd = peak - cum
                    if dd > running_max_dd:
                        running_max_dd = dd
                    d["_max_drawdown"] = running_max_dd
                rows = [
                    (backtest_id, d.get("date", ""), d.get("end_date", ""),
                     d.get("top_n", 0), d.get("avg_return_pct", 0),
                     d.get("win_rate", 0), d.get("max_return", 0), d.get("min_return", 0),
                     d.get("_max_drawdown", 0))
                    for d in details
                ]
                self.conn.executemany("""
                    INSERT INTO backtest_details
                    (backtest_id, date, end_date, top_n, avg_return_pct,
                     win_rate, max_return, min_return, max_drawdown)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, rows)
            return backtest_id

    def get_backtest_results(self, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        """获取最近的回测结果列表，返回 (results, total_count)"""
        total = self.conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
        result = self.conn.execute("""
            SELECT * FROM backtest_results ORDER BY run_ts DESC LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        return self._rows_to_dicts("backtest_results", result), total

    def get_backtest_result(self, backtest_id: int) -> dict | None:
        """按 ID 获取单条回测结果"""
        result = self.conn.execute("SELECT * FROM backtest_results WHERE id = ?", (backtest_id,)).fetchone()
        if not result:
            return None
        columns = [desc[0] for desc in self.conn.execute("SELECT * FROM backtest_results WHERE 1=0").description]
        return dict(zip(columns, result))

    def get_backtest_details(self, backtest_id: int) -> list[dict]:
        """获取某次回测的详情"""
        result = self.conn.execute("""
            SELECT * FROM backtest_details WHERE backtest_id = ? ORDER BY date
        """, (backtest_id,)).fetchall()
        return self._rows_to_dicts("backtest_details", result)

    def delete_backtest_result(self, backtest_id: int) -> bool:
        """删除某次回测结果及其详情"""
        with self._write_lock:
            count = self.conn.execute("SELECT COUNT(*) FROM backtest_results WHERE id = ?", (backtest_id,)).fetchone()[0]
            if count == 0:
                return False
            self.conn.execute("DELETE FROM backtest_details WHERE backtest_id = ?", (backtest_id,))
            self.conn.execute("DELETE FROM backtest_results WHERE id = ?", (backtest_id,))
            return True

    def cleanup_backtest_results(self, keep_days: int = 90) -> int:
        """清理过期的回测结果"""
        cutoff = datetime.now() - timedelta(days=keep_days)
        ids = self.conn.execute(
            "SELECT id FROM backtest_results WHERE run_ts < ?", (cutoff,)
        ).fetchall()
        if not ids:
            return 0
        id_list = [row[0] for row in ids]
        with self._write_lock:
            placeholders = ",".join("?" * len(id_list))
            self.conn.execute(f"DELETE FROM backtest_details WHERE backtest_id IN ({placeholders})", id_list)
            self.conn.execute(f"DELETE FROM backtest_results WHERE id IN ({placeholders})", id_list)
        logger.info(f"[Storage] Cleaned up {len(id_list)} old backtest results")
        return len(id_list)

    def cleanup_score_history(self, keep_days: int = 90) -> int:
        """清理过期的评分历史"""
        cutoff = date.today() - timedelta(days=keep_days)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM score_history WHERE snapshot_date < ?", (cutoff,)
        ).fetchone()[0]
        if count > 0:
            with self._write_lock:
                self.conn.execute("DELETE FROM score_history WHERE snapshot_date < ?", (cutoff,))
            logger.info(f"[Storage] Cleaned up {count} old score records")
        return count

    # ── 评分预警 ──

    def add_score_alert(self, alert: dict) -> int:
        """添加评分预警"""
        with self._write_lock:
            self.conn.execute("""
                INSERT INTO score_alerts
                (code, name, alert_type, threshold, direction, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (code, alert_type, threshold, direction) DO UPDATE SET
                    name = excluded.name,
                    enabled = excluded.enabled
            """, (
                alert['code'], alert.get('name', ''), alert.get('alert_type', 'score'),
                alert['threshold'], alert.get('direction', 'above'),
                alert.get('enabled', True), datetime.now()
            ))
            return self.conn.execute("SELECT currval('score_alerts_id_seq')").fetchone()[0]
        """删除评分预警"""
        with self._write_lock:
            self.conn.execute("DELETE FROM score_alerts WHERE id = ?", (alert_id,))

    def get_score_alerts(self, enabled_only: bool = False) -> list[dict]:
        """获取所有评分预警"""
        where = "WHERE enabled = TRUE" if enabled_only else ""
        result = self.conn.execute(f"SELECT * FROM score_alerts {where}").fetchall()
        return self._rows_to_dicts("score_alerts", result)

    def update_alert_triggered(self, alert_id: int) -> None:
        """更新预警触发时间"""
        with self._write_lock:
            self.conn.execute(
                "UPDATE score_alerts SET triggered_at = ? WHERE id = ?",
                (datetime.now(), alert_id)
            )

    def add_alert_history(self, record: dict) -> int:
        """添加预警触发历史记录"""
        with self._write_lock:
            self.conn.execute("""
                INSERT INTO alert_history
                (alert_id, alert_type, code, name, threshold, current_value, triggered_at, acknowledged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.get('alert_id'), record.get('alert_type', 'score'),
                record.get('code', ''), record.get('name', ''),
                record.get('threshold', 0), record.get('current_value', 0),
                record.get('triggered_at', datetime.now()), False
            ))
            return self.conn.execute("SELECT currval('alert_history_id_seq')").fetchone()[0]
        """获取预警历史记录"""
        cutoff = datetime.now() - timedelta(days=days)
        if code:
            result = self.conn.execute("""
                SELECT * FROM alert_history
                WHERE triggered_at >= ? AND code = ?
                ORDER BY triggered_at DESC
            """, (cutoff, code)).fetchall()
        else:
            result = self.conn.execute("""
                SELECT * FROM alert_history
                WHERE triggered_at >= ?
                ORDER BY triggered_at DESC
            """, (cutoff,)).fetchall()
        return self._rows_to_dicts("alert_history", result)

    def acknowledge_alert(self, history_id: int) -> None:
        """确认预警记录"""
        with self._write_lock:
            self.conn.execute(
                "UPDATE alert_history SET acknowledged = TRUE WHERE id = ?",
                (history_id,)
            )

    def cleanup_alert_history(self, keep_days: int = 90) -> int:
        """清理过期的预警历史"""
        cutoff = datetime.now() - timedelta(days=keep_days)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM alert_history WHERE triggered_at < ?", (cutoff,)
        ).fetchone()[0]
        if count > 0:
            with self._write_lock:
                self.conn.execute("DELETE FROM alert_history WHERE triggered_at < ?", (cutoff,))
            logger.info(f"[Storage] Cleaned up {count} old alert history records")
        return count

    # ── 组合预警 ──

    def add_combo_alert(self, alert: dict) -> int:
        """添加组合预警"""
        import json
        with self._write_lock:
            self.conn.execute("""
                INSERT INTO combo_alerts (name, description, conditions, logic, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                alert.get('name', ''), alert.get('description', ''),
                json.dumps(alert.get('conditions', [])),
                alert.get('logic', 'AND'), alert.get('enabled', True), datetime.now()
            ))
            return self.conn.execute("SELECT currval('combo_alerts_id_seq')").fetchone()[0]

    def remove_combo_alert(self, alert_id: int) -> None:
        """删除组合预警"""
        with self._write_lock:
            self.conn.execute("DELETE FROM combo_alerts WHERE id = ?", (alert_id,))

    def get_combo_alerts(self, enabled_only: bool = False) -> list[dict]:
        """获取所有组合预警"""
        import json
        where = "WHERE enabled = TRUE" if enabled_only else ""
        result = self.conn.execute(f"SELECT * FROM combo_alerts {where}").fetchall()
        alerts = []
        for row in result:
            d = dict(zip([desc[0] for desc in self.conn.execute("SELECT * FROM combo_alerts WHERE 1=0").description], row))
            d['conditions'] = json.loads(d['conditions']) if d.get('conditions') else []
            alerts.append(d)
        return alerts

    def update_combo_alert_triggered(self, alert_id: int) -> None:
        """更新组合预警触发时间"""
        with self._write_lock:
            self.conn.execute(
                "UPDATE combo_alerts SET triggered_at = ? WHERE id = ?",
                (datetime.now(), alert_id)
            )

    # ── 综合清理 ──

    def cleanup_all(self, keep_days: int = 90) -> dict:
        """执行所有数据清理"""
        results = {
            "quotes": self.cleanup_old_data(keep_days),
            "signals": self.cleanup_signal_history(keep_days),
            "executed": self.cleanup_executed_positions(keep_days),
            "scores": self.cleanup_score_history(keep_days),
            "alerts": self.cleanup_alert_history(keep_days),
            "backtest": self.cleanup_backtest_results(keep_days),
        }
        total = sum(results.values())
        logger.info(f"[Storage] Cleanup completed: {total} total records removed")
        return results

    # ── 通用配置 ──

    def get_config(self, key: str, default: str | None = None) -> str | None:
        """获取配置值"""
        result = self.conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
        return result[0] if result else default

    def set_config(self, key: str, value: str) -> None:
        """设置配置值"""
        with self._write_lock:
            self.conn.execute("""
                INSERT INTO app_config (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (key, value, datetime.now()))

    def close(self):
        self.conn.close()
        logger.info("[Storage] Connection closed")
