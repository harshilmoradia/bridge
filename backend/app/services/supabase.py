from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.auth import AuthUser, Profile


class SupabaseService:
    """Validate tokens with Auth and query PostgREST using the caller's JWT/RLS."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def _request(
        self, method: str, path: str, token: str, **kwargs: Any
    ) -> httpx.Response:
        if not self.settings.supabase_url or not self.settings.supabase_publishable_key:
            raise AppError(code="auth_unavailable", message="Account services are not configured", status_code=503)
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.supabase_url.rstrip("/") + "/",
                timeout=10,
                transport=self.transport,
                headers={
                    "apikey": self.settings.supabase_publishable_key,
                    "Authorization": f"Bearer {token}",
                },
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise AppError(code="auth_unavailable", message="Account services are unavailable", status_code=503) from exc
        if response.status_code in (401, 403):
            raise AppError(code="unauthenticated", message="Sign in with a valid account", status_code=401)
        if not response.is_success:
            raise AppError(code="account_upstream_error", message="Account services are unavailable", status_code=503)
        return response

    async def get_user(self, token: str) -> AuthUser:
        response = await self._request("GET", "auth/v1/user", token)
        try:
            data = response.json()
            if not isinstance(data, dict) or not data.get("email") or data.get("is_anonymous") is True or not data.get("email_confirmed_at"):
                raise AppError(code="unauthenticated", message="Sign in with a confirmed email account", status_code=401)
            return AuthUser.model_validate(data)
        except (ValueError, ValidationError) as exc:
            raise AppError(code="account_upstream_error", message="Account services returned an invalid response", status_code=502) from exc

    async def get_profile(self, user: AuthUser, token: str) -> Profile:
        response = await self._request(
            "GET", "rest/v1/profiles", token,
            params={"id": f"eq.{user.id}", "select": "id,display_name,created_at,updated_at"},
        )
        return self._profile(response, user)

    async def update_profile(self, user: AuthUser, token: str, display_name: str) -> Profile:
        response = await self._request(
            "PATCH", "rest/v1/profiles", token,
            params={"id": f"eq.{user.id}", "select": "id,display_name,created_at,updated_at"},
            json={"display_name": display_name},
            headers={"Prefer": "return=representation"},
        )
        return self._profile(response, user)

    @staticmethod
    def _profile(response: httpx.Response, user: AuthUser) -> Profile:
        try:
            rows = response.json()
            if rows == []:
                raise AppError(code="profile_not_found", message="Your account profile was not found", status_code=404)
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError("Expected exactly one profile")
            profile = Profile.model_validate(rows[0])
            if profile.id != user.id:
                raise ValueError("Profile does not belong to authenticated user")
            return profile
        except (ValueError, ValidationError) as exc:
            raise AppError(code="account_upstream_error", message="Account services returned an invalid response", status_code=502) from exc
