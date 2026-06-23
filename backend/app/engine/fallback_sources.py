"""
多数据源备选模块 — 当东方财富 API 被封时自动切换到其他数据源

数据源优先级（每个字段）：
  PE/PB:     Sina 实时行情 → THS 财务摘要(eps/bps) → yfinance
  ROE/GPM:   EM yjbb → THS 财务摘要 → yfinance
  Industry:  东方财富行业 → THS 行业板块(间接) → Sina API → yfinance
  K-line:    东方财富 push2his → 腾讯 K-line (akshare stock_zh_a_hist_tx)
  行情快照:   Sina stock_zh_a_spot
"""

import logging
import asyncio
import requests as _req
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from app.engine.data_enrich_utils import safe_float, safe_int

logger = logging.getLogger(__name__)

_POOL = ThreadPoolExecutor(max_workers=5)
atexit.register(_POOL.shutdown)

_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'}


# ── 工具函数 ──

async def _run_sync(fn, *args, **kwargs):
    """在线程池中运行同步函数"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_POOL, lambda: fn(*args, **kwargs))


def _pct_to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        s = str(v).replace('%', '').replace(',', '').strip()
        return float(s) / 100.0
    except (ValueError, TypeError):
        return None


# ── 1. PE/PB 数据 ──

async def fetch_pe_pb_batch_yfinance(stock_codes: list[str]) -> dict[str, dict]:
    """从 yfinance 批量获取 PE/PB (使用 yf.download) 速度快数十倍

    Returns: {stock_code: {'pe': float|None, 'pb': float|None}}
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}

    if not stock_codes:
        return {}

    results: dict[str, dict] = {}
    # 分批处理, 每批最多 50 只股票
    batch_size = 50
    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i:i + batch_size]
        try:
            tickers = [f'{c}.{"SS" if c.startswith(("6", "9")) else "SZ"}' for c in batch]
            # yf.Tickers for batch info
            multi = yf.Tickers(' '.join(tickers))
            for code in batch:
                suffix = '.SS' if code.startswith(('6', '9')) else '.SZ'
                try:
                    tkr = multi.tickers.get(f'{code}{suffix}')
                    if tkr is None:
                        continue
                    info = tkr.info if hasattr(tkr, 'info') else {}
                    if not info:
                        continue
                    entry = {}
                    pe = info.get('trailingPE') or info.get('forwardPE')
                    pb = info.get('priceToBook')
                    if pe and pe > 0:
                        entry['pe'] = round(float(pe), 2)
                    if pb and pb > 0:
                        entry['pb'] = round(float(pb), 2)
                    if entry:
                        results[code] = entry
                except Exception:
                    continue
        except Exception:
            continue
    return results


async def fetch_industry_batch_yfinance(stock_codes: list[str]) -> dict[str, str]:
    """从 yfinance 批量获取行业 (使用 yf.Tickers) 速度快数十倍

    Returns: {stock_code: industry_name}
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}

    if not stock_codes:
        return {}

    results: dict[str, str] = {}
    batch_size = 50
    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i:i + batch_size]
        try:
            tickers = [f'{c}.{"SS" if c.startswith(("6", "9")) else "SZ"}' for c in batch]
            multi = yf.Tickers(' '.join(tickers))
            for code in batch:
                suffix = '.SS' if code.startswith(('6', '9')) else '.SZ'
                try:
                    tkr = multi.tickers.get(f'{code}{suffix}')
                    if tkr is None:
                        continue
                    info = tkr.info if hasattr(tkr, 'info') else {}
                    industry = info.get('industry') or info.get('sector')
                    if industry:
                        results[code] = str(industry)
                except Exception:
                    continue
        except Exception:
            continue
    return results


async def fetch_industry_from_sina_sector() -> dict[str, str]:
    """从新浪行业板块列表获取所有A股的行业归属 (批量)

    Returns: {stock_code: industry_name}
    """
    import re
    results: dict[str, str] = {}
    try:
        # 新浪行业板块列表
        url = 'https://vip.stock.finance.sina.com.cn/q/go.php/vIndustryRank/kind/sshy/p/1/num/1000/sort/0/asc/0'
        resp = await _run_sync(
            lambda: _req.get(url, headers={**_HEADERS, 'Referer': 'https://finance.sina.com.cn'}, timeout=15)
        )
        html = resp.text
        # 解析行业表格: 每个行业有对应的股票列表页面
        # 提取行业链接
        industry_links = re.findall(r'/q/go\.php/vIndustryRank/kind/sshy/p/1/num/1000/sort/0/asc/0/([^"]+)', html)
        if not industry_links:
            return {}
        # 只取前 50 个行业 (避免太多请求)
        for ind_name in industry_links[:50]:
            try:
                ind_url = f'https://vip.stock.finance.sina.com.cn/q/go.php/vIndustryRank/kind/sshy/p/1/num/1000/sort/0/asc/0/{ind_name}'
                ind_resp = await _run_sync(
                    lambda: _req.get(ind_url, headers=_HEADERS, timeout=10)
                )
                ind_html = ind_resp.text
                # 提取行业名称
                ind_match = re.search(r'行业：([^<]+)', ind_html)
                industry = ind_match.group(1).strip() if ind_match else ind_name
                # 提取股票代码
                codes_in_ind = re.findall(r'>(60\d{4}|00\d{4}|30\d{4}|68\d{4})<', ind_html)
                for code in codes_in_ind:
                    if code not in results:
                        results[code] = industry
            except Exception:
                continue
    except Exception:
        pass
    return results


async def fetch_pe_pb_from_em_batch(stock_codes: list[str]) -> dict[str, dict]:
    """从东方财富批量获取 PE/PB (使用 ulist.np/get API)

    Returns: {stock_code: {'pe': float|None, 'pb': float|None}}
    """
    import re
    import json
    results: dict[str, dict] = {}
    if not stock_codes:
        return results

    # 分批处理, 每批最多 200 只
    for i in range(0, len(stock_codes), 200):
        batch = stock_codes[i:i + 200]
        codes_str = ','.join(f'1.{"600" if c.startswith("6") else "000"}.{c}' for c in batch)
        url = (f'https://push2.eastmoney.com/api/qt/ulist.np/get?'
               f'fltt=2&fields=f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23'
               f'&secids={codes_str}')
        try:
            resp = await _run_sync(
                lambda: _req.get(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com'}, timeout=10)
            )
            data = resp.json()
            if not data or 'data' not in data or 'diff' not in data['data']:
                continue
            for item in data['data']['diff']:
                code = str(item.get('f12', ''))
                if not code:
                    continue
                pe = item.get('f9')  # 动态市盈率
                pb = item.get('f23')  # 市净率
                entry = {}
                if pe is not None:
                    try:
                        p = float(pe)
                        if p > 0 and p < 10000:
                            entry['pe'] = round(p, 2)
                    except (ValueError, TypeError):
                        pass
                if pb is not None:
                    try:
                        p = float(pb)
                        if p > 0 and p < 1000:
                            entry['pb'] = round(p, 2)
                    except (ValueError, TypeError):
                        pass
                if entry:
                    results[code] = entry
        except Exception:
            continue
    return results


async def fetch_pe_pb(stock_codes: list[str]) -> dict[str, dict]:
    """获取 PE/PB 数据, 多源备选

    Returns: {stock_code: {'pe': float|None, 'pb': float|None}}
    """
    results: dict[str, dict] = {}

    # Source 1: EM batch API (speed > 200 stocks/request)
    try:
        em = await fetch_pe_pb_from_em_batch(stock_codes)
        if em:
            results.update(em)
            logger.info(f"[Fallback] EM batch PE/PB: {len(em)} stocks")
    except Exception as e:
        logger.debug(f"[Fallback] EM batch PE/PB failed: {e}")

    # Source 2: yfinance batch
    missing = [c for c in stock_codes if c not in results or results[c].get('pe') is None]
    if missing:
        try:
            yf_pe_pb = await fetch_pe_pb_batch_yfinance(missing)
            if yf_pe_pb:
                results.update(yf_pe_pb)
                logger.info(f"[Fallback] yfinance batch PE/PB: {len(yf_pe_pb)} stocks")
        except Exception as e:
            logger.debug(f"[Fallback] yfinance batch PE/PB failed: {e}")

    # Source 3: THS 财务摘要 (计算 PE = price / EPS, PB = price / BPS)
    missing = [c for c in stock_codes if c not in results or results[c].get('pe') is None]
    if missing:
        try:
            await _fetch_pe_pb_from_ths(missing, results)
            if results:
                logger.info(f"[Fallback] THS PE/PB: {len(results)} stocks")
        except Exception as e:
            logger.debug(f"[Fallback] THS PE/PB failed: {e}")

    # Source 4: yfinance single (final fallback)
    missing = [c for c in stock_codes if c not in results or results[c].get('pe') is None]
    if missing:
        try:
            await _fetch_pe_pb_from_yfinance(missing, results)
            filled = sum(1 for c in missing if results.get(c, {}).get('pe') is not None)
            if filled:
                logger.info(f"[Fallback] yfinance single PE/PB: {filled} stocks")
        except Exception as e:
            logger.debug(f"[Fallback] yfinance single PE/PB failed: {e}")

    return results


async def _fetch_pe_pb_from_ths(stock_codes: list[str], results: dict) -> None:
    """从 THS 财务摘要计算 PE/PB

    需要: EPS (基本每股收益) 和 BPS (每股净资产)
    PE = 最新价格 / EPS, PB = 最新价格 / BPS
    """
    import akshare as ak

    # 先获取所有股票的最新价格 (从新浪)
    prices = {}
    try:
        df_spot = await _run_sync(ak.stock_zh_a_spot)
        if not df_spot.empty:
            col_map = {'最新价': 'price', '收盘': 'price', '代码': 'code'}
            for _, row in df_spot.iterrows():
                code = str(row.get('代码', ''))
                price = safe_float(row.get('最新价', row.get('收盘', 0)))
                if code and price and price > 0:
                    prices[code] = price
    except Exception:
        pass

    if not prices:
        return

    for code in stock_codes:
        if code in results and results[code].get('pe') is not None:
            continue
        try:
            df = await _run_sync(ak.stock_financial_abstract_ths, symbol=code, indicator='按年度')
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            eps = safe_float(latest.get('基本每股收益', latest.get('每股收益')))
            bps = safe_float(latest.get('每股净资产'))
            if code not in results:
                results[code] = {}
            price = prices.get(code)
            if eps and eps > 0 and price and price > 0:
                results[code]['pe'] = round(price / eps, 2)
            if bps and bps > 0 and price and price > 0:
                results[code]['pb'] = round(price / bps, 2)
        except Exception:
            continue


async def _fetch_pe_pb_from_yfinance(stock_codes: list[str], results: dict) -> None:
    """从 yfinance 获取 PE/PB"""
    try:
        import yfinance as yf
    except ImportError:
        return

    for code in stock_codes:
        try:
            suffix = '.SS' if code.startswith(('6', '9')) else '.SZ'
            ticker = yf.Ticker(f'{code}{suffix}')
            info = await _run_sync(lambda: ticker.info)
            if code not in results:
                results[code] = {}
            pe = info.get('trailingPE') or info.get('forwardPE')
            pb = info.get('priceToBook')
            if pe and pe > 0:
                results[code]['pe'] = round(float(pe), 2)
            if pb and pb > 0:
                results[code]['pb'] = round(float(pb), 2)
        except Exception:
            continue


# ── 2. ROE / GPM / CAGR / debt_ratio ──

async def fetch_financial_ratios(stock_codes: list[str]) -> dict[str, dict]:
    """获取财务比率, 多源备选

    Returns: {stock_code: {'roe': float|None, 'gpm': float|None,
                           'cagr': float|None, 'debt_ratio': float|None}}
    """
    results: dict[str, dict] = {}

    # Source 1: EM yjbb (东方财富业绩报表)
    try:
        await _fetch_ratios_from_yjbb(stock_codes, results)
        if results:
            cov = sum(1 for c in stock_codes if c in results and results[c].get('roe') is not None)
            logger.info(f"[Fallback] EM yjbb ratios: {cov}/{len(stock_codes)} stocks")
    except Exception as e:
        logger.debug(f"[Fallback] EM yjbb failed: {e}")

    # Source 2: THS 财务摘要 (ROE/GPM/debt_ratio)
    missing = [c for c in stock_codes if c not in results or results[c].get('roe') is None]
    if missing:
        try:
            await _fetch_ratios_from_ths_abstract(missing, results)
            filled = sum(1 for c in missing if results.get(c, {}).get('roe') is not None)
            if filled:
                logger.info(f"[Fallback] THS abstract ratios: {filled} stocks")
        except Exception as e:
            logger.debug(f"[Fallback] THS abstract failed: {e}")

    return results


async def _fetch_ratios_from_yjbb(stock_codes: list[str], results: dict) -> None:
    """从东方财富业绩报表获取财务比率 (akshare stock_yjbb_em)"""
    import akshare as ak
    import math, time

    now = time.localtime()
    year = now.tm_year
    month = now.tm_mon
    fin_date = f"{year-1}1231" if month >= 10 else f"{year-2}1231"

    df = await _run_sync(ak.stock_yjbb_em, date=fin_date)
    if df is None or df.empty:
        raise ValueError("yjbb empty")

    col_code = '股票代码'
    col_roe = '净资产收益率'
    col_gpm = '销售毛利率'
    col_revenue = '营业总收入-营业总收入'
    col_industry = '所处行业'

    df_codes = df[col_code].astype(str).str.strip()
    df_filtered = df[df_codes.isin(stock_codes)]

    old_df = None
    try:
        cagr_date = f"{int(fin_date[:4])-3}{fin_date[4:]}"
        old_df = await _run_sync(ak.stock_yjbb_em, date=cagr_date)
    except Exception:
        pass

    old_rev = {}
    if old_df is not None and not old_df.empty:
        for _, r in old_df.iterrows():
            code = str(r.get(col_code, '')).strip()
            rev = safe_float(r.get(col_revenue))
            if code and rev and rev > 0:
                old_rev[code] = rev

    for _, r in df_filtered.iterrows():
        code = str(r.get(col_code, '')).strip()
        if not code:
            continue
        entry = results.get(code, {})
        roe = safe_float(r.get(col_roe))
        gpm = safe_float(r.get(col_gpm))
        if roe is not None:
            entry['roe'] = round(roe, 4)
        if gpm is not None:
            entry['gpm'] = round(gpm, 4)

        ind = str(r.get(col_industry, '')).strip()
        if ind and ind != 'nan':
            from app.engine.data_enrich import _set_global_map as _set_global_ind
            _set_global_ind("_industry_map", {code: ind})
            entry['industry'] = ind

        cur_rev = safe_float(r.get(col_revenue))
        if cur_rev and cur_rev > 0 and code in old_rev:
            try:
                cagr = (math.pow(cur_rev / old_rev[code], 1.0 / 3.0) - 1) * 100
                if -100 < cagr < 500:
                    entry['cagr'] = round(cagr, 2)
            except (ValueError, ZeroDivisionError):
                pass

        if entry:
            results[code] = entry


async def _fetch_ratios_from_ths_abstract(stock_codes: list[str], results: dict) -> None:
    """从 THS 财务摘要获取 ROE/GPM/debt_ratio (akshare stock_financial_abstract_ths)"""
    import akshare as ak

    for code in stock_codes:
        if code in results and results[code].get('roe') is not None:
            continue
        try:
            df = await _run_sync(ak.stock_financial_abstract_ths, symbol=code, indicator='按年度')
            if df is None or df.empty:
                continue
            latest = df.iloc[-1]
            if code not in results:
                results[code] = {}

            roe = _pct_to_float(latest.get('净资产收益率', latest.get('净资产收益率-摊薄')))
            gpm = _pct_to_float(latest.get('销售毛利率'))
            debt = _pct_to_float(latest.get('资产负债率'))
            if roe is not None:
                results[code]['roe'] = round(roe, 4)
            if gpm is not None:
                results[code]['gpm'] = round(gpm, 4)
            if debt is not None:
                results[code]['debt_ratio'] = round(debt, 4)
        except Exception:
            continue


# ── 3. 行业归属 ──

async def fetch_industry(stock_codes: list[str]) -> dict[str, str]:
    """获取股票所属行业, 多源备选

    Returns: {stock_code: industry_name}
    """
    results: dict[str, str] = {}

    # Source 1: yfinance batch (fastest, best batch support)
    try:
        yf_ind = await fetch_industry_batch_yfinance(stock_codes)
        if yf_ind:
            results.update(yf_ind)
            logger.info(f"[Fallback] yfinance batch industry: {len(yf_ind)} stocks")
    except Exception as e:
        logger.debug(f"[Fallback] yfinance batch industry failed: {e}")

    # Source 2: Sina sector list (batch, covers all A-shares)
    missing = [c for c in stock_codes if c not in results]
    if missing:
        try:
            sina_ind = await fetch_industry_from_sina_sector()
            if sina_ind:
                for c in missing:
                    if c in sina_ind:
                        results[c] = sina_ind[c]
                logger.info(f"[Fallback] Sina sector industry: {len(sina_ind)} stocks")
        except Exception as e:
            logger.debug(f"[Fallback] Sina sector industry failed: {e}")

    # Source 3: Sina F10 page (individual stock, slow but reliable)
    missing = [c for c in stock_codes if c not in results]
    if missing:
        try:
            await _fetch_industry_from_sina_api(missing, results)
            if results:
                filled = sum(1 for c in missing if results.get(c))
                if filled:
                    logger.info(f"[Fallback] Sina F10 industry: {filled} stocks")
        except Exception as e:
            logger.debug(f"[Fallback] Sina F10 industry failed: {e}")

    # Source 4: yfinance single (final fallback)
    missing = [c for c in stock_codes if c not in results]
    if missing:
        try:
            await _fetch_industry_from_yfinance(missing, results)
            filled = sum(1 for c in missing if results.get(c))
            if filled:
                logger.info(f"[Fallback] yfinance single industry: {filled} stocks")
        except Exception as e:
            logger.debug(f"[Fallback] yfinance single industry failed: {e}")

    return results


async def _fetch_industry_from_sina_api(stock_codes: list[str], results: dict) -> None:
    """通过新浪股票API逐股查询行业归属

    新浪个股页: https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/XXXXXX.phtml
    或者直接通过 Sina 的 JS 接口获取个股信息
    """
    import json

    for code in stock_codes:
        try:
            prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
            url = f'https://hq.sinajs.cn/list={prefix}{code}'
            resp = await _run_sync(
                lambda: _req.get(url, headers={**_HEADERS, 'Referer': 'https://finance.sina.com.cn'}, timeout=5)
            )
            text = resp.text.strip()
            if not text or '=' not in text:
                continue
            parts = text.split('"')
            if len(parts) < 2:
                continue
            fields = parts[1].split(',')
            # Sina 行情数据: 0-name, 1-open, 2-prev_close, 3-price, ... 12-industry (不定)
            # 有些版本中行业在第 13-14 字段
            # 更可靠的是通过新浪的 F10 页面获取
            # 改用 F10 页面
            f10_url = f'https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{code}.phtml'
            f10_resp = await _run_sync(
                lambda: _req.get(f10_url, headers=_HEADERS, timeout=10)
            )
            html = f10_resp.text
            # 查找行业: "所属行业" 后面跟着行业名称
            import re
            match = re.search(r'所属行业[：:]\s*([^<]+)', html)
            if match:
                ind = match.group(1).strip()
                if ind and ind != '--' and len(ind) < 50:
                    results[code] = ind
        except Exception:
            continue


async def _fetch_industry_from_yfinance(stock_codes: list[str], results: dict) -> None:
    """从 yfinance 获取行业"""
    try:
        import yfinance as yf
    except ImportError:
        return

    for code in stock_codes:
        try:
            suffix = '.SS' if code.startswith(('6', '9')) else '.SZ'
            ticker = yf.Ticker(f'{code}{suffix}')
            info = await _run_sync(lambda: ticker.info)
            industry = info.get('industry') or info.get('sector')
            if industry:
                results[code] = str(industry)
        except Exception:
            continue


async def _fetch_industry_from_tx_api(stock_codes: list[str], results: dict) -> None:
    """通过腾讯股票API获取行业信息"""
    for code in stock_codes:
        try:
            prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
            url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,2020-01-01,2025-12-31,1,qfq'
            # 腾讯的行业信息在个股基础信息里
            info_url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day'
            resp = await _run_sync(
                lambda: _req.get(info_url, headers=_HEADERS, timeout=5)
            )
            # 腾讯的基础信息字段不直接包含行业,跳过
        except Exception:
            continue


# ── 4. 历史K线 (补充 Tencent 接口) ──

async def fetch_kline_from_tx(code: str, days: int = 365) -> list[dict]:
    """从腾讯 K-line 获取历史数据"""
    import akshare as ak
    try:
        prefix = 'sh' if code.startswith(('11', '113')) else 'sz'
        symbol = f'{prefix}{code}'
        df = await _run_sync(ak.stock_zh_a_hist_tx, symbol=symbol, adjust='qfq')
        if df is None or df.empty:
            return []
        records = []
        for _, row in df.iterrows():
            close = safe_float(row.get('close'))
            if close is None or close <= 0:
                continue
            records.append({
                'code': code,
                'close_price': close,
                'volume': safe_float(row.get('amount')) if safe_float(row.get('amount')) is not None else 0,
                'snapshot_date': str(row.get('date', ''))[:10],
            })
        return records
    except Exception:
        return []


# ── 5. 可转债主列表 (THS 备选) ──

async def fetch_bond_list_from_ths() -> list[dict]:
    """从 THS 获取可转债主列表"""
    import akshare as ak
    try:
        df = await _run_sync(ak.bond_zh_cov_info_ths)
        if df is None or df.empty:
            return []
        bonds = []
        for _, row in df.iterrows():
            bonds.append({
                'code': str(row.get('转债代码', row.get('code', ''))).strip(),
                'name': str(row.get('转债名称', row.get('name', ''))).strip(),
                'stock_code': str(row.get('正股代码', row.get('stock_code', ''))).strip(),
                'stock_name': str(row.get('正股名称', row.get('stock_name', ''))).strip(),
            })
        return bonds
    except Exception:
        return []


async def fetch_bond_list_from_em() -> list[dict]:
    """从东方财富获取可转债主列表 (akshare)"""
    import akshare as ak
    try:
        df = await _run_sync(ak.bond_zh_cov_info_em)
        if df is None or df.empty:
            return []
        bonds = []
        for _, row in df.iterrows():
            bonds.append({
                'code': str(row.get('转债代码', row.get('code', ''))).strip(),
                'name': str(row.get('转债名称', row.get('name', ''))).strip(),
                'stock_code': str(row.get('正股代码', row.get('stock_code', ''))).strip(),
                'stock_name': str(row.get('正股名称', row.get('stock_name', ''))).strip(),
            })
        return bonds
    except Exception:
        return []


async def fetch_bond_list_any() -> list[dict]:
    """获取可转债主列表, 多源备选"""
    bonds = await fetch_bond_list_from_em()
    if bonds:
        return bonds
    bonds = await fetch_bond_list_from_ths()
    return bonds


# ── 6. Sina 行情快照注入 (为 spot_map 补充 PE/PB/change_pct) ──

async def fetch_sina_spot_snapshot() -> dict[str, dict]:
    """从 Sina 获取实时行情快照，返回 {code: {price, change_pct, ...}}

    Sina stock_zh_a_spot 包含所有 A 股的实时行情（涨跌幅、价格、成交量等）。
    """
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_zh_a_spot)
        if df is None or df.empty:
            return {}
        result = {}
        for _, r in df.iterrows():
            raw_code = str(r.get('代码', '')).strip()
            if not raw_code or raw_code.startswith('bj'):
                continue
            s_code = raw_code[2:] if (raw_code.startswith('sz') or raw_code.startswith('sh')) else raw_code
            result[s_code] = {
                'change_pct': safe_float(r.get('涨跌幅')),
                'price': safe_float(r.get('最新价')),
                'volume': safe_float(r.get('成交额')),
            }
        return result
    except Exception:
        return {}

# ── 7. 通达信 (TDX) 备选数据源 ──

async def fetch_pe_pb_from_tdx(stock_codes: list[str]) -> dict[str, dict]:
    """从 TDX 批量获取 PE/PB 数据"""
    if not stock_codes:
        return {}
    try:
        from app.adapters.tdx_adapter import get_tdx_adapter
        adapter = get_tdx_adapter()
        result = await _run_sync(adapter.fetch_finance_batch, stock_codes)
        cleaned = {}
        for code, info in result.items():
            entry = {}
            pe = info.get("pe")
            pb = info.get("pb")
            if pe is not None and pe > 0:
                entry["pe"] = pe
            if pb is not None and pb > 0:
                entry["pb"] = pb
            if entry:
                cleaned[code] = entry
        return cleaned
    except Exception:
        return {}


async def fetch_financial_from_tdx(stock_codes: list[str]) -> dict[str, dict]:
    """从 TDX 批量获取财务数据（ROE/EPS/BPS）"""
    if not stock_codes:
        return {}
    try:
        from app.adapters.tdx_adapter import get_tdx_adapter
        adapter = get_tdx_adapter()
        result = await _run_sync(adapter.fetch_finance_batch, stock_codes)
        cleaned = {}
        for code, info in result.items():
            entry = {}
            for key in ("pe", "pb", "roe", "eps", "bps"):
                val = info.get(key)
                if val is not None:
                    entry[key] = val
            if entry:
                cleaned[code] = entry
        return cleaned
    except Exception:
        return {}


async def fetch_quotes_from_tdx(codes: list[str]) -> dict[str, dict]:
    """从 TDX 批量获取实时行情"""
    if not codes:
        return {}
    try:
        from app.adapters.tdx_adapter import get_tdx_adapter
        adapter = get_tdx_adapter()
        return await _run_sync(adapter.fetch_quotes, codes)
    except Exception:
        return {}


async def fetch_kline_from_tdx(code: str, days: int = 120) -> list[dict]:
    """从 TDX 获取 K-line 数据"""
    try:
        from app.adapters.tdx_adapter import get_tdx_adapter
        adapter = get_tdx_adapter()
        return await _run_sync(adapter.fetch_kline, code, days)
    except Exception:
        return []


async def fetch_kline_batch_from_tdx(codes: list[str], days: int = 120) -> dict[str, list[dict]]:
    """从 TDX 批量获取 K-line 数据"""
    if not codes:
        return {}
    try:
        from app.adapters.tdx_adapter import get_tdx_adapter
        adapter = get_tdx_adapter()
        return await _run_sync(adapter.fetch_kline_batch, codes, days)
    except Exception:
        return {}


async def fetch_bond_list_from_tdx() -> list[dict]:
    """从 TDX 获取可转债列表（通过名称搜索 '转债'）"""
    try:
        from app.adapters.tdx_adapter import get_tdx_adapter
        adapter = get_tdx_adapter()
        result = await _run_sync(adapter.fetch_securities_by_name, "转债")
        bonds = []
        for s in result:
            code = s.get("code", "")
            name = s.get("name", "")
            if code and name and len(code) == 6 and code.isdigit():
                bonds.append({
                    "code": code,
                    "name": name,
                    "market": s.get("market"),
                })
        return bonds
    except Exception:
        return []
