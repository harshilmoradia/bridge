"""Reconciliation domain models. Money is Decimal; positive means money into the bank."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # CSV and some DB exports use "" for a missing value.
        return None if value == "" else value


class BankTxn(_Row):
    txn_id: str
    posted_date: date
    description: str
    amount: Decimal
    type: str
    check_number: str | None = None
    running_balance: Decimal | None = None


class GlEntry(_Row):
    entry_id: str
    date: date
    description: str
    amount: Decimal
    method: str
    check_number: str | None = None
    account: str
    counter_account: str
    counterparty: str | None = None


class Balances(_Row):
    company: str
    cash_account: str
    period_start: date
    period_end: date
    bank_opening_balance: Decimal
    bank_closing_balance: Decimal
    gl_opening_balance: Decimal
    gl_closing_balance: Decimal


class Dataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    balances: Balances
    bank: tuple[BankTxn, ...]
    gl: tuple[GlEntry, ...]
