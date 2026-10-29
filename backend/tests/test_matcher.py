"""Rule-based matcher (B-03): exact, check number, one-to-many and rounding, ambiguity left for fuzzy."""

import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.recon import load_dataset
from app.recon.matcher import MatchPolicy, load_match_policy, match
from app.recon.models import BankTxn, GlEntry

GROUND_TRUTH = Path(__file__).resolve().parents[2] / "evals" / "ground_truth.json"

POLICY = MatchPolicy(date_window_days=5, rounding_tolerance=Decimal("1.00"))


def bank(txn_id: str, day: int, amount: str, check: str | None = None) -> BankTxn:
    return BankTxn(
        txn_id=txn_id,
        posted_date=date(2026, 10, day),
        description=f"bank {txn_id}",
        amount=Decimal(amount),
        type="CHECK" if check else "TRANSFER",
        check_number=check,
    )


def gl(entry_id: str, day: int, amount: str, check: str | None = None) -> GlEntry:
    return GlEntry(
        entry_id=entry_id,
        date=date(2026, 10, day),
        description=f"gl {entry_id}",
        amount=Decimal(amount),
        method="CHECK" if check else "TRANSFER",
        check_number=check,
        account="1010",
        counter_account="2000",
    )


def pairs(result) -> set[tuple[str, tuple[tuple[str, ...], tuple[str, ...]]]]:
    return {(m.kind, (m.bank_ids, m.gl_ids)) for m in result.matches}


def test_same_amount_same_day_is_an_exact_match():
    result = match([bank("B1", 1, "-100.00")], [gl("G1", 1, "-100.00")], POLICY)
    assert pairs(result) == {("exact", (("B1",), ("G1",)))}
    assert result.unmatched_bank_ids == ()
    assert result.unmatched_gl_ids == ()


def test_a_date_gap_inside_the_policy_window_is_a_timing_match():
    result = match([bank("B1", 6, "5400.00")], [gl("G1", 1, "5400.00")], POLICY)
    assert pairs(result) == {("timing", (("B1",), ("G1",)))}
    assert result.matches[0].date_gap_days == 5


def test_a_date_gap_outside_the_policy_window_is_unmatched():
    result = match([bank("B1", 7, "5400.00")], [gl("G1", 1, "5400.00")], POLICY)
    assert result.matches == ()
    assert result.candidates == ()
    assert result.unmatched_bank_ids == ("B1",)
    assert result.unmatched_gl_ids == ("G1",)


def test_each_line_pairs_with_its_only_same_day_partner_when_the_window_holds_two():
    # Inside 5 days all four pairings are possible, but each line has one same-day partner.
    result = match(
        [bank("B1", 1, "-2500.00"), bank("B2", 5, "-2500.00")],
        [gl("G1", 1, "-2500.00"), gl("G2", 5, "-2500.00")],
        POLICY,
    )
    assert pairs(result) == {("exact", (("B1",), ("G1",))), ("exact", (("B2",), ("G2",)))}
    assert result.candidates == ()


def test_a_check_pairs_by_number_even_when_another_gl_line_has_the_same_amount():
    result = match(
        [bank("B1", 1, "-1200.00", check="3106")],
        [gl("G1", 1, "-1200.00", check="3106"), gl("G2", 1, "-1200.00")],
        POLICY,
    )
    assert pairs(result) == {("check_number", (("B1",), ("G1",)))}
    assert result.unmatched_gl_ids == ("G2",)


def test_a_check_never_pairs_with_a_gl_line_that_lacks_its_number():
    result = match([bank("B1", 1, "-425.00", check="3111")], [gl("G1", 1, "-425.00")], POLICY)
    assert result.matches == ()
    assert result.candidates == ()
    assert result.unmatched_bank_ids == ("B1",)
    assert result.unmatched_gl_ids == ("G1",)


def test_a_check_with_the_same_number_but_a_different_amount_is_not_matched():
    result = match([bank("B1", 2, "-925.00", check="3200")], [gl("G1", 2, "-952.00", check="3200")], POLICY)
    assert result.matches == ()
    assert result.unmatched_bank_ids == ("B1",)


def test_a_check_number_booked_twice_in_the_gl_is_ambiguous():
    # Mirrors check 2847: cleared once, posted twice. The matcher must not pick one.
    result = match(
        [bank("B1", 1, "-3200.00", check="2847")],
        [gl("G1", 1, "-3200.00", check="2847"), gl("G2", 1, "-3200.00", check="2847")],
        POLICY,
    )
    assert result.matches == ()
    group = result.candidates[0]
    assert (group.bank_ids, group.gl_ids) == (("B1",), ("G1", "G2"))
    assert {o.kind for o in group.options} == {"check_number"}


def test_one_deposit_ties_to_the_gl_lines_that_sum_to_it():
    # 1,200.00 + 850.00 + 2,150.00 = 4,200.00; the 500.00 line does not belong.
    result = match(
        [bank("B1", 8, "4200.00")],
        [gl("G1", 7, "1200.00"), gl("G2", 7, "850.00"), gl("G3", 7, "2150.00"), gl("G4", 8, "500.00")],
        POLICY,
    )
    assert pairs(result) == {("one_to_many", (("B1",), ("G1", "G2", "G3")))}
    assert result.matches[0].amount_delta == Decimal("0.00")
    assert result.unmatched_gl_ids == ("G4",)


def test_one_to_many_ignores_gl_lines_more_than_two_days_away():
    result = match(
        [bank("B1", 8, "4200.00")],
        [gl("G1", 5, "1200.00"), gl("G2", 7, "850.00"), gl("G3", 7, "2150.00")],
        POLICY,
    )
    assert result.matches == ()
    assert result.candidates == ()


def test_one_to_many_uses_at_most_four_gl_lines():
    result = match([bank("B1", 8, "500.00")], [gl(f"G{i}", 8, "100.00") for i in range(1, 6)], POLICY)
    assert result.matches == ()
    assert result.candidates == ()


def test_subset_search_stays_fast_with_many_gl_lines_on_one_day():
    gls = [gl(f"G{i}", 8, f"{i * 7 + 3}.13") for i in range(1, 61)]
    banks = [bank("B1", 8, "1500.52"), bank("B2", 8, "980.39"), bank("B3", 8, "4200.00")]
    start = time.perf_counter()
    match(banks, gls, POLICY)
    assert time.perf_counter() - start < 0.5


def test_two_subsets_summing_to_the_deposit_are_candidates():
    result = match(
        [bank("B1", 8, "300.00")],
        [gl("G1", 8, "100.00"), gl("G2", 8, "200.00"), gl("G3", 8, "200.00")],
        POLICY,
    )
    assert result.matches == ()
    group = result.candidates[0]
    assert {o.gl_ids for o in group.options} == {("G1", "G2"), ("G1", "G3")}
    assert {o.kind for o in group.options} == {"one_to_many"}


def test_a_one_cent_difference_is_a_rounding_match_with_its_delta():
    result = match([bank("B1", 3, "-1234.51")], [gl("G1", 5, "-1234.50")], POLICY)
    assert pairs(result) == {("rounding", (("B1",), ("G1",)))}
    assert result.matches[0].amount_delta == Decimal("-0.01")


def test_a_difference_equal_to_the_tolerance_still_rounds():
    result = match([bank("B1", 3, "-101.00")], [gl("G1", 3, "-100.00")], POLICY)
    assert pairs(result) == {("rounding", (("B1",), ("G1",)))}


def test_a_difference_above_the_tolerance_is_not_rounding():
    # The transposition case: 952.00 booked, 925.00 cleared.
    result = match([bank("B1", 2, "-925.00")], [gl("G1", 3, "-952.00")], POLICY)
    assert result.matches == ()
    assert result.unmatched_bank_ids == ("B1",)
    assert result.unmatched_gl_ids == ("G1",)


def test_an_exact_partner_wins_over_a_rounding_one():
    result = match([bank("B1", 3, "-100.00")], [gl("G1", 3, "-100.00"), gl("G2", 3, "-100.01")], POLICY)
    assert pairs(result) == {("exact", (("B1",), ("G1",)))}
    assert result.unmatched_gl_ids == ("G2",)


def test_two_rounding_partners_are_candidates():
    result = match([bank("B1", 3, "-100.00")], [gl("G1", 3, "-100.01"), gl("G2", 3, "-99.99")], POLICY)
    assert result.matches == ()
    assert {o.kind for o in result.candidates[0].options} == {"rounding"}


def test_a_same_day_partner_is_taken_and_the_later_line_is_left_unmatched():
    # Pins the current nearest-date tie-break (M1, pending Harshil's decision).
    result = match([bank("B1", 1, "-10.00"), bank("B2", 2, "-10.00")], [gl("G1", 1, "-10.00")], POLICY)
    assert pairs(result) == {("exact", (("B1",), ("G1",)))}
    assert result.unmatched_bank_ids == ("B2",)
    assert result.candidates == ()


def test_two_equal_partners_are_returned_as_candidates_not_guessed():
    # Two bank lines and two GL lines of the same amount on the same day: 4 valid pairings.
    result = match(
        [bank("B1", 1, "-950.00"), bank("B2", 1, "-950.00")],
        [gl("G1", 1, "-950.00"), gl("G2", 1, "-950.00")],
        POLICY,
    )
    assert result.matches == ()
    assert len(result.candidates) == 1
    group = result.candidates[0]
    assert group.bank_ids == ("B1", "B2")
    assert group.gl_ids == ("G1", "G2")
    assert {(o.bank_ids, o.gl_ids) for o in group.options} == {
        (("B1",), ("G1",)),
        (("B1",), ("G2",)),
        (("B2",), ("G1",)),
        (("B2",), ("G2",)),
    }
    # Rows waiting for the fuzzy step are not reported as unmatched.
    assert result.unmatched_bank_ids == ()
    assert result.unmatched_gl_ids == ()


def test_one_bank_line_with_two_gl_partners_two_days_apart_each_way_is_ambiguous():
    result = match([bank("B1", 3, "-500.00")], [gl("G1", 1, "-500.00"), gl("G2", 5, "-500.00")], POLICY)
    assert result.matches == ()
    assert [(c.bank_ids, c.gl_ids) for c in result.candidates] == [(("B1",), ("G1", "G2"))]


def test_policy_comes_from_demo_data_policy_json():
    # demo-data/policy.json: date_window_days 5, auto_writeoff_tolerance "1.00".
    assert load_match_policy() == MatchPolicy(date_window_days=5, rounding_tolerance=Decimal("1.00"))


# --- Acceptance against the answer key (tests only; runtime code never reads it) ---


def _demo_result():
    ds = load_dataset("northbrook-2026-10")
    return match(ds.bank, ds.gl, load_match_policy())


def _truth_groups() -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    # Only pairs the answer key auto-matches count; an escalated pair (transposition) must not be matched.
    items = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))["items"]
    return {
        (tuple(sorted(i["bank_ids"])), tuple(sorted(i["gl_ids"])))
        for i in items
        if i["resolution"] in ("auto_match", "auto_match_with_writeoff")
    }


def test_every_match_on_demo_data_is_correct_and_covers_100_items():
    result = _demo_result()
    truth = _truth_groups()
    made = [(tuple(sorted(m.bank_ids)), tuple(sorted(m.gl_ids))) for m in result.matches]
    correct = [m for m in made if m in truth]
    wrong = [m for m in made if m not in truth]
    print(f"matcher: {len(made)} matches, {len(correct)} correct, precision {len(correct) / len(made):.3f}")
    assert wrong == []
    assert len(correct) >= 100


def test_demo_rows_with_no_partner_in_the_answer_key_stay_unmatched():
    # Answer key: bank fee, interest, Zelle receipt, outstanding check 1001, deposit in transit.
    result = _demo_result()
    assert {"BANK032", "BANK042", "BANK113"} <= set(result.unmatched_bank_ids)
    assert {"GL034", "GL114"} <= set(result.unmatched_gl_ids)


def test_the_duplicate_check_2847_goes_to_fuzzy_instead_of_being_guessed():
    result = _demo_result()
    groups = [(c.bank_ids, c.gl_ids) for c in result.candidates]
    assert (("BANK009",), ("GL002", "GL003")) in groups
