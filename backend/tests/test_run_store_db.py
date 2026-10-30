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
        await runs.update_run(run.id, status="running", counts=RunCounts(items=1, needs_approval=1),
                              report="## Report")
        await runs.update_run(run.id, status="completed")

        got = await runs.get_run(run.id)
        assert got.status == "completed" and got.counts.needs_approval == 1 and got.report == "## Report"
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
        assert len(got.steps) == 9 and all(s.status == "completed" for s in got.steps)
        assert got.report and "864.09" in got.report

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
            saved = {}
            for item in pending:
                assert item["learnable"] is (item["kind"] in ("bank_fee_missing_in_gl", "interest_missing_in_gl"))
                r = http.post(f"/api/v1/items/{item['id']}/decision", json={"decision": "approve", "remember": True})
                assert r.status_code == 200, r.text
                saved[item["kind"]] = r.json()["rule_id"]
            assert r.json()["statement"]["unreconciled_difference"] == "0.00"
            assert http.get("/api/v1/statement", params={"run_id": run.id}).json()["unreconciled_difference"] == "0.00"
            # B-14: only the fee and the interest teach a rule, saved inline by the decision.
            learned = [v for v in saved.values() if v is not None]
            assert sorted(k for k, v in saved.items() if v is not None) == [
                "bank_fee_missing_in_gl", "interest_missing_in_gl"]

            decided = [mocked.trigger(item_decided, e, mocked.Inngest(app_id="test")) for e in events]
            assert all(d.status is mocked.Status.COMPLETED and "rule_id" not in d.output for d in decided)

            seeded = asyncio.run(runs.add_rule(kind="unknown", pattern={"description_regex": "X"}, action={},
                                               source_item=None, created_by="system", dataset=DATASET,
                                               origin="seeded"))
            reset = http.post("/api/v1/demo/reset").json()
            assert reset["runs_deleted"] >= 1 and reset["rules_kept"] >= 2
            assert http.get(f"/api/v1/runs/{run.id}").status_code == 404
            after = {r.id: r for r in asyncio.run(runs.list_rules())}
            assert seeded in after and all(after[i].source_item is None for i in learned)  # rules survive

            assert http.delete(f"/api/v1/rules/{seeded}").status_code == 409
            assert http.delete(f"/api/v1/rules/{learned[0]}").json() == {"rule_id": learned[0]}
            assert http.delete(f"/api/v1/rules/{learned[0]}").status_code == 404
            assert http.delete("/api/v1/rules").json()["rules_deleted"] >= 1
            assert seeded in [r.id for r in asyncio.run(runs.list_rules())]

            async def audit_and_drop_rule():
                import psycopg

                async with await psycopg.AsyncConnection.connect(DATABASE_URL, prepare_threshold=None) as conn:
                    kept = await (await conn.execute(
                        "select count(*) from audit_log where run_id is null and entity_type = 'item' "
                        "and entity_id = any(%s)", ([i["id"] for i in pending],))).fetchone()
                    last = await (await conn.execute(
                        "select action, entity_id, detail from audit_log where action = 'demo_reset' "
                        "order by id desc limit 1")).fetchone()
                    await conn.execute("delete from rules where id = %s", (seeded,))
                    return kept[0], last

            kept, last = asyncio.run(audit_and_drop_rule())
            assert kept == 5  # the five approvals outlive their run (append-only audit_log)
            assert last[:2] == ("demo_reset", DATASET) and last[2]["rules_kept"] == reset["rules_kept"]
    finally:
        asyncio.run(_delete(run.id))
        get_settings.cache_clear()


async def test_db_run_store_shows_live_stage_progress():
    """reconcile-run's progress writes: one row at a time, a stage completed while the next runs."""
    from app.workflows.reconcile import STAGES, _step

    runs = DbRunStore(DATABASE_URL)
    run = await runs.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31))
    try:
        await runs.save_steps(run.id, [_step(s.id, "pending") for s in STAGES])
        started = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        await runs.save_steps(run.id, [_step("classify", "running", started_at=started)])
        await runs.save_steps(run.id, [_step("classify", "completed", model="m-nano", started_at=started,
                                             finished_at=started, latency_ms=1200, tokens_in=50,
                                             tokens_out=9, output_summary="7 items classified")])
        await runs.save_steps(run.id, [_step("resolve", "running", started_at=started)])

        steps = {s.id: s for s in (await runs.get_run(run.id)).steps}
        assert {k: s.status for k, s in steps.items()} == {
            "load": "pending", "guard": "pending", "match-rules": "pending", "match-fuzzy": "pending",
            "classify": "completed", "resolve": "running", "review": "pending", "decide": "pending",
            "report": "pending"}
        c = steps["classify"]
        assert (c.tier, c.model, c.latency_ms, c.tokens_in, c.tokens_out) == ("nano", "m-nano", 1200, 50, 9)
    finally:
        await _delete(run.id)


async def test_db_run_store_lists_a_runs_audit_rows_oldest_first():
    runs = DbRunStore(DATABASE_URL)
    run = await runs.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31))
    other = await runs.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31))
    try:
        assert await runs.list_audit(run.id) == []
        first = await runs.add_audit(run_id=run.id, entity_type="run", entity_id=run.id, action="guard_scan",
                                     actor="agent:guard", detail={"masked_rows": 2, "flagged_rows": ["BANK077"]})
        await runs.add_audit(run_id=other.id, entity_type="run", entity_id=other.id, action="guard_scan",
                             actor="agent:guard", detail={})
        second = await runs.add_audit(run_id=run.id, entity_type="item", entity_id="i1", action="approve",
                                      actor="user:demo@bridge.local", detail={"note": None})
        rows = await runs.list_audit(run.id)
        assert [(r.id, r.action, r.run_id) for r in rows] == [(first, "guard_scan", run.id), (second, "approve", run.id)]
        assert rows[0].detail == {"masked_rows": 2, "flagged_rows": ["BANK077"]}
        assert rows[0].model is None and rows[0].created_at is not None
    finally:
        await _delete(run.id)
        await _delete(other.id)


async def test_db_run_store_lists_only_a_datasets_active_rules():
    import psycopg

    runs = DbRunStore(DATABASE_URL)
    mine = await runs.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "B13 TEST FEE"},
                               action={}, source_item=None, created_by="system", dataset=DATASET)
    other = await runs.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "B13 TEST FEE"},
                                action={}, source_item=None, created_by="system", dataset="b13-other")
    off = await runs.add_rule(kind="bank_fee_missing_in_gl", pattern={"description_regex": "B13 TEST FEE"},
                              action={}, source_item=None, created_by="system", dataset=DATASET)
    try:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, prepare_threshold=None) as conn:
            await conn.execute("update rules set active = false where id = %s", (off,))
        ids = [r.id for r in await runs.list_rules(DATASET)]
        assert mine in ids and other not in ids and off not in ids
        assert {mine, other, off} <= {r.id for r in await runs.list_rules()}
    finally:
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, prepare_threshold=None) as conn:
            await conn.execute("delete from rules where id = any(%s)", ([mine, other, off],))
