import base64
import json

import httpx
import pytest
from pydantic import ValidationError

from app.api.auth import get_supabase_service
from app.core.config import Settings
from app.services.supabase import SupabaseService

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_ID = "00000000-0000-0000-0000-000000000002"
USER = {"id": USER_ID, "email": "person@example.com", "email_confirmed_at": "2026-10-09T00:00:00Z", "is_anonymous": False}
PROFILE = {"id": USER_ID, "display_name": "Test User", "created_at": "2026-10-09T00:00:00Z", "updated_at": "2026-10-09T00:00:00Z"}


def configure_service(app, handler):
    service = SupabaseService(
        Settings(_env_file=None, supabase_url="https://test.supabase.co", supabase_publishable_key="sb_publishable_test"),
        transport=httpx.MockTransport(handler),
    )
    app.dependency_overrides[get_supabase_service] = lambda: service


@pytest.mark.parametrize("path,method", [("/api/v1/auth/me", "GET"), ("/api/v1/profile", "PATCH"), ("/api/v1/chat", "POST")])
async def test_protected_routes_require_bearer(client, path, method):
    response = await client.request(method, path, json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_unconfigured_auth_fails_closed(client):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "auth_unavailable"


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_token_never_reads_profile(app, client, status):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"message": "private upstream detail"})
    configure_service(app, handler)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert calls == ["/auth/v1/user"]
    assert "private upstream detail" not in response.text


async def test_valid_user_reads_only_own_profile(app, client):
    calls = []
    def handler(request):
        assert request.headers["authorization"] == "Bearer verified-token"
        assert request.headers["apikey"] == "sb_publishable_test"
        calls.append(request.url.path)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        assert request.url.params["id"] == f"eq.{USER_ID}"
        return httpx.Response(200, json=[PROFILE])
    configure_service(app, handler)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer verified-token"})
    assert response.status_code == 200
    assert response.json()["profile"]["display_name"] == "Test User"
    assert calls == ["/auth/v1/user", "/rest/v1/profiles"]
    assert "verified-token" not in response.text


async def test_profile_update_uses_authenticated_id_and_user_token(app, client):
    def handler(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        assert request.method == "PATCH"
        assert request.url.params["id"] == f"eq.{USER_ID}"
        assert request.headers["authorization"] == "Bearer user-token"
        assert request.headers["prefer"] == "return=representation"
        assert json.loads(request.content) == {"display_name": "New Name"}
        return httpx.Response(200, json=[{**PROFILE, "display_name": "New Name"}])
    configure_service(app, handler)
    response = await client.patch("/api/v1/profile", headers={"Authorization": "Bearer user-token"}, json={"display_name": "  New Name  "})
    assert response.status_code == 200
    assert response.json()["display_name"] == "New Name"


@pytest.mark.parametrize("payload", [{"display_name": " "}, {"display_name": "x" * 101}, {"display_name": "Name", "id": OTHER_ID}, {"display_name": "Name", "role": "admin"}])
async def test_profile_update_rejects_invalid_or_privileged_fields(app, client, payload):
    def handler(request):
        assert request.url.path == "/auth/v1/user"
        return httpx.Response(200, json=USER)
    configure_service(app, handler)
    response = await client.patch("/api/v1/profile", headers={"Authorization": "Bearer user-token"}, json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("data", [{**USER, "is_anonymous": True}, {**USER, "email_confirmed_at": None}, {**USER, "email": None}])
async def test_account_requires_confirmed_email_user(app, client, data):
    configure_service(app, lambda request: httpx.Response(200, json=data))
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer token"})
    assert response.status_code == 401


@pytest.mark.parametrize("profile,status", [([], 404), ([{**PROFILE, "id": OTHER_ID}], 502), ({"unexpected": True}, 502)])
async def test_missing_or_mismatched_profile_is_not_returned(app, client, profile, status):
    configure_service(app, lambda request: httpx.Response(200, json=USER if request.url.path == "/auth/v1/user" else profile))
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer token"})
    assert response.status_code == status


async def test_provider_unreachable_returns_safe_error(app, client):
    def handler(request):
        raise httpx.ConnectError("secret connection detail", request=request)
    configure_service(app, handler)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer token"})
    assert response.status_code == 503
    assert "secret connection detail" not in response.text


async def test_authenticated_chat_works(app, client):
    configure_service(app, lambda request: httpx.Response(200, json=USER))
    response = await client.post("/api/v1/chat", headers={"Authorization": "Bearer token"}, json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 200
    assert response.json()["message"]["content"] == "Stub response to: hello"


async def test_invalid_token_blocks_chat_provider(app, client):
    configure_service(app, lambda request: httpx.Response(401, json={}))
    response = await client.post("/api/v1/chat", headers={"Authorization": "Bearer token"}, json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 401


@pytest.mark.parametrize("value", ["sb_secret_privileged", "not-a-key", "header." + base64.urlsafe_b64encode(b'{"role":"service_role"}').decode() + ".signature"])
def test_configuration_rejects_privileged_or_invalid_key(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, supabase_publishable_key=value)
