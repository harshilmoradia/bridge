"""Code checks that gate review and decide. Rows and amounts are read from demo-data/ CSVs.

Worked example (from demo-data/bank_statement.csv and gl_entries.csv):
- BANK032 MONTHLY SERVICE FEE -25.00, no GL line -> book credits cash 25.00.
- BANK042 INTEREST PAYMENT +12.50 -> book debits cash 12.50.
- BANK113 ZELLE +600.00, no GL line -> debit cash 600.00 to suspense.
- GL003 is a second copy of GL002 (check 2847, -3200.00) -> debit cash 3200.00 back.
- BANK019 -925.00 vs GL023 -952.00 -> book overstated the payment by 27.00 -> debit cash 27.00.
"""

from decimal import Decimal

import pytest

from app.agents.checks import entry_problems, kind_problem
from app.agents.context import Books, load_accounts, load_policy
from app.agents.models import DraftEntry, WorkItem
from app.recon.loader import load_dataset

D = Decimal


@pytest.fixture(scope="module")
def books() -> Books:
    return Books(load_dataset("northbrook-2026-10"), load_policy(), load_accounts(),
                 matched_gl_ids=frozenset({"GL002"}))


def item(books: Books, kind: str, bank=(), gl=()) -> WorkItem:
    return WorkItem(id="I", kind=kind, source="classify", bank_ids=tuple(bank),
                    gl_ids=tuple(gl), amount_delta=books.delta(bank, gl))


def entry(dr: str, cr: str, amount: str) -> DraftEntry:
    return DraftEntry(debit_account=dr, credit_account=cr, amount=D(amount), memo="m")


@pytest.mark.parametrize("kind,bank,gl", [
    ("bank_fee_missing_in_gl", ["BANK032"], []),
    ("interest_missing_in_gl", ["BANK042"], []),
    ("unidentified_receipt", ["BANK113"], []),
    ("duplicate_gl_entry", [], ["GL003"]),
    ("transposition", ["BANK019"], ["GL023"]),
    ("outstanding_check", [], ["GL034"]),
    ("deposit_in_transit", [], ["GL114"]),
    ("nsf_pair", ["BANK080"], ["GL079"]),
    ("unknown", ["BANK113"], []),
])
def test_kind_holds_on_demo_rows(books, kind, bank, gl) -> None:
    assert kind_problem(item(books, kind, bank, gl), books) is None


@pytest.mark.parametrize("kind,bank,gl", [
    ("bank_fee_missing_in_gl", ["BANK042"], []),  # interest, not a fee
    ("interest_missing_in_gl", ["BANK032"], []),
    ("unidentified_receipt", ["BANK032"], []),  # money out
    ("duplicate_gl_entry", [], ["GL034"]),  # no twin
    ("transposition", ["BANK032"], ["GL034"]),
    ("outstanding_check", [], ["GL114"]),  # a deposit
    ("deposit_in_transit", [], ["GL034"]),
    ("nsf_pair", ["BANK089"], ["GL088"]),  # a freight payment
    ("bank_fee_missing_in_gl", ["BANK032"], ["GL034"]),  # wrong shape
    ("outstanding_check", [], ["GL003"]),  # check 2847 already cleared as BANK009 (live miss)
])
def test_kind_rejected_when_rows_disagree(books, kind, bank, gl) -> None:
    assert kind_problem(item(books, kind, bank, gl), books)


def test_duplicate_needs_the_twin_to_be_matched(books) -> None:
    alone = Books(books.dataset, books.policy, books.accounts)
    assert kind_problem(item(alone, "duplicate_gl_entry", gl=["GL003"]), alone)


@pytest.mark.parametrize("kind,bank,gl,good", [
    ("bank_fee_missing_in_gl", ["BANK032"], [], entry("6800", "1010", "25.00")),
    ("interest_missing_in_gl", ["BANK042"], [], entry("1010", "4100", "12.50")),
    ("unidentified_receipt", ["BANK113"], [], entry("1010", "2400", "600.00")),
    ("duplicate_gl_entry", [], ["GL003"], entry("1010", "2000", "3200.00")),
    ("transposition", ["BANK019"], ["GL023"], entry("1010", "2000", "27.00")),
])
def test_correct_draft_entries_pass(books, kind, bank, gl, good) -> None:
    assert entry_problems(item(books, kind, bank, gl), good, books) == []


@pytest.mark.parametrize("bad,why", [
    (entry("1010", "6800", "25.00"), "cash"),  # wrong direction
    (entry("6800", "1010", "24.00"), "amount"),
    (entry("6800", "1010", "-25.00"), "amount"),
    (entry("9999", "1010", "25.00"), "chart of accounts"),
    (entry("4100", "1010", "25.00"), "expense"),  # fee must hit an expense account
    (entry("6800", "6800", "25.00"), "cash"),
    (None, "entry"),
])
def test_bad_fee_entries_rejected(books, bad, why) -> None:
    problems = entry_problems(item(books, "bank_fee_missing_in_gl", ["BANK032"]), bad, books)
    assert problems and any(why in p for p in problems)


def test_duplicate_and_transposition_reverse_the_original_counter_account(books) -> None:
    dup = item(books, "duplicate_gl_entry", gl=["GL003"])
    assert entry_problems(dup, entry("1010", "6100", "3200.00"), books)
    trans = item(books, "transposition", ["BANK019"], ["GL023"])
    assert entry_problems(trans, entry("1010", "4200", "27.00"), books)


def test_unidentified_receipt_goes_to_a_liability_not_income(books) -> None:
    # Live run drafted CR 4000 Sales; unknown cash is held in suspense until identified.
    receipt = item(books, "unidentified_receipt", ["BANK113"])
    assert entry_problems(receipt, entry("1010", "4000", "600.00"), books)
    assert entry_problems(receipt, entry("1010", "2400", "600.00"), books) == []


def test_reconciling_items_take_no_entry(books) -> None:
    oc = item(books, "outstanding_check", gl=["GL034"])
    assert entry_problems(oc, None, books) == []
    assert entry_problems(oc, entry("1010", "6100", "325.00"), books)


def test_unknown_entry_is_optional_but_checked(books) -> None:
    unk = item(books, "unknown", ["BANK113"])
    assert entry_problems(unk, None, books) == []
    assert entry_problems(unk, entry("1010", "2400", "600.00"), books) == []
    assert entry_problems(unk, entry("1010", "2400", "60.00"), books)
