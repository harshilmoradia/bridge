"""Inngest function `reconcile-run`: load, guard, then the agent pipeline, persisted as it goes.

Triggered by `bridge/run.requested {run_id, dataset, period_start, period_end}` (sent by
`POST /runs`). Coarse durable steps: `start` writes every stage as a pending `run_steps` row,
`load` loads the period and runs the guard (its flags go to `audit_log`), `agents` runs
`run_agents` and saves items, entries and the stage rows, and `finish` marks the run completed.

Inngest Cloud stores step outputs, so every step returns IDs and counts only. Rows are re-read
inside each step that needs them. A failing step marks its stages and the run `failed` and
raises `NonRetriableError`: re-running the agents costs a full set of model calls, and the
pipeline already retries model calls itself.
"""

import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import inngest
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.agents.models import AgentItem, StepLog
from app.agents.pipeline import run_agents
from app.core.config import get_settings
from app.guardrails import screen_text
from app.llm import get_llm_client
from app.recon.models import Dataset
from app.recon.run_store import RunStore, get_run_store
from app.recon.store import read_store
from app.schemas.common import ApiError
from app.schemas.runs import Item, ModelTier, ProposedEntry, RunCounts, RunStep
from app.workflows.client import inngest_client

log = logging.getLogger(__name__)

RUN_REQUESTED = "bridge/run.requested"
GUARD_ACTOR = "agent:guard"


class RunRequested(BaseModel):
    run_id: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def _ordered(self) -> "RunRequested":
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self


@dataclass(frozen=True)
class Stage:
    id: str
    position: int
    agent: str
    label: str
    tier: ModelTier


# Sequential: classify works on what fuzzy match leaves, so no two stages share a position.
STAGES = (
    Stage("load", 1, "loader", "Load bank and GL rows", "code"),
    Stage("guard", 2, "guard", "Mask PII and scan for injection", "code"),
    Stage("match-rules", 3, "matcher", "Rule-based matching", "code"),
    Stage("match-fuzzy", 4, "fuzzy_match", "Fuzzy match by description", "nano"),
    Stage("classify", 5, "classify", "Classify leftovers", "nano"),
    Stage("resolve", 6, "resolve", "Explain and draft fixes", "super"),
    Stage("review", 7, "review", "Code checks and critic", "super"),
    Stage("decide", 8, "decide", "Apply policy", "code"),
)
STAGE = {s.id: s for s in STAGES}
LOAD_STAGES = ("load", "guard")
AGENT_STAGES = ("match-rules", "match-fuzzy", "classify", "resolve", "review", "decide")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _step(stage_id: str, status: str, **fields: Any) -> RunStep:
    s = STAGE[stage_id]
    return RunStep(id=s.id, position=s.position, agent=s.agent, label=s.label, tier=s.tier, status=status, **fields)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def load_period(req: RunRequested) -> Dataset:
    """The dataset's rows inside the requested period. Balances stay the dataset's."""
    dataset = await read_store(get_settings()).dataset(req.dataset)
    if dataset is None:
        raise inngest.NonRetriableError(f"Dataset {req.dataset} does not exist")

    def inside(day: date) -> bool:
        return req.period_start <= day <= req.period_end

    return dataset.model_copy(update={
        "bank": tuple(t for t in dataset.bank if inside(t.posted_date)),
        "gl": tuple(g for g in dataset.gl if inside(g.date)),
    })


@dataclass(frozen=True)
class GuardScan:
    masked_rows: int  # rows whose text PII masking changes
    flagged: dict[str, tuple[str, ...]]  # injection-flagged row id -> reason names


def guard_scan(dataset: Dataset) -> GuardScan:
    """Screen every bank and GL description: count the masked rows, collect the flagged ones."""
    rows = [(t.txn_id, t.description) for t in dataset.bank] + [(g.entry_id, g.description) for g in dataset.gl]
    masked, flagged = 0, {}
    for row_id, text in rows:
        screened = screen_text(text)
        masked += screened.pii_masked
        if screened.injection.flagged:
            flagged[row_id] = screened.injection.reasons
    return GuardScan(masked_rows=masked, flagged=flagged)


async def record_guard(store: RunStore, run_id: str, scan: GuardScan) -> None:
    """The guard's audit rows: one per injection-flagged row, then the scan's counts. Ids and reason
    names only, never row text."""
    for row_id, reasons in scan.flagged.items():
        await store.add_audit(run_id=run_id, entity_type="guardrail", entity_id=row_id,
                              action="injection_flagged", actor=GUARD_ACTOR, detail={"reasons": list(reasons)})
    await store.add_audit(run_id=run_id, entity_type="run", entity_id=run_id, action="guard_scan",
                          actor=GUARD_ACTOR,
                          detail={"masked_rows": scan.masked_rows, "flagged_rows": list(scan.flagged)})


def to_item(agent_item: AgentItem, run_id: str, created_at: datetime) -> Item:
    a = agent_item
    entry = None
    if a.entry is not None:
        entry = ProposedEntry(
            id=str(uuid4()), debit_account=a.entry.debit_account, credit_account=a.entry.credit_account,
            amount=a.entry.amount, memo=a.entry.memo,
            status="posted" if a.status == "auto_resolved" else "draft",  # only policy write-offs post
        )
    return Item(
        id=str(uuid4()), run_id=run_id, kind=a.kind, resolution=a.resolution, status=a.status,
        bank_ids=a.bank_ids, gl_ids=a.gl_ids, amount_delta=a.amount_delta, reasoning=a.reasoning,
        evidence=a.evidence, flags=a.flags, model=a.model, confidence=a.confidence,
        proposed_entry=entry, created_at=created_at,
    )


def run_counts(dataset: Dataset, items: Sequence[Item]) -> RunCounts:
    status = Counter(i.status for i in items)
    bank = {b for i in items for b in i.bank_ids}
    gl = {g for i in items for g in i.gl_ids}
    unmatched = sum(t.txn_id not in bank for t in dataset.bank) + sum(g.entry_id not in gl for g in dataset.gl)
    return RunCounts(
        bank_transactions=len(dataset.bank), gl_entries=len(dataset.gl), items=len(items),
        matched=status["matched"], auto_resolved=status["auto_resolved"],
        reconciling_item=status["reconciling_item"], needs_approval=status["needs_approval"],
        approved=status["approved"], rejected=status["rejected"], unmatched=unmatched,
    )


def _finished(log_: StepLog, started: datetime, finished: datetime) -> RunStep:
    # LLM stages carry their summed call latency. `run_agents` does not time its code stages, and
    # the block's wall time would overstate them, so their latency stays unknown (null).
    llm = log_.tier != "code"
    return _step(
        log_.id, "completed", model=log_.model, started_at=started, finished_at=finished,
        latency_ms=log_.latency_ms if llm else None,
        tokens_in=log_.tokens_in if llm else None, tokens_out=log_.tokens_out if llm else None,
        output_summary=log_.summary,
    )


async def _reject_event(data: Any) -> None:
    """A malformed event never retries: fail its run when the run id is readable, then stop."""
    run_id = data.get("run_id") if isinstance(data, dict) else None
    if isinstance(run_id, str) and run_id:
        try:
            store = get_run_store(get_settings())
            if await store.get_run(run_id) is not None:
                await store.update_run(run_id, status="failed", error=ApiError(
                    code="invalid_run_event", message="The run.requested event failed validation"))
        except Exception:
            log.exception("could not mark run %s failed after a bad event", run_id)
    # `from None`: pydantic's message echoes input values, and Inngest stores the error's chain.
    raise inngest.NonRetriableError("invalid run.requested event") from None


# retries=0: a failed run is marked failed and re-requested by POST /runs, never replayed. (The
# SDK's test runner ignores NonRetriableError, so this also keeps tests honest.)
@inngest_client.create_function(fn_id="reconcile-run", retries=0,
                                trigger=inngest.TriggerEvent(event=RUN_REQUESTED))
async def reconcile_run(ctx: inngest.Context) -> dict[str, Any]:
    try:
        req = RunRequested.model_validate(ctx.event.data)
    except ValidationError:
        await _reject_event(ctx.event.data)
    store = get_run_store(get_settings())
    run_id = req.run_id

    async def guarded(where: str, stage_ids: Sequence[str],
                      body: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            return await body()
        except Exception as exc:
            # Exception text can echo row text: it is logged here only. The stored error names the
            # block and the exception type, and `from None` keeps the cause out of what Inngest stores.
            log.exception("reconcile-run %s failed in %s", run_id, where)
            err = ApiError(code="step_failed", message=f"{type(exc).__name__} in {where}")
            await store.save_steps(run_id, [_step(s, "failed", finished_at=_now(), error=err) for s in stage_ids])
            await store.update_run(run_id, status="failed", error=ApiError(
                code="run_failed", message=f"Reconciliation failed in {where}"))
            raise inngest.NonRetriableError(f"{where} failed") from None

    async def start() -> dict[str, Any]:
        if await store.get_run(run_id) is None:
            raise inngest.NonRetriableError(f"Run {run_id} does not exist")
        await store.save_steps(run_id, [_step(s.id, "pending") for s in STAGES])
        await store.update_run(run_id, status="running")
        return {"run_id": run_id, "steps": len(STAGES)}

    async def load() -> dict[str, Any]:
        started, t0 = _now(), time.monotonic()
        data = await load_period(req)
        scan = guard_scan(data)
        masked, flagged = scan.masked_rows, len(scan.flagged)
        await record_guard(store, run_id, scan)
        raw = data.balances.bank_closing_balance - data.balances.gl_closing_balance
        ms, finished = int((time.monotonic() - t0) * 1000), _now()
        common = {"started_at": started, "finished_at": finished, "latency_ms": ms}
        await store.save_steps(run_id, [
            _step("load", "completed", **common,
                  output_summary=f"{len(data.bank)} bank rows, {len(data.gl)} GL rows, raw difference {raw}"),
            _step("guard", "completed", **common,
                  output_summary=f"{_plural(masked, 'row')} masked, {_plural(flagged, 'row')} flagged"),
        ])
        await store.update_run(run_id, status="running", counts=RunCounts(
            bank_transactions=len(data.bank), gl_entries=len(data.gl), unmatched=len(data.bank) + len(data.gl)))
        return {"bank_transactions": len(data.bank), "gl_entries": len(data.gl),
                "masked": masked, "flagged": flagged}

    async def agents() -> dict[str, Any]:
        started = _now()
        await store.save_steps(run_id, [_step(s, "running", started_at=started) for s in AGENT_STAGES])
        data = await load_period(req)
        result = await run_agents(data, get_llm_client(get_settings()))
        finished = _now()
        # Explicit, increasing timestamps keep the items in pipeline order when listed.
        items = [to_item(a, run_id, started + timedelta(microseconds=n)) for n, a in enumerate(result.items)]
        await store.replace_items(run_id, items)
        await store.save_steps(run_id, [_finished(s, started, finished) for s in result.steps])
        counts = run_counts(data, items)
        await store.update_run(run_id, status="running", counts=counts)
        return counts.model_dump()

    async def finish() -> dict[str, Any]:
        await store.update_run(run_id, status="completed")
        return {"run_id": run_id}

    await ctx.step.run("start", start)
    await ctx.step.run("load", lambda: guarded("load", LOAD_STAGES, load))
    # run_agents is one call, so a failure cannot be pinned to one of its six stages.
    counts = await ctx.step.run("agents", lambda: guarded("the agent pipeline", AGENT_STAGES, agents))
    await ctx.step.run("finish", finish)
    return {"run_id": run_id, **counts}
