from fastapi import APIRouter, Depends

from app.api.deps import get_chat_service, get_rag_chat_service
from app.api.auth import get_current_user, get_user_or_demo
from app.schemas.chat import ChatRequest, ChatResponse, RagChatRequest, RagChatResponse
from app.services.chat import ChatService
from app.services.rag_chat import RagChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    _user=Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    return await service.chat(request)


@router.post("/ask", response_model=RagChatResponse)
async def ask(
    request: RagChatRequest,
    _user=Depends(get_user_or_demo),
    service: RagChatService = Depends(get_rag_chat_service),
) -> RagChatResponse:
    """Search current transaction data and return a read-only grounded answer."""
    return await service.ask(request)
