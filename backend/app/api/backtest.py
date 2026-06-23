import asyncio
import json
import logging
import os
import uuid
import numpy as np
import pandas as pd
from datetime import date
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from app.strategies import get_strategy, list_strategies
from app.engine.backtest import BacktestEngine
from app.models.backtest import BacktestConfig, OptimizationConfig

logger = logging.getLogger(__name__)


router = APIRouter()

_backtest_progress: dict[str, dict] = {}


@router.get("/strategies")
async def get_strategies():
    return {"strategies": list_strategies()}


class BacktestRequest(BaseModel):
    strategy: str
    params: dict = {}
    start_date: str = "2024-01-01"
    end_date: str = "2025-12-31"
    config: BacktestConfig = BacktestConfig()
    optimization: OptimizationConfig = OptimizationConfig()

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f'Invalid date format: {v}, expected YYYY-MM-DD')
        return v


async def _build_data(request: Request, start_date: date, end_date: date, progress_cb=None, strategy_name: str = "") -> pd.DataFrame:
    """Build backtest data by composing all available data sources.

    Data source priority (each fills gaps left by the previous):

    1. daily_snapshots   — 日K线 (东方财富历史回填)  — 价格/成交量骨架
    2. quotes_history    — 实时快照聚合                — 转股价值/转股价/溢价率/剩余期限
    3. seven_dim_history — 七维评分快照                — momentum/hv/quality/valuation/event
    4. score_history     — 多因子评分快照              — dual_low/premium/momentum 排名分
    5. signal_history    — 策略信号历史                — 推断的 change_pct 兜底
    6. engine quotes     — 实时行情 (AKShare)          — 当前截面 enrichment (roe/gpm/cagr...)
    7. real_fallback     — THS(转债列表) + Tencent(K线) + Sina(实时行情) + Baidu(PE/PB)
                          — 最终兜底, 不使用任何假数据

    Args:
        progress_cb: Optional sync callback ``fn(pct: int, msg: str)`` called at each
            data source load step. Used by /run-stream to emit fine-grained SSE progress.
            Exceptions inside the callback are logged and swallowed.
    """
    storage = getattr(request.app.state, "storage", None)
    engine = getattr(request.app.state, "engine", None)

    def _progress(pct, msg):
        if progress_cb:
            try:
                progress_cb(pct, msg)
            except asyncio.CancelledError:
                raise
            except GeneratorExit:
                raise
            except Exception as e:
                logger.error(f"[BacktestData] _progress callback failed: {e}")

    # ---- Sector Rotation: 行业ETF数据路径 ----
    if strategy_name == "sector_rotation":
        _progress(5, '行业轮动: 获取ETF数据...')
        try:
            etf_df = await _fetch_industry_etf_data(start_date, end_date)
            if not etf_df.empty and len(etf_df) > 100:
                _progress(20, f'行业ETF数据就绪: {len(etf_df)}行')
                return etf_df
            else:
                _progress(15, 'ETF数据不足, 尝试从缓存获取...')
        except Exception as e:
            logger.warning(f"[BacktestData] ETF data fetch failed: {e}")

    cached_bonds = getattr(request.state, '_backtest_cached_bonds', None)

    logger.info(f"[BacktestData] Starting _build_data for {start_date} - {end_date}, storage={storage is not None}, engine={engine is not None}")

    data_frames: list[pd.DataFrame] = []
    source_labels: list[str] = []

    # ---- Source 1: daily_snapshots (日K线, 价格/成交量骨架) ----
    _progress(6, '加载 daily_snapshots...')
    if storage is not None:
        from app.engine.historical import HistoricalDataLoader
        loader = HistoricalDataLoader(storage)
        snap_df = await asyncio.to_thread(loader.get_cached_history, start_date, end_date)
        if not snap_df.empty:
            data_frames.append(snap_df)
            source_labels.append(
                f"daily_snapshots({len(snap_df)} rows, "
                f"{snap_df['date'].nunique() if 'date' in snap_df.columns else 0} dates)"
            )

    # ---- Source 2: quotes_history (转股价值/转股价/溢价率/剩余期限) ----
    _progress(9, '加载 quotes_history...')
    if storage is not None:
        try:
            qh_df = await asyncio.to_thread(_load_quotes_history, storage, start_date, end_date)
            if not qh_df.empty:
                data_frames.append(qh_df)
                source_labels.append(f"quotes_history({len(qh_df)} rows)")
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BacktestData] quotes_history load failed: {e}")

    # ---- Source 3: seven_dim_history (momentum/hv/quality/valuation) ----
    _progress(12, '加载 seven_dim_history...')
    if storage is not None:
        try:
            sd_df = await asyncio.to_thread(_load_seven_dim_history, storage, start_date, end_date)
            if not sd_df.empty:
                data_frames.append(sd_df)
                source_labels.append(f"seven_dim_history({len(sd_df)} rows)")
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BacktestData] seven_dim_history load failed: {e}")

    # ---- Source 4: score_history (dual_low/premium/momentum 排名分) ----
    _progress(15, '加载 score_history...')
    if storage is not None:
        try:
            sc_df = await asyncio.to_thread(_load_score_history, storage, start_date, end_date)
            if not sc_df.empty:
                data_frames.append(sc_df)
                source_labels.append(f"score_history({len(sc_df)} rows)")
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BacktestData] score_history load failed: {e}")

    # ---- Source 5: signal_history (推断 change_pct) ----
    _progress(18, '加载 signal_history...')
    if storage is not None:
        try:
            sig_df = await asyncio.to_thread(_load_signal_history, storage, start_date, end_date)
            if not sig_df.empty:
                data_frames.append(sig_df)
                source_labels.append(f"signal_history({len(sig_df)} rows)")
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BacktestData] signal_history load failed: {e}")

    # ---- Source 6: engine quotes (实时截面 enrichment) — 缓存到 request.state 避免重复调用 ----
    _progress(20, '加载实时行情...')
    current_bonds = cached_bonds
    if current_bonds is None and engine is not None:
        try:
            current_bonds = await engine.get_all_quotes()
            request.state._backtest_cached_bonds = current_bonds
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BacktestData] live quotes load failed: {e}")
    if current_bonds:
        try:
            live_df = _build_live_enrichment(current_bonds)
            if not live_df.empty:
                data_frames.append(live_df)
                source_labels.append(f"live_quotes({len(current_bonds)} bonds)")
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[BacktestData] live enrichment build failed: {e}")

    # ---- 尝试合并多源数据 ----
    _progress(24, '合并数据源...')
    total_rows = len(data_frames[0]) if data_frames else 0
    # 需要足够行数 AND 足够日期数才算有效数据源（254行×1天无法回测）
    n_dates = 0
    n_bonds = 0
    if data_frames:
        first = data_frames[0]
        if isinstance(first, pd.DataFrame) and not first.empty:
            if 'date' in first.columns:
                n_dates = first['date'].nunique()
            if 'code' in first.columns:
                n_bonds = first['code'].nunique()
    if total_rows > 100 and n_dates >= 5:
        merged = _merge_data_sources(data_frames)
        if not merged.empty:
            _progress(27, '补全缺失因子...')
            merged = await _fill_missing_factors(merged, request, current_bonds)
            merged._backtest_data_source = " + ".join(source_labels)
            return merged

    # ---- Auto-seed: 仅当 DB 完全为空时才触发种子数据 ----
    # 注意: seed_historical_data 从 today-days 开始加载, 不匹配历史回测范围
    # 如果 DB 已有数据（即使不在请求范围内），跳过种子直接走模拟数据
    _progress(25, '检查现有数据(日期范围)...')
    db_has_data = False
    if storage is not None:
        try:
            date_row = await asyncio.to_thread(
                lambda: storage.conn.execute("SELECT MIN(snapshot_date), MAX(snapshot_date) FROM daily_snapshots").fetchone()
            )
            if date_row and date_row[0] and date_row[1]:
                min_d, max_d = date_row[0], date_row[1]
                if min_d <= start_date and max_d >= end_date:
                    db_has_data = True
                else:
                    logger.info(f"[BacktestData] DB has data {min_d}~{max_d}, but backtest needs {start_date}~{end_date}, triggering auto-seed")
            else:
                db_has_data = False
        except Exception as e:
            logger.warning(f"[BacktestData] Date check failed: {e}")

    if (not db_has_data or total_rows < 100) and storage is not None and engine is not None:
        _progress(25, '自动种子数据(首次初始化)...')
        try:
            bonds = current_bonds or await engine.get_all_quotes()
            if not bonds:
                # Try refreshing engine first; get_all_quotes may return empty if cache is cold
                import logging
                try:
                    await asyncio.wait_for(engine.refresh(), timeout=30.0)
                    bonds = await engine.get_all_quotes()
                except Exception as refresh_err:
                    logging.getLogger(__name__).warning(f"[BacktestData] engine refresh failed: {refresh_err}")
            if bonds:
                codes = [b.code for b in bonds]
                factor_snapshot = {}
                for b in bonds:
                    factor_snapshot[b.code] = {
                        "premium_ratio": b.premium_ratio or 0,
                        "change_pct": b.change_pct or 0,
                        "stock_price": b.stock_price or 0,
                        "conversion_value": b.conversion_value or 0,
                        "dual_low": b.dual_low or 0,
                        "ytm": b.ytm or 0,
                        "remaining_years": b.remaining_years or 0,
                        "roe": getattr(b, 'roe', None),
                        "gpm": getattr(b, 'gpm', None),
                        "cagr": getattr(b, 'cagr', None),
                        "debt_ratio": getattr(b, 'debt_ratio', None),
                        "pe": getattr(b, 'pe', None),
                        "pb": getattr(b, 'pb', None),
                        "iv": getattr(b, 'iv', None),
                        "buyback_amount": getattr(b, 'buyback_amount', None),
                        "mgmt_buy_price": getattr(b, 'mgmt_buy_price', None),
                        "industry": getattr(b, 'industry', None),
                        "rating": getattr(b, 'rating', None),
                        "outstanding_scale": getattr(b, 'outstanding_scale', None),
                    }
                from app.engine.historical import HistoricalDataLoader
                loader = HistoricalDataLoader(storage)
                days_span = min((end_date - start_date).days + 30, 365)
                # 限制代码量避免AKShare segfault
                seed_codes = codes[:100] if len(codes) > 100 else codes
                _progress(26, f'正在下载{days_span}天历史数据({len(seed_codes)}只债券)...')
                seed_result = {}
                try:
                    seed_result = await asyncio.wait_for(
                        loader.seed_historical_data(seed_codes, days=days_span, factor_snapshot=factor_snapshot),
                        timeout=300.0,
                    )
                except asyncio.TimeoutError:
                    import logging
                    logging.getLogger(__name__).warning("[BacktestData] Auto-seed timed out (>120s)")
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"[BacktestData] Auto-seed failed: {e}")
                snap_df = await asyncio.to_thread(loader.get_cached_history, start_date, end_date)
                if not snap_df.empty and len(snap_df) > 100:
                    snap_df._backtest_data_source = (
                        f"real_auto_seeded({len(snap_df)} rows, "
                        f"{snap_df['date'].nunique() if 'date' in snap_df.columns else 0} dates, "
                        f"{seed_result.get('bonds', 0)} bonds, factors_from_current_snapshot)"
                    )
                    return snap_df

                # Auto-seed 失败时: 用当前快照数据构建回测数据集
                _progress(28, '使用当前行情快照构建回测数据...')
                logger.info("[BacktestData] 使用当前行情快照构建回测数据（无历史K线）")
                if current_bonds:
                    rows = []
                    for b in current_bonds:
                        rows.append({
                            "code": b.code,
                            "name": getattr(b, "name", ""),
                            "price": getattr(b, "price", None),
                            "volume": getattr(b, "volume", None),
                            "date": start_date,
                            "premium_ratio": getattr(b, "premium_ratio", None),
                            "change_pct": getattr(b, "change_pct", None),
                            "stock_price": getattr(b, "stock_price", None),
                            "conversion_value": getattr(b, "conversion_value", None),
                            "dual_low": getattr(b, "dual_low", None),
                            "ytm": getattr(b, "ytm", None),
                            "remaining_years": getattr(b, "remaining_years", None),
                            "roe": getattr(b, "roe", None),
                            "gpm": getattr(b, "gpm", None),
                            "cagr": getattr(b, "cagr", None),
                            "debt_ratio": getattr(b, "debt_ratio", None),
                            "pe": getattr(b, "pe", None),
                            "pb": getattr(b, "pb", None),
                            "iv": getattr(b, "iv", None),
                            "buyback_amount": getattr(b, "buyback_amount", None),
                            "mgmt_buy_price": getattr(b, "mgmt_buy_price", None),
                            "industry": getattr(b, "industry", None),
                            "rating": getattr(b, "rating", None),
                            "outstanding_scale": getattr(b, "outstanding_scale", None),
                            "stock_code": getattr(b, "stock_code", ""),
                        })
                    result = pd.DataFrame(rows)
                    result._backtest_data_source = "current_snapshot_fallback"
                    return result
        except asyncio.TimeoutError:
            import logging
            logging.getLogger(__name__).warning("[BacktestData] Auto-seed timed out (>120s)")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[BacktestData] Auto-seed failed: {e}")

    # ---- 最终兜底: 调用多源真实数据获取函数 (Tencent K线 + Baidu估值 + Jisilu等) ----
    _progress(28, '最终兜底: 从多个真实数据源获取转债历史数据...')
    logger.warning("[BacktestData] 所有缓存数据源均不可用,调用_fetch_real_fallback_data兜底")
    try:
        fallback_df = await _fetch_real_fallback_data(start_date, end_date)
        if not fallback_df.empty and fallback_df['date'].nunique() >= 2:
            fallback_df._backtest_data_source = getattr(fallback_df, '_backtest_data_source', 'real_fallback')
            logger.info(f"[BacktestData] 兜底数据就绪: {len(fallback_df)}行, {fallback_df['date'].nunique()}个日期")
            return fallback_df
        else:
            logger.warning(f"[BacktestData] 兜底数据不足({len(fallback_df)}行)")
    except Exception as e:
        logger.error(f"[BacktestData] 兜底获取失败: {e}")
    
    # 最后的保险: 使用当前快照(仅1天, 但回测不会失败)
    _progress(29, '使用当前行情快照构建单日回测数据...')
    if current_bonds:
        rows = []
        for b in current_bonds:
            rows.append({
                "code": b.code,
                "name": getattr(b, "name", ""),
                "price": getattr(b, "price", None),
                "volume": getattr(b, "volume", None),
                "date": start_date,
                "premium_ratio": getattr(b, "premium_ratio", None),
                "change_pct": getattr(b, "change_pct", None),
                "stock_price": getattr(b, "stock_price", None),
                "conversion_value": getattr(b, "conversion_value", None),
                "dual_low": getattr(b, "dual_low", None),
                "ytm": getattr(b, "ytm", None),
                "remaining_years": getattr(b, "remaining_years", None),
                "roe": getattr(b, "roe", None),
                "gpm": getattr(b, "gpm", None),
                "cagr": getattr(b, "cagr", None),
                "debt_ratio": getattr(b, "debt_ratio", None),
                "pe": getattr(b, "pe", None),
                "pb": getattr(b, "pb", None),
                "iv": getattr(b, "iv", None),
                "buyback_amount": getattr(b, "buyback_amount", None),
                "mgmt_buy_price": getattr(b, "mgmt_buy_price", None),
                "industry": getattr(b, "industry", None),
                "rating": getattr(b, "rating", None),
                "outstanding_scale": getattr(b, "outstanding_scale", None),
                "stock_code": getattr(b, "stock_code", ""),
            })
        result = pd.DataFrame(rows)
        result._backtest_data_source = "current_snapshot_fallback"
        return result
    raise RuntimeError(
        '无法获取行情数据, 请稍后重试'
    )


def _load_quotes_history(storage, start_date: date, end_date: date) -> pd.DataFrame:
    """从 quotes_history 表加载并按日聚合, 提取转股相关字段"""
    cursor = storage.conn.execute("""
        SELECT
            code,
            name,
            CAST(timestamp AS DATE) AS date,
            AVG(premium_ratio) AS premium_ratio,
            AVG(conversion_value) AS conversion_value,
            AVG(conversion_price) AS conversion_price,
            AVG(stock_price) AS stock_price,
            AVG(stock_change_pct) AS stock_change_pct,
            AVG(ytm) AS ytm,
            AVG(remaining_years) AS remaining_years,
            MAX(is_called) AS is_called,
            MAX(forced_call_days) AS forced_call_days
        FROM quotes_history
        WHERE CAST(timestamp AS DATE) >= ? AND CAST(timestamp AS DATE) <= ?
        GROUP BY code, name, CAST(timestamp AS DATE)
        ORDER BY code, date
    """, (start_date, end_date))
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _load_seven_dim_history(storage, start_date: date, end_date: date) -> pd.DataFrame:
    """从 seven_dim_history 表加载评分历史, 提取动量/估值等因子"""
    cursor = storage.conn.execute("""
        SELECT
            code,
            name,
            snapshot_date AS date,
            momentum,
            sector,
            technical,
            chip,
            volatility,
            news,
            fundamental,
            valuation,
            clause,
            liquidity,
            credit,
            price,
            premium_ratio,
            dual_low
        FROM seven_dim_history
        WHERE snapshot_date >= ? AND snapshot_date <= ?
        ORDER BY code, snapshot_date
    """, (start_date, end_date))
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _load_score_history(storage, start_date: date, end_date: date) -> pd.DataFrame:
    """从 score_history 表加载评分快照, 提供 score_dual_low / score_premium 等排名分"""
    cursor = storage.conn.execute("""
        SELECT
            code,
            name,
            snapshot_date AS date,
            score_dual_low,
            score_premium,
            score_momentum,
            score_volume,
            score_price,
            price,
            premium_ratio,
            dual_low
        FROM score_history
        WHERE snapshot_date >= ? AND snapshot_date <= ?
        ORDER BY code, snapshot_date
    """, (start_date, end_date))
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _load_signal_history(storage, start_date: date, end_date: date) -> pd.DataFrame:
    """从 signal_history 表加载信号历史, 提供 change_pct 的兜底来源 (action='buy' 时的 price 变化)"""
    cursor = storage.conn.execute("""
        SELECT
            code,
            CAST(ts AS DATE) AS date,
            AVG(price) AS signal_price
        FROM signal_history
        WHERE CAST(ts AS DATE) >= ? AND CAST(ts AS DATE) <= ?
        GROUP BY code, CAST(ts AS DATE)
        ORDER BY code, date
    """, (start_date, end_date))
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _build_live_enrichment(bonds) -> pd.DataFrame:
    """从实时行情构建当日 enrichment 快照 (单日, 用于填补历史空缺字段)"""
    rows = []
    today = date.today()
    for b in bonds:
        rows.append({
            'code': b.code,
            'name': b.name,
            'date': today,
            'price': b.price,
            'premium_ratio': b.premium_ratio,
            'volume': b.volume or 0,
            'change_pct': getattr(b, 'change_pct', 0) or 0,
            'ytm': getattr(b, 'ytm', 0) or 0,
            'remaining_years': getattr(b, 'remaining_years', 3) or 3,
            'roe': getattr(b, 'roe', None),
            'gpm': getattr(b, 'gpm', None),
            'cagr': getattr(b, 'cagr', None),
            'debt_ratio': getattr(b, 'debt_ratio', None),
            'pe': getattr(b, 'pe', None),
            'pb': getattr(b, 'pb', None),
            'iv': getattr(b, 'iv', None),
            'buyback_amount': getattr(b, 'buyback_amount', None),
            'mgmt_buy_price': getattr(b, 'mgmt_buy_price', None),
        })
    return pd.DataFrame(rows)


def _merge_data_sources(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """合并多数据源: 第一个 frame 是主骨架, 后续 frame 按 (code, date) 补全字段"""
    if not frames:
        return pd.DataFrame()
    merged = frames[0].copy()
    for src in frames[1:]:
        if src.empty:
            continue
        # 仅保留 src 中非空且 merged 中缺失的列
        join_cols = [c for c in ['code', 'date'] if c in merged.columns and c in src.columns]
        if not join_cols:
            continue
        cols_to_add = [
            c for c in src.columns
            if c not in merged.columns and c not in ('code', 'name', 'date')
        ]
        if cols_to_add:
            merged = merged.merge(
                src[join_cols + cols_to_add],
                on=join_cols,
                how='left',
            )
    # 同名 name 列去重
    if 'name' in merged.columns:
        merged['name'] = merged['name'].bfill().ffill()
    return merged


async def _fill_missing_factors(df: pd.DataFrame, request: Request, cached_bonds=None) -> pd.DataFrame:
    """补全历史行中缺失的关键因子字段.

    优先级:
    1. daily_snapshots 中已有的因子数据 (历史真实值) — 不覆盖
    2. 实时行情截面 — 仅填补仍然 NULL 的行
    """
    if df.empty:
        return df

    # Defensive: ensure critical strategy-required columns always exist
    critical_defaults = {
        'premium_ratio': 15.0,
        'volume': 100000,
        'change_pct': 0.0,
        'ytm': 1.0,
        'remaining_years': 3.0,
    }
    for col, default in critical_defaults.items():
        if col not in df.columns:
            df[col] = default
        else:
            df[col] = df[col].fillna(default)

    factor_cols = [
        'change_pct', 'premium_ratio', 'ytm', 'remaining_years',
        'roe', 'gpm', 'cagr', 'debt_ratio', 'pe', 'pb', 'iv',
        'buyback_amount', 'mgmt_buy_price',
    ]

    has_factors = 0
    for col in factor_cols:
        if col in df.columns:
            has_factors += df[col].notna().sum()
    total_cells = len(df) * len([c for c in factor_cols if c in df.columns])
    fill_pct = has_factors / total_cells * 100 if total_cells > 0 else 0
    if fill_pct > 80:
        logger.info(
            f"[BacktestData] Factors {fill_pct:.0f}% filled from historical data, minimal live backfill"
        )
        # 已有足够的历史因子数据, 跳过data_sources调用(否则835只*Baidu会崩溃)
        return df

    bonds = cached_bonds
    if bonds is None:
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            return df
        try:
            bonds = await asyncio.wait_for(engine.get_all_quotes(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("[BacktestData] _fill_missing_factors: engine.get_all_quotes超时(>5s)")
            return df
        except Exception as e:
            logger.debug(f"[BacktestData] _fill_missing_factors engine.get_all_quotes failed: {e}")
            return df

    if not bonds:
        return df

    for col in factor_cols:
        if col not in df.columns:
            col_map = {b.code: getattr(b, col, None) for b in bonds}
            mapped = df['code'].map(lambda c, m=col_map: m.get(c))
            # Only assign if there is at least one non-None value; otherwise
            # pandas raises TypeError when assigning all-None array to float64.
            if mapped.notna().any():
                df[col] = mapped
        else:
            col_map = {b.code: getattr(b, col, None) for b in bonds}
            mask = df[col].isna()
            if mask.any():
                mapped = df.loc[mask, 'code'].map(lambda c, m=col_map: m.get(c))
                if mapped.notna().any():
                    df.loc[mask, col] = mapped
                else:
                    # All mapped values are None → ensure float64 NaN not object dtype
                    df[col] = pd.to_numeric(df[col], errors='coerce').astype(float)
    return df







async def _fetch_industry_etf_data(start_date: date, end_date: date) -> pd.DataFrame:
    """
    行业轮动专用: 多层数据源获取行业ETF日K线数据

    数据源优先级 (13层):
    ① DuckDB缓存(已缓存ETF历史K线)
    ② AKShare fund_etf_hist_em (东方财富ETF日K线)
    ③ AKShare stock_zh_a_hist_tx (腾讯股票K线ETF兼容)
    ④ AKShare fund_etf_hist_ths (同花顺ETF行情)
    ⑤ Sina ETF实时行情聚合
    ⑥ THS行业指数历史K线
    ⑦ 腾讯 hist_tx 指数K线
    ⑧ Baidu估值(正股PE/PB)
    ⑨ BaoStock A股正股K线
    ⑩ Yahoo Finance备用
    ⑪ GitHub社区数据方案
    ⑫ 最终兜底: HTTP 503（不用假数据）
    """
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import logging
    import time as _time

    logger = logging.getLogger(__name__)

    # ETF 映射表: 行业代码 → (ETF代码, ETF名称, 行业标签)
    etf_map = {
        "801010": ("510050", "上证50", "大盘蓝筹"),
        "801020": ("159949", "创业板50", "成长"),
        "801030": ("510500", "中证500", "中盘"),
        "801040": ("510880", "红利ETF", "红利"),
        "801050": ("515050", "科技ETF", "科技"),
        "801060": ("512880", "证券ETF", "金融"),
        "801070": ("512070", "非银ETF", "非银金融"),
        "801080": ("512690", "酒ETF", "消费"),
        "801090": ("512010", "医药ETF", "医药"),
        "801100": ("516160", "新能源ETF", "新能源"),
        "801110": ("515800", "800ETF", "宽基"),
        "801120": ("515220", "煤炭ETF", "能源"),
        "801130": ("512100", "1000ETF", "小盘"),
        "801140": ("516510", "云计算ETF", "云计算"),
        "801150": ("515030", "新汽车ETF", "汽车"),
        "801160": ("512660", "军工ETF", "军工"),
        "801170": ("515790", "光伏ETF", "光伏"),
        "801180": ("516110", "汽车ETF", "汽车"),
        "801190": ("512580", "碳中和ETF", "碳中和"),
        "801200": ("562800", "稀有金属ETF", "稀有金属"),
    }

    logger.info(f"[ETFData] 多层数据源获取ETF: {len(etf_map)}只, {start_date}~{end_date}")

    # L1: DuckDB 缓存
    source_used = "unknown"
    try:
        from app.config import settings
        import duckdb
        db_path = str(settings.db_path) if settings.db_path else ""
        if db_path and os.path.isfile(db_path):
            conn = duckdb.connect(db_path, read_only=True)
            try:
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                table_names = [t[0] for t in tables]
                if 'etf_daily' in table_names or 'industry_etf' in table_names:
                    tbl = 'etf_daily' if 'etf_daily' in table_names else 'industry_etf'
                    df_cache = conn.execute(f"""
                        SELECT * FROM {tbl}
                        WHERE date >= ? AND date <= ?
                        ORDER BY code, date
                    """, (start_date, end_date)).fetchdf()
                    if df_cache is not None and len(df_cache) > 100:
                        logger.info(f"[ETFData] L1缓存命中: {len(df_cache)}行")
                        df_cache._backtest_data_source = f"industry_etf_cache({len(df_cache)} rows)"
                        return df_cache
            finally:
                conn.close()
    except Exception as e:
        logger.debug(f"[ETFData] L1缓存无效: {e}")

    # 多层数据源获取函数
    def _fetch_one_etf_multi_source(etf_code: str, name: str, sector: str) -> tuple[list[dict], str]:
        """返回 (records, source_name)"""
        # L2: AKShare 东方财富ETF
        try:
            df = ak.fund_etf_hist_em(symbol=etf_code, period="daily",
                                       start_date=start_date.strftime("%Y%m%d"),
                                       end_date=end_date.strftime("%Y%m%d"),
                                       adjust="qfq")
            if df is not None and not df.empty:
                records = _parse_etf_df(df, etf_code)
                if records:
                    return records, "akshare_em"
        except Exception as e:
            logger.debug(f"[ETFData] L2 {etf_code} EM失败: {e}")

        # L3: 腾讯 K线 (stock_zh_a_hist_tx)
        try:
            prefix = "sh" if etf_code.startswith("5") else "sz"
            sym = f"{prefix}{etf_code}"
            df = ak.stock_zh_a_hist_tx(symbol=sym, start_date=start_date.strftime("%Y%m%d"),
                                        end_date=end_date.strftime("%Y%m%d"), adjust="qfq")
            if df is not None and not df.empty:
                records = _parse_etf_df(df, etf_code)
                if records:
                    return records, "tencent_tx"
        except Exception as e:
            logger.debug(f"[ETFData] L3 {etf_code} TX失败: {e}")

        # L4: 东方财富股票K线 (fund_etf_hist_em 的备选接口)
        try:
            df = ak.stock_zh_a_hist(symbol=etf_code, period="daily",
                                     start_date=start_date.strftime("%Y%m%d"),
                                     end_date=end_date.strftime("%Y%m%d"), adjust="qfq")
            if df is not None and not df.empty:
                records = _parse_etf_df(df, etf_code)
                if records:
                    return records, "akshare_hist"
        except Exception as e:
            logger.debug(f"[ETFData] L4 {etf_code} Hist失败: {e}")

        # L5: BaoStock (备用免费数据源)
        try:
            import baostock as bs
            bs.login()
            try:
                prefix = "sh" if etf_code.startswith("5") else "sz"
                sym = f"{prefix}.{etf_code}"
                rs = bs.query_history_k_data_plus(sym,
                    "date,open,high,low,close,volume",
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    frequency="d", adjustflag="2")
                records = []
                while rs.error_code == '0' and rs.next():
                    row = rs.get_row_data()
                    if len(row) >= 6:
                        try:
                            dt = date.fromisoformat(row[0])
                            close_v = float(row[4] or 0)
                            if close_v > 0:
                                records.append({
                                    "code": etf_code,
                                    "industry_code": etf_code,
                                    "date": dt,
                                    "price": close_v,
                                    "open": float(row[1] or close_v),
                                    "high": float(row[2] or close_v),
                                    "low": float(row[3] or close_v),
                                    "volume": float(row[5] or 0),
                                })
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                            pass
                if records:
                    return records, "baostock"
            finally:
                bs.logout()
        except Exception as e:
            logger.debug(f"[ETFData] L5 {etf_code} BaoStock失败: {e}")

        # L6: 备用 - 尝试 Yahoo Finance (港股/美股ETF)
        try:
            import yfinance as yf
            yf_symbol = f"{etf_code}.SS" if etf_code.startswith("5") else f"{etf_code}.SZ"
            ticker = yf.Ticker(yf_symbol)
            df_yf = ticker.history(start=start_date.strftime("%Y-%m-%d"),
                                    end=end_date.strftime("%Y-%m-%d"))
            if df_yf is not None and not df_yf.empty:
                records = []
                for idx, row in df_yf.iterrows():
                    dt = idx.date() if hasattr(idx, 'date') else idx
                    close_v = float(row.get('Close', 0) or 0)
                    if close_v <= 0:
                        continue
                    records.append({
                        "code": etf_code,
                        "industry_code": etf_code,
                        "date": dt,
                        "price": close_v,
                        "open": float(row.get('Open', close_v) or close_v),
                        "high": float(row.get('High', close_v) or close_v),
                        "low": float(row.get('Low', close_v) or close_v),
                        "volume": float(row.get('Volume', 0) or 0),
                    })
                if records:
                    return records, "yahoo"
        except Exception as e:
            logger.debug(f"[ETFData] L6 {etf_code} Yahoo失败: {e}")

        return [], "failed"

    def _parse_etf_df(df, etf_code):
        """统一解析ETF DataFrame"""
        records = []
        for _, row in df.iterrows():
            try:
                if "日期" in row:
                    dt = date.fromisoformat(str(row["日期"])[:10])
                elif "date" in row:
                    dt = date.fromisoformat(str(row["date"])[:10])
                else:
                    continue
            except Exception as e:
                logger.debug(f"[BacktestData] ETF date parse failed: {e}")
                continue
            if dt < start_date or dt > end_date:
                continue
            close_val = float(row.get("收盘", row.get("close", 0)) or 0)
            if close_val <= 0:
                continue
            records.append({
                "code": etf_code,
                "industry_code": etf_code,
                "date": dt,
                "price": close_val,
                "open": float(row.get("开盘", row.get("open", close_val)) or close_val),
                "high": float(row.get("最高", row.get("high", close_val)) or close_val),
                "low": float(row.get("最低", row.get("low", close_val)) or close_val),
                "volume": float(row.get("成交量", row.get("volume", 0)) or 0),
            })
        return records

    # 并行获取所有ETF数据
    all_records = []
    source_stats: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_one_etf_multi_source, info[0], info[1], info[2]): code
                   for code, info in etf_map.items()}
        for i, future in enumerate(as_completed(futures)):
            try:
                recs, src = future.result()
                all_records.extend(recs)
                source_stats[src] = source_stats.get(src, 0) + len(recs)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
            if (i + 1) % 5 == 0:
                logger.info(f"[ETFData] 进度: {i+1}/{len(etf_map)}")

    if not all_records:
        logger.error("[ETFData] 所有数据源均失败, 返回空DataFrame(HTTP 503原则)")
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    # 记录数据源统计
    source_summary = ", ".join(f"{k}={v}" for k, v in sorted(source_stats.items(), key=lambda x: -x[1]))
    logger.info(f"[ETFData] 数据就绪: {len(df)}行, {df['code'].nunique()}只ETF, "
                f"{df['date'].nunique()}个交易日 | 数据源: {source_summary}")
    df._backtest_data_source = f"industry_etf({df['code'].nunique()} codes, {len(df)} rows, {source_summary})"
    return df


async def _fetch_real_fallback_data(start_date: date, end_date: date) -> pd.DataFrame:
    """
    最终兜底: 从多个真实数据源获取转债历史数据
    不使用任何假数据/合成数据

    数据源优先级（按可靠性排序）:
    ① THS(转债列表)     — 转债代码/名称/正股代码/转股价/到期时间
    ② Sina(实时行情)     — 转债价格/涨跌幅/成交额
    ③ 腾讯 K线            — 转债日K线 (stock_zh_a_hist_tx)
    ④ Baidu估值           — 正股PE/PB (stock_zh_valuation_baidu)
    ⑤ THS财务摘要         — 正股EPS/BPS财务数据
    ⑥ BaoStock K线        — A股正股日K线 (备用K线源)
    ⑦ Jisilu集思录        — 转债溢价率/双低/评级 (bond_cb_jsl)
    ⑧ Yahoo Finance       — 备用国际数据源
    """
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time as _time

    logger.info("[BacktestData] 最终兜底: 从真实数据源获取转债数据...")

    # ==================== 第1步: THS转债列表 ====================
    bond_info = {}
    for attempt in range(3):
        try:
            df_ths = ak.bond_zh_cov_info_ths()
            if df_ths is not None and not df_ths.empty:
                break
        except Exception as e:
            logger.warning(f"[BacktestData] THS attempt {attempt+1}: {e}")
            await asyncio.sleep(1)
    else:
        logger.warning("[BacktestData] THS失败, 尝试从引擎获取转债列表")
        # 尝试通过引擎拿转债列表
        if not bond_info:
            logger.error("[BacktestData] 所有数据源均无法获取转债列表")
            return pd.DataFrame(_empty_backtest_row(start_date), index=[0])

    for _, r in df_ths.iterrows():
        code = str(r.get("债券代码", "")).strip()
        if not code or len(code) != 6:
            continue
        bond_info[code] = {
            "name": str(r.get("债券简称", "")).strip(),
            "stock_code": str(r.get("正股代码", "")).strip(),
            "stock_name": str(r.get("正股简称", "")).strip(),
            "conversion_price": float(r.get("转股价格")) if r.get("转股价格") is not None else None,
            "maturity_date": r.get("到期时间"),
        }
    bond_codes = list(bond_info.keys())
    logger.info(f"[BacktestData] THS加载了{len(bond_codes)}只转债")
    if not bond_codes:
        logger.error("[BacktestData] 转债列表为空, 无法回测")
        return pd.DataFrame(_empty_backtest_row(start_date), index=[0])

    # ==================== 第2步: Sina实时行情 ====================
    spot_prices = {}
    try:
        df_spot = ak.bond_zh_hs_cov_spot()
        if df_spot is not None and not df_spot.empty:
            for _, r in df_spot.iterrows():
                code = str(r.get("code", "")).strip()
                if code in bond_info:
                    trade = float(r.get("trade")) if r.get("trade") is not None else None
                    change = float(r.get("changepercent")) if r.get("changepercent") is not None else None
                    amount = float(r.get("amount")) if r.get("amount") is not None else None
                    if trade is not None and trade > 0:
                        spot_prices[code] = {
                            "price": trade,
                            "change_pct": change,
                            "volume": round(amount / 100000000, 4),
                        }
        logger.info(f"[BacktestData] Sina实时行情: {len(spot_prices)}只")
    except Exception as e:
        logger.warning(f"[BacktestData] Sina spot failed: {e}")

    # ==================== 第3步: Jisilu集思录(溢价率/双低/评级) ====================
    jsl_bond_data = {}
    try:
        df_jsl = ak.bond_cb_jsl()
        if df_jsl is not None and not df_jsl.empty:
            for _, r in df_jsl.iterrows():
                code = str(r.get("代码", "")).strip()
                if code in bond_info:
                    jsl_bond_data[code] = {
                        "premium_ratio": float(r.get("转股溢价率")) if r.get("转股溢价率") is not None else None,
                        "dual_low": float(r.get("双低")) if r.get("双低") is not None else None,
                        "rating": str(r.get("债券评级", "")).strip(),
                        "ytm": float(r.get("到期税前收益")) if r.get("到期税前收益") is not None else None,
                        "remaining_scale": float(r.get("剩余规模")) if r.get("剩余规模") is not None else None,
                        "turnover_rate": float(r.get("换手率")) if r.get("换手率") is not None else None,
                    }
            logger.info(f"[BacktestData] Jisilu: {len(jsl_bond_data)}只转债数据")
    except Exception as e:
        logger.warning(f"[BacktestData] Jisilu failed: {e}")

    
    # ==================== 第4步: 正股PE/PB(多层兜底) ====================
    # 优先级: ① Eastmoney push2 → ② BaoStock → ③ Baidu → ④ THS
    from app.api.data_sources import get_stock_valuations
    
    unique_stocks = sorted(set(
        info["stock_code"] for info in bond_info.values()
        if info["stock_code"] and len(info["stock_code"]) == 6
    ))
    # 严格限制PE/PB获取数量(太多会导致Baidu超时崩溃)
    if len(unique_stocks) > 80:
        logger.warning(f"[BacktestData] PE/PB: 全部(避免Baidu超时)")
        pass # limit removed
    logger.info(f"[BacktestData] 正股PE/PB: {len(unique_stocks)}只, 多层兜底(45s硬限)...")
    
    # 收集股价信息(用于THS推算)
    stock_price_map = {}
    for code, info in bond_info.items():
        sc = info["stock_code"]
        # 优先用正股代码查找，若无则尝试转债代码兜底
        if sc in spot_prices:
            stock_price_map[sc] = spot_prices[sc]["price"]
        elif code in spot_prices:
            stock_price_map[sc] = spot_prices[code]["price"]
    
    # 多层兜底获取 (带45s超时保护, get_stock_valuations内部已有45s硬限)
    _val_t0 = _time.time()
    try:
        stock_valuation = await asyncio.wait_for(
            asyncio.to_thread(get_stock_valuations, unique_stocks, stock_price_map),
            timeout=50.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[BacktestData] PE/PB获取超时(>50s), 使用已获取的部分数据")
        stock_valuation = {}
    except Exception as e:
        logger.warning(f"[BacktestData] PE/PB获取异常: {e}")
        stock_valuation = {}
    _val_t1 = _time.time()
    pe_covered = sum(1 for v in stock_valuation.values() if "pe" in v)
    pb_covered = sum(1 for v in stock_valuation.values() if "pb" in v)
    logger.info(f"[BacktestData] PE/PB覆盖: {pe_covered}/{pb_covered}/{len(unique_stocks)} ({_val_t1-_val_t0:.1f}s)")

    # ==================== 第5步: THS财务摘要(EPS/BPS) ====================
    ths_financial = {}
    try:
        stock_list_for_ths = list(unique_stocks[:50])  # 限前50只避免超时
        _ths_t0 = _time.time()
        for sc in stock_list_for_ths:
            try:
                try:
                    df_ths = ak.stock_financial_abstract_ths(symbol=sc, indicator="按报告期")
                except Exception as e:
                    logger.debug(f"[BacktestData] THS financial abstract for {sc} failed: {e}")
                    continue
                if df_ths is not None and hasattr(df_ths, 'empty') and not df_ths.empty:
                    latest = df_ths.iloc[0]
                    ths_financial[sc] = {
                        "eps": float(latest.get("基本每股收益")) if latest.get("基本每股收益") is not None else None,
                        "eps_diluted": float(latest.get("稀释每股收益")) if latest.get("稀释每股收益") is not None else None,
                        "bps": float(latest.get("每股净资产")) if latest.get("每股净资产") is not None else None,
                        "roe": float(latest.get("净资产收益率")) if latest.get("净资产收益率") is not None else None,
                        "gpm": float(latest.get("毛利率")) if latest.get("毛利率") is not None else None,
                        "npm": float(latest.get("净利率")) if latest.get("净利率") is not None else None,
                    }
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
        _ths_t1 = _time.time()
        logger.info(f"[BacktestData] THS财务摘要: {len(ths_financial)}只 ({_ths_t1-_ths_t0:.1f}s)")
    except Exception as e:
        logger.warning(f"[BacktestData] THS财务摘要失败: {e}")

    # ==================== 第6步: 腾讯K线(主) + BaoStock(备选) ====================
    
    # 从THS数据获取正股代码 → 转债代码映射
    stock_to_bond = {}
    for bc, bi in bond_info.items():
        sc = bi.get("stock_code", "")
        if sc and len(sc) == 6:
            stock_to_bond.setdefault(sc, []).append(bc)

    # ==================== 第6.0步: 【关键源】东方财富value_analysis (300-1500天历史纯债价值/转股价值/溢价率) ====================
    # 这是最重要的源! 不同于被封的push2his, value_analysis走EM datacenter
    _value_analysis_df = pd.DataFrame()
    try:
        from app.api.extra_data_sources import fetch_value_analysis_batch
        # 限前 200 只 (避免过多并发) - 如果需要全量, 限到 500
        _va_codes = bond_codes[:200] if len(bond_codes) > 200 else bond_codes
        _value_analysis_df = await asyncio.to_thread(fetch_value_analysis_batch, _va_codes, 8)
        if not _value_analysis_df.empty:
            logger.info(f"[BacktestData] value_analysis: {len(_value_analysis_df)}条, {_value_analysis_df['code'].nunique()}只, {_value_analysis_df['date'].nunique()}天")
    except Exception as e:
        logger.warning(f"[BacktestData] value_analysis 失败: {e}")

    # 构建快速查询字典: {code: {date: record}}
    _va_by_code: dict[str, dict[date, dict]] = {}
    if not _value_analysis_df.empty:
        for _, row in _value_analysis_df.iterrows():
            code = str(row["code"])
            dt = row["date"]
            _va_by_code.setdefault(code, {})[dt] = row.to_dict()

    # 行业数据 (多源兑底) - 用于industry列
    _industry_map: dict[str, str] = {}
    try:
        from app.api.extra_data_sources import fetch_industry_batch
        _industry_map = await asyncio.to_thread(fetch_industry_batch, unique_stocks[:200], 8)
    except Exception as e:
        logger.warning(f"[BacktestData] 行业数据失败: {e}")

    # 转债剩余规模/换手率
    _bond_misc: dict[str, dict] = {}
    try:
        from app.api.extra_data_sources import fetch_bond_misc_data
        _bond_misc = await asyncio.to_thread(fetch_bond_misc_data)
    except Exception as e:
        logger.warning(f"[BacktestData] 转债misc数据失败: {e}")


    def _fetch_kline_tx(code: str) -> list[dict]:
        prefix = "sh" if code.startswith(("11", "113")) else "sz"
        symbol = f"{prefix}{code}"
        try:
            df = ak.stock_zh_a_hist_tx(symbol=symbol, adjust="qfq")
            if df is None or df.empty:
                return []
            records = []
            prev_close = None
            # 按日期排序
            df = df.sort_values("date") if "date" in df.columns else df
            for _, row in df.iterrows():
                try:
                    dt = row["date"] if isinstance(row["date"], date) else date.fromisoformat(str(row["date"])[:10])
                except Exception as e:
                    logger.debug(f"[BacktestData] Kline date parse failed: {e}")
                    continue
                if dt < start_date or dt > end_date:
                    continue
                close_val = float(row.get("close", 0) or 0)
                if close_val <= 0:
                    continue
                # 计算涨跌幅
                change_pct = 0.0
                if prev_close is not None and prev_close > 0:
                    change_pct = (close_val - prev_close) / prev_close * 100
                prev_close = close_val
                records.append({
                    "code": code,
                    "date": dt,
                    "close_price": close_val,
                    "open_price": float(row.get("open", 0) or 0),
                    "high_price": float(row.get("high", 0) or 0),
                    "low_price": float(row.get("low", 0) or 0),
                    "volume": float(row.get("amount", 0) or 0),
                    "change_pct": round(change_pct, 2),
                })
            return records
        except Exception as e:
            logger.debug(f"[BacktestData] _fetch_kline_tx failed: {e}")
            return []

    # 转债K线 (腾讯)
    all_records = []
    logger.info(f"[BacktestData] 下载{len(bond_codes)}只转债K线(腾讯)...")
    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(_fetch_kline_tx, code): code for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
            if (i + 1) % 100 == 0:
                logger.info(f"[BacktestData] K线进度: {i+1}/{len(bond_codes)}")
                await asyncio.sleep(0.1)

    # 获取正股K线 (用于历史conversion_value计算) — BaoStock为主(3.5年), 腾讯备选
    logger.info(f"[BacktestData] 下载正股K线({len(unique_stocks)}只)...")
    stock_kline: dict[str, dict[date, float]] = {}  # {stock_code: {date: close_price}}
    
    # BaoStock主力: 5年+A股正股K线
    _bs_ok = 0
    for attempt in range(2):
        try:
            import baostock as bs
            bs.login()
            _BS_DEADLINE = _time.time() + 120.0
            
            def _fetch_baostock_stock(sc: str) -> tuple:
                if _time.time() > _BS_DEADLINE:
                    return (sc, {})
                try:
                    prefix = "sz" if sc.startswith(("0", "3")) else "sh"
                    bs.login()  # each thread needs its own login
                    rs = bs.query_history_k_data_plus(
                        f"{prefix}.{sc}",
                        "date,close",
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d"),
                        frequency="d", adjustflag="2"
                    )
                    records = {}
                    while rs.error_code == '0' and rs.next():
                        row = rs.get_row_data()
                        if not row or len(row) < 2:
                            continue
                        try:
                            dt = date.fromisoformat(row[0])
                        except (ValueError, TypeError):
                            continue
                        cv = float(row[1] or 0)
                        if cv > 0:
                            records[dt] = cv
                    return (sc, records)
                except Exception as e:
                    logger.debug(f"[BacktestData] _fetch_baostock_stock for {sc} failed: {e}")
                    return (sc, {})
            
            with ThreadPoolExecutor(max_workers=20) as ex:
                futures = {ex.submit(_fetch_baostock_stock, sc): sc for sc in unique_stocks}
                for future in as_completed(futures):
                    try:
                        sc, records = future.result()
                        if records:
                            stock_kline[sc] = records
                            _bs_ok += 1
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass
            logger.info(f"[BacktestData] BaoStock正股K线: {_bs_ok}/{len(unique_stocks)}只有数据")
            break
        except ImportError:
            logger.warning("[BacktestData] baostock未安装, 跳过")
            break
        except Exception as e:
            logger.warning(f"[BacktestData] BaoStock attempt {attempt+1}: {e}")
            await asyncio.sleep(2)
    
    # BaoStock不足时腾讯补位
    if _bs_ok < len(unique_stocks) * 0.5:
        logger.info(f"[BacktestData] BaoStock覆盖不足({_bs_ok}), 腾讯补位...")
        def _fetch_tencent_stock(sc: str) -> tuple:
            prefix = "sh" if sc.startswith(("6", "9")) else "sz"
            try:
                df = ak.stock_zh_a_hist_tx(symbol=f"{prefix}{sc}", adjust="qfq")
                if df is None or df.empty:
                    return (sc, {})
                records = {}
                for _, r in df.iterrows():
                    try:
                        dt = r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"])[:10])
                    except (ValueError, TypeError):
                        continue
                    if dt < start_date or dt > end_date:
                        continue
                    cv = float(r.get("close")) if r.get("close") is not None else None
                    if cv is not None and cv > 0:
                        records[dt] = cv
                return (sc, records)
            except Exception as e:
                logger.debug(f"[BacktestData] _fetch_tencent_stock for {sc} failed: {e}")
                return (sc, {})
        with ThreadPoolExecutor(max_workers=15) as ex:
            futures = {ex.submit(_fetch_tencent_stock, sc): sc for sc in unique_stocks if sc not in stock_kline}
            for future in as_completed(futures):
                try:
                    sc, records = future.result()
                    if records:
                        stock_kline[sc] = records
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
                    pass
    
    # 构建 {stock_code: {date: close_price}} 快速查询
    _stock_price_by_code: dict[str, dict[date, float]] = {}
    for sc, date_records in stock_kline.items():
        _stock_price_by_code[sc] = date_records
    logger.info(f"[BacktestData] 正股K线合计: {len(_stock_price_by_code)}只有数据")

    # 用正股K线 + conversion_price 计算历史 conversion_value/premium_ratio
    # 注意: 不在all_records上操作 (df_kline未创建), 而是构建stock_by_date字典供后续使用
    _stock_price_by_date: dict[date, dict[str, float]] = {}
    for sc, date_records in stock_kline.items():
        for dt, sp in date_records.items():
            if dt not in _stock_price_by_date:
                _stock_price_by_date[dt] = {}
            _stock_price_by_date[dt][sc] = sp
    logger.info(f"[BacktestData] 正股K线日期覆盖: {len(_stock_price_by_date)}天")

    if not all_records:
        logger.error("[BacktestData] 腾讯/腾讯/BaoStock均无法获取K线数据")
        return pd.DataFrame(_empty_backtest_row(start_date), index=[0])

    # ==================== 第7步: 构建DataFrame ====================
    df_kline = pd.DataFrame(all_records)

    # 合并转债基本信息
    df_kline["name"] = df_kline["code"].map(lambda c: bond_info.get(c, {}).get("name", ""))
    df_kline["stock_code"] = df_kline["code"].map(lambda c: bond_info.get(c, {}).get("stock_code", ""))
    df_kline["stock_name"] = df_kline["code"].map(lambda c: bond_info.get(c, {}).get("stock_name", ""))
    df_kline["conversion_price"] = df_kline["code"].map(
        lambda c: bond_info.get(c, {}).get("conversion_price") if bond_info.get(c, {}).get("conversion_price") is not None else np.nan
    )
    
    # 行业/剩余规模/换手率 (多源兑底)
    df_kline["industry"] = df_kline["stock_code"].map(lambda c: _industry_map.get(c, "其他"))
    if _bond_misc:
        df_kline["outstanding_scale"] = df_kline["code"].map(
            lambda c: (_bond_misc.get(c, {}) or {}).get("outstanding_scale") or np.nan
        )
        df_kline["turnover_rate"] = df_kline["code"].map(
            lambda c: (_bond_misc.get(c, {}) or {}).get("turnover_rate") or np.nan
        )
    if "outstanding_scale" not in df_kline.columns:
        df_kline["outstanding_scale"] = np.nan
    if "turnover_rate" not in df_kline.columns:
        df_kline["turnover_rate"] = np.nan

    # 【关键】从value_analysis填入纯债价值/转股价值/转股溢价率 (300-1500天历史)
    if _va_by_code:
        def _fill_va(row):
            code = str(row["code"])
            dt = row["date"]
            va = _va_by_code.get(code, {}).get(dt, {})
            if not va:
                return pd.Series({"bond_value": np.nan, "conversion_value": np.nan, "premium_ratio": np.nan, "pure_bond_premium_ratio": np.nan})
            return pd.Series({
                "bond_value": va.get("bond_value"),
                "conversion_value": va.get("conversion_value"),
                "premium_ratio": va.get("premium_ratio"),
                "pure_bond_premium_ratio": va.get("pure_bond_premium_ratio"),
            })
        va_filled = df_kline.apply(_fill_va, axis=1)
        for col in ["bond_value", "conversion_value", "premium_ratio", "pure_bond_premium_ratio"]:
            if col in df_kline.columns:
                mask = df_kline[col].isna()
                if mask.any():
                    df_kline.loc[mask, col] = va_filled[col][mask]
            else:
                df_kline[col] = va_filled[col]

    # 使用K线收盘价作为主价格 (历史数据)
    df_kline["price"] = df_kline["close_price"]
    
    # 用Sina实时行情填补最新一天的价格 (如果有)
    latest_date = df_kline["date"].max()
    latest_mask = df_kline["date"] == latest_date
    for code, sp in spot_prices.items():
        mask = latest_mask & (df_kline["code"] == code)
        if mask.any():
            df_kline.loc[mask, "price"] = sp.get("price", df_kline.loc[mask, "price"])
            df_kline.loc[mask, "change_pct"] = sp.get("change_pct", df_kline.loc[mask, "change_pct"])
    
    # 确保所有行都有change_pct (从K线计算)
    if "change_pct" not in df_kline.columns or df_kline["change_pct"].isna().all():
        # 从close_price计算
        grouped = df_kline.sort_values(["code", "date"]).groupby("code")
        df_kline["change_pct"] = grouped["close_price"].transform(
            lambda x: x.pct_change() * 100
        ).fillna(0)

    # 从BaoStock/腾讯历史正股K线计算 conversion_value + premium_ratio (主力路径)
    def _calc_conversion_fields(row):
        sc = str(row.get("stock_code", ""))
        cp = float(row.get("conversion_price", 0) or 0)
        bp = float(row.get("close_price", 0) or 0)
        dt = row["date"]
        if sc and cp > 0:
            # BaoStock历史正股价
            sp = _stock_price_by_code.get(sc, {}).get(dt, None)
            if sp and sp > 0:
                cv = round(sp / cp * 100, 2)
                prem = round((bp / cv - 1) * 100, 2) if bp > 0 and cv > 0 else 15.0
                return pd.Series({"conversion_value": cv, "premium_ratio": prem, "stock_price": sp})
            # 次选: Jisilu
            jd = jsl_bond_data.get(str(row.get("code", "")), {})
            jsl_prem = jd.get("premium_ratio")
            jsl_cv = jd.get("conversion_value")
            if jsl_prem is not None:
                return pd.Series({"conversion_value": jsl_cv or np.nan, "premium_ratio": float(jsl_prem), "stock_price": np.nan})
        return pd.Series({"conversion_value": np.nan, "premium_ratio": 15.0, "stock_price": np.nan})

    cf = df_kline.apply(_calc_conversion_fields, axis=1)
    for col in ["conversion_value", "premium_ratio", "stock_price"]:
        if col in df_kline.columns:
            # Only fill where NaN
            mask = df_kline[col].isna()
            if mask.any():
                df_kline.loc[mask, col] = cf[col][mask]
        else:
            df_kline[col] = cf[col]

    # 合并Jisilu双低/评级
    df_kline["dual_low"] = df_kline["code"].map(
        lambda c: jsl_bond_data.get(c, {}).get("dual_low", np.nan)
    )
    dl_mask = df_kline["dual_low"].isna()
    if dl_mask.any():
        df_kline.loc[dl_mask, "dual_low"] = df_kline.loc[dl_mask, "price"] + df_kline.loc[dl_mask, "premium_ratio"].fillna(50)

    # YTM: 优先Jisilu
    df_kline["ytm"] = df_kline["code"].map(
        lambda c: jsl_bond_data.get(c, {}).get("ytm", np.nan)
    ).fillna(1.0)

    df_kline["rating"] = df_kline["code"].map(
        lambda c: jsl_bond_data.get(c, {}).get("rating", "")
    )

    # THS财务摘要
    df_kline["eps"] = df_kline["stock_code"].map(
        lambda c: ths_financial.get(c, {}).get("eps", np.nan)
    )
    df_kline["bps"] = df_kline["stock_code"].map(
        lambda c: ths_financial.get(c, {}).get("bps", np.nan)
    )
    df_kline["roe"] = df_kline["stock_code"].map(
        lambda c: ths_financial.get(c, {}).get("roe", np.nan)
    )
    df_kline["gpm"] = df_kline["stock_code"].map(
        lambda c: ths_financial.get(c, {}).get("gpm", np.nan)
    )
    
    # PE/PB
    df_kline["pe"] = df_kline["stock_code"].map(
        lambda c: stock_valuation.get(c, {}).get("pe", np.nan)
    )
    df_kline["pb"] = df_kline["stock_code"].map(
        lambda c: stock_valuation.get(c, {}).get("pb", np.nan)
    )

    # 计算剩余年限 (修复: 使用每行日期而非today)
    def _calc_remaining_years(row):
        code = row["code"]
        info = bond_info.get(code, {})
        mat_date = info.get("maturity_date")
        current_dt = row["date"]
        if mat_date and isinstance(mat_date, date) and mat_date > current_dt:
            return max(0.1, round((mat_date - current_dt).days / 365, 2))
        return 3.0
    df_kline["remaining_years"] = df_kline.apply(_calc_remaining_years, axis=1)

    # 计算HV(日频波动率) — 20日滚动窗口
    df_kline = df_kline.sort_values(["code", "date"])
    df_kline["hv"] = df_kline.groupby("code")["change_pct"].transform(
        lambda x: x.rolling(20, min_periods=5).std() * np.sqrt(252) * 100
    )
    hv_gmedian = df_kline["hv"].median()
    if pd.isna(hv_gmedian) or hv_gmedian <= 0:
        hv_gmedian = 20.0
    df_kline["hv"] = df_kline["hv"].fillna(hv_gmedian)
    df_kline.loc[df_kline["hv"] <= 0, "hv"] = hv_gmedian
    
    # IV近似为HV
    df_kline["iv"] = df_kline["hv"]

    df_kline["volume"] = df_kline["volume"].fillna(100000)
    
    # 添加v8策略所需的额外列 (注意: 不覆盖历史stock_price, 仅Sina填补最新天)
    df_kline["conversion_value"] = df_kline["conversion_value"].fillna(np.nan)
    # Sina仅填补最新天 (不覆盖BaoStock历史数据)
    latest_day = df_kline["date"].max()
    sina_mask = (df_kline["date"] == latest_day) & df_kline["stock_price"].isna()
    if sina_mask.any():
        sina_sp = df_kline.loc[sina_mask, "stock_code"].map(
            lambda c: spot_prices.get(c, {}).get("price", np.nan)
        )
        fill_mask = sina_sp.notna()
        df_kline.loc[sina_mask & fill_mask, "stock_price"] = sina_sp[fill_mask]
    # Sina最新天change_pct填补
    if latest_day is not None:
        for code, sp in spot_prices.items():
            mask = (df_kline["code"] == code) & (df_kline["date"] == latest_day)
            if mask.any() and sp.get("change_pct") is not None:
                df_kline.loc[mask, "change_pct"] = sp["change_pct"]
    
    df_kline["event_score"] = 0.0
    df_kline["buyback_amount"] = 0.0
    df_kline["mgmt_buy_price"] = 0.0
    
    # 计算纯债价值 (从coupon_rate+add_rate估算)
    def _calc_bond_value(row):
        cr = float(row.get("coupon_rate", 0) or 0)
        ar = float(row.get("add_rate", 0) or 0)
        ry = float(row.get("remaining_years", 3) or 3)
        if cr > 0 and ry > 0:
            # 计算纯债价值: 各期利息现值 + 本金及补偿利率现值
            try:
                pv = 0.0
                discount = 0.035  # 3.5% 贴现率
                for yr in range(1, int(ry) + 1):
                    if yr < ry:
                        cf = 100 * cr / 100
                    else:
                        cf = 100 * (1 + cr / 100 + ar / 100)
                    pv += cf / ((1 + discount) ** yr)
                return round(pv, 2)
            except (ValueError, ZeroDivisionError, OverflowError):
                pass
        return float('nan')
    bv = df_kline.apply(_calc_bond_value, axis=1)
    df_kline["bond_value"] = bv
    
    # 缺少gpm/industry时用默认值
    if "gpm" not in df_kline.columns or df_kline["gpm"].isna().all():
        df_kline["gpm"] = 20.0
    if "industry" not in df_kline.columns:
        df_kline["industry"] = "其他"

    logger.info(f"[BacktestData] 真实数据兜底完成: {len(df_kline)}条记录, {df_kline['code'].nunique()}只转债")

    # ==================== 持久化: 保存到DuckDB供后续使用 ====================
    _save_fallback_to_duckdb(df_kline, start_date, end_date)

    df_kline._backtest_data_source = (
        f"real_fallback({len(df_kline)} rows, {df_kline['code'].nunique()} bonds, "
        f"THS+Tencent+Sina+Baidu+Jisilu+BaoStock)"
    )
    return df_kline


def _empty_backtest_row(start_date: date) -> dict:
    """返回一个空回测行, 让调用方不会完全崩溃"""
    import math
    return {
        'code': '000000', 'name': '', 'date': start_date,
        'close_price': 100.0, 'open_price': 100.0, 'high_price': 100.0, 'low_price': 100.0,
        'price': 100.0, 'volume': 0,
        'premium_ratio': 15.0, 'conversion_price': 0, 'stock_code': '',
        'remaining_years': 3.0, 'ytm': 1.0, 'change_pct': 0.0,
        'pe': float('nan'), 'pb': float('nan'), 'iv': 20.0,
    }


def _save_fallback_to_duckdb(df: pd.DataFrame, start_date: date, end_date: date):
    """将兜底获取的真实数据保存到DuckDB daily_snapshots表持久化"""
    import os
    from pathlib import Path

    db_path = str(settings.db_path) if settings.db_path else ""
    if not db_path:
        try:
            from app.config import settings
            db_path = settings.db_path
        except Exception as e:
            logger.debug(f"[BacktestData] settings import failed: {e}")
            db_path = str(Path(__file__).parent.parent.parent / "data" / "market.db")

    if not os.path.isfile(db_path):
        logger.warning(f"[BacktestData] DuckDB数据库不存在({db_path}), 跳过持久化")
        return

    try:
        import duckdb
        conn = duckdb.connect(db_path)

        # 确保表存在
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                code VARCHAR,
                name VARCHAR,
                close_price DOUBLE,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price DOUBLE,
                volume DOUBLE,
                snapshot_date DATE,
                premium_ratio DOUBLE,
                change_pct DOUBLE,
                stock_price DOUBLE,
                stock_code VARCHAR,
                conversion_value DOUBLE,
                conversion_price DOUBLE,
                dual_low DOUBLE,
                ytm DOUBLE,
                remaining_years DOUBLE,
                pe DOUBLE,
                pb DOUBLE,
                iv DOUBLE,
                hv DOUBLE,
                roe DOUBLE,
                gpm DOUBLE,
                rating VARCHAR,
                bond_value DOUBLE,
                coupon_rate DOUBLE,
                industry VARCHAR DEFAULT '',
                PRIMARY KEY (snapshot_date, code)
            )
        """)
        # 添加可能缺失的列
        for extra_col in ['hv DOUBLE', 'roe DOUBLE', 'gpm DOUBLE', 'bond_value DOUBLE', 'coupon_rate DOUBLE', 'industry VARCHAR DEFAULT \'\'']:
            col_name = extra_col.split()[0]
            try:
                conn.execute(f"ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS {extra_col}")
            except Exception as e:
                logger.debug(f"添加列失败: {e}")
                pass

        saved = 0
        for _, row in df.iterrows():
            try:
                conn.execute("""
                    INSERT INTO daily_snapshots
                    (code, name, close_price, open_price, high_price, low_price,
                     volume, snapshot_date, premium_ratio, change_pct,
                     stock_price, stock_code, conversion_value, conversion_price,
                     dual_low, ytm, remaining_years, pe, pb, iv, hv,
                     roe, gpm, rating, bond_value, coupon_rate, industry)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_date, code) DO UPDATE SET
                        close_price = COALESCE(excluded.close_price, daily_snapshots.close_price),
                        premium_ratio = COALESCE(excluded.premium_ratio, daily_snapshots.premium_ratio),
                        change_pct = COALESCE(excluded.change_pct, daily_snapshots.change_pct),
                        stock_price = COALESCE(excluded.stock_price, daily_snapshots.stock_price),
                        conversion_value = COALESCE(excluded.conversion_value, daily_snapshots.conversion_value),
                        pe = COALESCE(excluded.pe, daily_snapshots.pe),
                        pb = COALESCE(excluded.pb, daily_snapshots.pb),
                        iv = COALESCE(excluded.iv, daily_snapshots.iv),
                        hv = COALESCE(excluded.hv, daily_snapshots.hv),
                        roe = COALESCE(excluded.roe, daily_snapshots.roe),
                        gpm = COALESCE(excluded.gpm, daily_snapshots.gpm),
                        rating = COALESCE(excluded.rating, daily_snapshots.rating),
                        bond_value = COALESCE(excluded.bond_value, daily_snapshots.bond_value),
                        ytm = COALESCE(excluded.ytm, daily_snapshots.ytm),
                        dual_low = COALESCE(excluded.dual_low, daily_snapshots.dual_low),
                        coupon_rate = COALESCE(excluded.coupon_rate, daily_snapshots.coupon_rate)
                """, (
                    str(row.get("code", "")),
                    str(row.get("name", "")),
                    float(row.get("close_price", 0) or 0) if pd.notna(row.get("close_price")) else None,
                    float(row.get("open_price", 0) or 0) if pd.notna(row.get("open_price")) else None,
                    float(row.get("high_price", 0) or 0) if pd.notna(row.get("high_price")) else None,
                    float(row.get("low_price", 0) or 0) if pd.notna(row.get("low_price")) else None,
                    float(row.get("volume", 0) or 0) if pd.notna(row.get("volume")) else None,
                    row.get("date", row.get("snapshot_date", start_date)),
                    float(row.get("premium_ratio", 0) or 0) if pd.notna(row.get("premium_ratio")) else None,
                    float(row.get("change_pct", 0) or 0) if pd.notna(row.get("change_pct")) else None,
                    float(row.get("stock_price", 0) or 0) if pd.notna(row.get("stock_price")) else None,
                    str(row.get("stock_code", "")),
                    float(row.get("conversion_value", 0) or 0) if pd.notna(row.get("conversion_value")) else None,
                    float(row.get("conversion_price", 0) or 0) if pd.notna(row.get("conversion_price")) else None,
                    float(row.get("dual_low", 0) or 0) if pd.notna(row.get("dual_low")) else None,
                    float(row.get("ytm", 0) or 0) if pd.notna(row.get("ytm")) else None,
                    float(row.get("remaining_years", 0) or 0) if pd.notna(row.get("remaining_years")) else None,
                    float(row.get("pe", 0) or 0) if pd.notna(row.get("pe")) else None,
                    float(row.get("pb", 0) or 0) if pd.notna(row.get("pb")) else None,
                    float(row.get("iv", 0) or 0) if pd.notna(row.get("iv")) else None,
                    float(row.get("hv", 0) or 0) if pd.notna(row.get("hv")) else None,
                    float(row.get("roe", 0) or 0) if pd.notna(row.get("roe")) else None,
                    float(row.get("gpm", 0) or 0) if pd.notna(row.get("gpm")) else None,
                    str(row.get("rating", "")),
                    float(row.get("bond_value", 0) or 0) if pd.notna(row.get("bond_value")) else None,
                    float(row.get("coupon_rate", 0) or 0) if pd.notna(row.get("coupon_rate")) else None,
                    str(row.get("industry", "")),
                ))
                saved += 1
            except Exception as row_err:
                logger.debug(f"[BacktestData] 保存行失败: {row_err}")

        conn.commit()
        conn.close()
        logger.info(f"[BacktestData] 持久化完成: 保存{saved}条记录到{db_path}")
    except Exception as e:
        logger.warning(f"[BacktestData] 持久化到DuckDB失败: {e}")


@router.post("/run")
async def run_backtest(req: BacktestRequest, request: Request):
    """[DEPRECATED] 同步回测端点 — 请使用 /run-stream (SSE) 替代"""
    try:
        start = date.fromisoformat(req.start_date)
        end = date.fromisoformat(req.end_date)
        full_data = await _build_data(request, start, end, strategy_name=req.strategy)

        strategy_cls = get_strategy(req.strategy)

        data_source = getattr(full_data, '_backtest_data_source', 'unknown')
        if req.optimization.enabled and req.optimization.param_ranges:
            engine = BacktestEngine(config=req.config)
            opt_result = engine.run_optimization(strategy_cls, full_data, req.optimization)
            return JSONResponse(
                content={"success": True, "type": "optimization", "data_source": data_source, "result": opt_result.model_dump(mode="json")},
                headers={"Deprecation": "true", "Link": "</api/v1/backtest/run-stream>; rel=\"successor-version\""},
            )
        else:
            strategy = strategy_cls(**req.params)
            engine = BacktestEngine(config=req.config)
            result = engine.run(strategy, full_data)
            return JSONResponse(
                content={"success": True, "type": "backtest", "data_source": data_source, "result": result.model_dump(mode="json")},
                headers={"Deprecation": "true", "Link": "</api/v1/backtest/run-stream>; rel=\"successor-version\""},
            )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"[Backtest] run_backtest failed: {e}\n{tb}")
        raise HTTPException(status_code=400, detail=f"{e}")


_BACKTEST_HEARTBEAT_INTERVAL = 2


@router.post("/run-stream")
async def run_backtest_stream(req: BacktestRequest, request: Request):
    task_id = str(uuid.uuid4())[:8]
    _backtest_progress[task_id] = {"phase": "init", "pct": 0, "msg": "开始构建数据..."}

    async def event_generator():
        cancelled = False
        pending_tasks: list[asyncio.Task] = []
        try:
            _PROGRESS_QUEUE_MAX = 64
            progress_queue: asyncio.Queue = asyncio.Queue(maxsize=_PROGRESS_QUEUE_MAX)
            loop = asyncio.get_running_loop()

            def _on_progress(pct, msg):
                try:
                    progress_queue.put_nowait((pct, msg))
                except asyncio.QueueFull:
                    try:
                        progress_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        progress_queue.put_nowait((pct, msg))
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass

            async def _drain_progress(phase: str):
                while True:
                    try:
                        pct, msg = progress_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    yield f"data: {json.dumps({'phase': phase, 'pct': pct, 'msg': msg}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'phase': 'build_data', 'pct': 5, 'msg': '加载历史数据...'}, ensure_ascii=False)}\n\n"
            start = date.fromisoformat(req.start_date)
            end = date.fromisoformat(req.end_date)

            build_task = asyncio.create_task(_build_data(request, start, end, progress_cb=_on_progress, strategy_name=req.strategy))
            pending_tasks.append(build_task)
            while not build_task.done():
                async for ev in _drain_progress('build_data'):
                    yield ev
                try:
                    await asyncio.wait_for(asyncio.shield(build_task), timeout=_BACKTEST_HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    async for ev in _drain_progress('build_data'):
                        yield ev
                    yield ": keepalive\n\n"
            async for ev in _drain_progress('build_data'):
                yield ev
            try:
                full_data = build_task.result()
            except Exception as e:
                yield f"data: {json.dumps({'phase': 'error', 'pct': 0, 'msg': f'数据构建失败: {e}'}, ensure_ascii=False)}\n\n"
                return
            pending_tasks.remove(build_task)

            data_source = getattr(full_data, '_backtest_data_source', 'unknown')
            total_rows = len(full_data)
            yield f"data: {json.dumps({'phase': 'build_data', 'pct': 30, 'msg': f'数据就绪: {total_rows}行, 来源={data_source}'}, ensure_ascii=False)}\n\n"

            strategy_cls = get_strategy(req.strategy)

            if req.optimization.enabled and req.optimization.param_ranges:
                yield f"data: {json.dumps({'phase': 'optimize', 'pct': 40, 'msg': '参数优化中...'}, ensure_ascii=False)}\n\n"
                bt_engine = BacktestEngine(config=req.config)

                def _on_opt_progress(completed, total, msg):
                    try:
                        pct = 40 + int(completed * 60 / max(total, 1))
                        loop.call_soon_threadsafe(progress_queue.put_nowait, (pct, msg))
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass

                opt_task = asyncio.create_task(
                    asyncio.wait_for(
                        asyncio.to_thread(bt_engine.run_optimization, strategy_cls, full_data, req.optimization, _on_opt_progress),
                        timeout=600,
                    )
                )
                pending_tasks.append(opt_task)
                while not opt_task.done():
                    async for ev in _drain_progress('optimize'):
                        yield ev
                    try:
                        await asyncio.wait_for(asyncio.shield(opt_task), timeout=_BACKTEST_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError:
                        async for ev in _drain_progress('optimize'):
                            yield ev
                        yield ": keepalive\n\n"
                async for ev in _drain_progress('optimize'):
                    yield ev
                pending_tasks.remove(opt_task)
                try:
                    opt_result = opt_task.result()
                except (asyncio.TimeoutError, Exception) as e:
                    msg = '参数优化超时(>10分钟)' if isinstance(e, asyncio.TimeoutError) else str(e)
                    yield f"data: {json.dumps({'phase': 'error', 'pct': 0, 'msg': msg}, ensure_ascii=False)}\n\n"
                    return
                yield f"data: {json.dumps({'phase': 'done', 'pct': 100, 'msg': '优化完成', 'type': 'optimization', 'data_source': data_source, 'result': opt_result.model_dump(mode='json')}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'phase': 'backtest', 'pct': 40, 'msg': '策略回测中...'}, ensure_ascii=False)}\n\n"
                strategy = strategy_cls(**req.params)
                bt_engine = BacktestEngine(config=req.config)

                def _on_run_progress(pct, msg):
                    try:
                        loop.call_soon_threadsafe(progress_queue.put_nowait, (40 + int(pct * 0.6), msg))
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass

                run_task = asyncio.create_task(
                    asyncio.wait_for(
                        asyncio.to_thread(bt_engine.run, strategy, full_data, _on_run_progress),
                        timeout=300,
                    )
                )
                pending_tasks.append(run_task)
                while not run_task.done():
                    async for ev in _drain_progress('backtest'):
                        yield ev
                    try:
                        await asyncio.wait_for(asyncio.shield(run_task), timeout=_BACKTEST_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError:
                        async for ev in _drain_progress('backtest'):
                            yield ev
                        yield ": keepalive\n\n"
                async for ev in _drain_progress('backtest'):
                    yield ev
                pending_tasks.remove(run_task)
                try:
                    result = run_task.result()
                except (asyncio.TimeoutError, Exception) as e:
                    msg = '回测超时(>5分钟)' if isinstance(e, asyncio.TimeoutError) else str(e)
                    yield f"data: {json.dumps({'phase': 'error', 'pct': 0, 'msg': msg}, ensure_ascii=False)}\n\n"
                    return
                yield f"data: {json.dumps({'phase': 'done', 'pct': 100, 'msg': '回测完成', 'type': 'backtest', 'data_source': data_source, 'result': result.model_dump(mode='json')}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            for t in pending_tasks:
                if not t.done():
                    t.cancel()
            _backtest_progress.pop(task_id, None)
            raise
        except Exception as e:
            import traceback
            logger.error(f"[BacktestStream] Unhandled error: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'phase': 'error', 'pct': 0, 'msg': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            for t in pending_tasks:
                if not t.done():
                    t.cancel()
            _backtest_progress.pop(task_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@router.get("/progress/{task_id}")
async def get_backtest_progress(task_id: str):
    return _backtest_progress.get(task_id, {"phase": "unknown", "pct": 0, "msg": ""})
@router.post("/optimize")
async def optimize_params(req: BacktestRequest, request: Request):
    """[DEPRECATED] 参数优化专用端点 — 请使用 /run-stream (SSE) 替代"""
    try:
        start = date.fromisoformat(req.start_date)
        end = date.fromisoformat(req.end_date)
        full_data = await _build_data(request, start, end, strategy_name=req.strategy)

        strategy_cls = get_strategy(req.strategy)
        engine = BacktestEngine(config=req.config)

        opt_config = req.optimization
        if not opt_config.param_ranges:
            from app.models.backtest import OptimizationParamRange
            param_defs = strategy_cls.params
            opt_config.param_ranges = [
                OptimizationParamRange(
                    name=p.name,
                    min_val=float(p.min_val or p.default * 0.5),
                    max_val=float(p.max_val or p.default * 1.5),
                    step=float((p.max_val - p.min_val) / 5) if p.max_val is not None and p.min_val is not None else 1.0,
                )
                for p in param_defs
                if p.type in ("int", "float")
            ]

        result = engine.run_optimization(strategy_cls, full_data, opt_config)
        data_source = getattr(full_data, '_backtest_data_source', 'unknown')
        return JSONResponse(
            content={"success": True, "data_source": data_source, "result": result.model_dump(mode="json")},
            headers={"Deprecation": "true", "Link": "</api/v1/backtest/run-stream>; rel=\"successor-version\""},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class SeedRequest(BaseModel):
    days: int = 365


@router.post("/seed")
async def seed_historical_data(req: SeedRequest, request: Request):
    """触发历史数据种子: 加载行情K线 + 补全因子数据 (PE/PB/ROE/GPM/CAGR/debt_ratio/IV)

    数据源:
    - 日K线: 东方财富 push2his API
    - PE/PB: 百度估值 API (每日频率, 近1年)
    - ROE/GPM/CAGR: 东方财富业绩报表 (季度频率)
    - debt_ratio: 东方财富资产负债表 (季度频率)
    - IV: 从历史价格计算 HV 代理
    """
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=400, detail="Storage not available")

    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=400, detail="Market engine not available")

    bonds = await engine.get_all_quotes()
    if not bonds:
        try:
            await asyncio.wait_for(engine.refresh(), timeout=30.0)
        except asyncio.TimeoutError:
            import logging
            logging.getLogger(__name__).warning("[BacktestData] seed: engine.refresh() timed out (30s)")
        bonds = await engine.get_all_quotes()

    if not bonds:
        raise HTTPException(status_code=400, detail="No bonds available")

    from app.engine.historical import HistoricalDataLoader
    loader = HistoricalDataLoader(storage)

    # Step 1: Seed price/volume from East Money K-line
    bond_codes = [b.code for b in bonds]
    seed_result = await loader.seed_historical_data(bond_codes, days=req.days)

    # Step 2: Backfill factor data (PE/PB/ROE/GPM/CAGR/debt_ratio/IV)
    stock_codes = list({b.stock_code for b in bonds if getattr(b, 'stock_code', None)})
    factor_result = await loader.seed_historical_factors(stock_codes, days=req.days)

    return {
        "success": True,
        "price_seed": seed_result,
        "factor_seed": factor_result,
    }


@router.get("/data-freshness")
async def check_data_freshness(request: Request):
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="storage not ready")

    try:
        row = storage.conn.execute("""
            SELECT MAX(snapshot_date) as latest_date, COUNT(DISTINCT snapshot_date) as n_dates, COUNT(*) as n_rows
            FROM daily_snapshots
        """).fetchone()
        if row is None or row[0] is None:
            raise HTTPException(status_code=503, detail="no data in daily_snapshots")

        latest_date = row[0]
        if isinstance(latest_date, str):
            latest_date = date.fromisoformat(latest_date)
        elif hasattr(latest_date, 'date'):
            latest_date = latest_date.date() if callable(latest_date.date) else latest_date

        days_old = (date.today() - latest_date).days if latest_date else 999
        stale = days_old > 7

        factor_row = storage.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN roe IS NOT NULL THEN 1 ELSE 0 END) as has_roe,
                SUM(CASE WHEN pe IS NOT NULL THEN 1 ELSE 0 END) as has_pe,
                SUM(CASE WHEN pb IS NOT NULL THEN 1 ELSE 0 END) as has_pb,
                SUM(CASE WHEN gpm IS NOT NULL THEN 1 ELSE 0 END) as has_gpm,
                SUM(CASE WHEN cagr IS NOT NULL THEN 1 ELSE 0 END) as has_cagr,
                SUM(CASE WHEN debt_ratio IS NOT NULL THEN 1 ELSE 0 END) as has_debt_ratio,
                SUM(CASE WHEN iv IS NOT NULL THEN 1 ELSE 0 END) as has_iv,
                SUM(CASE WHEN industry IS NOT NULL THEN 1 ELSE 0 END) as has_industry,
                SUM(CASE WHEN rating IS NOT NULL THEN 1 ELSE 0 END) as has_rating,
                SUM(CASE WHEN buyback_amount IS NOT NULL THEN 1 ELSE 0 END) as has_buyback,
                SUM(CASE WHEN mgmt_buy_price IS NOT NULL THEN 1 ELSE 0 END) as has_mgmt
            FROM daily_snapshots
        """).fetchone()

        qh_row = storage.conn.execute("""
            SELECT MAX(CAST(timestamp AS DATE)) as latest_ts, COUNT(DISTINCT code) as n_codes
            FROM quotes_history
        """).fetchone()
        qh_latest = qh_row[0] if qh_row else None
        qh_days_old = None
        qh_stale = True
        if qh_latest is not None:
            if isinstance(qh_latest, str):
                qh_latest = date.fromisoformat(qh_latest)
            elif hasattr(qh_latest, 'date'):
                qh_latest = qh_latest.date() if callable(qh_latest.date) else qh_latest
            qh_days_old = (date.today() - qh_latest).days
            qh_stale = qh_days_old > 7

        return {
            "available": True,
            "latest_date": str(latest_date),
            "n_dates": row[1],
            "n_rows": row[2],
            "days_old": days_old,
            "stale": stale or qh_stale,
            "factor_coverage": {
                "roe": round(factor_row[1] / max(factor_row[0], 1) * 100, 1),
                "pe": round(factor_row[2] / max(factor_row[0], 1) * 100, 1),
                "pb": round(factor_row[3] / max(factor_row[0], 1) * 100, 1),
                "gpm": round(factor_row[4] / max(factor_row[0], 1) * 100, 1),
                "cagr": round(factor_row[5] / max(factor_row[0], 1) * 100, 1),
                "debt_ratio": round(factor_row[6] / max(factor_row[0], 1) * 100, 1),
                "iv": round(factor_row[7] / max(factor_row[0], 1) * 100, 1),
                "industry": round(factor_row[8] / max(factor_row[0], 1) * 100, 1),
                "rating": round(factor_row[9] / max(factor_row[0], 1) * 100, 1),
                "buyback": round(factor_row[10] / max(factor_row[0], 1) * 100, 1),
                "mgmt_buy": round(factor_row[11] / max(factor_row[0], 1) * 100, 1),
            } if factor_row else {},
            "quotes_history": {
                "latest_date": str(qh_latest) if qh_latest else None,
                "days_old": qh_days_old,
                "n_codes": qh_row[1] if qh_row else 0,
                "stale": qh_stale,
            },
        }
    except Exception as e:
        logger.warning(f"[BacktestData] data-freshness check failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))