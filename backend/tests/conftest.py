import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


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
