# scripts/diag_relay.py
"""End-to-end relay check: connect to the app's own /ws/vessels endpoint,
listen for a fixed window, and assert that at least one vessel payload arrives
with the expected typed schema and a position inside a subscribed AIS box.

Run with the stack up (`docker compose up -d`):

    python scripts/diag_relay.py            # default ws://localhost:8000/ws/vessels, 60s
    python scripts/diag_relay.py --seconds 30

Exit code 0 = PASS, 1 = FAIL.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FIELDS = {"mmsi", "lat", "lon", "sog", "cog", "true_heading", "timestamp"}


def load_boxes() -> dict:
    raw = json.loads((REPO_ROOT / "backend" / "data" / "ais_boxes.json").read_text())
    return {name: cfg["bbox"] for name, cfg in raw.items()}


def in_box(lat: float, lon: float, bbox: list) -> bool:
    lat_min, lon_min, lat_max, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8000/ws/vessels")
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()

    boxes = load_boxes()
    print(f"Connecting to {args.url}  (listening {args.seconds}s)")
    print(f"Subscribed boxes: {list(boxes)}")

    frames = 0
    max_vessels = 0
    schema_ok = False
    in_box_hits: dict[str, int] = {name: 0 for name in boxes}
    sample = None

    try:
        async with websockets.connect(args.url) as ws:
            start = time.monotonic()
            while time.monotonic() - start < args.seconds:
                remaining = args.seconds - (time.monotonic() - start)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
                except asyncio.TimeoutError:
                    break
                frames += 1
                vessels = json.loads(raw)
                max_vessels = max(max_vessels, len(vessels))
                for v in vessels:
                    if REQUIRED_FIELDS.issubset(v.keys()):
                        schema_ok = True
                    for name, bbox in boxes.items():
                        if in_box(v["lat"], v["lon"], bbox):
                            in_box_hits[name] += 1
                            if sample is None:
                                sample = v
                # Stop early once we have everything we need to assert.
                if schema_ok and any(in_box_hits.values()) and frames >= 3:
                    break
    except Exception as e:
        print(f"FAIL: could not connect/listen: {type(e).__name__}: {e}")
        return 1

    print(f"\nframes={frames}  max_vessels_per_frame={max_vessels}")
    print(f"in-box hits (cumulative across frames): {in_box_hits}")
    if sample:
        print(f"sample vessel: mmsi={sample['mmsi']} lat={sample['lat']:.4f} lon={sample['lon']:.4f} "
              f"sog={sample['sog']} cog={sample['cog']} heading={sample['true_heading']} ts={sample['timestamp']}")

    ok = frames >= 1 and schema_ok and any(in_box_hits.values())
    missing = []
    if frames < 1:
        missing.append("no frames received from relay")
    if not schema_ok:
        missing.append(f"no vessel had all required fields {sorted(REQUIRED_FIELDS)}")
    if not any(in_box_hits.values()):
        missing.append("no vessel position inside any subscribed box")
    print("\nPASS" if ok else f"\nFAIL: {'; '.join(missing)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
