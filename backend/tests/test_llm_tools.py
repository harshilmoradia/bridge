"""LLMClient.complete_tools: native tool loop with Pydantic-validated arguments, capped turns."""

import json

from pydantic import BaseModel

from app.llm import LLMClient
from app.llm.tools import Tool
from app.providers.base import AgentMessage, Completion, ToolCall
from app.providers.stub import StubProvider
from app.schemas.chat import ChatMessage

MSGS = [ChatMessage(role="user", content="resolve BANK032")]


class RuleArgs(BaseModel):
    description: str


def make(responder):
    provider = StubProvider(responder=responder)
    client = LLMClient(
        provider,
        models={"nano": "m-nano", "super": "m-super", "ultra": "m-ultra"},
        timeouts={"nano": 1, "super": 1, "ultra": 1},
    )
    return client, provider


def call(name: str, args: str, cid: str = "c1") -> Completion:
    return Completion(content="", model="m-super", prompt_tokens=10, completion_tokens=2,
                      tool_calls=(ToolCall(id=cid, name=name, arguments=args),))


def find_rules_tool(seen: list) -> Tool:
    def run(args: RuleArgs) -> dict:
        seen.append(args)
        return {"rules": []}

    return Tool("find_rules", "Find learned rules.", RuleArgs, run)


async def test_runs_tool_then_returns_final_text() -> None:
    replies = iter([call("find_rules", '{"description": "MONTHLY SERVICE FEE"}'),
                    "Bank fee, no rule."])
    seen_msgs: list = []

    def responder(messages, _m):
        seen_msgs.append(messages)
        return next(replies)

    client, provider = make(responder)
    seen: list = []
    run, stats = await client.complete_tools("super", MSGS, [find_rules_tool(seen)])
    assert run.text == "Bank fee, no rule."
    assert seen == [RuleArgs(description="MONTHLY SERVICE FEE")]
    assert [(s.name, s.ok) for s in run.steps] == [("find_rules", True)]
    assert stats.attempts == 2 and stats.model == "m-super"
    assert stats.prompt_tokens >= 10
    # Second turn carries the assistant tool call and the tool result.
    assistant, tool_msg = seen_msgs[1][-2:]
    assert isinstance(assistant, AgentMessage) and assistant.tool_calls[0].id == "c1"
    assert tool_msg.role == "tool" and tool_msg.tool_call_id == "c1"
    assert json.loads(tool_msg.content) == {"rules": []}
    spec = provider.tools_seen[0][0]["function"]
    assert spec["name"] == "find_rules" and "description" in spec["parameters"]["properties"]


async def test_invalid_arguments_go_back_as_tool_error_without_echo() -> None:
    replies = iter([call("find_rules", '{"pattern": "SECRET-XYZ"}'),
                    call("find_rules", "not json", "c2"),
                    call("nope", "{}", "c3"),
                    "done"])
    seen_msgs: list = []

    def responder(messages, _m):
        seen_msgs.append(messages)
        return next(replies)

    client, _ = make(responder)
    seen: list = []
    run, _ = await client.complete_tools("super", MSGS, [find_rules_tool(seen)])
    assert run.text == "done" and seen == []
    assert [(s.name, s.ok) for s in run.steps] == [
        ("find_rules", False), ("find_rules", False), ("nope", False)]
    errors = [m.content for m in seen_msgs[-1] if m.role == "tool"]
    assert len(errors) == 3
    assert all("error" in json.loads(e) for e in errors)
    assert not any("SECRET-XYZ" in e for e in errors)
    assert "description" in errors[0]


async def test_caps_at_six_turns() -> None:
    client, provider = make(lambda *_: call("find_rules", '{"description": "x"}'))
    run, stats = await client.complete_tools("super", MSGS, [find_rules_tool([])])
    assert run.text is None and run.exhausted
    assert len(provider.calls) == 6 and stats.attempts == 6


async def test_network_error_retried_once_but_timeout_is_not() -> None:
    from app.core.errors import LLMUnavailableError

    client, provider = make(lambda *_: "ok")
    real = provider.generate
    fails = iter([LLMUnavailableError("Unable to reach LLM provider")])

    async def flaky(*a, **k):
        err = next(fails, None)
        if err:
            raise err
        return await real(*a, **k)

    provider.generate = flaky  # type: ignore[method-assign]
    run, _ = await client.complete_tools("super", MSGS, [find_rules_tool([])])
    assert run.text == "ok"

    import asyncio

    import pytest

    calls = 0

    async def slow(*_a, **_k):
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    client.timeouts["super"] = 0.01
    provider.generate = slow  # type: ignore[method-assign]
    with pytest.raises(LLMUnavailableError):
        await client.complete_tools("super", MSGS, [find_rules_tool([])])
    assert calls == 1


async def test_async_tool_handler_is_awaited() -> None:
    replies = iter([call("find_rules", '{"description": "x"}'), "ok"])

    async def run_async(args: RuleArgs) -> dict:
        return {"rules": [{"id": 1}]}

    client, _ = make(lambda *_: next(replies))
    run, _ = await client.complete_tools(
        "super", MSGS, [Tool("find_rules", "d", RuleArgs, run_async)])
    assert run.text == "ok" and run.steps[0].ok
