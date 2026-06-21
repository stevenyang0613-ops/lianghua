"""
补全数据源 — 璇玑v8策略回测所需的额外数据

核心问题: bond_value/纯债溢价率/转股价值 在历史回测中长期为 0%
解决方案: 通过 akshare.bond_zh_cov_value_analysis 从东方财富数据中心获取每只转债的
         300-1500 天的纯债价值、转股价值、纯债溢价率、转股溢价率、收盘价
"""

import asyncio
import logging
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# 关键源 1: akshare.bond_zh_cov_value_analysis (东方财富数据中心)
# 字段: 日期/收盘价/纯债价值/转股价值/纯债溢价率/转股溢价率
# 范围: 每只转债 300-1500 天的完整历史 (不依赖IP)
# ============================================================
def _fetch_value_analysis_single(code: str) -> list[dict]:
    """
    获取单只转债的纯债价值/转股价值/溢价率历史数据

    数据源: 东方财富数据中心 (https://datacenter-web.eastmoney.com)
    接口: ak.bond_zh_cov_value_analysis(symbol=code)
    """
    import akshare as ak
    try:
        df = ak.bond_zh_cov_value_analysis(symbol=code)
        if df is None or df.empty:
            return []
        records = []
        for _, r in df.iterrows():
            try:
                dt_str = str(r.get("日期", ""))[:10]
                if not dt_str or dt_str == "nan":
                    continue
                dt = date.fromisoformat(dt_str)
            except (ValueError, TypeError):
                continue
            rec = {
                "code": code,
                "date": dt,
                "bond_value": _safe_float(r.get("纯债价值")),
                "conversion_value": _safe_float(r.get("转股价值")),
                "pure_bond_premium_ratio": _safe_float(r.get("纯债溢价率")),
                "premium_ratio": _safe_float(r.get("转股溢价率")),
                "close_price": _safe_float(r.get("收盘价")),
            }
            records.append(rec)
        return records
    except Exception as e:
        logger.debug(f"[ValueAnalysis] {code}: {e}")
        return []


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def fetch_value_analysis_batch(bond_codes: list[str], max_workers: int = 10) -> pd.DataFrame:
    """
    批量获取多只转债的纯债价值/转股价值历史数据

    Args:
        bond_codes: 转债代码列表
        max_workers: 并发线程数

    Returns:
        DataFrame(columns=['code', 'date', 'bond_value', 'conversion_value',
                          'pure_bond_premium_ratio', 'premium_ratio', 'close_price'])
    """
    if not bond_codes:
        return pd.DataFrame()
    logger.info(f"[ValueAnalysis] 并行下载{len(bond_codes)}只转债价值分析 (max_workers={max_workers})...")
    t0 = _time.time()
    all_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_value_analysis_single, code): code
                   for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                logger.debug(f"[ValueAnalysis] {code}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(bond_codes)} ({len(all_records)}条)")
                _time.sleep(0.1)

    if not all_records:
        logger.warning("[ValueAnalysis] 无数据")
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    elapsed = _time.time() - t0
    logger.info(f"[ValueAnalysis] 完成: {len(df)}条, {df['code'].nunique()}只, {df['date'].nunique()}天 ({elapsed:.0f}s)")
    return df


# ============================================================
# 关键源 2: 转债日K线 (东方财富数据中心 web API)
# 这个接口提供 3.5+ 年的转债K线 (日频), 通过 EM datacenter 而非 push2his
# ============================================================
def _fetch_bond_daily_em(code: str, start_date: date, end_date: date) -> list[dict]:
    """
    通过东方财富数据中心接口获取转债日K线 (不依赖被封的 push2his)

    接口: https://datacenter-web.eastmoney.com/api/data/v1/get
    """
    import requests as _req
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        # 转债代码需带前缀 (sh/sz)
        if code.startswith(("11", "13")):
            market = "sh"
        else:
            market = "sz"
        sort_type = "(SECURITY_CODE=\"" + market + code + "\")"
        params = {
            "sty": "ALL",
            "token": "894050c76af8597a853f5b408b759f5d",
            "st": "TRADE_DATE",
            "sr": "1",
            "source": "WEB",
            "type": "RPTA_WEB_KZZ_MRHQ",
            "filter": sort_type,
            "p": "1",
            "ps": "5000",
            "varName": "RT_WEB_KZZ_MRHQ",
        }
        resp = _req.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        result = data.get("result", {})
        if not result or not result.get("data"):
            return []
        records = []
        for row in result["data"]:
            try:
                dt = date.fromisoformat(str(row.get("TRADE_DATE", ""))[:10])
            except (ValueError, TypeError):
                continue
            if dt < start_date or dt > end_date:
                continue
            records.append({
                "code": code,
                "date": dt,
                "close_price": _safe_float(row.get("CLOSE_PRICE")) or 0,
                "open_price": _safe_float(row.get("OPEN_PRICE")) or 0,
                "high_price": _safe_float(row.get("HIGH_PRICE")) or 0,
                "low_price": _safe_float(row.get("LOW_PRICE")) or 0,
                "volume": _safe_float(row.get("VOL")) or 0,
                "amount": _safe_float(row.get("AMOUNT")) or 0,
            })
        return records
    except Exception as e:
        logger.debug(f"[BondDailyEM] {code}: {e}")
        return []


def fetch_bond_daily_em_batch(bond_codes: list[str], start_date: date, end_date: date,
                              max_workers: int = 15) -> pd.DataFrame:
    """
    批量获取转债日K线 (东方财富数据中心, 不依赖被封的 push2his)

    与 Tencent K线对比:
    - 优点: 提供 3.5+ 年历史数据 (vs 腾讯仅 90 天)
    - 缺点: 速度稍慢, IP可能限速
    """
    if not bond_codes:
        return pd.DataFrame()
    logger.info(f"[BondDailyEM] 并行下载{len(bond_codes)}只转债K线 ({start_date}~{end_date})...")
    t0 = _time.time()
    all_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_bond_daily_em, code, start_date, end_date): code
                   for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                logger.debug(f"[BondDailyEM] {futures[future]}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(bond_codes)} ({len(all_records)}条)")
                _time.sleep(0.2)

    if not all_records:
        return pd.DataFrame()
    df = pd.DataFrame(all_records)
    elapsed = _time.time() - t0
    logger.info(f"[BondDailyEM] 完成: {len(df)}条, {df['code'].nunique()}只, {df['date'].nunique()}天 ({elapsed:.0f}s)")
    return df


# ============================================================
# 关键源 3: 行业数据 (多源兜底)
# 优先级: 东方财富个股信息 → THS行业 → 新浪行业 → yfinance
# ============================================================
def _fetch_industry_em_single(stock_code: str) -> Optional[str]:
    """
    东方财富F10接口 (含行业) - 实际可用接口
    
    返回 sszjhhy (申万行业) / sshy (所属市场行业) 字段
    """
    import requests as _req
    try:
        if stock_code.startswith(("6", "9")):
            market = "SH"
        elif stock_code.startswith(("0", "3")):
            market = "SZ"
        elif stock_code.startswith(("4", "8")):
            market = "BJ"
        else:
            market = "SH"
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={market}{stock_code}"
        resp = _req.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        data = resp.json()
        jbzl = data.get("jbzl", {})
        industry = jbzl.get("sszjhhy") or jbzl.get("sshy")
        if industry and industry != "--" and len(industry) < 30:
            return industry
        return None
    except Exception as e:
        logger.debug(f"[IndustryEM] {stock_code}: {e}")
        return None


def _fetch_industry_ths_single(stock_code: str) -> Optional[str]:
    """从 THS 个股信息获取行业"""
    import akshare as ak
    try:
        df = ak.stock_individual_info_ths(symbol=stock_code)
        if df is None or df.empty:
            return None
        for _, r in df.iterrows():
            key = str(r.get("item", ""))
            if key in ("行业", "所属行业", "行业分类", "industry"):
                val = str(r.get("value", "")).strip()
                if val and val != "--":
                    return val
        return None
    except Exception:
        return None


def _fetch_industry_sina_single(stock_code: str) -> Optional[str]:
    """从新浪 F10 获取行业"""
    import requests as _req
    try:
        prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
        url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{stock_code}.phtml"
        resp = _req.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn"
        })
        if resp.status_code != 200:
            return None
        # 解析: 所属行业
        import re
        match = re.search(r'所属行业[：:]\s*<[^>]*>([^<]+)', resp.text)
        if match:
            industry = match.group(1).strip()
            if industry and len(industry) < 30:
                return industry
        # 备用: 找 sw_level1
        match2 = re.search(r'(中信一级|申万一级|申万二级|申万行业)[：:]\s*<[^>]*>([^<]+)', resp.text)
        if match2:
            return match2.group(2).strip()
        return None
    except Exception:
        return None


def _fetch_industry_yfinance_single(stock_code: str) -> Optional[str]:
    """从 yfinance 获取行业"""
    try:
        import yfinance as yf
        suffix = ".SS" if stock_code.startswith(("6", "9")) else ".SZ"
        ticker = yf.Ticker(f"{stock_code}{suffix}")
        info = ticker.info
        return info.get("industry") or info.get("sector")
    except Exception:
        return None


def _fetch_industry_single(code: str) -> Optional[str]:
    """多源兜底获取单个股票行业 - EM F10 > THS > Sina > yfinance"""
    for fetcher in [_fetch_industry_em_single, _fetch_industry_ths_single, _fetch_industry_sina_single, _fetch_industry_yfinance_single]:
        try:
            ind = fetcher(code)
            if ind:
                return ind
        except Exception:
            continue
    return None


def fetch_industry_batch(stock_codes: list[str], max_workers: int = 8) -> dict[str, str]:
    """
    批量获取多只正股的行业归属 (多源兜底)

    Returns: {stock_code: industry_name}
    """
    if not stock_codes:
        return {}
    logger.info(f"[Industry] 多源兜底获取{len(stock_codes)}只正股行业 (max_workers={max_workers})...")
    t0 = _time.time()
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_industry_single, code): code
                   for code in stock_codes}
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                ind = future.result()
                if ind:
                    results[code] = ind
            except Exception as e:
                logger.debug(f"[Industry] {code}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(stock_codes)} ({len(results)}只有行业)")
                _time.sleep(0.2)

    elapsed = _time.time() - t0
    logger.info(f"[Industry] 完成: {len(results)}/{len(stock_codes)}只有行业 ({elapsed:.0f}s)")
    return results


# ============================================================
# 关键源 4: 转债剩余规模 + 换手率 (THS bond_zh_hs_cov_spot 实时)
# ============================================================
def fetch_bond_misc_data() -> dict:
    """
    从转债实时行情获取剩余规模/换手率/流通规模/上市日期

    包含字段: 转债代码/转债名称/最新价/涨跌幅/剩余规模/换手率/成交额
    """
    import akshare as ak
    logger.info("[BondMisc] 下载转债实时misc数据(剩余规模/换手率)...")
    result = {}
    for attempt in range(2):
        try:
            df = ak.bond_zh_hs_cov_spot()
            if df is not None and not df.empty:
                for _, r in df.iterrows():
                    code = str(r.get("code", "")).strip()
                    if not code or len(code) != 6:
                        continue
                    out_scale = _safe_float(r.get("剩余规模", 0))
                    turnover = _safe_float(r.get("换手率", 0))
                    volume = _safe_float(r.get("成交量", 0))
                    amount = _safe_float(r.get("成交额", 0))
                    result[code] = {
                        "outstanding_scale": out_scale,
                        "turnover_rate": turnover,
                        "volume": volume,
                        "amount": amount,
                    }
                logger.info(f"[BondMisc] 完成: {len(result)}只")
                return result
        except Exception as e:
            logger.warning(f"[BondMisc] attempt{attempt+1}: {e}")
            _time.sleep(1)
    return result


# ============================================================
# 关键源 5: 中证转债指数 (CSI Convertible Bond Index) - 基准
# 字段: 收盘价/涨跌幅, 用于策略对比基准
# ============================================================
def fetch_csi_index(start_date: date, end_date: date) -> pd.DataFrame:
    """
    中证转债指数 (000832.CSI) 历史数据 - 基准对比

    Returns: DataFrame(date, close, change_pct)
    """
    import akshare as ak
    logger.info(f"[CSI Index] 下载中证转债指数 {start_date}~{end_date}...")
    try:
        df = ak.stock_zh_index_daily(symbol="sh000832")
        if df is None or df.empty:
            return pd.DataFrame()
        df['date'] = pd.to_datetime(df['date']).dt.date
        mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        df = df[mask].copy()
        df['change_pct'] = df['close'].pct_change() * 100
        df = df.rename(columns={'close': 'csi_index_close'})
        logger.info(f"[CSI Index] 完成: {len(df)}天")
        return df[['date', 'csi_index_close', 'change_pct']]
    except Exception as e:
        logger.warning(f"[CSI Index] 失败: {e}")
        return pd.DataFrame()


# ============================================================
# 关键源 6: 转债发行人/正股财务摘要 (THS)
# 用于补全 ROE/GPM 等基本面因子
# ============================================================
def fetch_stock_financial_ths_batch(stock_codes: list[str], max_workers: int = 8) -> dict[str, dict]:
    """
    批量获取正股财务摘要 (ROE/GPM/EPS/BPS/CAGR/资产负债率)

    Returns: {stock_code: {roe, gpm, eps, bps, cagr, debt_ratio, revenue}}
    """
    import akshare as ak
    logger.info(f"[THS Financial] 批量获取{len(stock_codes)}只正股财务摘要 (max_workers={max_workers})...")
    result: dict[str, dict] = {}

    def _fetch_one(code: str) -> tuple:
        try:
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
            if df is None or df.empty:
                return code, {}
            row = df.iloc[0]
            entry = {}
            for k_src, k_dst in [
                ("基本每股收益", "eps"),
                ("每股净资产", "bps"),
                ("净资产收益率", "roe"),
                ("毛利率", "gpm"),
                ("净利率", "npm"),
                ("营业收入", "revenue"),
                ("资产负债率", "debt_ratio"),
                ("销售毛利率", "gpm"),
                ("每股经营现金流", "ocfps"),
            ]:
                v = row.get(k_src, None)
                if v is not None and str(v) not in ("False", "None", ""):
                    try:
                        f = float(v)
                        if not (np.isnan(f) or np.isinf(f)):
                            entry[k_dst] = f
                    except (ValueError, TypeError):
                        pass
            return code, entry
        except Exception as e:
            return code, {}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_one, code): code for code in stock_codes}
        for i, future in enumerate(as_completed(futures)):
            code, entry = future.result()
            if entry:
                result[code] = entry
            if (i + 1) % 30 == 0:
                logger.info(f"  进度: {i+1}/{len(stock_codes)} ({len(result)}只有数据)")
                _time.sleep(0.3)

    logger.info(f"[THS Financial] 完成: {len(result)}/{len(stock_codes)}只")
    return result


# ============================================================
# 关键源 7: East Money datacenter 历史K线 (push2his 被封时的备选)
# 接口: kzz.kline 获取 3.5+ 年日K线
# ============================================================
def _fetch_bond_kline_em_dc(code: str, start_date: date, end_date: date) -> list[dict]:
    """
    从东方财富数据中心获取转债日K线 (备选push2his)

    接口: https://datacenter-web.eastmoney.com/api/data/v1/get
    """
    import requests as _req
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        # 转债代码需带前缀
        if code.startswith(("11", "13")):
            market = "1"  # 上海
        else:
            market = "0"  # 深圳
        secid = f"{market}.{code}"
        params = {
            "sty": "ALL",
            "token": "894050c76af8597a853f5b408b759f5d",
            "st": "TRADE_DATE",
            "sr": "1",
            "source": "WEB",
            "type": "RPTA_WEB_KZZ_MRHQ",
            "filter": f'(SECURITY_CODE=\"{secid}\")',
            "p": "1",
            "ps": "5000",
        }
        resp = _req.get(url, params=params, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return []
        data = resp.json()
        result = data.get("result", {})
        if not result or not result.get("data"):
            return []
        records = []
        for row in result["data"]:
            try:
                dt = date.fromisoformat(str(row.get("TRADE_DATE", ""))[:10])
            except (ValueError, TypeError):
                continue
            if dt < start_date or dt > end_date:
                continue
            records.append({
                "code": code,
                "date": dt,
                "close_price": _safe_float(row.get("CLOSE_PRICE")) or 0,
                "open_price": _safe_float(row.get("OPEN_PRICE")) or 0,
                "high_price": _safe_float(row.get("HIGH_PRICE")) or 0,
                "low_price": _safe_float(row.get("LOW_PRICE")) or 0,
                "volume": _safe_float(row.get("VOL")) or 0,
                "amount": _safe_float(row.get("AMOUNT")) or 0,
            })
        return records
    except Exception as e:
        logger.debug(f"[BondKlineEM-DC] {code}: {e}")
        return []


def fetch_bond_kline_em_dc_batch(bond_codes: list[str], start_date: date, end_date: date,
                                  max_workers: int = 12) -> pd.DataFrame:
    """
    批量从东方财富数据中心获取转债日K线 (3.5+ 年历史)
    """
    if not bond_codes:
        return pd.DataFrame()
    logger.info(f"[BondKlineEM-DC] 下载{len(bond_codes)}只转债K线 (max_workers={max_workers})...")
    t0 = _time.time()
    all_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_bond_kline_em_dc, code, start_date, end_date): code
                   for code in bond_codes}
        for i, future in enumerate(as_completed(futures)):
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                logger.debug(f"[BondKlineEM-DC] {futures[future]}: {e}")
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(bond_codes)} ({len(all_records)}条)")
                _time.sleep(0.2)
    if not all_records:
        return pd.DataFrame()
    df = pd.DataFrame(all_records)
    elapsed = _time.time() - t0
    logger.info(f"[BondKlineEM-DC] 完成: {len(df)}条, {df['code'].nunique()}只 ({elapsed:.0f}s)")
    return df
