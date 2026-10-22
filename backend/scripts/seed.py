"""Load demo-data/ into bank_transactions, gl_entries and balances.

Idempotent: rows are upserted by primary key, and rows for the dataset that are
no longer in the files are deleted, all in one transaction.

    cd backend && uv run python -m scripts.seed [--dataset ID] [--data-dir PATH]
"""

import argparse
import csv
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "demo-data"

BANK_COLS = ["txn_id", "posted_date", "description", "amount", "type", "check_number", "running_balance"]
GL_COLS = ["entry_id", "date", "description", "amount", "method", "check_number", "account", "counter_account", "counterparty"]
BALANCE_COLS = [
    "company", "cash_account", "period_start", "period_end",
    "bank_opening_balance", "bank_closing_balance", "gl_opening_balance", "gl_closing_balance",
]
DATE_COLS = {"posted_date", "date", "period_start", "period_end"}
MONEY_COLS = {"amount", "running_balance"} | {c for c in BALANCE_COLS if c.endswith("_balance")}


def _convert(col: str, value: str) -> object:
    if value == "":
        return None
    if col in DATE_COLS:
        return date.fromisoformat(value)
    if col in MONEY_COLS:
        return Decimal(value)
    return value


def _read_csv(path: Path, cols: list[str], dataset: str) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            {"dataset": dataset} | {c: _convert(c, row[c]) for c in cols}
            for row in csv.DictReader(f)
        ]


def load_bank(dataset: str, data_dir: Path = DATA_DIR) -> list[dict]:
    return _read_csv(data_dir / "bank_statement.csv", BANK_COLS, dataset)


def load_gl(dataset: str, data_dir: Path = DATA_DIR) -> list[dict]:
    return _read_csv(data_dir / "gl_entries.csv", GL_COLS, dataset)


def load_balances(dataset: str, data_dir: Path = DATA_DIR) -> dict:
    raw = json.loads((data_dir / "balances.json").read_text(encoding="utf-8"))
    return {"dataset": dataset} | {c: _convert(c, raw[c]) for c in BALANCE_COLS}


def _upsert_sql(table: str, cols: list[str], key: list[str]) -> str:
    all_cols = ["dataset", *cols]
    updates = ", ".join(f"{c} = excluded.{c}" for c in all_cols if c not in key)
    return (
        f"insert into {table} ({', '.join(all_cols)}) "
        f"values ({', '.join(f'%({c})s' for c in all_cols)}) "
        f"on conflict ({', '.join(key)}) do update set {updates}"
    )


def seed(database_url: str, dataset: str, data_dir: Path = DATA_DIR) -> dict[str, int]:
    import psycopg

    bank = load_bank(dataset, data_dir)
    gl = load_gl(dataset, data_dir)
    balances = load_balances(dataset, data_dir)

    # prepare_threshold=None: the Supabase transaction pooler has no prepared statements.
    with psycopg.connect(database_url, prepare_threshold=None) as conn, conn.cursor() as cur:
        cur.executemany(_upsert_sql("bank_transactions", BANK_COLS, ["dataset", "txn_id"]), bank)
        cur.execute(
            "delete from bank_transactions where dataset = %s and txn_id <> all(%s)",
            (dataset, [r["txn_id"] for r in bank]),
        )
        cur.executemany(_upsert_sql("gl_entries", GL_COLS, ["dataset", "entry_id"]), gl)
        cur.execute(
            "delete from gl_entries where dataset = %s and entry_id <> all(%s)",
            (dataset, [r["entry_id"] for r in gl]),
        )
        cur.execute(_upsert_sql("balances", BALANCE_COLS, ["dataset"]), balances)

        counts = {}
        for table in ("bank_transactions", "gl_entries", "balances"):
            cur.execute(f"select count(*) from {table} where dataset = %s", (dataset,))
            counts[table] = cur.fetchone()[0]
    return counts


def main() -> int:
    from app.core.config import get_settings

    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", default=settings.dataset)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    if not settings.database_url:
        print("DATABASE_URL is not set (see .env.example)", file=sys.stderr)
        return 1
    counts = seed(settings.database_url, args.dataset, args.data_dir)
    print(" / ".join(f"{table}: {n}" for table, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
