"""Read API v1: datasets, bank and GL rows with their recon status, and the reconciliation statement."""

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.common import ItemStatus, Money, ReconStatus


class DatasetOut(BaseModel):
    id: str = Field(examples=["northbrook-2026-10"])
    label: str
    period_start: date
    period_end: date


class Guardrail(BaseModel):
    injection_flagged: bool = Field(description="The text reads like an instruction to the model: treated as data")
    pii_masked: bool = Field(description="Masking changed the text before it reaches a model")
    sent_to_model: str = Field(description="The description exactly as the agents' prompt carries it")
    sent_counterparty: str | None = Field(default=None, description="GL only: the counterparty as sent")


class BankTransactionOut(BaseModel):
    txn_id: str = Field(examples=["BANK001"])
    posted_date: date
    description: str
    amount: Money
    type: str
    check_number: str | None
    running_balance: Money | None
    recon_status: ReconStatus
    item_id: str | None = Field(description="The latest run's item that covers this row, if any")
    guardrail: Guardrail


class GlEntryOut(BaseModel):
    entry_id: str = Field(examples=["GL001"])
    date: date
    description: str
    amount: Money
    method: str
    check_number: str | None
    account: str
    counter_account: str
    counterparty: str | None
    recon_status: ReconStatus
    item_id: str | None
    guardrail: Guardrail


class StatementLine(BaseModel):
    item_id: str
    kind: str = Field(examples=["deposit_in_transit", "bank_fee_missing_in_gl"])
    label: str
    amount: Money = Field(description="Signed: added to this side's closing balance when applied")
    status: ItemStatus
    applied: bool = Field(description="True when the line counts toward adjusted_balance")
    bank_ids: list[str]
    gl_ids: list[str]


class StatementSide(BaseModel):
    closing_balance: Money
    lines: list[StatementLine]
    adjusted_balance: Money = Field(description="closing_balance plus the applied lines")


class Statement(BaseModel):
    dataset: str
    run_id: str | None = Field(description="The run the lines come from; null before any run")
    company: str
    cash_account: str
    period_start: date
    period_end: date
    raw_difference: Money = Field(description="bank.closing_balance - book.closing_balance")
    bank: StatementSide = Field(description="Reconciling items: deposits in transit, outstanding checks")
    book: StatementSide = Field(description="Adjustments that need a journal entry in the GL")
    unreconciled_difference: Money = Field(description="bank.adjusted_balance - book.adjusted_balance")
