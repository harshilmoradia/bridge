import logging

import httpx

from app.core.errors import LLMUnavailableError, LLMUpstreamError
from app.providers.base import Completion
from app.schemas.chat import ChatMessage

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> tuple[ChatMessage, str]:
        result = await self.generate(messages, model)
        return ChatMessage(role="assistant", content=result.content), result.model

    async def generate(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        *,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> Completion:
        used_model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": used_model,
            "messages": [message.model_dump() for message in messages],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError("LLM request timed out") from exc
        except httpx.RequestError as exc:
            logger.warning("LLM request failed: %s", type(exc).__name__)
            raise LLMUnavailableError("Unable to reach LLM provider") from exc

        if response.status_code >= 500:
            raise LLMUnavailableError("LLM provider is unavailable")
        if response.status_code >= 400:
            raise LLMUpstreamError(
                f"LLM provider rejected the request ({response.status_code})"
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            returned_model = data.get("model") or used_model
            usage = data.get("usage") or {}
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUpstreamError("LLM upstream returned an unexpected response") from exc

        if not isinstance(content, str):
            raise LLMUpstreamError("LLM upstream returned an unexpected response")

        return Completion(
            content=content,
            model=returned_model,
            prompt_tokens=_token_count(usage, "prompt_tokens"),
            completion_tokens=_token_count(usage, "completion_tokens"),
        )


def _token_count(usage: object, key: str) -> int:
    # Usage is telemetry only: a malformed block must not fail a good completion.
    try:
        return int(usage.get(key) or 0)  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return 0
