import os
import threading
import uuid
import json
from contextlib import contextmanager

import duckdb
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import logging

from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


def _safe_double(v, default=None, *, reject_neg1=False):
    """确保值是 DOUBLE 兼容类型（float/int/None），拒绝字符串误入数值列。
    
    Args:
        reject_neg1: 如果为 True，将 -1 视为标记值并返回 None（用于 gpm 列，
                     -1 是"银行无毛利率"的应用层标记，不应持久化到数据库）。
    """
    if v is None:
        return default
    if isinstance(v, (int, float)):
        if reject_neg1 and v == -1:
            return None
        return v
    if isinstance(v, str):
        # 字符串值不应出现在 DOUBLE 列中，强制转为 None 避免插入报错
        try:
            fv = float(v)
            if reject_neg1 and fv == -1:
                return None
            return fv
        except (ValueError, TypeError):
            return default
    return default


class DataStorage:
    """DuckDB数据持久化存储"""

    def __init__(self, db_path: str = "data/market.db", read_only: bool = False, checkpoint_interval: int = 3600, on_revision=None):
        # ── 启动时自检：列名必须全部注册提取器 ──
        # 防止添加新列到 _QH_INSERT_COLS 但忘记注册 extractor 导致的运行时 KeyError
        self._validate_qh_extractors()

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._write_lock = threading.Lock()
        self._reconnect_lock = threading.Lock()
        self._read_only = read_only
        self._checkpoint_interval = checkpoint_interval
        self._checkpoint_timer: threading.Timer | None = None
        self._on_revision = on_revision
        self._conn = self._connect_with_recovery(db_path, read_only)
        if not read_only:
            self._init_tables()
            if checkpoint_interval > 0:
                self._start_checkpoint_timer()
        self._qh_upsert_sql: str = self._build_qh_upsert_sql()
        self._qh_actual_columns: set[str] = self._detect_qh_actual_columns()
        self._qh_schema_version: str = (
            "matched" if self._qh_actual_columns >= set(self._QH_INSERT_COLS)
            else f"missing:{set(self._QH_INSERT_COLS) - self._qh_actual_columns}"
        )
        if self._qh_schema_version != "matched":
            logger.warning(
                f"[Storage] quotes_history schema mismatch: {self._qh_schema_version}; "
                f"expected {self._QH_UPSERT_VERSION}"
            )
        self._qh_schema_timer: threading.Timer | None = None
        if not read_only:
            self._start_schema_recheck_timer()
        logger.info(f"[Storage] Connected to {db_path}{' (read-only)' if read_only else ''}")

    def _connect_with_recovery(self, db_path: str, read_only: bool):
        """
        连接 DuckDB，自动处理锁冲突。

        策略:
        1. 直接连接
        2. 失败 → 删除 WAL 重试
        3. 仍失败 → 自动查找并杀死持有锁的进程
        4. 再失败 → 抛出明确错误
        """
        try:
            return duckdb.connect(db_path, read_only=read_only)
        except Exception as e:
            # Step 1: 删除 WAL 文件重试（安全操作）
            logger.warning(f"[Storage] duckdb.connect failed: {e}, attempting WAL recovery")
            wal_path = db_path + ".wal"
            try:
                if Path(wal_path).exists():
                    Path(wal_path).unlink()
                    logger.info(f"[Storage] Deleted WAL file, retrying connect")
                return duckdb.connect(db_path, read_only=read_only)
            except Exception as e2:
                # Step 2: 自动查找并杀死持有锁的进程 — 危险！子进程可能杀死父进程
                # 已禁用：此逻辑会导致子进程（如 score history bootstrap）杀死主进程
                # 改为直接报错
                logger.warning(f"[Storage] WAL recovery failed, database is locked")
                raise RuntimeError(
                    f"Cannot open DuckDB at {db_path}. Database is locked by another process.\n"
                    f"Original errors: {e} / {e2}"
                ) from e2

    @property
    def conn(self):
        """自动确保连接可用的 conn 属性"""
        try:
            self._conn.execute("SELECT 1")
        except Exception:
            self._reconnect()
        return self._conn

    def _reconnect(self):
        """重建数据库连接 - 使用 reconnect_lock 防止并发替换"""
        with self._reconnect_lock:
            # 双重检查：如果其他线程已经重连成功，跳过
            try:
                self._conn.execute("SELECT 1")
                return
            except Exception:
                pass
            logger.warning("[Storage] Connection lost, reconnecting...")
            try:
                self._conn.close()
            except Exception as e:
                logger.debug(f"[Storage] Close old connection: {e}")
            self._conn = duckdb.connect(self._db_path, read_only=self._read_only)
            if not self._read_only:
                self._init_tables()
            logger.info(f"[Storage] Reconnected to {self._db_path}")

    def _init_tables(self):
        self._conn.execute("""
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
                is_called BOOLEAN DEFAULT FALSE,
                call_status VARCHAR DEFAULT '',
                last_trade_date DATE,
                maturity_date DATE,
                redemption_price DOUBLE DEFAULT 0,
                timestamp TIMESTAMP
            )
        """)

        # Migration: 给老库补字段(列已存在会抛错,吞掉)
        # duckdb 在 DDL 失败时事务不会自动回滚,需显式 ROLLBACK
        for ddl in (
            "ALTER TABLE quotes_history ADD COLUMN is_called BOOLEAN DEFAULT FALSE",
            "ALTER TABLE quotes_history ADD COLUMN call_status VARCHAR DEFAULT ''",
            "ALTER TABLE quotes_history ADD COLUMN last_trade_date DATE",
            "ALTER TABLE quotes_history ADD COLUMN maturity_date DATE",
            "ALTER TABLE quotes_history ADD COLUMN redemption_price DOUBLE DEFAULT 0",
            "ALTER TABLE quotes_history ADD COLUMN stock_code VARCHAR DEFAULT ''",
            "ALTER TABLE quotes_history ADD COLUMN roe DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN gpm DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN cagr DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN debt_ratio DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN pe DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN pb DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN iv DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN buyback_amount DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN mgmt_buy_price DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN industry VARCHAR",
            "ALTER TABLE quotes_history ADD COLUMN rating VARCHAR",
        ):
            try:
                self._conn.execute(ddl)
                col_name = ddl.split("ADD COLUMN")[-1].strip()
                logger.info(f"[Storage] Migrated quotes_history: {col_name}")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
            try:
                self._conn.execute("COMMIT")
            except Exception:
                pass

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                code VARCHAR,
                name VARCHAR,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price DOUBLE,
                close_price DOUBLE,
                volume DOUBLE,
                snapshot_date DATE,
                premium_ratio DOUBLE DEFAULT 0,
                change_pct DOUBLE DEFAULT 0,
                stock_price DOUBLE DEFAULT 0,
                conversion_value DOUBLE DEFAULT 0,
                dual_low DOUBLE DEFAULT 0,
                ytm DOUBLE DEFAULT 0,
                remaining_years DOUBLE DEFAULT 0,
                roe DOUBLE,
                gpm DOUBLE,
                cagr DOUBLE,
                debt_ratio DOUBLE,
                pe DOUBLE,
                pb DOUBLE,
                iv DOUBLE,
                buyback_amount DOUBLE,
                mgmt_buy_price DOUBLE,
                industry VARCHAR,
                rating VARCHAR,
                outstanding_scale DOUBLE DEFAULT 0,
                stock_code VARCHAR DEFAULT '',
                UNIQUE(snapshot_date, code)
            )
        """)

        _NEW_QH_COLS = [
            "ALTER TABLE quotes_history ADD COLUMN iv_source VARCHAR",
            "ALTER TABLE quotes_history ADD COLUMN turnover_rate DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN current_ratio DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN outstanding_scale DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN net_capital_flow DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN net_capital_flow_pct DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN net_super_flow DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN net_big_flow DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN pledge_ratio DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN momentum_5d DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN momentum_10d DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN momentum_20d DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN momentum_60d DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN event_score DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN event_detail VARCHAR",
            "ALTER TABLE quotes_history ADD COLUMN bond_value DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN stock_name VARCHAR",
            "ALTER TABLE quotes_history ADD COLUMN concepts JSON",
            "ALTER TABLE quotes_history ADD COLUMN hv DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN rating_score DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN pure_bond_premium_ratio DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN north_net DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN margin_balance DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN lhb_count INTEGER",
            "ALTER TABLE quotes_history ADD COLUMN block_trade_amount DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN holder_num_change DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN eps_forecast DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN eps DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN bps DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN revenue_yoy DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN profit_yoy DOUBLE",
            "ALTER TABLE quotes_history ADD COLUMN restricted_release_amount DOUBLE",
        ]
        for ddl in _NEW_QH_COLS:
            try:
                self._conn.execute(ddl)
                col_name = ddl.split("ADD COLUMN")[-1].strip()
                logger.info(f"[Storage] Migrated quotes_history: {col_name}")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
            try:
                self._conn.execute("COMMIT")
            except Exception:
                pass

        # 修复历史库中 iv_source 被误创建为 DOUBLE 的问题
        for fix_ddl in (
            "ALTER TABLE quotes_history ALTER COLUMN iv_source SET DATA TYPE VARCHAR",
            "ALTER TABLE daily_snapshots ALTER COLUMN iv_source SET DATA TYPE VARCHAR",
            "ALTER TABLE quotes_history ALTER COLUMN event_detail SET DATA TYPE VARCHAR",
        ):
            try:
                self._conn.execute(fix_ddl)
                logger.info(f"[Storage] Fixed column type: {fix_ddl}")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
            try:
                self._conn.execute("COMMIT")
            except Exception:
                pass

        for ddl in (
            "ALTER TABLE daily_snapshots ADD COLUMN premium_ratio DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN change_pct DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN stock_price DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN conversion_value DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN dual_low DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN ytm DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN remaining_years DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN roe DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN gpm DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN cagr DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN debt_ratio DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN pe DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN pb DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN iv DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN buyback_amount DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN mgmt_buy_price DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN industry VARCHAR",
            "ALTER TABLE daily_snapshots ADD COLUMN rating VARCHAR",
            "ALTER TABLE daily_snapshots ADD COLUMN outstanding_scale DOUBLE DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN stock_code VARCHAR DEFAULT ''",
            "ALTER TABLE daily_snapshots ADD COLUMN iv_source VARCHAR",
            "ALTER TABLE daily_snapshots ADD COLUMN turnover_rate DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN current_ratio DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN net_capital_flow DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN net_capital_flow_pct DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN net_super_flow DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN net_big_flow DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN pledge_ratio DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN momentum_5d DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN momentum_10d DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN momentum_20d DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN momentum_60d DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN event_score DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN event_detail VARCHAR",
            "ALTER TABLE daily_snapshots ADD COLUMN bond_value DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN is_called BOOLEAN DEFAULT FALSE",
            "ALTER TABLE daily_snapshots ADD COLUMN call_status VARCHAR DEFAULT ''",
            "ALTER TABLE daily_snapshots ADD COLUMN forced_call_days INTEGER DEFAULT 0",
            "ALTER TABLE daily_snapshots ADD COLUMN hv DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN rating_score DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN pure_bond_premium_ratio DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN north_net DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN margin_balance DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN lhb_count INTEGER",
            "ALTER TABLE daily_snapshots ADD COLUMN block_trade_amount DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN holder_num_change DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN eps_forecast DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN eps DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN bps DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN revenue_yoy DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN profit_yoy DOUBLE",
            "ALTER TABLE daily_snapshots ADD COLUMN restricted_release_amount DOUBLE",
        ):
            try:
                self._conn.execute(ddl)
                col_name = ddl.split("ADD COLUMN")[-1].strip()
                logger.info(f"[Storage] Migrated daily_snapshots: {col_name}")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
            try:
                self._conn.execute("COMMIT")
            except Exception:
                pass

        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_code ON quotes_history(code)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_quotes_timestamp ON quotes_history(timestamp)")
        try:
            self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_unique ON quotes_history(code, timestamp)")
        except duckdb.ConstraintException:
            # Deduplicate existing data then retry
            self._conn.execute("DELETE FROM quotes_history WHERE rowid NOT IN (SELECT MAX(rowid) FROM quotes_history GROUP BY code, timestamp)")
            self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_unique ON quotes_history(code, timestamp)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_snapshots(snapshot_date)")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                id VARCHAR,
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

        self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_id ON signal_history(id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_unique ON signal_history(strategy, code, ts)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_ts ON signal_history(ts)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_code ON signal_history(code)")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS executed_positions (
                code VARCHAR,
                name VARCHAR,
                side VARCHAR,
                price DOUBLE,
                volume INTEGER,
                ts TIMESTAMP
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_pos_ts ON executed_positions(ts)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_pos_code ON executed_positions(code)")

        # Migration: add id column to signal_history if missing
        try:
            self._conn.execute("SELECT id FROM signal_history LIMIT 0")
        except Exception:
            try:
                self._conn.execute("ALTER TABLE signal_history ADD COLUMN id VARCHAR")
                logger.info("[Storage] Migrated signal_history: added id column")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass

        # Backfill: assign id to existing rows without one
        backfill_count = self._conn.execute(
            "SELECT COUNT(*) FROM signal_history WHERE id IS NULL"
        ).fetchone()[0]
        if backfill_count > 0:
            rows = self._conn.execute(
                "SELECT rowid FROM signal_history WHERE id IS NULL"
            ).fetchall()
            for (rowid,) in rows:
                self._conn.execute(
                    "UPDATE signal_history SET id = ? WHERE rowid = ?",
                    (uuid.uuid4().hex[:12], rowid),
                )
            logger.info(f"[Storage] Backfilled id for {backfill_count} signal_history rows")

        # 评分历史表
        self._conn.execute("""
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_score_date ON score_history(snapshot_date)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_score_code ON score_history(code)")

        # 评分预警表
        self._conn.execute("CREATE SEQUENCE IF NOT EXISTS score_alerts_id_seq START 1")
        self._conn.execute("""
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_score_alerts_code ON score_alerts(code)")

        # 组合预警表（支持多条件组合）
        self._conn.execute("CREATE SEQUENCE IF NOT EXISTS combo_alerts_id_seq START 1")
        self._conn.execute("""
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
        self._conn.execute("CREATE SEQUENCE IF NOT EXISTS alert_history_id_seq START 1")
        self._conn.execute("""
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_ts ON alert_history(triggered_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_code ON alert_history(code)")

        # 回测结果表
        self._conn.execute("CREATE SEQUENCE IF NOT EXISTS backtest_results_id_seq START 1")
        self._conn.execute("""
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_ts ON backtest_results(run_ts)")

        # 回测详情表
        self._conn.execute("""
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_detail_id ON backtest_details(backtest_id)")

        # 通用配置表（键值存储）
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key VARCHAR PRIMARY KEY,
                value VARCHAR,
                updated_at TIMESTAMP
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS revision_history (
                code VARCHAR,
                revision_date VARCHAR,
                old_price DOUBLE,
                new_price DOUBLE
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_revision_code ON revision_history (code)")

        # 七维评分快照表
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS seven_dim_history (
                code VARCHAR,
                name VARCHAR,
                total_score DOUBLE,
                stock_score DOUBLE,
                bond_score DOUBLE,
                momentum DOUBLE,
                sector DOUBLE,
                technical DOUBLE,
                chip DOUBLE,
                volatility DOUBLE,
                news DOUBLE,
                fundamental DOUBLE,
                valuation DOUBLE,
                clause DOUBLE,
                liquidity DOUBLE,
                credit DOUBLE,
                price DOUBLE,
                premium_ratio DOUBLE,
                dual_low DOUBLE,
                snapshot_date DATE,
                UNIQUE(snapshot_date, code)
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_seven_dim_date ON seven_dim_history(snapshot_date)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_seven_dim_code ON seven_dim_history(code)")

        # 缓冲带状态持久化表
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS buffer_tracker (
                code VARCHAR PRIMARY KEY,
                in_buffer BOOLEAN DEFAULT FALSE,
                days_in_buffer INTEGER DEFAULT 0,
                days_above_60 INTEGER DEFAULT 0,
                days_below_60 INTEGER DEFAULT 0,
                updated_at TIMESTAMP
            )
        """)

        # 通知渠道表
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                id INTEGER PRIMARY KEY,
                channel_type VARCHAR,
                name VARCHAR,
                config VARCHAR,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP
            )
        """)

        # 模拟盘账户表
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_accounts (
                id VARCHAR PRIMARY KEY,
                strategy_id VARCHAR,
                strategy_name VARCHAR,
                initial_cash DOUBLE DEFAULT 100000,
                is_running BOOLEAN DEFAULT FALSE,
                params_json VARCHAR DEFAULT '{}',
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)

        # 模拟盘权益曲线表
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_equity (
                account_id VARCHAR,
                ts TIMESTAMP,
                total_asset DOUBLE,
                cash DOUBLE,
                market_value DOUBLE,
                total_profit DOUBLE,
                total_profit_pct DOUBLE
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_equity_account ON paper_equity(account_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_equity_ts ON paper_equity(account_id, ts)")

        # 模拟盘账户状态持久化列迁移
        for ddl in (
            "ALTER TABLE paper_accounts ADD COLUMN cash_balance DOUBLE DEFAULT 0",
            "ALTER TABLE paper_accounts ADD COLUMN positions_json VARCHAR DEFAULT '[]'",
        ):
            try:
                self._conn.execute(ddl)
            except Exception:
                pass

    def _query_to_dicts(self, cursor) -> list[dict]:
        """从 cursor.description 获取列名，兼容别名和 JOIN 查询"""
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def save_quote(self, quote: ConvertibleQuote) -> None:
        cols = ", ".join(self._QH_INSERT_COLS)
        phs = ", ".join("?" for _ in self._QH_INSERT_COLS)
        row = self._get_qh_row(quote)
        with self._write() as conn:
            conn.execute(f"INSERT OR REPLACE INTO quotes_history ({cols}) VALUES ({phs})", row)

    _QH_INSERT_COLS = [
        "code", "name", "price", "change_pct", "stock_price", "stock_change_pct",
        "conversion_price", "conversion_value", "premium_ratio", "dual_low",
        "ytm", "volume", "remaining_years", "forced_call_days",
        "is_called", "call_status", "last_trade_date", "maturity_date", "redemption_price",
        "timestamp", "stock_code", "stock_name", "concepts", "roe", "gpm", "cagr", "debt_ratio", "pe", "pb", "iv",
        "iv_source", "buyback_amount", "mgmt_buy_price", "industry", "rating",
        "turnover_rate", "current_ratio", "outstanding_scale",
        "net_capital_flow", "net_capital_flow_pct", "net_super_flow", "net_big_flow",
        "pledge_ratio",
        "momentum_5d", "momentum_10d", "momentum_20d", "momentum_60d",
        "event_score", "event_detail", "bond_value",
        "hv", "rating_score", "pure_bond_premium_ratio",
        "north_net", "margin_balance", "lhb_count", "block_trade_amount",
        "holder_num_change", "eps_forecast", "eps", "bps",
        "revenue_yoy", "profit_yoy", "restricted_release_amount",
    ]
    _QH_ALWAYS_OVERWRITE = {"price"}
    _QH_COALESCE_MERGE = {
        "change_pct", "stock_price", "stock_change_pct", "conversion_value",
        "premium_ratio", "dual_low", "ytm", "volume", "stock_code", "stock_name", "concepts",
        "roe", "gpm", "cagr", "debt_ratio", "pe", "pb", "iv", "iv_source",
        "buyback_amount", "mgmt_buy_price", "industry", "rating",
        "turnover_rate", "current_ratio", "outstanding_scale",
        "net_capital_flow", "net_capital_flow_pct", "net_super_flow", "net_big_flow",
        "pledge_ratio",
        "momentum_5d", "momentum_10d", "momentum_20d", "momentum_60d",
        "event_score", "event_detail", "bond_value",
        "hv", "rating_score", "pure_bond_premium_ratio",
        "north_net", "margin_balance", "lhb_count", "block_trade_amount",
        "holder_num_change", "eps_forecast", "eps", "bps",
        "revenue_yoy", "profit_yoy", "restricted_release_amount",
    }
    _QH_UPSERT_VERSION = "v3"

    def _build_qh_upsert_sql(self) -> str:
        cols = self._QH_INSERT_COLS
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(cols)
        set_parts = []
        for c in cols:
            if c in self._QH_ALWAYS_OVERWRITE:
                set_parts.append(f"{c} = EXCLUDED.{c}")
            elif c in self._QH_COALESCE_MERGE:
                set_parts.append(f"{c} = COALESCE(EXCLUDED.{c}, quotes_history.{c})")
        return (
            f"INSERT INTO quotes_history ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT DO UPDATE SET {', '.join(set_parts)}"
        )

    def _detect_qh_actual_columns(self) -> set[str]:
        try:
            rows = self.conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'quotes_history'"
            ).fetchall()
            return {r[0] for r in rows}
        except Exception as e:
            logger.debug(f"[Storage] Column detection failed (table may not exist): {e}")
            return set()

    _QH_SCHEMA_RECHECK_INTERVAL = 300  # 5 minutes

    def _start_schema_recheck_timer(self):
        self._qh_schema_timer = threading.Timer(self._QH_SCHEMA_RECHECK_INTERVAL, self._qh_schema_recheck_loop)
        self._qh_schema_timer.daemon = True
        self._qh_schema_timer.start()

    def _qh_schema_recheck_loop(self):
        try:
            new_cols = self._detect_qh_actual_columns()
            new_version = (
                "matched" if new_cols >= set(self._QH_INSERT_COLS)
                else f"missing:{set(self._QH_INSERT_COLS) - new_cols}"
            )
            if new_version != self._qh_schema_version:
                self._qh_actual_columns = new_cols
                self._qh_schema_version = new_version
                self._qh_upsert_sql = self._build_qh_upsert_sql()
                logger.info(
                    f"[Storage] quotes_history schema changed: {new_version}; "
                    f"upsert SQL rebuilt"
                )
        except Exception as e:
            logger.debug(f"[Storage] Schema recheck failed: {e}")
        finally:
            self._start_schema_recheck_timer()

    # 字段提取器注册表：col_name → callable(ConvertibleQuote) → 值
    # O(1) dict lookup 比 60+ 字段 if-elif 链快约 2 倍，且列重排不会错位
    # 新增列时只需：(1) 加到 _QH_INSERT_COLS，(2) 在此注册
    _QH_FIELD_EXTRACTORS: dict[str, callable] = {
        "code":              lambda q: q.code,
        "name":              lambda q: q.name,
        "price":             lambda q: _safe_double(q.price),
        "change_pct":        lambda q: _safe_double(q.change_pct),
        "stock_price":       lambda q: _safe_double(q.stock_price),
        "stock_change_pct":  lambda q: _safe_double(q.stock_change_pct),
        "conversion_price":  lambda q: _safe_double(q.conversion_price),
        "conversion_value":  lambda q: _safe_double(q.conversion_value),
        "premium_ratio":     lambda q: _safe_double(q.premium_ratio),
        "dual_low":          lambda q: _safe_double(q.dual_low),
        "ytm":               lambda q: _safe_double(q.ytm),
        "volume":            lambda q: _safe_double(q.volume),
        "remaining_years":   lambda q: _safe_double(q.remaining_years),
        "forced_call_days":  lambda q: _safe_double(getattr(q, "forced_call_days", 0), 0),
        "is_called":         lambda q: bool(getattr(q, "is_called", False)),
        "call_status":       lambda q: str(getattr(q, "call_status", "") or ""),
        "last_trade_date":   lambda q: getattr(q, "last_trade_date", None),
        "maturity_date":     lambda q: getattr(q, "maturity_date", None),
        "redemption_price":  lambda q: _safe_double(getattr(q, "redemption_price", 0.0), 0.0),
        "timestamp":         lambda q: q.timestamp,
        "stock_code":        lambda q: getattr(q, "stock_code", None) or None,
        "stock_name":        lambda q: getattr(q, "stock_name", None) or None,
        "concepts":          lambda q: (
            json.dumps(getattr(q, "concepts") or []) if getattr(q, "concepts", None) else None
        ),
        "roe":               lambda q: _safe_double(getattr(q, "roe", None)),
        "gpm":               lambda q: _safe_double(getattr(q, "gpm", None), reject_neg1=True),
        "cagr":              lambda q: _safe_double(getattr(q, "cagr", None)),
        "debt_ratio":        lambda q: _safe_double(getattr(q, "debt_ratio", None)),
        "pe":                lambda q: _safe_double(getattr(q, "pe", None)),
        "pb":                lambda q: _safe_double(getattr(q, "pb", None)),
        "iv":                lambda q: _safe_double(getattr(q, "iv", None)),
        "iv_source":         lambda q: str(getattr(q, "iv_source", "") or ""),
        "buyback_amount":    lambda q: _safe_double(getattr(q, "buyback_amount", None)),
        "mgmt_buy_price":    lambda q: _safe_double(getattr(q, "mgmt_buy_price", None)),
        "industry":          lambda q: getattr(q, "industry", None),
        "rating":            lambda q: getattr(q, "rating", None),
        "turnover_rate":     lambda q: _safe_double(getattr(q, "turnover_rate", None)),
        "current_ratio":     lambda q: _safe_double(getattr(q, "current_ratio", None)),
        "outstanding_scale": lambda q: _safe_double(getattr(q, "outstanding_scale", None)),
        "net_capital_flow":  lambda q: _safe_double(getattr(q, "net_capital_flow", None)),
        "net_capital_flow_pct": lambda q: _safe_double(getattr(q, "net_capital_flow_pct", None)),
        "net_super_flow":    lambda q: _safe_double(getattr(q, "net_super_flow", None)),
        "net_big_flow":      lambda q: _safe_double(getattr(q, "net_big_flow", None)),
        "pledge_ratio":      lambda q: _safe_double(getattr(q, "pledge_ratio", None)),
        "momentum_5d":       lambda q: _safe_double(getattr(q, "momentum_5d", None)),
        "momentum_10d":      lambda q: _safe_double(getattr(q, "momentum_10d", None)),
        "momentum_20d":      lambda q: _safe_double(getattr(q, "momentum_20d", None)),
        "momentum_60d":      lambda q: _safe_double(getattr(q, "momentum_60d", None)),
        "event_score":       lambda q: _safe_double(getattr(q, "event_score", None)),
        "event_detail":      lambda q: getattr(q, "event_detail", None),
        "bond_value":        lambda q: _safe_double(getattr(q, "bond_value", None)),
        "hv":                lambda q: _safe_double(getattr(q, "hv", None)),
        "rating_score":      lambda q: _safe_double(getattr(q, "rating_score", None)),
        "pure_bond_premium_ratio": lambda q: _safe_double(getattr(q, "pure_bond_premium_ratio", None)),
        "north_net":         lambda q: _safe_double(getattr(q, "north_net", None)),
        "margin_balance":    lambda q: _safe_double(getattr(q, "margin_balance", None)),
        "lhb_count":         lambda q: getattr(q, "lhb_count", None),
        "block_trade_amount": lambda q: _safe_double(getattr(q, "block_trade_amount", None)),
        "holder_num_change": lambda q: _safe_double(getattr(q, "holder_num_change", None)),
        "eps_forecast":      lambda q: _safe_double(getattr(q, "eps_forecast", None)),
        "eps":               lambda q: _safe_double(getattr(q, "eps", None)),
        "bps":               lambda q: _safe_double(getattr(q, "bps", None)),
        "revenue_yoy":       lambda q: _safe_double(getattr(q, "revenue_yoy", None)),
        "profit_yoy":        lambda q: _safe_double(getattr(q, "profit_yoy", None)),
        "restricted_release_amount": lambda q: _safe_double(getattr(q, "restricted_release_amount", None)),
    }

    @classmethod
    def _validate_qh_extractors(cls) -> None:
        """启动时检查：_QH_INSERT_COLS 中每个列必须在 _QH_FIELD_EXTRACTORS 中注册。

        防止开发时添加新列到 _QH_INSERT_COLS 但忘记注册 extractor，导致运行时 KeyError
        （在生产环境第一次 save_quotes_batch 才发现，定位困难）。
        """
        missing = [col for col in cls._QH_INSERT_COLS if col not in cls._QH_FIELD_EXTRACTORS]
        if missing:
            raise RuntimeError(
                f"[Storage] _QH_INSERT_COLS has columns without registered extractors: {missing}. "
                f"Add them to DataStorage._QH_FIELD_EXTRACTORS."
            )

    def _get_qh_row(self, q):
        """Build a tuple for quotes_history upsert matching _QH_INSERT_COLS order.

        Uses dict-based dispatch in _QH_FIELD_EXTRACTORS instead of a manual tuple —
        column reordering in _QH_INSERT_COLS will not silently misalign field values,
        and missing columns are caught by _validate_qh_extractors at startup.
        """
        return tuple(self._QH_FIELD_EXTRACTORS[col](q) for col in self._QH_INSERT_COLS)

    def save_quotes_batch(self, quotes: list[ConvertibleQuote]) -> None:
        if not quotes:
            return
        rows = [self._get_qh_row(q) for q in quotes]
        try:
            sql = self._qh_upsert_sql
            with self._write() as conn:
                conn.executemany(sql, rows)

            logger.debug(f"[Storage] Saved {len(quotes)} quotes (upsert)")
            try:
                revision_count = self.detect_and_save_revisions(quotes)
                if revision_count > 0:
                    logger.info(f"[Storage] Detected {revision_count} downward revision(s)")
            except Exception as e:
                logger.warning(f"[Storage] Revision detection failed: {e}")
        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            # 自动检测 schema 变化并重建 upsert SQL
            if "does not have a column" in str(e):
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.warning(f"[Storage] Schema mismatch detected, re-detecting columns...")
                new_cols = self._detect_qh_actual_columns()
                if new_cols:
                    # 只插入实际存在的列
                    valid_cols = [c for c in self._QH_INSERT_COLS if c in new_cols]
                    if valid_cols:
                        logger.info(f"[Storage] Falling back to {len(valid_cols)}/{len(self._QH_INSERT_COLS)} columns")
                        try:
                            self._qh_actual_columns = new_cols
                            self._qh_schema_version = "fallback"
                            old_sql = self._qh_upsert_sql
                            self._qh_upsert_sql = self._build_qh_upsert_sql_with_cols(valid_cols)
                            rows_filtered = [self._get_qh_row_filtered(q, valid_cols) for q in quotes]
                            with self._write() as conn:
                                conn.executemany(self._qh_upsert_sql, rows_filtered)
                            logger.info(f"[Storage] Fallback batch insert succeeded for {len(quotes)} quotes")
                        except Exception as e2:
                            logger.error(f"[Storage] Fallback batch insert also failed: {e2}")
    
    def _build_qh_upsert_sql_with_cols(self, cols: list[str]) -> str:
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(cols)
        set_parts = []
        for c in cols:
            if c in self._QH_ALWAYS_OVERWRITE:
                set_parts.append(f"{c} = EXCLUDED.{c}")
            elif c in self._QH_COALESCE_MERGE:
                set_parts.append(f"{c} = COALESCE(EXCLUDED.{c}, quotes_history.{c})")
        return (
            f"INSERT INTO quotes_history ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT DO UPDATE SET {', '.join(set_parts)}"
        )
    
    @staticmethod
    def _get_qh_row_filtered(q, cols: list[str]) -> tuple:
        row_map = {
            "code": q.code, "name": q.name,
            "price": _safe_double(q.price), "change_pct": _safe_double(q.change_pct),
            "stock_price": _safe_double(q.stock_price), "stock_change_pct": _safe_double(q.stock_change_pct),
            "conversion_price": _safe_double(q.conversion_price), "conversion_value": _safe_double(q.conversion_value),
            "premium_ratio": _safe_double(q.premium_ratio), "dual_low": _safe_double(q.dual_low),
            "ytm": _safe_double(q.ytm), "volume": _safe_double(q.volume),
            "remaining_years": _safe_double(q.remaining_years),
            "forced_call_days": _safe_double(getattr(q, "forced_call_days", 0), 0),
            "is_called": bool(getattr(q, "is_called", False)),
            "call_status": str(getattr(q, "call_status", "") or ""),
            "last_trade_date": getattr(q, "last_trade_date", None),
            "maturity_date": getattr(q, "maturity_date", None),
            "redemption_price": _safe_double(getattr(q, "redemption_price", 0.0), 0.0),
            "timestamp": q.timestamp,
            "stock_code": getattr(q, "stock_code", None) or None,
            "stock_name": getattr(q, "stock_name", None) or None,
            "concepts": json.dumps(getattr(q, "concepts", None) or []) if getattr(q, "concepts", None) else None,
            "roe": _safe_double(getattr(q, "roe", None)),
            "gpm": _safe_double(getattr(q, "gpm", None), reject_neg1=True),
            "cagr": _safe_double(getattr(q, "cagr", None)),
            "debt_ratio": _safe_double(getattr(q, "debt_ratio", None)),
            "pe": _safe_double(getattr(q, "pe", None)),
            "pb": _safe_double(getattr(q, "pb", None)),
            "iv": _safe_double(getattr(q, "iv", None)),
            "iv_source": str(getattr(q, "iv_source", "") or ""),
            "buyback_amount": _safe_double(getattr(q, "buyback_amount", None)),
            "mgmt_buy_price": _safe_double(getattr(q, "mgmt_buy_price", None)),
            "industry": getattr(q, "industry", None),
            "rating": getattr(q, "rating", None),
            "turnover_rate": _safe_double(getattr(q, "turnover_rate", None)),
            "current_ratio": _safe_double(getattr(q, "current_ratio", None)),
            "outstanding_scale": _safe_double(getattr(q, "outstanding_scale", None)),
            "net_capital_flow": _safe_double(getattr(q, "net_capital_flow", None)),
            "net_capital_flow_pct": _safe_double(getattr(q, "net_capital_flow_pct", None)),
            "net_super_flow": _safe_double(getattr(q, "net_super_flow", None)),
            "net_big_flow": _safe_double(getattr(q, "net_big_flow", None)),
            "pledge_ratio": _safe_double(getattr(q, "pledge_ratio", None)),
            "momentum_5d": _safe_double(getattr(q, "momentum_5d", None)),
            "momentum_10d": _safe_double(getattr(q, "momentum_10d", None)),
            "momentum_20d": _safe_double(getattr(q, "momentum_20d", None)),
            "momentum_60d": _safe_double(getattr(q, "momentum_60d", None)),
            "event_score": _safe_double(getattr(q, "event_score", None)),
            "event_detail": getattr(q, "event_detail", None),
            "bond_value": _safe_double(getattr(q, "bond_value", None)),
            "hv": _safe_double(getattr(q, "hv", None)),
            "rating_score": _safe_double(getattr(q, "rating_score", None)),
            "pure_bond_premium_ratio": _safe_double(getattr(q, "pure_bond_premium_ratio", None)),
            "north_net": _safe_double(getattr(q, "north_net", None)),
            "margin_balance": _safe_double(getattr(q, "margin_balance", None)),
            "lhb_count": getattr(q, "lhb_count", None),
            "block_trade_amount": _safe_double(getattr(q, "block_trade_amount", None)),
            "holder_num_change": _safe_double(getattr(q, "holder_num_change", None)),
            "eps_forecast": _safe_double(getattr(q, "eps_forecast", None)),
            "eps": _safe_double(getattr(q, "eps", None)),
            "bps": _safe_double(getattr(q, "bps", None)),
            "revenue_yoy": _safe_double(getattr(q, "revenue_yoy", None)),
            "profit_yoy": _safe_double(getattr(q, "profit_yoy", None)),
            "restricted_release_amount": _safe_double(getattr(q, "restricted_release_amount", None)),
        }
        return tuple(row_map.get(c) for c in cols)

    # daily_snapshots 列定义 + 字段提取器注册表
    # 字典查找 O(1)，列重排不引起顺序错位
    _DS_COLS: list[str] = [
        "code", "name", "open_price", "high_price", "low_price", "close_price", "volume", "snapshot_date",
        "premium_ratio", "change_pct", "stock_price", "conversion_value", "dual_low",
        "ytm", "remaining_years", "roe", "gpm", "cagr", "debt_ratio", "pe", "pb", "iv", "iv_source",
        "buyback_amount", "mgmt_buy_price", "industry", "rating", "outstanding_scale", "stock_code",
        "turnover_rate", "current_ratio",
        "net_capital_flow", "net_capital_flow_pct", "net_super_flow", "net_big_flow",
        "pledge_ratio",
        "momentum_5d", "momentum_10d", "momentum_20d", "momentum_60d",
        "event_score", "event_detail", "bond_value",
        "is_called", "call_status", "forced_call_days",
        "hv", "rating_score", "pure_bond_premium_ratio",
        "north_net", "margin_balance", "lhb_count", "block_trade_amount",
        "holder_num_change", "eps_forecast", "eps", "bps",
        "revenue_yoy", "profit_yoy", "restricted_release_amount",
    ]

    @classmethod
    def _build_ds_field_extractors(cls) -> dict[str, callable]:
        """构建 daily_snapshots 字段提取器注册表。

        snapshot_date 是函数参数注入，不在 quote 上；其余字段直接对应 quote 属性。
        """
        snapshot_holder = {"date": None}

        def _snap(q):
            return snapshot_holder["date"]

        extractors: dict[str, callable] = {
            "code":           lambda q: q.code,
            "name":           lambda q: q.name,
            "open_price":     lambda q: _safe_double(q.price),
            "high_price":     lambda q: _safe_double(q.price),
            "low_price":      lambda q: _safe_double(q.price),
            "close_price":    lambda q: _safe_double(q.price),
            "volume":         lambda q: _safe_double(q.volume),
            "snapshot_date":  _snap,
            "premium_ratio":  lambda q: _safe_double(getattr(q, "premium_ratio", 0), 0),
            "change_pct":     lambda q: _safe_double(getattr(q, "change_pct", 0), 0),
            "stock_price":    lambda q: _safe_double(getattr(q, "stock_price", 0), 0),
            "conversion_value": lambda q: _safe_double(getattr(q, "conversion_value", 0), 0),
            "dual_low":       lambda q: _safe_double(getattr(q, "dual_low", 0), 0),
            "ytm":            lambda q: _safe_double(getattr(q, "ytm", 0), 0),
            "remaining_years": lambda q: _safe_double(getattr(q, "remaining_years", 0), 0),
            "roe":            lambda q: _safe_double(getattr(q, "roe", None)),
            "gpm":            lambda q: _safe_double(getattr(q, "gpm", None), reject_neg1=True),
            "cagr":           lambda q: _safe_double(getattr(q, "cagr", None)),
            "debt_ratio":     lambda q: _safe_double(getattr(q, "debt_ratio", None)),
            "pe":             lambda q: _safe_double(getattr(q, "pe", None)),
            "pb":             lambda q: _safe_double(getattr(q, "pb", None)),
            "iv":             lambda q: _safe_double(getattr(q, "iv", None)),
            "iv_source":      lambda q: str(getattr(q, "iv_source", "") or ""),
            "buyback_amount": lambda q: _safe_double(getattr(q, "buyback_amount", None)),
            "mgmt_buy_price": lambda q: _safe_double(getattr(q, "mgmt_buy_price", None)),
            "industry":       lambda q: getattr(q, "industry", None),
            "rating":         lambda q: getattr(q, "rating", None),
            "outstanding_scale": lambda q: _safe_double(getattr(q, "outstanding_scale", 0), 0),
            "stock_code":     lambda q: getattr(q, "stock_code", "") or "",
            "turnover_rate":  lambda q: _safe_double(getattr(q, "turnover_rate", None)),
            "current_ratio":  lambda q: _safe_double(getattr(q, "current_ratio", None)),
            "net_capital_flow": lambda q: _safe_double(getattr(q, "net_capital_flow", None)),
            "net_capital_flow_pct": lambda q: _safe_double(getattr(q, "net_capital_flow_pct", None)),
            "net_super_flow": lambda q: _safe_double(getattr(q, "net_super_flow", None)),
            "net_big_flow":   lambda q: _safe_double(getattr(q, "net_big_flow", None)),
            "pledge_ratio":   lambda q: _safe_double(getattr(q, "pledge_ratio", None)),
            "momentum_5d":    lambda q: _safe_double(getattr(q, "momentum_5d", None)),
            "momentum_10d":   lambda q: _safe_double(getattr(q, "momentum_10d", None)),
            "momentum_20d":   lambda q: _safe_double(getattr(q, "momentum_20d", None)),
            "momentum_60d":   lambda q: _safe_double(getattr(q, "momentum_60d", None)),
            "event_score":    lambda q: _safe_double(getattr(q, "event_score", None)),
            "event_detail":   lambda q: getattr(q, "event_detail", None),
            "bond_value":     lambda q: _safe_double(getattr(q, "bond_value", None)),
            "is_called":      lambda q: bool(getattr(q, "is_called", False)),
            "call_status":    lambda q: str(getattr(q, "call_status", "") or ""),
            "forced_call_days": lambda q: _safe_double(getattr(q, "forced_call_days", 0), 0),
            "hv":             lambda q: _safe_double(getattr(q, "hv", None)),
            "rating_score":   lambda q: _safe_double(getattr(q, "rating_score", None)),
            "pure_bond_premium_ratio": lambda q: _safe_double(getattr(q, "pure_bond_premium_ratio", None)),
            "north_net":      lambda q: _safe_double(getattr(q, "north_net", None)),
            "margin_balance": lambda q: _safe_double(getattr(q, "margin_balance", None)),
            "lhb_count":      lambda q: getattr(q, "lhb_count", None),
            "block_trade_amount": lambda q: _safe_double(getattr(q, "block_trade_amount", None)),
            "holder_num_change": lambda q: _safe_double(getattr(q, "holder_num_change", None)),
            "eps_forecast":   lambda q: _safe_double(getattr(q, "eps_forecast", None)),
            "eps":            lambda q: _safe_double(getattr(q, "eps", None)),
            "bps":            lambda q: _safe_double(getattr(q, "bps", None)),
            "revenue_yoy":    lambda q: _safe_double(getattr(q, "revenue_yoy", None)),
            "profit_yoy":     lambda q: _safe_double(getattr(q, "profit_yoy", None)),
            "restricted_release_amount": lambda q: _safe_double(getattr(q, "restricted_release_amount", None)),
        }

        # 启动时验证：所有 _DS_COLS 必须注册
        missing = [c for c in cls._DS_COLS if c not in extractors]
        if missing:
            raise RuntimeError(
                f"[Storage] _DS_COLS has columns without registered extractors: {missing}. "
                f"Add them to DataStorage._build_ds_field_extractors()."
            )
        return extractors

    def save_daily_snapshot(self, quotes: list[ConvertibleQuote], snapshot_date: Optional[date] = None) -> None:
        snapshot_date = snapshot_date or date.today()
        # 每次调用重建注册表（snapshot_date 注入到闭包）
        extractors = self._build_ds_field_extractors()

        cols_str = ", ".join(self._DS_COLS)
        phs = ", ".join("?" for _ in self._DS_COLS)
        update_set = ", ".join(
            f"{c} = COALESCE(EXCLUDED.{c}, daily_snapshots.{c})"
            for c in self._DS_COLS
            if c not in ("code", "name", "snapshot_date")
        )
        insert_sql = (
            f"INSERT INTO daily_snapshots ({cols_str}) VALUES ({phs}) "
            f"ON CONFLICT (snapshot_date, code) DO UPDATE SET {update_set}"
        )

        with self._write() as conn:
            # 注入 snapshot_date 到所有 extractors 的闭包
            for extractor in extractors.values():
                # 我们用单独的注入：snap_date 是 _DS_COLS 中唯一非 quote 的字段
                pass
            # 实际上只需为 snapshot_date 注入：使用 wrapper
            def _wrap_snapshot_date(extractor_dict):
                # 找到 snapshot_date 的 extractor 并替换为返回 snapshot_date 的 lambda
                # 但这要求 snapshot_date 在调用时可访问 → 用 lambda 默认参数捕获
                snap_date = snapshot_date  # 闭包
                extractor_dict["snapshot_date"] = lambda q, _d=snap_date: _d
                return extractor_dict

            extractors = _wrap_snapshot_date(extractors)

            for quote in quotes:
                row = tuple(extractors[col](quote) for col in self._DS_COLS)
                conn.execute(insert_sql, row)
        # 前向填充 iv/pe — 在写锁内部执行
        try:
            self._conn.execute('''
                UPDATE daily_snapshots
                SET iv = (
                    SELECT prev.iv FROM daily_snapshots prev
                    WHERE prev.code = daily_snapshots.code
                      AND prev.snapshot_date = (
                          SELECT MAX(sd.snapshot_date) FROM daily_snapshots sd
                          WHERE sd.code = daily_snapshots.code AND sd.snapshot_date < daily_snapshots.snapshot_date
                      )
                      AND prev.iv IS NOT NULL AND prev.iv > 0
                )
                WHERE snapshot_date = ?
                  AND (iv IS NULL OR iv = 0)
            ''', (snapshot_date,))
        except Exception:
            pass

        # 全局前向填充: 对所有历史日期中 iv 为空的记录
        try:
            self._conn.execute('''
                UPDATE daily_snapshots d
                SET iv = (
                    SELECT d2.iv FROM daily_snapshots d2
                    WHERE d2.code = d.code
                      AND d2.snapshot_date < d.snapshot_date
                      AND d2.iv IS NOT NULL
                      AND d2.iv > 0
                    ORDER BY d2.snapshot_date DESC
                    LIMIT 1
                )
                WHERE d.iv IS NULL OR d.iv = 0
            ''')
        except Exception as e:
            logger.debug(f"[Storage] Global iv forward-fill: {e}")

        # 前向填充 pe（当前日期）
        try:
            self._conn.execute('''
                UPDATE daily_snapshots
                SET pe = (
                    SELECT prev.pe FROM daily_snapshots prev
                    WHERE prev.code = daily_snapshots.code
                      AND prev.snapshot_date = (
                          SELECT MAX(sd.snapshot_date) FROM daily_snapshots sd
                          WHERE sd.code = daily_snapshots.code AND sd.snapshot_date < daily_snapshots.snapshot_date
                      )
                      AND prev.pe IS NOT NULL AND prev.pe > 0
                )
                WHERE snapshot_date = ?
                  AND (pe IS NULL OR pe = 0)
            ''', (snapshot_date,))
        except Exception:
            pass

        # 全局前向填充 pe
        try:
            self._conn.execute('''
                UPDATE daily_snapshots d
                SET pe = (
                    SELECT d2.pe FROM daily_snapshots d2
                    WHERE d2.code = d.code
                      AND d2.snapshot_date < d.snapshot_date
                      AND d2.pe IS NOT NULL
                      AND d2.pe > 0
                    ORDER BY d2.snapshot_date DESC
                    LIMIT 1
                )
                WHERE d.pe IS NULL OR d.pe = 0
            ''')
        except Exception as e:
            logger.debug(f"[Storage] Global pe forward-fill: {e}")
        logger.info(f"[Storage] Saved daily snapshot for {snapshot_date}, {len(quotes)} bonds")

    def get_quote_history(self, code: str, limit: int = 100) -> list[dict]:
        cursor = self.conn.execute("""
            SELECT * FROM quotes_history
            WHERE code = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (code, limit))
        return self._query_to_dicts(cursor)

    def get_quote_history_batch(self, codes: list[str], limit: int = 30, start_date: str = "", end_date: str = "") -> dict[str, list[dict]]:
        """Batch query quote history for multiple codes with optional date range."""
        if not codes:
            return {}
        placeholders = ",".join("?" for _ in codes)
        params: list = list(codes)
        date_clause = ""
        if start_date:
            date_clause += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            date_clause += " AND timestamp <= ?"
            params.append(end_date)
        cursor = self.conn.execute(f"""
            SELECT * FROM quotes_history
            WHERE code IN ({placeholders}){date_clause}
            ORDER BY code, timestamp DESC
        """, params)
        rows = self._query_to_dicts(cursor)
        result: dict[str, list[dict]] = {c: [] for c in codes}
        for r in rows:
            code = r.get("code", "")
            if code in result and len(result[code]) < limit:
                result[code].append(r)
        return result

    def get_revision_history(self, code: str) -> list[dict]:
        """Query historical downward revision records for a bond."""
        cursor = self.conn.execute("""
            SELECT code, revision_date, old_price, new_price
            FROM revision_history
            WHERE code = ?
            ORDER BY revision_date DESC
        """, (code,))
        return self._query_to_dicts(cursor)

    def save_revision_history(self, records: list[dict]) -> None:
        """Batch save revision history records."""
        if not records:
            return
        for r in records:
            self.conn.execute("""
                INSERT INTO revision_history (code, revision_date, old_price, new_price)
                VALUES (?, ?, ?, ?)
            """, (r.get("code", ""), r.get("revision_date", ""), r.get("old_price", 0), r.get("new_price", 0)))

    def detect_and_save_revisions(self, bonds: list) -> int:
        """Detect downward revisions by comparing conversion_price with last saved quote.

        Only records when conversion_price decreased (下修). Returns count of new records.
        """
        if not bonds:
            return 0
        codes = [b.code for b in bonds if b.code]
        if not codes:
            return 0

        placeholders = ",".join("?" for _ in codes)
        cursor = self.conn.execute(f"""
            SELECT code, conversion_price
            FROM (
                SELECT code, conversion_price,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY timestamp DESC) as rn
                FROM quotes_history
                WHERE code IN ({placeholders})
            ) WHERE rn = 1
        """, codes)
        last_prices = {row[0]: row[1] for row in cursor.fetchall()}

        today = datetime.now().strftime("%Y-%m-%d")
        new_records = []
        for b in bonds:
            old_price = last_prices.get(b.code)
            if old_price is None or old_price <= 0:
                continue
            if b.conversion_price > 0 and b.conversion_price < old_price:
                new_records.append({
                    "code": b.code,
                    "revision_date": today,
                    "old_price": old_price,
                    "new_price": b.conversion_price,
                })

        if new_records:
            self.save_revision_history(new_records)
            if self._on_revision:
                for rec in new_records:
                    try:
                        self._on_revision(rec)
                    except Exception as e:
                        logger.warning(f"[Storage] Revision callback error: {e}")
        return len(new_records)

    def get_daily_history(self, code: str, days: int = 30) -> list[dict]:
        cursor = self.conn.execute("""
            SELECT * FROM daily_snapshots
            WHERE code = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (code, days))
        return self._query_to_dicts(cursor)

    def get_period_changes_batch(
        self,
        codes: list[str],
        periods: list[int] = (1, 3, 5, 10, 30),
    ) -> dict[str, dict[int, float | None]]:
        """批量查询多周期涨跌幅。

        对每个 code 返回 {period_days: change_pct}，以 close_price 为基准。
        周期不足时返回 None。
        数据来源（按优先级）：
          1. daily_snapshots（每日收盘价，最准确）
          2. quotes_history 聚合（取每日最后一笔成交价，作为兜底）
        使用单条 SQL 一次性取出所有 (code, close_price) 对，按日期偏移计算。
        """
        if not codes or not periods:
            return {}
        max_period = max(periods)
        placeholders = ",".join("?" for _ in codes)
        params: list = list(codes)
        params.append(max_period + 1)
        cursor = self.conn.execute(f"""
            WITH ranked AS (
                SELECT
                    code,
                    close_price,
                    snapshot_date,
                    ROW_NUMBER() OVER (PARTITION BY code ORDER BY snapshot_date DESC) AS rn
                FROM daily_snapshots
                WHERE code IN ({placeholders})
            )
            SELECT code, rn, close_price
            FROM ranked
            WHERE rn <= ?
            ORDER BY code, rn
        """, params)
        rows = cursor.fetchall()
        history: dict[str, list[float]] = {}
        for code, rn, price in rows:
            history.setdefault(code, []).append(float(price) if price is not None else 0.0)

        # 兜底：从 quotes_history 按日聚合取最后一笔成交价
        for code in codes:
            if len(history.get(code, [])) <= max(periods):
                try:
                    fallback = self.conn.execute(f"""
                        WITH daily AS (
                            SELECT code, price,
                                   ROW_NUMBER() OVER (PARTITION BY code, timestamp::DATE ORDER BY timestamp DESC) AS rn_in_day,
                                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY timestamp::DATE DESC) AS day_rank
                            FROM quotes_history
                            WHERE code = ? AND timestamp::DATE >= CURRENT_DATE - INTERVAL '{max_period + 6} days'
                        )
                        SELECT day_rank, price FROM daily WHERE rn_in_day = 1 ORDER BY day_rank
                    """, (code,)).fetchall()
                    if fallback:
                        fb_prices = [float(r[1]) for r in fallback if r[1] is not None]
                        # 合并：fallback 补全 daily_snapshots 缺失的日期
                        existing = history.get(code, [])
                        for i, p in enumerate(fb_prices):
                            if i >= len(existing):
                                existing.append(p)
                        history[code] = existing
                except Exception as e:
                    logger.debug(f"[Storage] quotes_history fallback for {code} failed: {e}")

        result: dict[str, dict[int, float | None]] = {}
        for code in codes:
            prices = history.get(code, [])
            latest = prices[0] if prices else None
            changes: dict[int, float | None] = {}
            for p in periods:
                if latest is None or len(prices) <= p or prices[p] <= 0:
                    changes[p] = None
                else:
                    changes[p] = round((latest - prices[p]) / prices[p] * 100, 2)
            result[code] = changes
        return result

    def get_latest_quotes(self) -> list[dict]:
        cursor = self.conn.execute("""
            WITH latest AS (
                SELECT code, MAX(timestamp) as max_ts
                FROM quotes_history
                GROUP BY code
            )
            SELECT q.* FROM quotes_history q
            JOIN latest l ON q.code = l.code AND q.timestamp = l.max_ts
            ORDER BY q.code
        """)
        return self._query_to_dicts(cursor)

    def cleanup_old_data(self, keep_days: int = 30) -> int:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff - timedelta(days=keep_days)
        with self._write() as conn:
            count_before = conn.execute(
                "SELECT COUNT(*) FROM quotes_history WHERE timestamp < ?", (cutoff,)
            ).fetchone()[0]
            if count_before > 0:
                conn.execute("DELETE FROM quotes_history WHERE timestamp < ?", (cutoff,))
        logger.info(f"[Storage] Cleaned up {count_before} old records")
        return count_before

    def cleanup_signal_history(self, keep_days: int = 30) -> int:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff - timedelta(days=keep_days)
        with self._write() as conn:
            count_before = conn.execute(
                "SELECT COUNT(*) FROM signal_history WHERE ts < ?", (cutoff,)
            ).fetchone()[0]
            if count_before > 0:
                conn.execute("DELETE FROM signal_history WHERE ts < ?", (cutoff,))
        if count_before:
            logger.info(f"[Storage] Cleaned up {count_before} old signal records")
        return count_before

    def save_signals_batch(self, signals: list[dict]) -> None:
        if not signals:
            return
        with self._write() as conn:
            conn.executemany("""
                INSERT INTO signal_history
                (id, strategy, code, name, action, price, reason, confidence, executed, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, [
                (s.get("id") or str(uuid.uuid4())[:8], s.get("strategy", ""), s.get("code", ""), s.get("name", ""),
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
        cursor = self.conn.execute(f"""
            SELECT * FROM signal_history {where}
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
        """, (*params, limit, offset))
        return self._query_to_dicts(cursor), total

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
        with self._write() as conn:
            conn.execute("""
                INSERT INTO executed_positions (code, name, side, price, volume, ts)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (pos.get('code', ''), pos.get('name', ''), pos.get('side', ''),
                  pos.get('price', 0.0), pos.get('volume', 0), pos.get('ts', datetime.now())))

    def save_executed_positions_batch(self, positions: list[dict]) -> None:
        if not positions:
            return
        with self._write() as conn:
            conn.executemany(
                "INSERT INTO executed_positions (code, name, side, price, volume, ts) VALUES (?, ?, ?, ?, ?, ?)",
                [(p.get('code', ''), p.get('name', ''), p.get('side', ''),
                  p.get('price', 0.0), p.get('volume', 0), p.get('ts', datetime.now()))
                 for p in positions]
            )

    def get_executed_positions(self, limit: int = 100, offset: int = 0) -> list[dict]:
        cursor = self.conn.execute("""
            SELECT * FROM executed_positions ORDER BY ts DESC LIMIT ? OFFSET ?
        """, (limit, offset))
        return self._query_to_dicts(cursor)

    def cleanup_executed_positions(self, keep_days: int = 30) -> int:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=keep_days)
        with self._write() as conn:
            count = conn.execute("SELECT COUNT(*) FROM executed_positions WHERE ts < ?", (cutoff,)).fetchone()[0]
            if count > 0:
                conn.execute("DELETE FROM executed_positions WHERE ts < ?", (cutoff,))
        return count

    # ── 评分历史 ──

    def save_score_snapshot(self, scores: list[dict], snapshot_date: Optional[date] = None) -> None:
        """保存每日评分快照"""
        snapshot_date = snapshot_date or date.today()
        if not scores:
            return
        with self._write() as conn:
            for s in scores:
                conn.execute("""
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
        cursor = self.conn.execute("""
            SELECT * FROM score_history
            WHERE code = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (code, days))
        return self._query_to_dicts(cursor)

    def get_score_history_batch(self, codes: list[str], days: int = 30) -> dict[str, list[dict]]:
        """批量获取多只转债的评分历史"""
        if not codes:
            return {}
        placeholders = ",".join(["?" for _ in codes])
        cursor = self.conn.execute(f"""
            SELECT * FROM score_history
            WHERE code IN ({placeholders})
            ORDER BY code, snapshot_date DESC
        """, codes)
        rows = self._query_to_dicts(cursor)

        data = {}
        for row_dict in rows:
            code = row_dict['code']
            if code not in data:
                data[code] = []
            if len(data[code]) < days:
                data[code].append(row_dict)
        return data

    def get_daily_score_ranking(self, snapshot_date: date, top_n: int = 60) -> list[dict]:
        """获取某日的评分排名"""
        cursor = self.conn.execute("""
            SELECT * FROM score_history
            WHERE snapshot_date = ?
            ORDER BY score DESC
            LIMIT ?
        """, (snapshot_date, top_n))
        return self._query_to_dicts(cursor)

    def get_score_dates(self, limit: int = 30) -> list[str]:
        """获取有评分数据的日期列表"""
        result = self.conn.execute("""
            SELECT DISTINCT snapshot_date FROM score_history
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [str(r[0]) for r in result]

    # ── 七维评分快照 ──

    def save_seven_dim_snapshot(self, scores: list[dict], snapshot_date: Optional[date] = None) -> None:
        """保存七维评分快照"""
        snapshot_date = snapshot_date or date.today()
        if not scores:
            return
        with self._write() as conn:
            for s in scores:
                stock = s.get('stock_details', {})
                bond = s.get('bond_details', {})
                conn.execute("""
                    INSERT INTO seven_dim_history
                    (code, name, total_score, stock_score, bond_score,
                     momentum, sector, technical, chip, volatility, news, fundamental,
                     valuation, clause, liquidity, credit,
                     price, premium_ratio, dual_low, snapshot_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_date, code) DO UPDATE SET
                        total_score = excluded.total_score,
                        stock_score = excluded.stock_score,
                        bond_score = excluded.bond_score,
                        momentum = excluded.momentum,
                        sector = excluded.sector,
                        technical = excluded.technical,
                        chip = excluded.chip,
                        volatility = excluded.volatility,
                        news = excluded.news,
                        fundamental = excluded.fundamental,
                        valuation = excluded.valuation,
                        clause = excluded.clause,
                        liquidity = excluded.liquidity,
                        credit = excluded.credit,
                        price = excluded.price,
                        premium_ratio = excluded.premium_ratio,
                        dual_low = excluded.dual_low
                """, (
                    s.get('code', ''), s.get('name', ''),
                    s.get('total', 0), s.get('stock_score', 0), s.get('bond_score', 0),
                    stock.get('momentum', 0), stock.get('sector', 0), stock.get('technical', 0),
                    stock.get('chip', 0), stock.get('volatility', 0), stock.get('news', 0),
                    stock.get('fundamental', 0),
                    bond.get('valuation', 0), bond.get('clause', 0), bond.get('liquidity', 0),
                    bond.get('credit', 0),
                    s.get('price', 0), s.get('premium_ratio', 0), s.get('dual_low', 0),
                    snapshot_date
                ))
        logger.info(f"[Storage] Saved seven-dim snapshot for {snapshot_date}, {len(scores)} bonds")

    def get_seven_dim_history(self, code: str, days: int = 30) -> list[dict]:
        """获取某只转债的七维评分历史"""
        cursor = self.conn.execute("""
            SELECT * FROM seven_dim_history
            WHERE code = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (code, days))
        return self._query_to_dicts(cursor)

    def get_seven_dim_dates(self, limit: int = 30) -> list[str]:
        """获取有七维评分数据的日期列表"""
        result = self.conn.execute("""
            SELECT DISTINCT snapshot_date FROM seven_dim_history
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [str(r[0]) for r in result]

    # ── 回测结果持久化 ──

    def save_backtest_result(self, summary: dict, details: list[dict], params: dict) -> int:
        """保存回测结果，返回backtest_id"""
        with self._write() as conn:
            conn.execute("""
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
            backtest_id = conn.execute("SELECT currval('backtest_results_id_seq')").fetchone()[0]
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
                conn.executemany("""
                    INSERT INTO backtest_details
                    (backtest_id, date, end_date, top_n, avg_return_pct,
                     win_rate, max_return, min_return, max_drawdown)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, rows)
            return backtest_id

    def get_backtest_results(self, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        """获取最近的回测结果列表，返回 (results, total_count)"""
        total = self.conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
        cursor = self.conn.execute("""
            SELECT * FROM backtest_results ORDER BY run_ts DESC LIMIT ? OFFSET ?
        """, (limit, offset))
        return self._query_to_dicts(cursor), total

    def get_backtest_result(self, backtest_id: int) -> dict | None:
        """按 ID 获取单条回测结果"""
        cursor = self.conn.execute("SELECT * FROM backtest_results WHERE id = ?", (backtest_id,))
        columns = [desc[0] for desc in cursor.description]
        result = cursor.fetchone()
        if not result:
            return None
        return dict(zip(columns, result))

    def get_backtest_details(self, backtest_id: int) -> list[dict]:
        """获取某次回测的详情"""
        cursor = self.conn.execute("""
            SELECT * FROM backtest_details WHERE backtest_id = ? ORDER BY date
        """, (backtest_id,))
        return self._query_to_dicts(cursor)

    def delete_backtest_result(self, backtest_id: int) -> bool:
        """删除某次回测结果及其详情"""
        with self._write() as conn:
            count = conn.execute("SELECT COUNT(*) FROM backtest_results WHERE id = ?", (backtest_id,)).fetchone()[0]
            if count == 0:
                return False
            conn.execute("DELETE FROM backtest_details WHERE backtest_id = ?", (backtest_id,))
            conn.execute("DELETE FROM backtest_results WHERE id = ?", (backtest_id,))
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
        with self._write() as conn:
            placeholders = ",".join("?" * len(id_list))
            conn.execute(f"DELETE FROM backtest_details WHERE backtest_id IN ({placeholders})", id_list)
            conn.execute(f"DELETE FROM backtest_results WHERE id IN ({placeholders})", id_list)
        logger.info(f"[Storage] Cleaned up {len(id_list)} old backtest results")
        return len(id_list)

    def cleanup_score_history(self, keep_days: int = 90) -> int:
        """清理过期的评分历史"""
        cutoff = date.today() - timedelta(days=keep_days)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM score_history WHERE snapshot_date < ?", (cutoff,)
        ).fetchone()[0]
        if count > 0:
            with self._write() as conn:
                conn.execute("DELETE FROM score_history WHERE snapshot_date < ?", (cutoff,))
            logger.info(f"[Storage] Cleaned up {count} old score records")
        return count

    def cleanup_seven_dim_history(self, keep_days: int = 90) -> int:
        """清理过期的七维评分历史"""
        cutoff = date.today() - timedelta(days=keep_days)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM seven_dim_history WHERE snapshot_date < ?", (cutoff,)
        ).fetchone()[0]
        if count > 0:
            with self._write() as conn:
                conn.execute("DELETE FROM seven_dim_history WHERE snapshot_date < ?", (cutoff,))
            logger.info(f"[Storage] Cleaned up {count} old seven-dim records")
        return count

    # ── 评分预警 ──

    def add_score_alert(self, alert: dict) -> int:
        """添加评分预警"""
        with self._write() as conn:
            conn.execute("""
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
            return conn.execute("SELECT currval('score_alerts_id_seq')").fetchone()[0]

    def remove_score_alert(self, alert_id: int) -> None:
        """删除评分预警"""
        with self._write() as conn:
            conn.execute("DELETE FROM score_alerts WHERE id = ?", (alert_id,))

    def get_score_alerts(self, enabled_only: bool = False) -> list[dict]:
        """获取所有评分预警"""
        where = "WHERE enabled = TRUE" if enabled_only else ""
        cursor = self.conn.execute(f"SELECT * FROM score_alerts {where}")
        return self._query_to_dicts(cursor)

    def update_alert_triggered(self, alert_id: int) -> None:
        """更新预警触发时间"""
        with self._write() as conn:
            conn.execute(
                "UPDATE score_alerts SET triggered_at = ? WHERE id = ?",
                (datetime.now(), alert_id)
            )

    def add_alert_history(self, record: dict) -> int:
        """添加预警触发历史记录"""
        with self._write() as conn:
            conn.execute("""
                INSERT INTO alert_history
                (alert_id, alert_type, code, name, threshold, current_value, triggered_at, acknowledged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.get('alert_id'), record.get('alert_type', 'score'),
                record.get('code', ''), record.get('name', ''),
                record.get('threshold', 0), record.get('current_value', 0),
                record.get('triggered_at', datetime.now()), False
            ))
            return conn.execute("SELECT currval('alert_history_id_seq')").fetchone()[0]

    def get_alert_history(self, days: int = 30, code: str = "") -> list[dict]:
        """获取预警历史记录"""
        cutoff = datetime.now() - timedelta(days=days)
        if code:
            cursor = self.conn.execute("""
                SELECT * FROM alert_history
                WHERE triggered_at >= ? AND code = ?
                ORDER BY triggered_at DESC
            """, (cutoff, code))
        else:
            cursor = self.conn.execute("""
                SELECT * FROM alert_history
                WHERE triggered_at >= ?
                ORDER BY triggered_at DESC
            """, (cutoff,))
        return self._query_to_dicts(cursor)

    def acknowledge_alert(self, history_id: int) -> None:
        """确认预警记录"""
        with self._write() as conn:
            conn.execute(
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
            with self._write() as conn:
                conn.execute("DELETE FROM alert_history WHERE triggered_at < ?", (cutoff,))
            logger.info(f"[Storage] Cleaned up {count} old alert history records")
        return count

    # ── 组合预警 ──

    def add_combo_alert(self, alert: dict) -> int:
        """添加组合预警"""
        with self._write() as conn:
            conn.execute("""
                INSERT INTO combo_alerts (name, description, conditions, logic, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                alert.get('name', ''), alert.get('description', ''),
                json.dumps(alert.get('conditions', [])),
                alert.get('logic', 'AND'), alert.get('enabled', True), datetime.now()
            ))
            return conn.execute("SELECT currval('combo_alerts_id_seq')").fetchone()[0]

    def remove_combo_alert(self, alert_id: int) -> None:
        """删除组合预警"""
        with self._write() as conn:
            conn.execute("DELETE FROM combo_alerts WHERE id = ?", (alert_id,))

    def get_combo_alerts(self, enabled_only: bool = False) -> list[dict]:
        """获取所有组合预警"""
        where = "WHERE enabled = TRUE" if enabled_only else ""
        cursor = self.conn.execute(f"SELECT * FROM combo_alerts {where}")
        alerts = self._query_to_dicts(cursor)
        for a in alerts:
            a['conditions'] = json.loads(a['conditions']) if a.get('conditions') else []
        return alerts

    def update_combo_alert_triggered(self, alert_id: int) -> None:
        """更新组合预警触发时间"""
        with self._write() as conn:
            conn.execute(
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
            "seven_dim": self.cleanup_seven_dim_history(keep_days),
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
        with self._write() as conn:
            conn.execute("""
                INSERT INTO app_config (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (key, value, datetime.now()))

    def load_buffer_tracker(self) -> dict:
        """从 DuckDB 加载缓冲带状态，返回 {code: {in_buffer, days_in_buffer, ...}}"""
        try:
            rows = self.conn.execute(
                "SELECT code, in_buffer, days_in_buffer, days_above_60, days_below_60 FROM buffer_tracker"
            ).fetchall()
            return {row[0]: {
                'in_buffer': bool(row[1]),
                'days_in_buffer': int(row[2]),
                'days_above_60': int(row[3]),
                'days_below_60': int(row[4]),
            } for row in rows}
        except Exception as e:
            logger.warning(f"[Storage] load_buffer_tracker failed: {e}")
            return {}

    def save_buffer_tracker(self, tracker: dict) -> None:
        """持久化缓冲带状态到 DuckDB"""
        if not tracker:
            return
        with self._write() as conn:
            conn.execute("DELETE FROM buffer_tracker")
            for code, status in tracker.items():
                conn.execute(
                    "INSERT INTO buffer_tracker (code, in_buffer, days_in_buffer, days_above_60, days_below_60, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (code, bool(status.in_buffer) if hasattr(status, 'in_buffer') else bool(status.get('in_buffer', False)),
                     int(status.days_in_buffer) if hasattr(status, 'days_in_buffer') else int(status.get('days_in_buffer', 0)),
                     int(status.days_above_60) if hasattr(status, 'days_above_60') else int(status.get('days_above_60', 0)),
                     int(status.days_below_60) if hasattr(status, 'days_below_60') else int(status.get('days_below_60', 0))))
            logger.info(f"[Storage] Saved buffer tracker: {len(tracker)} entries")

    def close(self):
        """关闭数据库连接，先取消定时器再关闭连接"""
        if self._checkpoint_timer:
            self._checkpoint_timer.cancel()
            self._checkpoint_timer = None
        try:
            self._conn.close()
            logger.info("[Storage] Connection closed")
        except Exception as e:
            logger.debug(f"[Storage] Close connection: {e}")

    def ensure_connection(self):
        """确保数据库连接可用，断连时自动重建"""
        try:
            self._conn.execute("SELECT 1")
        except Exception:
            self._reconnect()

    @contextmanager
    def _write(self):
        """获取写锁并确保连接可用 — 带BusyError重试"""
        with self._write_lock:
            self.ensure_connection()
            yield self._conn

    def _execute_with_retry(self, sql: str, params=None, max_retries: int = 3) -> None:
        """执行SQL，遇到 DuckDB BusyError 自动重试"""
        import time as _time
        for attempt in range(max_retries + 1):
            try:
                if params:
                    self._conn.execute(sql, params)
                else:
                    self._conn.execute(sql)
                return
            except Exception as e:
                err_str = str(e).lower()
                is_busy = "busy" in err_str or "timeout" in err_str or "lock" in err_str
                if is_busy and attempt < max_retries:
                    wait = 0.2 * (2 ** attempt)
                    _time.sleep(wait)
                    self.ensure_connection()
                    continue
                raise

    def checkpoint(self):
        """执行 DuckDB WAL checkpoint，将 WAL 数据写入主文件"""
        if self._read_only:
            return
        try:
            with self._write() as conn:
                conn.execute("CHECKPOINT")
            logger.info("[Storage] Checkpoint completed")
        except Exception as e:
            logger.error(f"[Storage] Checkpoint failed: {e}")

    def _start_checkpoint_timer(self):
        """启动定时 checkpoint"""
        self._checkpoint_timer = threading.Timer(self._checkpoint_interval, self._checkpoint_loop)
        self._checkpoint_timer.daemon = True
        self._checkpoint_timer.start()

    def _checkpoint_loop(self):
        """定时执行 checkpoint"""
        self.checkpoint()
        if self._checkpoint_interval > 0:
            self._start_checkpoint_timer()
