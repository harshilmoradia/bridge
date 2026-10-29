"""review: code checks plus a Super critic, with the retry ladder.

Ladder: resolve on Super, retry on Super with feedback, one retry on Ultra, then escalate
as `unknown` with no entry. Code checks run first; the critic is only asked about a
result that already passed them, and it can only make an outcome stricter.
"""

import json
import re

from pydantic import BaseModel

from app.agents.checks import entry_problems, kind_problem
from app.agents.context import Books
from app.agents.decide import decide
from app.agents.models import AgentItem, WorkItem
from app.agents.prompts import system_prompt
from app.agents.resolve import ResolveResult, item_view, resolve
from app.core.errors import AppError
from app.llm import CallStats, LLMClient, Tier
from app.schemas.chat import ChatMessage
from app.schemas.runs import Evidence

LADDER: tuple[Tier, ...] = ("super", "super", "ultra")
_IDS = re.compile(r"\b(?:BANK|GL)\d{3,}\b")


class Critique(BaseModel):
    ok: bool
    feedback: str = ""


def result_problems(item: WorkItem, res: ResolveResult, books: Books) -> list[str]:
    if res.error:
        return [f"model call failed ({res.error})"]
    if not res.explanation:
        return ["no final explanation within the turn limit"]
    problems = list(res.rejected) if res.entry is None else []
    problems += [p for p in entry_problems(item, res.entry, books) if p not in problems]
    unknown = sorted({i for i in _IDS.findall(res.explanation) if not books.has_id(i)})
    if unknown:
        problems.append(f"cites rows that do not exist: {', '.join(unknown)}")
    return problems


async def critic(
    client: LLMClient, item: WorkItem, res: ResolveResult, books: Books
) -> tuple[Critique, CallStats | None]:
    entry = res.entry
    body = {
        "item": item_view(item, books),
        "explanation": res.explanation,
        "entry": None if entry is None else {
            "debit": f"{entry.debit_account} {books.accounts[entry.debit_account].name}",
            "credit": f"{entry.credit_account} {books.accounts[entry.credit_account].name}",
            "amount": str(entry.amount)},
    }
    messages = [ChatMessage(role="system", content=system_prompt("critic")),
                ChatMessage(role="user", content=json.dumps(body))]
    try:
        return await client.complete_json("super", messages, Critique)
    except AppError:
        # The critic only tightens; if it is unavailable, code checks stand alone.
        return Critique(ok=True), None


def evidence(item: WorkItem, books: Books, rule_ids=()) -> list[Evidence]:
    ev = [Evidence(type="bank_transaction", id=i) for i in item.bank_ids]
    ev += [Evidence(type="gl_entry", id=i) for i in item.gl_ids]
    p = books.policy
    for name in ("auto_resolve_kinds", "reconciling_item_kinds", "always_escalate_kinds"):
        if item.kind in getattr(p, name):
            ev.append(Evidence(type="policy", id=name, note=item.kind))
    ev += [Evidence(type="rule", id=str(r)) for r in rule_ids]
    return ev


def _finish(item: WorkItem, books: Books, *, passed: bool, problems: list[str],
            res: ResolveResult | None, reasoning: str | None) -> AgentItem:
    resolution, status = decide(item, checks_passed=passed, policy=books.policy)
    flags = list(item.flags)
    if res and res.rule_ids:
        flags.append("rule_applied")
    return AgentItem(
        id=item.id, kind=item.kind, resolution=resolution, status=status,
        bank_ids=list(item.bank_ids), gl_ids=list(item.gl_ids),
        amount_delta=item.amount_delta, reasoning=reasoning,
        evidence=evidence(item, books, res.rule_ids if res else ()), flags=flags,
        model=res.stats.model if res and res.stats else None,
        confidence=res.confidence if res else None,
        entry=res.entry if res and passed else None,
        checks_passed=passed, problems=problems,
    )


async def review_item(
    client: LLMClient, item: WorkItem, books: Books, *, use_critic: bool = True
) -> tuple[AgentItem, list[CallStats], list[CallStats]]:
    """Return the decided item plus resolve and critic call stats (for two run_steps rows)."""
    kind_failure = kind_problem(item, books)
    base_problems: list[str] = []
    if kind_failure:
        base_problems = [kind_failure]
        item = item.model_copy(update={"kind": "unknown"})
    if item.kind == "nsf_pair":  # a code-verified pair needs no fix
        return _finish(item, books, passed=True, problems=[], res=None,
                       reasoning="Returned (NSF) check and its GL reversal, tied by code."), [], []

    resolve_stats: list[CallStats] = []
    critic_stats: list[CallStats] = []
    feedback: list[str] = []
    res: ResolveResult | None = None
    problems: list[str] = []
    skipped = 0
    for tier in LADDER:
        res = await resolve(client, tier, item, books, feedback)
        if res.stats:
            resolve_stats.append(res.stats)
        problems = result_problems(item, res, books)
        if not problems and use_critic:
            verdict, stats = await critic(client, item, res, books)
            if stats:
                critic_stats.append(stats)
            else:
                skipped += 1
            if not verdict.ok:
                problems = [verdict.feedback.strip()[:300] or "the critic rejected the explanation"]
        if not problems:
            done = _finish(item, books, passed=not base_problems, problems=base_problems,
                           res=res, reasoning=res.explanation)
            done.critic_skipped = skipped
            return done, resolve_stats, critic_stats
        feedback = problems

    escalated = item.model_copy(update={"kind": "unknown"})
    reasoning = (res.explanation if res and res.explanation else None) \
        or "Escalated: no draft fix passed the code checks."
    res_no_entry = res
    if res_no_entry is not None:
        res_no_entry.entry = None
    done = _finish(escalated, books, passed=False, problems=base_problems + problems,
                   res=res_no_entry, reasoning=reasoning)
    done.critic_skipped = skipped
    return done, resolve_stats, critic_stats
