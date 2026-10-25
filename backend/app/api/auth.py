from dataclasses import dataclass, field

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.schemas.auth import AuthUser
from app.services.supabase import SupabaseService

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: AuthUser
    token: str = field(repr=False)


def get_supabase_service(settings: Settings = Depends(get_settings)) -> SupabaseService:
    return SupabaseService(settings)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    service: SupabaseService = Depends(get_supabase_service),
) -> AuthContext:
    if credentials is None:
        raise AppError(code="unauthenticated", message="Sign in to use this endpoint", status_code=401)
    user = await service.get_user(credentials.credentials)
    return AuthContext(user=user, token=credentials.credentials)
