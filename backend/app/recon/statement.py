"""Reconciliation statement. Stopgap for B-05: balances and the raw difference only.

B-04 owns the full calculator (reconciling items on the bank side, adjustments on
the book side). Until then both sides have no lines, so the unreconciled
difference equals the raw difference.
"""

from app.recon.models import Dataset
from app.schemas.reads import Statement, StatementSide


def build_statement(dataset: Dataset, run_id: str | None) -> Statement:
    b = dataset.balances
    bank = StatementSide(closing_balance=b.bank_closing_balance, lines=[], adjusted_balance=b.bank_closing_balance)
    book = StatementSide(closing_balance=b.gl_closing_balance, lines=[], adjusted_balance=b.gl_closing_balance)
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
