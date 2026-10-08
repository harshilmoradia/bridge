import logging

import httpx

from app.core.errors import LLMUnavailableError, LLMUpstreamError
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
        used_model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": used_model,
            "messages": [message.model_dump() for message in messages],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUpstreamError("LLM upstream returned an unexpected response") from exc

        if not isinstance(content, str):
            raise LLMUpstreamError("LLM upstream returned an unexpected response")

        return ChatMessage(role="assistant", content=content), returned_model
