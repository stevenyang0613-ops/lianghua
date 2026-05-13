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
