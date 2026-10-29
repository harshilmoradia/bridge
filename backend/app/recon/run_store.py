"""Where runs, their steps, items, decisions, audit rows and rules live: Postgres or memory.

Postgres when DATABASE_URL is set, else one process-wide memory store, so the API and the Inngest
functions (served by the same app) share it in local dev without a database. Both speak the v1
schemas.
"""

from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.common import ApiError
from app.schemas.runs import EntryOverride, Item, ProposedEntry, Rule, Run, RunCounts, RunStatus, RunStep

Verdict = Literal["approve", "reject"]
RuleOrigin = Literal["learned", "seeded"]
LIVE_RUN_STATUSES = ("running", "completed")  # runs whose items label rows and feed the statement


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Decision(BaseModel):
    id: str
    item_id: str
    decision: Verdict
    actor: str
    note: str | None = None
    remember: bool = False
    entry_override: EntryOverride | None = None


def item_not_found(item_id: str) -> AppError:
    return AppError(code="item_not_found", message=f"Item {item_id} does not exist", status_code=404)


def item_not_pending(item_id: str, status: str) -> AppError:
    return AppError(code="item_not_pending", message=f"Item {item_id} is {status}; only needs_approval items "
                    "can be decided", status_code=409)


class RunStore(Protocol):
    async def create_run(self, dataset: str, period_start: date, period_end: date) -> Run: ...

    async def get_run(self, run_id: str) -> Run | None: ...

    async def latest_run_id(self, dataset: str) -> str | None: ...

    async def update_run(
        self, run_id: str, *, status: RunStatus, counts: RunCounts | None = None, error: ApiError | None = None
    ) -> None: ...

    async def save_steps(self, run_id: str, steps: Sequence[RunStep]) -> None:
        """Insert or replace steps by id."""
        ...

    async def replace_items(self, run_id: str, items: Sequence[Item]) -> None:
        """Drop the run's items and write these, with their proposed entries (safe to retry)."""
        ...

    async def list_items(self, run_id: str, status: str | None = None) -> list[Item]: ...

    async def get_item(self, item_id: str) -> Item | None: ...

    async def decide_item(
        self, item_id: str, *, decision: Verdict, actor: str, note: str | None, remember: bool,
        override: EntryOverride | None,
    ) -> tuple[Item, str]:
        """Record the decision and move a needs_approval item (and its entry) to approved/rejected.

        An override replaces the draft entry, or becomes the entry when there was none. Raises
        item_not_found (404) or item_not_pending (409). Returns the item and the decision id.
        """
        ...

    async def get_decision(self, decision_id: str) -> Decision | None: ...

    async def add_audit(
        self, *, run_id: str | None, entity_type: str, entity_id: str, action: str, actor: str,
        detail: dict[str, Any],
    ) -> int: ...

    async def add_rule(
        self, *, kind: str, pattern: dict[str, Any], action: dict[str, Any], source_item: str | None,
        created_by: str, dataset: str, origin: RuleOrigin = "learned",
    ) -> int: ...

    async def list_rules(self) -> list[Rule]: ...

    async def reset(self, dataset: str, *, actor: str) -> tuple[int, int]:
        """Delete the dataset's runs (with steps, items, entries and decisions) and its learned rules.

        Seeded rules and other datasets' rules stay. `audit_log` is append-only: its rows stay (their
        `run_id` goes null) and the reset adds a `demo_reset` row with the counts. Returns (runs
        deleted, rules deleted).
        """
        ...


def _entry_after(entry: ProposedEntry | None, override: EntryOverride | None, status: str) -> ProposedEntry | None:
    if override is not None:
        return ProposedEntry(id=entry.id if entry else str(uuid4()), status=status, **override.model_dump())
    return entry.model_copy(update={"status": status}) if entry else None


class MemoryRunStore:
    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self._runs: dict[str, Run] = {}
        self._items: dict[str, list[Item]] = {}
        self._decisions: dict[str, Decision] = {}
        self.audit: list[dict[str, Any]] = []
        self._rules: list[Rule] = []
        self._rule_scope: dict[int, tuple[str, RuleOrigin]] = {}  # rule id -> (dataset, origin)

    async def create_run(self, dataset: str, period_start: date, period_end: date) -> Run:
        now = _now()
        run = Run(id=str(uuid4()), dataset=dataset, period_start=period_start, period_end=period_end,
                  status="queued", created_at=now, updated_at=now, steps=[], counts=RunCounts())
        self._runs[run.id] = run
        self._items[run.id] = []
        return run.model_copy(deep=True)

    async def get_run(self, run_id: str) -> Run | None:
        run = self._runs.get(run_id)
        return run.model_copy(deep=True) if run else None

    async def latest_run_id(self, dataset: str) -> str | None:
        live = [r for r in self._runs.values() if r.dataset == dataset and r.status in LIVE_RUN_STATUSES]
        return max(live, key=lambda r: r.created_at).id if live else None

    async def update_run(
        self, run_id: str, *, status: RunStatus, counts: RunCounts | None = None, error: ApiError | None = None
    ) -> None:
        run = self._runs[run_id]
        run.status, run.error, run.updated_at = status, error, _now()
        if counts is not None:
            run.counts = counts

    async def save_steps(self, run_id: str, steps: Sequence[RunStep]) -> None:
        run = self._runs[run_id]
        by_id = {s.id: s for s in run.steps} | {s.id: s.model_copy(deep=True) for s in steps}
        run.steps = sorted(by_id.values(), key=lambda s: (s.position, s.id))
        run.updated_at = _now()

    async def replace_items(self, run_id: str, items: Sequence[Item]) -> None:
        self._items[run_id] = [i.model_copy(deep=True) for i in items]

    async def list_items(self, run_id: str, status: str | None = None) -> list[Item]:
        return [i.model_copy(deep=True) for i in self._items.get(run_id, []) if status in (None, i.status)]

    def _find(self, item_id: str) -> tuple[list[Item], int] | None:
        for items in self._items.values():
            for n, item in enumerate(items):
                if item.id == item_id:
                    return items, n
        return None

    async def get_item(self, item_id: str) -> Item | None:
        found = self._find(item_id)
        return found[0][found[1]].model_copy(deep=True) if found else None

    async def decide_item(
        self, item_id: str, *, decision: Verdict, actor: str, note: str | None, remember: bool,
        override: EntryOverride | None,
    ) -> tuple[Item, str]:
        found = self._find(item_id)
        if found is None:
            raise item_not_found(item_id)
        items, n = found
        item = items[n]
        if item.status != "needs_approval":
            raise item_not_pending(item_id, item.status)
        status = "approved" if decision == "approve" else "rejected"
        items[n] = item.model_copy(update={"status": status,
                                           "proposed_entry": _entry_after(item.proposed_entry, override, status)})
        d = Decision(id=str(uuid4()), item_id=item_id, decision=decision, actor=actor, note=note,
                     remember=remember, entry_override=override)
        self._decisions[d.id] = d
        return items[n].model_copy(deep=True), d.id

    async def get_decision(self, decision_id: str) -> Decision | None:
        return self._decisions.get(decision_id)

    async def add_audit(
        self, *, run_id: str | None, entity_type: str, entity_id: str, action: str, actor: str,
        detail: dict[str, Any],
    ) -> int:
        self.audit.append({"id": len(self.audit) + 1, "run_id": run_id, "entity_type": entity_type,
                           "entity_id": entity_id, "action": action, "actor": actor, "detail": detail})
        return len(self.audit)

    async def add_rule(
        self, *, kind: str, pattern: dict[str, Any], action: dict[str, Any], source_item: str | None,
        created_by: str, dataset: str, origin: RuleOrigin = "learned",
    ) -> int:
        rule_id = max((r.id for r in self._rules), default=0) + 1
        self._rule_scope[rule_id] = (dataset, origin)
        self._rules.append(Rule(id=rule_id, kind=kind, pattern=pattern, action=action, source_item=source_item,
                                created_by=created_by, active=True, created_at=_now()))
        return rule_id

    async def list_rules(self) -> list[Rule]:
        return [r.model_copy(deep=True) for r in self._rules]

    async def reset(self, dataset: str, *, actor: str) -> tuple[int, int]:
        run_ids = {r.id for r in self._runs.values() if r.dataset == dataset}
        item_ids = {i.id for rid in run_ids for i in self._items.get(rid, [])}
        for rid in run_ids:
            del self._runs[rid]
            self._items.pop(rid, None)
        self._decisions = {k: d for k, d in self._decisions.items() if d.item_id not in item_ids}
        for a in self.audit:  # on delete set null
            if a["run_id"] in run_ids:
                a["run_id"] = None
        kept = [r for r in self._rules if self._rule_scope[r.id] != (dataset, "learned")]
        removed = len(self._rules) - len(kept)
        self._rules = kept
        for r in self._rules:  # on delete set null
            if r.source_item in item_ids:
                r.source_item = None
        await self.add_audit(run_id=None, entity_type="dataset", entity_id=dataset, action="demo_reset",
                             actor=actor, detail={"runs_deleted": len(run_ids), "rules_deleted": removed})
        return len(run_ids), removed


RUN_COLS = "id::text, dataset, period_start, period_end, status, counts, report, error, created_at, updated_at"
STEP_COLS = (
    "step_key as id, position, agent, label, model_tier as tier, model, status, started_at, finished_at, "
    "latency_ms, tokens_in, tokens_out, output_summary, error"
)
# The effective entry: the latest draft, with the latest decision's entry_override on top. DbStore.run_items
# (the statement) reads the same expression, so /runs/{id}/items and /statement always agree.
EFFECTIVE_ENTRY_JOINS = (
    "left join lateral (select * from proposed_entries p where p.item_id = i.id "
    "order by p.created_at desc limit 1) pe on true "
    "left join lateral (select entry_override as o from decisions x where x.item_id = i.id "
    "order by x.created_at desc limit 1) d on true "
)
EFFECTIVE_ENTRY_COLS = (
    "coalesce(d.o->>'debit_account', pe.debit_account) as debit_account, "
    "coalesce(d.o->>'credit_account', pe.credit_account) as credit_account, "
    "coalesce((d.o->>'amount')::numeric(14,2), pe.amount) as amount, "
    "coalesce(d.o->>'memo', pe.memo) as memo"
)
ITEMS_SQL = (
    "select i.id::text, i.run_id::text, i.kind, i.resolution, i.status, i.bank_ids, i.gl_ids, i.amount_delta, "
    "i.reasoning, i.evidence, i.flags, i.model, i.confidence::float, i.rule_id, i.created_at, "
    f"pe.id::text as entry_id, {EFFECTIVE_ENTRY_COLS}, pe.status as entry_status "
    f"from items i {EFFECTIVE_ENTRY_JOINS}"
)
RULE_COLS = "id, kind, pattern, action, source_item::text, created_by, active, created_at"


def _item_from_row(r: dict) -> Item:
    entry = None
    if r["entry_id"] is not None:
        entry = ProposedEntry(id=r["entry_id"], debit_account=r["debit_account"], credit_account=r["credit_account"],
                              amount=r["amount"], memo=r["memo"], status=r["entry_status"])
    fields = {k: v for k, v in r.items() if k in Item.model_fields}
    return Item(**fields, proposed_entry=entry)


class DbRunStore:
    """Supabase Postgres through the transaction pooler: one short connection per call."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    async def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return await psycopg.AsyncConnection.connect(self._url, prepare_threshold=None, row_factory=dict_row)

    async def create_run(self, dataset: str, period_start: date, period_end: date) -> Run:
        async with await self._connect() as conn:
            row = await (await conn.execute(
                f"insert into runs (dataset, period_start, period_end) values (%s, %s, %s) returning {RUN_COLS}",
                (dataset, period_start, period_end),
            )).fetchone()
            return Run(**row, steps=[])

    async def get_run(self, run_id: str) -> Run | None:
        async with await self._connect() as conn:
            row = await (await conn.execute(f"select {RUN_COLS} from runs where id::text = %s", (run_id,))).fetchone()
            if row is None:
                return None
            steps = await (await conn.execute(
                f"select {STEP_COLS} from run_steps where run_id::text = %s order by position, step_key", (run_id,)
            )).fetchall()
            return Run(**row, steps=[RunStep(**s) for s in steps])

    async def latest_run_id(self, dataset: str) -> str | None:
        async with await self._connect() as conn:
            row = await (await conn.execute(
                "select id::text from runs where dataset = %s and status = any(%s) order by created_at desc limit 1",
                (dataset, list(LIVE_RUN_STATUSES)),
            )).fetchone()
            return row["id"] if row else None

    async def update_run(
        self, run_id: str, *, status: RunStatus, counts: RunCounts | None = None, error: ApiError | None = None
    ) -> None:
        from psycopg.types.json import Jsonb

        async with await self._connect() as conn:
            await conn.execute(
                "update runs set status = %s, counts = coalesce(%s, counts), error = %s, updated_at = now() "
                "where id::text = %s",
                (status, Jsonb(counts.model_dump()) if counts else None,
                 Jsonb(error.model_dump()) if error else None, run_id),
            )

    async def save_steps(self, run_id: str, steps: Sequence[RunStep]) -> None:
        from psycopg.types.json import Jsonb

        rows = [
            (run_id, s.id, s.position, s.agent, s.label, s.tier, s.model, s.status, s.started_at, s.finished_at,
             s.latency_ms, s.tokens_in, s.tokens_out, s.output_summary, Jsonb(s.error.model_dump()) if s.error else None)
            for s in steps
        ]
        async with await self._connect() as conn, conn.cursor() as cur:
            await cur.executemany(
                "insert into run_steps (run_id, step_key, position, agent, label, model_tier, model, status, "
                "started_at, finished_at, latency_ms, tokens_in, tokens_out, output_summary, error) "
                "values (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (run_id, step_key) do update set position = excluded.position, agent = excluded.agent, "
                "label = excluded.label, model_tier = excluded.model_tier, model = excluded.model, "
                "status = excluded.status, started_at = excluded.started_at, finished_at = excluded.finished_at, "
                "latency_ms = excluded.latency_ms, tokens_in = excluded.tokens_in, tokens_out = excluded.tokens_out, "
                "output_summary = excluded.output_summary, error = excluded.error",
                rows,
            )
            await conn.execute("update runs set updated_at = now() where id::text = %s", (run_id,))

    async def replace_items(self, run_id: str, items: Sequence[Item]) -> None:
        from psycopg.types.json import Jsonb

        item_rows = [
            (i.id, run_id, i.kind, i.resolution, i.status, i.bank_ids, i.gl_ids, i.amount_delta, i.reasoning,
             Jsonb([e.model_dump() for e in i.evidence]), i.flags, i.model, i.confidence, i.rule_id, i.created_at)
            for i in items
        ]
        entry_rows = [
            (e.id, i.id, e.debit_account, e.credit_account, e.amount, e.memo, e.status)
            for i in items if (e := i.proposed_entry) is not None
        ]
        async with await self._connect() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute("delete from items where run_id::text = %s", (run_id,))  # entries cascade
            await cur.executemany(
                "insert into items (id, run_id, kind, resolution, status, bank_ids, gl_ids, amount_delta, "
                "reasoning, evidence, flags, model, confidence, rule_id, created_at) "
                "values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                item_rows,
            )
            await cur.executemany(
                "insert into proposed_entries (id, item_id, debit_account, credit_account, amount, memo, status) "
                "values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)",
                entry_rows,
            )

    async def list_items(self, run_id: str, status: str | None = None) -> list[Item]:
        async with await self._connect() as conn:
            rows = await (await conn.execute(
                ITEMS_SQL + "where i.run_id::text = %s and (%s::text is null or i.status = %s) "
                "order by i.created_at, i.id",
                (run_id, status, status),
            )).fetchall()
            return [_item_from_row(r) for r in rows]

    async def _item(self, conn, item_id: str) -> Item | None:
        row = await (await conn.execute(ITEMS_SQL + "where i.id::text = %s", (item_id,))).fetchone()
        return _item_from_row(row) if row else None

    async def get_item(self, item_id: str) -> Item | None:
        async with await self._connect() as conn:
            return await self._item(conn, item_id)

    async def decide_item(
        self, item_id: str, *, decision: Verdict, actor: str, note: str | None, remember: bool,
        override: EntryOverride | None,
    ) -> tuple[Item, str]:
        from psycopg.types.json import Jsonb

        status = "approved" if decision == "approve" else "rejected"
        async with await self._connect() as conn:
            async with conn.transaction():
                # The status guard in the update makes two concurrent decisions safe: one wins.
                moved = await (await conn.execute(
                    "update items set status = %s where id::text = %s and status = 'needs_approval' returning id",
                    (status, item_id),
                )).fetchone()
                if moved is None:
                    current = await (await conn.execute(
                        "select status from items where id::text = %s", (item_id,))).fetchone()
                    if current is None:
                        raise item_not_found(item_id)
                    raise item_not_pending(item_id, current["status"])
                row = await (await conn.execute(
                    "insert into decisions (item_id, decision, actor, note, remember, entry_override) "
                    "values (%s, %s, %s, %s, %s, %s) returning id::text",
                    (moved["id"], decision, actor, note, remember,
                     Jsonb(override.model_dump(mode="json")) if override else None),
                )).fetchone()
                if override is None:
                    await conn.execute("update proposed_entries set status = %s where item_id = %s",
                                       (status, moved["id"]))
                else:
                    o = override
                    updated = await conn.execute(
                        "update proposed_entries set debit_account = %s, credit_account = %s, amount = %s, "
                        "memo = %s, status = %s where item_id = %s",
                        (o.debit_account, o.credit_account, o.amount, o.memo, status, moved["id"]),
                    )
                    if updated.rowcount == 0:
                        await conn.execute(
                            "insert into proposed_entries (item_id, debit_account, credit_account, amount, memo, "
                            "status) values (%s, %s, %s, %s, %s, %s)",
                            (moved["id"], o.debit_account, o.credit_account, o.amount, o.memo, status),
                        )
            return await self._item(conn, item_id), row["id"]

    async def get_decision(self, decision_id: str) -> Decision | None:
        async with await self._connect() as conn:
            row = await (await conn.execute(
                "select id::text, item_id::text, decision, actor, note, remember, entry_override "
                "from decisions where id::text = %s", (decision_id,),
            )).fetchone()
            return Decision(**row) if row else None

    async def add_audit(
        self, *, run_id: str | None, entity_type: str, entity_id: str, action: str, actor: str,
        detail: dict[str, Any],
    ) -> int:
        from psycopg.types.json import Jsonb

        async with await self._connect() as conn:
            row = await (await conn.execute(
                "insert into audit_log (run_id, entity_type, entity_id, action, actor, detail) "
                "values (%s::uuid, %s, %s, %s, %s, %s) returning id",
                (run_id, entity_type, entity_id, action, actor, Jsonb(detail)),
            )).fetchone()
            return row["id"]

    async def add_rule(
        self, *, kind: str, pattern: dict[str, Any], action: dict[str, Any], source_item: str | None,
        created_by: str, dataset: str, origin: RuleOrigin = "learned",
    ) -> int:
        from psycopg.types.json import Jsonb

        async with await self._connect() as conn:
            row = await (await conn.execute(
                "insert into rules (kind, pattern, action, source_item, created_by, dataset, origin) "
                "values (%s, %s, %s, %s::uuid, %s, %s, %s) returning id",
                (kind, Jsonb(pattern), Jsonb(action), source_item, created_by, dataset, origin),
            )).fetchone()
            return row["id"]

    async def list_rules(self) -> list[Rule]:
        async with await self._connect() as conn:
            rows = await (await conn.execute(f"select {RULE_COLS} from rules order by id")).fetchall()
            return [Rule(**r) for r in rows]

    async def reset(self, dataset: str, *, actor: str) -> tuple[int, int]:
        from psycopg.types.json import Jsonb

        async with await self._connect() as conn, conn.transaction():
            rules = await conn.execute(
                "delete from rules where dataset = %s and origin = 'learned'", (dataset,))
            # Cascades to run_steps, items, proposed_entries and decisions; audit_log rows keep, run_id null.
            runs = await conn.execute("delete from runs where dataset = %s", (dataset,))
            await conn.execute(
                "insert into audit_log (run_id, entity_type, entity_id, action, actor, detail) "
                "values (null, 'dataset', %s, 'demo_reset', %s, %s)",
                (dataset, actor, Jsonb({"runs_deleted": runs.rowcount, "rules_deleted": rules.rowcount})))
            return runs.rowcount, rules.rowcount


MEMORY_RUNS = MemoryRunStore()


def get_run_store(settings: Settings) -> RunStore:
    return DbRunStore(settings.database_url) if settings.database_url else MEMORY_RUNS
