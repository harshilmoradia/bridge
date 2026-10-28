"""E-01: the rules-only baseline (B-03 matcher, no LLM) scored on demo-data/.

Expected numbers: HANDOFF (103 matches, all correct, one of them BANK112 against GL111-113;
3 candidate groups; unmatched BANK019/032/042/113 and GL023/034/114), scenarios.md and the ground truth.
"""

from decimal import Decimal

import pytest

from evals.pipelines import rules_only
from evals.scoring import load_ground_truth, score
from app.recon.loader import load_dataset

DATASET = "northbrook-2026-10"


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(DATASET)


async def test_rules_only_closes_the_rounding_pair_with_the_policy_write_off(dataset):
    result = await rules_only(dataset)
    [rounding] = [i for i in result.items if i.bank_ids == ("BANK033",)]
    assert (rounding.kind, rounding.resolution, rounding.gl_ids) == ("rounding", "auto_match_with_writeoff", ("GL045",))
    # scenarios.md #7: DR 6990 / CR 1010, 0.01
    e = rounding.entry
    assert (e.debit_account, e.credit_account, e.amount) == ("6990", "1010", Decimal("0.01"))


async def test_rules_only_leaves_what_it_cannot_pair_undecided(dataset):
    result = await rules_only(dataset)
    open_items = [i for i in result.items if i.resolution is None]
    assert all(i.kind == "unknown" and i.entry is None for i in open_items)
    singles = sorted((*i.bank_ids, *i.gl_ids) for i in open_items if len(i.bank_ids) + len(i.gl_ids) == 1)
    assert singles == [("BANK019",), ("BANK032",), ("BANK042",), ("BANK113",), ("GL023",), ("GL034",), ("GL114",)]
    assert len(open_items) == 10  # the 7 rows above plus 3 candidate groups


async def test_rules_only_scores(dataset):
    s = score(dataset, load_ground_truth(), await rules_only(dataset))
    assert (s.match_precision.hit, s.match_precision.total) == (105, 105)
    assert (s.match_recall.hit, s.match_recall.total) == (105, 111)
    # 103 matched items, but the matcher never labels nsf_pair (HANDOFF): the NSF deposit leg
    # BANK056/GL047 (scenarios.md #8) comes back as `exact`, right rows, wrong kind.
    assert (s.kind_accuracy.hit, s.kind_accuracy.total) == (102, 115)
    assert (s.kind_accuracy_by_kind["nsf_pair"].hit, s.kind_accuracy_by_kind["nsf_pair"].total) == (0, 2)
    assert s.false_auto_resolutions == []
    assert (s.correct_escalations.hit, s.correct_escalations.total, s.escalated) == (0, 5, 0)
    assert (s.entry_correctness.hit, s.entry_correctness.total) == (1, 6)  # only the rounding write-off
    assert s.unresolved == 10
    assert s.uncovered_rows == 0  # every bank and GL row lands in some item
    # Raw 864.09 plus the 0.01 write-off taken off the book side; nothing else is explained.
    assert s.final_difference == s.difference_after_approvals == Decimal("864.10")
