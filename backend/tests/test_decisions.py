"""B-12 on the memory run store: decisions, the item-decided function, rules and the demo reset.

Numbers are the worked example in test_agents_pipeline.py (B-04): after the scripted run the bank
side adjusts to 51498.39 and the book side to 47683.89 (only the 0.01 write-off is posted), so the
statement shows 3814.50; approving the five correct drafts (27.00, -25.00, 12.50, 600.00, 3200.00)
brings the book side to 51498.39 and the difference to 0.00.
"""

import asyncio
import json
from datetime import date

import inngest
import pytest
from fastapi.testclient import TestClient
from inngest.experimental import mocked

from app.recon.run_store import MEMORY_RUNS
from tests.test_agents_pipeline import Oracle, client_for

DATASET = "northbrook-2026-10"


@pytest.fixture
def ran(app, monkeypatch):
    """A completed scripted run in the memory store, plus an HTTP client and the sent events."""
    from app.workflows.reconcile import reconcile_run

    MEMORY_RUNS.clear()
    llm, _ = client_for(Oracle())
    monkeypatch.setattr("app.workflows.reconcile.get_llm_client", lambda _settings: llm)
    events: list = []

    async def fake_send(events_, *, skip_middleware=False):
        events.append(events_)
        return ["evt"]

    monkeypatch.setattr("app.workflows.client.inngest_client.send", fake_send)
    run = asyncio.run(MEMORY_RUNS.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31)))
    result = mocked.trigger(reconcile_run, inngest.Event(name="bridge/run.requested", data={
        "run_id": run.id, "dataset": DATASET, "period_start": "2026-10-01", "period_end": "2026-10-31"}),
        mocked.Inngest(app_id="test"))
    assert result.status is mocked.Status.COMPLETED, result.error
    with TestClient(app) as http:
        yield http, run.id, events
    MEMORY_RUNS.clear()


def _pending(http, run_id) -> dict[str, dict]:
    items = http.get(f"/api/v1/runs/{run_id}/items", params={"status": "needs_approval"}).json()
    return {(i["bank_ids"] + i["gl_ids"])[0]: i for i in items}


def _decide(http, item_id, **body):
    return http.post(f"/api/v1/items/{item_id}/decision", json={"decision": "approve", **body})


def test_statement_reflects_the_memory_run_before_any_decision(ran):
    http, run_id, _ = ran
    statement = http.get("/api/v1/statement").json()
    assert statement["run_id"] == run_id
    assert statement["bank"]["adjusted_balance"] == "51498.39"
    assert statement["book"]["adjusted_balance"] == "47683.89"
    assert statement["unreconciled_difference"] == "3814.50"
    rows = {r["txn_id"]: r for r in http.get("/api/v1/bank-transactions").json()}
    assert rows["BANK032"]["recon_status"] == "needs_approval" and rows["BANK032"]["item_id"]


def test_approving_all_five_escalations_closes_the_statement(ran):
    http, run_id, events = ran
    pending = _pending(http, run_id)
    assert set(pending) == {"BANK019", "BANK032", "BANK042", "BANK113", "GL003"}

    for first in ("BANK019", "BANK032", "BANK042", "BANK113", "GL003"):
        response = _decide(http, pending[first]["id"], note="checked")
        assert response.status_code == 200
        body = response.json()
        assert body["item"]["status"] == "approved" and body["item"]["proposed_entry"]["status"] == "approved"

    assert body["statement"]["unreconciled_difference"] == "0.00"
    statement = http.get("/api/v1/statement", params={"run_id": run_id}).json()
    assert statement["book"]["adjusted_balance"] == statement["bank"]["adjusted_balance"] == "51498.39"
    assert statement["unreconciled_difference"] == "0.00"
    assert http.get(f"/api/v1/runs/{run_id}/items", params={"status": "needs_approval"}).json() == []

    assert [e.name for e in events] == ["bridge/item.decided"] * 5
    assert set(events[0].data) == {"item_id", "decision_id", "run_id"}  # IDs only


def test_reject_leaves_the_book_side_alone(ran):
    http, run_id, _ = ran
    fee = _pending(http, run_id)["BANK032"]
    body = _decide(http, fee["id"], decision="reject").json()
    assert body["item"]["status"] == "rejected" and body["item"]["proposed_entry"]["status"] == "rejected"
    assert body["statement"]["unreconciled_difference"] == "3814.50"


def test_entry_override_replaces_the_draft(ran):
    http, run_id, _ = ran
    fee = _pending(http, run_id)["BANK032"]
    override = {"debit_account": "6800", "credit_account": "1010", "amount": "30.00", "memo": "Fee incl. wire"}
    body = _decide(http, fee["id"], entry_override=override).json()
    entry = body["item"]["proposed_entry"]
    assert (entry["amount"], entry["memo"], entry["status"]) == ("30.00", "Fee incl. wire", "approved")
    assert body["statement"]["unreconciled_difference"] == "3844.50"  # 51498.39 - (47683.89 - 30.00)


@pytest.mark.parametrize("override, code", [
    ({"debit_account": "9999", "credit_account": "1010", "amount": "25.00", "memo": "m"}, "invalid_entry_override"),
    ({"debit_account": "1010", "credit_account": "1010", "amount": "25.00", "memo": "m"}, "invalid_entry_override"),
    ({"debit_account": "6800", "credit_account": "1010", "amount": "25.001", "memo": "m"}, "invalid_entry_override"),
    ({"debit_account": "6800", "credit_account": "1010", "amount": "25.00", "memo": " "}, "invalid_entry_override"),
    ({"debit_account": "6800", "credit_account": "1010", "amount": "1000000000000.00", "memo": "m"},
     "invalid_entry_override"),  # over numeric(14,2): was a 500
    ({"debit_account": "6800", "credit_account": "1010", "amount": "-1", "memo": "m"}, "invalid_request"),
    ({"debit_account": "6800", "credit_account": "1010", "amount": 25.0, "memo": "m"}, "invalid_request"),
])
def test_bad_overrides_are_422_and_leave_the_item_pending(ran, override, code):
    http, run_id, _ = ran
    fee = _pending(http, run_id)["BANK032"]
    response = _decide(http, fee["id"], entry_override=override)
    assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert "BANK032" in _pending(http, run_id)


def test_decision_errors(ran):
    http, run_id, _ = ran
    fee = _pending(http, run_id)["BANK032"]
    override = {"debit_account": "6800", "credit_account": "1010", "amount": "25.00", "memo": "m"}
    reject_edit = _decide(http, fee["id"], decision="reject", entry_override=override)
    assert reject_edit.status_code == 422 and reject_edit.json()["detail"]["code"] == "override_requires_approve"

    assert _decide(http, fee["id"]).status_code == 200
    again = _decide(http, fee["id"])
    assert again.status_code == 409 and again.json()["detail"]["code"] == "item_not_pending"

    matched = http.get(f"/api/v1/runs/{run_id}/items", params={"status": "matched"}).json()[0]
    assert _decide(http, matched["id"]).json()["detail"]["code"] == "item_not_pending"
    missing = _decide(http, "no-such-item")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "item_not_found"


def _decision_audit() -> list[dict]:
    return [a for a in MEMORY_RUNS.audit if a["entity_type"] == "item"]  # the guard writes its own rows


def _item_decided(data: dict):
    from app.workflows.item_decided import item_decided

    return mocked.trigger(item_decided, inngest.Event(name="bridge/item.decided", data=data),
                          mocked.Inngest(app_id="test"))


def test_item_decided_writes_audit_and_a_remembered_rule(ran):
    http, run_id, events = ran
    pending = _pending(http, run_id)
    _decide(http, pending["BANK032"]["id"], remember=True)
    _decide(http, pending["BANK042"]["id"])

    remembered = _item_decided(events[0].data)
    plain = _item_decided(events[1].data)

    assert remembered.status is plain.status is mocked.Status.COMPLETED
    assert plain.output["rule_id"] is None
    rule_id = remembered.output["rule_id"]
    assert all(isinstance(v, (int, str)) for v in remembered.output.values() if v is not None)
    (rule,) = asyncio.run(MEMORY_RUNS.list_rules())
    assert rule.id == rule_id and rule.kind == "bank_fee_missing_in_gl" and rule.active
    assert rule.pattern == {"description_regex": "MONTHLY SERVICE FEE"}
    assert rule.action == {"debit": "6800", "credit": "1010"}
    assert (rule.source_item, rule.created_by) == (pending["BANK032"]["id"], "user:demo@bridge.local")
    audit = _decision_audit()
    assert [(a["entity_id"], a["action"], a["actor"]) for a in audit] == [
        (pending["BANK032"]["id"], "approve", "user:demo@bridge.local"),
        (pending["BANK042"]["id"], "approve", "user:demo@bridge.local"),
    ]
    assert audit[0]["run_id"] == run_id and audit[0]["detail"]["remember"] is True


def test_decision_records_audit_inline_when_inngest_is_down(ran, monkeypatch):
    http, run_id, _ = ran

    async def down(_events, *, skip_middleware=False):
        raise ConnectionError("refused")

    monkeypatch.setattr("app.workflows.client.inngest_client.send", down)
    fee = _pending(http, run_id)["BANK032"]
    assert _decide(http, fee["id"], remember=True).status_code == 200
    assert len(_decision_audit()) == 1 and len(asyncio.run(MEMORY_RUNS.list_rules())) == 1


def test_rule_pattern_keeps_pii_out():
    from app.recon.decisions import description_pattern

    assert description_pattern("ZELLE FROM J MARTINEZ ACCT ****4417 PH 312-555-0186 MEMO OCT ORDER") == "ZELLE"
    assert description_pattern("ONLINE PMT BOXCRAFT PKG CONF#780728") == "ONLINE PMT BOXCRAFT PKG"
    assert description_pattern("MONTHLY SERVICE FEE") == "MONTHLY SERVICE FEE"
    assert "SMITH" not in description_pattern("PAYMENT FROM JOHN SMITH")  # mask_pii misses this name
    assert "OKAFOR" not in description_pattern("ACH DEBIT REIMB D OKAFOR")


def _gl_item(gl_id: str):
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.schemas.runs import Item, ProposedEntry

    return Item(id="i", run_id="r", kind="unknown", resolution="escalate", status="approved", bank_ids=[],
                gl_ids=[gl_id], amount_delta=Decimal("1.00"), evidence=[], flags=[],
                proposed_entry=ProposedEntry(id="e", debit_account="1010", credit_account="5000",
                                             amount=Decimal("1.00"), memo="m", status="approved"),
                created_at=datetime(2026, 10, 28, tzinfo=timezone.utc))


def test_learned_rules_keep_people_out_and_businesses_in():
    from app.recon.decisions import rule_for
    from app.recon.loader import load_dataset

    data = load_dataset(DATASET)
    person, _ = rule_for(_gl_item("GL069"), data)  # Employee Salary - Michael Chen
    assert "chen" not in json.dumps(person).lower() and "michael" not in json.dumps(person).lower()
    business, _ = rule_for(_gl_item("GL003"), data)  # Granite Mutual Insurance
    assert business == {"description_regex": "Invoice payment", "counterparty": "Granite Mutual Insurance"}
    from app.recon.decisions import _is_business

    for name in ("Sarah Patel", "David Okafor", "John Smith", "Payroll advance - James Wilson"):
        assert not _is_business(name, data), name


def test_demo_reset_clears_runs_and_learned_rules_and_keeps_history(ran):
    http, run_id, events = ran
    fee = _pending(http, run_id)["BANK032"]
    _decide(http, fee["id"], remember=True)
    _item_decided(events[0].data)
    audit_before = len(MEMORY_RUNS.audit)

    seeded = asyncio.run(MEMORY_RUNS.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "X"},
                                               action={}, source_item=None, created_by="system", dataset=DATASET,
                                               origin="seeded"))
    response = http.post("/api/v1/demo/reset")
    assert response.status_code == 200
    assert response.json() == {"dataset": DATASET, "runs_deleted": 1, "rules_deleted": 1}
    assert [r.id for r in asyncio.run(MEMORY_RUNS.list_rules())] == [seeded]  # seeded rules stay
    assert http.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert http.get("/api/v1/statement").json()["unreconciled_difference"] == "864.09"
    assert len(MEMORY_RUNS.audit) == audit_before + 1  # history kept, the reset logged on top
    last = MEMORY_RUNS.audit[-1]
    assert (last["action"], last["entity_id"], last["actor"]) == ("demo_reset", DATASET, "user:demo@bridge.local")
    assert last["detail"] == {"runs_deleted": 1, "rules_deleted": 1}


def test_demo_reset_is_off_without_the_public_demo_flag(app, monkeypatch):
    from app.api.auth import DEMO_USER, AuthContext, get_user_or_demo
    from app.core.config import get_settings

    monkeypatch.setenv("PUBLIC_DEMO_API", "false")
    get_settings.cache_clear()
    app.dependency_overrides[get_user_or_demo] = lambda: AuthContext(user=DEMO_USER, token="t")
    with TestClient(app) as http:
        response = http.post("/api/v1/demo/reset")
    assert response.status_code == 403 and response.json()["detail"]["code"] == "demo_reset_disabled"


def test_decided_event_payload_has_no_row_text(ran):
    http, run_id, events = ran
    _decide(http, _pending(http, run_id)["BANK113"]["id"], note="Zelle from J Martinez")
    dumped = json.dumps(events[0].data)
    assert "MARTINEZ" not in dumped.upper() and "4417" not in dumped


def test_recording_an_unknown_decision_is_a_404_item_not_found():
    from app.core.errors import AppError
    from app.recon.decisions import write_audit
    from app.recon.run_store import MemoryRunStore

    with pytest.raises(AppError) as err:
        asyncio.run(write_audit(MemoryRunStore(), item_id="nope", decision_id="nope", run_id="r"))
    assert (err.value.status_code, err.value.code) == (404, "item_not_found")
