"""Where the read API gets its data: Postgres when DATABASE_URL is set, otherwise demo-data/ CSVs.

Both stores return the same domain models, so routes never know which one they talk to.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import uuid4

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
