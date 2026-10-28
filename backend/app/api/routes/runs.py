"""Run creation, lookup, item listing, and human approval endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

import inngest
from fastapi import APIRouter, Depends, Query

from app.api.auth import get_user_or_demo
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.recon.store import MemoryRunStore, RunStore
from app.schemas.runs import (
    CreateRunRequest,
    CreateRunResponse,
    DecisionRequest,
    DecisionResponse,
    Item,
    Run,
)
from app.workflows.client import inngest_client

router = APIRouter(tags=["runs"], dependencies=[Depends(get_user_or_demo)])

_rune_store = MemoryRunStore()
RUNS: dict[str, Run] = _rune_store._runs
ITEMS: dict[str, Item] = _rune_store._items


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_run_store(_settings: Settings = Depends(get_settings)) -> RunStore:
    return _rune_store


@router.post("/runs", response_model=CreateRunResponse)
async def create_run(request: CreateRunRequest, store: RunStore = Depends(get_run_store)) -> CreateRunResponse:
    run = await store.create_run(request)
    try:
        await inngest_client.send(
            inngest.Event(
                name="bridge/reconciliation.requested",
                data={
                    **request.model_dump(mode="json"),
                    "run_id": run.id,
                },
            )
        )
    except Exception:
        pass
    return CreateRunResponse(id=run.id, status=run.status)


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: str, store: RunStore = Depends(get_run_store)) -> Run:
    run = await store.get_run(run_id)
    if run is None:
        raise AppError(code="run_not_found", message=f"Run {run_id} does not exist", status_code=404)
    return run


@router.get("/runs/{run_id}/items", response_model=list[Item])
async def get_run_items(run_id: str, status: str | None = Query(default=None), store: RunStore = Depends(get_run_store)) -> list[Item]:
    run = await store.get_run(run_id)
    if run is None:
        raise AppError(code="run_not_found", message=f"Run {run_id} does not exist", status_code=404)
    return await store.list_items(run_id, status)


@router.post("/items/{item_id}/decision", response_model=DecisionResponse)
async def decide_item(item_id: str, request: DecisionRequest, store: RunStore = Depends(get_run_store)) -> DecisionResponse:
    return await store.decide_item(item_id, request)
