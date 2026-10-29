"""decide: policy kind plus code checks only. Confidence and injection flags never gate."""

from decimal import Decimal

import pytest

from app.agents.context import load_policy
from app.agents.decide import decide
from app.agents.models import WorkItem

POLICY = load_policy()


def wi(kind: str, delta: str = "0.00", flags=()) -> WorkItem:
    return WorkItem(id="I", kind=kind, source="rules", bank_ids=("B",), gl_ids=("G",),
                    amount_delta=Decimal(delta), flags=tuple(flags))


@pytest.mark.parametrize("kind,expected", [
    ("exact", ("auto_match", "matched")),
    ("timing", ("auto_match", "matched")),
    ("check_number", ("auto_match", "matched")),
    ("one_to_many", ("auto_match", "matched")),
    ("nsf_pair", ("auto_match", "auto_resolved")),
    ("rounding", ("auto_match_with_writeoff", "auto_resolved")),
    ("outstanding_check", ("reconciling_item", "reconciling_item")),
    ("deposit_in_transit", ("reconciling_item", "reconciling_item")),
    ("bank_fee_missing_in_gl", ("escalate", "needs_approval")),
    ("interest_missing_in_gl", ("escalate", "needs_approval")),
    ("duplicate_gl_entry", ("escalate", "needs_approval")),
    ("transposition", ("escalate", "needs_approval")),
    ("unidentified_receipt", ("escalate", "needs_approval")),
    ("unknown", ("escalate", "needs_approval")),
])
def test_policy_by_kind(kind, expected) -> None:
    delta = "-0.01" if kind == "rounding" else "0.00"
    assert decide(wi(kind, delta), checks_passed=True, policy=POLICY) == expected


@pytest.mark.parametrize("kind", ["exact", "nsf_pair", "rounding", "outstanding_check"])
def test_failed_checks_escalate(kind) -> None:
    assert decide(wi(kind), checks_passed=False, policy=POLICY) == ("escalate", "needs_approval")


def test_rounding_over_tolerance_escalates() -> None:
    assert decide(wi("rounding", "-1.01"), checks_passed=True, policy=POLICY)[0] == "escalate"
    assert decide(wi("rounding", "1.00"), checks_passed=True, policy=POLICY)[0] \
        == "auto_match_with_writeoff"


def test_delta_over_max_auto_amount_escalates() -> None:
    assert decide(wi("timing", "10000.01"), checks_passed=True, policy=POLICY)[0] == "escalate"


def test_injection_flag_never_changes_the_decision() -> None:
    plain = decide(wi("exact"), checks_passed=True, policy=POLICY)
    flagged = decide(wi("exact", flags=["injection_flagged"]), checks_passed=True, policy=POLICY)
    assert plain == flagged == ("auto_match", "matched")
