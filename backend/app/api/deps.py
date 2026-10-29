from fastapi import Depends

from app.core.config import Settings, get_settings
from app.providers.base import LLMProvider, get_llm_provider
from app.services.chat import ChatService


def get_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    return get_llm_provider(settings)


def get_chat_service(provider: LLMProvider = Depends(get_provider)) -> ChatService:
    return ChatService(provider=provider)
