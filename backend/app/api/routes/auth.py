from fastapi import APIRouter, Depends

from app.api.auth import AuthContext, get_current_user, get_supabase_service
from app.schemas.auth import Account, Profile, ProfileUpdate
from app.services.supabase import SupabaseService

router = APIRouter(tags=["account"])


@router.get("/auth/me", response_model=Account)
async def account(
    context: AuthContext = Depends(get_current_user),
    service: SupabaseService = Depends(get_supabase_service),
) -> Account:
    profile = await service.get_profile(context.user, context.token)
    return Account(user=context.user, profile=profile)


@router.patch("/profile", response_model=Profile)
async def update_profile(
    request: ProfileUpdate,
    context: AuthContext = Depends(get_current_user),
    service: SupabaseService = Depends(get_supabase_service),
) -> Profile:
    return await service.update_profile(context.user, context.token, request.display_name)
