"""fuzzy_match (Nano): pick true pairs inside a candidate group, by description.

The model may only choose among the group's options, and each row is used at most once.
Rows left unpaired go on to classify.
"""

import json
from collections import Counter

from pydantic import BaseModel

from app.agents.context import Books
from app.agents.prompts import system_prompt
from app.core.errors import AppError
from app.guardrails import prompt_row
from app.llm import CallStats, LLMClient
from app.recon.matching_models import CandidateGroup, Match
from app.schemas.chat import ChatMessage


class Pair(BaseModel):
    bank_id: str
    gl_id: str


class FuzzyOut(BaseModel):
    pairs: list[Pair]


def _same(books: Books, gl_ids) -> bool:
    rows = [books.gl[i] for i in gl_ids]
    key = lambda g: (g.date, g.amount, g.description, g.check_number, g.counterparty)  # noqa: E731
    return len({key(g) for g in rows}) == 1


def _accept(group: CandidateGroup, pairs: list[tuple[str, str]]) -> list[Match]:
    options = {(o.bank_ids[0], o.gl_ids[0]): o for o in group.options
               if len(o.bank_ids) == 1 and len(o.gl_ids) == 1}
    used: set[str] = set()
    picked: list[Match] = []
    for bank_id, gl_id in pairs:
        option = options.get((bank_id, gl_id))
        if option is None or bank_id in used or gl_id in used:
            continue
        used |= {bank_id, gl_id}
        picked.append(option)
    # Complete forced pairs: once picks remove the alternatives, a row with exactly one
    # option left whose partner also has exactly one left is the matcher's uniqueness rule.
    if picked:
        while True:
            free = [k for k in options if k[0] not in used and k[1] not in used]
            per_bank = Counter(b for b, _ in free)
            per_gl = Counter(g for _, g in free)
            forced = [k for k in free if per_bank[k[0]] == 1 and per_gl[k[1]] == 1]
            if not forced:
                return picked
            for bank_id, gl_id in forced:
                used |= {bank_id, gl_id}
                picked.append(options[(bank_id, gl_id)])


async def fuzzy_match(
    client: LLMClient, group: CandidateGroup, books: Books
) -> tuple[list[Match], list[CallStats]]:
    # One bank line against identical GL copies: code picks the lowest ID, no model needed.
    if len(group.bank_ids) == 1 and _same(books, group.gl_ids):
        return _accept(group, [(group.bank_ids[0], min(group.gl_ids))]), []
    body = {
        "bank": [prompt_row(books.bank[i].model_dump()) for i in group.bank_ids],
        "gl": [prompt_row(books.gl[i].model_dump()) for i in group.gl_ids],
        "options": [{"bank_id": o.bank_ids[0], "gl_id": o.gl_ids[0]} for o in group.options],
    }
    messages = [ChatMessage(role="system", content=system_prompt("fuzzy_match")),
                ChatMessage(role="user", content=json.dumps(body))]
    try:
        out, stats = await client.complete_json("nano", messages, FuzzyOut)
    except AppError:  # bad output, timeout or outage: rows go on to classify unpaired
        return [], []
    return _accept(group, [(p.bank_id, p.gl_id) for p in out.pairs]), [stats]
