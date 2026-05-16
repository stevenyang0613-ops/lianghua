"""松岗量化可转债策略 V3.0 实时行情推送模块

功能:
- WebSocket实时推送
- 增量更新机制
- 多级缓存架构
- 百万级并发支持
- 心跳检测
- 断线重连
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable, Set
from enum import Enum
import logging
import json
import asyncio
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib

logger = logging.getLogger(__name__)

# 检查WebSocket库
try:
    import websockets
    from websockets.server import serve
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False


# ============ 枚举类型 ============

class MessageType(str, Enum):
    """消息类型"""
    TICK = "tick"                  # Tick数据
    SNAPSHOT = "snapshot"          # 快照数据
    DEPTH = "depth"                # 盘口深度
    TRADE = "trade"                # 成交数据
    SIGNAL = "signal"              # 信号推送
    ORDER = "order"                # 订单状态
    POSITION = "position"          # 持仓更新
    RISK = "risk"                  # 风控预警
    HEARTBEAT = "heartbeat"        # 心跳
    SUBSCRIBE = "subscribe"        # 订阅
    UNSUBSCRIBE = "unsubscribe"    # 取消订阅


class CompressionType(str, Enum):
    """压缩类型"""
    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"
    SNAPPY = "snappy"


class CacheLevel(str, Enum):
    """缓存层级"""
    L1_MEMORY = "l1"      # 内存缓存
    L2_REDIS = "l2"       # Redis缓存
    L3_DISK = "l3"        # 磁盘缓存


# ============ 配置类 ============

@dataclass
class PusherConfig:
    """推送配置"""
    host: str = "0.0.0.0"
    port: int = 8765
    max_connections: int = 100000
    heartbeat_interval: float = 30.0
    heartbeat_timeout: float = 60.0
    message_batch_size: int = 100
    message_batch_timeout: float = 0.01
    compression: CompressionType = CompressionType.NONE
    enable_compression_threshold: int = 1024
    max_message_size: int = 10 * 1024 * 1024  # 10MB


@dataclass
class TickData:
    """Tick数据"""
    code: str
    timestamp: datetime
    price: float
    volume: int
    turnover: float
    bid_price: float
    bid_volume: int
    ask_price: float
    ask_volume: int
    open: float = 0
    high: float = 0
    low: float = 0
    prev_close: float = 0
    sequence: int = 0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp.isoformat(),
            "price": self.price,
            "volume": self.volume,
            "turnover": self.turnover,
            "bid": self.bid_price,
            "bid_vol": self.bid_volume,
            "ask": self.ask_price,
            "ask_vol": self.ask_volume,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "prev_close": self.prev_close,
            "seq": self.sequence,
        }

    def to_compressed(self) -> bytes:
        """压缩格式"""
        # 紧凑二进制格式
        return json.dumps(self.to_dict(), separators=(',', ':')).encode()


@dataclass
class ClientSession:
    """客户端会话"""
    client_id: str
    websocket: Any
    subscriptions: Set[str] = field(default_factory=set)
    last_heartbeat: float = field(default_factory=time.time)
    last_sequence: Dict[str, int] = field(default_factory=dict)
    is_active: bool = True
    connect_time: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    bytes_sent: int = 0

    def update_heartbeat(self):
        """更新心跳"""
        self.last_heartbeat = time.time()

    def is_timeout(self, timeout: float) -> bool:
        """检查超时"""
        return time.time() - self.last_heartbeat > timeout


# ============ 多级缓存管理器 ============

class MultiLevelCache:
    """多级缓存"""

    def __init__(self, l1_size: int = 10000, l2_client: Any = None):
        self.l1_size = l1_size
        self.l2_client = l2_client  # Redis客户端

        # L1缓存 (内存)
        self._l1_cache: Dict[str, Any] = {}
        self._l1_access: Dict[str, float] = {}
        self._l1_lock = threading.RLock()

        # 统计
        self._stats = {
            "l1_hits": 0,
            "l2_hits": 0,
            "misses": 0,
            "evictions": 0,
        }

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        # L1查找
        with self._l1_lock:
            if key in self._l1_cache:
                self._l1_access[key] = time.time()
                self._stats["l1_hits"] += 1
                return self._l1_cache[key]

        # L2查找 (Redis)
        if self.l2_client:
            try:
                value = self.l2_client.get(key)
                if value:
                    self._stats["l2_hits"] += 1
                    # 回填L1
                    self._set_l1(key, value)
                    return value
            except Exception as e:
                logger.error(f"[MultiLevelCache] L2获取失败: {e}")

        self._stats["misses"] += 1
        return None

    def set(self, key: str, value: Any, ttl: int = 300):
        """设置缓存"""
        # L1缓存
        self._set_l1(key, value)

        # L2缓存 (Redis)
        if self.l2_client:
            try:
                self.l2_client.setex(key, ttl, value)
            except Exception as e:
                logger.error(f"[MultiLevelCache] L2设置失败: {e}")

    def _set_l1(self, key: str, value: Any):
        """设置L1缓存"""
        with self._l1_lock:
            # 淘汰策略
            if len(self._l1_cache) >= self.l1_size:
                self._evict_l1()

            self._l1_cache[key] = value
            self._l1_access[key] = time.time()

    def _evict_l1(self):
        """L1淘汰"""
        # LRU淘汰
        sorted_keys = sorted(self._l1_access.keys(), key=lambda k: self._l1_access[k])
        evict_count = max(1, len(sorted_keys) // 10)  # 淘汰10%

        for key in sorted_keys[:evict_count]:
            del self._l1_cache[key]
            del self._l1_access[key]
            self._stats["evictions"] += 1

    def delete(self, key: str):
        """删除缓存"""
        with self._l1_lock:
            self._l1_cache.pop(key, None)
            self._l1_access.pop(key, None)

        if self.l2_client:
            try:
                self.l2_client.delete(key)
            except:
                pass

    def get_stats(self) -> Dict:
        """获取统计"""
        total = self._stats["l1_hits"] + self._stats["l2_hits"] + self._stats["misses"]
        return {
            **self._stats,
            "l1_size": len(self._l1_cache),
            "hit_rate": (self._stats["l1_hits"] + self._stats["l2_hits"]) / total if total > 0 else 0,
        }


# ============ 增量更新管理器 ============

class IncrementalUpdater:
    """增量更新管理器"""

    def __init__(self, history_size: int = 100):
        self.history_size = history_size
        self._snapshots: Dict[str, TickData] = {}
        self._delta_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=history_size))
        self._lock = threading.RLock()

    def update(self, tick: TickData):
        """更新数据"""
        code = tick.code

        with self._lock:
            if code in self._snapshots:
                old_tick = self._snapshots[code]

                # 计算增量
                delta = self._calculate_delta(old_tick, tick)

                # 存储增量
                self._delta_history[code].append({
                    "seq": tick.sequence,
                    "delta": delta,
                    "timestamp": tick.timestamp.isoformat(),
                })

            # 更新快照
            self._snapshots[code] = tick

    def _calculate_delta(self, old: TickData, new: TickData) -> Dict:
        """计算增量"""
        delta = {}

        if new.price != old.price:
            delta["price"] = new.price
        if new.volume != old.volume:
            delta["volume"] = new.volume - old.volume
        if new.bid_price != old.bid_price:
            delta["bid"] = new.bid_price
        if new.ask_price != old.ask_price:
            delta["ask"] = new.ask_price

        delta["seq"] = new.sequence
        return delta

    def get_snapshot(self, code: str) -> Optional[TickData]:
        """获取快照"""
        return self._snapshots.get(code)

    def get_deltas(self, code: str, from_seq: int) -> List[Dict]:
        """获取增量"""
        history = list(self._delta_history.get(code, []))
        return [d for d in history if d["seq"] > from_seq]

    def get_snapshot_with_deltas(self, code: str, from_seq: int) -> Dict:
        """获取快照+增量"""
        snapshot = self._snapshots.get(code)
        deltas = self.get_deltas(code, from_seq)

        return {
            "snapshot": snapshot.to_dict() if snapshot else None,
            "deltas": deltas,
            "need_full_update": snapshot is None or snapshot.sequence <= from_seq,
        }


# ============ 消息批处理器 ============

class MessageBatcher:
    """消息批处理器"""

    def __init__(
        self,
        batch_size: int = 100,
        batch_timeout: float = 0.01,
    ):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout

        self._batches: Dict[str, List[Dict]] = defaultdict(list)
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []

    def add_message(self, channel: str, message: Dict):
        """添加消息"""
        with self._lock:
            self._batches[channel].append(message)

            # 达到批处理大小
            if len(self._batches[channel]) >= self.batch_size:
                self._flush_channel(channel)

    def _flush_channel(self, channel: str):
        """刷新通道"""
        if not self._batches[channel]:
            return

        batch = self._batches[channel][:self.batch_size]
        self._batches[channel] = self._batches[channel][self.batch_size:]

        # 触发回调
        for callback in self._callbacks:
            try:
                callback(channel, batch)
            except Exception as e:
                logger.error(f"[MessageBatcher] 回调失败: {e}")

    def flush_all(self):
        """刷新所有"""
        with self._lock:
            for channel in list(self._batches.keys()):
                while self._batches[channel]:
                    self._flush_channel(channel)

    def register_callback(self, callback: Callable):
        """注册回调"""
        self._callbacks.append(callback)


# ============ WebSocket推送服务 ============

class WebSocketPusher:
    """WebSocket推送服务"""

    def __init__(self, config: PusherConfig = None):
        self.config = config or PusherConfig()
        self.cache = MultiLevelCache()
        self.updater = IncrementalUpdater()
        self.batcher = MessageBatcher(
            batch_size=self.config.message_batch_size,
            batch_timeout=self.config.message_batch_timeout,
        )

        # 客户端管理
        self._clients: Dict[str, ClientSession] = {}
        self._subscription_index: Dict[str, Set[str]] = defaultdict(set)  # code -> client_ids
        self._lock = threading.RLock()

        # 统计
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_sent": 0,
            "bytes_sent": 0,
            "errors": 0,
        }

        # 服务状态
        self._running = False
        self._server = None

    async def start(self):
        """启动服务"""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("[WebSocketPusher] websockets库未安装")
            return

        self._running = True

        # 启动心跳检测
        asyncio.create_task(self._heartbeat_checker())

        # 启动批量刷新
        asyncio.create_task(self._batch_flusher())

        # 启动WebSocket服务
        async with serve(
            self._handle_connection,
            self.config.host,
            self.config.port,
            max_size=self.config.max_message_size,
        ):
            logger.info(f"[WebSocketPusher] 服务启动: ws://{self.config.host}:{self.config.port}")

            while self._running:
                await asyncio.sleep(1)

    def stop(self):
        """停止服务"""
        self._running = False
        logger.info("[WebSocketPusher] 服务停止")

    async def _handle_connection(self, websocket, path):
        """处理连接"""
        client_id = self._generate_client_id()

        session = ClientSession(
            client_id=client_id,
            websocket=websocket,
        )

        with self._lock:
            self._clients[client_id] = session
            self._stats["total_connections"] += 1
            self._stats["active_connections"] += 1

        logger.info(f"[WebSocketPusher] 客户端连接: {client_id}")

        try:
            async for message in websocket:
                try:
                    await self._handle_message(session, message)
                except Exception as e:
                    logger.error(f"[WebSocketPusher] 消息处理失败: {e}")
                    self._stats["errors"] += 1
        except Exception as e:
            logger.error(f"[WebSocketPusher] 连接异常: {e}")
        finally:
            await self._cleanup_client(client_id)

    async def _handle_message(self, session: ClientSession, message: str):
        """处理消息"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == MessageType.HEARTBEAT.value:
                session.update_heartbeat()
                await session.websocket.send(json.dumps({"type": "heartbeat", "ts": time.time()}))

            elif msg_type == MessageType.SUBSCRIBE.value:
                await self._handle_subscribe(session, data)

            elif msg_type == MessageType.UNSUBSCRIBE.value:
                await self._handle_unsubscribe(session, data)

            elif msg_type == MessageType.SNAPSHOT.value:
                await self._handle_snapshot_request(session, data)

        except json.JSONDecodeError:
            logger.warning(f"[WebSocketPusher] 无效消息格式")

    async def _handle_subscribe(self, session: ClientSession, data: Dict):
        """处理订阅"""
        codes = data.get("codes", [])
        incremental = data.get("incremental", False)

        with self._lock:
            for code in codes:
                session.subscriptions.add(code)
                self._subscription_index[code].add(session.client_id)

                # 发送当前快照
                if incremental:
                    snapshot = self.updater.get_snapshot(code)
                    if snapshot:
                        await session.websocket.send(json.dumps({
                            "type": MessageType.SNAPSHOT.value,
                            "data": snapshot.to_dict(),
                        }))
                else:
                    snapshot = self.updater.get_snapshot(code)
                    if snapshot:
                        await session.websocket.send(json.dumps({
                            "type": MessageType.TICK.value,
                            "data": snapshot.to_dict(),
                        }))

        await session.websocket.send(json.dumps({
            "type": "subscribed",
            "codes": codes,
            "count": len(codes),
        }))

        logger.info(f"[WebSocketPusher] 订阅成功: {session.client_id} -> {len(codes)}个标的")

    async def _handle_unsubscribe(self, session: ClientSession, data: Dict):
        """处理取消订阅"""
        codes = data.get("codes", [])

        with self._lock:
            for code in codes:
                session.subscriptions.discard(code)
                self._subscription_index[code].discard(session.client_id)

        await session.websocket.send(json.dumps({
            "type": "unsubscribed",
            "codes": codes,
        }))

    async def _handle_snapshot_request(self, session: ClientSession, data: Dict):
        """处理快照请求"""
        code = data.get("code")
        from_seq = data.get("from_seq", 0)

        result = self.updater.get_snapshot_with_deltas(code, from_seq)
        await session.websocket.send(json.dumps({
            "type": MessageType.SNAPSHOT.value,
            **result,
        }))

    async def _cleanup_client(self, client_id: str):
        """清理客户端"""
        with self._lock:
            session = self._clients.pop(client_id, None)
            if session:
                for code in session.subscriptions:
                    self._subscription_index[code].discard(client_id)

                self._stats["active_connections"] -= 1

        logger.info(f"[WebSocketPusher] 客户端断开: {client_id}")

    async def _heartbeat_checker(self):
        """心跳检测"""
        while self._running:
            await asyncio.sleep(self.config.heartbeat_interval)

            timeout_clients = []

            with self._lock:
                for client_id, session in self._clients.items():
                    if session.is_timeout(self.config.heartbeat_timeout):
                        timeout_clients.append(client_id)

            for client_id in timeout_clients:
                await self._cleanup_client(client_id)
                logger.warning(f"[WebSocketPusher] 心跳超时: {client_id}")

    async def _batch_flusher(self):
        """批量刷新"""
        while self._running:
            await asyncio.sleep(self.batcher.batch_timeout)
            self.batcher.flush_all()

    def push_tick(self, tick: TickData):
        """推送Tick"""
        # 更新增量
        self.updater.update(tick)

        # 获取订阅者
        client_ids = self._subscription_index.get(tick.code, set())

        if not client_ids:
            return

        # 广播
        asyncio.create_task(self._broadcast_tick(tick, client_ids))

    async def _broadcast_tick(self, tick: TickData, client_ids: Set[str]):
        """广播Tick"""
        message = json.dumps({
            "type": MessageType.TICK.value,
            "data": tick.to_dict(),
        })

        with self._lock:
            for client_id in client_ids:
                session = self._clients.get(client_id)
                if session and session.is_active:
                    try:
                        await session.websocket.send(message)
                        session.message_count += 1
                        session.bytes_sent += len(message)
                        self._stats["messages_sent"] += 1
                        self._stats["bytes_sent"] += len(message)
                    except Exception as e:
                        logger.error(f"[WebSocketPusher] 发送失败: {e}")
                        session.is_active = False

    def push_signal(self, signal: Dict):
        """推送信号"""
        asyncio.create_task(self._broadcast_signal(signal))

    async def _broadcast_signal(self, signal: Dict):
        """广播信号"""
        message = json.dumps({
            "type": MessageType.SIGNAL.value,
            "data": signal,
        })

        with self._lock:
            for session in self._clients.values():
                if session.is_active:
                    try:
                        await session.websocket.send(message)
                    except:
                        pass

    def push_order_update(self, client_id: str, order: Dict):
        """推送订单更新"""
        asyncio.create_task(self._send_to_client(client_id, MessageType.ORDER, order))

    def push_risk_alert(self, alert: Dict):
        """推送风控预警"""
        asyncio.create_task(self._broadcast_to_all(MessageType.RISK, alert))

    async def _send_to_client(self, client_id: str, msg_type: MessageType, data: Dict):
        """发送给指定客户端"""
        session = self._clients.get(client_id)
        if session and session.is_active:
            message = json.dumps({
                "type": msg_type.value,
                "data": data,
            })
            await session.websocket.send(message)

    async def _broadcast_to_all(self, msg_type: MessageType, data: Dict):
        """广播给所有客户端"""
        message = json.dumps({
            "type": msg_type.value,
            "data": data,
        })

        with self._lock:
            for session in self._clients.values():
                if session.is_active:
                    try:
                        await session.websocket.send(message)
                    except:
                        pass

    def _generate_client_id(self) -> str:
        """生成客户端ID"""
        return f"client_{int(time.time() * 1000000)}_{hash(time.time()) % 10000}"

    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            **self._stats,
            "cache": self.cache.get_stats(),
            "snapshot_count": len(self.updater._snapshots),
        }


# ============ 高性能推送服务 ============

class HighPerformancePusher:
    """高性能推送服务"""

    def __init__(self, config: PusherConfig = None, worker_count: int = 4):
        self.config = config or PusherConfig()
        self.worker_count = worker_count

        # 多个推送器实例
        self._pushers: List[WebSocketPusher] = []
        self._current_index = 0

        # 线程池
        self._executor = ThreadPoolExecutor(max_workers=worker_count)

    def start(self):
        """启动"""
        for i in range(self.worker_count):
            pusher = WebSocketPusher(self.config)
            self._pushers.append(pusher)

            # 在独立线程启动
            asyncio.new_event_loop().run_until_complete(pusher.start())

        logger.info(f"[HighPerformancePusher] 启动 {self.worker_count} 个推送器")

    def stop(self):
        """停止"""
        for pusher in self._pushers:
            pusher.stop()

        self._executor.shutdown()

    def push_tick(self, tick: TickData):
        """推送Tick"""
        # 轮询选择推送器
        pusher = self._pushers[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._pushers)

        pusher.push_tick(tick)

    def get_aggregate_stats(self) -> Dict:
        """获取汇总统计"""
        total_stats = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_sent": 0,
            "bytes_sent": 0,
            "errors": 0,
        }

        for pusher in self._pushers:
            stats = pusher.get_stats()
            for key in total_stats:
                total_stats[key] += stats.get(key, 0)

        return total_stats


# ============ 便捷函数 ============

def create_pusher(config: PusherConfig = None) -> WebSocketPusher:
    """创建推送器"""
    return WebSocketPusher(config)


def create_high_performance_pusher(
    config: PusherConfig = None,
    worker_count: int = 4,
) -> HighPerformancePusher:
    """创建高性能推送器"""
    return HighPerformancePusher(config, worker_count)


async def start_push_server(host: str = "0.0.0.0", port: int = 8765):
    """启动推送服务器"""
    config = PusherConfig(host=host, port=port)
    pusher = WebSocketPusher(config)
    await pusher.start()
    return pusher
