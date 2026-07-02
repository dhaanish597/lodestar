from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ws import router as ws_router
from app.ingestion.aisstream import VesselStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, 'vessel_store') or app.state.vessel_store is None:
        app.state.vessel_store = VesselStore()
    yield


app = FastAPI(title="Lodestar API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
