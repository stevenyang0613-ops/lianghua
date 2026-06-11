"""
WebSocket实时推送模块

提供实时行情、告警、信号推送功能
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Set, Any, Callable
from enum import Enum
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型"""
    QUOTE = 'quote'           # 实时行情
    ALERT = 'alert'           # 告警
    SIGNAL = 'signal'         # 策略信号
    PORTFOLIO = 'portfolio'   # 组合更新
    SYSTEM = 'system'         # 系统消息
    HEARTBEAT = 'heartbeat'   # 心跳
    REVISION = 'revision'     # 下修事件


@dataclass
class WSMessage:
    """WebSocket消息"""
    type: MessageType
    data: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_json(self) -> str:
        return json.dumps({
            'type': self.type.value,
            'data': self.data,
            'timestamp': self.timestamp,
        })


@dataclass
class ClientInfo:
    """客户端信息"""
    websocket: WebSocket
    client_id: str
    subscriptions: Set[str] = field(default_factory=set)  # 订阅的代码
    subscribed_types: Set[MessageType] = field(default_factory=lambda: {MessageType.QUOTE})
    last_heartbeat: datetime = field(default_factory=datetime.now)
    is_active: bool = True


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self, max_connections: int = 1000, heartbeat_interval: int = 30):
        self._clients: Dict[str, ClientInfo] = {}
        self._max_connections = max_connections
        self._heartbeat_interval = heartbeat_interval
        self._message_handlers: Dict[MessageType, List[Callable]] = {
            msg_type: [] for msg_type in MessageType
        }
        self._lock = asyncio.Lock()

    @property
    def active_connections(self) -> int:
        """活跃连接数"""
        return sum(1 for c in self._clients.values() if c.is_active)

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """接受新连接"""
        async with self._lock:
            if len(self._clients) >= self._max_connections:
                logger.warning(f"[WS] 达到最大连接数 {self._max_connections}")
                return False

            await websocket.accept()
            self._clients[client_id] = ClientInfo(
                websocket=websocket,
                client_id=client_id,
            )
            logger.info(f"[WS] 客户端连接: {client_id}, 当前连接数: {len(self._clients)}")
            return True

    async def disconnect(self, client_id: str) -> None:
        """断开连接"""
        async with self._lock:
            if client_id in self._clients:
                self._clients[client_id].is_active = False
                del self._clients[client_id]
                logger.info(f"[WS] 客户端断开: {client_id}, 当前连接数: {len(self._clients)}")

    async def subscribe(
        self,
        client_id: str,
        codes: List[str] = None,
        message_types: List[MessageType] = None,
    ) -> None:
        """订阅"""
        async with self._lock:
            if client_id not in self._clients:
                return

            client = self._clients[client_id]
            if codes:
                client.subscriptions.update(codes)
            if message_types:
                client.subscribed_types.update(message_types)

            logger.debug(f"[WS] {client_id} 订阅: codes={codes}, types={[t.value for t in message_types] if message_types else None}")

    async def unsubscribe(
        self,
        client_id: str,
        codes: List[str] = None,
        message_types: List[MessageType] = None,
    ) -> None:
        """取消订阅"""
        async with self._lock:
            if client_id not in self._clients:
                return

            client = self._clients[client_id]
            if codes:
                client.subscriptions.difference_update(codes)
            if message_types:
                client.subscribed_types.difference_update(message_types)

    async def broadcast(self, message: WSMessage, codes: List[str] = None) -> int:
        """广播消息"""
        sent_count = 0
        dead_clients = []

        async with self._lock:
            clients_snapshot = dict(self._clients)

        for client_id, client in clients_snapshot.items():
            if not client.is_active:
                continue

            # 检查消息类型订阅
            if message.type not in client.subscribed_types:
                continue

            # 检查代码订阅（如果有）
            if codes and message.type == MessageType.QUOTE:
                if not client.subscriptions.intersection(codes):
                    continue

            try:
                await client.websocket.send_text(message.to_json())
                sent_count += 1
            except Exception as e:
                logger.warning(f"[WS] 发送失败 {client_id}: {e}")
                dead_clients.append(client_id)

        # 清理断开的连接
        for client_id in dead_clients:
            await self.disconnect(client_id)

        return sent_count

    async def send_to_client(self, client_id: str, message: WSMessage) -> bool:
        """发送给特定客户端"""
        async with self._lock:
            if client_id not in self._clients:
                return False

            client = self._clients[client_id]
            if not client.is_active:
                return False

            try:
                await client.websocket.send_text(message.to_json())
                return True
            except Exception as e:
                logger.warning(f"[WS] 发送失败 {client_id}: {e}")
                return False

    async def handle_client_message(self, client_id: str, message: str) -> None:
        """处理客户端消息"""
        try:
            data = json.loads(message)
            action = data.get('action')

            if action == 'subscribe':
                codes = data.get('codes', [])
                types = [MessageType(t) for t in data.get('types', ['quote'])]
                await self.subscribe(client_id, codes, types)
                await self.send_to_client(client_id, WSMessage(
                    type=MessageType.SYSTEM,
                    data={'status': 'subscribed', 'codes': codes, 'types': [t.value for t in types]},
                ))

            elif action == 'unsubscribe':
                codes = data.get('codes', [])
                types = [MessageType(t) for t in data.get('types', [])]
                await self.unsubscribe(client_id, codes, types)
                await self.send_to_client(client_id, WSMessage(
                    type=MessageType.SYSTEM,
                    data={'status': 'unsubscribed'},
                ))

            elif action == 'heartbeat':
                async with self._lock:
                    if client_id in self._clients:
                        self._clients[client_id].last_heartbeat = datetime.now()
                await self.send_to_client(client_id, WSMessage(
                    type=MessageType.HEARTBEAT,
                    data={'status': 'ok'},
                ))

        except json.JSONDecodeError:
            logger.warning(f"[WS] 无效JSON消息: {message[:100]}")
        except Exception as e:
            logger.error(f"[WS] 处理消息错误: {e}")

    async def cleanup_stale_connections(self, timeout_seconds: int = 60) -> int:
        """清理过期连接"""
        now = datetime.now()
        stale_clients = []

        for client_id, client in self._clients.items():
            if (now - client.last_heartbeat).total_seconds() > timeout_seconds:
                stale_clients.append(client_id)

        for client_id in stale_clients:
            await self.disconnect(client_id)

        return len(stale_clients)


# 全局连接管理器
_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """获取全局连接管理器"""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


class RealtimeQuotePusher:
    """实时行情推送器"""

    def __init__(self, manager: ConnectionManager = None):
        self.manager = manager or get_connection_manager()
        self._last_quotes: Dict[str, Dict] = {}

    async def push_quotes(self, quotes: List[Dict]) -> int:
        """推送行情更新"""
        updated_codes = []

        for quote in quotes:
            code = quote.get('code')
            if not code:
                continue

            # 检查是否有变化
            last = self._last_quotes.get(code, {})
            if self._quote_changed(last, quote):
                updated_codes.append(code)
                self._last_quotes[code] = quote

        if not updated_codes:
            return 0

        # 只推送有变化的行情
        changed_quotes = [self._last_quotes[c] for c in updated_codes]
        message = WSMessage(
            type=MessageType.QUOTE,
            data={'quotes': changed_quotes, 'count': len(changed_quotes)},
        )

        return await self.manager.broadcast(message, updated_codes)

    def _quote_changed(self, old: Dict, new: Dict, threshold: float = 0.0001) -> bool:
        """检查行情是否有变化"""
        if not old:
            return True

        # 价格变化超过阈值
        old_price = old.get('price', 0)
        new_price = new.get('price', 0)
        if abs(new_price - old_price) / max(old_price, 1) > threshold:
            return True

        # 成交量变化
        old_vol = old.get('volume', 0)
        new_vol = new.get('volume', 0)
        if new_vol != old_vol:
            return True

        return False


class AlertPusher:
    """告警推送器"""

    def __init__(self, manager: ConnectionManager = None):
        self.manager = manager or get_connection_manager()

    async def push_alert(self, alert: Dict) -> int:
        """推送告警"""
        message = WSMessage(
            type=MessageType.ALERT,
            data=alert,
        )
        return await self.manager.broadcast(message)

    async def push_alerts(self, alerts: List[Dict]) -> int:
        """推送多个告警"""
        message = WSMessage(
            type=MessageType.ALERT,
            data={'alerts': alerts, 'count': len(alerts)},
        )
        return await self.manager.broadcast(message)


class SignalPusher:
    """策略信号推送器"""

    def __init__(self, manager: ConnectionManager = None):
        self.manager = manager or get_connection_manager()

    async def push_signal(self, signal: Dict) -> int:
        """推送信号"""
        message = WSMessage(
            type=MessageType.SIGNAL,
            data=signal,
        )
        codes = [signal.get('code')] if signal.get('code') else None
        return await self.manager.broadcast(message, codes)

    async def push_signals(self, signals: List[Dict]) -> int:
        """推送多个信号"""
        message = WSMessage(
            type=MessageType.SIGNAL,
            data={'signals': signals, 'count': len(signals)},
        )
        codes = list(set(s.get('code') for s in signals if s.get('code')))
        return await self.manager.broadcast(message, codes)


# WebSocket路由处理
async def websocket_handler(websocket: WebSocket, client_id: str):
    """WebSocket处理函数"""
    manager = get_connection_manager()

    if not await manager.connect(websocket, client_id):
        await websocket.close(code=1013, reason="Server busy")
        return

    try:
        # 发送欢迎消息
        await manager.send_to_client(client_id, WSMessage(
            type=MessageType.SYSTEM,
            data={'status': 'connected', 'client_id': client_id},
        ))

        # 消息循环
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0,
                )
                await manager.handle_client_message(client_id, message)
            except asyncio.TimeoutError:
                # 发送心跳检测
                await manager.send_to_client(client_id, WSMessage(
                    type=MessageType.HEARTBEAT,
                    data={'status': 'ping'},
                ))

    except WebSocketDisconnect:
        logger.info(f"[WS] 客户端主动断开: {client_id}")
    except Exception as e:
        logger.error(f"[WS] 连接错误 {client_id}: {e}")
    finally:
        await manager.disconnect(client_id)
