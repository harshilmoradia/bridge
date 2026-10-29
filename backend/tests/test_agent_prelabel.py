"""Code pre-labels: the leftover rows whose kind code can prove get that kind and a code-built draft,
so the demo's approve-all close never depends on Nano's label or Super's entry.

Expected kinds and drafts are the worked example in test_agent_checks.py, read off the demo-data
CSVs (bank_statement.csv, gl_entries.csv) and the chart of accounts:
- BANK032 type FEE -25.00 -> DR 6800 Bank Fees / CR 1010, 25.00.
- BANK042 type INTEREST +12.50 -> DR 1010 / CR 4100 Interest Income, 12.50 (the live run's 12.50 gap).
- BANK019 -925.00 vs GL023 -952.00 (digits swapped) -> DR 1010 / CR 2000 (GL023's counter), 27.00.
- GL003, a second copy of matched GL002 (check 2847, -3200.00, counter 2000) -> DR 1010 / CR 2000, 3200.00.
- GL034 check 1001 -325.00, never cleared -> outstanding check, no entry.
- GL114 deposit on Oct 10, the period's last day -> deposit in transit, no entry.
- BANK113 Zelle +600.00 is a judgment call (who paid, for what): it is left for Nano.
"""

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from app.agents.classify import prelabel
from app.agents.context import Books, load_accounts, load_policy
from app.agents.pipeline import run_agents
from app.agents.review import review_item
from app.core.errors import LLMUnavailableError
from app.recon.loader import load_dataset
from tests.test_agents_pipeline import Oracle, by_first, client_for

D = Decimal
DATASET = load_dataset("northbrook-2026-10")
LEFT_BANK = ["BANK019", "BANK032", "BANK042", "BANK113"]  # what rule and fuzzy matching leave
LEFT_GL = ["GL003", "GL023", "GL034", "GL114"]


def books_for(dataset=DATASET, left_gl=LEFT_GL) -> Books:
    matched = frozenset(g.entry_id for g in dataset.gl if g.entry_id not in left_gl)
    return Books(dataset, load_policy(), load_accounts(), matched_gl_ids=matched)


def _by_first(items):
    return {(w.bank_ids + w.gl_ids)[0]: w for w in items}


def _draft(w):
    return None if w.draft is None else (w.draft.debit_account, w.draft.credit_account, w.draft.amount)


def test_prelabels_the_provable_demo_rows_with_code_drafts():
    items, rest_bank, rest_gl = prelabel(books_for(), LEFT_BANK, LEFT_GL)
    got = {k: (w.kind, w.bank_ids, w.gl_ids, _draft(w)) for k, w in _by_first(items).items()}
    assert got == {
        "BANK032": ("bank_fee_missing_in_gl", ("BANK032",), (), ("6800", "1010", D("25.00"))),
        "BANK042": ("interest_missing_in_gl", ("BANK042",), (), ("1010", "4100", D("12.50"))),
        "BANK019": ("transposition", ("BANK019",), ("GL023",), ("1010", "2000", D("27.00"))),
        "GL003": ("duplicate_gl_entry", (), ("GL003",), ("1010", "2000", D("3200.00"))),
        "GL034": ("outstanding_check", (), ("GL034",), None),
        "GL114": ("deposit_in_transit", (), ("GL114",), None),
    }
    assert all(w.source == "code" for w in items)
    assert (rest_bank, rest_gl) == (["BANK113"], [])


def _with_gl(**changes_by_id) -> object:
    gl = tuple(g.model_copy(update=changes_by_id[g.entry_id]) if g.entry_id in changes_by_id else g
               for g in DATASET.gl)
    return DATASET.model_copy(update={"gl": gl})


def test_a_duplicate_check_is_found_by_its_check_number_even_with_a_different_memo():
    data = _with_gl(GL003={"description": "Granite Mutual - duplicate keying"})
    items, _, _ = prelabel(books_for(data), [], ["GL003"])
    assert [(w.kind, _draft(w)) for w in items] == [("duplicate_gl_entry", ("1010", "2000", D("3200.00")))]


def test_a_same_check_number_far_from_its_twin_is_not_a_certain_duplicate():
    far = DATASET.balances.period_end + timedelta(days=30)
    data = _with_gl(GL003={"description": "Granite Mutual - later", "date": far})
    items, _, rest_gl = prelabel(books_for(data), [], ["GL003"])
    assert items == [] and rest_gl == ["GL003"]


def _with_bank(**changes_by_id):
    bank = tuple(b.model_copy(update=changes_by_id[b.txn_id]) if b.txn_id in changes_by_id else b
                 for b in DATASET.bank)
    return DATASET.model_copy(update={"bank": bank})


@pytest.mark.parametrize("row,change", [
    ("BANK032", {"amount": D("25.00")}),  # a "fee" that pays money in: the sign does not fit
    ("BANK042", {"amount": D("-12.50")}),  # "interest" that takes money out
    ("BANK032", {"type": "DEBIT"}),  # the description says fee, the bank's type does not
])
def test_bank_rows_whose_signal_is_not_certain_are_left_for_nano(row, change):
    data = _with_bank(**{row: change})
    items, rest_bank, _ = prelabel(books_for(data), [row], [])
    assert items == [] and rest_bank == [row]


def test_a_transposition_with_two_possible_partners_is_left_for_nano():
    # A second leftover GL line with the same swapped digits makes the pairing a judgment call.
    twin = DATASET.gl[[g.entry_id for g in DATASET.gl].index("GL023")].model_copy(
        update={"entry_id": "GL900"})
    data = DATASET.model_copy(update={"gl": DATASET.gl + (twin,)})
    items, rest_bank, rest_gl = prelabel(books_for(data, [*LEFT_GL, "GL900"]), ["BANK019"], ["GL023", "GL900"])
    assert items == [] and rest_bank == ["BANK019"] and rest_gl == ["GL023", "GL900"]


class ResolveDown(Oracle):
    """Super and Ultra never answer resolve: only code can label and draft."""

    def resolve(self, messages, model):
        raise LLMUnavailableError("resolve timed out")


async def test_code_labelled_items_keep_their_kind_and_draft_when_the_model_fails():
    client, _ = client_for(ResolveDown())
    items = by_first((await run_agents(DATASET, client)).items)
    for first, kind, draft in [
        ("BANK032", "bank_fee_missing_in_gl", ("6800", "1010", D("25.00"))),
        ("BANK042", "interest_missing_in_gl", ("1010", "4100", D("12.50"))),
        ("BANK019", "transposition", ("1010", "2000", D("27.00"))),
        ("GL003", "duplicate_gl_entry", ("1010", "2000", D("3200.00"))),
    ]:
        i = items[first]
        assert (i.kind, i.status, i.checks_passed) == (kind, "needs_approval", True)
        assert (i.entry.debit_account, i.entry.credit_account, i.entry.amount) == draft
        assert i.reasoning and "BANK" not in (i.entry.memo.replace(first, ""))  # ids only, no row text
    assert items["GL034"].status == items["GL114"].status == "reconciling_item"
    # Nano labelled the receipt (a valid kind), so code attaches its draft as the fallback too.
    receipt = items["BANK113"]
    assert (receipt.kind, receipt.status) == ("unidentified_receipt", "needs_approval")
    assert (receipt.entry.debit_account, receipt.entry.credit_account, receipt.entry.amount) == (
        "1010", "2400", D("600.00"))


class LabelsEverythingUnknown(Oracle):
    def classify(self, messages, _model):
        body = json.loads(messages[-1].content)
        return json.dumps({"items": [{"bank_ids": [r["txn_id"]], "gl_ids": [], "kind": "unknown"}
                                     for r in body["bank"]]})


async def test_nano_never_sees_code_labelled_rows():
    oracle = LabelsEverythingUnknown()
    client, _ = client_for(oracle)
    items = by_first((await run_agents(DATASET, client)).items)
    sent = json.loads(oracle.prompts["classify"][0])
    assert [r["txn_id"] for r in sent["bank"]] == ["BANK113"] and sent["gl"] == []
    assert items["BANK042"].kind == "interest_missing_in_gl"


async def test_a_model_entry_that_passes_the_checks_is_kept_over_the_code_draft():
    # Oracle's fee entry is the same as the code's; give it a different expense account.
    class OtherExpense(Oracle):
        def resolve(self, messages, model):
            out = super().resolve(messages, model)
            if not isinstance(out, str) and '"BANK032"' in messages[-1].content:
                args = json.loads(out.tool_calls[0].arguments) | {"debit_account": "6990"}
                out = type(out)(content="", model=model, tool_calls=(
                    type(out.tool_calls[0])(id="c1", name="propose_entry", arguments=json.dumps(args)),))
            return out

    client, _ = client_for(OtherExpense())
    fee = by_first((await run_agents(DATASET, client)).items)["BANK032"]
    assert (fee.entry.debit_account, fee.entry.amount, fee.model) == ("6990", D("25.00"), "m-super")


async def test_review_of_a_code_item_falls_back_to_the_code_draft_after_the_ladder():
    books = books_for()
    items, _, _ = prelabel(books, ["BANK042"], [])
    client, _ = client_for(ResolveDown())
    done, resolve_stats, _ = await review_item(client, items[0], books)
    assert (done.kind, done.status, done.resolution) == ("interest_missing_in_gl", "needs_approval", "escalate")
    assert (done.entry.debit_account, done.entry.credit_account, done.entry.amount) == ("1010", "4100", D("12.50"))
    assert done.model is None and done.checks_passed
    # The model's failure stays visible next to the code draft; decide reads only checks_passed.
    assert done.problems and all(p.startswith("model fallback: ") for p in done.problems)


class UnknownAndResolveDown(LabelsEverythingUnknown, ResolveDown):
    """Live run 1 after pre-labels: Nano gave up on the Zelle credit and resolve drafted nothing."""


async def test_a_lone_credit_nano_gives_up_on_is_held_in_suspense_by_code():
    client, _ = client_for(UnknownAndResolveDown())
    receipt = by_first((await run_agents(DATASET, client)).items)["BANK113"]
    assert (receipt.kind, receipt.status, receipt.checks_passed) == ("unidentified_receipt", "needs_approval", True)
    assert (receipt.entry.debit_account, receipt.entry.credit_account, receipt.entry.amount) == (
        "1010", "2400", D("600.00"))


def test_a_credit_a_leftover_book_deposit_could_explain_stays_unknown():
    from app.agents.prelabel import backstop, work_item
    books = books_for()
    gave_up = [work_item(books, ["BANK113"], [], "unknown")]
    # GL114 is a +3275.40 deposit: with a book credit still unexplained, the pairing is a judgment call.
    assert backstop(books, gave_up, ["GL114"]) == gave_up
    assert [w.kind for w in backstop(books, gave_up, [])] == ["unidentified_receipt"]


def test_a_nano_label_that_fails_its_check_is_not_given_a_draft():
    from app.agents.prelabel import backstop, work_item
    books = books_for()
    wrong = [work_item(books, ["BANK032"], [], "interest_missing_in_gl")]  # a fee, not interest
    assert backstop(books, wrong, []) == wrong


def test_a_voided_and_reissued_check_is_not_a_duplicate():
    # GL901 voids check 2847 (+3200.00) and GL902 re-records it (-3200.00): the pair nets to zero,
    # so GL902 is not a second payment even though matched GL002 has the same check and amount.
    base = DATASET.gl[[g.entry_id for g in DATASET.gl].index("GL002")]
    void = base.model_copy(update={"entry_id": "GL901", "amount": D("3200.00"), "description": "Void check 2847"})
    again = base.model_copy(update={"entry_id": "GL902", "description": "Re-record check 2847"})
    data = DATASET.model_copy(update={"gl": DATASET.gl + (void, again)})
    items, _, rest_gl = prelabel(books_for(data, [*LEFT_GL, "GL901", "GL902"]), [], ["GL902"])
    assert items == [] and rest_gl == ["GL902"]


@pytest.mark.parametrize("bank_amount,gl_amount", [
    ("-1005.00", "-1500.00"),  # same digits, but 5 and 0 are not neighbours (difference 495 = 9 x 55)
    ("-231.00", "-123.00"),  # a rotation of three digits (difference 108 = 9 x 12)
    ("-92.50", "-952.00"),  # different lengths
])
def test_only_two_adjacent_swapped_digits_are_a_transposition(bank_amount, gl_amount):
    data = _with_bank(BANK019={"amount": D(bank_amount)})
    data = data.model_copy(update={"gl": tuple(
        g.model_copy(update={"amount": D(gl_amount)}) if g.entry_id == "GL023" else g for g in data.gl)})
    items, rest_bank, rest_gl = prelabel(books_for(data), ["BANK019"], ["GL023"])
    assert items == [] and rest_bank == ["BANK019"] and rest_gl == ["GL023"]


def test_a_cents_position_swap_is_a_transposition():
    # -12.34 vs -12.43: 3 and 4 swap in the cents; the difference is 0.09, so `% 9` on dollars fails.
    data = _with_bank(BANK019={"amount": D("-12.34")})
    data = data.model_copy(update={"gl": tuple(
        g.model_copy(update={"amount": D("-12.43")}) if g.entry_id == "GL023" else g for g in data.gl)})
    items, _, _ = prelabel(books_for(data), ["BANK019"], ["GL023"])
    assert [(w.kind, w.bank_ids, w.gl_ids) for w in items] == [("transposition", ("BANK019",), ("GL023",))]
    assert items[0].draft.amount == D("0.09")


def test_transposition_reasoning_says_two_adjacent_digits_swapped():
    from app.agents.prelabel import code_reasoning
    books = books_for()
    items, _, _ = prelabel(books, ["BANK019"], ["GL023"])
    assert "two adjacent digits swapped" in code_reasoning(items[0], books)
