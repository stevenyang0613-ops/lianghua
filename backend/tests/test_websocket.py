"""Tests for WebSocket module"""
import pytest
import asyncio
import json
import math
from unittest.mock import MagicMock, AsyncMock, patch

from app.api.websocket import (
    MessageType, WSMessage, ClientInfo, ConnectionManager,
    RealtimeQuotePusher, AlertPusher, SignalPusher,
)


class TestWSMessage:
    """WebSocket消息测试"""

    def test_message_creation(self):
        """测试消息创建"""
        msg = WSMessage(
            type=MessageType.QUOTE,
            data={'code': '123456', 'price': 100.0},
        )

        assert msg.type == MessageType.QUOTE
        assert msg.data['code'] == '123456'
        assert msg.timestamp is not None

    def test_message_to_json(self):
        """测试消息JSON序列化"""
        msg = WSMessage(
            type=MessageType.ALERT,
            data={'level': 'warning', 'message': 'test'},
        )

        json_str = msg.to_json()
        parsed = json.loads(json_str)

        assert parsed['type'] == 'alert'
        assert parsed['data']['level'] == 'warning'
        assert 'timestamp' in parsed


class TestConnectionManager:
    """连接管理器测试"""

    def test_manager_initialization(self):
        """测试管理器初始化"""
        manager = ConnectionManager()
        assert manager.active_connections == 0
        assert manager._max_connections == 1000

    @pytest.mark.asyncio
    async def test_connect_client(self):
        """测试客户端连接"""
        manager = ConnectionManager(max_connections=10)

        websocket = AsyncMock()
        websocket.accept = AsyncMock()

        result = await manager.connect(websocket, 'client1')

        assert result is True
        assert manager.active_connections == 1

    @pytest.mark.asyncio
    async def test_max_connections_limit(self):
        """测试最大连接数限制"""
        manager = ConnectionManager(max_connections=2)

        # 连接两个客户端
        for i in range(2):
            ws = AsyncMock()
            ws.accept = AsyncMock()
            await manager.connect(ws, f'client{i}')

        # 第三个应被拒绝
        ws3 = AsyncMock()
        result = await manager.connect(ws3, 'client3')
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_client(self):
        """测试客户端断开"""
        manager = ConnectionManager()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        await manager.connect(ws, 'client1')

        await manager.disconnect('client1')

        assert manager.active_connections == 0

    @pytest.mark.asyncio
    async def test_subscribe_codes(self):
        """测试订阅代码"""
        manager = ConnectionManager()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        await manager.connect(ws, 'client1')

        await manager.subscribe('client1', codes=['123456', '123457'])

        assert '123456' in manager._clients['client1'].subscriptions
        assert '123457' in manager._clients['client1'].subscriptions

    @pytest.mark.asyncio
    async def test_subscribe_message_types(self):
        """测试订阅消息类型"""
        manager = ConnectionManager()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        await manager.connect(ws, 'client1')

        await manager.subscribe('client1', message_types=[MessageType.ALERT, MessageType.SIGNAL])

        client = manager._clients['client1']
        assert MessageType.ALERT in client.subscribed_types
        assert MessageType.SIGNAL in client.subscribed_types

    @pytest.mark.asyncio
    async def test_broadcast_message(self):
        """测试广播消息"""
        manager = ConnectionManager()

        # 连接多个客户端并订阅消息类型
        clients = []
        for i in range(3):
            ws = AsyncMock()
            ws.accept = AsyncMock()
            ws.send_text = AsyncMock()
            await manager.connect(ws, f'client{i}')
            await manager.subscribe(f'client{i}', message_types=[MessageType.SYSTEM])
            clients.append(ws)

        msg = WSMessage(type=MessageType.SYSTEM, data={'test': 'broadcast'})

        count = await manager.broadcast(msg)

        assert count == 3
        for ws in clients:
            ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_with_code_filter(self):
        """测试带代码过滤的广播"""
        manager = ConnectionManager()

        # 客户端1订阅123456
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()
        await manager.connect(ws1, 'client1')
        await manager.subscribe('client1', codes=['123456'])

        # 客户端2订阅其他代码
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()
        await manager.connect(ws2, 'client2')
        await manager.subscribe('client2', codes=['789012'])

        msg = WSMessage(type=MessageType.QUOTE, data={'code': '123456'})

        count = await manager.broadcast(msg, codes=['123456'])

        # 只有订阅了123456的客户端应收到
        assert count == 1
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_not_called()


class TestRealtimeQuotePusher:
    """实时行情推送器测试"""

    def test_quote_changed_detection(self):
        """测试行情变化检测"""
        pusher = RealtimeQuotePusher()

        old = {'price': 100.0, 'volume': 1000}
        new = {'price': 100.0, 'volume': 1000}

        # 无变化
        assert not pusher._quote_changed(old, new)

        # 价格变化
        new['price'] = 100.5
        assert pusher._quote_changed(old, new)

        # 成交量变化
        new['price'] = 100.0
        new['volume'] = 2000
        assert pusher._quote_changed(old, new)

    @pytest.mark.asyncio
    async def test_push_only_changed_quotes(self):
        """测试只推送有变化的行情"""
        manager = ConnectionManager()
        pusher = RealtimeQuotePusher(manager)

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        await manager.connect(ws, 'client1')
        await manager.subscribe('client1', codes=['123456'])

        # 第一次推送
        quotes = [{'code': '123456', 'price': 100.0, 'volume': 1000}]
        count = await pusher.push_quotes(quotes)
        assert count == 1

        # 相同数据再次推送
        count = await pusher.push_quotes(quotes)
        assert count == 0  # 无变化，不推送


class TestAlertPusher:
    """告警推送器测试"""

    @pytest.mark.asyncio
    async def test_push_single_alert(self):
        """测试推送单个告警"""
        manager = ConnectionManager()
        pusher = AlertPusher(manager)

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        await manager.connect(ws, 'client1')
        await manager.subscribe('client1', message_types=[MessageType.ALERT])

        alert = {'level': 'warning', 'code': '123456', 'message': 'test'}
        count = await pusher.push_alert(alert)

        assert count == 1
        ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_multiple_alerts(self):
        """测试推送多个告警"""
        manager = ConnectionManager()
        pusher = AlertPusher(manager)

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        await manager.connect(ws, 'client1')
        await manager.subscribe('client1', message_types=[MessageType.ALERT])

        alerts = [
            {'level': 'warning', 'message': 'alert1'},
            {'level': 'error', 'message': 'alert2'},
        ]
        count = await pusher.push_alerts(alerts)

        assert count == 1


class TestSignalPusher:
    """信号推送器测试"""

    @pytest.mark.asyncio
    async def test_push_signal(self):
        """测试推送信号"""
        manager = ConnectionManager()
        pusher = SignalPusher(manager)

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        await manager.connect(ws, 'client1')
        await manager.subscribe('client1', codes=['123456'], message_types=[MessageType.SIGNAL])

        signal = {'code': '123456', 'action': 'buy', 'price': 100.0}
        count = await pusher.push_signal(signal)

        assert count == 1

    @pytest.mark.asyncio
    async def test_push_signals_to_subscribers(self):
        """测试推送给订阅者"""
        manager = ConnectionManager()
        pusher = SignalPusher(manager)

        # 两个客户端订阅不同代码和消息类型
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()
        await manager.connect(ws1, 'client1')
        await manager.subscribe('client1', codes=['123456'], message_types=[MessageType.SIGNAL])

        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()
        await manager.connect(ws2, 'client2')
        await manager.subscribe('client2', codes=['789012'], message_types=[MessageType.SIGNAL])

        signals = [
            {'code': '123456', 'action': 'buy'},
            {'code': '789012', 'action': 'sell'},
        ]

        count = await pusher.push_signals(signals)

        # 两个客户端都应收到（广播消息）
        assert count == 2
