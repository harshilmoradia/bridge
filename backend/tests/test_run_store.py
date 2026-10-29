"""MemoryRunStore: the run store used when DATABASE_URL is unset (tests, local dev without a DB)."""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.recon.run_store import MemoryRunStore
from app.schemas.runs import Item, ProposedEntry, RunCounts, RunStep

OCT = (date(2026, 10, 1), date(2026, 10, 31))
NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def _step(step_id: str, position: int, status: str = "pending") -> RunStep:
    return RunStep(id=step_id, position=position, agent=step_id, label=step_id, tier="code", status=status)


def _item(item_id: str, run_id: str, status: str, entry: ProposedEntry | None = None) -> Item:
    return Item(id=item_id, run_id=run_id, kind="exact", resolution="auto_match", status=status,
                bank_ids=["BANK001"], gl_ids=["GL001"], amount_delta=Decimal("0.00"), evidence=[],
                flags=[], proposed_entry=entry, created_at=NOW)


async def test_create_run_is_queued_with_no_steps():
    store = MemoryRunStore()
    run = await store.create_run("northbrook-2026-10", *OCT)
    assert (run.status, run.steps, run.counts, run.report) == ("queued", [], RunCounts(), None)
    assert await store.get_run(run.id) == run
    assert await store.get_run("missing") is None


async def test_steps_upsert_by_id_and_sort_by_position():
    store = MemoryRunStore()
    run = await store.create_run("northbrook-2026-10", *OCT)
    await store.save_steps(run.id, [_step("b", 2), _step("a", 1)])
    await store.save_steps(run.id, [_step("b", 2, "completed")])
    got = await store.get_run(run.id)
    assert [(s.id, s.status) for s in got.steps] == [("a", "pending"), ("b", "completed")]


async def test_update_run_sets_status_counts_and_error():
    store = MemoryRunStore()
    run = await store.create_run("northbrook-2026-10", *OCT)
    await store.update_run(run.id, status="completed", counts=RunCounts(items=3, matched=3))
    got = await store.get_run(run.id)
    assert (got.status, got.counts.items, got.counts.matched, got.error) == ("completed", 3, 3, None)
    assert got.updated_at >= run.updated_at


async def test_update_run_keeps_the_report_once_set():
    store = MemoryRunStore()
    run = await store.create_run("northbrook-2026-10", *OCT)
    await store.update_run(run.id, status="running", report="## Report")
    await store.update_run(run.id, status="completed")
    got = await store.get_run(run.id)
    assert (got.status, got.report) == ("completed", "## Report")


async def test_replace_items_overwrites_and_filters_by_status():
    store = MemoryRunStore()
    run = await store.create_run("northbrook-2026-10", *OCT)
    await store.replace_items(run.id, [_item("old", run.id, "matched")])
    await store.replace_items(run.id, [_item("i1", run.id, "matched"), _item("i2", run.id, "needs_approval")])
    assert [i.id for i in await store.list_items(run.id)] == ["i1", "i2"]
    assert [i.id for i in await store.list_items(run.id, "needs_approval")] == ["i2"]


async def test_returned_runs_are_copies():
    store = MemoryRunStore()
    run = await store.create_run("northbrook-2026-10", *OCT)
    run.status = "failed"
    assert (await store.get_run(run.id)).status == "queued"


def test_db_run_items_row_maps_kind_and_entry():
    from app.recon.store import _item_ref

    row = {"id": "i1", "status": "approved", "bank_ids": ["BANK032"], "gl_ids": [], "kind": "bank_fee_missing_in_gl",
           "debit_account": "6800", "credit_account": "1010", "amount": Decimal("30.00"), "memo": "edit"}
    ref = _item_ref(row)
    assert ref.kind == "bank_fee_missing_in_gl" and ref.bank_ids == ("BANK032",)
    assert (ref.entry.debit_account, ref.entry.amount) == ("6800", Decimal("30.00"))
    no_entry = _item_ref({**row, "debit_account": None, "credit_account": None, "amount": None, "memo": None})
    assert no_entry.entry is None


async def test_reset_keeps_audit_history_and_seeded_rules_and_logs_itself():
    store = MemoryRunStore()
    run = await store.create_run("northbrook-2026-10", *OCT)
    await store.replace_items(run.id, [_item("i1", run.id, "approved")])
    kept_run = await store.create_run("other", *OCT)
    await store.add_audit(run_id=run.id, entity_type="item", entity_id="i1", action="approve", actor="user:a",
                          detail={})

    def rule(dataset: str, origin: str = "learned", source: str | None = "i1"):
        return store.add_rule(kind="exact", pattern={"description_regex": "X"}, action={}, source_item=source,
                              created_by="user:a", dataset=dataset, origin=origin)

    await rule("northbrook-2026-10")
    await rule("northbrook-2026-10", source=None)  # learned, its item long gone: still this dataset's
    seeded = await rule("northbrook-2026-10", origin="seeded", source=None)
    other = await rule("other", source=None)

    assert await store.reset("northbrook-2026-10", actor="user:demo") == (1, 2)

    assert await store.get_run(run.id) is None and await store.get_run(kept_run.id) is not None
    assert [r.id for r in await store.list_rules()] == [seeded, other]
    decision, reset = store.audit
    assert (decision["entity_id"], decision["action"], decision["run_id"]) == ("i1", "approve", None)
    assert (reset["entity_type"], reset["entity_id"], reset["action"], reset["actor"], reset["run_id"]) == (
        "dataset", "northbrook-2026-10", "demo_reset", "user:demo", None)
    assert reset["detail"] == {"runs_deleted": 1, "rules_deleted": 2}
