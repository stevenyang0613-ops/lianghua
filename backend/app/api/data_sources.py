"""
多源真实数据兜底模块 — 用于回测数据加载
数据源优先级 (从快到慢, 从可靠到备用):

PE/PB数据:
  ① Baidu valuation (逐股 PE+PB, 多线程) — ~0.85s/只 × 2次, 15线程并行
  ② THS财务摘要 (EPS/BPS推算)             — 最后备选, 季度数据

转债行情数据:
  ① THS转债列表 + Sina实时行情           — 主力
  ② Jisilu集思录                         — 溢价率/双低/评级
  ③ Tencent K线 (正股)                    — 正股历史日线
  ④ 正股K线推算转债价格                    — premium ratio 估算法
"""
import os
import time as _time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================
# 第1层: Baidu估值 — 逐股PE/PB (稳定可用, 主力)
# ============================================================
def fetch_pe_pb_baidu_both(code: str) -> dict:
    """
    Baidu 同时获取 PE + PB (单只股票, 2次API调用)
    
    akshare.stock_zh_valuation_baidu 返回近1年的每日估值数据
    取最新日期的值, 约0.4s/次, 2次≈0.85s/只
    
    Returns:
        {"pe": float, "pb": float} 或 {}
    """
    result = {}
    try:
        df_pe = ak.stock_zh_valuation_baidu(symbol=code, indicator='市盈率(TTM)', period='近一年')
        if df_pe is not None and not df_pe.empty:
            v = df_pe['value'].iloc[-1]
            if v is not None and v != 0:
                result['pe'] = float(v)
    except Exception:
        pass
    
    _time.sleep(0.05)  # 避免请求过快
    
    try:
        df_pb = ak.stock_zh_valuation_baidu(symbol=code, indicator='市净率', period='近一年')
        if df_pb is not None and not df_pb.empty:
            v = df_pb['value'].iloc[-1]
            if v is not None and v != 0:
                result['pb'] = float(v)
    except Exception:
        pass
    
    return result


# ============================================================
# 第2层: THS财务摘要 — EPS/BPS推算PE/PB (最后备选)
# ============================================================
def fetch_pe_pb_ths_financial(code: str, stock_price: float = None) -> dict:
    """
    从同花顺财务摘要获取EPS/BPS, 反推PE/PB
    
    akshare.stock_financial_abstract_ths 返回年度财务数据
    取最近一年 EPS(基本每股收益) 和 BPS(每股净资产)
    用最新数据推算 PE = price / EPS, PB = price / BPS
    
    注意: 年报数据滞后6-12个月, 仅作最后备选
    
    Returns:
        {"pe": float, "pb": float}
    """
    if stock_price is None or stock_price <= 0:
        return {}
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator='按年度')
        if df is None or df.empty:
            return {}
        
        eps = None
        bps = None
        for _, r in df.iterrows():
            if eps is None:
                v = r.get('基本每股收益', None)
                if v is not None and str(v) not in ('False', 'None', ''):
                    try:
                        eps = float(v)
                    except (ValueError, TypeError):
                        pass
            if bps is None:
                v = r.get('每股净资产', None)
                if v is not None and str(v) not in ('False', 'None', ''):
                    try:
                        bps = float(v)
                    except (ValueError, TypeError):
                        pass
            if eps is not None and bps is not None:
                break
        
        result = {}
        if eps is not None and eps > 0:
            pe = stock_price / eps
            if 0 < pe < 10000:
                result['pe'] = pe
        if bps is not None and bps > 0:
            pb = stock_price / bps
            if 0 < pb < 1000:
                result['pb'] = pb
        return result
    except Exception:
        return {}


# ============================================================
# 主入口: 多层兜底PE/PB获取 (修复版 v2)
# ============================================================
def get_stock_valuations(stock_codes: list[str], stock_prices: dict[str, float] = None) -> dict[str, dict]:
    """
    多层兜底获取全量正股PE/PB估值数据
    
    优先级:
    ① Baidu估值 (逐股, 15线程, 全量)    — ~15s 处理250只
    ② THS财务摘要 (EPS/BPS推算)          — 最后备选, 限100只
    
    整体超时保护: 硬180秒上限
    
    Args:
        stock_codes: 正股代码列表
        stock_prices: {code: price} 用于THS推算PE/PB
    
    Returns:
        {stock_code: {"pe": float, "pb": float}}
    """
    if not stock_codes:
        return {}
    
    stock_codes = list(set(stock_codes))
    stock_prices = stock_prices or {}
    _DEADLINE = _time.time() + 180.0  # 硬180秒上限 (Baidu 500只 × 0.85s, 15线程 ≈ 30s)

    def _remaining() -> float:
        return max(1.0, _DEADLINE - _time.time())

    result: dict[str, dict] = {}

    # ===== 第1层: Baidu估值 (逐股, 多线程, 主力) =====
    logger.info(f"[MultiSource] 第1层: Baidu估值 ({len(stock_codes)}只, 15线程)...")
    t0 = _time.time()
    
    # Baidu 并发线程数: 15线程
    n_workers = min(15, max(3, len(stock_codes) // 10 + 1))
    
    def _fetch_code(code: str) -> tuple[str, dict]:
        """带超时的单只股票Baidu估值"""
        try:
            val = fetch_pe_pb_baidu_both(code)
            return code, val
        except Exception:
            return code, {}
    
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(_fetch_code, code): code for code in stock_codes}
        done_count = [0]
        for future in as_completed(futures):
            if _time.time() >= _DEADLINE:
                break
            code = futures[future]
            try:
                _, val = future.result(timeout=max(1, _remaining()))
                if val:
                    if code not in result:
                        result[code] = {}
                    for k, v in val.items():
                        if k not in result[code]:
                            result[code][k] = v
            except Exception:
                pass
            done_count[0] += 1
            if done_count[0] % 50 == 0:
                pe_now = sum(1 for c in stock_codes if result.get(c, {}).get('pe'))
                logger.info(f"  [Baidu] {done_count[0]}/{len(stock_codes)}, PE={pe_now} ({_time.time()-_DEADLINE+180:.0f}s)")
    
    t1 = _time.time()
    baidu_pe = sum(1 for c in stock_codes if result.get(c, {}).get('pe'))
    baidu_pb = sum(1 for c in stock_codes if result.get(c, {}).get('pb'))
    logger.info(f"[MultiSource] Baidu完成: PE={baidu_pe}, PB={baidu_pb}/{len(stock_codes)} ({t1-t0:.0f}s)")

    # ===== 第2层: THS财务摘要 (最后备选, EPS/BPS推算, 限100只) =====
    missing = [c for c in stock_codes
               if c not in result or 'pe' not in result.get(c, {}) or 'pb' not in result.get(c, {})]
    if missing and stock_prices and _remaining() > 30:
        missing_with_price = [c for c in missing if c in stock_prices and stock_prices[c] > 0]
        if len(missing_with_price) > 100:
            logger.warning(f"[MultiSource] THS: 全部{len(missing_with_price)}只, 截取100只")
            missing_with_price = missing_with_price[:100]
        
        if missing_with_price:
            logger.info(f"[MultiSource] 第2层: THS财务推算 ({len(missing_with_price)}只)...")
            t0 = _time.time()
            with ThreadPoolExecutor(max_workers=5) as ex:
                futures = {
                    ex.submit(fetch_pe_pb_ths_financial, code, stock_prices.get(code)): code
                    for code in missing_with_price
                }
                for future in as_completed(futures):
                    if _time.time() >= _DEADLINE:
                        break
                    code = futures[future]
                    try:
                        val = future.result(timeout=max(1, _remaining()))
                        if val:
                            if code not in result:
                                result[code] = {}
                            for k, v in val.items():
                                if k not in result[code]:
                                    result[code][k] = v
                    except Exception:
                        pass
            t1 = _time.time()
            logger.info(f"[MultiSource] THS完成 ({t1-t0:.1f}s)")

    # 最终统计
    pe_ok = sum(1 for v in result.values() if v.get('pe'))
    pb_ok = sum(1 for v in result.values() if v.get('pb'))
    elapsed = _time.time() - (_DEADLINE - 180)
    logger.info(f"[MultiSource] 最终PE/PB覆盖: PE={pe_ok}, PB={pb_ok}/{len(stock_codes)} in {elapsed:.0f}s")
    return result


# ============================================================
# 辅助函数: 获取正股历史价格 (Tencent K线)
# ============================================================
def get_stock_hist_prices(stock_code: str, start_date, end_date) -> pd.DataFrame:
    """从Tencent获取正股历史K线"""
    if stock_code.startswith('6'):
        symbol = f'sh{stock_code}'
    elif stock_code.startswith(('0', '3')):
        symbol = f'sz{stock_code}'
    elif stock_code.startswith(('4', '8')):
        symbol = f'bj{stock_code}'
    else:
        symbol = f'sh{stock_code}'
    
    try:
        df = ak.stock_zh_a_hist_tx(symbol=symbol, adjust='hfq')
        if df is None or df.empty:
            return pd.DataFrame()
        df['date'] = pd.to_datetime(df['date'])
        mask = (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
        df = df[mask].copy()
        df['code'] = stock_code
        return df
    except Exception as e:
        logger.warning(f"[Tencent hist] {stock_code}: {e}")
        return pd.DataFrame()
# ============================================================
# Tushare Pro 数据源 — YTM/纯债价值/隐含波动率
# ============================================================
# Tushare Pro 提供:
#   cb_daily:   可转债行情 (close, bond_value纯债价值, cb_value转股价值, cb_over_rate转股溢价率)
#   cb_basic:   可转债基本信息 (maturity_date, conv_price, coupon_rate, add_rate补偿利率)
#   cb_rate:    可转债票息表 (逐年票息率)
#   cb_share:   可转债股本变动 (remain_size剩余规模)

_TUSHARE_INITIALIZED = False
_TUSHARE_PRO = None

def _get_tushare():
    """初始化Tushare Pro连接"""
    global _TUSHARE_INITIALIZED, _TUSHARE_PRO
    if _TUSHARE_INITIALIZED:
        return _TUSHARE_PRO
    try:
        token = None
        try:
            from app.config import settings
            token = settings.TUSHARE_TOKEN
        except Exception:
            token = os.environ.get('LH_TUSHARE_TOKEN', '')
        if not token:
            _TUSHARE_INITIALIZED = True
            _TUSHARE_PRO = None
            return None
        import tushare as ts
        _TUSHARE_PRO = ts.pro_api(token)
        _TUSHARE_INITIALIZED = True
        logger.info("[Tushare] Pro API connected")
        return _TUSHARE_PRO
    except ImportError:
        logger.warning("[Tushare] tushare package not installed")
        _TUSHARE_INITIALIZED = True
        _TUSHARE_PRO = None
        return None
    except Exception as e:
        logger.warning(f"[Tushare] init failed: {e}")
        _TUSHARE_INITIALIZED = True
        _TUSHARE_PRO = None
        return None


def fetch_cb_daily_tushare(trade_date: str = None, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    Tushare Pro cb_daily — 可转债日线行情
    
    关键字段:
    - bond_value: 纯债价值(元) — 估算债券底
    - cb_value: 转股价值(元)
    - bond_over_rate: 纯债溢价率(%)
    - cb_over_rate: 转股溢价率(%)
    """
    pro = _get_tushare()
    if pro is None:
        return pd.DataFrame()
    
    fields = 'ts_code,trade_date,close,bond_value,cb_value,bond_over_rate,cb_over_rate,vol,amount'
    try:
        df = pro.cb_daily(
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            fields=fields
        )
        if df is not None and not df.empty:
            # 解析code
            df['code'] = df['ts_code'].str.extract(r'(\d{6})')
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            return df
    except Exception as e:
        logger.debug(f"[Tushare] cb_daily error: {e}")
    return pd.DataFrame()


def fetch_cb_basic_tushare() -> dict:
    """
    Tushare Pro cb_basic — 可转债基本信息
    
    关键字段:
    - maturity_date: 到期日期
    - conv_price: 最新转股价
    - coupon_rate: 票面利率(%)
    - add_rate: 补偿利率(%)
    - remain_size: 债券余额(元)
    """
    pro = _get_tushare()
    if pro is None:
        return {}
    
    try:
        df = pro.cb_basic(fields='ts_code,bond_short_name,stk_code,stk_short_name,'
                          'maturity_date,coupon_rate,add_rate,conv_price,'
                          'remain_size,list_date,delist_date,issue_size')
        if df is not None and not df.empty:
            result = {}
            for _, r in df.iterrows():
                code = str(r.get('ts_code', '')).split('.')[0]
                if not code or len(code) != 6:
                    continue
                result[code] = {
                    'name': str(r.get('bond_short_name', '')),
                    'stock_code': str(r.get('stk_code', '')).split('.')[0],
                    'stock_name': str(r.get('stk_short_name', '')),
                    'maturity_date': r.get('maturity_date'),
                    'conv_price': float(r.get('conv_price', 0) or 0),
                    'coupon_rate': float(r.get('coupon_rate', 0) or 0),
                    'add_rate': float(r.get('add_rate', 0) or 0),
                    'remain_size': float(r.get('remain_size', 0) or 0),
                    'issue_size': float(r.get('issue_size', 0) or 0),
                    'list_date': r.get('list_date'),
                }
            logger.info(f"[Tushare] cb_basic: {len(result)} bonds")
            return result
    except Exception as e:
        logger.debug(f"[Tushare] cb_basic error: {e}")
    return {}
