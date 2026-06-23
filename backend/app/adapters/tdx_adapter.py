"""
通达信 (TDX) 数据适配器 - 低延迟行情、K线、财务数据

数据来源:
  通过 pytdx 连接通达信行情服务器，提供低延迟的实时行情、历史K线、财务数据等。
  作为东方财富/Sina/百度等数据源的备用或补充。

TDX 服务器池:
  - 180.153.18.170:7709 (已验证可用)
  - 180.153.18.171:7709
  - 180.153.18.172:7709
  - 119.147.212.81:7709
  - 115.238.56.43:7709
  - 106.120.96.158:7709
"""

import asyncio
import logging
import time
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
from app.engine.data_enrich_utils import safe_float, safe_int

logger = logging.getLogger(__name__)

# TDX 服务器池（按优先级排序）
TDX_SERVERS = [
    ("180.153.18.170", 7709),
    ("180.153.18.171", 7709),
    ("180.153.18.172", 7709),
    ("119.147.212.81", 7709),
    ("115.238.56.43", 7709),
    ("106.120.96.158", 7709),
]

# 市场代码
MARKET_SH = 1  # 上海
MARKET_SZ = 0  # 深圳
MARKET_BJ = 2  # 北京

_POOL = ThreadPoolExecutor(max_workers=4)
atexit.register(_POOL.shutdown)


def _get_market(code: str) -> int:
    """根据股票代码返回 TDX 市场代码"""
    c = str(code).strip()
    if c.startswith(("6", "9", "11")):
        return MARKET_SH
    elif c.startswith(("0", "3", "2", "12")):
        return MARKET_SZ
    elif c.startswith(("4", "8")):
        return MARKET_BJ
    return MARKET_SZ  # default


class TdxAdapter:
    """通达信数据适配器 - 支持连接池、自动重连、批量查询"""

    def __init__(self, connect_timeout: float = 3.0) -> None:
        self._connected: bool = False
        self._api: Any = None
        self._server: Optional[tuple[str, int]] = None
        self._connect_timeout: float = connect_timeout
        self._last_used: float = 0.0

    # ── 连接管理 ──

    def _ensure_connected(self) -> bool:
        """确保连接到 TDX 服务器，自动选择可用服务器"""
        if not isinstance(TDX_SERVERS, (list, tuple)) or not TDX_SERVERS:
            logger.warning("[TDX] TDX_SERVERS 不可用或为空，跳过连接")
            self._connected = False
            return False

        now = time.time()
        if self._connected and self._api is not None and (now - self._last_used) < 60:
            try:
                self._api.do_heartbeat()
                return True
            except Exception as e:
                logger.warning(f"[TDX] heartbeat failed: {e}")
                self._connected = False

        for ip, port in TDX_SERVERS:
            try:
                from pytdx.hq import TdxHq_API
                api: Any = TdxHq_API()
                ok = api.connect(ip, port, time_out=self._connect_timeout)
                if ok:
                    self._api = api
                    self._server = (ip, port)
                    self._connected = True
                    self._last_used = time.time()
                    logger.debug(f"[TDX] Connected to {ip}:{port}")
                    return True
            except Exception as e:
                logger.warning(f"[TDX] 连接服务器 {ip}:{port} 失败: {e}")
                continue

        self._connected = False
        return False

    def disconnect(self) -> None:
        if self._api is not None:
            try:
                self._api.disconnect()
            except Exception as e:
                logger.warning(f"[TDX] 断开连接失败: {e}")
        self._api = None
        self._connected = False

    # ── API 方法（_ensure_connected 确保 self._api 非 None） ──

    def _api_call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """执行 TDX API 调用，确保连接可用"""
        if not self._ensure_connected():
            return None
        fn = getattr(self._api, method, None)
        if fn is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.debug(f"[TDXAdapter] API call {method} failed: {e}")
            raise

    # ── 实时行情 ──

    def fetch_quotes(self, codes: list[str]) -> dict[str, dict]:
        """批量获取实时行情

        Args:
            codes: 股票/债券代码列表

        Returns: {code: {price, open, high, low, last_close, vol, amount, change_pct, ...}}
        """
        if not self._ensure_connected():
            return {}

        groups: dict[int, list[str]] = {}
        for code in codes:
            m = _get_market(code)
            groups.setdefault(m, []).append(code)

        result: dict[str, dict] = {}
        for market, codes_list in groups.items():
            for i in range(0, len(codes_list), 80):
                batch = codes_list[i:i + 80]
                try:
                    quotes = self._api.get_security_quotes(
                        [(market, c) for c in batch]
                    )
                    if not quotes:
                        continue
                    for q in quotes:
                        code = str(q.get('code', '')).strip()
                        if not code:
                            continue
                        price_raw = q.get('price')
                        last_close_raw = q.get('last_close')
                        open_raw = q.get('open')
                        high_raw = q.get('high')
                        low_raw = q.get('low')
                        vol = q.get('vol')
                        amount = q.get('amount')
                        # TDX 债券价格用 0.001元 存储（如 106798→106.80元），股票直接是元
                        divisor = 1.0
                        # 只有 price_raw 有效时才判断 divisor
                        if price_raw is not None and price_raw > 1000 and (code.startswith("11") or code.startswith("12") or code.startswith("13") or code.startswith("118") or code.startswith("123")):
                            divisor = 100.0
                        price = (price_raw / divisor) if price_raw is not None else None
                        last_close = (last_close_raw / divisor) if last_close_raw is not None else None
                        open_p = (open_raw / divisor) if open_raw is not None else None
                        high = (high_raw / divisor) if high_raw is not None else None
                        low = (low_raw / divisor) if low_raw is not None else None
                        change_pct = ((price - last_close) / last_close * 100) if (price is not None and last_close is not None and last_close > 0) else None
                        result[code] = {
                            "price": round(price, 2) if price is not None else None,
                            "open": round(open_p, 2) if open_p is not None else None,
                            "high": round(high, 2) if high is not None else None,
                            "low": round(low, 2) if low is not None else None,
                            "last_close": round(last_close, 2) if last_close is not None else None,
                            "vol": vol,
                            "amount": amount,
                            "change_pct": round(change_pct, 2) if change_pct is not None else None,
                        }
                except Exception as e:
                    logger.debug(f"[TDX] quotes batch failed for market={market}: {e}")
        self._last_used = time.time()
        return result

    def fetch_single_quote(self, code: str) -> Optional[dict]:
        """获取单只股票/债券实时行情"""
        quotes = self.fetch_quotes([code])
        return quotes.get(code)

    # ── 财务数据 ──

    def fetch_finance_info(self, code: str) -> Optional[dict]:
        """获取单只股票财务数据
        
        注意: pytdx 返回的 jinglirun (净利润) 是集团合并数据 (含子公司/母公司),
        非单家上市公司数据。计算的 PE/PB/ROE 可能偏差 3-5x, 仅供最低优先级参考。
        优先使用 Baidu 估值 (akshare) 或同花顺财务摘要。
        """
        if not self._ensure_connected():
            return None
        try:
            market = _get_market(code)
            info = self._api.get_finance_info(market, code)
            if not info:
                return None

            price: Optional[float] = None
            try:
                qs = self._api.get_security_quotes([(market, code)])
                if qs:
                    p = float(qs[0].get('price', 0) or 0)
                    if p > 0:
                        price = p
            except Exception as e:
                logger.warning(f"[TDX] 获取 {code} 行情失败: {e}")

            jingzichan = safe_float(info.get('jingzichan'))
            meigujingzichan = safe_float(info.get('meigujingzichan'))
            zongguben = safe_float(info.get('zongguben'))
            jinglirun = safe_float(info.get('jinglirun'))
            zhuyingshouru = safe_float(info.get('zhuyingshouru'))
            zongzichan = safe_float(info.get('zongzichan'))
            liudongfuzhai = safe_float(info.get('liudongfuzhai'))
            gudongrenshu = safe_float(info.get('gudongrenshu'))
            liutongguben = safe_float(info.get('liutongguben'))

            result: dict[str, Any] = {
                "jingzichan": jingzichan,
                "meigujingzichan": meigujingzichan,
                "zongguben": zongguben,
                "jinglirun": jinglirun,
                "zhuyingshouru": zhuyingshouru,
                "zongzichan": zongzichan,
                "liudongfuzhai": liudongfuzhai,
                "gudongrenshu": gudongrenshu,
                "liutongguben": liutongguben,
            }

            # ⚠️ 低精度警告: pytdx 的 jinglirun 是集团合并数据, PE/PB 可能偏差 3-5x
            if price and price > 0 and jinglirun is not None and zongguben and zongguben > 0:
                eps = jinglirun / zongguben
                pe_val = round(price / eps, 2) if eps > 0 else None
                if pe_val is not None:
                    result["pe"] = pe_val
                    result["pe_confidence"] = "low"  # 标记低可信度
                result["eps"] = round(eps, 4)
            else:
                result["pe"] = None
                result["eps"] = None

            if price and price > 0 and meigujingzichan and meigujingzichan > 0:
                pb = price / meigujingzichan
                pb_val = round(pb, 2) if 0 < pb < 1000 else None
                if pb_val is not None:
                    result["pb"] = pb_val
                    result["pb_confidence"] = "low"
            else:
                result["pb"] = None

            result["bps"] = meigujingzichan

            if jinglirun is not None and jingzichan and jingzichan > 0:
                roe_val = round(jinglirun / jingzichan, 4)
                result["roe"] = roe_val
                result["roe_confidence"] = "low"
            else:
                result["roe"] = None

            self._last_used = time.time()
            return result
        except Exception as e:
            logger.debug(f"[TDX] finance info failed for {code}: {e}")
            return None

    def fetch_finance_batch(self, codes: list[str]) -> dict[str, dict]:
        """批量获取财务数据"""
        result: dict[str, dict] = {}
        for code in codes:
            info = self.fetch_finance_info(code)
            # 保留任一有用财务字段，避免仅含 ROE 的数据被丢弃
            if info and any(info.get(k) for k in ("pe", "pb", "eps", "bps", "roe", "gpm")):
                result[code] = info
        return result

    # ── K-line 数据 ──

    def fetch_kline(self, code: str, days: int = 120) -> list[dict]:
        """获取日K线数据"""
        if not self._ensure_connected():
            return []
        from pytdx.params import TDXParams
        try:
            market = _get_market(code)
            bars = self._api.get_security_bars(
                TDXParams.KLINE_TYPE_DAILY, market, code, 0, min(days, 800)
            )
            if not bars:
                return []
            result: list[dict] = []
            for b in bars:
                year = b.get('year', 0)
                month = b.get('month', 1)
                day = b.get('day', 1)
                date_str = f"{year:04d}-{month:02d}-{day:02d}"
                close = safe_float(b.get('close'))
                if close is None or close <= 0:
                    continue
                result.append({
                    "date": date_str,
                    "open": safe_float(b.get('open')),
                    "close": close,
                    "high": safe_float(b.get('high')),
                    "low": safe_float(b.get('low')),
                    "vol": safe_float(b.get('vol', 0)),
                    "amount": safe_float(b.get('amount', 0)),
                })
            self._last_used = time.time()
            return result
        except Exception as e:
            logger.debug(f"[TDX] kline failed for {code}: {e}")
            return []

    def fetch_kline_batch(self, codes: list[str], days: int = 120) -> dict[str, list[dict]]:
        """批量获取K线数据"""
        result: dict[str, list[dict]] = {}
        for code in codes:
            kline = self.fetch_kline(code, days)
            if kline:
                result[code] = kline
        return result

    # ── 证券列表 ──

    def fetch_security_list(self, market: int, start: int = 0, count: int = 2000) -> list[dict]:
        """获取证券列表（自动跳过空段）"""
        if not self._ensure_connected():
            return []
        try:
            total = self._api.get_security_count(market)
            if not total:
                return []
            result: list[dict] = []
            offset = start
            empty_skip = 0
            while offset < total and len(result) < count:
                chunk = self._api.get_security_list(market, offset)
                if not chunk or len(chunk) == 0:
                    empty_skip += 1
                    offset += 200  # 跳过空段
                    if empty_skip > 50:  # 最多跳过10000条
                        break
                    continue
                empty_skip = 0
                for s in chunk:
                    code = str(s.get('code', '')).strip()
                    name = str(s.get('name', '')).strip()
                    pre_close = safe_float(s.get('pre_close'))
                    if code:
                        result.append({
                            "code": code,
                            "name": name,
                            "pre_close": pre_close,
                        })
                        if len(result) >= count:
                            break
                # 按实际返回长度递增偏移；空段使用 200 步长跳过
                offset += len(chunk) if chunk else 200
            self._last_used = time.time()
            return result
        except Exception as e:
            logger.debug(f"[TDX] security list failed for market={market}: {e}")
            return []

    def fetch_securities_by_name(self, keyword: str, stock_only: bool = True) -> list[dict]:
        """通过名称关键词搜索证券（自动跳过空段）
        
        Args:
            keyword: 搜索关键词
            stock_only: 如果为 True, 只返回 A 股股票 (排除指数/债券)
        """
        result: list[dict] = []
        for market in [MARKET_SZ, MARKET_SH]:
            if not self._ensure_connected():
                continue
            try:
                total_raw = self._api.get_security_count(market)
                if total_raw is None:
                    continue
                total = int(total_raw)
            except Exception as e:
                logger.warning(f"[TDX] 获取市场 {market} 证券总数失败: {e}")
                continue
            offset = 0
            empty_skip = 0
            while offset < total:
                try:
                    chunk = self._api.get_security_list(market, offset)
                    if not chunk or len(chunk) == 0:
                        empty_skip += 1
                        offset += 200
                        if empty_skip > 50:
                            break
                        continue
                    empty_skip = 0
                    for s in chunk:
                        code = str(s.get('code', '')).strip()
                        name = str(s.get('name', '')).strip()
                        if not code or not name:
                            continue
                        if stock_only:
                            # SH 股票: 6xxxxx
                            if market == MARKET_SH and not code.startswith('6'):
                                continue
                            # SZ 股票: 000/001/002/003/300/301 (排除 394/395/399 等非股票代码)
                            if market == MARKET_SZ and code[:3] not in ('000', '001', '002', '003', '300', '301'):
                                continue
                            if len(code) != 6 or not code.isdigit():
                                continue
                        if keyword in name:
                            result.append({
                                "code": code,
                                "name": name,
                                "market": market,
                            })
                    offset += 1000
                except Exception as e:
                    logger.warning(f"[TDX] 按名称搜索证券时失败: {e}")
                    break
        return result

    def fetch_all_securities(self, stock_only: bool = True) -> dict[str, str]:
        """获取所有证券的代码→名称映射
        
        Args:
            stock_only: 如果为 True, 只返回 A 股股票代码 (排除指数/债券/基金)
                        SZ: 0/2/3开头, SH: 6开头, BJ: 4/8开头
        """
        result: dict[str, str] = {}
        for market in [MARKET_SZ, MARKET_SH, MARKET_BJ]:
            securities = self.fetch_security_list(market, count=99999)  # 获取全部
            for s in securities:
                code = s["code"]
                name = s["name"]
                if not code or not name:
                    continue
                if code in result:
                    continue
                if stock_only:
                    # SH 股票: 6xxxxx
                    if market == MARKET_SH and not code.startswith('6'):
                        continue
                    # SZ 股票: 000/001/002/003/300/301
                    if market == MARKET_SZ and code[:3] not in ('000', '001', '002', '003', '300', '301'):
                        continue
                    # BJ 股票: 4/8xxxxx
                    if market == MARKET_BJ and not code.startswith(('4', '8')):
                        continue
                    # 确保6位数字
                    if len(code) != 6 or not code.isdigit():
                        continue
                if name:
                    result[code] = name
        logger.info(f"[TDX] Securities loaded: {len(result)} stocks (stock_only={stock_only})")
        return result


# ── 共享实例（懒加载） ──

_shared_adapter: Optional[TdxAdapter] = None


def get_tdx_adapter() -> TdxAdapter:
    """获取共享 TDX 适配器实例"""
    global _shared_adapter
    if _shared_adapter is None:
        _shared_adapter = TdxAdapter()
    return _shared_adapter


# ── 异步包装 ──

async def _run_tdx_sync(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """在线程池中运行 TDX 同步函数"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_POOL, lambda: fn(*args, **kwargs))


async def async_fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """异步获取实时行情"""
    adapter = get_tdx_adapter()
    return await _run_tdx_sync(adapter.fetch_quotes, codes)


async def async_fetch_finance_batch(codes: list[str]) -> dict[str, dict]:
    """异步批量获取财务数据"""
    adapter = get_tdx_adapter()
    return await _run_tdx_sync(adapter.fetch_finance_batch, codes)


async def async_fetch_kline_batch(codes: list[str], days: int = 120) -> dict[str, list[dict]]:
    """异步批量获取K线数据"""
    adapter = get_tdx_adapter()
    return await _run_tdx_sync(adapter.fetch_kline_batch, codes, days)


async def async_fetch_security_list(market: int, start: int = 0, count: int = 2000) -> list[dict]:
    """异步获取证券列表"""
    adapter = get_tdx_adapter()
    return await _run_tdx_sync(adapter.fetch_security_list, market, start, count)


async def async_fetch_all_securities() -> dict[str, str]:
    """异步获取所有证券代码→名称"""
    adapter = get_tdx_adapter()
    return await _run_tdx_sync(adapter.fetch_all_securities)


async def async_fetch_finance_info(code: str) -> Optional[dict]:
    """异步获取单只股票财务数据"""
    adapter = get_tdx_adapter()
    return await _run_tdx_sync(adapter.fetch_finance_info, code)


async def async_fetch_kline(code: str, days: int = 120) -> list[dict]:
    """异步获取K线数据"""
    adapter = get_tdx_adapter()
    return await _run_tdx_sync(adapter.fetch_kline, code, days)
