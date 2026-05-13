import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engine.market import MarketEngine

router = APIRouter()
engine = MarketEngine()


@router.websocket("/market")
async def market_websocket(websocket: WebSocket):
    await websocket.accept()

    async def on_market_update_all(bonds):
        data = [b.model_dump(mode="json") for b in bonds]
        try:
            await websocket.send_json({"type": "tick", "data": data})
        except Exception:
            pass

    engine.subscribe_all(on_market_update_all)

    async def poll():
        while True:
            try:
                bonds = await engine.refresh()
                await on_market_update_all(bonds)
            except Exception as e:
                print(f"Poll error: {e}")
            await asyncio.sleep(5)

    poll_task = asyncio.create_task(poll())

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "subscribe":
                codes = msg.get("codes", [])
            elif msg.get("type") == "unsubscribe":
                codes = msg.get("codes", [])
    except WebSocketDisconnect:
        pass
    finally:
        poll_task.cancel()
        engine.unsubscribe_all(on_market_update_all)
