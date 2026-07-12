from unittest.mock import AsyncMock

import pytest

from app.agents.llm_client import LLMClient, STUB_NARRATION


@pytest.mark.asyncio
async def test_narrate_returns_stub_without_key():
    client = LLMClient(api_key="", model="test-model")
    result = await client.narrate("system", "user")
    assert result == STUB_NARRATION
    assert client.has_key is False


@pytest.mark.asyncio
async def test_narrate_returns_model_content_on_success(monkeypatch):
    client = LLMClient(api_key="test-key", model="test-model")

    class FakeMessage:
        content = "The corridor risk is elevated."

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    monkeypatch.setattr(
        client._client.chat.completions, "create", AsyncMock(return_value=FakeResponse())
    )
    result = await client.narrate("system", "user")
    assert result == "The corridor risk is elevated."


@pytest.mark.asyncio
async def test_narrate_returns_stub_on_api_error(monkeypatch):
    client = LLMClient(api_key="test-key", model="test-model")
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    result = await client.narrate("system", "user")
    assert result.startswith("STUB — LLM narration unavailable")
