"""Statement calculator (B-04). Expected numbers come from demo-data/, the backlog and evals/ground_truth.json."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.recon.loader import load_dataset
from app.recon.models import ProposedEntry
from app.recon.statement import build_statement
from app.recon.store import ItemRef

DATASET = "northbrook-2026-10"
GROUND_TRUTH = Path(__file__).resolve().parents[2] / "evals" / "ground_truth.json"


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(DATASET)


def test_no_items_leaves_the_raw_difference_unreconciled(dataset):
    statement = build_statement(dataset, None, ())
    assert statement.raw_difference == Decimal("864.09")
    assert statement.bank.lines == [] and statement.book.lines == []
    assert statement.bank.adjusted_balance == Decimal("48547.99")
    assert statement.book.adjusted_balance == Decimal("47683.90")
    assert statement.unreconciled_difference == Decimal("864.09")


def test_deposit_in_transit_is_added_to_the_bank_side(dataset):
    dit = ItemRef(id="i-dit", status="reconciling_item", kind="deposit_in_transit", bank_ids=(), gl_ids=("GL114",))
    statement = build_statement(dataset, None, [dit])
    [line] = statement.bank.lines
    assert (line.item_id, line.kind, line.amount, line.applied) == ("i-dit", "deposit_in_transit", Decimal("3275.40"), True)
    assert line.gl_ids == ["GL114"] and line.bank_ids == []
    assert statement.bank.adjusted_balance == Decimal("51823.39")  # 48547.99 + 3275.40
    assert statement.book.lines == []


def test_outstanding_check_is_subtracted_from_the_bank_side(dataset):
    oc = ItemRef(id="i-oc", status="reconciling_item", kind="outstanding_check", bank_ids=(), gl_ids=("GL034",))
    statement = build_statement(dataset, None, [oc])
    [line] = statement.bank.lines
    assert (line.kind, line.label, line.amount) == ("outstanding_check", "Outstanding check", Decimal("-325.00"))
    assert statement.bank.adjusted_balance == Decimal("48222.99")  # 48547.99 - 325.00


def test_a_matched_item_adds_no_line(dataset):
    match = ItemRef(id="i-m", status="matched", kind="check_number", bank_ids=("BANK005",), gl_ids=("GL008",))
    statement = build_statement(dataset, None, [match])
    assert statement.bank.lines == [] and statement.book.lines == []
    assert statement.unreconciled_difference == Decimal("864.09")


FEE_ENTRY = ProposedEntry(debit_account="6800", credit_account="1010", amount=Decimal("25.00"), memo="Monthly bank service fee")


def _fee(status: str) -> ItemRef:
    return ItemRef(id="i-fee", status=status, kind="bank_fee_missing_in_gl", bank_ids=("BANK032",), gl_ids=(), entry=FEE_ENTRY)


def test_approved_entry_crediting_cash_lowers_the_book_side(dataset):
    statement = build_statement(dataset, None, [_fee("approved")])
    [line] = statement.book.lines
    assert (line.item_id, line.kind, line.label) == ("i-fee", "bank_fee_missing_in_gl", "Monthly bank service fee")
    assert (line.amount, line.status, line.applied) == (Decimal("-25.00"), "approved", True)
    assert line.bank_ids == ["BANK032"]
    assert statement.book.adjusted_balance == Decimal("47658.90")  # 47683.90 - 25.00
    assert statement.unreconciled_difference == Decimal("889.09")
    assert statement.bank.lines == []


@pytest.mark.parametrize("status", ["needs_approval", "rejected"])
def test_unapproved_entry_is_listed_but_not_applied(dataset, status):
    statement = build_statement(dataset, None, [_fee(status)])
    [line] = statement.book.lines
    assert (line.amount, line.status, line.applied) == (Decimal("-25.00"), status, False)
    assert statement.book.adjusted_balance == Decimal("47683.90")
    assert statement.unreconciled_difference == Decimal("864.09")


def test_auto_write_off_applies_without_approval(dataset):
    entry = ProposedEntry(debit_account="6990", credit_account="1010", amount=Decimal("0.01"), memo="Rounding")
    rounding = ItemRef(
        id="i-r", status="auto_resolved", kind="rounding", bank_ids=("BANK033",), gl_ids=("GL045",), entry=entry
    )
    statement = build_statement(dataset, None, [rounding])
    [line] = statement.book.lines
    assert (line.amount, line.applied) == (Decimal("-0.01"), True)
    assert statement.book.adjusted_balance == Decimal("47683.89")


def test_entry_debiting_cash_raises_the_book_side(dataset):
    entry = ProposedEntry(debit_account="1010", credit_account="4100", amount=Decimal("12.50"), memo="Bank interest")
    interest = ItemRef(
        id="i-int", status="approved", kind="interest_missing_in_gl", bank_ids=("BANK042",), gl_ids=(), entry=entry
    )
    statement = build_statement(dataset, None, [interest])
    assert statement.book.lines[0].amount == Decimal("12.50")
    assert statement.book.adjusted_balance == Decimal("47696.40")
    assert statement.unreconciled_difference == Decimal("851.59")


def test_reconciling_item_with_an_unknown_row_raises_a_domain_error(dataset):
    ghost = ItemRef(id="w", status="reconciling_item", bank_ids=(), gl_ids=("GL999",))
    with pytest.raises(AppError) as err:
        build_statement(dataset, None, [ghost])
    assert "GL999" in err.value.message


def test_entry_amount_must_be_positive():
    with pytest.raises(ValidationError):
        ProposedEntry(debit_account="6800", credit_account="1010", amount=Decimal("-5"), memo="x")


def test_entry_that_does_not_touch_cash_adds_no_book_line(dataset):
    entry = ProposedEntry(debit_account="6800", credit_account="2000", amount=Decimal("40.00"), memo="Reclass")
    item = ItemRef(id="i-x", status="approved", kind="unknown", bank_ids=(), gl_ids=(), entry=entry)
    statement = build_statement(dataset, None, [item])
    assert statement.book.lines == []
    assert statement.unreconciled_difference == Decimal("864.09")


# How a resolved run stores each ground-truth item once every escalation has been approved.
STATUS_AFTER_APPROVAL = {
    "auto_match": "matched",
    "auto_match_with_writeoff": "auto_resolved",
    "reconciling_item": "reconciling_item",
    "escalate": "approved",
}


def _resolved_items() -> list[ItemRef]:
    truth = json.loads(GROUND_TRUTH.read_text())
    items = []
    for t in truth["items"]:
        e = t.get("expected_entry")
        entry = e and ProposedEntry(
            debit_account=e["debit"], credit_account=e["credit"], amount=Decimal(e["amount"]), memo=e["memo"]
        )
        items.append(ItemRef(
            id=t["id"], status=STATUS_AFTER_APPROVAL[t["resolution"]], kind=t["kind"],
            bank_ids=tuple(t["bank_ids"]), gl_ids=tuple(t["gl_ids"]), entry=entry,
        ))
    return items


def test_all_ground_truth_resolutions_close_the_statement_to_zero(dataset):
    summary = json.loads(GROUND_TRUTH.read_text())["summary"]
    statement = build_statement(dataset, "run-1", _resolved_items())

    def total(lines, kind=None):
        return sum((line.amount for line in lines if kind in (None, line.kind)), Decimal("0"))

    assert statement.raw_difference == Decimal(summary["raw_difference"])
    assert total(statement.bank.lines, "deposit_in_transit") == Decimal(summary["deposits_in_transit"])
    assert total(statement.bank.lines, "outstanding_check") == -Decimal(summary["outstanding_checks"])
    assert statement.bank.adjusted_balance == Decimal(summary["adjusted_bank_balance"])
    assert total(statement.book.lines) == Decimal(summary["book_adjustments"])
    assert statement.book.adjusted_balance == Decimal(summary["adjusted_book_balance"])
    assert all(line.applied for line in statement.bank.lines + statement.book.lines)
    assert statement.unreconciled_difference == Decimal(summary["unreconciled_difference_after_all_resolutions"])
    assert str(statement.unreconciled_difference) == "0.00"
