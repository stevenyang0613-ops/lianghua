"""松岗量化可转债策略 V3.0 WebSocket推送模块

功能:
- WebSocket连接管理
- 行情订阅推送
- 信号实时推送
- 持仓变更推送
- 心跳保活
- 广播机制
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Set, Callable
from enum import Enum
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from fastapi import Depends

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class MessageType(str, Enum):
    """消息类型"""
    # 连接管理
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    HEARTBEAT = "heartbeat"
    PONG = "pong"

    # 订阅
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    SUBSCRIBED = "subscribed"

    # 数据推送
    QUOTE = "quote"           # 行情
    SIGNAL = "signal"         # 信号
    POSITION = "position"     # 持仓
    PORTFOLIO = "portfolio"   # 组合
    ALERT = "alert"           # 告警
    TRADE = "trade"           # 成交

    # 系统消息
    ERROR = "error"
    INFO = "info"


class ChannelType(str, Enum):
    """频道类型"""
    ALL_QUOTES = "all_quotes"         # 所有行情
    QUOTE_PREFIX = "quote:"           # 单只行情 quote:110001
    ALL_SIGNALS = "all_signals"       # 所有信号
    ALL_POSITIONS = "all_positions"   # 所有持仓
    PORTFOLIO = "portfolio"           # 组合信息
    ALL_ALERTS = "all_alerts"         # 所有告警


# ============ 数据模型 ============

@dataclass
class WSMessage:
    """WebSocket消息"""
    type: MessageType
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id,
        }, ensure_ascii=False, default=str)


@dataclass
class WSClient:
    """WebSocket客户端"""
    client_id: str
    websocket: WebSocket
    subscriptions: Set[str] = field(default_factory=set)
    connected_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    is_active: bool = True

    async def send(self, message: WSMessage):
        """发送消息"""
        if not self.is_active:
            return

        try:
            await self.websocket.send_text(message.to_json())
            self.message_count += 1
        except Exception as e:
            logger.error(f"[WSClient] 发送失败: {e}")
            self.is_active = False

    async def send_json(self, data: dict):
        """发送JSON数据"""
        await self.send(WSMessage(
            type=MessageType.INFO,
            data=data,
        ))

    def subscribe(self, channel: str):
        """订阅频道"""
        self.subscriptions.add(channel)

    def unsubscribe(self, channel: str):
        """取消订阅"""
        self.subscriptions.discard(channel)

    def is_subscribed(self, channel: str) -> bool:
        """检查是否订阅"""
        if channel in self.subscriptions:
            return True
        # 检查通配符订阅
        if ChannelType.ALL_QUOTES.value in self.subscriptions and channel.startswith(ChannelType.QUOTE_PREFIX.value):
            return True
        return False


# ============ WebSocket连接管理器 ============

class ConnectionManager:
    """WebSocket连接管理器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._clients: Dict[str, WSClient] = {}
        self._channel_subscribers: Dict[str, Set[str]] = defaultdict(set)
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._broadcast_queue: asyncio.Queue = None
        self._running = False

        self._initialized = True

    async def connect(self, websocket: WebSocket) -> WSClient:
        """接受连接"""
        await websocket.accept()

        client_id = str(uuid.uuid4())[:8]
        client = WSClient(
            client_id=client_id,
            websocket=websocket,
        )

        self._clients[client_id] = client

        # 发送连接成功消息
        await client.send(WSMessage(
            type=MessageType.CONNECT,
            data={"client_id": client_id},
        ))

        logger.info(f"[WS] 客户端连接: {client_id}, 当前连接数: {len(self._clients)}")
        return client

    def disconnect(self, client_id: str):
        """断开连接"""
        if client_id in self._clients:
            client = self._clients[client_id]
            client.is_active = False

            # 清理订阅
            for channel in client.subscriptions:
                self._channel_subscribers[channel].discard(client_id)

            del self._clients[client_id]
            logger.info(f"[WS] 客户端断开: {client_id}, 当前连接数: {len(self._clients)}")

    async def subscribe(self, client_id: str, channel: str):
        """订阅频道"""
        if client_id not in self._clients:
            return

        client = self._clients[client_id]
        client.subscribe(channel)
        self._channel_subscribers[channel].add(client_id)

        await client.send(WSMessage(
            type=MessageType.SUBSCRIBED,
            data={"channel": channel},
        ))

        logger.debug(f"[WS] {client_id} 订阅 {channel}")

    async def unsubscribe(self, client_id: str, channel: str):
        """取消订阅"""
        if client_id not in self._clients:
            return

        client = self._clients[client_id]
        client.unsubscribe(channel)
        self._channel_subscribers[channel].discard(client_id)

        logger.debug(f"[WS] {client_id} 取消订阅 {channel}")

    async def send_to_client(self, client_id: str, message: WSMessage):
        """发送给指定客户端"""
        if client_id in self._clients:
            await self._clients[client_id].send(message)

    async def broadcast(self, message: WSMessage, channel: str = None):
        """广播消息"""
        if channel:
            # 发送给订阅了指定频道的客户端
            subscriber_ids = self._channel_subscribers.get(channel, set())
            for client_id in subscriber_ids:
                client = self._clients.get(client_id)
                if client and client.is_active and client.is_subscribed(channel):
                    await client.send(message)
        else:
            # 广播给所有客户端
            for client in list(self._clients.values()):
                if client.is_active:
                    await client.send(message)

    async def broadcast_quote(self, code: str, quote_data: dict):
        """广播行情"""
        message = WSMessage(
            type=MessageType.QUOTE,
            data={"code": code, **quote_data},
        )

        # 发送给订阅了该代码行情的客户端
        channel = f"{ChannelType.QUOTE_PREFIX.value}{code}"
        await self.broadcast(message, channel)

        # 也发送给订阅了所有行情的客户端
        await self.broadcast(message, ChannelType.ALL_QUOTES.value)

    async def broadcast_quotes(self, quotes: Dict[str, dict]):
        """批量广播行情"""
        for code, data in quotes.items():
            await self.broadcast_quote(code, data)

    async def broadcast_signal(self, signal: dict):
        """广播信号"""
        message = WSMessage(
            type=MessageType.SIGNAL,
            data=signal,
        )
        await self.broadcast(message, ChannelType.ALL_SIGNALS.value)

    async def broadcast_position(self, position: dict):
        """广播持仓变更"""
        message = WSMessage(
            type=MessageType.POSITION,
            data=position,
        )
        await self.broadcast(message, ChannelType.ALL_POSITIONS.value)

    async def broadcast_portfolio(self, portfolio: dict):
        """广播组合信息"""
        message = WSMessage(
            type=MessageType.PORTFOLIO,
            data=portfolio,
        )
        await self.broadcast(message, ChannelType.PORTFOLIO.value)

    async def broadcast_alert(self, alert: dict):
        """广播告警"""
        message = WSMessage(
            type=MessageType.ALERT,
            data=alert,
        )
        await self.broadcast(message, ChannelType.ALL_ALERTS.value)

    async def handle_message(self, client_id: str, message: dict):
        """处理客户端消息"""
        client = self._clients.get(client_id)
        if not client:
            return

        msg_type = message.get("type")

        if msg_type == MessageType.SUBSCRIBE.value:
            channel = message.get("channel")
            if channel:
                await self.subscribe(client_id, channel)

        elif msg_type == MessageType.UNSUBSCRIBE.value:
            channel = message.get("channel")
            if channel:
                await self.unsubscribe(client_id, channel)

        elif msg_type == MessageType.HEARTBEAT.value:
            client.last_heartbeat = datetime.now()
            await client.send(WSMessage(type=MessageType.PONG))

        elif msg_type in self._message_handlers:
            handler = self._message_handlers[MessageType(msg_type)]
            await handler(client_id, message)

    def register_handler(self, msg_type: MessageType, handler: Callable):
        """注册消息处理器"""
        self._message_handlers[msg_type] = handler

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_connections": len(self._clients),
            "active_connections": sum(1 for c in self._clients.values() if c.is_active),
            "channels": {ch: len(subs) for ch, subs in self._channel_subscribers.items()},
            "total_messages": sum(c.message_count for c in self._clients.values()),
        }

    async def start_heartbeat_check(self, interval: int = 60):
        """启动心跳检查"""
        while self._running:
            await asyncio.sleep(interval)

            now = datetime.now()
            for client_id, client in list(self._clients.items()):
                # 检查心跳超时
                if (now - client.last_heartbeat).total_seconds() > interval * 3:
                    logger.warning(f"[WS] 客户端心跳超时: {client_id}")
                    client.is_active = False

    async def start_broadcast_loop(self):
        """启动广播循环"""
        self._running = True
        self._broadcast_queue = asyncio.Queue()

        while self._running:
            try:
                message, channel = await asyncio.wait_for(
                    self._broadcast_queue.get(),
                    timeout=1.0,
                )
                await self.broadcast(message, channel)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[WS] 广播失败: {e}")

    def stop(self):
        """停止"""
        self._running = False


# ============ 行情推送服务 ============

class QuotePushService:
    """行情推送服务"""

    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self._running = False
        self._quote_cache: Dict[str, dict] = {}
        self._last_push: Dict[str, float] = {}

    async def start(self, interval: float = 1.0):
        """启动推送服务"""
        self._running = True

        while self._running:
            try:
                # 获取最新行情
                quotes = await self._fetch_quotes()

                # 推送变更
                for code, quote in quotes.items():
                    last_push = self._last_push.get(code, 0)
                    now = time.time()

                    # 检查是否有变更或超过推送间隔
                    cached = self._quote_cache.get(code, {})
                    if quote != cached or now - last_push > 30:
                        await self.manager.broadcast_quote(code, quote)
                        self._quote_cache[code] = quote
                        self._last_push[code] = now

                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"[QuotePush] 推送失败: {e}")
                await asyncio.sleep(1)

    async def _fetch_quotes(self) -> Dict[str, dict]:
        """获取行情数据 - 从 AKShare 获取真实行情"""
        try:
            import akshare as ak
            df = ak.bond_zh_hs_cov_spot()
            result = {}
            for _, r in df.iterrows():
                code = str(r.get("code", "")).strip()
                if code and len(code) == 6 and code[0] in '12':
                    trade = float(r.get("trade", 0) or 0)
                    if trade > 0:
                        result[code] = {
                            "price": trade,
                            "change_pct": float(r.get("changepercent", 0) or 0),
                            "volume": int(r.get("volume", 0) or 0),
                            "amount": float(r.get("amount", 0) or 0),
                        }
            return result
        except Exception as e:
            logger.error(f"[QuotePush] 获取行情失败: {e}")
            return {}

    def stop(self):
        """停止"""
        self._running = False

    def push_quote(self, code: str, quote: dict):
        """手动推送行情"""
        asyncio.create_task(self.manager.broadcast_quote(code, quote))


# ============ 信号推送服务 ============

class SignalPushService:
    """信号推送服务"""

    def __init__(self, manager: ConnectionManager):
        self.manager = manager

    async def push_signal(self, signal: dict):
        """推送信号"""
        await self.manager.broadcast_signal(signal)

    async def push_signals(self, signals: List[dict]):
        """批量推送信号"""
        for signal in signals:
            await self.push_signal(signal)


# ============ FastAPI WebSocket路由 ============

def get_connection_manager() -> ConnectionManager:
    """获取连接管理器"""
    return ConnectionManager()


async def websocket_endpoint(
    websocket: WebSocket,
    manager: ConnectionManager = Depends(get_connection_manager),
):
    """WebSocket端点"""
    client = await manager.connect(websocket)

    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                await manager.handle_message(client.client_id, message)
            except json.JSONDecodeError:
                await client.send(WSMessage(
                    type=MessageType.ERROR,
                    data={"message": "无效的JSON格式"},
                ))

    except WebSocketDisconnect:
        manager.disconnect(client.client_id)
    except Exception as e:
        logger.error(f"[WS] 异常: {e}")
        manager.disconnect(client.client_id)


# ============ 便捷函数 ============

def get_ws_manager() -> ConnectionManager:
    """获取WebSocket管理器"""
    return ConnectionManager()
