"""Tiered LLM client: tier -> model, JSON mode with repair retries, timeouts, usage capture.

Agents call `complete_json(tier, messages, Schema)` or, for the tool-using resolve agent,
`complete_tools(tier, messages, tools)` (native OpenAI tools, decided in B-07). Every call returns `CallStats`
(model, latency, tokens, attempts) for the `run_steps` row.
"""

import asyncio
import inspect
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import LLMInvalidOutputError, LLMUnavailableError
from app.llm.tools import Tool, ToolRun, ToolStep
from app.providers.base import (
    AgentMessage,
    Completion,
    LLMProvider,
    ToolCall,
    get_llm_provider,
)
from app.schemas.chat import ChatMessage

Tier = Literal["nano", "super", "ultra"]
T = TypeVar("T", bound=BaseModel)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True)
class CallStats:
    tier: Tier
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    attempts: int = 1


def clean_output(text: str) -> str:
    """Drop reasoning blocks and the leading newline reasoning models emit."""
    text = _THINK.sub("", text)
    # Templates that pre-fill <think> in the prompt leave only the closing tag.
    return text.rpartition("</think>")[2].strip()


def _extract_json(text: str) -> str:
    text = clean_output(text)
    fenced = _FENCE.match(text)
    return fenced.group(1) if fenced else text


def _problem(exc: Exception) -> str:
    # Location and reason only: never echo model output or untrusted input back.
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
    return "the reply was not valid JSON"


class LLMClient:
    def __init__(
        self,
        provider: LLMProvider,
        models: dict[Tier, str],
        timeouts: dict[Tier, float],
        *,
        json_response_format: bool = True,
        max_repairs: int = 2,
    ) -> None:
        self.provider = provider
        self.models = models
        self.timeouts = timeouts
        self.json_response_format = json_response_format
        self.max_repairs = max_repairs

    async def complete_text(
        self, tier: Tier, messages: list[ChatMessage]
    ) -> tuple[str, CallStats]:
        text, stats = await self._call(tier, messages, json_mode=False)
        return clean_output(text), stats

    async def complete_json(
        self, tier: Tier, messages: list[ChatMessage], schema: type[T]
    ) -> tuple[T, CallStats]:
        convo = list(messages)
        total: CallStats | None = None
        for attempt in range(1, self.max_repairs + 2):
            text, stats = await self._call(
                tier, convo, json_mode=self.json_response_format
            )
            total = _merge(total, stats, attempt)
            try:
                return schema.model_validate(json.loads(_extract_json(text))), total
            except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
                problem = _problem(exc)
            convo = [
                *convo,
                ChatMessage(role="assistant", content=text),
                ChatMessage(
                    role="user",
                    content=f"That reply was rejected: {problem}. "
                    "Reply again with only a JSON object matching the schema.",
                ),
            ]
        raise LLMInvalidOutputError(
            f"{tier} output failed validation after {self.max_repairs + 1} attempts: {problem}"
        )

    async def complete_tools(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        tools: list[Tool],
        *,
        max_turns: int = 6,
    ) -> tuple[ToolRun, CallStats]:
        """Native tool loop: the model calls tools until it answers in text or hits `max_turns`.

        Arguments are validated against each tool's Pydantic model. A bad call goes back to
        the model as a tool error naming the field and reason, never the rejected value.
        """
        by_name = {tool.name: tool for tool in tools}
        specs = [tool.spec() for tool in tools]
        convo: list[ChatMessage] = list(messages)
        steps: list[ToolStep] = []
        total: CallStats | None = None
        for turn in range(1, max_turns + 1):
            result, stats = await self._generate(tier, convo, json_mode=False, tools=specs)
            total = _merge(total, stats, turn)
            if not result.tool_calls:
                return ToolRun(text=clean_output(result.content), steps=tuple(steps)), total
            convo.append(AgentMessage(
                role="assistant", content=result.content, tool_calls=list(result.tool_calls)))
            for call in result.tool_calls:
                output, ok = await _run_tool(by_name.get(call.name), call)
                steps.append(ToolStep(name=call.name, ok=ok))
                convo.append(AgentMessage(
                    role="tool", content=json.dumps(output), tool_call_id=call.id))
        assert total is not None
        return ToolRun(text=None, steps=tuple(steps)), total

    async def _call(
        self, tier: Tier, messages: list[ChatMessage], *, json_mode: bool
    ) -> tuple[str, CallStats]:
        result, stats = await self._generate(tier, messages, json_mode=json_mode)
        return result.content, stats

    async def _generate(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        *,
        json_mode: bool,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[Completion, CallStats]:
        model, timeout = self.models[tier], self.timeouts[tier]
        start = time.perf_counter()
        for attempt in (1, 2):
            try:
                async with asyncio.timeout(timeout):
                    result = await self.provider.generate(
                        messages, model, json_mode=json_mode, timeout=timeout,
                        **({"tools": tools} if tools else {}),
                    )
                break
            except TimeoutError as exc:
                # Not retried: a stalled call already cost the full timeout.
                raise LLMUnavailableError(f"{tier} call timed out after {timeout:g}s") from exc
            except LLMUnavailableError:
                # Network blips (ReadError, 5xx) seen live under parallel load: retry once.
                if attempt == 2:
                    raise
        stats = CallStats(
            tier=tier,
            model=result.model,
            latency_ms=round((time.perf_counter() - start) * 1000),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        return result, stats


async def _run_tool(tool: Tool | None, call: ToolCall) -> tuple[dict[str, Any], bool]:
    if tool is None:
        return {"error": "unknown tool"}, False
    try:
        args = tool.args.model_validate_json(call.arguments)
    except ValidationError as exc:
        return {"error": f"invalid arguments: {_problem(exc)}"}, False
    output = tool.run(args)
    if inspect.isawaitable(output):
        output = await output
    return output, True


def _merge(total: CallStats | None, stats: CallStats, attempt: int) -> CallStats:
    if total is None:
        return stats
    return CallStats(
        tier=stats.tier,
        model=stats.model,
        latency_ms=total.latency_ms + stats.latency_ms,
        prompt_tokens=total.prompt_tokens + stats.prompt_tokens,
        completion_tokens=total.completion_tokens + stats.completion_tokens,
        attempts=attempt,
    )


def get_llm_client(settings: Settings) -> LLMClient:
    return LLMClient(
        get_llm_provider(settings),
        models={
            "nano": settings.model_nano,
            "super": settings.model_super,
            "ultra": settings.model_ultra,
        },
        timeouts={
            "nano": settings.llm_timeout_nano,
            "super": settings.llm_timeout_super,
            "ultra": settings.llm_timeout_ultra,
        },
        json_response_format=settings.llm_json_response_format,
    )
