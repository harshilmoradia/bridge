from app.schemas.chat import ChatMessage


class StubProvider:
    def __init__(self, default_model: str = "stub-model") -> None:
        self.default_model = default_model

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> tuple[ChatMessage, str]:
        last_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        reply = f"Stub response to: {last_user}" if last_user else "Stub response"
        used_model = model or self.default_model
        return ChatMessage(role="assistant", content=reply), used_model
