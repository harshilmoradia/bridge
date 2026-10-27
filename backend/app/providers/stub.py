from collections.abc import Callable

from app.providers.base import Completion
from app.schemas.chat import ChatMessage


class StubProvider:
    """Echo provider. `responder` lets tests script replies (and failures) per call."""

    def __init__(
        self,
        default_model: str = "stub-model",
        responder: Callable[[list[ChatMessage], str], str] | None = None,
    ) -> None:
        self.default_model = default_model
        self.responder = responder
        self.calls: list[tuple[str, bool]] = []

    async def generate(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        *,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> Completion:
        used_model = model or self.default_model
        self.calls.append((used_model, json_mode))
        if self.responder:
            content = self.responder(messages, used_model)
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
