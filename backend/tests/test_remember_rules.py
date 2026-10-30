"""B-14: "remember" saves a rule only when the rule could ever apply, says so in the decision
response, and learned rules survive the demo reset until someone forgets them.

The five demo escalations (B-04 worked example): BANK032 the monthly fee and BANK042 the interest
are recurring postings, so a remembered approval saves a rule. BANK019 (transposition), BANK113
(unidentified receipt) and GL003 (duplicate GL entry) are judgments about which rows are wrong
(`RULE_EXCLUDED_KINDS`), so no rule is saved and the UI must not say one was.
"""

import asyncio

import pytest

from app.recon.run_store import MEMORY_RUNS
from tests.test_decisions import _decide, _item_decided, _pending, ran  # noqa: F401  (ran is a fixture)
from tests.test_learning_loop import _second_run

DATASET = "northbrook-2026-10"
LEARNABLE = {"BANK032": True, "BANK042": True, "BANK019": False, "BANK113": False, "GL003": False}


def _rules(http) -> list[dict]:
    return http.get("/api/v1/rules").json()


def _learned_fee_rule(http, run_id) -> int:
    body = _decide(http, _pending(http, run_id)["BANK032"]["id"], remember=True).json()
    assert body["rule_id"] is not None
    return body["rule_id"]


def test_remember_saves_rules_only_for_the_fee_and_the_interest(ran):
    http, run_id, events = ran
    pending = _pending(http, run_id)
    saved = {}
    for first, item in pending.items():
        response = _decide(http, item["id"], remember=True)
        assert response.status_code == 200
        saved[first] = response.json()["rule_id"]
    assert {k: v is not None for k, v in saved.items()} == LEARNABLE

    rules = _rules(http)
    assert sorted(r["id"] for r in rules) == sorted([saved["BANK032"], saved["BANK042"]])
    assert {r["source_item"] for r in rules} == {pending["BANK032"]["id"], pending["BANK042"]["id"]}
    assert {r["kind"] for r in rules} == {"bank_fee_missing_in_gl", "interest_missing_in_gl"}

    # The item-decided job writes the audit row only: running it saves no second copy.
    outputs = [_item_decided(e.data).output for e in events]
    assert all("rule_id" not in o and o["audit_id"] for o in outputs)
    assert len(_rules(http)) == 2


def test_learnable_matches_what_remember_saves(ran):
    http, run_id, _ = ran
    pending = _pending(http, run_id)
    assert {k: i["learnable"] for k, i in pending.items()} == LEARNABLE
    every = http.get(f"/api/v1/runs/{run_id}/items").json()
    assert all(isinstance(i["learnable"], bool) for i in every)
    body = _decide(http, pending["BANK042"]["id"], remember=True).json()
    assert body["item"]["learnable"] is True and body["rule_id"] is not None


def test_an_injection_flagged_item_is_not_learnable_and_saves_nothing(ran):
    http, run_id, _ = ran
    fee_id = _pending(http, run_id)["BANK032"]["id"]
    items, n = MEMORY_RUNS._find(fee_id)
    items[n] = items[n].model_copy(update={"flags": ["injection_flagged"]})
    assert _pending(http, run_id)["BANK032"]["learnable"] is False
    body = _decide(http, fee_id, remember=True).json()
    assert body["rule_id"] is None and body["item"]["learnable"] is False
    assert _rules(http) == []


def test_reject_and_approve_without_remember_save_no_rule(ran):
    http, run_id, _ = ran
    pending = _pending(http, run_id)
    assert _decide(http, pending["BANK032"]["id"], decision="reject", remember=True).json()["rule_id"] is None
    assert _decide(http, pending["BANK042"]["id"]).json()["rule_id"] is None
    assert _rules(http) == []


def test_the_inline_fallback_saves_the_rule_once(ran, monkeypatch):
    http, run_id, _ = ran

    async def down(*_a, **_k):
        raise RuntimeError("inngest unreachable")

    monkeypatch.setattr("app.workflows.client.inngest_client.send", down)
    fee_id = _pending(http, run_id)["BANK032"]["id"]
    rule_id = _learned_fee_rule(http, run_id)
    assert [r["id"] for r in _rules(http)] == [rule_id]
    decided = [a for a in MEMORY_RUNS.audit if a["entity_id"] == fee_id and a["action"] == "approve"]
    assert len(decided) == 1  # the audit row is still written inline


def test_reset_keeps_learned_rules_and_the_next_run_applies_them(ran, monkeypatch):
    http, run_id, _ = ran
    rule_id = _learned_fee_rule(http, run_id)

    response = http.post("/api/v1/demo/reset")
    assert response.status_code == 200
    assert response.json() == {"dataset": DATASET, "runs_deleted": 1, "rules_kept": 1}
    last = MEMORY_RUNS.audit[-1]
    assert (last["action"], last["detail"]) == ("demo_reset", {"runs_deleted": 1, "rules_kept": 1})
    (rule,) = _rules(http)
    assert rule["id"] == rule_id and rule["source_item"] is None  # its item went with the run

    second = _second_run(monkeypatch)
    items = {(i["bank_ids"] + i["gl_ids"])[0]: i for i in http.get(f"/api/v1/runs/{second}/items").json()}
    fee = items["BANK032"]
    assert (fee["status"], fee["rule_id"]) == ("auto_resolved", rule_id)
    assert fee["reasoning"].startswith(f"Applied rule #{rule_id}")


def test_forgetting_one_rule(ran, monkeypatch):
    http, run_id, _ = ran
    rule_id = _learned_fee_rule(http, run_id)
    seeded = asyncio.run(MEMORY_RUNS.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "X"},
                                               action={}, source_item=None, created_by="system", dataset=DATASET,
                                               origin="seeded"))
    other = asyncio.run(MEMORY_RUNS.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "X"},
                                              action={}, source_item=None, created_by="system", dataset="other"))

    r = http.delete(f"/api/v1/rules/{seeded}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "rule_not_deletable"
    for missing in (other, 999):
        r = http.delete(f"/api/v1/rules/{missing}")
        assert r.status_code == 404 and r.json()["detail"]["code"] == "rule_not_found"

    r = http.delete(f"/api/v1/rules/{rule_id}")
    assert r.status_code == 200 and r.json() == {"rule_id": rule_id}
    assert http.delete(f"/api/v1/rules/{rule_id}").status_code == 404
    assert [x["id"] for x in _rules(http)] == [seeded]
    last = MEMORY_RUNS.audit[-1]
    assert (last["entity_type"], last["entity_id"], last["action"], last["actor"], last["run_id"]) == (
        "rule", str(rule_id), "rule_forgotten", "user:demo@bridge.local", None)

    http.post("/api/v1/demo/reset")
    assert "BANK032" in _pending(http, _second_run(monkeypatch))


def test_forgetting_all_learned_rules(ran, monkeypatch):
    http, run_id, _ = ran
    pending = _pending(http, run_id)
    for first in ("BANK032", "BANK042"):
        _decide(http, pending[first]["id"], remember=True)
    seeded = asyncio.run(MEMORY_RUNS.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "X"},
                                               action={}, source_item=None, created_by="system", dataset=DATASET,
                                               origin="seeded"))
    asyncio.run(MEMORY_RUNS.add_rule(kind="bank_fee_missing_in_gl", pattern={}, action={}, source_item=None,
                                     created_by="system", dataset="other"))

    r = http.delete("/api/v1/rules")
    assert r.status_code == 200 and r.json() == {"rules_deleted": 2}
    assert [x["id"] for x in _rules(http)] == [seeded]
    assert len(asyncio.run(MEMORY_RUNS.list_rules())) == 2  # the other dataset's rule stays
    last = MEMORY_RUNS.audit[-1]
    assert (last["entity_type"], last["entity_id"], last["action"], last["detail"]) == (
        "dataset", DATASET, "rules_forgotten", {"rules_deleted": 2})
    assert http.delete("/api/v1/rules").json() == {"rules_deleted": 0}

    http.post("/api/v1/demo/reset")
    assert {"BANK032", "BANK042"} <= set(_pending(http, _second_run(monkeypatch)))


def test_the_rules_route_shows_each_rules_origin_and_dataset(ran):
    # The UI offers "forget" only for origin == "learned" (a seeded rule is 409 rule_not_deletable).
    http, run_id, _ = ran
    learned = _learned_fee_rule(http, run_id)
    seeded = asyncio.run(MEMORY_RUNS.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "X"},
                                               action={}, source_item=None, created_by="system", dataset=DATASET,
                                               origin="seeded"))
    by_id = {r["id"]: r for r in _rules(http)}
    assert {i: (r["origin"], r["dataset"]) for i, r in by_id.items()} == {
        learned: ("learned", DATASET), seeded: ("seeded", DATASET)}


def test_a_forgotten_rules_id_is_never_reused(ran, monkeypatch):
    # "Applied rule #N" must keep meaning one rule, as with Postgres serial.
    http, run_id, _ = ran
    first = _learned_fee_rule(http, run_id)
    assert http.delete(f"/api/v1/rules/{first}").status_code == 200
    second_run = _second_run(monkeypatch)
    again = _learned_fee_rule(http, second_run)
    assert again != first and [r["id"] for r in _rules(http)] == [again]


@pytest.mark.parametrize("inngest_up", [True, False])
def test_a_failed_rule_save_still_leaves_the_decision_audited(ran, monkeypatch, inngest_up):
    http, run_id, events = ran
    if not inngest_up:
        async def down(*_a, **_k):
            raise ConnectionError("refused")

        monkeypatch.setattr("app.workflows.client.inngest_client.send", down)

    async def broken(*_a, **_k):
        raise RuntimeError("rules table unavailable")

    monkeypatch.setattr("app.api.routes.runs.save_rule", broken)
    fee_id = _pending(http, run_id)["BANK032"]["id"]
    with pytest.raises(RuntimeError):  # still a 500: the reviewer is not told a rule was saved
        _decide(http, fee_id, remember=True)
    if inngest_up:
        (event,) = events
        assert event.data["item_id"] == fee_id
        _item_decided(event.data)
    audited = [a for a in MEMORY_RUNS.audit if a["entity_id"] == fee_id and a["action"] == "approve"]
    assert len(audited) == 1


@pytest.mark.parametrize("path", ["/api/v1/rules", "/api/v1/rules/1"])
def test_forget_routes_need_a_user_without_the_public_demo_flag(app, monkeypatch, path):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    monkeypatch.setenv("PUBLIC_DEMO_API", "false")
    get_settings.cache_clear()
    with TestClient(app) as http:
        assert http.delete(path).status_code == 401
    get_settings.cache_clear()
