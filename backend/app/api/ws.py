import asyncio
import gzip
import json
import logging
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

active_market_connections = 0
active_signal_connections = 0

# 消息统计
_STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ws_stats.json")

_ws_stats = {
    "market_messages_sent": 0,
    "market_bytes_sent": 0,
    "signal_messages_sent": 0,
    "signal_bytes_sent": 0,
    "market_delta_messages": 0,
    "market_full_messages": 0,
    "disconnect_reasons": {
        "client_close": 0,
        "send_error": 0,
        "receive_error": 0,
        "heartbeat_timeout": 0,
        "auth_failed": 0,
        "engine_unavailable": 0,
        "connection_limit": 0,
        "unknown": 0,
    },
}


def _load_stats():
    """启动时从文件恢复统计"""
    global _ws_stats
    try:
        if os.path.exists(_STATS_FILE):
            with open(_STATS_FILE, "r") as f:
                saved = json.load(f)
                # 深度合并 disconnect_reasons，保留新增的默认键
                if "disconnect_reasons" in saved:
                    _ws_stats["disconnect_reasons"].update(saved.pop("disconnect_reasons"))
                _ws_stats.update(saved)
                logger.info(f"[WS] Restored stats from {_STATS_FILE}")
    except Exception as e:
        logger.warning(f"[WS] Failed to load stats: {e}")


def _save_stats():
    """定时保存统计到文件"""
    try:
        os.makedirs(os.path.dirname(_STATS_FILE), exist_ok=True)
        with open(_STATS_FILE, "w") as f:
            json.dump(_ws_stats, f)
    except Exception as e:
        logger.warning(f"[WS] Failed to save stats: {e}")


_load_stats()

# WebSocket 管理器 - 用于跨模块广播
class WSManager:
    """简单的 WebSocket 管理器，用于从非请求上下文广播消息"""
    def __init__(self):
        self._subscribers: list = []

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def unsubscribe(self, callback):
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    async def broadcast(self, message):
        for callback in self._subscribers:
            try:
                await callback(message)
            except Exception as e:
                logger.warning(f"[WSManager] broadcast error: {e}")

ws_manager = WSManager()


def broadcast_revision(record: dict):
    """从同步上下文广播转股价下修事件到 WebSocket 客户端"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    ws_manager.broadcast({"type": "revision", "data": record})
                )
            )
        else:
            # loop 存在但不在运行（shutdown中），安全丢弃
            logger.debug("[WS] Skipping revision broadcast: event loop not running")
    except RuntimeError:
        logger.debug("[WS] No event loop available for revision broadcast")


async def _stats_persistence_loop():
    """每60秒保存一次统计到文件"""
    while True:
        await asyncio.sleep(60)
        _save_stats()

# 在模块加载时启动持久化任务（由 lifespan 中的 event loop 调度）
_stats_task: asyncio.Task | None = None


def start_stats_persistence():
    """在事件循环中启动统计持久化任务"""
    global _stats_task
    if _stats_task is None or _stats_task.done():
        _stats_task = asyncio.ensure_future(_stats_persistence_loop())


@router.get("/stats")
async def get_ws_stats(request: Request):
    """获取 WebSocket 连接和消息统计"""
    return {
        "connections": {
            "market": active_market_connections,
            "signals": active_signal_connections,
            "total": active_market_connections + active_signal_connections,
        },
        "messages": _ws_stats,
    }


async def verify_ws_auth(websocket: WebSocket) -> bool:
    """Verify WebSocket authentication token and connection limits."""
    token = websocket.query_params.get("token", "")
    if not token:
        logger.warning("[WS] Auth rejected: empty token from %s", websocket.client.host if websocket.client else "unknown")
        _ws_stats["disconnect_reasons"]["auth_failed"] += 1
        await websocket.close(code=4001, reason="Unauthorized: empty token")
        return False
    if token != settings.ws_auth_token:
        logger.warning("[WS] Auth rejected: token mismatch from %s (got %s...)", websocket.client.host if websocket.client else "unknown", token[:8])
        _ws_stats["disconnect_reasons"]["auth_failed"] += 1
        await websocket.close(code=4001, reason="Unauthorized: invalid token")
        return False

    total = active_market_connections + active_signal_connections
    if total >= 50:
        logger.warning("[WS] Connection limit reached: %d active", total)
        _ws_stats["disconnect_reasons"]["connection_limit"] += 1
        await websocket.close(code=1013, reason="Too many connections")
        return False

    return True


def _build_tick_delta(bonds, last_snapshot: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    """构建增量行情数据，只发送变化的字段。返回 (delta_list, new_snapshot)。"""
    delta_list = []
    new_snapshot = {}

    for b in bonds:
        current = b.model_dump(mode="json")
        code = current["code"]
        new_snapshot[code] = current

        prev = last_snapshot.get(code)
        if prev is None:
            # 新增品种，发送完整数据
            delta_list.append(current)
            continue

        # 计算变化字段
        changed = {"code": code}
        has_change = False
        for key, val in current.items():
            if key == "code":
                continue
            if prev.get(key) != val:
                changed[key] = val
                has_change = True

        if has_change:
            delta_list.append(changed)

    return delta_list, new_snapshot


_COMPRESS_THRESHOLD = 1024  # 超过1KB时压缩


async def _send_compressed(ws: WebSocket, msg: dict, stats_key: str = "market") -> int:
    """发送消息，大消息使用 gzip 压缩。返回发送字节数。"""
    raw = json.dumps(msg).encode("utf-8")
    if len(raw) > _COMPRESS_THRESHOLD:
        compressed = gzip.compress(raw)
        await ws.send_bytes(compressed)
        _ws_stats[f"{stats_key}_compressed_messages"] = _ws_stats.get(f"{stats_key}_compressed_messages", 0) + 1
        return len(compressed)
    else:
        await ws.send_json(msg)
        return len(raw)


@router.websocket("/market")
async def market_websocket(websocket: WebSocket):
    global active_market_connections

    engine = getattr(websocket.app.state, "engine", None)
    if not engine:
        _ws_stats["disconnect_reasons"]["engine_unavailable"] += 1
        await websocket.close(code=5030, reason="Market engine not available (503)")
        return

    if not await verify_ws_auth(websocket):
        return

    await websocket.accept()
    active_market_connections += 1
    if active_market_connections > 10:
        logger.warning(f"Market WebSocket connections exceed 10: {active_market_connections}")

    # 首次推送：发送当前全量数据
    is_first_push = True
    # Per-connection snapshot for delta computation (not shared across connections)
    conn_snapshot: dict[str, dict] = {}

    async def on_market_update(bonds):
        nonlocal is_first_push, conn_snapshot
        try:
            if is_first_push:
                # 首次推送全量数据
                data = [b.model_dump(mode="json") for b in bonds]
                msg = {
                    "type": "tick",
                    "data": data,
                    "ts": engine.last_update.isoformat() if engine.last_update else None,
                }
                sent_bytes = await _send_compressed(websocket, msg, "market")
                _ws_stats["market_messages_sent"] += 1
                _ws_stats["market_bytes_sent"] += sent_bytes
                _ws_stats["market_full_messages"] += 1
                # Store full snapshot for future delta computation
                conn_snapshot = {b.code: b.model_dump(mode="json") for b in bonds}
                is_first_push = False
                return

            delta, conn_snapshot = _build_tick_delta(bonds, conn_snapshot)
            if delta:
                msg = {
                    "type": "tick",
                    "data": delta,
                    "ts": engine.last_update.isoformat() if engine.last_update else None,
                }
                sent_bytes = await _send_compressed(websocket, msg, "market")
                _ws_stats["market_messages_sent"] += 1
                _ws_stats["market_bytes_sent"] += sent_bytes
                # 判断是否为增量消息
                if any(len(d) < len(bonds[0].model_dump(mode="json")) for d in delta if isinstance(d, dict)):
                    _ws_stats["market_delta_messages"] += 1
                else:
                    _ws_stats["market_full_messages"] += 1
        except Exception:
            _ws_stats["disconnect_reasons"]["send_error"] += 1

    engine.subscribe(on_market_update)

    # Push current cached data immediately
    try:
        current_bonds = list(engine._quotes.values()) if engine._quotes else []
        if current_bonds:
            data = [b.model_dump(mode="json") for b in current_bonds]
            msg = {"type": "tick", "data": data, "ts": engine.last_update.isoformat() if engine.last_update else None}
            sent_bytes = await _send_compressed(websocket, msg, "market")
            _ws_stats["market_messages_sent"] += 1
            _ws_stats["market_bytes_sent"] += sent_bytes
            _ws_stats["market_full_messages"] += 1
    except Exception:
        pass

    heartbeat_task = None

    async def heartbeat():
        while True:
            try:
                await asyncio.sleep(settings.ws_ping_interval)
                await websocket.send_json({"type": "ping"})
            except asyncio.CancelledError:
                break
            except Exception:
                _ws_stats["disconnect_reasons"]["heartbeat_timeout"] += 1
                break

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "pong":
                    continue
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        _ws_stats["disconnect_reasons"]["client_close"] += 1
    except Exception as e:
        _ws_stats["disconnect_reasons"]["receive_error"] += 1
        logger.error(f"[WS] Market connection error: {e}")
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        engine.unsubscribe(on_market_update)
        try:
            active_market_connections -= 1
        except Exception:
            pass


@router.websocket("/signals")
async def signals_websocket(websocket: WebSocket):
    global active_signal_connections

    signal_engine = getattr(websocket.app.state, "signal_engine", None)
    if not signal_engine:
        _ws_stats["disconnect_reasons"]["engine_unavailable"] += 1
        await websocket.close(code=5030, reason="Signal engine not available (503)")
        return

    if not await verify_ws_auth(websocket):
        return

    await websocket.accept()
    active_signal_connections += 1
    if active_signal_connections > 10:
        logger.warning(f"Signal WebSocket connections exceed 10: {active_signal_connections}")

    async def on_signal_update(signals):
        try:
            ts = signals[0].ts.isoformat() if signals else None
            msg = {
                "type": "signals",
                "data": [s.to_dict() for s in signals],
                "ts": ts,
            }
            sent_bytes = await _send_compressed(websocket, msg, "signal")
            _ws_stats["signal_messages_sent"] += 1
            _ws_stats["signal_bytes_sent"] += sent_bytes
        except Exception:
            _ws_stats["disconnect_reasons"]["send_error"] += 1

    signal_engine.subscribe(on_signal_update)

    async def heartbeat():
        while True:
            try:
                await asyncio.sleep(settings.ws_ping_interval)
                await websocket.send_json({"type": "ping"})
            except asyncio.CancelledError:
                break
            except Exception:
                _ws_stats["disconnect_reasons"]["heartbeat_timeout"] += 1
                break

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "pong":
                    continue
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        _ws_stats["disconnect_reasons"]["client_close"] += 1
    except Exception as e:
        _ws_stats["disconnect_reasons"]["receive_error"] += 1
        logger.error(f"[WS] Signal connection error: {e}")
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        signal_engine.unsubscribe(on_signal_update)
        try:
            active_signal_connections -= 1
        except Exception:
            pass
