from collections.abc import Callable, Sequence
from typing import Any

from app.providers.base import Completion
from app.schemas.chat import ChatMessage


class StubProvider:
    """Echo provider. `responder` scripts replies (and failures) per call: return a string
    for a text reply, or a full `Completion` to script tool_calls."""

    def __init__(
        self,
        default_model: str = "stub-model",
        responder: Callable[[list[ChatMessage], str], str | Completion] | None = None,
    ) -> None:
        self.default_model = default_model
        self.responder = responder
        self.calls: list[tuple[str, bool]] = []
        self.tools_seen: list[list[dict[str, Any]] | None] = []

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        *,
        json_mode: bool = False,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Completion:
        used_model = model or self.default_model
        self.calls.append((used_model, json_mode))
        self.tools_seen.append(tools)
        if self.responder:
            content = self.responder(list(messages), used_model)
            if isinstance(content, Completion):
                return content
        else:
            last_user = next(
                (message.content for message in reversed(messages) if message.role == "user"),
                "",
            )
            content = f"Stub response to: {last_user}" if last_user else "Stub response"
        return Completion(
            content=content,
            model=used_model,
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(content.split()),
        )

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> tuple[ChatMessage, str]:
        result = await self.generate(messages, model)
        return ChatMessage(role="assistant", content=result.content), result.model
