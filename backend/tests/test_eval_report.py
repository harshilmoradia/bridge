"""E-01 report: `evals/run_eval.py` writes <timestamp>-<pipeline>.json and a markdown table beside it."""

import json
from datetime import UTC, datetime

from evals import run_eval

NOW = datetime(2026, 10, 27, 9, 30, 5, tzinfo=UTC)


def test_main_writes_json_and_markdown_and_prints_the_table(tmp_path, capsys):
    assert run_eval.main(["--pipeline", "rules", "--out", str(tmp_path)], now=NOW) == 0

    json_path = tmp_path / "20261027T093005Z-rules.json"
    md_path = tmp_path / "20261027T093005Z-rules.md"
    assert sorted(p.name for p in tmp_path.iterdir()) == [json_path.name, md_path.name]

    report = json.loads(json_path.read_text())
    assert (report["pipeline"], report["dataset"], report["created_at"]) == (
        "rules", "northbrook-2026-10", "2026-10-27T09:30:05Z"
    )
    scores = report["scores"]
    assert scores["final_difference"] == "864.10"  # money stays a decimal string
    assert scores["expected_difference"] == "0.00"
    assert scores["match_precision"] == {"hit": 105, "total": 105, "value": 1.0}
    assert scores["false_auto_resolutions"] == []

    table = md_path.read_text()
    assert table in capsys.readouterr().out
    assert "| Match precision | 105/105 | 100.0% |" in table
    assert "| Correct escalations | 0/5 | 0.0% |" in table
    assert "| False auto-resolutions | 0 | must be 0 |" in table
    assert "| Final difference (escalations pending) | 864.10 | expected 0.00 after approvals |" in table


def test_the_table_shows_rows_no_item_cites(tmp_path):
    run_eval.main(["--pipeline", "rules", "--out", str(tmp_path)], now=NOW)
    assert "| Rows no item cites | 0 | must be 0 |" in (tmp_path / "20261027T093005Z-rules.md").read_text()


def test_a_commit_with_local_changes_is_marked_dirty():
    assert run_eval.describe_commit("15432f1", " M evals/scoring.py\n") == "15432f1-dirty"
    assert run_eval.describe_commit("15432f1", "") == "15432f1"
    assert run_eval.describe_commit("", "") is None  # not a git checkout


def test_a_ratio_with_nothing_to_score_shows_na():
    assert run_eval.fmt_ratio(run_eval.Ratio(hit=0, total=0)) == ("0/0", "N/A")
