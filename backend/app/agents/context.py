"""Shared, read-only inputs for the agents: rows by id, the full policy, the chart of accounts.

Loaded from demo-data/ (runtime inputs). Never from evals/.
"""

import csv
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.recon.loader import DATA_DIR
from app.recon.models import BankTxn, Dataset, GlEntry

CASH = "1010"


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True)

    date_window_days: int
    auto_writeoff_tolerance: Decimal
    auto_writeoff_account: str
    auto_resolve_kinds: tuple[str, ...]
    reconciling_item_kinds: tuple[str, ...]
    always_escalate_kinds: tuple[str, ...]
    max_auto_amount: Decimal

    def resolution_for(self, kind: str) -> str:
        if kind in self.auto_resolve_kinds:
            return "auto_resolve"
        if kind in self.reconciling_item_kinds:
            return "reconciling_item"
        return "escalate"


class Account(BaseModel):
    model_config = ConfigDict(frozen=True)

    account: str
    name: str
    type: str


def load_policy(data_dir: Path = DATA_DIR) -> Policy:
    raw = json.loads((data_dir / "policy.json").read_text(encoding="utf-8"))
    return Policy(**raw)


def load_accounts(data_dir: Path = DATA_DIR) -> dict[str, Account]:
    with (data_dir / "chart_of_accounts.csv").open(newline="", encoding="utf-8") as f:
        return {r["account"]: Account(**r) for r in csv.DictReader(f)}


@dataclass(frozen=True)
class Rule:
    """A learned rule (B-12 writes them). `pattern` is matched case-insensitively as a substring."""

    id: int
    kind: str
    pattern: str
    debit_account: str
    credit_account: str
    approved_by: str = ""


@dataclass
class Books:
    dataset: Dataset
    policy: Policy
    accounts: dict[str, Account]
    rules: tuple[Rule, ...] = ()
    matched_gl_ids: frozenset[str] = frozenset()
    bank: dict[str, BankTxn] = field(init=False)
    gl: dict[str, GlEntry] = field(init=False)

    def __post_init__(self) -> None:
        self.bank = {b.txn_id: b for b in self.dataset.bank}
        self.gl = {g.entry_id: g for g in self.dataset.gl}

    @property
    def period_end(self):
        return self.dataset.balances.period_end

    def rows(self, bank_ids, gl_ids) -> tuple[list[BankTxn], list[GlEntry]]:
        return [self.bank[i] for i in bank_ids], [self.gl[i] for i in gl_ids]

    def delta(self, bank_ids, gl_ids) -> Decimal:
        b, g = self.rows(bank_ids, gl_ids)
        return sum((x.amount for x in b), Decimal("0.00")) - sum((x.amount for x in g), Decimal("0.00"))

    def has_id(self, row_id: str) -> bool:
        return row_id in self.bank or row_id in self.gl


def row_dict(row: BankTxn | GlEntry) -> dict[str, Any]:
    return row.model_dump()
