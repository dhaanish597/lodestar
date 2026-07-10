import asyncio
import websockets
import time
import json

async def listen():
    uri = "ws://localhost:8000/ws/vessels"
    async with websockets.connect(uri) as websocket:
        end_time = time.time() + 60
        while time.time() < end_time:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Received: {message}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"Error: {e}")
                break

if __name__ == "__main__":
    asyncio.run(listen())
