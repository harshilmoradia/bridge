"""DbRunStore and DbStore.run_items against a seeded Supabase database. Skipped unless DATABASE_URL is set.

Statement numbers are the B-04 worked example: book closing 47683.90, the 25.00 bank fee is
BANK032, and an approved entry moves the book side by its cash effect.
"""

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.recon.run_store import DbRunStore
from app.recon.statement import build_statement
from app.recon.store import DbStore
from app.schemas.runs import Item, ProposedEntry, RunCounts, RunStep

DATASET = "northbrook-2026-10"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not set")


def _fee(run_id: str) -> Item:
    return Item(
        id=str(uuid4()), run_id=run_id, kind="bank_fee_missing_in_gl", resolution="escalate",
        status="needs_approval", bank_ids=["BANK032"], gl_ids=[], amount_delta=Decimal("-25.00"),
        reasoning="fee", evidence=[{"type": "bank_transaction", "id": "BANK032", "note": None}],
        flags=[], model="m-super", confidence=0.9,
        proposed_entry=ProposedEntry(id=str(uuid4()), debit_account="6800", credit_account="1010",
                                     amount=Decimal("25.00"), memo="Record fee", status="draft"),
        created_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )


async def _delete(run_id: str) -> None:
    import psycopg

    async with await psycopg.AsyncConnection.connect(DATABASE_URL, prepare_threshold=None) as conn:
        await conn.execute("delete from runs where id::text = %s", (run_id,))


async def test_db_run_store_round_trip_and_statement_lines():
    runs = DbRunStore(DATABASE_URL)
    run = await runs.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31))
    try:
        assert run.status == "queued"
        await runs.save_steps(run.id, [RunStep(id="load", position=1, agent="loader", label="Load",
                                               tier="code", status="pending")])
        await runs.save_steps(run.id, [RunStep(id="load", position=1, agent="loader", label="Load",
                                               tier="code", status="completed", output_summary="ok")])
        fee = _fee(run.id)
        await runs.replace_items(run.id, [fee])
        await runs.replace_items(run.id, [fee])  # a retried step must not duplicate items
        await runs.update_run(run.id, status="completed", counts=RunCounts(items=1, needs_approval=1))

        got = await runs.get_run(run.id)
        assert got.status == "completed" and got.counts.needs_approval == 1
        assert [(s.id, s.status, s.output_summary) for s in got.steps] == [("load", "completed", "ok")]
        (item,) = await runs.list_items(run.id, "needs_approval")
        assert item.proposed_entry.amount == Decimal("25.00") and item.evidence[0].id == "BANK032"
        assert await runs.list_items(run.id, "matched") == []

        reads = DbStore(DATABASE_URL)
        (ref,) = (await reads.run_items(DATASET, run.id)).items
        assert ref.kind == "bank_fee_missing_in_gl" and ref.entry.amount == Decimal("25.00")
        dataset = await reads.dataset(DATASET)
        (line,) = build_statement(dataset, run.id, [ref]).book.lines
        assert (line.amount, line.applied) == (Decimal("-25.00"), False)

        import psycopg
        from psycopg.types.json import Jsonb

        async with await psycopg.AsyncConnection.connect(DATABASE_URL, prepare_threshold=None) as conn:
            await conn.execute("update items set status = 'approved' where id::text = %s", (fee.id,))
            await conn.execute(
                "insert into decisions (item_id, decision, actor, entry_override) values (%s::uuid, 'approve', 'test', %s)",
                (fee.id, Jsonb({"debit_account": "6800", "credit_account": "1010", "amount": "30.00", "memo": "edit"})),
            )
        (ref,) = (await reads.run_items(DATASET, run.id)).items
        assert (ref.entry.amount, ref.entry.memo) == (Decimal("30.00"), "edit")
        (listed,) = await runs.list_items(run.id)  # the items API agrees with the statement
        assert (listed.proposed_entry.amount, listed.proposed_entry.memo) == (Decimal("30.00"), "edit")
        statement = build_statement(dataset, run.id, [ref])
        assert statement.book.adjusted_balance == Decimal("47653.90")  # 47683.90 - 30.00
    finally:
        await _delete(run.id)


def test_reconcile_run_writes_the_db_and_the_statement_reads_it(monkeypatch):
    """The whole workflow on Postgres with the scripted model (worked example in test_agents_pipeline)."""
    import asyncio

    import inngest
    from inngest.experimental import mocked

    from app.core.config import get_settings
    from app.workflows.reconcile import reconcile_run
    from tests.test_agents_pipeline import Oracle, client_for

    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("DATASET", DATASET)
    get_settings.cache_clear()
    client, _ = client_for(Oracle())
    monkeypatch.setattr("app.workflows.reconcile.get_llm_client", lambda _settings: client)
    runs = DbRunStore(DATABASE_URL)
    run = asyncio.run(runs.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31)))
    try:
        result = mocked.trigger(reconcile_run, inngest.Event(name="bridge/run.requested", data={
            "run_id": run.id, "dataset": DATASET, "period_start": "2026-10-01", "period_end": "2026-10-31"}),
            mocked.Inngest(app_id="test"))
        assert result.status is mocked.Status.COMPLETED, result.error

        got = asyncio.run(runs.get_run(run.id))
        assert got.status == "completed" and got.counts.items == 115 and got.counts.needs_approval == 5
        assert len(got.steps) == 8 and all(s.status == "completed" for s in got.steps)

        async def statement():
            reads = DbStore(DATABASE_URL)
            return build_statement(await reads.dataset(DATASET), run.id, (await reads.run_items(DATASET, run.id)).items)

        s = asyncio.run(statement())
        assert s.bank.adjusted_balance == Decimal("51498.39")  # 48547.99 - 325.00 + 3275.40
        assert len(s.book.lines) == 6  # five drafts plus the posted rounding write-off
        assert s.book.adjusted_balance == Decimal("47683.89")  # only the 0.01 write-off is applied yet
    finally:
        asyncio.run(_delete(run.id))
        get_settings.cache_clear()


def test_b12_approving_all_five_closes_the_statement_on_postgres(monkeypatch):
    """B-12 acceptance on Postgres: run, approve the 5 drafts over HTTP, statement 0.00, then reset."""
    import asyncio

    import inngest
    from fastapi.testclient import TestClient
    from inngest.experimental import mocked

    from app.core.config import get_settings
    from app.main import create_app
    from app.workflows.item_decided import item_decided
    from app.workflows.reconcile import reconcile_run
    from tests.test_agents_pipeline import Oracle, client_for

    for key, value in {"DATABASE_URL": DATABASE_URL, "DATASET": DATASET, "LLM_PROVIDER": "stub",
                       "PUBLIC_DEMO_API": "true", "SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": ""}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    llm, _ = client_for(Oracle())
    monkeypatch.setattr("app.workflows.reconcile.get_llm_client", lambda _settings: llm)
    events = []

    async def fake_send(event, *, skip_middleware=False):
        events.append(event)
        return ["evt"]

    monkeypatch.setattr("app.workflows.client.inngest_client.send", fake_send)
    runs = DbRunStore(DATABASE_URL)
    run = asyncio.run(runs.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31)))
    try:
        result = mocked.trigger(reconcile_run, inngest.Event(name="bridge/run.requested", data={
            "run_id": run.id, "dataset": DATASET, "period_start": "2026-10-01", "period_end": "2026-10-31"}),
            mocked.Inngest(app_id="test"))
        assert result.status is mocked.Status.COMPLETED, result.error
        with TestClient(create_app()) as http:
            pending = http.get(f"/api/v1/runs/{run.id}/items", params={"status": "needs_approval"}).json()
            assert len(pending) == 5
            for n, item in enumerate(pending):
                r = http.post(f"/api/v1/items/{item['id']}/decision",
                              json={"decision": "approve", "remember": n == 0})
                assert r.status_code == 200, r.text
            assert r.json()["statement"]["unreconciled_difference"] == "0.00"
            assert http.get("/api/v1/statement", params={"run_id": run.id}).json()["unreconciled_difference"] == "0.00"

            decided = [mocked.trigger(item_decided, e, mocked.Inngest(app_id="test")) for e in events]
            assert all(d.status is mocked.Status.COMPLETED for d in decided)
            assert decided[0].output["rule_id"] is not None and decided[1].output["rule_id"] is None

            seeded = asyncio.run(runs.add_rule(kind="unknown", pattern={"description_regex": "X"}, action={},
                                               source_item=None, created_by="system", dataset=DATASET,
                                               origin="seeded"))
            reset = http.post("/api/v1/demo/reset").json()
            assert reset["runs_deleted"] >= 1 and reset["rules_deleted"] >= 1
            assert http.get(f"/api/v1/runs/{run.id}").status_code == 404
            assert seeded in [r.id for r in asyncio.run(runs.list_rules())]  # seeded rules stay

            async def audit_and_drop_rule():
                import psycopg

                async with await psycopg.AsyncConnection.connect(DATABASE_URL, prepare_threshold=None) as conn:
                    kept = await (await conn.execute(
                        "select count(*) from audit_log where run_id is null and entity_type = 'item' "
                        "and entity_id = any(%s)", ([i["id"] for i in pending],))).fetchone()
                    last = await (await conn.execute(
                        "select action, entity_id, detail from audit_log order by id desc limit 1")).fetchone()
                    await conn.execute("delete from rules where id = %s", (seeded,))
                    return kept[0], last

            kept, last = asyncio.run(audit_and_drop_rule())
            assert kept == 5  # the five approvals outlive their run (append-only audit_log)
            assert last[:2] == ("demo_reset", DATASET) and last[2]["rules_deleted"] == reset["rules_deleted"]
    finally:
        asyncio.run(_delete(run.id))
        get_settings.cache_clear()
