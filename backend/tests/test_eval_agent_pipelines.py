"""E-02/E-03: the agent pipeline as eval adapters (`tiered`, and `nano`, `super`, `ultra` forced onto one
tier), with usage capture and an estimated cost. All on the stub provider (the B-09 Oracle).

Expected scores come from the answer key's worked example (test_agents_pipeline.py): the scripted run
escalates five items with correct drafts and auto-resolves nothing wrongly, so the difference after
approvals is 0.00.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.llm import LLMClient
from evals import pipelines, run_eval
from evals.pricing import PRICES_PER_MILLION, estimate_cost
from evals.scoring import load_ground_truth, score
from tests.test_agents_pipeline import DATASET, Oracle, client_for

D = Decimal
NOW = datetime(2026, 10, 29, 1, 2, 3, tzinfo=UTC)


# --- the eval-only tier override ---------------------------------------------------------------

async def test_a_forced_client_sends_every_tier_to_one_model() -> None:
    client, provider = client_for(lambda _m, _model: "ok")
    forced = client.forced("nano")
    for tier in ("nano", "super", "ultra"):
        await forced.complete_text(tier, [])
    assert [m for m, _ in provider.calls] == ["m-nano"] * 3


async def test_the_default_client_keeps_its_tier_map() -> None:
    client, provider = client_for(lambda _m, _model: "ok")
    client.forced("ultra")  # a copy: the original is untouched
    for tier in ("nano", "super", "ultra"):
        await client.complete_text(tier, [])
    assert [m for m, _ in provider.calls] == ["m-nano", "m-super", "m-ultra"]
    assert client.force_tier is None


# --- prices -------------------------------------------------------------------------------------

def test_cost_is_tokens_times_the_per_million_price():
    # Nano 0.06 in / 0.24 out, Super 0.30 in / 0.90 out per 1M tokens:
    # 1M nano in = 0.06, 0.5M nano out = 0.12, 0.2M super in = 0.06, 0.1M super out = 0.09.
    assert PRICES_PER_MILLION["nano"] == (D("0.06"), D("0.24"))
    assert PRICES_PER_MILLION["super"] == (D("0.30"), D("0.90"))
    assert estimate_cost({"nano": (1_000_000, 500_000), "super": (200_000, 100_000)}) == D("0.330000")


# --- the adapters -------------------------------------------------------------------------------

def _pipeline(name: str, oracle=None):
    client, provider = client_for(oracle or Oracle())
    return pipelines.agent_pipeline(pipelines.TIERS[name], make_client=lambda: client), provider


async def test_tiered_runs_the_agents_and_meets_the_gate() -> None:
    run, provider = _pipeline("tiered")
    result = await run(DATASET)
    scores = score(DATASET, load_ground_truth(), result)
    assert scores.false_auto_resolutions == []
    assert (scores.correct_escalations.hit, scores.correct_escalations.total) == (5, 5)
    assert scores.difference_after_approvals == scores.expected_difference == D("0.00")
    assert {m for m, _ in provider.calls} == {"m-nano", "m-super"}  # Ultra only on a failed retry
    usage = result.usage
    assert usage.calls == len(provider.calls)
    assert usage.tokens_in > 0 and usage.tokens_out > 0
    assert set(usage.tokens_by_tier) == {"nano", "super"}
    assert usage.tokens_in == sum(i for i, _ in usage.tokens_by_tier.values())
    assert usage.cost_usd == estimate_cost(usage.tokens_by_tier)


@pytest.mark.parametrize("tier", ["nano", "super", "ultra"])
async def test_a_forced_pipeline_uses_one_tier(tier) -> None:
    run, provider = _pipeline(tier)
    result = await run(DATASET)
    assert {m for m, _ in provider.calls} == {f"m-{tier}"}
    assert set(result.usage.tokens_by_tier) == {tier}


def test_every_ui_pipeline_is_registered():
    assert {"rules", "nano", "super", "tiered", "ultra"} <= set(pipelines.PIPELINES)


# --- the report carries latency, tokens and cost --------------------------------------------------

def test_the_report_carries_latency_tokens_and_cost(tmp_path, monkeypatch):
    run, _ = _pipeline("tiered")
    monkeypatch.setitem(pipelines.PIPELINES, "tiered", run)
    monkeypatch.setitem(run_eval.PIPELINES, "tiered", run)
    assert run_eval.main(["--pipeline", "tiered", "--out", str(tmp_path)], now=NOW) == 0
    report = json.loads((tmp_path / "20261029T010203Z-tiered.json").read_text())
    assert isinstance(report["latency_ms"], int) and report["latency_ms"] >= 0
    assert isinstance(report["tokens_in"], int) and report["tokens_in"] > 0
    assert isinstance(report["tokens_out"], int) and report["tokens_out"] > 0
    assert isinstance(report["cost_usd"], str) and D(report["cost_usd"]) > 0
    assert report["scores"]["difference_after_approvals"] == "0.00"
    assert report["scores"]["expected_difference"] == "0.00"
    table = (tmp_path / "20261029T010203Z-tiered.md").read_text()
    assert "| Latency |" in table and "| Estimated cost (USD) |" in table


def test_the_rules_report_has_latency_but_no_tokens(tmp_path):
    run_eval.main(["--pipeline", "rules", "--out", str(tmp_path)], now=NOW)
    report = json.loads((tmp_path / "20261029T010203Z-rules.json").read_text())
    assert isinstance(report["latency_ms"], int)
    assert (report["tokens_in"], report["tokens_out"], report["cost_usd"]) == (None, None, None)


def test_llm_client_has_no_forced_tier_by_default():
    from app.core.config import Settings
    from app.llm.client import get_llm_client
    assert get_llm_client(Settings(_env_file=None)).force_tier is None
    assert isinstance(get_llm_client(Settings(_env_file=None)), LLMClient)


# --- calls, per-tier calls and step summaries in the artifact (Quinn round 2) ----------------------

def _report_for(name, tmp_path, monkeypatch):
    run, provider = _pipeline(name)
    monkeypatch.setitem(run_eval.PIPELINES, name, run)
    assert run_eval.main(["--pipeline", name, "--out", str(tmp_path)], now=NOW) == 0
    stem = f"20261029T010203Z-{name}"
    return (json.loads((tmp_path / f"{stem}.json").read_text()), (tmp_path / f"{stem}.md").read_text(),
            provider)


def test_the_report_counts_model_calls_in_total_and_per_tier(tmp_path, monkeypatch):
    report, table, provider = _report_for("tiered", tmp_path, monkeypatch)
    assert report["calls"] == len(provider.calls)
    by_model = {}
    for model, _ in provider.calls:
        by_model[model] = by_model.get(model, 0) + 1
    assert report["calls_by_tier"] == {"nano": by_model["m-nano"], "super": by_model["m-super"]}
    assert f"| Model calls | {len(provider.calls)} |" in table


def test_the_report_carries_the_agent_step_summaries_without_row_text(tmp_path, monkeypatch):
    report, table, _ = _report_for("tiered", tmp_path, monkeypatch)
    steps = {s["id"]: s for s in report["steps"]}
    assert list(steps) == ["match-rules", "match-fuzzy", "classify", "resolve", "review", "decide"]
    # The worked example (test_agents_pipeline.py): 5 escalations, nothing on Ultra, all checks pass.
    assert steps["resolve"]["summary"].endswith("0 on Ultra")
    assert steps["review"]["summary"] == "0 failed checks, 0 critic calls failed"
    assert steps["resolve"]["calls"] > 0 and steps["resolve"]["tier"] == "super"
    text = json.dumps(report["steps"])
    assert not any(t in text for t in ("BANK", "GL0", "GL1", "MONTHLY", "ZELLE"))  # ids and counts only
    assert "| resolve |" in table


def test_only_a_placeholder_priced_tier_gets_the_price_note(tmp_path, monkeypatch):
    nano, nano_md, _ = _report_for("nano", tmp_path, monkeypatch)
    assert "price_placeholder_tiers" not in nano and "placeholder" not in nano_md.lower()
    ultra, ultra_md, _ = _report_for("ultra", tmp_path, monkeypatch)
    assert ultra["price_placeholder_tiers"] == ["ultra"]
    assert "placeholder" in ultra_md.lower()


async def test_the_models_off_floor_makes_no_calls_and_keeps_the_gate(monkeypatch) -> None:
    # The floor builds its own unavailable client; reading settings would reach the configured model.
    monkeypatch.setattr(pipelines, "get_llm_client", lambda *_a: pytest.fail("models_off read the settings client"))
    result = await pipelines.PIPELINES["models_off"](DATASET)
    scores = score(DATASET, load_ground_truth(), result)
    assert result.usage.calls == 0 and result.usage.cost_usd == D("0")
    assert scores.false_auto_resolutions == []
    assert (scores.correct_escalations.hit, scores.correct_escalations.total) == (5, 5)
    assert scores.difference_after_approvals == scores.expected_difference == D("0.00")
