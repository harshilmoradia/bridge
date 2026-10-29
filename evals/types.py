"""What a pipeline hands the eval. Pipelines import this module only, never the scorer or the answer key."""

from collections.abc import Awaitable, Callable
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.agents.models import StepLog
from app.recon.models import Dataset, ProposedEntry
from app.schemas.runs import Resolution

RowKey = tuple[frozenset[str], frozenset[str]]


class EvalItem(BaseModel):
    """One item as a pipeline returns it: its rows, its kind and decision, and its draft entry."""

    model_config = ConfigDict(frozen=True)

    kind: str
    resolution: Resolution | None  # None: the pipeline did not decide this item
    bank_ids: tuple[str, ...]
    gl_ids: tuple[str, ...]
    entry: ProposedEntry | None = None

    @property
    def key(self) -> RowKey:
        return frozenset(self.bank_ids), frozenset(self.gl_ids)


class Usage(BaseModel):
    """LLM calls a pipeline made: totals, tokens per tier and the estimated cost (evals/pricing.py)."""

    model_config = ConfigDict(frozen=True)

    calls: int
    tokens_in: int
    tokens_out: int
    tokens_by_tier: dict[str, tuple[int, int]]  # tier -> (tokens_in, tokens_out)
    calls_by_tier: dict[str, int] = {}  # tier -> calls
    cost_usd: Decimal
    models: dict[str, str] = {}  # tier -> model id called


class PipelineResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[EvalItem, ...]
    usage: Usage | None = None  # None: the pipeline made no model calls
    steps: tuple[StepLog, ...] = ()  # the agent stages' logs: counts and stats only, never row text


Pipeline = Callable[[Dataset], Awaitable[PipelineResult]]
