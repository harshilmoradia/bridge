"""Inngest function `reconcile-run`: load, guard, then the agent pipeline, persisted as it goes.

Triggered by `bridge/run.requested {run_id, dataset, period_start, period_end}` (sent by
`POST /runs`). Coarse durable steps: `start` writes every stage as a pending `run_steps` row,
`load` loads the period and runs the guard (its flags go to `audit_log`), `agents` runs
`run_agents` and saves items, entries and the stage rows, `report` has Ultra write the markdown
report from the statement's numbers, and `finish` marks the run completed.
Inside `agents`, `StageProgress` writes each agent stage's row as it starts (running) and ends
(completed, with model, tier, latency and tokens), so `GET /runs/{id}` shows stages finish one by
one. Progress writes are best effort; the rows are written again once the pipeline returns.

Inngest Cloud stores step outputs, so every step returns IDs and counts only. Rows are re-read
inside each step that needs them. A failing step marks its stages and the run `failed` and
raises `NonRetriableError`: re-running the agents costs a full set of model calls, and the
pipeline already retries model calls itself. The report is the exception: it never fails the
run. A report whose numbers fail the code check twice, or a model outage, gives the template report
and a failed `report` step; any other error leaves `report` null and the step failed.
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
from app.agents.rules import agent_rule
from app.agents.report import ReportResult, report_facts, write_report
from app.core.config import get_settings
from app.guardrails import screen_text
from app.llm import get_llm_client
from app.recon.models import Dataset
from app.recon.run_store import RunStore, get_run_store
from app.recon.statement import build_statement
from app.recon.store import item_refs, read_store
from app.schemas.common import ApiError
from app.schemas.runs import Item, ModelTier, ProposedEntry, RunCounts, RunStep
from app.workflows.client import inngest_client

log = logging.getLogger(__name__)

RUN_REQUESTED = "bridge/run.requested"
GUARD_ACTOR = "agent:guard"
DECIDE_ACTOR = "agent:decide"


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
    Stage("report", 9, "report", "Write the report", "ultra"),
)
STAGE = {s.id: s for s in STAGES}
LOAD_STAGES = ("load", "guard")
AGENT_STAGES = ("match-rules", "match-fuzzy", "classify", "resolve", "review", "decide")
REPORT = "report"


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


async def record_rules_applied(store: RunStore, run_id: str, items: Sequence[Item]) -> int:
    """One audit row per item a learned rule auto-resolved (B-13). Ids and the amount only.

    Idempotent per (run, rule, item): a retried step skips the rows it already wrote. Returns the
    number of rows written."""
    written = 0
    done = {(a.entity_id, a.detail.get("item_id")) for a in await store.list_audit(run_id)
            if a.action == "rule_applied"}
    for item in items:
        if item.rule_id is None or (str(item.rule_id), item.id) in done:
            continue
        await store.add_audit(
            run_id=run_id, entity_type="rule", entity_id=str(item.rule_id), action="rule_applied",
            actor=DECIDE_ACTOR, detail={"item_id": item.id, "bank_ids": list(item.bank_ids),
                                        "gl_ids": list(item.gl_ids),
                                        "amount": str(item.proposed_entry.amount) if item.proposed_entry else None})
        written += 1
    return written


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
        rule_id=a.rule_id, proposed_entry=entry, created_at=created_at,
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


def _finished(log_: StepLog, started: datetime, finished: datetime, wall_ms: int) -> RunStep:
    # LLM stages carry their summed call latency; code stages their own wall time and no tokens.
    llm = log_.tier != "code"
    return _step(
        log_.id, "completed", model=log_.model, started_at=started, finished_at=finished,
        latency_ms=log_.latency_ms if llm else wall_ms,
        tokens_in=log_.tokens_in if llm else None, tokens_out=log_.tokens_out if llm else None,
        output_summary=log_.summary,
    )


def report_row(out: ReportResult, started: datetime, finished: datetime) -> RunStep:
    """The report stage's row. A template report means the model's report was not usable: the
    step is failed (with the reason) even though the run has a report."""
    stats = out.stats
    common = {
        "model": stats[0].model if stats else None, "started_at": started, "finished_at": finished,
        "latency_ms": sum(s.latency_ms for s in stats) if stats else None,
        "tokens_in": sum(s.prompt_tokens for s in stats) if stats else None,
        "tokens_out": sum(s.completion_tokens for s in stats) if stats else None,
    }
    if out.source == "model":
        return _step(REPORT, "completed", output_summary="Report written", **common)
    if out.source == "repaired":
        return _step(REPORT, "completed", output_summary="Report written after one repair", **common)
    if stats:
        return _step(REPORT, "failed", output_summary="Template report: the model's numbers failed the check",
                     error=ApiError(code="report_unverified",
                                    message=f"{len(out.unsupported)} numbers not in the statement"), **common)
    return _step(REPORT, "failed", output_summary="Template report: the model was unavailable",
                 error=ApiError(code="report_model_unavailable", message="The report model did not answer"),
                 **common)


class StageProgress:
    """`run_agents`' on_step hook: writes each agent stage's row as it starts and as it ends.

    Times are kept here before the write, so the final rows written after `run_agents` returns are
    complete even when a progress write failed (`run_agents` logs and swallows hook errors).
    """

    def __init__(self, store: RunStore, run_id: str) -> None:
        self._store, self._run_id = store, run_id
        self._started: dict[str, tuple[datetime, float]] = {}
        self._rows: dict[str, RunStep] = {}

    async def __call__(self, stage_id: str, log_: StepLog | None) -> None:
        if log_ is None:
            started = _now()
            try:
                await self._store.save_steps(self._run_id, [_step(stage_id, "running", started_at=started)])
            finally:  # a code stage's wall time should not include its own progress write
                self._started[stage_id] = (started, time.monotonic())
            return
        started, t0 = self._started.get(stage_id, (_now(), time.monotonic()))
        row = _finished(log_, started, _now(), int((time.monotonic() - t0) * 1000))
        self._rows[stage_id] = row
        await self._store.save_steps(self._run_id, [row])

    def rows(self) -> list[RunStep]:
        return list(self._rows.values())

    def unfinished(self) -> list[str]:
        return [s for s in AGENT_STAGES if s not in self._rows]

    def to_fail(self) -> list[str]:
        """The stages a failure marks failed: the unfinished ones, or the last stage when every
        stage finished and a later write failed, so a failed run never shows all green."""
        return [*(self.unfinished() or [AGENT_STAGES[-1]]), REPORT]


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

    progress = StageProgress(store, run_id)

    async def guarded(where: str, stage_ids: Callable[[], Sequence[str]],
                      body: Callable[[], Awaitable[dict[str, Any]]],
                      done_rows: Callable[[], Sequence[RunStep]] = lambda: ()) -> dict[str, Any]:
        try:
            return await body()
        except Exception as exc:
            # Exception text can echo row text: it is logged here only. The stored error names the
            # block and the exception type, and `from None` keeps the cause out of what Inngest stores.
            log.exception("reconcile-run %s failed in %s", run_id, where)
            # Rewrite the finished stages first, one by one: it repairs a lost progress write. A
            # stage whose rewrite fails too may still show running, so it is marked failed instead.
            unrepaired: list[str] = []
            for row in done_rows():
                try:
                    await store.save_steps(run_id, [row])
                except Exception as repair:
                    log.warning("reconcile-run %s could not rewrite stage %s: %s",
                                run_id, row.id, type(repair).__name__)
                    unrepaired.append(row.id)
            err = ApiError(code="step_failed", message=f"{type(exc).__name__} in {where}")
            failed = [*unrepaired, *(s for s in stage_ids() if s not in unrepaired)]
            await store.save_steps(run_id, [_step(s, "failed", finished_at=_now(), error=err) for s in failed])
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
        data = await load_period(req)
        stored = await store.list_rules(data.id)
        rules = [r for r in (agent_rule(x, data.id) for x in stored) if r is not None]
        result = await run_agents(data, get_llm_client(get_settings()), rules=rules, on_step=progress)
        # Explicit, increasing timestamps keep the items in pipeline order when listed.
        items = [to_item(a, run_id, started + timedelta(microseconds=n)) for n, a in enumerate(result.items)]
        await store.replace_items(run_id, items)
        # Rewrite every stage's final row: it repairs any progress write that failed.
        await store.save_steps(run_id, progress.rows())
        counts = run_counts(data, items)
        await store.update_run(run_id, status="running", counts=counts)
        return {**counts.model_dump(), "rule_item_ids": [i.id for i in items if i.rule_id is not None]}

    async def rules_applied(item_ids: list[str]) -> dict[str, Any]:
        # Its own step, after the items are saved: an agents retry writes new item ids, so the audit
        # rows are written once the ids are final (and record_rules_applied skips rows already written).
        # Best effort, like the report: the items are already saved, so a lost audit row must not
        # leave the run stuck in running. Only the exception type is logged, never row text.
        try:
            items = [i for i in [await store.get_item(x) for x in item_ids] if i is not None]
            return {"rules_applied": await record_rules_applied(store, run_id, items)}
        except Exception as exc:
            log.error("reconcile-run %s could not record applied rules: %s", run_id, type(exc).__name__)
            return {"rules_applied": 0}

    async def report() -> dict[str, Any]:
        # Never raises: the run's numbers are already saved, so a report problem must not fail it.
        started = _now()
        try:  # progress is for display: the final row below repairs a lost running write
            await store.save_steps(run_id, [_step(REPORT, "running", started_at=started)])
        except Exception as e:
            log.warning("reconcile-run %s report progress write failed: %s", run_id, type(e).__name__)
        try:
            data = await load_period(req)
            refs = item_refs(await store.list_items(run_id))
            run = await store.get_run(run_id)
            facts = report_facts(build_statement(data, run_id, refs), run.counts, refs)
            out = await write_report(get_llm_client(get_settings()), facts, run_id=run_id)
            # The row first: if it cannot be written, the report is not saved either, so a
            # failed step never sits beside a saved model report.
            await store.save_steps(run_id, [report_row(out, started, _now())])
            await store.update_run(run_id, status="running", report=out.markdown)
            return {"report_chars": len(out.markdown), "model_calls": len(out.stats),
                    "unsupported_numbers": len(out.unsupported)}
        except Exception as exc:
            log.exception("reconcile-run %s failed in the report", run_id)
            try:
                await store.save_steps(run_id, [_step(REPORT, "failed", started_at=started, finished_at=_now(),
                                                      error=ApiError(code="report_failed",
                                                                     message=f"{type(exc).__name__} in the report"))])
            except Exception as again:
                log.warning("reconcile-run %s could not mark the report failed: %s", run_id, type(again).__name__)
            return {"report_chars": 0, "model_calls": 0, "unsupported_numbers": 0}

    async def finish() -> dict[str, Any]:
        await store.update_run(run_id, status="completed")
        return {"run_id": run_id}

    await ctx.step.run("start", start)
    # A failed load means no later stage runs: they are all marked failed.
    await ctx.step.run("load", lambda: guarded("load", lambda: [s.id for s in STAGES], load))
    # On a failure, the stages that already finished keep their rows; the rest are marked failed.
    counts = await ctx.step.run("agents", lambda: guarded("the agent pipeline", progress.to_fail, agents,
                                                                   progress.rows))
    rule_item_ids = list(counts.get("rule_item_ids", []))
    await ctx.step.run("rules-applied", lambda: rules_applied(rule_item_ids))
    await ctx.step.run("report", report)
    await ctx.step.run("finish", finish)
    return {"run_id": run_id, **{k: v for k, v in counts.items() if k != "rule_item_ids"}}
