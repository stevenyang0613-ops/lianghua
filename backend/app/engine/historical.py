import asyncio
from datetime import date, timedelta, datetime
from typing import Optional
import logging
import requests
import pandas as pd
import numpy as np

from app.engine.storage import DataStorage

logger = logging.getLogger(__name__)


class HistoricalDataLoader:
    """历史数据加载器 - 从东方财富获取历史行情并缓存到DuckDB"""

    def __init__(self, storage: DataStorage):
        self.storage = storage

    async def load_bond_history(self, code: str, days: int = 365, max_retries: int = 3) -> list[dict]:
        """加载单只可转债历史行情 — 东方财富优先，腾讯K线兜底"""
        # Source 1: 东方财富
        records = await self._load_em_history(code, days, max_retries)
        if records:
            return records

        # Source 2: 腾讯K线 (akshare stock_zh_a_hist_tx)
        records = await self._load_tx_history(code, days)
        if records:
            return records

        return []

    async def _load_em_history(self, code: str, days: int = 365, max_retries: int = 2) -> list[dict]:
        """东方财富 K线数据 (通过代理网关, 带快速失败检测)"""
        # 快速失败检测: 首次调用时检查EM是否被封
        if not hasattr(self, '_em_checked'):
            self._em_banned = await self._fast_check_em_banned()
            self._em_checked = True

        if self._em_banned:
            logger.debug(f"[Historical] EM banned, skipping {code}, using TX")
            return []

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
                    timeout=45,
                )
                data = resp.json()
                klines = (data.get("data") or {}).get("klines") or []
                if not klines and not resp.ok:
                    self._em_banned = True
                    logger.warning(f"[Historical] EM appears banned (attempt {attempt}), falling back to TX")
                    return []
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
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    wait = attempt * 1.0
                    logger.debug(f"[Historical] EM retry {code} attempt {attempt+1}/{max_retries} after {wait}s: {e}")
                    await asyncio.sleep(wait)
        logger.debug(f"[Historical] EM failed for {code}: {last_err}")
        return []

    async def _fast_check_em_banned(self) -> bool:
        """快速检测东方财富IP是否被封禁: 采样3只活跃转债（优先从_bond_stock_codes取）"""
        try:
            from app.engine.data_enrich import _bond_stock_codes
            if _bond_stock_codes and len(_bond_stock_codes) >= 3:
                test_codes = list(_bond_stock_codes)[:3]
            else:
                test_codes = ["110079", "123172", "113050"]
        except ImportError:
            test_codes = ["110079", "123172", "113050"]
        failed = 0
        end = date.today()
        start = end - timedelta(days=5)
        for code in test_codes:
            market = "1" if code.startswith(("11", "13")) else "0"
            url = (
                f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
                f"secid={market}.{code}&fields1=f1,f2,f3,f4,f5"
                f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
                f"&klt=101&fqt=0"
                f"&beg={start.strftime('%Y%m%d')}"
                f"&end={end.strftime('%Y%m%d')}"
            )
            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(requests.get, url, timeout=8),
                    timeout=10,
                )
                if not resp.ok:
                    failed += 1
                else:
                    data = resp.json()
                    if not data.get("data") or not data["data"].get("klines"):
                        failed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                failed += 1
        is_banned = failed >= 2
        if is_banned:
            logger.warning(f"[Historical] East Money detected as IP-banned ({failed}/{len(test_codes)} failed), using TX fallback only")
        return is_banned

    async def _load_tx_history(self, code: str, days: int = 365) -> list[dict]:
        """腾讯K线数据 — 东方财富被封时的可靠兜底"""
        try:
            import akshare as ak
            prefix = "sh" if code.startswith(("11", "113")) else "sz"
            symbol = f"{prefix}{code}"
            df = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_zh_a_hist_tx, symbol=symbol, adjust="qfq"),
                timeout=60,
            )
            if df is None or df.empty:
                return []

            cutoff = date.today() - timedelta(days=days)
            records = []
            for _, row in df.iterrows():
                try:
                    dt = row["date"] if isinstance(row["date"], date) else date.fromisoformat(str(row["date"])[:10])
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
                if dt < cutoff:
                    continue
                close_val = float(row.get("close", 0) or 0)
                # 腾讯后复权数据可能有负值，过滤
                if close_val <= 0:
                    continue
                records.append({
                    "code": code,
                    "name": "",
                    "open_price": float(row.get("open", 0) or 0),
                    "close_price": close_val,
                    "high_price": float(row.get("high", 0) or 0),
                    "low_price": float(row.get("low", 0) or 0),
                    "volume": float(row.get("amount", 0) or 0),
                    "snapshot_date": dt,
                })
            if records:
                logger.info(f"[Historical] TX fallback loaded {len(records)} days for {code}")
            return records
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"[Historical] TX fallback failed for {code}: {e}")
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
        _SQL = """
            SELECT code, name, close_price as price, volume,
                   snapshot_date as date,
                   premium_ratio, change_pct, stock_price, conversion_value,
                   dual_low, ytm, remaining_years,
                   roe, gpm, cagr, debt_ratio, pe, pb, iv,
                   buyback_amount, mgmt_buy_price, industry, rating, outstanding_scale
            FROM daily_snapshots
            WHERE snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY code, snapshot_date
        """
        _EXPECTED_COLS = ['code', 'name', 'price', 'volume', 'date',
            'premium_ratio', 'change_pct', 'stock_price', 'conversion_value',
            'dual_low', 'ytm', 'remaining_years',
            'roe', 'gpm', 'cagr', 'debt_ratio', 'pe', 'pb', 'iv',
            'buyback_amount', 'mgmt_buy_price', 'industry', 'rating', 'outstanding_scale']
        _NCOLS = len(_EXPECTED_COLS)
        import time as _time
        for _attempt in range(3):
            cursor = self.storage.conn.execute(_SQL, (start_date, end_date))
            rows = cursor.fetchall()
            if not rows:
                return pd.DataFrame(columns=_EXPECTED_COLS)
            # DuckDB concurrent-write race guard: verify column count matches
            if rows and len(rows[0]) == _NCOLS:
                break
            if _attempt < 2:
                _time.sleep(0.2 * (_attempt + 1))
                continue
            # Last resort: return empty so caller falls through to other data sources
            import logging
            logging.getLogger(__name__).warning(
                f"[Historical] get_cached_history column mismatch: "
                f"expected {_NCOLS}, got {len(rows[0])} (attempt {_attempt+1}/3)"
            )
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=_EXPECTED_COLS)
        if codes:
            df = df[df["code"].isin(codes)]
        # Recalculate dual_low from price + premium_ratio (stored value may be stale)
        # 缺失值保持 NaN，不填充为 0
        if "price" in df.columns and "premium_ratio" in df.columns:
            df["dual_low"] = df["price"] + df["premium_ratio"]
        return df

    def get_available_dates(self) -> list[date]:
        rows = self.storage.conn.execute("""
            SELECT DISTINCT snapshot_date
            FROM daily_snapshots
            ORDER BY snapshot_date
        """).fetchall()
        return [row[0] for row in rows]

    async def seed_historical_data(self, codes: list[str], days: int = 365,
                                    factor_snapshot: Optional[dict[str, dict]] = None):
        """种子数据：为指定可转债加载历史数据并缓存

        factor_snapshot: 可选的 {code: {roe:..., gpm:..., ...}} 字典，用于补充历史因子数据。
        若提供则写入 daily_snapshots 的因子列，否则因子列为 NULL。
        """
        all_records = await self.load_all_bonds_history(codes, days)
        saved = 0
        batch = 0
        total_bonds = len(all_records)
        for code, records in all_records.items():
            factors = factor_snapshot.get(code, {}) if factor_snapshot else {}
            with self.storage._write() as conn:
                for rec in records:
                    conn.execute("""
                        INSERT INTO daily_snapshots
                        (code, name, open_price, high_price, low_price, close_price, volume, snapshot_date,
                         premium_ratio, change_pct, stock_price, conversion_value, dual_low,
                         ytm, remaining_years, roe, gpm, cagr, debt_ratio, pe, pb, iv,
                         buyback_amount, mgmt_buy_price, industry, rating, outstanding_scale, stock_code)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (snapshot_date, code) DO UPDATE SET
                            close_price = excluded.close_price,
                            high_price = GREATEST(high_price, excluded.high_price),
                            low_price = LEAST(low_price, excluded.low_price),
                            volume = excluded.volume,
                            stock_price = COALESCE(excluded.stock_price, daily_snapshots.stock_price),
                            conversion_value = COALESCE(excluded.conversion_value, daily_snapshots.conversion_value),
                            premium_ratio = COALESCE(excluded.premium_ratio, daily_snapshots.premium_ratio),
                            change_pct = COALESCE(excluded.change_pct, daily_snapshots.change_pct),
                            roe = COALESCE(excluded.roe, daily_snapshots.roe),
                            gpm = COALESCE(excluded.gpm, daily_snapshots.gpm),
                            cagr = COALESCE(excluded.cagr, daily_snapshots.cagr),
                            debt_ratio = COALESCE(excluded.debt_ratio, daily_snapshots.debt_ratio),
                            pe = COALESCE(excluded.pe, daily_snapshots.pe),
                            pb = COALESCE(excluded.pb, daily_snapshots.pb),
                            iv = COALESCE(excluded.iv, daily_snapshots.iv),
                            ytm = COALESCE(excluded.ytm, daily_snapshots.ytm),
                            remaining_years = COALESCE(excluded.remaining_years, daily_snapshots.remaining_years),
                            industry = COALESCE(excluded.industry, daily_snapshots.industry),
                            stock_code = COALESCE(excluded.stock_code, daily_snapshots.stock_code)
                    """, (
                        code, rec["name"],
                        rec["open_price"], rec["high_price"],
                        rec["low_price"], rec["close_price"],
                        rec["volume"], rec["snapshot_date"],
                        factors.get("premium_ratio"),
                        factors.get("change_pct"),
                        factors.get("stock_price"),
                        factors.get("conversion_value"),
                        factors.get("dual_low"),
                        factors.get("ytm"),
                        factors.get("remaining_years"),
                        factors.get("roe"),
                        factors.get("gpm"),
                        factors.get("cagr"),
                        factors.get("debt_ratio"),
                        factors.get("pe"),
                        factors.get("pb"),
                        factors.get("iv"),
                        factors.get("buyback_amount"),
                        factors.get("mgmt_buy_price"),
                        factors.get("industry"),
                        factors.get("rating"),
                        factors.get("outstanding_scale"),
                        factors.get("stock_code", ""),
                    ))
                    saved += 1
            batch += 1
            if batch % 50 == 0:
                self.storage.checkpoint()
                logger.info(f"[Historical] Seed progress: {batch}/{total_bonds} bonds, {saved} records saved")
        self.storage.checkpoint()
        logger.info(f"[Historical] Seeded {saved} records for {total_bonds} bonds")
        return {"bonds": total_bonds, "records": saved}

    async def seed_historical_factors(self, stock_codes: list[str], days: int = 365):
        """补全 daily_snapshots 中历史因子数据 (PE/PB/ROE/GPM/CAGR/debt_ratio)

        数据源:
        - PE/PB: Baidu 估值 API (每日值, 覆盖近1年)
        - ROE/GPM/CAGR: 东方财富业绩报表 (季度值, forward-fill 到每日)
        - debt_ratio: 东方财富资产负债表 (季度值, forward-fill)
        - IV: 从已有的 change_pct / close_price 计算 HV 作为 IV 代理
        """
        import akshare as ak
        from concurrent.futures import ThreadPoolExecutor

        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        updated = 0
        errors = 0

        # ---- 1. ROE/GPM/CAGR (季度频率, forward-fill) ----
        logger.info(f"[HistoricalFactors] Fetching financial reports for {len(stock_codes)} stocks...")
        quarters = self._get_recent_quarters(4)
        fin_data = {}
        for q in quarters:
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(ak.stock_yjbb_em, date=q),
                    timeout=30,
                )
                if df is None or df.empty:
                    continue
                for _, row in df.iterrows():
                    code = str(row.get("股票代码", "")).strip()
                    if not code or len(code) != 6:
                        continue
                    if code not in stock_codes:
                        continue
                    if code not in fin_data:
                        fin_data[code] = {"_quarter": q}
                    roe_val = row.get("净资产收益率", None)
                    gpm_val = row.get("销售毛利率", None)
                    eps_val = row.get("每股收益", None)
                    rev_growth = row.get("营业总收入-同比增长", None)
                    if roe_val is not None:
                        try:
                            fin_data[code]["roe"] = float(roe_val)
                        except (ValueError, TypeError):
                            pass
                    if gpm_val is not None:
                        try:
                            fin_data[code]["gpm"] = float(gpm_val)
                        except (ValueError, TypeError):
                            pass
                    if rev_growth is not None:
                        try:
                            fin_data[code]["cagr"] = float(rev_growth)
                        except (ValueError, TypeError):
                            pass
                logger.info(f"[HistoricalFactors] Loaded financial data for quarter {q}: {len(df)} stocks")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[HistoricalFactors] Financial report for {q} failed: {e}")

        # ---- 2. debt_ratio / current_ratio (季度频率) ----
        logger.info(f"[HistoricalFactors] Fetching balance sheet data...")
        for q in quarters:
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(ak.stock_zcfz_em, date=q),
                    timeout=30,
                )
                if df is None or df.empty:
                    continue
                debt_col = None
                for c in df.columns:
                    if "资产负债率" in str(c):
                        debt_col = c
                        break
                if debt_col is None:
                    continue
                for _, row in df.iterrows():
                    code = str(row.get("股票代码", "")).strip()
                    if not code or len(code) != 6 or code not in stock_codes:
                        continue
                    if code not in fin_data:
                        fin_data[code] = {"_quarter": q}
                    val = row.get(debt_col, None)
                    if val is not None:
                        try:
                            fin_data[code]["debt_ratio"] = float(val)
                        except (ValueError, TypeError):
                            pass
                logger.info(f"[HistoricalFactors] Loaded balance sheet for quarter {q}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[HistoricalFactors] Balance sheet for {q} failed: {e}")

        # ---- 3. PE/PB (每日频率 from Baidu, 仅 bond underlying stocks) ----
        logger.info(f"[HistoricalFactors] Fetching PE/PB from Baidu for {len(stock_codes)} stocks...")
        pe_pb_data = {}

        def _fetch_baidu_valuation(code: str, max_retries: int = 2) -> tuple[str, dict]:
            for attempt in range(max_retries + 1):
                try:
                    pe_df = ak.stock_zh_valuation_baidu(
                        symbol=code, indicator="市盈率(TTM)", period="近一年"
                    )
                    pb_df = ak.stock_zh_valuation_baidu(
                        symbol=code, indicator="市净率", period="近一年"
                    )
                    result = {}
                    if pe_df is not None and not pe_df.empty:
                        for _, r in pe_df.iterrows():
                            d = str(r.get("date", ""))[:10]
                            v = r.get("value", None)
                            if d and v is not None:
                                try:
                                    result.setdefault(d, {})["pe"] = float(v)
                                except (ValueError, TypeError):
                                    pass
                    if pb_df is not None and not pb_df.empty:
                        for _, r in pb_df.iterrows():
                            d = str(r.get("date", ""))[:10]
                            v = r.get("value", None)
                            if d and v is not None:
                                try:
                                    result.setdefault(d, {})["pb"] = float(v)
                                except (ValueError, TypeError):
                                    pass
                    return code, result
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if attempt < max_retries:
                        import time
                        time.sleep(1.0 * (attempt + 1))
                    else:
                        return code, {}

        sem = asyncio.Semaphore(5)

        async def _fetch_one(code: str):
            async with sem:
                result = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_baidu_valuation, code),
                    timeout=60,
                )
                return result

        tasks = [_fetch_one(code) for code in stock_codes[:250]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                errors += 1
                continue
            code, data = r
            if data:
                pe_pb_data[code] = data

        logger.info(f"[HistoricalFactors] Loaded PE/PB for {len(pe_pb_data)} stocks")

        # ---- 4. Write factor data to daily_snapshots ----
        logger.info(f"[HistoricalFactors] Writing factor data to daily_snapshots...")

        # Get existing dates in daily_snapshots
        available_dates = self.get_available_dates()
        if not available_dates:
            logger.warning("[HistoricalFactors] No daily_snapshots data found, skip factor seeding")
            return {"updated": 0, "errors": errors}

        date_range = [d for d in available_dates if start_date <= d <= end_date]
        if not date_range:
            logger.warning("[HistoricalFactors] No dates in range, skip factor seeding")
            return {"updated": 0, "errors": errors}

        # Build code->stock_code mapping from daily_snapshots + bond info
        code_stock_map = self._get_code_stock_map()

        fin_report_dates: dict[str, date] = {}
        for q in quarters:
            q_str = str(q)
            year = int(q_str[:4])
            month = int(q_str[4:6])
            if month == 3:
                report_date = date(year, 4, 30)
            elif month == 6:
                report_date = date(year, 8, 31)
            elif month == 9:
                report_date = date(year, 10, 31)
            elif month == 12:
                report_date = date(year + 1, 4, 30)
            else:
                continue
            fin_report_dates[q_str] = report_date

        with self.storage._write() as conn:
            for snap_date in date_range:
                snap_date_obj = snap_date if isinstance(snap_date, date) else date.fromisoformat(str(snap_date))
                date_str = snap_date_obj.isoformat()

                rows = conn.execute("""
                    SELECT code FROM daily_snapshots
                    WHERE snapshot_date = ? AND roe IS NULL
                """, (snap_date,)).fetchall()

                for (bond_code,) in rows:
                    stock_code = code_stock_map.get(bond_code)
                    if not stock_code:
                        continue

                    fin = fin_data.get(stock_code, {})
                    if fin and "_quarter" in fin:
                        q_key = fin["_quarter"]
                        report_dt = fin_report_dates.get(q_key)
                        if report_dt and snap_date_obj < report_dt:
                            fin = {}

                    baidu = pe_pb_data.get(stock_code, {}).get(date_str, {})

                    roe_val = fin.get("roe")
                    gpm_val = fin.get("gpm")
                    cagr_val = fin.get("cagr")
                    debt_val = fin.get("debt_ratio")
                    pe_val = baidu.get("pe")
                    pb_val = baidu.get("pb")

                    if any(v is not None for v in [roe_val, gpm_val, cagr_val, debt_val, pe_val, pb_val]):
                        try:
                            # Write to this specific date
                            conn.execute("""
                                UPDATE daily_snapshots SET
                                    roe = COALESCE(?, roe),
                                    gpm = COALESCE(?, gpm),
                                    cagr = COALESCE(?, cagr),
                                    debt_ratio = COALESCE(?, debt_ratio),
                                    pe = COALESCE(?, pe),
                                    pb = COALESCE(?, pb)
                                WHERE snapshot_date = ? AND code = ?
                            """, (
                                roe_val, gpm_val, cagr_val, debt_val, pe_val, pb_val,
                                snap_date, bond_code,
                            ))
                            updated += 1
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            errors += 1

        # ---- 5. Compute IV from change_pct (HV proxy) ----
        logger.info(f"[HistoricalFactors] Computing IV (HV proxy) from price data...")
        iv_updated = self._compute_iv_from_prices()
        updated += iv_updated

        self.storage.checkpoint()
        logger.info(
            f"[HistoricalFactors] Done: {updated} rows updated, {errors} errors, "
            f"{len(fin_data)} stocks with financial data, {len(pe_pb_data)} with PE/PB"
        )
        return {"updated": updated, "errors": errors, "stocks_with_fin": len(fin_data), "stocks_with_pepb": len(pe_pb_data)}

    def _get_recent_quarters(self, n: int = 4) -> list[str]:
        """生成最近 n 个已披露的财报季度代码。

        规则：财报披露有滞后 — Q1 (0430), Q2 (0831), Q3 (1031), Q4 (0430次年).
        当前日期若未过披露截止日,则该季度数据尚未发布,需回退一个季度.
        """
        today = date.today()
        # 确定当前已披露完的最近季度
        y, m = today.year, today.month
        # Q1 披露截止 4/30, Q2 截止 8/31, Q3 截止 10/31, Q4(年报) 截止次年 4/30
        # Q1 披露截止 4/30, Q2 截止 8/31, Q3 截止 10/31, Q4(年报) 截止次年 4/30
        if m >= 11:   # 11月起Q3已披露
            last_q_year, last_q = y, 3
        elif m >= 9:   # 9月起Q2已披露
            last_q_year, last_q = y, 2
        elif m >= 5:   # 5月起Q1已披露
            last_q_year, last_q = y, 1
        else:          # 1-4月, 上一年Q4(年报)
            last_q_year, last_q = y - 1, 4

        quarters = []
        q_year, q_num = last_q_year, last_q
        for _ in range(n * 2):
            if q_num == 1:
                quarters.append(f"{q_year}0331")
            elif q_num == 2:
                quarters.append(f"{q_year}0630")
            elif q_num == 3:
                quarters.append(f"{q_year}0930")
            elif q_num == 4:
                quarters.append(f"{q_year}1231")
            q_num -= 1
            if q_num <= 0:
                q_num = 4
                q_year -= 1
            if len(quarters) >= n:
                break
        return quarters[:n]

    def _get_code_stock_map(self) -> dict[str, str]:
        try:
            rows = self.storage.conn.execute("""
                SELECT code, MAX(stock_code) as stock_code
                FROM daily_snapshots
                WHERE stock_code IS NOT NULL AND stock_code != ''
                GROUP BY code
            """).fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception:
            return {}

    def _compute_iv_from_prices(self) -> int:
        try:
            rows = self.storage.conn.execute("""
                SELECT code, snapshot_date, close_price
                FROM daily_snapshots
                WHERE close_price > 0
                ORDER BY code, snapshot_date
            """).fetchall()

            if not rows:
                return 0

            from collections import defaultdict
            prices_by_code = defaultdict(list)
            for code, snap_date, price in rows:
                prices_by_code[code].append((snap_date, price))

            updated = 0
            with self.storage._write() as conn:
                for code, price_list in prices_by_code.items():
                    if len(price_list) < 5:
                        continue
                    prices = [p for _, p in price_list]
                    returns = [(prices[i] / prices[i-1] - 1) for i in range(1, len(prices)) if prices[i-1] > 0]
                    window = returns[-20:] if len(returns) >= 20 else returns  # use at most 20 most recent returns
                    if len(window) < 5:
                        continue
                    hv = float(np.std(window) * np.sqrt(252) * 100)
                    hv = max(5.0, min(80.0, hv))
                    for snap_date, _ in price_list:
                        try:
                            conn.execute("""
                                UPDATE daily_snapshots SET iv = ?
                                WHERE snapshot_date = ? AND code = ? AND iv IS NULL
                            """, (hv, snap_date, code))
                            updated += 1
                        except Exception:
                            pass
            return updated
        except Exception as e:
            logger.warning(f"[HistoricalFactors] IV computation failed: {e}")
            return 0