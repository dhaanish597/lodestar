# backend/app/ingestion/gdelt.py
"""GDELT TimelineVol connector with in-memory TTL cache and 429 handling.

GDELT's API enforces a rate limit of roughly 1 request per 5 seconds and
returns HTTP 429 when exceeded.  The ``GdeltCache`` wrapper ensures:
  - At most one real request per ``ttl`` seconds (default 120).
  - On a 429, any ``Retry-After`` header is respected before the next attempt.
  - The last good cached value is served while rate-limited or on error.
"""
import asyncio
import logging
import os
import time

import httpx
import redis.asyncio as redis
from app.config import get_settings

logger = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# Original query and bbox for Hormuz
QUERY = '(Hormuz OR "Red Sea") (attack OR strike OR sanction OR disruption)'
HORMUZ_BBOX = "25.27,55.16,27.37,57.34"

async def gdelt_poller(client: httpx.AsyncClient):
    """Background task that polls GDELT safely.
    Makes exactly one request per cycle to stay well under rate limits."""
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    
    logger.info("[GDELT] Background poller started")
    
    while True:
        try:
            response = await client.get(
                GDELT_URL,
                params={
                    "query": QUERY,
                    "mode": "TimelineVol",
                    "timespan": "72h",
                    "format": "json",
                    "bbox": HORMUZ_BBOX,
                },
            )
            
            if response.status_code == 429:
                raw_retry = response.headers.get("Retry-After", "")
                try:
                    retry_secs = max(float(raw_retry), 5.0)
                except (ValueError, TypeError):
                    retry_secs = 15.0
                logger.warning("[GDELT] 429 Too Many Requests — backing off %.0fs", retry_secs)
                await asyncio.sleep(retry_secs)
                continue
                
            response.raise_for_status()
            payload = response.json()
            
            val = 0.0
            timelines = payload.get("timeline", [])
            if timelines:
                points = timelines[0].get("data", [])
                if points:
                    values = [p["value"] for p in points]
                    lo, hi = min(values), max(values)
                    if hi > lo:
                        val = (values[-1] - lo) / (hi - lo)
                        
            await redis_client.set("gdelt_kinetic_hormuz", val, ex=300)
            logger.info("[GDELT] Fetched kinetic volume for hormuz: %.4f", val)
            
        except httpx.HTTPStatusError as exc:
            logger.warning("[GDELT] HTTP %d", exc.response.status_code)
        except Exception as exc:
            logger.warning("[GDELT] Fetch failed: %s", repr(exc))
            
        # Global cycle delay: 120s between GDELT calls (very safe)
        await asyncio.sleep(120)


async def fetch_kinetic_volume(client: httpx.AsyncClient, corridor: str = "hormuz") -> float:
    """Public API consumed by routes.py — only reads from cache."""
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        val = await redis_client.get(f"gdelt_kinetic_{corridor}")
        if val is not None:
            return float(val)
    except Exception as e:
        logger.warning("[GDELT] Redis get error: %s", e)
        
    return 0.0
