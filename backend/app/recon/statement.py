"""Reconciliation statement, recomputed on every read from the dataset and one run's items.

Bank side: reconciling items (deposits in transit, outstanding checks). These are GL rows
the bank has not cleared yet, so each line is the GL amount minus any bank amount on the item.
Book side: items carrying a journal entry. Each line is the entry's effect on GL cash, and it
counts toward the adjusted balance only once the entry is approved or auto-resolved by policy.
"""

from collections.abc import Sequence
from decimal import Decimal

from app.core.errors import AppError
from app.recon.models import Dataset, ProposedEntry
from app.recon.store import ItemRef
from app.schemas.reads import Statement, StatementLine, StatementSide

POSTED_STATUSES = frozenset({"approved", "auto_resolved"})
KIND_LABELS = {"deposit_in_transit": "Deposit in transit", "outstanding_check": "Outstanding check"}


def _label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.replace("_", " ").capitalize())


def _side(closing: Decimal, lines: list[StatementLine]) -> StatementSide:
    applied = sum((line.amount for line in lines if line.applied), Decimal("0"))
    return StatementSide(closing_balance=closing, lines=lines, adjusted_balance=closing + applied)


def _total(amounts: dict[str, Decimal], ids: Sequence[str], item_id: str) -> Decimal:
    missing = [i for i in ids if i not in amounts]
    if missing:
        raise AppError(
            code="item_row_not_found",
            message=f"Item {item_id} cites rows not in the dataset: {', '.join(missing)}",
            status_code=409,
        )
    return sum((amounts[i] for i in ids), Decimal("0"))


def _bank_lines(dataset: Dataset, items: Sequence[ItemRef]) -> list[StatementLine]:
    bank = {t.txn_id: t.amount for t in dataset.bank}
    gl = {e.entry_id: e.amount for e in dataset.gl}
    return [
        StatementLine(
            item_id=item.id,
            kind=item.kind,
            label=_label(item.kind),
            amount=_total(gl, item.gl_ids, item.id) - _total(bank, item.bank_ids, item.id),
            status=item.status,
            applied=True,
            bank_ids=list(item.bank_ids),
            gl_ids=list(item.gl_ids),
        )
        for item in items
        if item.status == "reconciling_item"
    ]


def _cash_effect(entry: ProposedEntry, cash_account: str) -> Decimal:
    """What posting the entry does to the GL cash balance: a debit to cash adds, a credit subtracts."""
    effect = Decimal("0")
    if entry.debit_account == cash_account:
        effect += entry.amount
    if entry.credit_account == cash_account:
        effect -= entry.amount
    return effect


def _book_lines(dataset: Dataset, items: Sequence[ItemRef]) -> list[StatementLine]:
    cash = dataset.balances.cash_account  # entries that never touch cash do not move the book balance
    return [
        StatementLine(
            item_id=item.id,
            kind=item.kind,
            label=item.entry.memo,
            amount=_cash_effect(item.entry, cash),
            status=item.status,
            applied=item.status in POSTED_STATUSES,
            bank_ids=list(item.bank_ids),
            gl_ids=list(item.gl_ids),
        )
        for item in items
        if item.entry is not None and cash in (item.entry.debit_account, item.entry.credit_account)
    ]


def build_statement(dataset: Dataset, run_id: str | None, items: Sequence[ItemRef]) -> Statement:
    b = dataset.balances
    bank = _side(b.bank_closing_balance, _bank_lines(dataset, items))
    book = _side(b.gl_closing_balance, _book_lines(dataset, items))
    return Statement(
        dataset=dataset.id,
        run_id=run_id,
        company=b.company,
        cash_account=b.cash_account,
        period_start=b.period_start,
        period_end=b.period_end,
        raw_difference=b.bank_closing_balance - b.gl_closing_balance,
        bank=bank,
        book=book,
        unreconciled_difference=bank.adjusted_balance - book.adjusted_balance,
    )
