"""report (Ultra): a markdown narrative from computed numbers, checked by code.

Expected numbers come from demo-data (bank closing 48547.99, book closing 47683.90, raw
difference 864.09, 112 bank rows, 114 GL rows) and the worked example in test_agents_pipeline.py
(outstanding check GL034 325.00, deposit in transit GL114 3275.40, fee entry 25.00).
"""

import json
from decimal import Decimal

from app.agents.report import numbers_in, report_facts, template_report, unsupported_numbers, write_report
from app.core.errors import LLMUnavailableError
from app.recon.models import ProposedEntry
from app.recon.statement import build_statement
from app.recon.store import ItemRef
from app.schemas.runs import RunCounts
from tests.test_agents_pipeline import DATASET, agent, client_for, user_json

D = Decimal
COUNTS = RunCounts(bank_transactions=112, gl_entries=114, items=115, matched=106, auto_resolved=2,
                   reconciling_item=2, needs_approval=5)
ITEMS = (
    ItemRef(id="i1", status="reconciling_item", bank_ids=(), gl_ids=("GL034",), kind="outstanding_check"),
    ItemRef(id="i2", status="reconciling_item", bank_ids=(), gl_ids=("GL114",), kind="deposit_in_transit"),
    ItemRef(id="i3", status="needs_approval", bank_ids=("BANK032",), gl_ids=(), kind="bank_fee_missing_in_gl",
            entry=ProposedEntry(debit_account="6800", credit_account="1010", amount=D("25.00"),
                                memo="MONTHLY SERVICE FEE ACCT 000123456789")),
    ItemRef(id="i4", status="matched", bank_ids=("BANK002",), gl_ids=("GL002",), kind="exact"),
)


def facts() -> dict:
    return report_facts(build_statement(DATASET, "r1", ITEMS), COUNTS, ITEMS)


def test_numbers_are_read_whatever_their_formatting():
    text = "Bank $48,547.99, book (47,683.90), diff -864.09; 112 rows on Oct 1-31."
    assert numbers_in(text) == [D("48547.99"), D("47683.90"), D("864.09"), D("112"), D("1"), D("31")]


def test_facts_carry_the_computed_numbers_and_no_row_text():
    f = facts()
    assert (f["bank"]["closing_balance"], f["book"]["closing_balance"], f["raw_difference"]) == (
        "48547.99", "47683.90", "864.09")
    assert f["counts"]["needs_approval"] == 5
    assert {(line["kind"], line["amount"]) for line in f["bank"]["lines"]} == {
        ("outstanding_check", "-325.00"), ("deposit_in_transit", "3275.40")}
    assert f["book"]["pending_total"] == "-25.00"  # the unapproved fee entry
    dumped = json.dumps(f)
    assert "SERVICE FEE" not in dumped and "000123456789" not in dumped  # entry memos stay out
    assert "BANK032" not in dumped and "GL034" not in dumped  # and so do row ids


def test_numbers_in_the_facts_pass_and_others_are_named():
    f = facts()
    assert unsupported_numbers("Bank 48,547.99 vs book $47,683.90: 864.09 apart. 5 to approve.", f) == []
    assert unsupported_numbers("Raw difference 864.90 across 7 items.", f) == ["864.90", "7"]


def test_the_template_report_passes_its_own_check():
    f = facts()
    text = template_report(f)
    assert "864.09" in text and "48,547.99" in text
    assert unsupported_numbers(text, f) == []


class Writer:
    """Scripted Ultra: returns each reply in turn and keeps what it was sent."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages, model):
        self.calls.append((agent(messages), model, messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


async def test_a_report_with_only_given_numbers_is_kept():
    writer = Writer("## October\n\nBank 48,547.99, book 47,683.90, raw difference 864.09.")
    client, _ = client_for(writer)
    out = await write_report(client, facts())
    assert out.source == "model" and out.markdown.startswith("## October")
    assert [(a, m) for a, m, _ in writer.calls] == [("report", "m-ultra")]
    assert [s.tier for s in out.stats] == ["ultra"]
    assert user_json(writer.calls[0][2])["raw_difference"] == "864.09"


async def test_an_invented_number_gets_one_repair():
    writer = Writer("Raw difference 846.09.", "Raw difference 864.09.")
    client, _ = client_for(writer)
    out = await write_report(client, facts())
    assert (out.source, out.markdown) == ("repaired", "Raw difference 864.09.")
    assert len(out.stats) == 2
    assert "846.09" in writer.calls[1][2][-1].content  # the repair names the bad number


async def test_two_bad_drafts_fall_back_to_the_template():
    writer = Writer("Raw difference 846.09.", "Still 999.99.")
    client, _ = client_for(writer)
    f = facts()
    out = await write_report(client, f)
    assert out.source == "template" and out.markdown == template_report(f)
    assert out.unsupported == ("999.99",) and len(out.stats) == 2


async def test_a_model_outage_falls_back_to_the_template():
    client, _ = client_for(Writer(LLMUnavailableError("down"), LLMUnavailableError("down")))  # client retries once
    f = facts()
    out = await write_report(client, f)
    assert (out.source, out.markdown, out.stats) == ("template", template_report(f), [])


async def test_report_fallback_logs_safe_provider_diagnostics(caplog):
    import logging

    client, _ = client_for(Writer(
        LLMUnavailableError("private provider detail", diagnostic_code="request_timeout"),
        LLMUnavailableError("private provider detail", diagnostic_code="request_timeout"),
    ))

    with caplog.at_level(logging.WARNING, logger="app.agents.report"):
        result = await write_report(client, facts(), run_id="run-diagnostic-1")

    assert result.source == "template"
    record = next(r for r in caplog.records if "Ultra report request failed" in r.getMessage())
    assert record.run_id == "run-diagnostic-1"
    assert record.diagnostic_code == "request_timeout"
    assert record.error_code == "llm_unavailable"
    assert record.error_type == "LLMUnavailableError"
    assert record.report_attempt == 1
    assert "diagnostic_code=request_timeout" in record.getMessage()
    assert "run_id=run-diagnostic-1" in record.getMessage()
    assert "private provider detail" not in caplog.text


# Number words and scale words: the check cannot be passed by spelling a number out.

def test_a_spelled_out_scale_is_unsupported():
    f = facts()
    assert "thousand" in unsupported_numbers("About four thousand dollars is still open.", f)
    assert unsupported_numbers("A gap of eight hundred sixty-four dollars.", f)  # 864 is not 864.09


def test_a_spelled_out_count_in_the_facts_passes():
    f = {**facts(), "counts": {**facts()["counts"], "unknown": 3}}
    assert unsupported_numbers("Three unknown items need a look.", f) == []
    assert unsupported_numbers("Forty-two items need a look.", f) == ["Forty-two"]


def test_number_words_are_read_as_numbers():
    assert numbers_in("three items, a dozen rows, twenty-one checks, zero gaps") == [
        D("3"), D("12"), D("21"), D("0")]


def test_money_must_match_a_money_fact_not_a_count():
    f = facts()  # 2 is a count (auto_resolved, reconciling_item); no fact amount is 2.00
    assert unsupported_numbers("2 reconciling items", f) == []
    assert unsupported_numbers("a $2 charge", f) == ["$2"]
    assert unsupported_numbers("a 2.00 charge", f) == ["2.00"]


def test_a_dollar_amount_equal_only_to_a_count_is_unsupported():
    f = {**facts(), "counts": {**facts()["counts"], "unknown": 30}}
    assert unsupported_numbers("a $30.00 charge", f) == ["$30.00"]


def test_abbreviated_and_scaled_amounts_are_unsupported():
    f = facts()  # 3 is not needed: the suffix alone rejects
    assert unsupported_numbers("about $3k left", f) == ["$3k"]
    assert unsupported_numbers("about 2 thousand left", f) == ["2 thousand"]
    assert unsupported_numbers("about 5m left", f) == ["5m"]
    assert unsupported_numbers("about 1bn left", f) == ["1bn"]
