from fastapi import APIRouter

from app.api.routes import auth, chat, demo, health, reads, runs

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router, prefix="/api/v1")
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(reads.router, prefix="/api/v1")
api_router.include_router(runs.router, prefix="/api/v1")
api_router.include_router(demo.router, prefix="/api/v1")
