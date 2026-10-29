"""docs/fixtures/ must match the v1 schemas exactly: the UI mocks are built from them."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.schemas.reads import BankTransactionOut, DatasetOut, GlEntryOut, Statement
from app.schemas.runs import AuditEntry, DecisionResponse, DemoResetResponse, Item, Rule, Run

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "fixtures"

CONTRACT = {
    "datasets.json": list[DatasetOut],
    "bank-transactions.json": list[BankTransactionOut],
    "gl-entries.json": list[GlEntryOut],
    "statement.json": Statement,
    "run-running.json": Run,
    "run-completed.json": Run,
    "items.json": list[Item],
    "decision-response.json": DecisionResponse,
    "rules.json": list[Rule],
    "demo-reset.json": DemoResetResponse,
    "run-audit.json": list[AuditEntry],
}


def _fixture(name: str):
    path = FIXTURES / name
    if not path.exists():  # fixtures live outside backend/, absent in the Docker image
        pytest.skip(f"{path} not found")
    return json.loads(path.read_text())


@pytest.mark.parametrize("name", sorted(CONTRACT))
def test_fixture_round_trips_through_contract(name):
    raw = _fixture(name)
    adapter = TypeAdapter(CONTRACT[name])
    # Exact round trip: money stays a 2-dp string, and no field is missing or extra.
    assert json.loads(adapter.dump_json(adapter.validate_python(raw))) == raw


def test_run_fixtures_cover_both_states():
    running = Run.model_validate(_fixture("run-running.json"))
    completed = Run.model_validate(_fixture("run-completed.json"))
    assert running.status == "running" and running.report is None
    assert completed.status == "completed" and completed.report


def test_statement_fixture_shows_raw_difference():
    statement = _fixture("statement.json")
    assert statement["run_id"] is None
    assert statement["raw_difference"] == "864.09"
    assert statement["unreconciled_difference"] == "864.09"


def test_row_fixtures_hold_the_whole_dataset():
    assert len(_fixture("bank-transactions.json")) == 112
    assert len(_fixture("gl-entries.json")) == 114
