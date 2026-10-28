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


def test_reconciliation_run_accepts_validated_run_metadata():
    import inngest
    from inngest.experimental import mocked

    from app.workflows.reconciliation import reconciliation_run

    result = mocked.trigger(
        reconciliation_run,
        inngest.Event(
            name="bridge/reconciliation.requested",
            data={
                "run_id": "run-123",
                "dataset": "northbrook-2026-10",
                "period_start": "2026-10-01",
                "period_end": "2026-10-10",
            },
        ),
        mocked.Inngest(app_id="test"),
    )

    assert result.status is mocked.Status.COMPLETED
    assert result.output == {"run_id": "run-123"}


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
