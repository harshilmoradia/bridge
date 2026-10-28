"""Run a pipeline on demo-data/ and score it against evals/ground_truth.json.

    uv run --project backend python -m evals.run_eval --pipeline rules     # from the repo root

Writes evals/results/<timestamp>-<pipeline>.json and a .md table beside it, and prints the table.
"""

import argparse
import asyncio
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # allow `python evals/run_eval.py` as well as `-m`
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import BaseModel, ConfigDict, field_serializer  # noqa: E402

from app.recon.store import CsvStore  # noqa: E402
from evals.pipelines import PIPELINES  # noqa: E402
from evals.scoring import Ratio, Scores, load_ground_truth, score  # noqa: E402

DEFAULT_DATASET = "northbrook-2026-10"
RESULTS_DIR = REPO_ROOT / "evals" / "results"


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    pipeline: str
    dataset: str
    created_at: datetime
    git_sha: str | None
    scores: Scores

    @field_serializer("created_at")
    def _utc(self, value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe_commit(sha: str, porcelain: str) -> str | None:
    """The short sha, marked `-dirty` when the checkout has changes the commit does not hold."""
    sha = sha.strip()
    if not sha:
        return None
    return f"{sha}-dirty" if porcelain.strip() else sha


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_sha() -> str | None:
    return describe_commit(_git("rev-parse", "--short", "HEAD"), _git("status", "--porcelain"))


async def evaluate(pipeline: str, dataset_id: str = DEFAULT_DATASET, now: datetime | None = None) -> EvalReport:
    dataset = await CsvStore(dataset_id).dataset(dataset_id)
    if dataset is None:
        raise ValueError(f"Unknown dataset {dataset_id}")
    result = await PIPELINES[pipeline](dataset)
    return EvalReport(
        pipeline=pipeline,
        dataset=dataset_id,
        created_at=now or datetime.now(UTC),
        git_sha=_git_sha(),
        scores=score(dataset, load_ground_truth(), result),
    )


def fmt_ratio(r: Ratio) -> tuple[str, str]:
    return f"{r.hit}/{r.total}", "N/A" if r.value is None else f"{r.value * 100:.1f}%"


def _money(d: Decimal) -> str:
    return f"{d:.2f}"


def to_markdown(report: EvalReport) -> str:
    s = report.scores
    rows = [
        ("Match precision", *fmt_ratio(s.match_precision)),
        ("Match recall", *fmt_ratio(s.match_recall)),
        ("Kind accuracy", *fmt_ratio(s.kind_accuracy)),
        ("Correct escalations", *fmt_ratio(s.correct_escalations)),
        ("False auto-resolutions", str(len(s.false_auto_resolutions)), "must be 0"),
        ("Entry correctness", *fmt_ratio(s.entry_correctness)),
        ("Escalated (all)", str(s.escalated), ""),
        ("Left undecided", str(s.unresolved), ""),
        ("Rows no item cites", str(s.uncovered_rows), "must be 0"),
        ("Final difference (escalations pending)", _money(s.final_difference),
         f"expected {_money(s.expected_difference)} after approvals"),
        ("Difference after approving escalations", _money(s.difference_after_approvals),
         f"expected {_money(s.expected_difference)}"),
    ]
    sha = f", commit `{report.git_sha}`" if report.git_sha else ""
    created = report.model_dump(mode="json")["created_at"]
    lines = [
        f"## Eval: `{report.pipeline}` on `{report.dataset}` ({created}{sha})",
        "",
        "| Metric | Count | Score |",
        "|---|---|---|",
        *(f"| {name} | {count} | {value} |" for name, count, value in rows),
        "",
        "| Kind | Correct |",
        "|---|---|",
        *(f"| {kind} | {r.hit}/{r.total} |" for kind, r in s.kind_accuracy_by_kind.items()),
    ]
    if s.false_auto_resolutions:
        lines += ["", "False auto-resolutions:", ""]
        lines += [
            f"- {f.resolution} `{f.kind}` bank {list(f.bank_ids)} GL {list(f.gl_ids)} (answer key: {f.expected or 'no such item'})"
            for f in s.false_auto_resolutions
        ]
    return "\n".join(lines) + "\n"


def write_results(report: EvalReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report.created_at.astimezone(UTC):%Y%m%dT%H%M%SZ}-{report.pipeline}"
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pipeline", choices=sorted(PIPELINES), default="rules")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    report = asyncio.run(evaluate(args.pipeline, args.dataset, now))
    json_path, md_path = write_results(report, args.out)
    print(md_path.read_text(encoding="utf-8"), end="")
    print(f"\nWrote {json_path} and {md_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
