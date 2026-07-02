import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

BROADCAST_INTERVAL_SECONDS = 2


@router.websocket("/ws/vessels")
async def ws_vessels(websocket: WebSocket) -> None:
    await websocket.accept()
    client = websocket.client
    logger.info("[WS hop-d] Client connected from %s", client)

    store = websocket.app.state.vessel_store
    broadcast_count = 0
    try:
        while True:
            snapshot = store.snapshot()
            payload = json.dumps([v.model_dump(mode="json") for v in snapshot])
            await websocket.send_text(payload)
            broadcast_count += 1

            # --- HOP (d): vessel relay logging ---
            if broadcast_count == 1:
                logger.info(
                    "[WS hop-d] First broadcast → %d vessels  (%d bytes)",
                    len(snapshot), len(payload),
                )
            elif broadcast_count % 10 == 0:
                logger.debug(
                    "[WS hop-d] Broadcast #%d → %d vessels",
                    broadcast_count, len(snapshot),
                )

            await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        logger.info("[WS hop-d] Client %s disconnected (after %d broadcasts)", client, broadcast_count)
        return
