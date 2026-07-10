# test_aisstream_wide.py
import asyncio, websockets, json, time

async def main():
    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as ws:
        await ws.send(json.dumps({
            "APIKey": "aba680edfc64feb6e588b6aa698dd0ba18a5d01c",
            "BoundingBoxes": [[[24.8, 54.8], [26.6, 57.0]]],  # widened south+west to catch Fujairah/Dubai/Jebel Ali coastal coverage
            "FilterMessageTypes": ["PositionReport"]
        }))
        start = time.time()
        count = 0
        async for msg in ws:
            count += 1
            print(f"[{count}] {msg[:200]}")
            if time.time() - start > 60:
                break
        print(f"Total in 60s: {count}")

asyncio.run(main())