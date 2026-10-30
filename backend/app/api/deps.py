from fastapi import Depends

from app.core.config import Settings, get_settings
from app.providers.base import LLMProvider, get_llm_provider
from app.services.chat import ChatService
from app.services.rag_chat import RagChatService
from app.rag.search import RagSearchService


def get_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    return get_llm_provider(settings)


def get_chat_service(provider: LLMProvider = Depends(get_provider)) -> ChatService:
    return ChatService(provider=provider)


def get_rag_chat_service(
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_provider),
) -> RagChatService:
    return RagChatService(provider=provider, settings=settings, search=RagSearchService(settings))
