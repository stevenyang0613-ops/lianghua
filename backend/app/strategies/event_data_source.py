"""
事件驱动实时数据源模块

监控和解析：
- 下修公告
- 强赎公告
- 回售公告
- 其他重要公告

数据来源：
  ① 东方财富 stock_notice_report（每日全市场公告，含可转债/正股动态）
  ② 妙想 MX (东方财富官方 API) — 资讯搜索补充公告监控
     - mx-search: 关键词搜索下修/强赎/回售/评级变动等公告
     - mx-data: 自然语言查询事件进展
     - 需 MX_APIKEY 配置
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable
from enum import Enum
import asyncio
import re
import logging
import time

try:
    import akshare as ak
except ImportError:
    ak = None

logger = logging.getLogger(__name__)


class EventType(Enum):
    """事件类型"""
    DOWNSIDE_PROPOSAL = 'downside_proposal'      # 下修提案
    DOWNSIDE_RESULT = 'downside_result'          # 下修结果
    REDEMPTION_NOTICE = 'redemption_notice'      # 强赎公告
    REDEMPTION_CANCEL = 'redemption_cancel'      # 取消强赎
    PUT_NOTICE = 'put_notice'                    # 回售公告
    CONVERSION_ADJUST = 'conversion_adjust'      # 转股价调整
    INTEREST_PAYMENT = 'interest_payment'        # 利息支付
    MATURITY = 'maturity'                        # 到期
    RATINGS_CHANGE = 'ratings_change'            # 评级变化
    MAJOR_EVENT = 'major_event'                  # 重大事项


@dataclass
class BondEvent:
    """转债事件"""
    event_id: str
    event_type: EventType
    code: str
    name: str
    title: str
    content: str
    publish_time: str
    source: str
    impact_score: float  # 影响评分 -5 到 +5
    action: str  # 建议操作 buy/sell/hold/watch
    details: dict = field(default_factory=dict)


@dataclass
class EventMonitorConfig:
    """事件监控配置"""
    check_interval: int = 300  # 检查间隔（秒）
    sources: list[str] = field(default_factory=lambda: ['sse', 'szse', 'cninfo'])
    keywords: list[str] = field(default_factory=lambda: [
        '转股价', '下修', '强赎', '回售', '赎回',
        '转股', '利息', '到期', '评级',
    ])


class EventDataSource:
    """事件数据源"""

    # 事件关键词匹配规则
    EVENT_PATTERNS = {
        EventType.DOWNSIDE_PROPOSAL: [
            r'转股价.*下修.*议案',
            r'向下修正.*转股价格',
            r'董事会.*下修',
        ],
        EventType.DOWNSIDE_RESULT: [
            r'转股价.*下修.*结果',
            r'转股价格调整为',
            r'下修.*完成',
        ],
        EventType.REDEMPTION_NOTICE: [
            r'赎回.*公告',
            r'强制赎回',
            r'提前赎回',
            r'赎回登记日',
        ],
        EventType.REDEMPTION_CANCEL: [
            r'不提前赎回',
            r'取消.*赎回',
            r'放弃.*赎回',
        ],
        EventType.PUT_NOTICE: [
            r'回售.*公告',
            r'回售申报',
            r'回售价格',
        ],
        EventType.CONVERSION_ADJUST: [
            r'转股价格.*调整',
            r'转股价.*调整为',
        ],
    }

    # 事件影响评分
    IMPACT_SCORES = {
        EventType.DOWNSIDE_PROPOSAL: 2.0,
        EventType.DOWNSIDE_RESULT: 3.0,
        EventType.REDEMPTION_NOTICE: -3.0,
        EventType.REDEMPTION_CANCEL: 1.5,
        EventType.PUT_NOTICE: 1.0,
        EventType.CONVERSION_ADJUST: 1.5,
        EventType.RATINGS_CHANGE: 0.0,  # 需要具体判断
    }

    def __init__(self, config: EventMonitorConfig = None):
        self._config = config or EventMonitorConfig()
        self._subscribers: set[Callable[[BondEvent], Awaitable[None]]] = set()
        self._event_history: list[BondEvent] = []
        self._running = False
        self._last_check_time: Optional[datetime] = None

    def subscribe(self, callback: Callable[[BondEvent], Awaitable[None]]) -> None:
        """订阅事件"""
        self._subscribers.add(callback)
        logger.info(f"[EventSource] New subscriber, total: {len(self._subscribers)}")

    def unsubscribe(self, callback: Callable[[BondEvent], Awaitable[None]]) -> None:
        """取消订阅"""
        self._subscribers.discard(callback)

    async def broadcast(self, event: BondEvent) -> None:
        """广播事件"""
        self._event_history.append(event)

        tasks = []
        for callback in list(self._subscribers):
            try:
                tasks.append(callback(event))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[EventSource] Broadcast error: {e}")

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def parse_event(
        self,
        title: str,
        content: str,
        code: str,
        name: str,
        publish_time: str,
        source: str,
    ) -> Optional[BondEvent]:
        """解析公告内容，识别事件类型"""
        # 匹配事件类型
        event_type = None
        for etype, patterns in self.EVENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, title + content):
                    event_type = etype
                    break
            if event_type:
                break

        if not event_type:
            return None

        # 计算影响评分
        base_score = self.IMPACT_SCORES.get(event_type, 0)
        impact_score = self._adjust_impact_score(event_type, content, base_score)

        # 提取关键信息
        details = self._extract_details(event_type, content)

        # 确定建议操作
        action = self._determine_action(event_type, impact_score, details)

        event_id = f"{code}_{event_type.value}_{publish_time}"

        return BondEvent(
            event_id=event_id,
            event_type=event_type,
            code=code,
            name=name,
            title=title,
            content=content[:500],  # 截取前500字符
            publish_time=publish_time,
            source=source,
            impact_score=round(impact_score, 1),
            action=action,
            details=details,
        )

    def _adjust_impact_score(
        self,
        event_type: EventType,
        content: str,
        base_score: float,
    ) -> float:
        """调整影响评分"""
        score = base_score

        # 下修事件：幅度越大，影响越大
        if event_type in [EventType.DOWNSIDE_PROPOSAL, EventType.DOWNSIDE_RESULT]:
            # 提取下修幅度
            match = re.search(r'调整为(\d+\.?\d*)', content)
            if match:
                new_price = float(match.group(1))
                # 新转股价越低，影响越大
                if new_price < 10:
                    score += 1.0
                elif new_price > 20:
                    score -= 0.5

        # 强赎事件：剩余时间越短，影响越大
        elif event_type == EventType.REDEMPTION_NOTICE:
            match = re.search(r'赎回登记日.*?(\d+)月(\d+)日', content)
            if match:
                # 剩余时间短则更紧急
                score -= 1.0

        return score

    def _extract_details(self, event_type: EventType, content: str) -> dict:
        """提取事件关键信息"""
        details = {}

        # 提取转股价
        match = re.search(r'转股价格.*?(\d+\.?\d*)', content)
        if match:
            details['conversion_price'] = float(match.group(1))

        # 提取日期
        match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', content)
        if match:
            details['event_date'] = f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"

        # 提取赎回价格
        match = re.search(r'赎回价格.*?(\d+\.?\d*)', content)
        if match:
            details['redemption_price'] = float(match.group(1))

        # 提取回售价格
        match = re.search(r'回售价格.*?(\d+\.?\d*)', content)
        if match:
            details['put_price'] = float(match.group(1))

        return details

    def _determine_action(
        self,
        event_type: EventType,
        impact_score: float,
        details: dict,
    ) -> str:
        """确定建议操作"""
        if impact_score >= 2:
            return 'buy'
        elif impact_score <= -2:
            return 'sell'
        elif abs(impact_score) >= 1:
            return 'watch'
        else:
            return 'hold'

    async def start_monitoring(self) -> None:
        """启动监控"""
        self._running = True
        logger.info("[EventSource] Starting event monitoring...")

        while self._running:
            try:
                # 检查新公告
                await self._check_new_announcements()
                self._last_check_time = datetime.now()

                # 等待下次检查
                await asyncio.sleep(self._config.check_interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[EventSource] Monitoring error: {e}")
                await asyncio.sleep(60)  # 错误后等待1分钟

    async def _check_new_announcements(self) -> None:
        """从东方财富 stock_notice_report 拉取当日可转债相关公告"""
        if not ak or not hasattr(ak, 'stock_notice_report'):
            return
        try:
            from concurrent.futures import ThreadPoolExecutor
            today = datetime.now().strftime("%Y%m%d")
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=1) as ex:
                df = await loop.run_in_executor(ex, lambda: ak.stock_notice_report(symbol='全部', date=today))
            if df is None or df.empty:
                return
            for _, row in df.iterrows():
                title = str(row.get('公告标题', ''))
                code = str(row.get('代码', ''))
                name = str(row.get('名称', ''))
                publish_time = str(row.get('公告日期', ''))
                if not any(kw in title for kw in self._config.keywords):
                    continue
                if not (code.startswith('1') or code.startswith('5')):
                    continue
                content = title
                event = self._parse_announcement(content, code, name, title, publish_time, 'eastmoney')
                if event:
                    await self.broadcast(event)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"[EventSource] 公告拉取失败: {e}")
        pass

    def stop_monitoring(self) -> None:
        """停止监控"""
        self._running = False
        logger.info("[EventSource] Stopped event monitoring")

    def get_recent_events(
        self,
        hours: int = 24,
        event_types: list[EventType] = None,
    ) -> list[BondEvent]:
        """获取最近的事件"""
        cutoff = datetime.now() - timedelta(hours=hours)

        events = [
            e for e in self._event_history
            if datetime.fromisoformat(e.publish_time) >= cutoff
        ]

        if event_types:
            events = [e for e in events if e.event_type in event_types]

        return events

    def get_events_by_code(self, code: str, days: int = 30) -> list[BondEvent]:
        """获取指定转债的事件"""
        cutoff = datetime.now() - timedelta(days=days)

        return [
            e for e in self._event_history
            if e.code == code and datetime.fromisoformat(e.publish_time) >= cutoff
        ]

    def get_pending_downside_bonds(self) -> list[dict]:
        """获取待下修的转债列表"""
        events = self.get_recent_events(hours=720, event_types=[EventType.DOWNSIDE_PROPOSAL])

        # 过滤掉已经公布结果的
        result_codes = set(
            e.code for e in self.get_recent_events(hours=720, event_types=[EventType.DOWNSIDE_RESULT])
        )

        return [
            {
                'code': e.code,
                'name': e.name,
                'proposal_date': e.publish_time,
                'details': e.details,
            }
            for e in events
            if e.code not in result_codes
        ]

    def get_pending_redemption_bonds(self) -> list[dict]:
        """获取待赎回的转债列表"""
        events = self.get_recent_events(hours=720, event_types=[EventType.REDEMPTION_NOTICE])

        cancel_codes = set(
            e.code for e in self.get_recent_events(hours=720, event_types=[EventType.REDEMPTION_CANCEL])
        )

        return [
            {
                'code': e.code,
                'name': e.name,
                'notice_date': e.publish_time,
                'details': e.details,
            }
            for e in events
            if e.code not in cancel_codes
        ]


# 全局单例
_event_source: Optional[EventDataSource] = None


def get_event_source() -> EventDataSource:
    """获取全局事件数据源"""
    global _event_source
    if _event_source is None:
        _event_source = EventDataSource()
    return _event_source
