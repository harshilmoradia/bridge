import json
from pathlib import Path

import pytest

from app.schemas.runs import Run

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "fixtures"


@pytest.mark.parametrize("name", ["run-running.json", "run-completed.json"])
def test_fixture_matches_contract(name):
    path = FIXTURES / name
    if not path.exists():  # fixtures live outside backend/, absent in the Docker image
        pytest.skip(f"{path} not found")
    run = Run.model_validate(json.loads(path.read_text()))
    assert run.status in {"running", "completed"}
    assert (run.result is not None) == (run.status == "completed")
