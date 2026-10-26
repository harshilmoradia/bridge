"""PUBLIC_DEMO_API: the v1 read API serves an anonymous demo user when no bearer token is sent."""

import httpx
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.api.auth import DEMO_USER, get_user_or_demo
from app.core.config import Settings, get_settings
from tests.test_auth import USER, USER_ID, configure_service

READS = ["/api/v1/datasets", "/api/v1/bank-transactions", "/api/v1/gl-entries", "/api/v1/statement"]


@pytest.fixture
def demo_off(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_API", "false")
    get_settings.cache_clear()


@pytest.mark.parametrize("path", READS)
async def test_reads_are_public_when_the_demo_flag_is_on(client, path):
    response = await client.get(path)
    assert response.status_code == 200


@pytest.mark.parametrize("path", READS)
async def test_reads_need_sign_in_when_the_demo_flag_is_off(client, demo_off, path):
    response = await client.get(path)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"


async def test_a_rejected_token_is_401_not_the_demo_user(app, client):
    configure_service(app, lambda request: httpx.Response(401, json={"msg": "bad jwt"}))
    response = await client.get("/api/v1/datasets", headers={"Authorization": "Bearer stale-token"})
    assert response.status_code == 401


async def test_a_valid_token_resolves_to_the_real_user(app):
    configure_service(app, lambda request: httpx.Response(200, json=USER))
    from app.api.auth import get_supabase_service

    service = app.dependency_overrides[get_supabase_service]()
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="user-token")
    context = await get_user_or_demo(credentials, service, Settings(_env_file=None, public_demo_api=True))
    assert str(context.user.id) == USER_ID
    assert context.token == "user-token"


async def test_no_token_with_the_flag_on_is_the_demo_user(app):
    from app.api.auth import get_supabase_service

    context = await get_user_or_demo(None, get_supabase_service(get_settings()), Settings(_env_file=None))
    assert context.user == DEMO_USER
    assert context.token is None
