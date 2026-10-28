async def test_inngest_endpoint_lists_functions(client):
    response = await client.get("/api/inngest")
    assert response.status_code == 200
    body = response.json()
    assert body["function_count"] == 2
    assert body["mode"] == "dev"


def test_smoke_run_executes_all_steps(monkeypatch):
    import inngest
    from inngest.experimental import mocked

    from app.core.config import get_settings
    from app.workflows.smoke import smoke_run

    monkeypatch.setenv("LLM_PROVIDER", "stub")
    get_settings.cache_clear()

    result = mocked.trigger(
        smoke_run,
        inngest.Event(name="bridge/smoke.requested", data={"topic": "cards"}),
        mocked.Inngest(app_id="test"),
    )

    assert result.status is mocked.Status.COMPLETED
    assert set(result.output) == {"plan", "a", "b", "summary"}
    assert "agent-a-ok" in result.output["a"]
    assert "agent-b-ok" in result.output["b"]
    assert "cards" in result.output["plan"]
    get_settings.cache_clear()


def _trigger_reconciliation(monkeypatch, period_start="2026-10-01", period_end="2026-10-10"):
    import inngest
    from inngest.experimental import mocked

    from app.core.config import get_settings
    from app.workflows.reconciliation import reconciliation_run

    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATASET", "northbrook-2026-10")
    get_settings.cache_clear()
    result = mocked.trigger(
        reconciliation_run,
        inngest.Event(
            name="bridge/reconciliation.requested",
            data={
                "run_id": "run-123",
                "dataset": "northbrook-2026-10",
                "period_start": period_start,
                "period_end": period_end,
            },
        ),
        mocked.Inngest(app_id="test"),
    )
    get_settings.cache_clear()
    return result


def test_reconciliation_run_loads_dataset_and_runs_rule_matcher(monkeypatch):
    from inngest.experimental import mocked

    result = _trigger_reconciliation(monkeypatch)
    assert result.status is mocked.Status.COMPLETED
    output = result.output
    assert output["run_id"] == "run-123"
    assert output["counts"]["bank_transactions"] == 112
    assert output["counts"]["gl_entries"] == 114

    # One bank deposit is matched to the three ledger invoices by deterministic subset sum.
    assert {"bank_ids": ["BANK112"], "gl_ids": ["GL111", "GL112", "GL113"]} in output["matches"]
    # The duplicate check remains an LLM candidate rather than being guessed by code.
    assert any(
        group["bank_ids"] == ["BANK009"] and group["gl_ids"] == ["GL002", "GL003"]
        for group in output["candidate_groups"]
    )
    assert "description" not in str(output).lower()
    assert "amount" not in str(output).lower()


def test_reconciliation_run_limits_inputs_to_requested_period(monkeypatch):
    from inngest.experimental import mocked

    result = _trigger_reconciliation(monkeypatch, "2026-10-01", "2026-10-02")
    assert result.status is mocked.Status.COMPLETED
    assert result.output["counts"]["bank_transactions"] == 20
    assert result.output["counts"]["gl_entries"] == 22


def test_reconciliation_run_resolves_ambiguous_candidates(monkeypatch):
    import inngest
    from inngest.experimental import mocked

    from app.core.config import get_settings
    from app.workflows.reconciliation import reconciliation_run

    class FakeClient:
        async def complete_json(self, *_args, **_kwargs):
            return type("Decision", (), {"selected_option_index": 1, "confidence": 0.94, "reason": "second option is the later posting"})(), None

    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATASET", "northbrook-2026-10")
    monkeypatch.setattr("app.workflows.reconciliation.get_llm_client", lambda _settings: FakeClient())
    get_settings.cache_clear()
    result = mocked.trigger(
        reconciliation_run,
        inngest.Event(
            name="bridge/reconciliation.requested",
            data={
                "run_id": "run-456",
                "dataset": "northbrook-2026-10",
                "period_start": "2026-10-01",
                "period_end": "2026-10-10",
            },
        ),
        mocked.Inngest(app_id="test"),
    )
    get_settings.cache_clear()

    assert result.status is mocked.Status.COMPLETED
    assert result.output["counts"]["candidate_groups"] >= 1
    assert result.output["resolved_candidates"]
    assert result.output["resolved_candidates"][0]["selected_option_index"] == 1
    assert any(
        decision["resolution"] in {"auto_match", "auto_match_with_writeoff", "escalate"}
        and decision["kind"] is not None
        for decision in result.output["policy_decisions"]
    )
    assert any(item["resolution"] == "auto_match" and item["status"] == "matched" for item in result.output["items"])


async def test_create_run_route_returns_queued_run(client):
    response = await client.post(
        "/api/v1/runs",
        json={
            "dataset": "northbrook-2026-10",
            "period_start": "2026-10-01",
            "period_end": "2026-10-10",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["id"]

    run_response = await client.get(f"/api/v1/runs/{body['id']}")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["dataset"] == "northbrook-2026-10"
    assert run["status"] == "queued"


def test_reconciliation_request_rejects_reversed_period():
    import pytest
    from pydantic import ValidationError

    from app.workflows.reconciliation import ReconciliationRequested

    with pytest.raises(ValidationError, match="period_start must not be after period_end"):
        ReconciliationRequested.model_validate({
            "run_id": "run-123",
            "dataset": "northbrook-2026-10",
            "period_start": "2026-10-10",
            "period_end": "2026-10-01",
        })
