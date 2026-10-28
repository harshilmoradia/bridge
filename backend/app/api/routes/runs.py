"""Run creation, lookup, item listing, and human approval endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import inngest
from fastapi import APIRouter, Depends, Query

from app.api.auth import get_user_or_demo
from app.core.errors import AppError
from app.schemas.reads import Statement, StatementLine, StatementSide
from app.workflows.client import inngest_client
from app.schemas.runs import (
    CreateRunRequest,
    CreateRunResponse,
    DecisionRequest,
    DecisionResponse,
    Item,
    Run,
    RunCounts,
)

router = APIRouter(tags=["runs"], dependencies=[Depends(get_user_or_demo)])

RUNS: dict[str, Run] = {}
ITEMS: dict[str, Item] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


@router.post("/runs", response_model=CreateRunResponse)
async def create_run(request: CreateRunRequest) -> CreateRunResponse:
    run_id = str(uuid4())
    now = _now()
    run = Run(
        id=run_id,
        dataset=request.dataset,
        period_start=request.period_start,
        period_end=request.period_end,
        status="queued",
        created_at=now,
        updated_at=now,
        steps=[],
        counts=RunCounts(),
        report=None,
        error=None,
    )
    RUNS[run_id] = run
    try:
        await inngest_client.send(
            inngest.Event(
                name="bridge/reconciliation.requested",
                data={
                    **request.model_dump(mode="json"),
                    "run_id": run_id,
                },
            )
        )
    except Exception:
        pass
    return CreateRunResponse(id=run_id, status=run.status)


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: str) -> Run:
    run = RUNS.get(run_id)
    if run is None:
        raise AppError(code="run_not_found", message=f"Run {run_id} does not exist", status_code=404)
    return run


@router.get("/runs/{run_id}/items", response_model=list[Item])
async def get_run_items(run_id: str, status: str | None = Query(default=None)) -> list[Item]:
    if run_id not in RUNS:
        raise AppError(code="run_not_found", message=f"Run {run_id} does not exist", status_code=404)
    items = [item for item in ITEMS.values() if item.run_id == run_id]
    if status is not None:
        items = [item for item in items if item.status == status]
    return sorted(items, key=lambda item: item.created_at)


@router.post("/items/{item_id}/decision", response_model=DecisionResponse)
async def decide_item(item_id: str, request: DecisionRequest) -> DecisionResponse:
    item = ITEMS.get(item_id)
    if item is None:
        raise AppError(code="item_not_found", message=f"Item {item_id} does not exist", status_code=404)
    run = RUNS.get(item.run_id)
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
