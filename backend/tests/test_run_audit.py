"""GET /runs/{id}/audit on the memory run store: the run's audit_log rows, oldest first.

The rows come from the writers that already exist: the guard (one `injection_flagged` row per
flagged bank or GL row plus a `guard_scan` row), and `item-decided` (one row per decision).
"""

import asyncio
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.recon.loader import load_dataset
from app.recon.run_store import MEMORY_RUNS, MemoryRunStore
from app.workflows.reconcile import GUARD_ACTOR
from tests.test_decisions import _decide, _item_decided, _pending, ran  # noqa: F401  (ran is a fixture)

FIELDS = {"id", "run_id", "entity_type", "entity_id", "action", "actor", "model", "detail", "created_at"}
OCT = (date(2026, 10, 1), date(2026, 10, 31))


def test_audit_lists_the_runs_guard_and_decision_rows_oldest_first(ran):  # noqa: F811
    http, run_id, events = ran
    fee = _pending(http, run_id)["BANK032"]
    _decide(http, fee["id"], note="Checked with J Smith on 312-555-0186")
    _item_decided(events[0].data)

    response = http.get(f"/api/v1/runs/{run_id}/audit")
    assert response.status_code == 200
    rows = response.json()
    assert all(set(r) == FIELDS and r["run_id"] == run_id for r in rows)
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)

    scan = next(r for r in rows if r["action"] == "guard_scan")
    assert (scan["entity_type"], scan["entity_id"], scan["actor"]) == ("run", run_id, GUARD_ACTOR)
    flagged = [r for r in rows if r["action"] == "injection_flagged"]
    assert sorted(r["entity_id"] for r in flagged) == sorted(scan["detail"]["flagged_rows"])
    assert all(r["entity_type"] == "guardrail" and r["detail"]["reasons"] for r in flagged)

    (decision,) = [r for r in rows if r["entity_type"] == "item"]
    assert (decision["entity_id"], decision["action"], decision["actor"]) == (
        fee["id"], "approve", "user:demo@bridge.local")
    assert decision["model"] is None and decision["created_at"]
    # The item's row ids label it in the audit trail (ids only, never description text).
    assert (decision["detail"]["bank_ids"], decision["detail"]["gl_ids"]) == (["BANK032"], [])
    # The reviewer's note is free text: masked like any description before it leaves the API.
    assert "[PHONE]" in decision["detail"]["note"] and "312-555-0186" not in response.text


def test_audit_never_carries_bank_or_gl_text(ran):  # noqa: F811
    http, run_id, _ = ran
    text = http.get(f"/api/v1/runs/{run_id}/audit").text
    data = load_dataset("northbrook-2026-10")
    leaked = [r.description for r in (*data.bank, *data.gl) if r.description in text]
    assert leaked == []


@pytest.fixture
def http(app):
    MEMORY_RUNS.clear()
    with TestClient(app) as client:
        yield client
    MEMORY_RUNS.clear()


def test_audit_of_a_run_with_no_rows_is_empty(http):
    run = asyncio.run(MEMORY_RUNS.create_run("northbrook-2026-10", *OCT))
    response = http.get(f"/api/v1/runs/{run.id}/audit")
    assert response.status_code == 200 and response.json() == []


def test_audit_of_an_unknown_run_is_404(http):
    response = http.get("/api/v1/runs/missing/audit")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "run_not_found"


def test_audit_needs_auth_when_the_public_demo_flag_is_off(http, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("PUBLIC_DEMO_API", "false")
    get_settings.cache_clear()
    assert http.get("/api/v1/runs/missing/audit").status_code == 401


async def test_memory_store_lists_only_the_runs_rows_with_a_timestamp():
    store = MemoryRunStore()
    a = await store.create_run("northbrook-2026-10", *OCT)
    b = await store.create_run("northbrook-2026-10", *OCT)
    await store.add_audit(run_id=a.id, entity_type="run", entity_id=a.id, action="guard_scan",
                          actor="system", detail={"masked_rows": 2, "flagged_rows": []})
    await store.add_audit(run_id=b.id, entity_type="item", entity_id="i9", action="reject",
                          actor="user:x", detail={})
    await store.add_audit(run_id=a.id, entity_type="item", entity_id="i1", action="approve",
                          actor="user:x", detail={"note": None})

    rows = await store.list_audit(a.id)
    assert [(r.id, r.action) for r in rows] == [(1, "guard_scan"), (3, "approve")]
    assert all(r.created_at is not None and r.model is None for r in rows)
    assert json.loads(rows[0].model_dump_json())["detail"] == {"masked_rows": 2, "flagged_rows": []}

    await store.reset("northbrook-2026-10", actor="user:demo")
    assert await store.list_audit(a.id) == []  # rows stay in the log with run_id null
    assert store.audit[-1]["action"] == "demo_reset" and store.audit[-1]["created_at"] is not None
