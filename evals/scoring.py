"""Score a pipeline's items against evals/ground_truth.json.

A pipeline is any async callable `(Dataset) -> PipelineResult`. The scorer knows nothing about
how the items were made, so the rules-only baseline and B-09's agent pipeline are scored the same way.

Items are compared by their row sets: a pipeline item corresponds to a ground-truth item only
when both cite exactly the same bank IDs and GL IDs.
"""

import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, computed_field

from app.recon.models import Dataset, ProposedEntry
from app.recon.statement import build_statement
from app.recon.store import ItemRef
from app.schemas.runs import Resolution
from evals.types import EvalItem, PipelineResult, RowKey

GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth.json"

# How a run stores each resolution. None means the pipeline left the item open.
STATUS = {
    "auto_match": "matched",
    "auto_match_with_writeoff": "auto_resolved",
    "reconciling_item": "reconciling_item",
    "escalate": "needs_approval",
    None: "unmatched",
}
# Closed without a human: wrong ones are false auto-resolutions.
AUTO_CLOSED = frozenset({"auto_match", "auto_match_with_writeoff", "reconciling_item"})

class TruthItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    resolution: Resolution
    bank_ids: tuple[str, ...]
    gl_ids: tuple[str, ...]
    expected_entry: ProposedEntry | None = None

    @property
    def key(self) -> RowKey:
        return frozenset(self.bank_ids), frozenset(self.gl_ids)


class GroundTruth(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_difference: Decimal
    items: tuple[TruthItem, ...]


def load_ground_truth(path: Path = GROUND_TRUTH_PATH) -> GroundTruth:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for t in raw["items"]:
        e = t.get("expected_entry")
        entry = e and ProposedEntry(
            debit_account=e["debit"], credit_account=e["credit"], amount=Decimal(e["amount"]), memo=e["memo"]
        )
        items.append(TruthItem(**{k: t[k] for k in ("id", "kind", "resolution", "bank_ids", "gl_ids")}, expected_entry=entry))
    return GroundTruth(
        expected_difference=Decimal(raw["summary"]["unreconciled_difference_after_all_resolutions"]),
        items=tuple(items),
    )


class Ratio(BaseModel):
    model_config = ConfigDict(frozen=True)

    hit: int
    total: int

    @computed_field
    @property
    def value(self) -> float | None:
        """None when nothing could be scored, shown as N/A."""
        return round(self.hit / self.total, 4) if self.total else None


class FalseAuto(BaseModel):
    """An item the pipeline closed without a human that the answer key does not close that way."""

    model_config = ConfigDict(frozen=True)

    kind: str
    resolution: Resolution
    bank_ids: tuple[str, ...]
    gl_ids: tuple[str, ...]
    expected: str | None  # the answer key's resolution for these rows, or None if no item has them


class Scores(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_precision: Ratio
    match_recall: Ratio
    kind_accuracy: Ratio
    kind_accuracy_by_kind: dict[str, Ratio]
    correct_escalations: Ratio
    escalated: int  # everything the pipeline escalated, right or wrong
    false_auto_resolutions: list[FalseAuto]
    entry_correctness: Ratio
    unresolved: int  # items the pipeline left without a decision
    uncovered_rows: int  # dataset rows no item cites, so a pipeline cannot drop rows silently
    final_difference: Decimal  # as the run leaves it: escalations still pending
    difference_after_approvals: Decimal  # once every escalation is approved as drafted
    expected_difference: Decimal
    missed_truth_ids: list[str]  # answer-key items with no pipeline item on the same rows


def _pairs(items) -> set[tuple[str, str]]:
    return {(b, g) for i in items for b in i.bank_ids for g in i.gl_ids}


def _same_entry(got: ProposedEntry | None, want: ProposedEntry) -> bool:
    # The memo is free text, so only accounts and amount are compared.
    return got is not None and (got.debit_account, got.credit_account, got.amount) == (
        want.debit_account, want.credit_account, want.amount
    )


def _right_auto(item: EvalItem, truth: TruthItem | None) -> bool:
    """An auto-closed item is right when the key closes the same rows the same way. A write-off
    also posts its entry without approval, so that entry has to match the key's as well."""
    if truth is None or truth.resolution != item.resolution:
        return False
    if item.resolution == "auto_match_with_writeoff":
        return truth.expected_entry is not None and _same_entry(item.entry, truth.expected_entry)
    return True


def _uncovered_rows(dataset: Dataset, items: tuple[EvalItem, ...]) -> int:
    """Reject rows cited twice or not in the dataset; return how many dataset rows no item cites."""
    known = {t.txn_id for t in dataset.bank} | {e.entry_id for e in dataset.gl}
    seen: set[str] = set()
    for item in items:
        for row in (*item.bank_ids, *item.gl_ids):
            if row not in known:
                raise ValueError(f"Pipeline item cites a row not in the dataset: {row}")
            if row in seen:
                raise ValueError(f"Pipeline cites row {row} in more than one item")
            seen.add(row)
    return len(known - seen)


def _difference(dataset: Dataset, items: tuple[EvalItem, ...], approve: bool) -> Decimal:
    refs = []
    for n, item in enumerate(items):
        status = STATUS[item.resolution]
        if approve and status == "needs_approval":
            status = "approved"
        refs.append(ItemRef(
            id=f"eval-{n}", status=status, kind=item.kind,
            bank_ids=item.bank_ids, gl_ids=item.gl_ids, entry=item.entry,
        ))
    return build_statement(dataset, None, refs).unreconciled_difference


def score(dataset: Dataset, truth: GroundTruth, result: PipelineResult) -> Scores:
    items = result.items
    uncovered = _uncovered_rows(dataset, items)
    by_key = {i.key: i for i in items}
    truth_by_key = {t.key: t for t in truth.items}

    # An undecided item (say, a candidate group the fuzzy step never ran on) claims no match.
    got_pairs, want_pairs = _pairs(i for i in items if i.resolution is not None), _pairs(truth.items)
    hit_pairs = len(got_pairs & want_pairs)

    kinds: dict[str, list[int]] = {}
    for t in truth.items:
        counts = kinds.setdefault(t.kind, [0, 0])
        counts[1] += 1
        got = by_key.get(t.key)
        counts[0] += got is not None and got.kind == t.kind

    escalations = [t for t in truth.items if t.resolution == "escalate"]
    with_entry = [t for t in truth.items if t.expected_entry is not None]
    false_auto = [
        FalseAuto(
            kind=i.kind, resolution=i.resolution, bank_ids=i.bank_ids, gl_ids=i.gl_ids,
            expected=truth_by_key[i.key].resolution if i.key in truth_by_key else None,
        )
        for i in items
        if i.resolution in AUTO_CLOSED and not _right_auto(i, truth_by_key.get(i.key))
    ]

    return Scores(
        match_precision=Ratio(hit=hit_pairs, total=len(got_pairs)),
        match_recall=Ratio(hit=hit_pairs, total=len(want_pairs)),
        kind_accuracy=Ratio(hit=sum(c[0] for c in kinds.values()), total=len(truth.items)),
        kind_accuracy_by_kind={k: Ratio(hit=c[0], total=c[1]) for k, c in sorted(kinds.items())},
        correct_escalations=Ratio(
            hit=sum(1 for t in escalations if t.key in by_key and by_key[t.key].resolution == "escalate"),
            total=len(escalations),
        ),
        escalated=sum(1 for i in items if i.resolution == "escalate"),
        false_auto_resolutions=false_auto,
        entry_correctness=Ratio(
            hit=sum(1 for t in with_entry if t.key in by_key and _same_entry(by_key[t.key].entry, t.expected_entry)),
            total=len(with_entry),
        ),
        unresolved=sum(1 for i in items if i.resolution is None),
        uncovered_rows=uncovered,
        final_difference=_difference(dataset, items, approve=False),
        difference_after_approvals=_difference(dataset, items, approve=True),
        expected_difference=truth.expected_difference,
        missed_truth_ids=[t.id for t in truth.items if t.key not in by_key],
    )
