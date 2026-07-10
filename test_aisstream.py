import asyncio
import websockets
import json
import time

API_KEY = "aba680edfc64feb6e588b6aa698dd0ba18a5d01c"

async def test_stream(name, bbox, timeout):
    print(f"\n--- Running test: {name} ---")
    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
        subscribe_message = {
            "APIKey": API_KEY,
            "BoundingBoxes": bbox,
            "FilterMessageTypes": ["PositionReport"]
        }
        raw_msg = json.dumps(subscribe_message)
        print(f"RAW SUBSCRIBE STRING:\n{raw_msg}")
        await websocket.send(raw_msg)
        print("Connected and sent subscribe message.")
        
        start_time = time.time()
        msg_count = 0
        while time.time() - start_time < timeout:
            try:
                time_left = max(0.1, timeout - (time.time() - start_time))
                message_json = await asyncio.wait_for(websocket.recv(), timeout=time_left)
                print(f"RAW FRAME RECEIVED: {message_json}")
                msg_count += 1
                if name == "World Control" and msg_count >= 5:
                    print("Received enough control messages, stopping world test early.")
                    break
            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"ERROR: {e}")
                break
        print(f"--- Finished test: {name} ---")

async def main():
    # Test 1: Fujairah/Dubai
    await test_stream(
        "Fujairah/Dubai", 
        [[[24.8, 54.8], [26.6, 57.0]]], 
        90.0
    )
    
    # Test 2: World Control
    await test_stream(
        "World Control", 
        [[[-90, -180], [90, 180]]], 
        15.0
    )

if __name__ == "__main__":
    asyncio.run(main())
