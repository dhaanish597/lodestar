# backend/tests/conftest.py
"""Shared pytest fixtures for the backend test suite.

This module is auto-discovered by pytest for every test in this directory
(and subdirectories) without requiring per-file imports.
"""
import pytest

from app.ingestion.aisstream import AISStreamClient


@pytest.fixture(autouse=True)
def no_real_aisstream_connection(monkeypatch):
    """Prevent any real network connection from AISStreamClient during tests.

    `app.main.lifespan()` unconditionally constructs an `AISStreamClient` and
    schedules `asyncio.create_task(ais_client.run())` on every app startup,
    which every `TestClient(app)` triggers. Without this patch, `run()` would
    call `websockets.connect("wss://stream.aisstream.io/v0/stream")` against
    the real network on every single test in the suite, regardless of whether
    `AISSTREAM_API_KEY` is configured. In a network-restricted environment
    this can hang for the OS resolver's timeout, since `task.cancel()` cannot
    interrupt a DNS lookup already running in a worker thread.

    Patching `AISStreamClient.run` at the class level (rather than the
    instance) works because `ais_client.run` is looked up on the class at
    call time when `asyncio.create_task(ais_client.run())` binds the method,
    and `lifespan()` always constructs a fresh `AISStreamClient` from the
    imported `app.ingestion.aisstream.AISStreamClient` symbol -- the same
    class object this fixture patches. Being function-scoped and autouse,
    monkeypatch reverts the attribute after every test automatically.
    """

    async def _noop_run(self):
        return None

    monkeypatch.setattr(AISStreamClient, "run", _noop_run)
