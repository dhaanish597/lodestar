import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as risk_router
from app.api.ws import router as ws_router
from app.config import get_settings
from app.ingestion.aisstream import AISStreamClient, VesselStore
from app.ingestion.coverage import CoverageMonitor
from app.ingestion.density import DensityTracker
from app.ingestion.gdelt import gdelt_poller
from app.ingestion.prices import PriceService

logger = logging.getLogger(__name__)


def _log_task_result(task: asyncio.Task) -> None:
    """Done-callback for the AIS background task.

    Fires whenever the task finishes — whether cleanly, via cancellation,
    or due to an unhandled exception.  A task that dies silently is exactly
    the bug class we need to catch; this ensures it's always logged.
    """
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        logger.info("[AIS-TASK] AIS task was cancelled (normal shutdown)")
        return

    if exc is not None:
        logger.error(
            "[AIS-TASK] ✗ AIS task DIED with exception: %s",
            exc,
            exc_info=exc,
        )
    else:
        logger.warning(
            "[AIS-TASK] AIS task completed with no exception — "
            "this is unexpected; run() should loop forever unless cancelled."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # ---- Startup diagnostics ----
    key = settings.aisstream_api_key
    masked = key[:8] + "…" if len(key) > 8 else "(EMPTY!)"
    ais_boxes = settings.ais_boxes
    logger.info(
        "[STARTUP] AISSTREAM_API_KEY=%s  ais_boxes=%s",
        masked, {name: box.bbox for name, box in ais_boxes.items()},
    )
    if not key:
        logger.error(
            "[STARTUP] ✗ AISSTREAM_API_KEY is EMPTY — AIS pipeline will NOT start. "
            "Set it in backend/.env or docker-compose env_file."
        )

    # Guarded assignment: TestClient(app) used as a context manager triggers this
    # lifespan on startup. Tests pre-populate app.state with mocked instances
    # (e.g. httpx.AsyncClient wired to a MockTransport) before constructing
    # TestClient(app); an unconditional assignment here would silently clobber
    # those mocks with real instances (e.g. an http_client that hits GDELT for
    # real during tests). Only create an instance if one isn't already set.
    if not hasattr(app.state, 'vessel_store') or app.state.vessel_store is None:
        app.state.vessel_store = VesselStore()
    if not hasattr(app.state, 'density_tracker') or app.state.density_tracker is None:
        app.state.density_tracker = DensityTracker()
    if not hasattr(app.state, 'coverage_monitor') or app.state.coverage_monitor is None:
        app.state.coverage_monitor = CoverageMonitor(list(ais_boxes))
    if not hasattr(app.state, 'http_client') or app.state.http_client is None:
        app.state.http_client = httpx.AsyncClient(timeout=10.0)
    if not hasattr(app.state, 'price_service') or app.state.price_service is None:
        app.state.price_service = PriceService(
            eia_api_key=settings.eia_api_key,
            alphavantage_api_key=settings.alphavantage_api_key,
        )

    ais_client = AISStreamClient(
        api_key=settings.aisstream_api_key,
        boxes=ais_boxes,
        store=app.state.vessel_store,
        coverage=app.state.coverage_monitor,
    )

    # ---- Pin the task on app.state so it is never GC'd ----
    app.state.ais_task = asyncio.create_task(ais_client.run(), name="ais-stream")
    app.state.ais_task.add_done_callback(_log_task_result)
    
    app.state.gdelt_task = asyncio.create_task(gdelt_poller(app.state.http_client), name="gdelt-poller")
    
    logger.info("[STARTUP] AIS background task scheduled (id=%s)", app.state.ais_task.get_name())

    yield

    app.state.ais_task.cancel()
    app.state.gdelt_task.cancel()
    try:
        await asyncio.gather(app.state.ais_task, app.state.gdelt_task, return_exceptions=True)
    except Exception:
        pass
    await app.state.http_client.aclose()


# ---- Configure logging so hop-a..e messages are visible ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(title="Lodestar API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(risk_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
