"""classify (Nano): group the leftover rows into items and give each a kind.

One call sees every leftover row, because a transposition pairs a bank line with a GL
line the matcher could not tie. Code then enforces that every leftover ID lands in
exactly one item: items naming an unknown or already-used ID are dropped, and any row
left over becomes its own `unknown` item. Review checks each kind against the rows.
Rows whose kind code can prove are pre-labelled first (agents/prelabel.py) and never reach Nano.
"""

import json

from pydantic import BaseModel

from app.agents.context import Books
from app.agents.models import ClassifyKind, WorkItem
from app.agents.prelabel import backstop, item_id, prelabel, work_item  # noqa: F401  (item_id: re-exported)
from app.agents.prompts import system_prompt
from app.core.errors import AppError
from app.guardrails import prompt_row
from app.llm import CallStats, LLMClient, Tier
from app.schemas.chat import ChatMessage

FALLBACK: tuple[Tier, ...] = ("nano", "super")


class ClassifiedItem(BaseModel):
    bank_ids: list[str]
    gl_ids: list[str]
    kind: ClassifyKind


class ClassifyOut(BaseModel):
    items: list[ClassifiedItem]


def _similar_matched(books: Books, gl_ids) -> dict[str, list[dict]]:
    out = {}
    for gid in gl_ids:
        g = books.gl[gid]
        twins = [o for o in books.dataset.gl if o.entry_id != gid
                 and o.entry_id in books.matched_gl_ids and o.amount == g.amount]
        if twins:
            out[gid] = [prompt_row(t.model_dump()) for t in twins[:3]]
    return out


def _check_facts(books: Books, gl_ids) -> dict[str, dict]:
    """For each leftover GL check: the bank line that already cleared that check number, if any."""
    cleared = {b.check_number: b.txn_id for b in books.dataset.bank if b.check_number}
    return {gid: {"check_number": books.gl[gid].check_number,
                  "cleared_by_bank": cleared.get(books.gl[gid].check_number)}
            for gid in gl_ids if books.gl[gid].check_number}


async def classify(
    client: LLMClient, bank_ids: list[str], gl_ids: list[str], books: Books
) -> tuple[list[WorkItem], list[CallStats]]:
    proven, bank_ids, gl_ids = prelabel(books, bank_ids, gl_ids)
    items, stats = await _classify_rest(client, bank_ids, gl_ids, books)
    return proven + backstop(books, items, gl_ids), stats


async def _classify_rest(
    client: LLMClient, bank_ids: list[str], gl_ids: list[str], books: Books
) -> tuple[list[WorkItem], list[CallStats]]:
    if not bank_ids and not gl_ids:
        return [], []
    body = {
        "bank": [prompt_row(books.bank[i].model_dump()) for i in bank_ids],
        "gl": [prompt_row(books.gl[i].model_dump()) for i in gl_ids],
        "similar_matched": _similar_matched(books, gl_ids),
        "check_facts": _check_facts(books, gl_ids),
    }
    messages = [ChatMessage(role="system", content=system_prompt("classify")),
                ChatMessage(role="user", content=json.dumps(body))]
    # Nano reasons at length on this one call and can time out; Super is the fallback.
    # If both fail, every row escalates as `unknown`: slower for the reviewer, never wrong.
    proposed: list[ClassifiedItem] = []
    all_stats: list[CallStats] = []
    for tier in FALLBACK:
        try:
            out, stats = await client.complete_json(tier, messages, ClassifyOut)
        except AppError:
            continue
        proposed, all_stats = out.items, [stats]
        break

    left_bank, left_gl = set(bank_ids), set(gl_ids)
    items: list[WorkItem] = []
    for p in proposed:
        b, g = set(p.bank_ids), set(p.gl_ids)
        if not (b or g) or not b <= left_bank or not g <= left_gl \
                or len(b) != len(p.bank_ids) or len(g) != len(p.gl_ids):
            continue
        left_bank -= b
        left_gl -= g
        if p.kind == "unknown" and len(b) + len(g) > 1:
            # An unexplained group helps no one: each row gets its own resolve.
            items += [work_item(books, [i], [], "unknown") for i in p.bank_ids]
            items += [work_item(books, [], [i], "unknown") for i in p.gl_ids]
            continue
        items.append(work_item(books, p.bank_ids, p.gl_ids, p.kind))
    items += [work_item(books, [i], [], "unknown") for i in bank_ids if i in left_bank]
    items += [work_item(books, [], [i], "unknown") for i in gl_ids if i in left_gl]
    return items, all_stats

