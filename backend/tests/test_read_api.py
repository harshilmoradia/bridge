"""Read API v1 over the CSV source (no DATABASE_URL). Expected values come from demo-data/ and the backlog."""

import json
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api.routes.reads import get_read_store
from app.recon.models import ProposedEntry
from app.recon.store import CsvStore, ItemRef, RunItems
from tests.test_run_contract import FIXTURES

DATASET = "northbrook-2026-10"
# conftest turns PUBLIC_DEMO_API on, so these calls need no bearer token (see test_demo_auth.py).


async def test_datasets_lists_the_demo_dataset(client: AsyncClient):
    response = await client.get("/api/v1/datasets")
    assert response.status_code == 200
    assert response.json() == [
        {"id": DATASET, "label": "Northbrook Goods Co.", "period_start": "2026-10-01", "period_end": "2026-10-10"}
    ]


async def test_bank_transactions_are_unmatched_before_any_run(client: AsyncClient):
    response = await client.get("/api/v1/bank-transactions", params={"dataset": DATASET})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 112
    assert {r["recon_status"] for r in rows} == {"unmatched"}
    assert next(r for r in rows if r["txn_id"] == "BANK005") == {
        "txn_id": "BANK005",
        "posted_date": "2026-10-01",
        "description": "CHECK 3105",
        "amount": "-680.00",
        "type": "CHECK",
        "check_number": "3105",
        "running_balance": "209075.00",
        "recon_status": "unmatched",
        "item_id": None,
    }


@pytest.mark.parametrize(
    ("path", "params", "count"),
    [
        ("/api/v1/bank-transactions", {"from": "2026-10-01", "to": "2026-10-02"}, 20),
        ("/api/v1/bank-transactions", {"from": "2026-10-10"}, 11),
        ("/api/v1/gl-entries", {"from": "2026-10-01", "to": "2026-10-02"}, 22),
        ("/api/v1/gl-entries", {}, 114),
    ],
)
async def test_rows_filter_by_inclusive_date_range(client: AsyncClient, path, params, count):
    response = await client.get(path, params=params)
    assert response.status_code == 200
    assert len(response.json()) == count


async def test_gl_entries_carry_ledger_fields(client: AsyncClient):
    rows = (await client.get("/api/v1/gl-entries")).json()
    assert next(r for r in rows if r["entry_id"] == "GL017") == {
        "entry_id": "GL017",
        "date": "2026-10-02",
        "description": "Software License Renewal - CloudLedger Software",
        "amount": "-800.00",
        "method": "CHECK",
        "check_number": "3108",
        "account": "1010",
        "counter_account": "6510",
        "counterparty": "CloudLedger Software",
        "recon_status": "unmatched",
        "item_id": None,
    }


async def test_statement_before_any_run_shows_the_raw_difference(client: AsyncClient):
    response = await client.get("/api/v1/statement", params={"dataset": DATASET})
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] is None
    assert body["bank"] == {"closing_balance": "48547.99", "lines": [], "adjusted_balance": "48547.99"}
    assert body["book"] == {"closing_balance": "47683.90", "lines": [], "adjusted_balance": "47683.90"}
    assert body["raw_difference"] == "864.09"
    assert body["unreconciled_difference"] == "864.09"


async def test_statement_with_empty_run_id_uses_the_latest_run(client: AsyncClient):
    response = await client.get("/api/v1/statement?run_id=")
    assert response.status_code == 200
    assert response.json()["unreconciled_difference"] == "864.09"


async def test_malformed_query_is_422_with_the_api_error_shape(client: AsyncClient):
    response = await client.get("/api/v1/bank-transactions?from=2026-13-01")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert response.json()["detail"]["message"]


async def test_statement_for_unknown_run_is_404(client: AsyncClient):
    response = await client.get("/api/v1/statement", params={"run_id": "6f1c2a9e-3b7d-4c51-9a8e-2d4f0b1e7a10"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "run_not_found"


RUN_ID = "6f1c2a9e-3b7d-4c51-9a8e-2d4f0b1e7a10"


class OneRunStore(CsvStore):
    """The CSV dataset plus one run whose items cover a check match and a bank fee."""

    async def run_items(self, dataset_id, run_id):
        if run_id not in (None, RUN_ID):
            return await super().run_items(dataset_id, run_id)
        return RunItems(
            run_id=RUN_ID,
            items=(
                ItemRef(id="item-1", status="matched", bank_ids=("BANK005",), gl_ids=("GL008",)),
                ItemRef(id="item-2", status="needs_approval", bank_ids=("BANK032",), gl_ids=()),
            ),
        )


@pytest.fixture
def one_run(app):
    app.dependency_overrides[get_read_store] = lambda: OneRunStore(DATASET)


async def test_rows_take_status_and_item_from_the_latest_run(client: AsyncClient, one_run):
    bank = {r["txn_id"]: r for r in (await client.get("/api/v1/bank-transactions")).json()}
    gl = {r["entry_id"]: r for r in (await client.get("/api/v1/gl-entries")).json()}
    assert (bank["BANK005"]["recon_status"], bank["BANK005"]["item_id"]) == ("matched", "item-1")
    assert (bank["BANK032"]["recon_status"], bank["BANK032"]["item_id"]) == ("needs_approval", "item-2")
    assert (gl["GL008"]["recon_status"], gl["GL008"]["item_id"]) == ("matched", "item-1")
    assert (bank["BANK001"]["recon_status"], bank["BANK001"]["item_id"]) == ("unmatched", None)


async def test_statement_names_the_run_it_reads(client: AsyncClient, one_run):
    body = (await client.get("/api/v1/statement")).json()
    assert body["run_id"] == RUN_ID
    assert body["raw_difference"] == "864.09"


class FeeApprovedStore(CsvStore):
    """A run where the bank fee's entry (DR 6800 / CR 1010 25.00) has been approved."""

    async def run_items(self, dataset_id, run_id):
        entry = ProposedEntry(debit_account="6800", credit_account="1010", amount=Decimal("25.00"), memo="Bank fee")
        return RunItems(
            run_id=RUN_ID,
            items=(
                ItemRef(id="item-2", status="approved", kind="bank_fee_missing_in_gl",
                        bank_ids=("BANK032",), gl_ids=(), entry=entry),
            ),
        )


async def test_statement_applies_the_run_items(app, client: AsyncClient):
    app.dependency_overrides[get_read_store] = lambda: FeeApprovedStore(DATASET)
    body = (await client.get("/api/v1/statement")).json()
    assert body["book"]["lines"] == [{
        "item_id": "item-2", "kind": "bank_fee_missing_in_gl", "label": "Bank fee", "amount": "-25.00",
        "status": "approved", "applied": True, "bank_ids": ["BANK032"], "gl_ids": [],
    }]
    assert body["book"]["adjusted_balance"] == "47658.90"
    assert body["unreconciled_difference"] == "889.09"


@pytest.mark.parametrize(
    ("path", "fixture"),
    [
        ("/api/v1/datasets", "datasets.json"),
        ("/api/v1/bank-transactions", "bank-transactions.json"),
        ("/api/v1/gl-entries", "gl-entries.json"),
        ("/api/v1/statement", "statement.json"),
    ],
)
async def test_responses_match_the_ui_fixtures(client: AsyncClient, path, fixture):
    path_on_disk = FIXTURES / fixture
    if not path_on_disk.exists():
        pytest.skip(f"{path_on_disk} not found")
    assert (await client.get(path)).json() == json.loads(path_on_disk.read_text())


@pytest.mark.parametrize("path", ["/api/v1/bank-transactions", "/api/v1/gl-entries", "/api/v1/statement"])
async def test_unknown_dataset_is_404(client: AsyncClient, path):
    response = await client.get(path, params={"dataset": "nope"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "dataset_not_found"


@pytest.mark.parametrize("path", ["/api/v1/bank-transactions", "/api/v1/gl-entries"])
async def test_reversed_date_range_is_422(client: AsyncClient, path):
    response = await client.get(path, params={"from": "2026-10-05", "to": "2026-10-01"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_date_range"
