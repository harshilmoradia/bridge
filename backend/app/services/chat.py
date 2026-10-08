from app.providers.base import LLMProvider
from app.schemas.chat import ChatRequest, ChatResponse


class ChatService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def chat(self, request: ChatRequest) -> ChatResponse:
        message, model = await self.provider.complete(
            messages=request.messages,
            model=request.model,
        )
        return ChatResponse(message=message, model=model)
