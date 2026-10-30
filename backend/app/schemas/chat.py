from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None


class ChatResponse(BaseModel):
    message: ChatMessage
    model: str


ChatSourceType = Literal["bank_transaction", "gl_entry"]
ChatReconStatus = Literal[
    "matched", "auto_resolved", "reconciling_item", "needs_approval", "approved", "rejected", "unmatched"
]


class RagChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class RagChatRequest(BaseModel):
    dataset: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=500)
    history: list[RagChatTurn] = Field(default_factory=list, max_length=8)
    source_type: ChatSourceType | None = None
    date_from: date | None = None
    date_to: date | None = None
    amount: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    status: ChatReconStatus | None = None

    @model_validator(mode="after")
    def _ordered_dates(self) -> "RagChatRequest":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class RagChatEntry(BaseModel):
    id: str
    debit_account: str
    credit_account: str
    amount: str
    memo: str
    status: str


class RagChatItem(BaseModel):
    id: str
    run_id: str
    kind: str
    status: ChatReconStatus
    amount_delta: str
    reasoning: str | None = None
    evidence: list[dict[str, str | None]] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    proposed_entry: RagChatEntry | None = None


class RagChatSource(BaseModel):
    source_type: ChatSourceType
    source_id: str
    date: date
    amount: str
    description: str
    type: str
    check_number: str | None = None
    running_balance: str | None = None
    account: str | None = None
    counter_account: str | None = None
    counterparty: str | None = None
    guardrail: dict[str, object]
    status: ChatReconStatus
    item: RagChatItem | None = None
    score: float
    matched_by: list[str]


class RagChatResponse(BaseModel):
    message: ChatMessage
    model: str
    sources: list[RagChatSource]
    citations: list[str] = Field(default_factory=list)
    no_evidence: bool = False
