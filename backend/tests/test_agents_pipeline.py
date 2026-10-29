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
    for first in ("BANK113", "BANK032"):
        assert items[first].kind == "unknown"
        assert items[first].status == "needs_approval"
        assert items[first].problems
    # Code pre-labels the GL kinds it can prove, so the model's wrong labels never reach them.
    assert items["GL034"].kind == "outstanding_check"
    assert items["GL114"].kind == "deposit_in_transit"


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
    assert {"BANK113", "BANK042", "BANK019", "GL023"} <= unknown
    assert not {"GL034", "GL114", "GL003"} & unknown  # pre-labelled by code


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
    fee = items["BANK032"]
    assert fee.kind == "unknown" and fee.status == "needs_approval" and fee.entry is None
    assert not fee.checks_passed and fee.problems
    assert ("m-ultra", False) in provider.calls
    # Retries carry code-check feedback.
    assert any(any("amount" in f for f in fb) for fb in oracle.resolve_feedback)


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
    sent = json.loads(oracle.prompts["classify"][0])
    assert sorted(r["entry_id"] for r in sent["gl"]) == ["GL023"]
    assert sorted(r["txn_id"] for r in sent["bank"]) == ["BANK019", "BANK032", "BANK042", "BANK113"]


class HalfFuzzyLumpyClassify(Oracle):
    """Live pass 4: Nano picked only one pair of two, then lumped rows into one unknown item."""

    def fuzzy_match(self, messages, _model):
        opts = user_json(messages)["options"]
        first = next(o for o in opts if FUZZY.get(o["bank_id"]) == o["gl_id"])
        return json.dumps({"pairs": [first]})

    def classify(self, messages, _model):
        body = user_json(messages)
        ids = [r["txn_id"] for r in body["bank"]] + [r["entry_id"] for r in body["gl"]]
        lumped = {"BANK113", "BANK042"}
        items = [{"bank_ids": b, "gl_ids": g, "kind": k} for b, g, k in CLASSIFY
                 if not lumped & set(b + g)]
        items.append({"bank_ids": ["BANK113", "BANK042"], "gl_ids": [], "kind": "unknown"})
        assert set(ids) >= lumped
        return json.dumps({"items": items})


async def test_forced_pairs_completed_and_unknown_split() -> None:
    client, _ = client_for(HalfFuzzyLumpyClassify())
    items = by_first((await run_agents(DATASET, client)).items)
    # One pick in each 2x2 group forces the other pair.
    assert items["BANK010"].status == "matched" and items["BANK010"].gl_ids == ["GL014"]
    assert items["BANK089"].status == "matched" and items["BANK089"].gl_ids == ["GL088"]
    # A multi-row unknown is split so each row gets its own resolve.
    assert items["BANK113"].bank_ids == ["BANK113"] and items["BANK042"].bank_ids == ["BANK042"]


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
