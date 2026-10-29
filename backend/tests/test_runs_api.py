"""POST /runs, GET /runs/{id}, GET /runs/{id}/items with the memory run store (no DATABASE_URL)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.recon.run_store import MEMORY_RUNS
from app.schemas.runs import Item, ProposedEntry

BODY = {"dataset": "northbrook-2026-10", "period_start": "2026-10-01", "period_end": "2026-10-31"}


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    MEMORY_RUNS.clear()
    events = []

    async def fake_send(events_, *, skip_middleware=False):
        events.append(events_)
        return ["evt-1"]

    monkeypatch.setattr("app.api.routes.runs.inngest_client.send", fake_send)
    yield events
    MEMORY_RUNS.clear()


async def test_post_runs_queues_a_run_and_sends_the_event(client, sent):
    response = await client.post("/api/v1/runs", json=BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued" and body["id"]
    assert len(sent) == 1
    assert sent[0].name == "bridge/run.requested"
    assert sent[0].data == {"run_id": body["id"], **BODY}

    run = (await client.get(f"/api/v1/runs/{body['id']}")).json()
    assert (run["status"], run["dataset"], run["steps"], run["report"]) == ("queued", "northbrook-2026-10", [], None)
    assert run["counts"]["items"] == 0


async def test_post_runs_rejects_unknown_dataset_and_reversed_period(client, sent):
    unknown = await client.post("/api/v1/runs", json={**BODY, "dataset": "nope"})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "dataset_not_found"
    reversed_ = await client.post("/api/v1/runs", json={**BODY, "period_start": "2026-11-01"})
    assert reversed_.status_code == 422 and reversed_.json()["detail"]["code"] == "invalid_date_range"
    assert sent == []


async def test_post_runs_fails_the_run_when_inngest_is_unreachable(client, monkeypatch):
    async def down(_events, *, skip_middleware=False):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("app.api.routes.runs.inngest_client.send", down)
    response = await client.post("/api/v1/runs", json=BODY)

    assert response.status_code == 503 and response.json()["detail"]["code"] == "workflow_unavailable"
    (run,) = MEMORY_RUNS._runs.values()
    assert run.status == "failed" and run.error.code == "workflow_unavailable"


async def test_unknown_run_is_404(client):
    for path in ("/api/v1/runs/missing", "/api/v1/runs/missing/items"):
        response = await client.get(path)
        assert response.status_code == 404 and response.json()["detail"]["code"] == "run_not_found"


def _item(run_id: str, item_id: str, status: str, entry: bool) -> Item:
    return Item(
        id=item_id, run_id=run_id, kind="bank_fee_missing_in_gl" if entry else "exact",
        resolution="escalate" if entry else "auto_match", status=status,
        bank_ids=["BANK032"] if entry else ["BANK005"], gl_ids=[] if entry else ["GL008"],
        amount_delta=Decimal("-25.00") if entry else Decimal("0"), evidence=[], flags=[],
        proposed_entry=ProposedEntry(id="e1", debit_account="6800", credit_account="1010",
                                     amount=Decimal("25"), memo="fee", status="draft") if entry else None,
        created_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )


async def test_items_list_and_status_filter(client):
    run_id = (await client.post("/api/v1/runs", json=BODY)).json()["id"]
    await MEMORY_RUNS.replace_items(run_id, [_item(run_id, "i1", "matched", False),
                                             _item(run_id, "i2", "needs_approval", True)])

    everything = (await client.get(f"/api/v1/runs/{run_id}/items")).json()
    assert [i["id"] for i in everything] == ["i1", "i2"]
    (pending,) = (await client.get(f"/api/v1/runs/{run_id}/items", params={"status": "needs_approval"})).json()
    assert pending["amount_delta"] == "-25.00" and pending["proposed_entry"]["amount"] == "25.00"
    assert everything[0]["amount_delta"] == "0.00" and everything[0]["proposed_entry"] is None

    bad = await client.get(f"/api/v1/runs/{run_id}/items", params={"status": "bogus"})
    assert bad.status_code == 422


async def test_runs_need_auth_when_the_public_demo_flag_is_off(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("PUBLIC_DEMO_API", "false")
    get_settings.cache_clear()
    assert (await client.post("/api/v1/runs", json=BODY)).status_code == 401
    assert (await client.get("/api/v1/runs/missing")).status_code == 401
