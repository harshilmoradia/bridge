"""What the agents pass between steps. Money is Decimal; positive means money into the bank.

`amount_delta` is always bank total minus GL total for the item's rows, computed by code.
A draft entry that fixes an item debits cash (1010) when the delta is positive and credits
it when negative, for `abs(amount_delta)`.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.runs import Evidence, ItemFlag, ItemKind, Resolution
from app.schemas.common import ItemStatus

Source = Literal["rules", "fuzzy", "classify", "code"]  # code: pre-labelled (agents/prelabel.py)

# Kinds classify may assign. Rule kinds (exact, timing, ...) come only from the matcher.
ClassifyKind = Literal[
    "nsf_pair", "outstanding_check", "deposit_in_transit",
    "bank_fee_missing_in_gl", "interest_missing_in_gl", "duplicate_gl_entry",
    "transposition", "unidentified_receipt", "unknown",
]


class DraftEntry(BaseModel):
    """A two-line journal entry: one debit, one credit, one positive amount."""

    model_config = ConfigDict(frozen=True)

    debit_account: str
    credit_account: str
    amount: Decimal
    memo: str


class WorkItem(BaseModel):
    """An item before review and decide: rows, kind and the code-computed delta."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: ItemKind
    source: Source
    bank_ids: tuple[str, ...]
    gl_ids: tuple[str, ...]
    amount_delta: Decimal
    flags: tuple[ItemFlag, ...] = ()
    draft: DraftEntry | None = None  # code-built fix for a pre-labelled item; the fallback after resolve


class AgentItem(BaseModel):
    """A decided item. Maps onto `schemas.runs.Item` (B-10 adds run_id, timestamps, ids)."""

    id: str
    kind: ItemKind
    resolution: Resolution
    status: ItemStatus
    bank_ids: list[str]
    gl_ids: list[str]
    amount_delta: Decimal
    reasoning: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    flags: list[ItemFlag] = Field(default_factory=list)
    model: str | None = None
    confidence: float | None = Field(default=None, description="Display only, never a gate")
    entry: DraftEntry | None = None
    checks_passed: bool = True
    problems: list[str] = Field(default_factory=list)  # code-check failures, for the UI and evals
    rule_id: int | None = None  # the learned rule decide applied (B-13)
    critic_skipped: int = 0  # critic calls that failed (timeout, bad JSON); code checks stood alone


class StepLog(BaseModel):
    """One agent step for a `run_steps` row. Counts and stats only, never row text."""

    id: str
    tier: Literal["code", "nano", "super", "ultra"]
    model: str | None = None
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    failed_calls: int = 0  # calls that raised and fell back to a code default; all failed: the row is failed
    summary: str = ""
