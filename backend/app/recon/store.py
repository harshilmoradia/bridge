"""Where the read API gets its data: Postgres when DATABASE_URL is set, otherwise demo-data/ CSVs.

Both stores return the same domain models, so routes never know which one they talk to.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict

from app.core.errors import AppError
from app.recon.loader import DATA_DIR, load_dataset
from app.recon.models import Balances, BankTxn, Dataset, GlEntry, ProposedEntry
from app.schemas.reads import Statement, StatementLine, StatementSide
from app.schemas.runs import CreateRunRequest, DecisionRequest, DecisionResponse, Item, Run, RunCounts


class ItemRef(BaseModel):
    """The part of a run's item that the read API needs: row labels and the statement's inputs."""

    model_config = ConfigDict(frozen=True)

    id: str
    status: str
    bank_ids: tuple[str, ...]
    gl_ids: tuple[str, ...]
    kind: str = "unknown"
    entry: ProposedEntry | None = None  # the item's journal entry, when it needs one


class RunItems(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str | None
    items: tuple[ItemRef, ...]


NO_RUN = RunItems(run_id=None, items=())


def run_not_found(run_id: str) -> AppError:
    return AppError(code="run_not_found", message=f"Run {run_id} does not exist", status_code=404)


class ReadStore(Protocol):
    async def datasets(self) -> list[Dataset]: ...

    async def dataset(self, dataset_id: str) -> Dataset | None: ...

    async def run_items(self, dataset_id: str, run_id: str | None) -> RunItems:
        """Items of `run_id`, or of the dataset's latest run when it is None."""
        ...


class RunStore(Protocol):
    async def create_run(self, request: CreateRunRequest) -> Run: ...

    async def get_run(self, run_id: str) -> Run | None: ...

    async def list_items(self, run_id: str, status: str | None = None) -> list[Item]: ...

    async def decide_item(self, item_id: str, request: DecisionRequest) -> DecisionResponse: ...


def _empty_statement(run: Run) -> Statement:
    zero = Decimal("0.00")
    return Statement(
        dataset=run.dataset,
        run_id=run.id,
        company="Northbrook Goods Co.",
        cash_account="1010",
        period_start=run.period_start,
        period_end=run.period_end,
        raw_difference=zero,
        bank=StatementSide(closing_balance=zero, lines=[], adjusted_balance=zero),
        book=StatementSide(closing_balance=zero, lines=[], adjusted_balance=zero),
        unreconciled_difference=zero,
    )


def _item_from_db_row(row: dict[str, object]) -> Item:
    proposed_entry = None
    if row.get("entry_id") is not None:
        proposed_entry = {
            "id": row["entry_id"],
            "debit_account": row["debit_account"],
            "credit_account": row["credit_account"],
            "amount": row["entry_amount"],
            "memo": row["entry_memo"],
            "status": row["entry_status"],
        }
    fields = {
        key: value
        for key, value in row.items()
        if key not in {"entry_id", "debit_account", "credit_account", "entry_amount", "entry_memo", "entry_status"}
    }
    return Item.model_validate({
        **fields,
        "evidence": row.get("evidence") or [],
        "flags": row.get("flags") or [],
        "proposed_entry": proposed_entry,
    })


def _decision_response(item: Item, run: Run) -> DecisionResponse:
    statement = _empty_statement(run)
    if item.proposed_entry is not None and item.status == "approved":
        statement.book.lines.append(
            StatementLine(
                item_id=item.id,
                kind=item.kind,
                label=item.proposed_entry.memo,
                amount=item.amount_delta,
                status=item.status,
                applied=True,
                bank_ids=item.bank_ids,
                gl_ids=item.gl_ids,
            )
        )
        statement.book.adjusted_balance += Decimal(str(item.amount_delta))
        statement.unreconciled_difference -= Decimal(str(item.amount_delta))
    return DecisionResponse(item=item, statement=statement)


def _persisted_item_id(run_id: str, item_id: object) -> str:
    return str(uuid5(NAMESPACE_URL, f"bridge:{run_id}:{item_id}"))


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._items: dict[str, Item] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def create_run(self, request: CreateRunRequest) -> Run:
        run = Run(
            id=str(uuid4()),
            dataset=request.dataset,
            period_start=request.period_start,
            period_end=request.period_end,
            status="queued",
            created_at=self._now(),
            updated_at=self._now(),
            steps=[],
            counts=RunCounts(),
            report=None,
            error=None,
        )
        self._runs[run.id] = run
        return run

    async def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def list_items(self, run_id: str, status: str | None = None) -> list[Item]:
        items = [item for item in self._items.values() if item.run_id == run_id]
        if status is not None:
            items = [item for item in items if item.status == status]
        return sorted(items, key=lambda item: item.created_at)

    async def decide_item(self, item_id: str, request: DecisionRequest) -> DecisionResponse:
        item = self._items.get(item_id)
        if item is None:
            raise AppError(code="item_not_found", message=f"Item {item_id} does not exist", status_code=404)
        run = self._runs.get(item.run_id)
        if run is None:
            raise AppError(code="run_not_found", message=f"Run {item.run_id} does not exist", status_code=404)

        item.status = "approved" if request.decision == "approve" else "rejected"
        if item.proposed_entry is not None:
            item.proposed_entry.status = item.status

        if request.entry_override is not None and item.proposed_entry is not None:
            item.proposed_entry.debit_account = request.entry_override.debit_account
            item.proposed_entry.credit_account = request.entry_override.credit_account
            item.proposed_entry.amount = request.entry_override.amount
            item.proposed_entry.memo = request.entry_override.memo

        statement = _empty_statement(run)
        if item.proposed_entry is not None and item.status == "approved":
            statement.book.lines.append(
                StatementLine(
                    item_id=item.id,
                    kind=item.kind,
                    label=item.proposed_entry.memo,
                    amount=item.amount_delta,
                    status=item.status,
                    applied=True,
                    bank_ids=item.bank_ids,
                    gl_ids=item.gl_ids,
                )
            )
            statement.book.adjusted_balance = statement.book.adjusted_balance + Decimal(str(item.amount_delta))
            statement.unreconciled_difference = statement.unreconciled_difference - Decimal(str(item.amount_delta))

        return DecisionResponse(item=item, statement=statement)


class CsvStore:
    """One dataset read from demo-data/. It has no runs, so every row is unmatched."""

    def __init__(self, dataset_id: str, data_dir: Path = DATA_DIR) -> None:
        self._dataset_id = dataset_id
        self._data_dir = data_dir

    async def datasets(self) -> list[Dataset]:
        return [load_dataset(self._dataset_id, self._data_dir)]

    async def dataset(self, dataset_id: str) -> Dataset | None:
        return load_dataset(dataset_id, self._data_dir) if dataset_id == self._dataset_id else None

    async def run_items(self, dataset_id: str, run_id: str | None) -> RunItems:
        if run_id is not None:
            raise run_not_found(run_id)
        return NO_RUN


BALANCE_COLS = (
    "company, cash_account, period_start, period_end, "
    "bank_opening_balance, bank_closing_balance, gl_opening_balance, gl_closing_balance"
)
BANK_COLS = "txn_id, posted_date, description, amount, type, check_number, running_balance"
GL_COLS = "entry_id, date, description, amount, method, check_number, account, counter_account, counterparty"
# Runs that are still going count too, so rows change status live during a run.
LATEST_RUN_SQL = (
    "select id::text from runs where dataset = %s and status in ('running', 'completed') "
    "order by created_at desc limit 1"
)


class DbStore:
    """Supabase Postgres through the transaction pooler: one short connection per call."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    async def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        # prepare_threshold=None: the transaction pooler has no prepared statements.
        return await psycopg.AsyncConnection.connect(self._url, prepare_threshold=None, row_factory=dict_row)

    async def create_run(self, request: CreateRunRequest) -> Run:
        async with await self._connect() as conn:
            row = await (await conn.execute(
                """
                insert into runs (dataset, period_start, period_end, status, counts, report, error, created_at, updated_at)
                values (%s, %s, %s, 'queued', '{}'::jsonb, null, null, now(), now())
                returning id::text, dataset, period_start, period_end, status, counts, report, error, created_at, updated_at
                """,
                (request.dataset, request.period_start, request.period_end),
            )).fetchone()
            if row is None:
                raise AppError(code="run_create_failed", message="Unable to create the run", status_code=500)
            return Run.model_validate({**row, "steps": []})

    async def start_run(self, run_id: str) -> None:
        async with await self._connect() as conn:
            await conn.execute(
                "update runs set status = 'running', updated_at = now() where id::text = %s",
                (run_id,),
            )
            await conn.execute(
                """
                insert into run_steps (run_id, step_key, position, agent, label, model_tier, status, started_at)
                values (%s, 'load-and-match', 1, 'reconciliation', 'Load and match transactions', 'code', 'running', now())
                on conflict (run_id, step_key) do update set
                    status = 'running', started_at = now(), finished_at = null, error = null
                """,
                (run_id,),
            )

    async def complete_run(self, run_id: str, result: dict[str, object]) -> list[str]:
        counts = result.get("counts", {})
        items = result.get("items", [])
        if not isinstance(counts, dict) or not isinstance(items, list):
            raise ValueError("Invalid reconciliation result")

        status_counts = {
            "items": len(items),
            "matched": int(counts.get("matches", 0)) + sum(item.get("status") == "matched" for item in items),
            "auto_resolved": int(counts.get("auto_resolved", 0)),
            "reconciling_item": sum(item.get("status") == "reconciling_item" for item in items),
            "needs_approval": sum(item.get("status") == "needs_approval" for item in items),
            "unmatched": int(counts.get("unmatched_bank", 0)) + int(counts.get("unmatched_gl", 0)),
            "bank_transactions": int(counts.get("bank_transactions", 0)),
            "gl_entries": int(counts.get("gl_entries", 0)),
        }

        persisted_ids: list[str] = []
        async with await self._connect() as conn:
            for item in items:
                item_id = _persisted_item_id(run_id, item["id"])
                persisted_ids.append(item_id)
                await conn.execute(
                    """
                    insert into items (
                        id, run_id, kind, resolution, status, bank_ids, gl_ids, amount_delta,
                        reasoning, evidence, flags, model, confidence, rule_id
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                    on conflict (id) do update set
                        kind = excluded.kind, resolution = excluded.resolution,
                        status = case when items.status in ('approved', 'rejected') then items.status else excluded.status end,
                        bank_ids = excluded.bank_ids, gl_ids = excluded.gl_ids,
                        amount_delta = excluded.amount_delta, reasoning = excluded.reasoning,
                        evidence = excluded.evidence, flags = excluded.flags,
                        model = excluded.model, confidence = excluded.confidence, rule_id = excluded.rule_id
                    """,
                    (
                        item_id,
                        run_id,
                        item["kind"],
                        item["resolution"],
                        item["status"],
                        item["bank_ids"],
                        item["gl_ids"],
                        item["amount_delta"] or "0.00",
                        item.get("reasoning"),
                        json.dumps(item.get("evidence", [])),
                        item.get("flags", []),
                        item.get("model"),
                        item.get("confidence"),
                        item.get("rule_id"),
                    ),
                )
                proposed_entry = item.get("proposed_entry")
                if isinstance(proposed_entry, dict):
                    entry_id = str(uuid5(NAMESPACE_URL, f"bridge:{item_id}:proposed-entry"))
                    await conn.execute(
                        """
                        insert into proposed_entries (id, item_id, debit_account, credit_account, amount, memo, status)
                        values (%s, %s, %s, %s, %s, %s, %s)
                        on conflict (id) do update set
                            debit_account = excluded.debit_account, credit_account = excluded.credit_account,
                            amount = excluded.amount, memo = excluded.memo,
                            status = case when proposed_entries.status in ('approved', 'rejected', 'posted')
                                          then proposed_entries.status else excluded.status end
                        """,
                        (
                            entry_id,
                            item_id,
                            proposed_entry["debit_account"],
                            proposed_entry["credit_account"],
                            proposed_entry["amount"],
                            proposed_entry["memo"],
                            proposed_entry.get("status", "draft"),
                        ),
                    )

            await conn.execute(
                "update runs set status = 'completed', counts = %s::jsonb, updated_at = now(), error = null where id::text = %s",
                (json.dumps(status_counts), run_id),
            )
            await conn.execute(
                """
                update run_steps set status = 'completed', finished_at = now(),
                    output_summary = %s, error = null
                where run_id::text = %s and step_key = 'load-and-match'
                """,
                (json.dumps({"items": len(items), "counts": status_counts}), run_id),
            )

        return persisted_ids

    async def fail_run(self, run_id: str, message: str) -> None:
        error = {"code": "reconciliation_failed", "message": message[:500]}
        async with await self._connect() as conn:
            await conn.execute(
                "update runs set status = 'failed', error = %s::jsonb, updated_at = now() where id::text = %s",
                (json.dumps(error), run_id),
            )
            await conn.execute(
                """
                update run_steps set status = 'failed', finished_at = now(), error = %s::jsonb
                where run_id::text = %s and step_key = 'load-and-match'
                """,
                (json.dumps(error), run_id),
            )

    async def get_run(self, run_id: str) -> Run | None:
        async with await self._connect() as conn:
            row = await (await conn.execute(
                """
                select id::text, dataset, period_start, period_end, status, counts, report, error, created_at, updated_at
                from runs where id::text = %s
                """,
                (run_id,),
            )).fetchone()
            if row is None:
                return None
            steps = await (await conn.execute(
                """
                select step_key, position, agent, label, model_tier, model, status, started_at,
                       finished_at, latency_ms, tokens_in, tokens_out, output_summary, error
                from run_steps where run_id::text = %s order by position, step_key
                """,
                (run_id,),
            )).fetchall()
            normalized_steps = [
                {
                    "id": step["step_key"],
                    "position": step["position"],
                    "agent": step["agent"],
                    "label": step["label"],
                    "tier": step["model_tier"] or "code",
                    "model": step["model"],
                    "status": step["status"],
                    "started_at": step["started_at"],
                    "finished_at": step["finished_at"],
                    "latency_ms": step["latency_ms"],
                    "tokens_in": step["tokens_in"],
                    "tokens_out": step["tokens_out"],
                    "output_summary": step["output_summary"],
                    "error": step["error"],
                }
                for step in steps
            ]
            return Run.model_validate({**row, "steps": normalized_steps})

    async def list_items(self, run_id: str, status: str | None = None) -> list[Item]:
        async with await self._connect() as conn:
            query = """
                select i.id::text, i.run_id::text, i.kind, i.resolution, i.status, i.bank_ids, i.gl_ids,
                       i.amount_delta, i.reasoning, i.evidence, i.flags, i.model, i.confidence, i.rule_id,
                       i.created_at, pe.id::text as entry_id, pe.debit_account, pe.credit_account,
                       pe.amount as entry_amount, pe.memo as entry_memo, pe.status as entry_status
                from items i left join proposed_entries pe on pe.item_id = i.id
                where i.run_id::text = %s
            """
            if status is None:
                rows = await (await conn.execute(query + " order by i.created_at", (run_id,))).fetchall()
            else:
                rows = await (await conn.execute(
                    query + " and i.status = %s order by i.created_at", (run_id, status)
                )).fetchall()
            return [_item_from_db_row(row) for row in rows]

    async def decide_item(self, item_id: str, request: DecisionRequest) -> DecisionResponse:
        item_status = "approved" if request.decision == "approve" else "rejected"
        async with await self._connect() as conn:
            row = await (await conn.execute(
                """
                select i.id::text, i.run_id::text, i.kind, i.resolution, i.status, i.bank_ids, i.gl_ids,
                       i.amount_delta, i.reasoning, i.evidence, i.flags, i.model, i.confidence, i.rule_id,
                       i.created_at, pe.id::text as entry_id, pe.debit_account, pe.credit_account,
                       pe.amount as entry_amount, pe.memo as entry_memo, pe.status as entry_status
                from items i left join proposed_entries pe on pe.item_id = i.id
                where i.id::text = %s for update of i
                """,
                (item_id,),
            )).fetchone()
            if row is None:
                raise AppError(code="item_not_found", message=f"Item {item_id} does not exist", status_code=404)
            item = _item_from_db_row(row)
            override = request.entry_override
            await conn.execute("update items set status = %s where id::text = %s", (item_status, item_id))
            if item.proposed_entry is not None:
                if override is None:
                    await conn.execute(
                        "update proposed_entries set status = %s where item_id::text = %s",
                        (item_status, item_id),
                    )
                else:
                    await conn.execute(
                        """
                        update proposed_entries set status = %s, debit_account = %s, credit_account = %s,
                            amount = %s, memo = %s where item_id::text = %s
                        """,
                        (
                            item_status,
                            override.debit_account,
                            override.credit_account,
                            override.amount,
                            override.memo,
                            item_id,
                        ),
                    )

            override_json = override.model_dump(mode="json") if override is not None else None
            await conn.execute(
                """
                insert into decisions (item_id, decision, actor, note, remember, entry_override)
                values (%s, %s, 'user:api', %s, %s, %s::jsonb)
                """,
                (item_id, request.decision, request.note, request.remember, json.dumps(override_json)),
            )
            await conn.execute(
                """
                insert into audit_log (run_id, entity_type, entity_id, action, actor, detail)
                values (%s, 'item', %s, %s, 'user:api', %s::jsonb)
                """,
                (
                    item.run_id,
                    item_id,
                    request.decision,
                    json.dumps({"note": request.note, "remember": request.remember}),
                ),
            )
            await conn.execute(
                """
                update runs set counts = jsonb_set(
                    jsonb_set(counts, '{approved}', to_jsonb((select count(*) from items where run_id::text = %s and status = 'approved')), true),
                    '{rejected}', to_jsonb((select count(*) from items where run_id::text = %s and status = 'rejected')), true
                ), updated_at = now() where id::text = %s
                """,
                (item.run_id, item.run_id, item.run_id),
            )
            updated_row = await (await conn.execute(
                """
                select i.id::text, i.run_id::text, i.kind, i.resolution, i.status, i.bank_ids, i.gl_ids,
                       i.amount_delta, i.reasoning, i.evidence, i.flags, i.model, i.confidence, i.rule_id,
                       i.created_at, pe.id::text as entry_id, pe.debit_account, pe.credit_account,
                       pe.amount as entry_amount, pe.memo as entry_memo, pe.status as entry_status
                from items i left join proposed_entries pe on pe.item_id = i.id where i.id::text = %s
                """,
                (item_id,),
            )).fetchone()
            run_row = await (await conn.execute(
                """
                select id::text, dataset, period_start, period_end, status, counts, report, error, created_at, updated_at
                from runs where id::text = %s
                """,
                (item.run_id,),
            )).fetchone()
            if run_row is None:
                raise run_not_found(item.run_id)

        updated_item = _item_from_db_row(updated_row)
        run = Run.model_validate({**run_row, "steps": []})
        return _decision_response(updated_item, run)

    async def list_items_by_id(self, item_id: str) -> list[Item]:
        async with await self._connect() as conn:
            rows = await (await conn.execute(
                """
                select i.id::text, i.run_id::text, i.kind, i.resolution, i.status, i.bank_ids, i.gl_ids,
                       i.amount_delta, i.reasoning, i.evidence, i.flags, i.model, i.confidence, i.rule_id,
                       i.created_at, pe.id::text as entry_id, pe.debit_account, pe.credit_account,
                       pe.amount as entry_amount, pe.memo as entry_memo, pe.status as entry_status
                from items i left join proposed_entries pe on pe.item_id = i.id where i.id::text = %s
                """,
                (item_id,),
            )).fetchall()
            if not rows:
                raise AppError(code="item_not_found", message=f"Item {item_id} does not exist", status_code=404)
            return [_item_from_db_row(row) for row in rows]

    async def datasets(self) -> list[Dataset]:
        async with await self._connect() as conn:
            rows = await (await conn.execute("select dataset from balances order by dataset")).fetchall()
            return [await self._load(conn, r["dataset"]) for r in rows]

    async def dataset(self, dataset_id: str) -> Dataset | None:
        async with await self._connect() as conn:
            return await self._load(conn, dataset_id)

    async def _load(self, conn, dataset_id: str) -> Dataset | None:
        cur = await conn.execute(f"select {BALANCE_COLS} from balances where dataset = %s", (dataset_id,))
        balances = await cur.fetchone()
        if balances is None:
            return None
        bank = await (await conn.execute(
            f"select {BANK_COLS} from bank_transactions where dataset = %s order by posted_date, txn_id",
            (dataset_id,),
        )).fetchall()
        gl = await (await conn.execute(
            f"select {GL_COLS} from gl_entries where dataset = %s order by date, entry_id", (dataset_id,)
        )).fetchall()
        return Dataset(
            id=dataset_id,
            balances=Balances(**balances),
            bank=tuple(BankTxn(**r) for r in bank),
            gl=tuple(GlEntry(**r) for r in gl),
        )

    async def run_items(self, dataset_id: str, run_id: str | None) -> RunItems:
        async with await self._connect() as conn:
            if run_id is None:
                row = await (await conn.execute(LATEST_RUN_SQL, (dataset_id,))).fetchone()
                if row is None:
                    return NO_RUN
                run_id = row["id"]
            else:
                row = await (await conn.execute(
                    "select id::text from runs where id::text = %s and dataset = %s", (run_id, dataset_id)
                )).fetchone()
                if row is None:
                    raise run_not_found(run_id)
            items = await (await conn.execute(
                "select id::text, status, bank_ids, gl_ids from items where run_id::text = %s order by created_at",
                (run_id,),
            )).fetchall()
            return RunItems(run_id=run_id, items=tuple(ItemRef(**r) for r in items))
