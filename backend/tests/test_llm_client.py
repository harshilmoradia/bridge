import asyncio

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import LLMInvalidOutputError, LLMUnavailableError, LLMUpstreamError
from app.llm import LLMClient, get_llm_client
from app.providers.stub import StubProvider
from app.schemas.chat import ChatMessage

MSGS = [ChatMessage(role="user", content="classify BANK019")]
TIERS = ("nano", "super", "ultra")


class Answer(BaseModel):
    kind: str
    ids: list[str]


def make_client(responder=None, **kw) -> tuple[LLMClient, StubProvider]:
    provider = StubProvider(responder=responder)
    client = LLMClient(
        provider,
        models={"nano": "m-nano", "super": "m-super", "ultra": "m-ultra"},
        timeouts={"nano": 1, "super": 1, "ultra": 1},
        **kw,
    )
    return client, provider


@pytest.mark.parametrize("tier", TIERS)
async def test_every_tier_uses_its_model(tier: str) -> None:
    client, provider = make_client()
    text, stats = await client.complete_text(tier, MSGS)
    assert text == "Stub response to: classify BANK019"
    assert stats.model == f"m-{tier}" and stats.tier == tier
    assert stats.prompt_tokens > 0 and stats.completion_tokens > 0
    assert stats.latency_ms >= 0 and stats.attempts == 1
    assert provider.calls == [(f"m-{tier}", False)]


@pytest.mark.parametrize("tier", TIERS)
async def test_json_through_every_tier(tier: str) -> None:
    client, provider = make_client(lambda *_: '{"kind": "bank_fee", "ids": ["BANK019"]}')
    answer, stats = await client.complete_json(tier, MSGS, Answer)
    assert answer == Answer(kind="bank_fee", ids=["BANK019"])
    assert stats.model == f"m-{tier}"
    assert provider.calls == [(f"m-{tier}", True)]


async def test_strips_leading_newline_think_block_and_fence() -> None:
    client, _ = make_client(
        lambda *_: '\n<think>hmm</think>\n```json\n{"kind": "x", "ids": []}\n```'
    )
    answer, _ = await client.complete_json("super", MSGS, Answer)
    assert answer.kind == "x"
    client, _ = make_client(lambda *_: "\nhello\n")
    text, _ = await client.complete_text("nano", MSGS)
    assert text == "hello"


async def test_repairs_invalid_output_and_sums_usage() -> None:
    replies = iter(["not json", '{"kind": 1}', '{"kind": "ok", "ids": []}'])
    seen: list[list[ChatMessage]] = []

    def responder(messages, _model):
        seen.append(messages)
        return next(replies)

    client, provider = make_client(responder)
    answer, stats = await client.complete_json("nano", MSGS, Answer)
    assert answer.kind == "ok"
    assert stats.attempts == 3 and len(provider.calls) == 3
    repair = seen[2][-1]
    assert repair.role == "user" and "kind" in repair.content and "ids" in repair.content
    assert seen[2][-2].content == '{"kind": 1}'


async def test_gives_up_after_two_repairs() -> None:
    client, provider = make_client(lambda *_: "nope")
    with pytest.raises(LLMInvalidOutputError):
        await client.complete_json("nano", MSGS, Answer)
    assert len(provider.calls) == 3


async def test_repair_message_never_echoes_model_output() -> None:
    seen: list[list[ChatMessage]] = []

    def responder(messages, _model):
        seen.append(messages)
        return '{"kind": "SECRET-123"}' if len(seen) == 1 else '{"kind": "a", "ids": []}'

    client, _ = make_client(responder)
    await client.complete_json("nano", MSGS, Answer)
    assert "SECRET-123" not in seen[1][-1].content


async def test_json_response_format_can_be_disabled() -> None:
    client, provider = make_client(lambda *_: '{"kind": "a", "ids": []}', json_response_format=False)
    await client.complete_json("nano", MSGS, Answer)
    assert provider.calls == [("m-nano", False)]


async def test_timeout_raises_unavailable() -> None:
    client, provider = make_client()
    client.timeouts["nano"] = 0.01

    async def slow(*_a, **_k):
        await asyncio.sleep(1)

    provider.generate = slow  # type: ignore[method-assign]
    with pytest.raises(LLMUnavailableError):
        await client.complete_text("nano", MSGS)


def test_get_llm_client_reads_tiers_from_settings() -> None:
    client = get_llm_client(Settings(_env_file=None, llm_provider="stub", model_super="custom/super"))
    assert client.models["super"] == "custom/super"
    assert client.timeouts["ultra"] > client.timeouts["nano"]


@pytest.mark.parametrize("error", [LLMUpstreamError("bad request"), ValueError("provider bug")])
async def test_provider_errors_propagate_without_repair(error: Exception) -> None:
    client, provider = make_client()
    calls = 0

    async def failing(*_a, **_k):
        nonlocal calls
        calls += 1
        raise error

    provider.generate = failing  # type: ignore[method-assign]
    with pytest.raises(type(error)) as caught:
        await client.complete_json("super", MSGS, Answer)
    assert caught.value is error
    assert calls == 1


async def test_strips_reasoning_when_template_prefilled_think_tag() -> None:
    client, _ = make_client(lambda *_: 'step 1... step 2\n</think>\n\n{"kind": "x", "ids": []}')
    answer, _ = await client.complete_json("super", MSGS, Answer)
    assert answer.kind == "x"
