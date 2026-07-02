import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

BROADCAST_INTERVAL_SECONDS = 2


@router.websocket("/ws/vessels")
async def ws_vessels(websocket: WebSocket) -> None:
    await websocket.accept()
    store = websocket.app.state.vessel_store
    try:
        while True:
            snapshot = store.snapshot()
            await websocket.send_text(json.dumps([v.model_dump(mode="json") for v in snapshot]))
            await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
