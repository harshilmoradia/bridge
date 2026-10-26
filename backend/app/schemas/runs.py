"""Run, item and decision contract v1, shared by the API, the Inngest workflow and the UI.

The UI renders whatever `steps` come back, so adding or renaming an agent never
breaks the frontend. Steps that share a `position` run in parallel.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ApiError, ItemStatus, Money
from app.schemas.reads import Statement

RunStatus = Literal["queued", "running", "completed", "failed"]
StepStatus = Literal["pending", "running", "completed", "failed"]
ModelTier = Literal["code", "nano", "super", "ultra"]
ItemKind = Literal[
    "exact", "timing", "check_number", "one_to_many", "rounding", "nsf_pair",
    "outstanding_check", "deposit_in_transit",
    "bank_fee_missing_in_gl", "interest_missing_in_gl", "duplicate_gl_entry",
    "transposition", "unidentified_receipt", "unknown",
]
Resolution = Literal["auto_match", "auto_match_with_writeoff", "reconciling_item", "escalate"]
ItemFlag = Literal["pii_redacted", "injection_flagged", "rule_applied"]
EvidenceType = Literal["bank_transaction", "gl_entry", "policy", "rule"]
EntryStatus = Literal["draft", "approved", "rejected", "posted"]


class CreateRunRequest(BaseModel):
    dataset: str = Field(examples=["northbrook-2026-10"])
    period_start: date
    period_end: date


class CreateRunResponse(BaseModel):
    id: str
    status: RunStatus


class RunStep(BaseModel):
    id: str = Field(examples=["load", "match-rules", "resolve"])
    position: int = Field(description="Display order; steps sharing a position run in parallel")
    agent: str
    label: str
    tier: ModelTier
    model: str | None = None
    status: StepStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    output_summary: str | None = None
    error: ApiError | None = None


class RunCounts(BaseModel):
    bank_transactions: int = 0
    gl_entries: int = 0
    items: int = 0
    matched: int = 0
    auto_resolved: int = 0
    reconciling_item: int = 0
    needs_approval: int = 0
    approved: int = 0
    rejected: int = 0
    unmatched: int = 0


class Run(BaseModel):
    id: str
    dataset: str
    period_start: date
    period_end: date
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    steps: list[RunStep]
    counts: RunCounts
    report: str | None = Field(default=None, description="Markdown, set once the run completes")
    error: ApiError | None = None


class Evidence(BaseModel):
    type: EvidenceType
    id: str = Field(examples=["BANK004", "GL017", "auto_resolve_kinds", "3"])
    note: str | None = None


class ProposedEntry(BaseModel):
    id: str
    debit_account: str = Field(examples=["6800"])
    credit_account: str = Field(examples=["1010"])
    amount: Money = Field(description="Always positive")
    memo: str
    status: EntryStatus


class Item(BaseModel):
    id: str
    run_id: str
    kind: ItemKind
    resolution: Resolution
    status: ItemStatus
    bank_ids: list[str]
    gl_ids: list[str]
    amount_delta: Money
    reasoning: str | None = None
    evidence: list[Evidence]
    flags: list[ItemFlag]
    model: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1, description="Display only, never a gate")
    rule_id: int | None = None
    proposed_entry: ProposedEntry | None = None
    created_at: datetime


class EntryOverride(BaseModel):
    debit_account: str
    credit_account: str
    amount: Money = Field(gt=0)
    memo: str


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    entry_override: EntryOverride | None = None
    remember: bool = False
    note: str | None = None


class DecisionResponse(BaseModel):
    item: Item
    statement: Statement


class Rule(BaseModel):
    id: int
    kind: ItemKind
    pattern: dict[str, Any] = Field(examples=[{"description_regex": "MONTHLY SERVICE FEE"}])
    action: dict[str, Any] = Field(examples=[{"debit": "6800", "credit": "1010"}])
    source_item: str | None = None
    created_by: str
    active: bool
    created_at: datetime
