"""Load a dataset from demo-data/ CSVs, so tests and evals run without a database."""

import csv
import json
from pathlib import Path

from app.recon.models import Balances, BankTxn, Dataset, GlEntry

DATA_DIR = Path(__file__).resolve().parents[3] / "demo-data"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_dataset(dataset_id: str, data_dir: Path = DATA_DIR) -> Dataset:
    return Dataset(
        id=dataset_id,
        # Model fields pick what they need; extra keys (sign_convention, currency) are ignored.
        balances=Balances(**json.loads((data_dir / "balances.json").read_text(encoding="utf-8"))),
        bank=tuple(BankTxn(**r) for r in _rows(data_dir / "bank_statement.csv")),
        gl=tuple(GlEntry(**r) for r in _rows(data_dir / "gl_entries.csv")),
    )
