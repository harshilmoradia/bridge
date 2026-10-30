"""report (Ultra): the run's narrative, written from numbers code has already computed.

The model sees only `report_facts`: the statement's balances, each statement line's kind, amount
and status, the run counts and item counts by kind. No row ids, descriptions or entry memos.
Code then checks the markdown: every number in it must be one of the facts' numbers, compared by
absolute value whatever the formatting ($, commas, minus, parentheses). One repair retry names
the numbers that failed; after that, or when the model is down, code writes `template_report`.
"""

import json
import logging
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.agents.prompts import system_prompt
from app.core.errors import AppError
from app.llm import CallStats, LLMClient
from app.recon.store import ItemRef
from app.schemas.chat import ChatMessage
from app.schemas.common import CENT
from app.schemas.reads import Statement, StatementSide
from app.schemas.runs import RunCounts

ReportSource = Literal["model", "repaired", "template"]
logger = logging.getLogger(__name__)

# A number as written: an optional "$", the digits (thousands-grouped first, so "48,547.99" reads as
# one number), then an optional scale ("3k", "2 thousand") that the check always rejects.
_NUMBER = re.compile(
    r"(?P<dollar>\$)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale>(?:k|K|m|M|bn)\b|\s+(?:thousand|million|billion)\b)?")
_UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
          "fifteen sixteen seventeen eighteen nineteen twenty").split()
_TENS = {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_VALUE = {w: n for n, w in enumerate(_UNITS)} | _TENS | {"dozen": 12}
_SCALE_WORDS = ("hundred", "thousand", "million", "billion")  # never allowed: "four thousand" hides a figure
_WORD = re.compile(
    r"\b(?:(?P<tens>twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)-(?P<unit>one|two|three|four|five|"
    r"six|seven|eight|nine)|(?P<word>" + "|".join(sorted(_WORD_VALUE, key=len, reverse=True)) + ")"
    r"|(?P<scale>" + "|".join(_SCALE_WORDS) + r"))\b", re.IGNORECASE)


@dataclass(frozen=True)
class _Token:
    raw: str  # as written, commas dropped
    value: Decimal | None  # None: a scale, which no fact can support
    money: bool  # a decimal point or "$": it must match a money fact, not a count


def _tokens(text: str) -> list[_Token]:
    found: list[tuple[int, _Token]] = []
    taken: list[range] = []  # "2 thousand" is one token: its word is not read again
    for m in _NUMBER.finditer(text):
        taken.append(range(m.start(), m.end()))
        raw = m.group().replace(",", "")
        if m.group("scale"):
            found.append((m.start(), _Token(raw, None, True)))
        else:
            num = m.group("num").replace(",", "")
            found.append((m.start(), _Token(raw, Decimal(num), bool(m.group("dollar")) or "." in num)))
    for m in _WORD.finditer(text):
        raw = m.group()
        if any(m.start() in span for span in taken):
            continue
        if m.group("scale"):
            value = None
        elif m.group("tens"):
            value = Decimal(_WORD_VALUE[m.group("tens").lower()] + _UNITS.index(m.group("unit").lower()))
        else:
            value = Decimal(_WORD_VALUE[m.group("word").lower()])
        found.append((m.start(), _Token(raw, value, False)))
    return [t for _, t in sorted(found, key=lambda pair: pair[0])]


@dataclass(frozen=True)
class ReportResult:
    markdown: str
    source: ReportSource
    stats: list[CallStats] = field(default_factory=list)
    unsupported: tuple[str, ...] = ()  # numbers in the last rejected draft that the facts lack


def _money(d: Decimal) -> str:
    return str(d.quantize(CENT))


def _side(side: StatementSide) -> dict[str, Any]:
    pending = sum((line.amount for line in side.lines if not line.applied), Decimal("0"))
    return {
        "closing_balance": _money(side.closing_balance),
        "adjusted_balance": _money(side.adjusted_balance),
        "pending_total": _money(pending),  # lines that count once approved
        "lines": [{"kind": line.kind, "amount": _money(line.amount), "status": line.status,
                   "applied": line.applied} for line in side.lines],
    }


def report_facts(statement: Statement, counts: RunCounts, items: Sequence[ItemRef]) -> dict[str, Any]:
    """Everything the report may say, as computed numbers. No row text, ids or memos."""
    bank, book = _side(statement.bank), _side(statement.book)
    after = statement.unreconciled_difference - Decimal(book["pending_total"])
    by_kind: dict[str, Counter] = {}
    for item in items:
        by_kind.setdefault(item.kind, Counter())[item.status] += 1
    return {
        "company": statement.company,
        "cash_account": statement.cash_account,
        "period_start": statement.period_start.isoformat(),
        "period_end": statement.period_end.isoformat(),
        "raw_difference": _money(statement.raw_difference),
        "bank": bank,
        "book": book,
        "unreconciled_difference": _money(statement.unreconciled_difference),
        "difference_after_approvals": _money(after),  # if every pending line is approved
        "counts": counts.model_dump(),
        "items_by_kind": {k: {"count": sum(c.values()), "by_status": dict(c)} for k, c in sorted(by_kind.items())},
    }


def numbers_in(text: str) -> list[Decimal]:
    """Every number in the text as an absolute Decimal: "$1,234.50", "(1,234.50)" and "-1234.5" agree,
    and number words count ("three", "sixty-four", "dozen"). Scales ("3k", "thousand") have no value."""
    return [t.value for t in _tokens(text) if t.value is not None]


def _fact_values(value: Any) -> Iterator[tuple[Decimal, bool]]:
    """(value, is_money) for every number in the facts: decimal strings are money; counts, date
    parts and digits in names are integers."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _fact_values(k)
            yield from _fact_values(v)
    elif isinstance(value, list):
        for v in value:
            yield from _fact_values(v)
    elif isinstance(value, bool):
        return
    elif isinstance(value, int):
        yield Decimal(value), False
    elif isinstance(value, str):
        try:  # a date is its year, month and day
            d = date.fromisoformat(value)
            yield from ((Decimal(d.year), False), (Decimal(d.month), False), (Decimal(d.day), False))
            return
        except ValueError:
            pass
        try:
            yield abs(Decimal(value)), True
        except InvalidOperation:
            for t in _tokens(value):  # e.g. digits in the company name
                if t.value is not None:
                    yield t.value, False


def unsupported_numbers(text: str, facts: dict[str, Any]) -> list[str]:
    """The numbers in `text` the facts do not support, as written (commas dropped). A number with a
    decimal point or "$" must match a money fact; a bare integer may match any fact; a scale
    ("3k", "2 thousand", "hundred") never matches."""
    money, ints = set(), set()
    for v, is_money in _fact_values(facts):
        (money if is_money else ints).add(v)
    return [t.raw for t in _tokens(text)
            if t.value is None or t.value not in (money if t.money else money | ints)]


def _fmt(amount: str) -> str:
    return f"{Decimal(amount):,.2f}"


def template_report(facts: dict[str, Any]) -> str:
    """The deterministic report: written by code from the same facts, so its numbers always check."""
    f, c = facts, facts["counts"]
    bank, book = f["bank"], f["book"]
    lines = [
        f"## {f['company']} bank reconciliation, {f['period_start']} to {f['period_end']}",
        "",
        f"The bank closed at {_fmt(bank['closing_balance'])} and the book at {_fmt(book['closing_balance'])}, "
        f"a raw difference of {_fmt(f['raw_difference'])}.",
        "",
        f"- {c['matched']} items matched and {c['auto_resolved']} auto-resolved by policy.",
        f"- {c['reconciling_item']} reconciling items bring the bank to an adjusted {_fmt(bank['adjusted_balance'])}.",
        f"- {c['needs_approval']} items need approval; their draft entries move the book by "
        f"{_fmt(book['pending_total'])}.",
        "",
        f"Unreconciled difference now: {_fmt(f['unreconciled_difference'])}. "
        f"Once the pending entries are approved: {_fmt(f['difference_after_approvals'])}.",
        "",
    ]
    return "\n".join(lines)


def _messages(facts: dict[str, Any]) -> list[ChatMessage]:
    return [ChatMessage(role="system", content=system_prompt("report")),
            ChatMessage(role="user", content=json.dumps(facts))]


async def write_report(client: LLMClient, facts: dict[str, Any], *, run_id: str | None = None) -> ReportResult:
    """Ultra's report if its numbers check (after at most one repair), else the template."""
    convo = _messages(facts)
    stats: list[CallStats] = []
    bad: list[str] = []
    for attempt, source in enumerate(("model", "repaired"), start=1):
        try:
            text, call = await client.complete_text("ultra", convo)
        except AppError as exc:
            diagnostic_code = exc.diagnostic_code or exc.code
            logger.warning(
                "Ultra report request failed; using template fallback "
                "run_id=%s diagnostic_code=%s error_code=%s error_type=%s attempt=%s",
                run_id or "unknown",
                diagnostic_code,
                exc.code,
                type(exc).__name__,
                attempt,
                extra={
                    "run_id": run_id,
                    "diagnostic_code": diagnostic_code,
                    "error_code": exc.code,
                    "error_type": type(exc).__name__,
                    "report_attempt": attempt,
                },
            )
            break
        stats.append(call)
        bad = unsupported_numbers(text, facts)
        if text and not bad:
            return ReportResult(text, source, stats)
        problem = f"these numbers are not in the facts: {', '.join(bad)}" if bad else "it was empty"
        convo = [*convo, ChatMessage(role="assistant", content=text), ChatMessage(
            role="user", content=f"That report was rejected because {problem}. Rewrite it using only "
                                 "numbers that appear in the facts, copied exactly. Do not compute new ones.")]
    return ReportResult(template_report(facts), "template", stats, tuple(bad))
