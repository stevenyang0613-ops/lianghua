import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/market")
async def market_websocket(websocket: WebSocket):
    await websocket.accept()
    engine = websocket.app.state.engine

    async def on_market_update(bonds):
        data = [b.model_dump(mode="json") for b in bonds]
        try:
            await websocket.send_json({"type": "tick", "data": data, "ts": engine.last_update.isoformat() if engine.last_update else None})
        except Exception:
            pass

    engine.subscribe(on_market_update)

    heartbeat_task = None

    async def heartbeat():
        while True:
            try:
                await asyncio.sleep(30)
                await websocket.send_json({"type": "ping"})
            except Exception:
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
        pass
    except Exception as e:
        print(f"[WS] Connection error: {e}")
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        engine.unsubscribe(on_market_update)


@router.websocket("/signals")
async def signals_websocket(websocket: WebSocket):
    await websocket.accept()
    signal_engine = getattr(websocket.app.state, "signal_engine", None)
    if not signal_engine:
        await websocket.send_json({"type": "error", "message": "Signal engine not available"})
        await websocket.close()
        return

    async def on_signal_update(signals):
        try:
            await websocket.send_json({
                "type": "signals",
                "signals": [s.to_dict() for s in signals],
                "ts": signals[0].ts.isoformat() if signals else None,
            })
        except Exception:
            pass

    signal_engine.subscribe(on_signal_update)

    async def heartbeat():
        while True:
            try:
                await asyncio.sleep(30)
                await websocket.send_json({"type": "ping"})
            except Exception:
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
        pass
    except Exception as e:
        print(f"[WS] Signal connection error: {e}")
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        signal_engine.unsubscribe(on_signal_update)

