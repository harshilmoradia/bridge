import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


@pytest.mark.asyncio
async def test_chat_stub_ok(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"]["role"] == "assistant"
    assert data["message"]["content"] == "Stub response to: hello"
    assert "model" in data


@pytest.mark.asyncio
async def test_chat_empty_messages_422(client: AsyncClient) -> None:
    response = await client.post("/api/v1/chat", json={"messages": []})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_openai_compatible_missing_key_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_API_KEY", "")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
    get_settings.cache_clear()

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["code"] == "llm_unavailable"
