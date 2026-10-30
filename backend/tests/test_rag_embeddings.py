import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import LLMUnavailableError, LLMUpstreamError
from app.rag.embeddings import NebiusEmbeddingProvider, get_embedding_provider


@pytest.fixture
def transport(monkeypatch):
    state: dict = {"handler": None, "requests": []}
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["handler"](request)

    def fake_client(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    return state


def _provider() -> NebiusEmbeddingProvider:
    return NebiusEmbeddingProvider(
        api_key="test-key", base_url="https://api.tokenfactory.nebius.com/v1",
        model="BAAI/bge-en-icl", dimensions=3,
    )


def _body(vectors: list[list[float]]) -> dict:
    return {
        "model": "BAAI/bge-en-icl",
        "data": [{"index": i, "embedding": vector} for i, vector in enumerate(vectors)],
    }


async def test_embedding_request_uses_nebius_openai_compatible_contract(transport) -> None:
    transport["handler"] = lambda _request: httpx.Response(200, json=_body([[0.1, 0.2, 0.3]]))
    vectors = await _provider().embed(["masked transaction memo [PERSON]"])

    request = transport["requests"][0]
    assert str(request.url) == "https://api.tokenfactory.nebius.com/v1/embeddings"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert json.loads(request.content) == {
        "model": "BAAI/bge-en-icl",
        "input": ["masked transaction memo [PERSON]"],
        "dimensions": 3,
        "encoding_format": "float",
    }
    assert vectors == [[0.1, 0.2, 0.3]]


async def test_embeddings_are_returned_in_input_order(transport) -> None:
    transport["handler"] = lambda _request: httpx.Response(200, json={
        "model": "BAAI/bge-en-icl",
        "data": [
            {"index": 1, "embedding": [4, 5, 6]},
            {"index": 0, "embedding": [1, 2, 3]},
        ],
    })
    assert await _provider().embed(["first", "second"]) == [[1, 2, 3], [4, 5, 6]]


async def test_empty_input_makes_no_request(transport) -> None:
    assert await _provider().embed([]) == []
    assert transport["requests"] == []


@pytest.mark.parametrize("body", [
    {"data": []},
    {"data": [{"index": 0, "embedding": [1, 2]}]},
    {"data": [{"index": 1, "embedding": [1, 2, 3]}]},
    {"data": [{"index": 0, "embedding": [1, True, 3]}]},
    {"data": [{"index": 0, "embedding": [1, "NaN", 3]}]},
])
async def test_invalid_embedding_response_fails_without_echoing_body(transport, body) -> None:
    transport["handler"] = lambda _request: httpx.Response(200, json=body)
    with pytest.raises(LLMUpstreamError) as error:
        await _provider().embed(["sensitive text"])
    assert error.value.diagnostic_code == "invalid_embedding_response"
    assert "sensitive text" not in error.value.message


async def test_non_finite_embedding_values_are_rejected(transport) -> None:
    transport["handler"] = lambda _request: httpx.Response(
        200, content=b'{"data":[{"index":0,"embedding":[1,NaN,3]}]}'
    )
    with pytest.raises(LLMUpstreamError) as error:
        await _provider().embed(["sensitive text"])
    assert error.value.diagnostic_code == "invalid_embedding_response"


@pytest.mark.parametrize("status", [400, 401, 422])
async def test_provider_4xx_is_sanitized_upstream_error(transport, status) -> None:
    transport["handler"] = lambda _request: httpx.Response(status, json={"detail": "sensitive"})
    with pytest.raises(LLMUpstreamError) as error:
        await _provider().embed(["sensitive"])
    assert error.value.diagnostic_code == f"embedding_http_{status}"
    assert "sensitive" not in error.value.message


async def test_provider_5xx_is_unavailable(transport) -> None:
    transport["handler"] = lambda _request: httpx.Response(503)
    with pytest.raises(LLMUnavailableError) as error:
        await _provider().embed(["text"])
    assert error.value.diagnostic_code == "embedding_provider_error"


async def test_timeout_is_sanitized_unavailable(transport) -> None:
    def timeout(request):
        raise httpx.ReadTimeout("sensitive", request=request)

    transport["handler"] = timeout
    with pytest.raises(LLMUnavailableError) as error:
        await _provider().embed(["sensitive text"])
    assert error.value.diagnostic_code == "embedding_timeout"
    assert "sensitive text" not in error.value.message


def test_factory_reuses_llm_key_only_for_nebius() -> None:
    nebius = Settings(_env_file=None, llm_api_key="nebius-key",
                      llm_base_url="https://api.tokenfactory.nebius.com/v1/")
    other = Settings(_env_file=None, llm_api_key="other-key", llm_base_url="https://api.openai.com/v1")
    no_key = Settings(_env_file=None, llm_api_key="", llm_base_url="https://api.tokenfactory.nebius.com/v1")

    assert get_embedding_provider(nebius) is not None
    assert get_embedding_provider(other) is None
    assert get_embedding_provider(no_key) is None


def test_settings_reject_model_that_does_not_match_fixed_vector_dimension() -> None:
    settings = Settings(_env_file=None)
    assert settings.rag_embedding_model == "Qwen/Qwen3-Embedding-8B"
    with pytest.raises(ValueError, match="verified Nebius model"):
        Settings(_env_file=None, rag_embedding_model="BAAI/bge-en-icl")
