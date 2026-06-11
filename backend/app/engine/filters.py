"""
可转债交易过滤器 - 集中管理退市/可交换债/价格异常/强赎等过滤规则。

此模块的缺失会导致 signals.py / market.py / analysis.py 在处理行情时
抛出 ModuleNotFoundError，且被上层 try/except 静默吞掉——最终导致:
- 行情刷新时所有可交换债和退市转债混入
- 信号引擎对已强赎/临近退市的债券继续生成信号
- 静默失败，没有告警
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.convertible import ConvertibleQuote

logger = logging.getLogger(__name__)


# 临退市预警天数（强赎/到期/退市最后交易日前 N 天不交易）
RETIREMENT_WARNING_DAYS = 3


def is_exchangeable_bond(code: str, name: str) -> bool:
    """判断是否可交换债(EB)。可交换债代码以 "EB" 或 "132"/"133" 开头。"""
    if not code and not name:
        return False
    if code:
        c = code.upper()
        if c.startswith("EB") or c.startswith("132") or c.startswith("133"):
            return True
    if name and ("可交换债" in name or name.startswith("EB")):
        return True
    return False


def is_delisted_bond(code: str, name: str) -> bool:
    """判断是否已退市/退市整理期。

    退市转债在行情系统中通常:
    - 代码以 "Z" 开头（部分老退市债券）
    - 名称含 "退" 字
    """
    if not code and not name:
        return False
    if code and code.upper().startswith("Z"):
        return True
    if name and ("退" in name or "DELIST" in name.upper()):
        return True
    return False


def is_delisted_or_exchangeable(code: str, name: str) -> bool:
    """退市/可交换债过滤 — 应从行情中排除。"""
    return is_delisted_bond(code, name) or is_exchangeable_bond(code, name)


def _parse_iso_date(value) -> date | None:
    """容错解析 date/datetime/str → date;空值/无效值返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s or s in ("nan", "NaT", "None"):
            return None
        try:
            return datetime.strptime(s[:10].replace("/", "-"), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def is_tradeable_bond(b: "ConvertibleQuote", today: date | None = None) -> bool:
    """是否适合生成交易信号。

    过滤规则:
    - 退市/可交换债
    - 价格异常（<= 0 或极端值）
    - 已公告强赎（is_called=True）
    - 强赎/到期/退市最后交易日前 3 天（用户要求:即将赎回/退市前 3 天不能交易）

    出错时记录日志并返回 False（保守放行：宁可漏掉机会，不要对坏数据生成信号）。
    """
    try:
        if b is None:
            return False
        if is_delisted_or_exchangeable(b.code, b.name):
            return False
        if b.price is None or b.price <= 0:
            return False
        if b.is_called:
            return False
        # 公告要强赎（call_status 含 "公告要强赎" 或 "已公告强赎"）也应排除
        if b.call_status and any(s in b.call_status for s in ("公告要强赎", "已公告强赎")):
            return False
        today = today or date.today()
        cutoff = today.toordinal() + RETIREMENT_WARNING_DAYS
        for d in (b.last_trade_date, b.maturity_date):
            parsed = _parse_iso_date(d)
            if parsed and parsed.toordinal() <= cutoff:
                return False
        return True
    except Exception as e:
        logger.warning(f"[filters] is_tradeable_bond failed for {getattr(b, 'code', '?')}: {e}")
        return False
