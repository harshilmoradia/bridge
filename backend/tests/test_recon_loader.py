from datetime import date
from decimal import Decimal

from app.recon import load_dataset

DATASET = "northbrook-2026-10"


def test_loads_every_row_of_demo_data():
    ds = load_dataset(DATASET)
    assert ds.id == DATASET
    assert len(ds.bank) == 112
    assert len(ds.gl) == 114


def test_bank_rows_are_typed():
    first = load_dataset(DATASET).bank[0]
    assert first.txn_id == "BANK001"
    assert first.posted_date == date(2026, 10, 1)
    assert first.amount == Decimal("-1850.00")
    assert first.check_number is None
    assert first.running_balance == Decimal("213000.00")


def test_gl_rows_are_typed():
    first = load_dataset(DATASET).gl[0]
    assert first.entry_id == "GL001"
    assert first.date == date(2026, 10, 1)
    assert first.amount == Decimal("-750.00")
    assert first.check_number == "4521"
    assert (first.account, first.counter_account) == ("1010", "6500")


def test_rows_sum_to_the_stated_closing_balances():
    ds = load_dataset(DATASET)
    b = ds.balances
    assert b.bank_opening_balance + sum(t.amount for t in ds.bank) == b.bank_closing_balance
    assert b.gl_opening_balance + sum(e.amount for e in ds.gl) == b.gl_closing_balance
    assert b.bank_closing_balance - b.gl_closing_balance == Decimal("864.09")
