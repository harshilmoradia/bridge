from fastapi import APIRouter

from app.api.routes import auth, chat, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router, prefix="/api/v1")
api_router.include_router(auth.router, prefix="/api/v1")
