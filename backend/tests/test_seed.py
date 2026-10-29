from datetime import date
from decimal import Decimal

from scripts.seed import load_balances, load_bank, load_gl

DATASET = "northbrook-2026-10"


def test_load_bank_rows():
    rows = load_bank(DATASET)
    assert len(rows) == 112
    first = rows[0]
    assert first["dataset"] == DATASET
    assert first["txn_id"] == "BANK001"
    assert first["posted_date"] == date(2026, 10, 1)
    assert first["amount"] == Decimal("-1850.00")
    assert first["check_number"] is None
    assert len({r["txn_id"] for r in rows}) == 112


def test_load_gl_rows():
    rows = load_gl(DATASET)
    assert len(rows) == 114
    first = rows[0]
    assert first["entry_id"] == "GL001"
    assert first["amount"] == Decimal("-750.00")
    assert first["check_number"] == "4521"
    assert len({r["entry_id"] for r in rows}) == 114


def test_load_balances():
    row = load_balances(DATASET)
    assert row["company"] == "Northbrook Goods Co."
    assert row["period_end"] == date(2026, 10, 10)
    assert row["bank_closing_balance"] - row["gl_closing_balance"] == Decimal("864.09")
