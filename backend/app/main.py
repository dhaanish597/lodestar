import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as risk_router
from app.api.ws import router as ws_router
from app.config import get_settings
from app.ingestion.aisstream import AISStreamClient, VesselStore
from app.ingestion.density import DensityTracker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

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
    if not hasattr(app.state, 'http_client') or app.state.http_client is None:
        app.state.http_client = httpx.AsyncClient(timeout=10.0)

    ais_client = AISStreamClient(
        api_key=settings.aisstream_api_key,
        corridor=settings.corridors["hormuz"],
        store=app.state.vessel_store,
    )
    task = asyncio.create_task(ais_client.run())

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await app.state.http_client.aclose()


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
