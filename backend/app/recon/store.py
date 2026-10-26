"""Where the read API gets its data: Postgres when DATABASE_URL is set, otherwise demo-data/ CSVs.

Both stores return the same domain models, so routes never know which one they talk to.
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.core.errors import AppError
from app.recon.loader import DATA_DIR, load_dataset
from app.recon.models import Balances, BankTxn, Dataset, GlEntry, ProposedEntry


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
