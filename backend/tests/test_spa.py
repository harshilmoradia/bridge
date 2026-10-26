import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
async def spa_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()


async def test_root_serves_index(spa_client):
    response = await spa_client.get("/")
    assert response.status_code == 200
    assert "id=root" in response.text


async def test_client_route_falls_back_to_index(spa_client):
    response = await spa_client.get("/runs/abc")
    assert response.status_code == 200
    assert "id=root" in response.text


async def test_static_asset_served(spa_client):
    response = await spa_client.get("/assets/app.js")
    assert response.text == "console.log(1)"


async def test_backend_routes_win(spa_client):
    assert (await spa_client.get("/health")).json() == {"status": "ok"}
    assert (await spa_client.get("/api/inngest")).status_code == 200
    assert (await spa_client.get("/docs")).status_code == 200
    assert (await spa_client.get("/openapi.json")).status_code == 200


async def test_unknown_api_path_is_json_404(spa_client):
    response = await spa_client.get("/api/v1/nope")
    assert response.status_code == 404
    assert "id=root" not in response.text


async def test_path_traversal_blocked(spa_client):
    response = await spa_client.get("/..%2F..%2Fetc%2Fpasswd")
    assert "root:" not in response.text


async def test_missing_asset_is_404(spa_client):
    response = await spa_client.get("/assets/missing.js")
    assert response.status_code == 404
    assert "id=root" not in response.text


async def test_path_sharing_backend_prefix_falls_back_to_index(spa_client):
    response = await spa_client.get("/healthcheck")
    assert response.status_code == 200
    assert "id=root" in response.text


async def test_extra_leading_slash_missing_asset_is_404(spa_client):
    response = await spa_client.get("http://test//assets/missing.js")
    assert response.status_code == 404
    assert "id=root" not in response.text


async def test_extra_leading_slash_api_path_is_json_404(spa_client):
    response = await spa_client.get("http://test//api/v1/x")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_extra_leading_slash_health_is_not_spa(spa_client):
    response = await spa_client.get("http://test//health")
    assert "id=root" not in response.text


async def test_extra_leading_slash_client_route_falls_back_to_index(spa_client):
    response = await spa_client.get("http://test//runs/abc")
    assert response.status_code == 200
    assert "id=root" in response.text


async def test_extra_leading_slash_absolute_path_not_served(spa_client):
    response = await spa_client.get("http://test//etc/passwd")
    assert "root:" not in response.text


async def test_unknown_path_under_health_is_json_404(spa_client):
    response = await spa_client.get("/health/nope")
    assert response.status_code == 404
    assert "id=root" not in response.text
