"""Pipelines the eval can score. Each is an async `(Dataset) -> PipelineResult` and reads only
demo-data/ (never the answer key).

`rules_only` is the code-only baseline: the B-03 matcher plus the policy gate on its match kinds.
It has no classify or resolve step, so whatever the matcher cannot pair stays undecided (kind
`unknown`, no resolution).

`models_off` is the floor: the agent pipeline over a provider that is always unavailable, so every
model stage falls back to code (no API calls).

`tiered` runs the real agent pipeline (`run_agents`) with the production tier map; `nano`, `super`
and `ultra` run it with every call forced onto one tier (`LLMClient.forced`, an eval-only hook). The
client comes from settings (`backend/.env`), so a live run calls Token Factory. No learned rules are
loaded: the eval scores the agents alone.
"""

import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.recon.loader import DATA_DIR
from app.recon.matcher import load_match_policy, match
from app.recon.matching_models import Match
from app.recon.models import Dataset, ProposedEntry
from app.agents.pipeline import run_agents
from app.core.config import get_settings
from app.core.errors import LLMUnavailableError
from app.llm import LLMClient, Tier
from app.llm.client import get_llm_client
from app.providers.base import Completion, LLMProvider
from app.schemas.chat import ChatMessage
from evals.pricing import estimate_cost
from evals.types import EvalItem, Pipeline, PipelineResult, Usage


def _write_off(m: Match, cash: str, account: str) -> ProposedEntry:
    """Move the book onto the bank amount: a bank shortfall credits cash, a surplus debits it."""
    short = m.amount_delta < 0
    return ProposedEntry(
        debit_account=account if short else cash,
        credit_account=cash if short else account,
        amount=abs(m.amount_delta),
        memo=f"Rounding write-off {', '.join((*m.bank_ids, *m.gl_ids))}",
    )


async def rules_only(dataset: Dataset, data_dir: Path = DATA_DIR) -> PipelineResult:
    policy = json.loads((data_dir / "policy.json").read_text(encoding="utf-8"), parse_float=Decimal)
    auto_kinds = set(policy["auto_resolve_kinds"])
    cash = dataset.balances.cash_account
    result = match(dataset.bank, dataset.gl, load_match_policy(data_dir))

    items: list[EvalItem] = []
    for m in result.matches:
        if m.kind not in auto_kinds:
            items.append(EvalItem(kind=m.kind, resolution=None, bank_ids=m.bank_ids, gl_ids=m.gl_ids))
        elif m.kind == "rounding":
            entry = _write_off(m, cash, policy["auto_writeoff_account"])
            items.append(EvalItem(
                kind=m.kind, resolution="auto_match_with_writeoff", bank_ids=m.bank_ids, gl_ids=m.gl_ids, entry=entry
            ))
        else:
            items.append(EvalItem(kind=m.kind, resolution="auto_match", bank_ids=m.bank_ids, gl_ids=m.gl_ids))
    # Candidate groups need the fuzzy step to pick an option; rules-only leaves each group open.
    for c in result.candidates:
        items.append(EvalItem(kind="unknown", resolution=None, bank_ids=c.bank_ids, gl_ids=c.gl_ids))
    for b in result.unmatched_bank_ids:
        items.append(EvalItem(kind="unknown", resolution=None, bank_ids=(b,), gl_ids=()))
    for g in result.unmatched_gl_ids:
        items.append(EvalItem(kind="unknown", resolution=None, bank_ids=(), gl_ids=(g,)))
    return PipelineResult(items=tuple(items))


class RecordingProvider:
    """Passes calls through and counts calls and tokens per requested model."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.by_model: dict[str, list[int]] = {}  # model -> [calls, tokens_in, tokens_out]

    async def generate(self, messages: Sequence[ChatMessage], model: str | None = None,
                       **kwargs: Any) -> Completion:
        out = await self.inner.generate(messages, model, **kwargs)
        row = self.by_model.setdefault(model or out.model, [0, 0, 0])
        row[0] += 1
        row[1] += out.prompt_tokens
        row[2] += out.completion_tokens
        return out

    async def complete(self, messages: list[ChatMessage], model: str | None = None):
        return await self.inner.complete(messages, model)


def usage(recorder: RecordingProvider, models: dict[str, str]) -> Usage:
    tier_of = {model: tier for tier, model in models.items()}
    by_tier: dict[str, tuple[int, int]] = {}
    calls_by_tier: dict[str, int] = {}
    for model, (calls, tokens_in, tokens_out) in recorder.by_model.items():
        tier = tier_of[model]
        prev = by_tier.get(tier, (0, 0))
        by_tier[tier] = (prev[0] + tokens_in, prev[1] + tokens_out)
        calls_by_tier[tier] = calls_by_tier.get(tier, 0) + calls
    return Usage(calls=sum(r[0] for r in recorder.by_model.values()),
                 tokens_in=sum(i for i, _ in by_tier.values()), tokens_out=sum(o for _, o in by_tier.values()),
                 tokens_by_tier=by_tier, calls_by_tier=dict(sorted(calls_by_tier.items())),
                 cost_usd=estimate_cost(by_tier),
                 models={tier_of[m]: m for m in recorder.by_model})


def _cash_entry(entry) -> ProposedEntry | None:
    if entry is None:
        return None
    return ProposedEntry(debit_account=entry.debit_account, credit_account=entry.credit_account,
                         amount=entry.amount, memo=entry.memo)


def agent_pipeline(force_tier: Tier | None, make_client: Callable[[], LLMClient] | None = None) -> Pipeline:
    """The agent pipeline as an eval adapter; `force_tier` None is the production tier map."""

    async def run(dataset: Dataset) -> PipelineResult:
        base = make_client() if make_client else get_llm_client(get_settings())
        recorder = RecordingProvider(base.provider)
        result = await run_agents(dataset, base.forced(force_tier, provider=recorder))
        items = tuple(EvalItem(kind=a.kind, resolution=a.resolution, bank_ids=tuple(a.bank_ids),
                               gl_ids=tuple(a.gl_ids), entry=_cash_entry(a.entry)) for a in result.items)
        return PipelineResult(items=items, usage=usage(recorder, base.models), steps=tuple(result.steps))

    return run


class UnavailableProvider:
    """Every call fails as an outage: the agents fall back to code everywhere."""

    async def generate(self, messages: Sequence[ChatMessage], model: str | None = None,
                       **kwargs: Any) -> Completion:
        raise LLMUnavailableError("models off (eval floor)")

    async def complete(self, messages: list[ChatMessage], model: str | None = None):
        raise LLMUnavailableError("models off (eval floor)")


def _models_off_client() -> LLMClient:
    models = {"nano": "off-nano", "super": "off-super", "ultra": "off-ultra"}
    return LLMClient(UnavailableProvider(), models=models, timeouts={t: 1.0 for t in models})


# Pipeline name -> forced tier (None: the production tier map).
TIERS: dict[str, Tier | None] = {"tiered": None, "nano": "nano", "super": "super", "ultra": "ultra"}

PIPELINES: dict[str, Pipeline] = {"rules": rules_only, **{name: agent_pipeline(t) for name, t in TIERS.items()},
                                  "models_off": agent_pipeline(None, make_client=_models_off_client)}
