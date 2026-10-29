"""The agent pipeline on demo-data with a scripted stub model.

Expected results are the worked example in test_agent_checks.py, plus the statement:
bank closing 48547.99 - outstanding check GL034 325.00 + deposit in transit GL114 3275.40
= 51498.39; book closing 47683.90 - 25.00 + 12.50 + 600.00 + 3200.00 + 27.00 - 0.01 (rounding
write-off) = 51498.39.
"""

import json
from decimal import Decimal

import pytest

from app.agents.pipeline import run_agents
from app.core.errors import LLMUnavailableError
from app.llm import LLMClient
from app.providers.base import Completion, ToolCall
from app.providers.stub import StubProvider
from app.recon.loader import load_dataset

D = Decimal
DATASET = load_dataset("northbrook-2026-10")

FUZZY = {"BANK001": "GL004", "BANK010": "GL014", "BANK080": "GL079", "BANK089": "GL088"}
CLASSIFY = [
    (["BANK019"], ["GL023"], "transposition"),
    (["BANK032"], [], "bank_fee_missing_in_gl"),
    (["BANK042"], [], "interest_missing_in_gl"),
    (["BANK113"], [], "unidentified_receipt"),
    ([], ["GL003"], "duplicate_gl_entry"),
    ([], ["GL034"], "outstanding_check"),
    ([], ["GL114"], "deposit_in_transit"),
]
ENTRIES = {  # item's first row id -> (debit, credit, amount)
    "BANK019": ("1010", "2000", "27.00"),
    "BANK032": ("6800", "1010", "25.00"),
    "BANK042": ("1010", "4100", "12.50"),
    "BANK113": ("1010", "2400", "600.00"),
    "GL003": ("1010", "2000", "3200.00"),
}


def agent(messages) -> str:
    return messages[0].content.splitlines()[0].removeprefix("# ").strip()


def user_json(messages) -> dict:
    return json.loads(next(m.content for m in messages if m.role == "user"))


class Oracle:
    """A well-behaved fake model. Subclasses override one agent to misbehave."""

    def __init__(self) -> None:
        self.prompts: dict[str, list[str]] = {}
        self.resolve_feedback: list[list[str]] = []

    def __call__(self, messages, model):
        name = agent(messages)
        self.prompts.setdefault(name, []).append(messages[-1].content)
        return getattr(self, name)(messages, model)

    def fuzzy_match(self, messages, _model):
        opts = user_json(messages)["options"]
        pairs = [o for o in opts if FUZZY.get(o["bank_id"]) == o["gl_id"]]
        return json.dumps({"pairs": pairs})

    def classify(self, messages, _model):
        return json.dumps({"items": [
            {"bank_ids": b, "gl_ids": g, "kind": k} for b, g, k in CLASSIFY]})

    def resolve(self, messages, model):
        body = user_json(messages)
        if messages[-1].role == "tool":
            return f"Explained {body['item']['id']}."
        self.resolve_feedback.append(body.get("feedback") or [])
        first = (body["item"]["bank_ids"] + body["item"]["gl_ids"])[0]
        if first not in ENTRIES:
            return f"Timing item {first}."
        dr, cr, amount = ENTRIES[first]
        args = {"debit_account": dr, "credit_account": cr, "amount": amount,
                "memo": f"fix {first}", "confidence": 0.9}
        return Completion(content="", model=model, tool_calls=(
            ToolCall(id="c1", name="propose_entry", arguments=json.dumps(args)),))

    def critic(self, _messages, _model):
        return '{"ok": true, "feedback": ""}'

    def report(self, messages, _model):
        f = user_json(messages)
        return (f"## {f['company']}\n\nThe bank closed at {f['bank']['closing_balance']} and the book at "
                f"{f['book']['closing_balance']}, a raw difference of {f['raw_difference']}.\n\n"
                f"- {f['counts']['needs_approval']} items need approval.\n")


def client_for(oracle) -> tuple[LLMClient, StubProvider]:
    provider = StubProvider(responder=oracle)
    return LLMClient(provider, models={"nano": "m-nano", "super": "m-super", "ultra": "m-ultra"},
                     timeouts={"nano": 5, "super": 5, "ultra": 5}), provider


def by_first(items) -> dict:
    return {(i.bank_ids + i.gl_ids)[0]: i for i in items}


async def test_pipeline_closes_the_demo_statement() -> None:
    oracle = Oracle()
    client, _ = client_for(oracle)
    run = await run_agents(DATASET, client)
    items = run.items

    # Every row is in exactly one item.
    bank = [b for i in items for b in i.bank_ids]
    gl = [g for i in items for g in i.gl_ids]
    assert sorted(bank) == sorted(b.txn_id for b in DATASET.bank)
    assert sorted(gl) == sorted(g.entry_id for g in DATASET.gl)

    escalated = {k: i for k, i in by_first(items).items() if i.status == "needs_approval"}
    assert set(escalated) == set(ENTRIES)
    for first, (dr, cr, amount) in ENTRIES.items():
        e = escalated[first].entry
        assert (e.debit_account, e.credit_account, e.amount) == (dr, cr, D(amount))
        assert escalated[first].resolution == "escalate" and escalated[first].checks_passed

    rec = {k for k, i in by_first(items).items() if i.status == "reconciling_item"}
    assert rec == {"GL034", "GL114"}
    auto = {k: i for k, i in by_first(items).items() if i.status == "auto_resolved"}
    assert set(auto) == {"BANK080", "BANK033"}
    assert auto["BANK080"].kind == "nsf_pair"
    wo = auto["BANK033"].entry
    assert (wo.debit_account, wo.credit_account, wo.amount) == ("6990", "1010", D("0.01"))
    assert sum(i.status == "matched" for i in items) == 106

    # Statement closes once the five drafts are approved.
    bank_adj = D("48547.99") - D("325.00") + D("3275.40")
    book = D("47683.90")
    for i in items:
        if i.entry:
            sign = 1 if i.entry.debit_account == "1010" else -1
            book += sign * i.entry.amount
    assert bank_adj == book == D("51498.39")

    steps = {s.id: s for s in run.steps}
    assert steps["match-fuzzy"].tier == "nano" and steps["match-fuzzy"].calls == 2
    assert steps["classify"].calls == 1 and steps["resolve"].tier == "super"
    assert steps["review"].calls == 7


async def test_prompts_carry_masked_untrusted_text_and_computed_numbers() -> None:
    oracle = Oracle()
    client, _ = client_for(oracle)
    await run_agents(DATASET, client)
    resolve_bank113 = next(p for p in oracle.prompts["resolve"] if '"BANK113"' in p
                           and "required_entry" in p)
    assert "****4417" in resolve_bank113 and "312-555-0186" not in resolve_bank113
    assert '<untrusted ref=\\"BANK113\\">' in resolve_bank113
    body = json.loads(resolve_bank113)
    assert body["item"]["amount_delta"] == "600.00"
    assert body["item"]["required_entry"] == {"amount": "600.00", "cash_side": "debit",
                                              "cash_account": "1010"}
    assert "J MARTINEZ" not in "".join(oracle.prompts["classify"])
    # The GL checks (GL003, GL034) are pre-labelled by code, so none reach classify.
    assert json.loads(oracle.prompts["classify"][0])["check_facts"] == {}


class Misclassifies(Oracle):
    def classify(self, messages, _model):
        wrong = {"BANK113": "deposit_in_transit", "GL034": "nsf_pair",
                 "GL114": "outstanding_check", "BANK032": "interest_missing_in_gl"}
        out = []
        for b, g, k in CLASSIFY:
            out.append({"bank_ids": b, "gl_ids": g, "kind": wrong.get((b + g)[0], k)})
        return json.dumps({"items": out})


async def test_misclassified_items_escalate_never_auto() -> None:
    client, _ = client_for(Misclassifies())
    items = by_first((await run_agents(DATASET, client)).items)
    # A lone credit with a kind its rows refute is held in suspense by code, and still escalates.
    assert items["BANK113"].kind == "unidentified_receipt"
    assert items["BANK113"].status == "needs_approval"
    # Code pre-labels the kinds it can prove, so the model's wrong labels never reach them.
    assert items["GL034"].kind == "outstanding_check"
    assert items["GL114"].kind == "deposit_in_transit"
    assert items["BANK032"].kind == "bank_fee_missing_in_gl"


class DropsAndInvents(Oracle):
    def classify(self, messages, _model):
        return json.dumps({"items": [
            {"bank_ids": ["BANK032"], "gl_ids": [], "kind": "bank_fee_missing_in_gl"},
            {"bank_ids": ["BANK999"], "gl_ids": ["GL034"], "kind": "outstanding_check"},
            {"bank_ids": ["BANK032"], "gl_ids": [], "kind": "bank_fee_missing_in_gl"},
        ]})


async def test_classify_output_cannot_drop_or_invent_rows() -> None:
    client, _ = client_for(DropsAndInvents())
    items = (await run_agents(DATASET, client)).items
    bank = [b for i in items for b in i.bank_ids]
    gl = [g for i in items for g in i.gl_ids]
    assert sorted(bank) == sorted(b.txn_id for b in DATASET.bank)
    assert sorted(gl) == sorted(g.entry_id for g in DATASET.gl)
    unknown = {(i.bank_ids + i.gl_ids)[0] for i in items if i.kind == "unknown"}
    assert not unknown  # code labels what Nano dropped when it can prove the kind
    assert by_first(items)["BANK113"].kind == "unidentified_receipt"


class WrongAmounts(Oracle):
    def resolve(self, messages, model):
        if messages[-1].role == "tool":
            return "Explained."
        self.resolve_feedback.append(user_json(messages).get("feedback") or [])
        args = {"debit_account": "6800", "credit_account": "1010", "amount": "1.00", "memo": "x"}
        return Completion(content="", model=model, tool_calls=(
            ToolCall(id="c1", name="propose_entry", arguments=json.dumps(args)),))


async def test_resolve_retries_then_ultra_then_escalates_unknown() -> None:
    oracle = WrongAmounts()
    client, provider = client_for(oracle)
    items = by_first((await run_agents(DATASET, client)).items)
    assert ("m-ultra", False) in provider.calls
    # A code-labelled item keeps its kind and falls back to the code draft.
    fee = items["BANK032"]
    assert fee.kind == "bank_fee_missing_in_gl" and fee.checks_passed
    assert (fee.entry.debit_account, fee.entry.credit_account, fee.entry.amount) == ("6800", "1010", D("25.00"))
    # Retries carry code-check feedback.
    assert any(any("amount" in f for f in fb) for fb in oracle.resolve_feedback)
    # An item with no code draft (here, one built by hand) escalates as unknown with no entry.
    from app.agents.classify import work_item
    from app.agents.context import Books, load_accounts, load_policy
    from app.agents.review import review_item
    books = Books(DATASET, load_policy(), load_accounts())
    bare = work_item(books, ["BANK113"], [], "unidentified_receipt")
    done, _, _ = await review_item(client, bare, books)
    assert done.kind == "unknown" and done.status == "needs_approval" and done.entry is None
    assert not done.checks_passed and done.problems


class CriticRejectsOnce(Oracle):
    def __init__(self) -> None:
        super().__init__()
        self.rejected = False

    def critic(self, messages, _model):
        if not self.rejected and '"BANK032"' in messages[-1].content:
            self.rejected = True
            return '{"ok": false, "feedback": "Say it is the monthly service fee."}'
        return '{"ok": true, "feedback": ""}'


async def test_critic_feedback_triggers_one_retry() -> None:
    oracle = CriticRejectsOnce()
    client, _ = client_for(oracle)
    items = by_first((await run_agents(DATASET, client)).items)
    assert items["BANK032"].kind == "bank_fee_missing_in_gl" and items["BANK032"].checks_passed
    assert ["Say it is the monthly service fee."] in oracle.resolve_feedback


class CriticBroken(Oracle):
    def critic(self, _messages, _model):
        return "not json"


async def test_failed_critic_is_counted_not_hidden() -> None:
    client, _ = client_for(CriticBroken())
    run = await run_agents(DATASET, client)
    items = by_first(run.items)
    assert items["BANK032"].critic_skipped == 1 and items["BANK032"].status == "needs_approval"
    review = next(s for s in run.steps if s.id == "review")
    assert "7 critic calls failed" in review.summary


async def test_code_prelabels_provable_gl_kinds_and_classify_sees_only_the_rest() -> None:
    oracle = Oracle()
    client, _ = client_for(oracle)
    items = by_first((await run_agents(DATASET, client)).items)
    assert items["GL003"].kind == "duplicate_gl_entry"
    assert items["GL034"].kind == "outstanding_check" and items["GL034"].status == "reconciling_item"
    assert items["GL114"].kind == "deposit_in_transit" and items["GL114"].status == "reconciling_item"
    assert items["BANK019"].kind == "transposition" and items["BANK019"].gl_ids == ["GL023"]
    assert items["BANK042"].kind == "interest_missing_in_gl"
    sent = json.loads(oracle.prompts["classify"][0])
    assert sent["gl"] == []
    assert [r["txn_id"] for r in sent["bank"]] == ["BANK113"]  # the one judgment call


class HalfFuzzyLumpyClassify(Oracle):
    """Live pass 4: Nano picked only one pair of two, then lumped rows into one unknown item."""

    def fuzzy_match(self, messages, _model):
        opts = user_json(messages)["options"]
        first = next(o for o in opts if FUZZY.get(o["bank_id"]) == o["gl_id"])
        return json.dumps({"pairs": [first]})

    def classify(self, messages, _model):
        return json.dumps({"items": [{"bank_ids": ["BANK113", "BANK042"], "gl_ids": [], "kind": "unknown"}]})


async def test_forced_pairs_completed_and_unknown_split() -> None:
    client, _ = client_for(HalfFuzzyLumpyClassify())
    items = by_first((await run_agents(DATASET, client)).items)
    # One pick in each 2x2 group forces the other pair.
    assert items["BANK010"].status == "matched" and items["BANK010"].gl_ids == ["GL014"]
    assert items["BANK089"].status == "matched" and items["BANK089"].gl_ids == ["GL088"]
    # A multi-row unknown is split so each row gets its own resolve. (Code labels BANK042 before
    # classify, so the split is checked on classify's own rows.)
    from app.agents.classify import _classify_rest
    from app.agents.context import Books, load_accounts, load_policy
    books = Books(DATASET, load_policy(), load_accounts())
    work, _ = await _classify_rest(client, ["BANK113", "BANK042"], [], books)
    assert sorted(w.bank_ids for w in work) == [("BANK042",), ("BANK113",)]
    assert all(w.kind == "unknown" for w in work)


class NanoDown(Oracle):
    def __init__(self, super_classifies: bool) -> None:
        super().__init__()
        self.super_classifies = super_classifies

    def __call__(self, messages, model):
        if model == "m-nano" or (model == "m-super" and agent(messages) == "classify"
                                 and not self.super_classifies):
            raise LLMUnavailableError("nano call timed out after 30s")
        return super().__call__(messages, model)


async def test_classify_falls_back_to_super_when_nano_fails() -> None:
    client, provider = client_for(NanoDown(super_classifies=True))
    items = by_first((await run_agents(DATASET, client)).items)
    assert items["BANK032"].kind == "bank_fee_missing_in_gl"
    assert items["GL034"].status == "reconciling_item"


async def test_run_survives_classify_and_fuzzy_outage_by_escalating() -> None:
    client, _ = client_for(NanoDown(super_classifies=False))
    run = await run_agents(DATASET, client)
    items = run.items
    assert sorted(b for i in items for b in i.bank_ids) == sorted(b.txn_id for b in DATASET.bank)
    # Only code-proven outcomes survive an outage: the rounding write-off and the
    # pre-labelled reconciling items. Nothing the model would have labelled.
    assert not [i for i in items if i.status == "auto_resolved" and i.kind != "rounding"]
    assert {i.gl_ids[0] for i in items if i.status == "reconciling_item"} == {"GL034", "GL114"}
    assert by_first(items)["BANK001"].status == "needs_approval"  # fuzzy rows escalate


@pytest.mark.parametrize("confidence", [0.0, 1.0])
async def test_confidence_is_display_only(confidence) -> None:
    class Sure(Oracle):
        def resolve(self, messages, model):
            out = super().resolve(messages, model)
            if isinstance(out, Completion):
                args = json.loads(out.tool_calls[0].arguments) | {"confidence": confidence}
                out = Completion(content="", model=model, tool_calls=(
                    ToolCall(id="c1", name="propose_entry", arguments=json.dumps(args)),))
            return out

    client, _ = client_for(Sure())
    items = by_first((await run_agents(DATASET, client)).items)
    assert items["BANK032"].status == "needs_approval"
    assert items["BANK032"].confidence == confidence


# Live progress: `on_step(stage_id, log)` fires with log=None as a stage starts and with its
# StepLog as it ends. Resolve and the critic review interleave per item (critic feedback goes
# back into resolve), so those two start together and end together.
STAGE_EVENTS = [
    ("start", "match-rules"), ("end", "match-rules"),
    ("start", "match-fuzzy"), ("end", "match-fuzzy"),
    ("start", "classify"), ("end", "classify"),
    ("start", "resolve"), ("start", "review"), ("end", "resolve"), ("end", "review"),
    ("start", "decide"), ("end", "decide"),
]


async def test_on_step_reports_each_stage_as_it_starts_and_ends() -> None:
    events: list[tuple[str, str]] = []
    seen_in_classify: list[list[tuple[str, str]]] = []

    class Spy(Oracle):
        def classify(self, messages, model):
            seen_in_classify.append(list(events))
            return super().classify(messages, model)

    async def on_step(stage_id, log):
        events.append(("start" if log is None else "end", stage_id))
        assert log is None or log.id == stage_id

    client, _ = client_for(Spy())
    run = await run_agents(DATASET, client, on_step=on_step)

    assert events == STAGE_EVENTS
    # While classify's model call is in flight, the stages before it have ended and it has started.
    assert seen_in_classify[0] == STAGE_EVENTS[:5]
    assert [s.id for s in run.steps] == ["match-rules", "match-fuzzy", "classify", "resolve", "review", "decide"]


async def test_a_failing_on_step_callback_does_not_change_the_run() -> None:
    calls = 0

    async def broken(stage_id, log):
        nonlocal calls
        calls += 1
        raise RuntimeError("store down")

    client, _ = client_for(Oracle())
    run = await run_agents(DATASET, client, on_step=broken)

    assert calls == len(STAGE_EVENTS)  # every event is still attempted
    assert sum(i.status == "matched" for i in run.items) == 106
    assert sum(i.status == "needs_approval" for i in run.items) == 5


# A label the rows refute is turned into `unknown` before review (review.py), so no draft
# it attracts can pass and nothing closes. Expected problems are kind_problem's own messages.
@pytest.mark.parametrize("label,problem", [
    ("interest_missing_in_gl", "interest_missing_in_gl needs one bank INTEREST credit with no GL line"),
    ("deposit_in_transit", "deposit_in_transit needs one GL deposit near period end"),
])
async def test_a_refuted_classify_label_is_reviewed_as_unknown_and_escalates(label, problem) -> None:
    from app.agents.classify import work_item
    from app.agents.context import Books, load_accounts, load_policy
    from app.agents.review import review_item
    books = Books(DATASET, load_policy(), load_accounts())
    wrong = work_item(books, ["BANK032"], [], label)  # BANK032 is a -25.00 FEE debit
    client, _ = client_for(Oracle())
    done, _, _ = await review_item(client, wrong, books)
    assert (done.kind, done.status, done.resolution) == ("unknown", "needs_approval", "escalate")
    assert not done.checks_passed and done.problems[0] == problem
    assert done.entry is None


class CriticAlwaysNo(Oracle):
    def critic(self, _messages, _model):
        return '{"ok": false, "feedback": "The explanation does not hold up."}'


async def test_a_critic_veto_on_a_timing_item_escalates_instead_of_closing() -> None:
    client, _ = client_for(CriticAlwaysNo())
    items = by_first((await run_agents(DATASET, client)).items)
    check = items["GL034"]  # code-labelled outstanding check: no draft to fall back on
    assert check.status != "reconciling_item"
    assert (check.kind, check.status, check.checks_passed) == ("unknown", "needs_approval", False)
    assert "The explanation does not hold up." in check.problems
    # problems is not persisted: the reasoning must carry the critic's reason.
    assert check.reasoning.startswith(
        "Escalated: the critic rejected the explanation: The explanation does not hold up.")


async def test_a_code_draft_fallback_keeps_the_critic_rejection_visible() -> None:
    client, _ = client_for(CriticAlwaysNo())
    items = by_first((await run_agents(DATASET, client)).items)
    fee = items["BANK032"]
    assert (fee.kind, fee.status, fee.checks_passed) == ("bank_fee_missing_in_gl", "needs_approval", True)
    assert (fee.entry.debit_account, fee.entry.credit_account, fee.entry.amount) == ("6800", "1010", D("25.00"))
    assert fee.problems == ["model fallback: The explanation does not hold up."]
    # Nano labelled the receipt; code only built its draft.
    receipt = items["BANK113"]
    assert receipt.kind == "unidentified_receipt" and receipt.entry is not None
    assert "Labelled by code" not in receipt.reasoning
    assert receipt.reasoning.startswith("Labelled by Nano; draft built by code")
    assert fee.reasoning.startswith("Labelled by code")
