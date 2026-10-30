"""Run, item and decision contract v1, shared by the API, the Inngest workflow and the UI.

The UI renders whatever `steps` come back, so adding or renaming an agent never
breaks the frontend. Steps that share a `position` run in parallel.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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
Resolution = Literal["auto_match", "auto_match_with_writeoff", "apply_rule", "reconciling_item", "escalate"]
ItemFlag = Literal["pii_redacted", "injection_flagged", "rule_applied"]
EvidenceType = Literal["bank_transaction", "gl_entry", "policy", "rule"]
EntryStatus = Literal["draft", "approved", "rejected", "posted"]
RuleOrigin = Literal["learned", "seeded"]


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
    learnable: bool = Field(default=False, description=(
        "True only when approving with remember would save a rule (recon/decisions.learnable)"))


class EntryOverride(BaseModel):
    debit_account: str
    credit_account: str
    amount: Money = Field(gt=0)
    memo: str

    @field_validator("amount", mode="before")
    @classmethod
    def _money_is_a_string(cls, value: Any) -> Any:
        # Money is a decimal string in JSON; a JSON number may already have lost cents to float.
        if isinstance(value, (int, float)):
            raise ValueError("amount must be a decimal string such as \"25.00\"")
        return value


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    entry_override: EntryOverride | None = None
    remember: bool = False
    note: str | None = None


class DecisionResponse(BaseModel):
    item: Item
    statement: Statement
    rule_id: int | None = Field(default=None, description="The rule this decision saved, else null")


class DemoResetResponse(BaseModel):
    dataset: str
    runs_deleted: int
    rules_kept: int = Field(description="Learned rules still active for the dataset; a reset keeps them")


class RuleForgotten(BaseModel):
    rule_id: int


class RulesForgotten(BaseModel):
    rules_deleted: int


class Rule(BaseModel):
    id: int
    kind: ItemKind
    pattern: dict[str, Any] = Field(examples=[{"description_regex": "MONTHLY SERVICE FEE"}])
    action: dict[str, Any] = Field(examples=[{"debit": "6800", "credit": "1010"}])
    source_item: str | None = None
    created_by: str
    dataset: str = Field(examples=["northbrook-2026-10"])
    origin: RuleOrigin = Field(description="learned (a remember approval; can be forgotten) or seeded")
    active: bool
    created_at: datetime


class AuditEntry(BaseModel):
    """One `audit_log` row of a run (GET /runs/{id}/audit). Append-only; oldest first.

    entity_type is run | item | entry | rule | guardrail | dataset; actor is agent:<name> |
    user:<email> | system. `detail` holds ids, counts and reason names; free text a reviewer
    typed (a decision's note, an override memo) is PII-masked before it leaves the API.
    """

    id: int
    run_id: str | None = None
    entity_type: str = Field(examples=["guardrail"])
    entity_id: str | None = None
    action: str = Field(examples=["injection_flagged"])
    actor: str = Field(examples=["agent:guard"])
    model: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict, examples=[{"reasons": ["instruction_override"]}])
    created_at: datetime
