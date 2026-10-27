import json

import httpx
import pytest

from app.core.errors import LLMUnavailableError, LLMUpstreamError
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.schemas.chat import ChatMessage

MSGS = [ChatMessage(role="user", content="hi")]


def ok_body(**extra) -> dict:
    return {
        "model": "nvidia/returned",
        "choices": [{"message": {"role": "assistant", "content": '{"a": 1}'}}],
        **extra,
    }


@pytest.fixture
def transport(monkeypatch):
    """Route the provider's httpx.AsyncClient through a MockTransport; record requests."""
    state: dict = {"handler": None, "requests": [], "timeouts": []}
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["handler"](request)

    def fake_client(*args, **kwargs):
        state["timeouts"].append(kwargs.get("timeout"))
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    return state


def provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key="k", base_url="https://example.test/v1/", default_model="default"
    )


async def test_parses_content_model_and_usage(transport) -> None:
    transport["handler"] = lambda _r: httpx.Response(
        200, json=ok_body(usage={"prompt_tokens": 12, "completion_tokens": 5})
    )
    result = await provider().generate(MSGS, "m-nano", timeout=7)
    assert result.content == '{"a": 1}'
    assert result.model == "nvidia/returned"
    assert (result.prompt_tokens, result.completion_tokens) == (12, 5)
    request = transport["requests"][0]
    assert str(request.url) == "https://example.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer k"
    assert json.loads(request.content)["model"] == "m-nano"
    assert transport["timeouts"] == [7]


async def test_response_format_only_in_json_mode(transport) -> None:
    transport["handler"] = lambda _r: httpx.Response(200, json=ok_body())
    await provider().generate(MSGS)
    await provider().generate(MSGS, json_mode=True)
    plain, json_call = (json.loads(r.content) for r in transport["requests"])
    assert "response_format" not in plain
    assert json_call["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("usage", [None, {}, "garbage", {"prompt_tokens": "x"}])
async def test_missing_or_malformed_usage_is_zero(transport, usage) -> None:
    body = ok_body() if usage is None else ok_body(usage=usage)
    transport["handler"] = lambda _r: httpx.Response(200, json=body)
    result = await provider().generate(MSGS)
    assert (result.prompt_tokens, result.completion_tokens) == (0, 0)
    assert result.content == '{"a": 1}'


@pytest.mark.parametrize("status", [400, 401, 422])
async def test_4xx_is_upstream_error(transport, status) -> None:
    transport["handler"] = lambda _r: httpx.Response(status, json={"error": "no"})
    with pytest.raises(LLMUpstreamError):
        await provider().generate(MSGS)


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_is_unavailable(transport, status) -> None:
    transport["handler"] = lambda _r: httpx.Response(status)
    with pytest.raises(LLMUnavailableError):
        await provider().generate(MSGS)


async def test_httpx_timeout_is_unavailable(transport) -> None:
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    transport["handler"] = handler
    with pytest.raises(LLMUnavailableError):
        await provider().generate(MSGS)


async def test_complete_still_returns_message_and_model(transport) -> None:
    transport["handler"] = lambda _r: httpx.Response(200, json=ok_body())
    message, model = await provider().complete(MSGS)
    assert message.role == "assistant" and message.content == '{"a": 1}'
    assert model == "nvidia/returned"
