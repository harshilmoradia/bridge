"""What a pipeline hands the eval. Pipelines import this module only, never the scorer or the answer key."""

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

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


class PipelineResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[EvalItem, ...]


Pipeline = Callable[[Dataset], Awaitable[PipelineResult]]
