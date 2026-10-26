"""Read API v1: datasets, bank and GL rows labelled by the latest run, and the statement."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.auth import get_user_or_demo
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.recon.models import Dataset
from app.recon.statement import build_statement
from app.recon.store import CsvStore, DbStore, ReadStore, RunItems
from app.schemas.reads import BankTransactionOut, DatasetOut, GlEntryOut, Statement

router = APIRouter(tags=["reads"], dependencies=[Depends(get_user_or_demo)])


def get_read_store(settings: Settings = Depends(get_settings)) -> ReadStore:
    if settings.database_url:
        return DbStore(settings.database_url)
    return CsvStore(settings.dataset)


async def _dataset(store: ReadStore, dataset_id: str) -> Dataset:
    dataset = await store.dataset(dataset_id)
    if dataset is None:
        raise AppError(code="dataset_not_found", message=f"Dataset {dataset_id} does not exist", status_code=404)
    return dataset


def _check_range(start: date | None, end: date | None) -> None:
    if start and end and start > end:
        raise AppError(code="invalid_date_range", message="'from' must not be after 'to'", status_code=422)


def _in_range(day: date, start: date | None, end: date | None) -> bool:
    return (start is None or day >= start) and (end is None or day <= end)


def _status_by_id(run: RunItems, side: str) -> dict[str, tuple[str, str]]:
    return {row_id: (item.status, item.id) for item in run.items for row_id in getattr(item, side)}


def _label(status: dict[str, tuple[str, str]], row_id: str) -> dict[str, str | None]:
    recon_status, item_id = status.get(row_id, ("unmatched", None))
    return {"recon_status": recon_status, "item_id": item_id}


DatasetParam = Query(default=None, description="Defaults to the configured demo dataset")
FromParam = Query(default=None, alias="from", description="Inclusive start date")
ToParam = Query(default=None, alias="to", description="Inclusive end date")


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(store: ReadStore = Depends(get_read_store)) -> list[DatasetOut]:
    return [
        DatasetOut(
            id=d.id, label=d.balances.company, period_start=d.balances.period_start, period_end=d.balances.period_end
        )
        for d in await store.datasets()
    ]


@router.get("/bank-transactions", response_model=list[BankTransactionOut])
async def list_bank_transactions(
    dataset: str | None = DatasetParam,
    start: date | None = FromParam,
    end: date | None = ToParam,
    store: ReadStore = Depends(get_read_store),
    settings: Settings = Depends(get_settings),
) -> list[BankTransactionOut]:
    _check_range(start, end)
    data = await _dataset(store, dataset or settings.dataset)
    status = _status_by_id(await store.run_items(data.id, None), "bank_ids")
    return [
        BankTransactionOut(**t.model_dump(), **_label(status, t.txn_id))
        for t in data.bank
        if _in_range(t.posted_date, start, end)
    ]


@router.get("/gl-entries", response_model=list[GlEntryOut])
async def list_gl_entries(
    dataset: str | None = DatasetParam,
    start: date | None = FromParam,
    end: date | None = ToParam,
    store: ReadStore = Depends(get_read_store),
    settings: Settings = Depends(get_settings),
) -> list[GlEntryOut]:
    _check_range(start, end)
    data = await _dataset(store, dataset or settings.dataset)
    status = _status_by_id(await store.run_items(data.id, None), "gl_ids")
    return [
        GlEntryOut(**g.model_dump(), **_label(status, g.entry_id))
        for g in data.gl
        if _in_range(g.date, start, end)
    ]


@router.get("/statement", response_model=Statement)
async def get_statement(
    dataset: str | None = DatasetParam,
    run_id: str | None = Query(default=None, description="Defaults to the dataset's latest run"),
    store: ReadStore = Depends(get_read_store),
    settings: Settings = Depends(get_settings),
) -> Statement:
    data = await _dataset(store, dataset or settings.dataset)
    run = await store.run_items(data.id, run_id or None)  # `?run_id=` means the latest run
    return build_statement(data, run.run_id)
