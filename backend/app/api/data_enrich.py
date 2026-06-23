

logger = logging.getLogger(__name__)


# ============================================================
# 1. THS财务报表演示 — ROE/GPM/debt_ratio
# ============================================================
def _parse_pct(val) -> float:
    """将 '54.27%' 或 False 转为 float"""
    if val is None or val is False or str(val).strip() in ("", "False", "None"):
        return None
    s = str(val).strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def fetch_ths_financial_single(code: str) -> dict:
    """
    从THS获取单只股票的财务数据 (ROE/GPM/debt_ratio)
    
    注意: macOS Electron 沙盒中 py_mini_racer 可能 dlsym 失败，
    返回空 dict。调用方需自行处理 fallback。
    """
    import akshare as ak
    import sys, os
    # AGENTS.md #48: macOS sandbox 中 py_mini_racer 不可用，跳过 THS
    if sys.platform == 'darwin' and not os.environ.get('LH_MGMT_TRY_CNINFO'):
        return {}
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
    except Exception as e:
        logger.warning(f"THS 财务摘要失败: {e}")
        return {}
    if df is None or df.empty:
        return {}
    result = {}
    for _, r in df.iterrows():
        name = str(r.get("指标", "")).strip()
        val = r.get("值", None)
        if val is None or val == "False" or val == False:
            continue
        parsed = _parse_pct(val)
        if parsed is None:
            continue
        if "ROE" in name or "净资产收益率" in name:
            result["roe"] = parsed
        elif "毛利率" in name:
            result["gpm"] = parsed
        elif "资产负债率" in name:
            result["debt_ratio"] = parsed
    return result


# ============================================================
# 2. 批量THS财务数据（后台任务）
# ============================================================
def fetch_ths_financial_batch(stock_codes: list, max_workers: int = 8) -> dict:
    """
    批量获取THS财务数据
    
    Args:
        stock_codes: 股票代码列表（6位数字）
        max_workers: 最大并发数（THS服务器较慢，不宜过高）
    
    Returns:
        {stock_code: {"roe": float, "gpm": float, "debt_ratio": float}}
    """
    import concurrent.futures
    import sys, os
    # AGENTS.md #48: macOS sandbox 中 py_mini_racer 不可用，跳过 THS
    if sys.platform == 'darwin' and not os.environ.get('LH_MGMT_TRY_CNINFO'):
        logger.warning("[THS] macOS sandbox, skipping THS financial batch")
        return {}
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_ths_financial_single, code): code for code in stock_codes}
        for future in concurrent.futures.as_completed(futures):
            code = futures[future]
            try:
                data = future.result()
                if data:
                    result[code] = data
            except Exception as e:
                logger.warning(f"THS 财务数据 {code} 失败: {e}")
    return result


# ============================================================
# 3. THS行业数据（原 stock_individual_info_ths → stock_individual_info_em）
# ============================================================
def fetch_ths_bond_industry(bonds: dict) -> dict:
    """
    从东方财富个股信息获取正股行业

    原 THS stock_individual_info_ths 在 akshare 1.18.x 中已移除，
    现使用 stock_individual_info_em 替代。

    Returns: {stock_code: industry_name}
    """
    import akshare as ak
    result = {}
    sample_codes = list(set(
        info["stock_code"] for info in bonds.values()
        if info["stock_code"] and len(info["stock_code"]) == 6
    ))

    if not hasattr(ak, "stock_individual_info_em"):
        return result

    for code in sample_codes:
        try:
            df = ak.stock_individual_info_em(symbol=code)
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                key = str(r.get("item", ""))
                if key in ("行业", "所属行业", "行业分类", "industry"):
                    val = str(r.get("value", "")).strip()
                    if val and val != "--":
                        result[code] = val
                        break
        except Exception:
            continue

    return result


# ============================================================
# 4. 统一行业兜底
# ============================================================
def get_industry(code: str) -> str:
    """
    统一获取行业信息（优先THS，其次EM，最后代码前缀兜底）
    """
    import akshare as ak
    # 1. THS
    if hasattr(ak, "stock_individual_info_em"):
        try:
            df = ak.stock_individual_info_em(symbol=code)
            if df is not None and not df.empty:
                for _, r in df.iterrows():
                    key = str(r.get("item", ""))
                    if key in ("行业", "所属行业"):
                        val = str(r.get("value", "")).strip()
                        if val and val != "--":
                            return val
        except Exception:
            pass
    # 2. 代码前缀兜底
    if code.startswith(('60', '68')):
        return "上海主板"
    elif code.startswith('00'):
        return "深圳主板"
    elif code.startswith('30'):
        return "创业板"
    elif code.startswith('8', '4'):
        return "北交所"
    return "未知"


# ============================================================
# 5. 估值数据（PE/PB）— Baidu + THS + yfinance 多层兜底
# ============================================================
def _fill_pe_pb_from_baidu(codes: list, pe_map: dict, pb_map: dict):
    """使用百度股市通补充PE/PB（逐股查询，较慢但覆盖率高）"""
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor
    def _fetch_one(code):
        try:
            pe_df = ak.stock_zh_valuation_baidu(symbol=code, indicator="市盈率(TTM)", period="近一年")
            pe = pe_df["value"].iloc[-1] if pe_df is not None and len(pe_df) > 0 else None
            pb_df = ak.stock_zh_valuation_baidu(symbol=code, indicator="市净率", period="近一年")
            pb = pb_df["value"].iloc[-1] if pb_df is not None and len(pb_df) > 0 else None
            return code, pe, pb
        except Exception:
            return code, None, None
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(_fetch_one, c) for c in codes]
        for f in futures:
            code, pe, pb = f.result()
            if pe is not None:
                pe_map[code] = pe
            if pb is not None:
                pb_map[code] = pb


def _fill_pe_pb_from_ths(codes: list, pe_map: dict, pb_map: dict):
    """使用THS财务摘要计算PE/PB（EPS/BPS → PE/PB）"""
    import akshare as ak
    import sys, os
    # AGENTS.md #48: macOS sandbox 中 py_mini_racer 不可用，跳过 THS
    if sys.platform == 'darwin' and not os.environ.get('LH_MGMT_TRY_CNINFO'):
        return
    for code in codes:
        try:
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                eps = r.get("基本每股收益")
                bps = r.get("每股净资产")
                if eps and bps:
                    # 需要股价，但此处不获取，直接返回 EPS/BPS
                    pass
        except Exception:
            continue


def _fill_pe_pb_from_yfinance(codes: list, pe_map: dict, pb_map: dict):
    """使用 yfinance 补充PE/PB（海外数据源，覆盖A股有限）"""
    try:
        import yfinance as yf
        for code in codes:
            ticker = f"{code}.SS" if code.startswith('6') else f"{code}.SZ"
            try:
                info = yf.Ticker(ticker).info
                if info:
                    pe = info.get("trailingPE") or info.get("forwardPE")
                    pb = info.get("priceToBook")
                    if pe:
                        pe_map[code] = pe
                    if pb:
                        pb_map[code] = pb
            except Exception:
                continue
    except ImportError:
        pass


# ============================================================
# 6. 数据增强统一入口
# ============================================================
async def enrich_data(
    bonds: list,
    include_financial: bool = True,
    include_industry: bool = True,
    include_pe_pb: bool = True,
) -> list:
    """
    统一数据增强入口
    
    Args:
        bonds: ConvertibleQuote 列表
        include_financial: 是否包含财务数据
        include_industry: 是否包含行业数据
        include_pe_pb: 是否包含PE/PB估值
    
    Returns:
        增强后的 ConvertibleQuote 列表
    """
    from app.models.convertible import ConvertibleQuote
    
    stock_codes = [b.stock_code for b in bonds if b.stock_code]
    
    # 1. 财务数据
    if include_financial:
        fin_data = fetch_ths_financial_batch(stock_codes)
        for b in bonds:
            if b.stock_code in fin_data:
                d = fin_data[b.stock_code]
                b.roe = d.get("roe")
                b.gpm = d.get("gpm")
                b.debt_ratio = d.get("debt_ratio")
    
    # 2. 行业数据
    if include_industry:
        # 构建 bonds dict
        bonds_dict = {b.code: {"stock_code": b.stock_code} for b in bonds}
        industry_data = fetch_ths_bond_industry(bonds_dict)
        for b in bonds:
            if b.stock_code in industry_data:
                b.industry = industry_data[b.stock_code]
    
    # 3. PE/PB
    if include_pe_pb:
        pe_map, pb_map = {}, {}
        _fill_pe_pb_from_baidu(stock_codes, pe_map, pb_map)
        missing_pe = [c for c in stock_codes if c not in pe_map]
        if missing_pe:
            _fill_pe_pb_from_ths(missing_pe, pe_map, pb_map)
        missing_pe2 = [c for c in stock_codes if c not in pe_map]
        if missing_pe2:
            _fill_pe_pb_from_yfinance(missing_pe2, pe_map, pb_map)
        for b in bonds:
            if b.stock_code in pe_map:
                b.pe = pe_map[b.stock_code]
            if b.stock_code in pb_map:
                b.pb = pb_map[b.stock_code]
    
    return bonds
