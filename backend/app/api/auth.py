from dataclasses import dataclass, field
from uuid import UUID

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
    token: str | None = field(default=None, repr=False)  # None only for the anonymous demo user


# Who acts when PUBLIC_DEMO_API serves a caller without a bearer token.
DEMO_USER = AuthUser(id=UUID("00000000-0000-0000-0000-00000000de30"), email="demo@bridge.local")


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


async def get_user_or_demo(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    service: SupabaseService = Depends(get_supabase_service),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    """Guard for the v1 demo routers. No header plus PUBLIC_DEMO_API gives the demo user.

    A token that is sent is always verified, so a bad token is a 401, never a silent demo fallback.
    """
    if credentials is None and settings.public_demo_api:
        return AuthContext(user=DEMO_USER)
    return await get_current_user(credentials, service)
