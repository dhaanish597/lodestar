# scripts/diag_aisstream.py
"""AISStream diagnostic matrix — falsify H1 (coordinate order) vs H2 (coverage void).

Connects to wss://stream.aisstream.io/v0/stream, subscribes with a given
bounding box (+ optional MessageType filter), listens for a fixed duration,
and reports: total frames, count per MessageType, and the first 3
(lat, lon, MMSI) samples.

Usage (run cases STRICTLY sequentially — the free-tier key is single-session;
the app must be fully down: `docker compose down` first):

    python scripts/diag_aisstream.py            # run the full A–H matrix
    python scripts/diag_aisstream.py A D F      # run only the named cases

The API key is read from backend/.env (AISSTREAM_API_KEY) or the environment.
Never hardcode it here.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import websockets

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover
    dotenv_values = None

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
REPO_ROOT = Path(__file__).resolve().parent.parent

# Positive cases stop early once this many frames arrive — the question per
# case is yes/no + samples, not throughput. Zero-frame cases run full duration.
EARLY_STOP_FRAMES = 100

# (case_id, name, bbox, filter_types, duration_s)
CASES = [
    ("A", "Worldwide positive control", [[[-90, -180], [90, 180]]], ["PositionReport"], 30),
    ("B", "Dover Strait lat-lon", [[[50.5, 0.5], [51.5, 2.0]]], ["PositionReport"], 120),
    ("C", "Dover Strait axes SWAPPED (lon-lat)", [[[0.5, 50.5], [2.0, 51.5]]], ["PositionReport"], 120),
    ("D", "Hormuz lat-lon", [[[25.2732, 55.1647], [27.3713, 57.3419]]], ["PositionReport"], 120),
    ("E", "Hormuz axes SWAPPED (lon-lat)", [[[55.1647, 25.2732], [57.3419, 27.3713]]], ["PositionReport"], 120),
    ("F", "Entire Gulf + Gulf of Oman, NO filter", [[[20.0, 48.0], [30.0, 65.0]]], None, 180),
    ("G", "India west coast (Gujarat + Mumbai), NO filter", [[[19.5, 68.5], [23.5, 73.0]]], None, 180),
    ("H", "Singapore Strait", [[[1.0, 103.3], [1.6, 104.4]]], ["PositionReport"], 120),
]


def load_api_key() -> str:
    key = os.environ.get("AISSTREAM_API_KEY", "")
    if not key and dotenv_values is not None:
        env = dotenv_values(REPO_ROOT / "backend" / ".env")
        key = env.get("AISSTREAM_API_KEY", "") or ""
    if not key:
        sys.exit("FATAL: AISSTREAM_API_KEY not found in environment or backend/.env")
    return key


async def run_case(api_key: str, case_id: str, name: str, bbox, filter_types, duration_s: int) -> dict:
    print(f"\n=== Case {case_id}: {name} ===")
    print(f"    bbox={bbox}  filter={filter_types}  duration={duration_s}s", flush=True)

    result = {
        "case": case_id,
        "name": name,
        "bbox": bbox,
        "filter": filter_types,
        "duration_s": duration_s,
        "total_frames": 0,
        "per_type": {},
        "samples": [],
        "error": None,
    }

    subscribe: dict = {"APIKey": api_key, "BoundingBoxes": bbox}
    if filter_types is not None:
        subscribe["FilterMessageTypes"] = filter_types

    try:
        async with websockets.connect(AISSTREAM_URL) as ws:
            await ws.send(json.dumps(subscribe))
            print(f"    subscribed at t=0.0s", flush=True)
            start = time.monotonic()
            while True:
                elapsed = time.monotonic() - start
                remaining = duration_s - elapsed
                if remaining <= 0 or result["total_frames"] >= EARLY_STOP_FRAMES:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                result["total_frames"] += 1
                try:
                    frame = json.loads(raw)
                    mtype = frame.get("MessageType", "UNKNOWN")
                except Exception:
                    mtype = "UNPARSEABLE"
                    frame = {}
                result["per_type"][mtype] = result["per_type"].get(mtype, 0) + 1
                if result["total_frames"] == 1:
                    print(f"    FIRST frame at t={elapsed:.1f}s  type={mtype}", flush=True)
                if len(result["samples"]) < 3:
                    meta = frame.get("MetaData", {}) if isinstance(frame, dict) else {}
                    lat, lon, mmsi = meta.get("latitude"), meta.get("longitude"), meta.get("MMSI")
                    if lat is not None:
                        result["samples"].append((lat, lon, mmsi))
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"    ERROR: {result['error']}", flush=True)

    print(f"    -> total_frames={result['total_frames']}  per_type={result['per_type']}")
    for lat, lon, mmsi in result["samples"]:
        print(f"       sample: lat={lat}  lon={lon}  mmsi={mmsi}")
    return result


async def main() -> None:
    api_key = load_api_key()
    wanted = [a.upper() for a in sys.argv[1:]]
    cases = [c for c in CASES if not wanted or c[0] in wanted]

    results = []
    for case_id, name, bbox, filter_types, duration_s in cases:
        results.append(await run_case(api_key, case_id, name, bbox, filter_types, duration_s))
        await asyncio.sleep(2)  # let the server fully release the session between cases

    print("\n\n=== RESULTS TABLE ===")
    print(f"{'Case':<5} {'Frames':>7}  {'Types':<40} Name")
    for r in results:
        types = ",".join(f"{k}:{v}" for k, v in r["per_type"].items()) or ("ERROR" if r["error"] else "-")
        print(f"{r['case']:<5} {r['total_frames']:>7}  {types:<40} {r['name']}")
    print("\nJSON:", json.dumps(results, default=str))


if __name__ == "__main__":
    asyncio.run(main())
