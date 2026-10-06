from typing import Protocol

from app.core.config import Settings
from app.core.errors import LLMUnavailableError
from app.schemas.chat import ChatMessage


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> tuple[ChatMessage, str]:
        """Return assistant message and model name used."""


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "stub":
        from app.providers.stub import StubProvider

        return StubProvider(default_model=settings.llm_model)

    if settings.llm_provider == "openai_compatible":
        if not settings.llm_api_key.strip():
            raise LLMUnavailableError(
                "LLM_API_KEY is required when LLM_PROVIDER=openai_compatible"
            )
        from app.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            default_model=settings.llm_model,
        )

    raise LLMUnavailableError(f"Unsupported LLM provider: {settings.llm_provider}")
