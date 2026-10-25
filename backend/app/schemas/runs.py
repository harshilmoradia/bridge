"""Run contract shared by the API, the Inngest workflow and the UI.

Agent-agnostic on purpose: the UI renders whatever `steps` come back, so adding
or renaming an agent never breaks the frontend. Money is a decimal string.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

RunStatus = Literal["queued", "running", "completed", "failed"]
StepStatus = Literal["pending", "running", "completed", "failed"]
ModelTier = Literal["nano", "super", "ultra"]
Severity = Literal["low", "medium", "high"]
EvidenceType = Literal["bank_transaction", "bill", "card_transaction", "receipt"]


class ApiError(BaseModel):
    code: str
    message: str


class DemoInput(BaseModel):
    id: str = Field(examples=["day-2026-09-23"])
    label: str
    description: str


class CreateRunRequest(BaseModel):
    input_id: str = Field(description="One of the ids from GET /inputs")


class CreateRunResponse(BaseModel):
    id: str
    status: RunStatus


class Evidence(BaseModel):
    type: EvidenceType
    id: str = Field(examples=["B-0023", "BT-0027", "CT-0052"])


class Finding(BaseModel):
    id: str
    kind: str = Field(examples=["duplicate_bill", "expense_spike", "vendor_match"])
    severity: Severity
    needs_human: bool
    title: str
    reasoning: str
    confidence: float = Field(ge=0, le=1)
    proposed_action: str
    evidence: list[Evidence]


class ProposedEntry(BaseModel):
    id: str
    debit_account: str = Field(examples=["6900 Bank & Card Fees"])
    credit_account: str = Field(examples=["1000 Operating Cash"])
    amount: Decimal
    memo: str
    confidence: float = Field(ge=0, le=1)
    auto_post: bool
    evidence: list[Evidence]


class RunResult(BaseModel):
    summary: str
    findings: list[Finding]
    proposed_entries: list[ProposedEntry]


class RunStep(BaseModel):
    id: str = Field(examples=["plan", "match-payments", "synthesize"])
    agent: str
    label: str
    model_tier: ModelTier
    status: StepStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output_summary: str | None = None
    error: ApiError | None = None


class Run(BaseModel):
    id: str
    input_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    steps: list[RunStep]
    result: RunResult | None = None
    error: ApiError | None = None
