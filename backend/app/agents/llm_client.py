"""Thin wrapper around NVIDIA's OpenAI-compatible NIM endpoint
(build.nvidia.com). Agents call this for narration/classification text
only -- it never computes or returns a number consumed as engine output.
If NVIDIA_API_KEY is unset, narrate() returns an honest STUB string instead
of fabricating text, mirroring the OpenSanctions-stub pattern (docs/04).
"""
import logging

from openai import AsyncOpenAI, APIError

logger = logging.getLogger(__name__)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
STUB_NARRATION = "STUB — LLM narration unavailable, NVIDIA_API_KEY not configured."


class LLMClient:
    """One instance per app lifetime. api_key="" makes every call an honest STUB."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._client = (
            AsyncOpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key) if api_key else None
        )

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    async def narrate(self, system_prompt: str, user_prompt: str) -> str:
        if self._client is None:
            return STUB_NARRATION
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=400,
            )
            content = response.choices[0].message.content
            return content if content else STUB_NARRATION
        except APIError as exc:
            logger.warning("[LLM] NVIDIA NIM call failed: %s", exc)
            return f"STUB — LLM narration unavailable, NVIDIA API error ({type(exc).__name__})."
        except Exception as exc:
            logger.warning("[LLM] Unexpected error: %s", type(exc).__name__)
            return f"STUB — LLM narration unavailable, unexpected error ({type(exc).__name__})."
