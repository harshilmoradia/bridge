"""The `reconcile-run` Inngest function, run in-process with Inngest's mock and a scripted model.

Expected numbers are independent of the workflow code: item statuses come from the worked
example in test_agents_pipeline.py (106 matched, 2 auto-resolved, 2 reconciling, 5 escalated),
row counts from demo-data (112 bank, 114 GL), and guard counts from demo-data's PII rows (BANK004,
BANK024, BANK068, BANK070, BANK099, BANK113 and GL007, GL025, GL028, GL038, GL069, GL098 carry
account numbers, contacts or people's names) and B-08's injection row BANK074.
"""

import asyncio
import json
import re
from datetime import date

import inngest
import pytest
from inngest._internal.comm_lib.models import ErrorData  # what the SDK reports to Inngest for an error
from inngest.experimental import mocked

from app.core.config import get_settings
from app.recon.run_store import MemoryRunStore
from tests.test_agents_pipeline import Oracle, client_for

DATASET = "northbrook-2026-10"


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATASET", DATASET)
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    get_settings.cache_clear()
    memory = MemoryRunStore()
    monkeypatch.setattr("app.workflows.reconcile.get_run_store", lambda _settings: memory)
    yield memory
    get_settings.cache_clear()


def _use_model(monkeypatch, oracle) -> None:
    client, _ = client_for(oracle)
    monkeypatch.setattr("app.workflows.reconcile.get_llm_client", lambda _settings: client)


def _trigger(run_id: str, period=("2026-10-01", "2026-10-31")):
    from app.workflows.reconcile import reconcile_run

    event = inngest.Event(name="bridge/run.requested", data={
        "run_id": run_id, "dataset": DATASET, "period_start": period[0], "period_end": period[1]})
    return mocked.trigger(reconcile_run, event, mocked.Inngest(app_id="test"))  # runs its own loop


def _new_run(store: MemoryRunStore) -> str:
    return asyncio.run(store.create_run(DATASET, date(2026, 10, 1), date(2026, 10, 31))).id


def test_run_completes_and_persists_items_entries_and_steps(store, monkeypatch):
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "completed"
    c = run.counts
    assert (c.bank_transactions, c.gl_entries, c.unmatched) == (112, 114, 0)
    assert (c.matched, c.auto_resolved, c.reconciling_item, c.needs_approval) == (106, 2, 2, 5)
    assert c.items == 115

    items = asyncio.run(store.list_items(run_id))
    assert len(items) == 115 and all(i.run_id == run_id for i in items)
    escalated = asyncio.run(store.list_items(run_id, "needs_approval"))
    assert len(escalated) == 5
    assert all(i.proposed_entry and i.proposed_entry.status == "draft" for i in escalated)
    fee = next(i for i in escalated if i.bank_ids == ["BANK032"])
    assert (fee.proposed_entry.debit_account, fee.proposed_entry.credit_account,
            str(fee.proposed_entry.amount)) == ("6800", "1010", "25.00")
    writeoff = next(i for i in items if i.bank_ids == ["BANK033"])
    assert writeoff.status == "auto_resolved" and writeoff.proposed_entry.status == "posted"

    steps = {s.id: s for s in run.steps}
    assert list(steps) == ["load", "guard", "match-rules", "match-fuzzy", "classify", "resolve", "review", "decide",
                           "report"]
    assert all(s.status == "completed" for s in run.steps)
    assert steps["guard"].output_summary == "12 rows masked, 1 row flagged"
    assert steps["load"].output_summary == "112 bank rows, 114 GL rows, raw difference 864.09"
    assert (steps["match-fuzzy"].tier, steps["match-fuzzy"].model) == ("nano", "m-nano")
    assert steps["resolve"].tier == "super" and steps["resolve"].tokens_in is not None
    # Code stages are timed by their own wall clock and carry no tokens.
    assert steps["match-rules"].tokens_in is None and steps["match-rules"].latency_ms is not None
    assert steps["load"].latency_ms is not None
    order = [steps[s] for s in ("match-rules", "match-fuzzy", "classify", "resolve", "decide")]
    assert all(a.finished_at <= b.started_at for a, b in zip(order, order[1:]))  # each stage its own times


def _statuses(store: MemoryRunStore, run_id: str) -> dict[str, str]:
    # The model is called synchronously inside the running loop, so read the memory store directly.
    return {s.id: s.status for s in store._runs[run_id].steps}


def test_each_stage_shows_live_while_later_stages_run(store, monkeypatch):
    seen: dict[str, dict[str, str]] = {}
    run_id = _new_run(store)

    class Watcher(Oracle):
        def classify(self, messages, model):
            seen.setdefault("classify", _statuses(store, run_id))
            return super().classify(messages, model)

        def resolve(self, messages, model):
            seen.setdefault("resolve", _statuses(store, run_id))
            classify = next(s for s in store._runs[run_id].steps if s.id == "classify")
            seen.setdefault("classify_row", classify.model_dump())
            return super().resolve(messages, model)

    _use_model(monkeypatch, Watcher())
    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    done = "completed"
    assert seen["classify"] == {"load": done, "guard": done, "match-rules": done, "match-fuzzy": done,
                                "classify": "running", "resolve": "pending", "review": "pending",
                                "decide": "pending", "report": "pending"}
    # Resolve and the critic review interleave per item, so both run together.
    assert seen["resolve"] == {"load": done, "guard": done, "match-rules": done, "match-fuzzy": done,
                               "classify": done, "resolve": "running", "review": "running",
                               "decide": "pending", "report": "pending"}
    row = seen["classify_row"]
    assert (row["tier"], row["model"]) == ("nano", "m-nano")
    assert row["finished_at"] is not None and row["latency_ms"] is not None and row["tokens_in"] is not None
    assert row["output_summary"] == "7 items classified: 6 by code, 1 by Nano"


class FlakyProgress(MemoryRunStore):
    """Every 'running' progress write fails; the other writes work."""

    async def save_steps(self, run_id, steps):
        if any(s.status == "running" for s in steps):
            raise ConnectionError("pooler hiccup")
        await super().save_steps(run_id, steps)


def test_a_failed_progress_write_does_not_fail_the_run(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATASET", DATASET)
    get_settings.cache_clear()
    flaky = FlakyProgress()
    monkeypatch.setattr("app.workflows.reconcile.get_run_store", lambda _settings: flaky)
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(flaky)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(flaky.get_run(run_id))
    assert run.status == "completed" and run.counts.needs_approval == 5
    assert all(s.status == "completed" and s.started_at is not None for s in run.steps)
    get_settings.cache_clear()


def test_guard_writes_its_flags_to_the_audit_log(store, monkeypatch):
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    guard = [a for a in store.audit if a["actor"] == "agent:guard"]
    assert [(a["entity_type"], a["entity_id"], a["action"]) for a in guard] == [
        ("guardrail", "BANK074", "injection_flagged"),
        ("run", run_id, "guard_scan"),
    ]
    assert all(a["run_id"] == run_id for a in guard)
    assert guard[0]["detail"]["reasons"]
    assert guard[1]["detail"] == {"masked_rows": 12, "flagged_rows": ["BANK074"]}
    assert "IGNORE" not in json.dumps([a["detail"] for a in guard])  # ids and reasons, never row text


def test_step_outputs_carry_ids_and_counts_only(store, monkeypatch):
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    def scalars(value):
        if isinstance(value, dict):
            for v in value.values():
                yield from scalars(v)
        elif isinstance(value, list):
            for v in value:
                yield from scalars(v)
        else:
            yield value

    assert result.status is mocked.Status.COMPLETED
    dumped = json.dumps(result.output)
    assert "SERVICE FEE" not in dumped and "4417" not in dumped
    assert all(isinstance(v, int) or v == run_id for v in scalars(result.output))


def test_run_limits_rows_to_the_requested_period(store, monkeypatch):
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id, ("2026-10-01", "2026-10-02"))

    assert result.status is mocked.Status.COMPLETED, result.error
    counts = asyncio.run(store.get_run(run_id)).counts
    assert (counts.bank_transactions, counts.gl_entries) == (20, 22)  # from the WFS prior-art test


class ModelDown(Oracle):
    def classify(self, messages, _model):
        raise RuntimeError("ROW TEXT: ACH DEBIT REIMB JOHN SMITH ACCT 000123456789")


def test_a_failing_stage_marks_the_run_failed(store, monkeypatch):
    oracle = ModelDown()
    _use_model(monkeypatch, oracle)
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.FAILED
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "failed" and run.error.code == "run_failed"
    assert run.error.message == "Reconciliation failed in the agent pipeline"
    # Exception text can echo row text: none of it may reach the store or what Inngest keeps.
    stored = ErrorData.from_error(result.error)
    leaked = [stored.message, stored.stack or "", run.error.message] + [s.error.message for s in run.steps if s.error]
    assert not [t for t in leaked if "JOHN SMITH" in t or "000123456789" in t]
    # Stages that finished before the failure keep their rows; the failing stage and the ones it
    # never reached are failed, so no stage is left running or pending on a failed run.
    status = {s.id: s.status for s in run.steps}
    assert status == {"load": "completed", "guard": "completed", "match-rules": "completed",
                      "match-fuzzy": "completed", "classify": "failed", "resolve": "failed",
                      "review": "failed", "decide": "failed", "report": "failed"}
    assert all(s.error.message == "RuntimeError in the agent pipeline" for s in run.steps if s.error)
    assert run.report is None
    assert len(oracle.prompts["classify"]) == 1  # the agents ran once: no retry replays the model calls
    assert asyncio.run(store.list_items(run_id)) == []


def _with_store(monkeypatch, store: MemoryRunStore) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATASET", DATASET)
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    get_settings.cache_clear()
    monkeypatch.setattr("app.workflows.reconcile.get_run_store", lambda _settings: store)


class FuzzyEndWriteFailsOnce(MemoryRunStore):
    """The first write of match-fuzzy's completed row fails; every later write works."""

    failed = False

    async def save_steps(self, run_id, steps):
        if not self.failed and any(s.id == "match-fuzzy" and s.status == "completed" for s in steps):
            self.failed = True
            raise ConnectionError("pooler hiccup")
        await super().save_steps(run_id, steps)


def test_a_failed_run_repairs_a_lost_completed_row(monkeypatch):
    store = FuzzyEndWriteFailsOnce()
    _with_store(monkeypatch, store)
    _use_model(monkeypatch, ModelDown())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.FAILED
    run = asyncio.run(store.get_run(run_id))
    status = {s.id: s.status for s in run.steps}
    assert store.failed and run.status == "failed"
    assert status["match-fuzzy"] == "completed" and status["classify"] == "failed"
    assert not [s for s, v in status.items() if v in ("running", "pending")]
    get_settings.cache_clear()


class ItemsWriteFails(MemoryRunStore):
    async def replace_items(self, run_id, items):
        raise RuntimeError("db down")


def test_a_failure_after_the_pipeline_returns_marks_decide_failed(monkeypatch):
    store = ItemsWriteFails()
    _with_store(monkeypatch, store)
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.FAILED
    run = asyncio.run(store.get_run(run_id))
    status = {s.id: s.status for s in run.steps}
    assert run.status == "failed"
    # Every agent stage finished, so the run's last stage carries the failure: never all green.
    assert status["decide"] == "failed"
    assert status["report"] == "failed"
    assert all(v == "completed" for s, v in status.items() if s not in ("decide", "report"))
    get_settings.cache_clear()


def _statement_numbers(store: MemoryRunStore, run_id: str) -> set[str]:
    """What GET /statement shows for the run, plus its counts, as plain number strings."""
    from app.recon.loader import load_dataset
    from app.recon.statement import build_statement
    from app.recon.store import item_refs

    items = asyncio.run(store.list_items(run_id))
    statement = build_statement(load_dataset(DATASET), run_id, item_refs(items))
    counts = asyncio.run(store.get_run(run_id)).counts
    text = statement.model_dump_json() + counts.model_dump_json()
    return {n.lstrip("-") for n in re.findall(r"-?\d+(?:\.\d+)?", text)}


def test_a_completed_run_carries_a_report_built_from_the_statement(store, monkeypatch):
    oracle = Oracle()
    _use_model(monkeypatch, oracle)
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "completed" and run.report
    assert "48547.99" in run.report and "864.09" in run.report  # demo-data closing balance and raw difference
    found = [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", run.report)]
    assert set(found) <= _statement_numbers(store, run_id)
    step = next(s for s in run.steps if s.id == "report")
    assert (step.status, step.tier, step.model, step.position) == ("completed", "ultra", "m-ultra", 9)
    assert step.output_summary == "Report written" and step.tokens_in is not None
    facts = oracle.prompts["report"][0]
    assert "SERVICE FEE" not in facts and "BANK032" not in facts  # computed numbers only, no row text


class UltraInvents(Oracle):
    def report(self, messages, model):
        return "The raw difference is 1,234.56."


def test_a_report_that_fails_its_check_falls_back_and_the_run_completes(store, monkeypatch):
    oracle = UltraInvents()
    _use_model(monkeypatch, oracle)
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "completed" and run.error is None
    assert run.report.startswith("## Northbrook") and "1,234.56" not in run.report
    assert len(oracle.prompts["report"]) == 2  # one repair, then the template
    step = next(s for s in run.steps if s.id == "report")
    assert (step.status, step.error.code) == ("failed", "report_unverified")
    assert step.output_summary == "Template report: the model's numbers failed the check"


class UltraDown(Oracle):
    def report(self, messages, model):
        from app.core.errors import LLMUnavailableError
        raise LLMUnavailableError("down")


def test_an_ultra_outage_gives_the_template_report(store, monkeypatch):
    _use_model(monkeypatch, UltraDown())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "completed" and "864.09" in run.report
    step = next(s for s in run.steps if s.id == "report")
    assert (step.status, step.error.code, step.model) == ("failed", "report_model_unavailable", None)


def test_a_failed_load_marks_every_stage_failed(store, monkeypatch):
    async def broken(_req):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.workflows.reconcile.load_period", broken)
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.FAILED
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "failed" and len(run.steps) == 9
    assert all(s.status == "failed" and s.error.message == "RuntimeError in load" for s in run.steps)


class ReportReadFails(MemoryRunStore):
    """Only the report step lists items, so only it fails."""

    async def list_items(self, run_id, status=None):
        raise RuntimeError("db down")


def test_a_crashing_report_step_leaves_the_run_completed_without_a_report(monkeypatch):
    store = ReportReadFails()
    _with_store(monkeypatch, store)
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "completed" and run.report is None and run.counts.needs_approval == 5
    step = next(s for s in run.steps if s.id == "report")
    assert (step.status, step.error.code, step.error.message) == ("failed", "report_failed",
                                                                  "RuntimeError in the report")
    get_settings.cache_clear()


def test_unknown_run_fails_without_retry(store, monkeypatch):
    _use_model(monkeypatch, Oracle())
    result = _trigger("00000000-0000-0000-0000-000000000000")
    assert result.status is mocked.Status.FAILED


def test_a_malformed_event_fails_the_run_without_retrying(store, monkeypatch):
    from app.workflows.reconcile import reconcile_run

    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)
    event = inngest.Event(name="bridge/run.requested", data={
        "run_id": run_id, "dataset": DATASET, "period_start": "JOHN SMITH", "period_end": "2026-10-31"})

    result = mocked.trigger(reconcile_run, event, mocked.Inngest(app_id="test"))

    assert result.status is mocked.Status.FAILED
    stored = ErrorData.from_error(result.error)
    assert "JOHN SMITH" not in stored.message + (stored.stack or "")
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "failed" and run.error.code == "invalid_run_event"


def test_event_rejects_a_reversed_period():
    from pydantic import ValidationError

    from app.workflows.reconcile import RunRequested

    with pytest.raises(ValidationError, match="period_start must not be after period_end"):
        RunRequested.model_validate({"run_id": "r", "dataset": DATASET,
                                     "period_start": "2026-10-10", "period_end": "2026-10-01"})


class FuzzyEndWriteAlwaysFails(MemoryRunStore):
    """Every write of match-fuzzy's completed row fails, so the repair rewrite fails too."""

    async def save_steps(self, run_id, steps):
        if any(s.id == "match-fuzzy" and s.status == "completed" for s in steps):
            raise ConnectionError("pooler down")
        await super().save_steps(run_id, steps)


def test_a_failed_repair_marks_the_unrepaired_stage_failed(monkeypatch):
    store = FuzzyEndWriteAlwaysFails()
    _with_store(monkeypatch, store)
    _use_model(monkeypatch, ModelDown())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.FAILED
    run = asyncio.run(store.get_run(run_id))
    status = {s.id: s.status for s in run.steps}
    assert run.status == "failed"
    assert status["match-fuzzy"] == "failed" and status["classify"] == "failed"
    assert status["match-rules"] == "completed"  # its rewrite worked, so it keeps its row
    assert not [s for s, v in status.items() if v in ("running", "pending")]
    get_settings.cache_clear()


class ReportRowWriteFails(MemoryRunStore):
    """The report's final (completed) row cannot be written; its failed row can."""

    async def save_steps(self, run_id, steps):
        if any(s.id == "report" and s.status == "completed" for s in steps):
            raise ConnectionError("pooler down")
        await super().save_steps(run_id, steps)


def test_a_report_whose_step_row_is_lost_is_not_saved(monkeypatch):
    store = ReportRowWriteFails()
    _with_store(monkeypatch, store)
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(store.get_run(run_id))
    step = next(s for s in run.steps if s.id == "report")
    # The step row and the report agree: a failed step never sits beside a saved model report.
    assert (step.status, step.error.code) == ("failed", "report_failed")
    assert run.report is None
    get_settings.cache_clear()


class AuditReadFails(MemoryRunStore):
    """Only the rules-applied step reads the audit log, so only it fails."""

    async def list_audit(self, run_id):
        raise RuntimeError("db down")


def test_a_failing_rules_applied_step_leaves_the_run_completed(monkeypatch):
    store = AuditReadFails()
    _with_store(monkeypatch, store)
    _use_model(monkeypatch, Oracle())
    run_id = _new_run(store)

    result = _trigger(run_id)

    assert result.status is mocked.Status.COMPLETED, result.error
    run = asyncio.run(store.get_run(run_id))
    assert run.status == "completed" and run.counts.needs_approval == 5
    get_settings.cache_clear()
