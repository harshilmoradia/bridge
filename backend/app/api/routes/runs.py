"""Run API v1: start a reconciliation run, poll it, list its items, decide escalated items."""

import logging

import inngest
from fastapi import APIRouter, Depends, Query

from app.api.auth import AuthContext, get_user_or_demo
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.recon.decisions import override_problems
from app.recon.run_store import RunStore, get_run_store
from app.recon.statement import build_statement
from app.recon.store import read_store, run_not_found
from app.schemas.common import ApiError, ItemStatus
from app.schemas.runs import CreateRunRequest, CreateRunResponse, DecisionRequest, DecisionResponse, Item, Run
from app.workflows.client import inngest_client
from app.workflows.item_decided import ITEM_DECIDED, ItemDecided, record_decided
from app.workflows.reconcile import RUN_REQUESTED

log = logging.getLogger(__name__)

router = APIRouter(tags=["runs"], dependencies=[Depends(get_user_or_demo)])


def run_store(settings: Settings = Depends(get_settings)) -> RunStore:
    return get_run_store(settings)


@router.post("/runs", response_model=CreateRunResponse, status_code=202)
async def create_run(
    body: CreateRunRequest,
    store: RunStore = Depends(run_store),
    settings: Settings = Depends(get_settings),
) -> CreateRunResponse:
    if body.period_start > body.period_end:
        raise AppError(code="invalid_date_range", message="period_start must not be after period_end",
                       status_code=422)
    if await read_store(settings).dataset(body.dataset) is None:
        raise AppError(code="dataset_not_found", message=f"Dataset {body.dataset} does not exist", status_code=404)

    run = await store.create_run(body.dataset, body.period_start, body.period_end)
    try:
        await inngest_client.send(inngest.Event(
            name=RUN_REQUESTED, data={"run_id": run.id, **body.model_dump(mode="json")}))
    except Exception:
        log.exception("could not send %s for run %s", RUN_REQUESTED, run.id)
        error = ApiError(code="workflow_unavailable", message="The workflow engine is unreachable")
        await store.update_run(run.id, status="failed", error=error)
        raise AppError(code=error.code, message=error.message, status_code=503) from None
    return CreateRunResponse(id=run.id, status=run.status)


async def _run(store: RunStore, run_id: str) -> Run:
    run = await store.get_run(run_id)
    if run is None:
        raise run_not_found(run_id)
    return run


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: str, store: RunStore = Depends(run_store)) -> Run:
    return await _run(store, run_id)


@router.get("/runs/{run_id}/items", response_model=list[Item])
async def list_run_items(
    run_id: str,
    status: ItemStatus | None = Query(default=None, description="Only items with this status"),
    store: RunStore = Depends(run_store),
) -> list[Item]:
    await _run(store, run_id)
    return await store.list_items(run_id, status)


@router.post("/items/{item_id}/decision", response_model=DecisionResponse)
async def decide_item(
    item_id: str,
    body: DecisionRequest,
    auth: AuthContext = Depends(get_user_or_demo),
    store: RunStore = Depends(run_store),
    settings: Settings = Depends(get_settings),
) -> DecisionResponse:
    override = body.entry_override
    if override is not None and body.decision != "approve":
        raise AppError(code="override_requires_approve", message="An entry override only goes with approve",
                       status_code=422)
    if override is not None and (problems := override_problems(override)):
        raise AppError(code="invalid_entry_override", message="; ".join(problems), status_code=422)

    item, decision_id = await store.decide_item(
        item_id, decision=body.decision, actor=f"user:{auth.user.email}", note=body.note,
        remember=body.remember, override=override)
    event = ItemDecided(item_id=item.id, decision_id=decision_id, run_id=item.run_id)
    try:
        await inngest_client.send(inngest.Event(name=ITEM_DECIDED, data=event.model_dump()))
    except Exception:
        # The decision is already saved; write its audit row (and rule) here instead of losing them.
        log.exception("could not send %s for item %s; recording inline", ITEM_DECIDED, item.id)
        await record_decided(store, event)

    run = await _run(store, item.run_id)
    reads = read_store(settings)
    dataset = await reads.dataset(run.dataset)
    if dataset is None:
        raise AppError(code="dataset_not_found", message=f"Dataset {run.dataset} does not exist", status_code=404)
    run_items = await reads.run_items(run.dataset, run.id)
    return DecisionResponse(item=item, statement=build_statement(dataset, run.id, run_items.items))
