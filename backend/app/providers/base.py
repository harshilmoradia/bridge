from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import LLMUnavailableError
from app.schemas.chat import ChatMessage


class ToolCall(BaseModel, frozen=True):
    """One OpenAI-style function call. `arguments` is the raw JSON string; callers validate it."""

    id: str
    name: str
    arguments: str

    def wire(self) -> dict[str, Any]:
        return {"id": self.id, "type": "function",
                "function": {"name": self.name, "arguments": self.arguments}}


class AgentMessage(ChatMessage):
    """Internal message for tool turns. Not part of the public /chat contract."""

    role: Literal["user", "assistant", "system", "tool"]  # type: ignore[assignment]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [call.wire() for call in self.tool_calls]
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        return out


def wire_message(message: ChatMessage) -> dict[str, Any]:
    if isinstance(message, AgentMessage):
        return message.wire()
    return {"role": message.role, "content": message.content}


@dataclass(frozen=True)
class Completion:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: tuple[ToolCall, ...] = ()


class LLMProvider(Protocol):
    async def generate(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        json_mode: bool = False,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Completion:
        """Return the raw completion with token usage. With `tools`, may return tool_calls."""

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
                "LLM_API_KEY is required when LLM_PROVIDER=openai_compatible",
                diagnostic_code="missing_api_key",
            )
        from app.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            default_model=settings.llm_model,
        )

    raise LLMUnavailableError("Unsupported LLM provider configuration", diagnostic_code="unsupported_provider")
