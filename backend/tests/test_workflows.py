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


async def test_run_items_and_decision_routes_work(client):
    from app.api.routes import runs as run_routes
    from app.schemas.runs import Item, ProposedEntry

    create_response = await client.post(
        "/api/v1/runs",
        json={
            "dataset": "northbrook-2026-10",
            "period_start": "2026-10-01",
            "period_end": "2026-10-10",
        },
    )
    run_id = create_response.json()["id"]
    item_id = "item-queued-1"
    run_routes.ITEMS[item_id] = Item(
        id=item_id,
        run_id=run_id,
        kind="unknown",
        resolution="escalate",
        status="needs_approval",
        bank_ids=["BANK099"],
        gl_ids=["GL099"],
        amount_delta="15.00",
        reasoning="Needs review for the vendor credit.",
        evidence=[],
        flags=[],
        model="stub",
        confidence=0.82,
        rule_id=None,
        proposed_entry=ProposedEntry(
            id="entry-queued-1",
            debit_account="6800",
            credit_account="1010",
            amount="15.00",
            memo="Vendor credit",
            status="draft",
        ),
        created_at=run_routes._now(),
    )

    items_response = await client.get(f"/api/v1/runs/{run_id}/items")
    assert items_response.status_code == 200
    assert any(item["id"] == item_id for item in items_response.json())

    decision_response = await client.post(
        f"/api/v1/items/{item_id}/decision",
        json={
            "decision": "approve",
            "remember": False,
            "note": "Looks valid and matches the vendor credit.",
        },
    )
    assert decision_response.status_code == 200
    body = decision_response.json()
    assert body["item"]["status"] == "approved"
    assert body["item"]["proposed_entry"]["status"] == "approved"


async def test_create_run_route_triggers_reconciliation_workflow(client, monkeypatch):
    sent = []

    async def fake_send(events, *, skip_middleware=False):
        sent.append(events)
        return ["evt-1"]

    monkeypatch.setattr("app.api.routes.runs.inngest_client.send", fake_send)

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
    assert len(sent) == 1
    event = sent[0]
    assert event.name == "bridge/reconciliation.requested"
    assert event.data["run_id"] == body["id"]
    assert event.data["dataset"] == "northbrook-2026-10"


async def test_db_run_store_creates_and_fetches_runs(monkeypatch):
    from app.recon.store import DbStore
    from app.schemas.runs import CreateRunRequest

    class FakeCursor:
        def __init__(self, rows=None):
            self._rows = rows or []

        async def execute(self, *_args, **_kwargs):
            return self

        async def fetchone(self):
            return self._rows[0] if self._rows else None

        async def fetchall(self):
            return self._rows

    class FakeConn:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, sql, params=None):
            self.calls.append((sql, params))
            text = sql.strip().lower()
            if text.startswith("insert into runs"):
                    return FakeCursor([
                        {
                            "id": "11111111-1111-4111-8111-111111111111",
                            "dataset": "northbrook-2026-10",
                            "period_start": "2026-10-01",
                            "period_end": "2026-10-10",
                            "status": "queued",
                            "counts": {},
                            "report": None,
                            "error": None,
                            "created_at": "2026-10-27T00:00:00Z",
                            "updated_at": "2026-10-27T00:00:00Z",
                        }
                    ])
            if "from runs where id" in text:
                return FakeCursor([
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "dataset": "northbrook-2026-10",
                        "period_start": "2026-10-01",
                        "period_end": "2026-10-10",
                        "status": "queued",
                        "created_at": "2026-10-27T00:00:00Z",
                        "updated_at": "2026-10-27T00:00:00Z",
                        "steps": [],
                        "counts": {},
                        "report": None,
                        "error": None,
                    }
                ])
            return FakeCursor()

    store = DbStore("postgres://example")
    fake_conn = FakeConn()

    async def fake_connect():
        return fake_conn

    monkeypatch.setattr(store, "_connect", fake_connect)

    run = await store.create_run(CreateRunRequest(
        dataset="northbrook-2026-10",
        period_start="2026-10-01",
        period_end="2026-10-10",
    ))

    assert run.dataset == "northbrook-2026-10"
    assert run.status == "queued"
    fetched = await store.get_run(run.id)
    assert fetched is not None
    assert fetched.id == run.id


async def test_db_run_store_persists_results_and_returns_stable_item_ids(monkeypatch):
    import json

    from app.recon.store import DbStore

    class FakeCursor:
        async def fetchone(self):
            return None

        async def fetchall(self):
            return []

    class FakeConn:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, sql, params=None):
            self.calls.append((sql, params))
            return FakeCursor()

    store = DbStore("postgres://example")
    fake_conn = FakeConn()

    async def fake_connect():
        return fake_conn

    monkeypatch.setattr(store, "_connect", fake_connect)
    result = {
        "counts": {"bank_transactions": 4, "gl_entries": 5, "unmatched_bank": 1, "unmatched_gl": 2},
        "items": [
            {
                "id": "item-0",
                "kind": "bank_fee_missing_in_gl",
                "resolution": "escalate",
                "status": "needs_approval",
                "bank_ids": ["BANK001"],
                "gl_ids": [],
                "amount_delta": "5.00",
                "reasoning": "Needs review",
                "evidence": [],
                "flags": [],
                "proposed_entry": {
                    "debit_account": "6800",
                    "credit_account": "1010",
                    "amount": "5.00",
                    "memo": "Bank fee",
                },
            }
        ],
    }

    item_ids = await store.complete_run("run-123", result)

    assert len(item_ids) == 1
    assert item_ids[0] != "item-0"
    statements = [sql.lower() for sql, _ in fake_conn.calls]
    assert any("insert into items" in sql for sql in statements)
    assert any("insert into proposed_entries" in sql for sql in statements)
    assert any("update runs set status = 'completed'" in sql for sql in statements)
    assert any("update run_steps set status = 'completed'" in sql for sql in statements)
    counts = next(params[0] for sql, params in fake_conn.calls if "update runs set status = 'completed'" in sql.lower())
    assert json.loads(counts)["needs_approval"] == 1


async def test_db_run_store_persists_decision_and_audit(monkeypatch):
    from app.recon.store import DbStore
    from app.schemas.runs import DecisionRequest

    existing_item = {
        "id": "22222222-2222-4222-8222-222222222222",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "kind": "bank_fee_missing_in_gl",
        "resolution": "escalate",
        "status": "needs_approval",
        "bank_ids": ["BANK001"],
        "gl_ids": [],
        "amount_delta": "5.00",
        "reasoning": "Needs review",
        "evidence": [],
        "flags": [],
        "model": "stub",
        "confidence": 0.8,
        "rule_id": None,
        "created_at": "2026-10-27T00:00:00Z",
        "entry_id": "33333333-3333-4333-8333-333333333333",
        "debit_account": "6800",
        "credit_account": "1010",
        "entry_amount": "5.00",
        "entry_memo": "Bank fee",
        "entry_status": "draft",
    }

    class FakeCursor:
        def __init__(self, row=None):
            self.row = row

        async def fetchone(self):
            return self.row

        async def fetchall(self):
            return []

    class FakeConn:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, sql, params=None):
            self.calls.append((sql, params))
            text = sql.lower()
            if "from items i left join proposed_entries" in text:
                if "select i.id::text" in text:
                    if "from runs where" in text:
                        return FakeCursor({
                            "id": "11111111-1111-4111-8111-111111111111",
                            "dataset": "northbrook-2026-10",
                            "period_start": "2026-10-01",
                            "period_end": "2026-10-10",
                            "status": "running",
                            "counts": {},
                            "report": None,
                            "error": None,
                            "created_at": "2026-10-27T00:00:00Z",
                            "updated_at": "2026-10-27T00:00:00Z",
                        })
                    row = dict(existing_item)
                    if any("update items set status" in call_sql.lower() for call_sql, _ in self.calls):
                        row["status"] = "approved"
                        row["entry_status"] = "approved"
                    return FakeCursor(row)
            if "from runs where id::text" in text:
                return FakeCursor({
                    "id": "11111111-1111-4111-8111-111111111111",
                    "dataset": "northbrook-2026-10",
                    "period_start": "2026-10-01",
                    "period_end": "2026-10-10",
                    "status": "running",
                    "counts": {},
                    "report": None,
                    "error": None,
                    "created_at": "2026-10-27T00:00:00Z",
                    "updated_at": "2026-10-27T00:00:00Z",
                })
            return FakeCursor()

    store = DbStore("postgres://example")
    fake_conn = FakeConn()

    async def fake_connect():
        return fake_conn

    monkeypatch.setattr(store, "_connect", fake_connect)
    response = await store.decide_item(
        existing_item["id"],
        DecisionRequest(decision="approve", note="Verified", remember=True),
    )

    assert response.item.status == "approved"
    assert response.item.proposed_entry.status == "approved"
    statements = [sql.lower() for sql, _ in fake_conn.calls]
    assert any("insert into decisions" in sql for sql in statements)
    assert any("insert into audit_log" in sql for sql in statements)
    assert any("update proposed_entries set status" in sql for sql in statements)


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
