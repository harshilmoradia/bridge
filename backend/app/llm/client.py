"""Tiered LLM client: tier -> model, JSON mode with repair retries, timeouts, usage capture.

Agents call `complete_json(tier, messages, Schema)`. Every call returns `CallStats`
(model, latency, tokens, attempts) for the `run_steps` row.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import LLMInvalidOutputError, LLMUnavailableError
from app.providers.base import LLMProvider, get_llm_provider
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

    async def _call(
        self, tier: Tier, messages: list[ChatMessage], *, json_mode: bool
    ) -> tuple[str, CallStats]:
        model, timeout = self.models[tier], self.timeouts[tier]
        start = time.perf_counter()
        try:
            async with asyncio.timeout(timeout):
                result = await self.provider.generate(
                    messages, model, json_mode=json_mode, timeout=timeout
                )
        except TimeoutError as exc:
            raise LLMUnavailableError(f"{tier} call timed out after {timeout:g}s") from exc
        stats = CallStats(
            tier=tier,
            model=result.model,
            latency_ms=round((time.perf_counter() - start) * 1000),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        return result.content, stats


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
