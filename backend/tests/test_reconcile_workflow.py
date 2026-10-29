"""The `reconcile-run` Inngest function, run in-process with Inngest's mock and a scripted model.

Expected numbers are independent of the workflow code: item statuses come from the worked
example in test_agents_pipeline.py (106 matched, 2 auto-resolved, 2 reconciling, 5 escalated),
row counts from demo-data (112 bank, 114 GL), and guard counts from demo-data's PII rows (BANK004,
BANK024, BANK068, BANK070, BANK099, BANK113 and GL007, GL025, GL028, GL038, GL069, GL098 carry
account numbers, contacts or people's names) and B-08's injection row BANK074.
"""

import asyncio
import json
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
    assert list(steps) == ["load", "guard", "match-rules", "match-fuzzy", "classify", "resolve", "review", "decide"]
    assert all(s.status == "completed" for s in run.steps)
    assert steps["guard"].output_summary == "12 rows masked, 1 row flagged"
    assert steps["load"].output_summary == "112 bank rows, 114 GL rows, raw difference 864.09"
    assert (steps["match-fuzzy"].tier, steps["match-fuzzy"].model) == ("nano", "m-nano")
    assert steps["resolve"].tier == "super" and steps["resolve"].tokens_in is not None
    # run_agents does not time its code stages; the block's wall time would overstate them.
    assert steps["match-rules"].tokens_in is None and steps["match-rules"].latency_ms is None
    assert steps["load"].latency_ms is not None


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
    failed = {s.id for s in run.steps if s.status == "failed"}
    assert failed == {"match-rules", "match-fuzzy", "classify", "resolve", "review", "decide"}
    assert all(s.error.message == "RuntimeError in the agent pipeline" for s in run.steps if s.error)
    assert len(oracle.prompts["classify"]) == 1  # the agents ran once: no retry replays the model calls
    assert {s.id: s.status for s in run.steps}["load"] == "completed"
    assert any(s.status == "failed" for s in run.steps)
    assert asyncio.run(store.list_items(run_id)) == []


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
