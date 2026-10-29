import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch):
    """Every test runs on the stub provider with no key, and real HTTP fails the test.

    backend/.env may hold a live key; env vars win over it. A test that needs another provider sets
    LLM_PROVIDER itself (and clears the settings cache); a test that needs HTTP routes it through
    httpx.MockTransport or ASGITransport, which never reach the real transports blocked here.
    """
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()

    def blocked(*_args, **_kwargs):
        pytest.fail("real network request in a test: use the stub provider or httpx.MockTransport")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "")
    monkeypatch.setenv("DATABASE_URL", "")  # read API uses the CSV store in tests
    monkeypatch.setenv("DATASET", "northbrook-2026-10")
    monkeypatch.setenv("PUBLIC_DEMO_API", "true")  # the default; pinned so a local .env can't flip it
    application = create_app()
    yield application
    get_settings.cache_clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
