"""E-01 eval scorer. Expected numbers come from evals/scenarios.md, the ground-truth summary and HANDOFF.

The ground truth has 115 items: 108 auto (107 one-to-one plus BANK112 against three GL lines),
2 reconciling items, 5 escalations. Matched (bank, GL) pairs: 107 + 3 + the transposition = 111.
Six items carry an entry: the 5 escalations and the rounding write-off.
"""

from decimal import Decimal

import pytest

from app.recon.loader import load_dataset
from app.recon.models import ProposedEntry
from evals.scoring import load_ground_truth, score
from evals.types import EvalItem, PipelineResult

DATASET = "northbrook-2026-10"


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(DATASET)


@pytest.fixture(scope="module")
def truth():
    return load_ground_truth()


def perfect(truth) -> list[EvalItem]:
    """What a pipeline that gets everything right would return."""
    return [
        EvalItem(kind=t.kind, resolution=t.resolution, bank_ids=t.bank_ids, gl_ids=t.gl_ids, entry=t.expected_entry)
        for t in truth.items
    ]


def test_a_perfect_pipeline_scores_full_marks_and_closes_to_zero(dataset, truth):
    s = score(dataset, truth, PipelineResult(items=tuple(perfect(truth))))
    assert (s.match_precision.hit, s.match_precision.total) == (111, 111)
    assert (s.match_recall.hit, s.match_recall.total) == (111, 111)
    assert (s.kind_accuracy.hit, s.kind_accuracy.total) == (115, 115)
    assert (s.correct_escalations.hit, s.correct_escalations.total) == (5, 5)
    assert (s.entry_correctness.hit, s.entry_correctness.total) == (6, 6)
    assert s.false_auto_resolutions == []
    assert s.match_precision.value == 1.0
    # scenarios.md: 0.00 once every escalation is approved
    assert str(s.difference_after_approvals) == "0.00"
    # With the 5 escalations still pending, their book lines (3200 + 600 + 27 + 12.50 - 25) are not applied.
    assert s.final_difference == Decimal("3814.50")


def _replace(items: list[EvalItem], drop: set[tuple[str, ...]], add: list[EvalItem]) -> PipelineResult:
    """Perfect items minus those whose bank+GL ids are in `drop`, plus `add`."""
    kept = [i for i in items if (*i.bank_ids, *i.gl_ids) not in drop]
    return PipelineResult(items=tuple(kept + add))


def _auto(kind, bank, gl):
    return EvalItem(kind=kind, resolution="auto_match", bank_ids=bank, gl_ids=gl)


def test_swapped_check_pairs_cost_precision_recall_and_count_as_false_auto(dataset, truth):
    # scenarios.md #4: BANK043 is check 1005 (GL036), BANK044 is check 1003 (GL035).
    result = _replace(
        perfect(truth),
        {("BANK043", "GL036"), ("BANK044", "GL035")},
        [_auto("check_number", ("BANK043",), ("GL035",)), _auto("check_number", ("BANK044",), ("GL036",))],
    )
    s = score(dataset, truth, result)
    assert (s.match_precision.hit, s.match_precision.total) == (109, 111)
    assert (s.match_recall.hit, s.match_recall.total) == (109, 111)
    assert s.kind_accuracy.hit == 113
    assert [(f.bank_ids, f.gl_ids, f.expected) for f in s.false_auto_resolutions] == [
        (("BANK043",), ("GL035",), None),
        (("BANK044",), ("GL036",), None),
    ]
    assert sorted(s.missed_truth_ids) == ["T105", "T106"]


def test_calling_the_duplicate_posting_an_outstanding_check_is_a_false_auto_resolution(dataset, truth):
    # GL003 looks like an uncleared check, but it duplicates GL002 and must go to a human.
    wrong = EvalItem(kind="outstanding_check", resolution="reconciling_item", bank_ids=(), gl_ids=("GL003",))
    s = score(dataset, truth, _replace(perfect(truth), {("GL003",)}, [wrong]))
    [f] = s.false_auto_resolutions
    assert (f.gl_ids, f.resolution, f.expected) == (("GL003",), "reconciling_item", "escalate")
    assert (s.correct_escalations.hit, s.correct_escalations.total) == (4, 5)
    assert (s.entry_correctness.hit, s.entry_correctness.total) == (5, 6)
    assert s.kind_accuracy.hit == 114
    # The statement still ties (-3,200 on the bank side instead of +3,200 on the book side),
    # which is why the false auto-resolution count, not the difference, has to catch this.
    assert str(s.difference_after_approvals) == "0.00"


def test_an_escalation_with_the_wrong_entry_amount_is_escalated_but_its_entry_is_wrong(dataset, truth):
    # scenarios.md #14: the correction is 27.00 (952.00 booked, 925.00 cleared).
    bad = EvalItem(
        kind="transposition", resolution="escalate", bank_ids=("BANK019",), gl_ids=("GL023",),
        entry=ProposedEntry(debit_account="1010", credit_account="2000", amount=Decimal("72.00"), memo="x"),
    )
    s = score(dataset, truth, _replace(perfect(truth), {("BANK019", "GL023")}, [bad]))
    assert (s.correct_escalations.hit, s.entry_correctness.hit) == (5, 5)
    assert s.false_auto_resolutions == []
    assert s.difference_after_approvals == Decimal("-45.00")  # 72.00 posted where 27.00 was due


def test_items_left_open_are_neither_auto_nor_escalated(dataset, truth):
    fee = EvalItem(kind="unknown", resolution=None, bank_ids=("BANK032",), gl_ids=())
    s = score(dataset, truth, _replace(perfect(truth), {("BANK032",)}, [fee]))
    assert (s.unresolved, s.escalated, s.correct_escalations.hit) == (1, 4, 4)
    assert s.false_auto_resolutions == []
    assert s.difference_after_approvals == Decimal("-25.00")  # the 25.00 fee never reaches the book


def test_an_undecided_group_claims_no_match(dataset, truth):
    # scenarios.md #13: BANK009 clears GL002; GL003 is the duplicate. Left as one open group.
    group = EvalItem(kind="unknown", resolution=None, bank_ids=("BANK009",), gl_ids=("GL002", "GL003"))
    s = score(dataset, truth, _replace(perfect(truth), {("BANK009", "GL002"), ("GL003",)}, [group]))
    assert (s.match_precision.hit, s.match_precision.total) == (110, 110)
    assert (s.match_recall.hit, s.match_recall.total) == (110, 111)


def test_an_empty_run_scores_zero_and_shows_na_where_nothing_was_proposed(dataset, truth):
    s = score(dataset, truth, PipelineResult(items=()))
    assert s.match_precision.value is None  # no pairs proposed, so precision is undefined
    assert (s.match_recall.hit, s.match_recall.value) == (0, 0.0)
    assert s.final_difference == Decimal("864.09")  # the raw difference
    assert len(s.missed_truth_ids) == 115


@pytest.mark.parametrize(
    "entry",
    [ProposedEntry(debit_account="1010", credit_account="6990", amount=Decimal("500.00"), memo="x"), None],
    ids=["wrong-entry", "no-entry"],
)
def test_a_write_off_without_the_right_entry_is_a_false_auto_resolution(dataset, truth, entry):
    # scenarios.md #7: BANK033 vs GL045 writes off 0.01, DR 6990 / CR 1010. It posts without approval.
    bad = EvalItem(
        kind="rounding", resolution="auto_match_with_writeoff", bank_ids=("BANK033",), gl_ids=("GL045",), entry=entry
    )
    s = score(dataset, truth, _replace(perfect(truth), {("BANK033", "GL045")}, [bad]))
    [f] = s.false_auto_resolutions
    assert (f.bank_ids, f.gl_ids, f.expected) == (("BANK033",), ("GL045",), "auto_match_with_writeoff")


def test_a_perfect_run_cites_every_row(dataset, truth):
    assert score(dataset, truth, PipelineResult(items=tuple(perfect(truth)))).uncovered_rows == 0


def test_rows_no_item_cites_are_counted(dataset, truth):
    # scenarios.md #15: drop the unidentified Zelle (BANK113) and nothing else.
    s = score(dataset, truth, _replace(perfect(truth), {("BANK113",)}, []))
    assert s.uncovered_rows == 1


def test_a_row_cited_twice_is_rejected(dataset, truth):
    twice = [_auto("exact", ("BANK001",), ("GL004",)), _auto("exact", ("BANK001",), ())]
    with pytest.raises(ValueError, match="BANK001"):
        score(dataset, truth, PipelineResult(items=tuple(twice)))


def test_a_row_not_in_the_dataset_is_rejected(dataset, truth):
    with pytest.raises(ValueError, match="GL999"):
        score(dataset, truth, PipelineResult(items=(_auto("exact", ("BANK001",), ("GL999",)),)))
