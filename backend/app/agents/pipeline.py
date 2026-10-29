"""The agent pipeline as one callable: `run_agents(dataset, client)`.

E-01 (evals) and B-10 (Inngest) both call into this. B-10 can run the same pieces as
separate steps: `match`, `fuzzy_match`, `classify`, `review_item` (resolve + critic +
decide). Step logs carry stats and counts only. An optional `on_step` hook hears each stage
start and end, for live progress.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.agents.classify import classify, item_id
from app.agents.context import CASH, Books, Policy, Rule, load_accounts, load_policy
from app.agents.decide import decide
from app.agents.fuzzy_match import fuzzy_match
from app.agents.models import AgentItem, DraftEntry, StepLog, WorkItem
from app.agents.review import evidence, review_item
from app.guardrails import screen_text
from app.llm import CallStats, LLMClient
from app.recon.matcher import load_match_policy, match
from app.recon.matching_models import Match
from app.recon.models import Dataset

log = logging.getLogger(__name__)

# Progress hook: `on_step(stage_id, None)` as a stage starts, `on_step(stage_id, log)` as it ends.
OnStep = Callable[[str, StepLog | None], Awaitable[None]]


@dataclass
class AgentRun:
    items: list[AgentItem]
    steps: list[StepLog]


def _flags(books: Books, bank_ids, gl_ids) -> tuple[str, ...]:
    texts = [books.bank[i].description for i in bank_ids] + [books.gl[i].description for i in gl_ids]
    flags = []
    for text in texts:
        screened = screen_text(text)
        if screened.pii_masked and "pii_redacted" not in flags:
            flags.append("pii_redacted")
        if screened.injection.flagged and "injection_flagged" not in flags:
            flags.append("injection_flagged")
    return tuple(flags)


def _match_kind(m: Match, books: Books) -> str:
    bank, gl = books.rows(m.bank_ids, m.gl_ids)
    if len(bank) == len(gl) == 1 and bank[0].type == "RETURNED_ITEM" \
            and gl[0].method == "RETURNED_ITEM":
        return "nsf_pair"
    return m.kind


def _match_item(m: Match, books: Books, source: str) -> AgentItem:
    work = WorkItem(id=item_id(m.bank_ids, m.gl_ids), kind=_match_kind(m, books), source=source,
                    bank_ids=m.bank_ids, gl_ids=m.gl_ids, amount_delta=m.amount_delta,
                    flags=_flags(books, m.bank_ids, m.gl_ids))
    entry = None
    if work.kind == "rounding":
        delta, other = m.amount_delta, books.policy.auto_writeoff_account
        entry = DraftEntry(
            debit_account=CASH if delta > 0 else other,
            credit_account=other if delta > 0 else CASH,
            amount=abs(delta), memo=f"Rounding write-off {', '.join(m.bank_ids + m.gl_ids)}")
    resolution, status = decide(work, checks_passed=True, policy=books.policy)
    via = "description (Nano)" if source == "fuzzy" else "rules"
    return AgentItem(
        id=work.id, kind=work.kind, resolution=resolution, status=status,
        bank_ids=list(m.bank_ids), gl_ids=list(m.gl_ids), amount_delta=m.amount_delta,
        reasoning=f"Matched by {via}: {work.kind}, date gap {m.date_gap_days} day(s), "
                  f"difference {m.amount_delta}.",
        evidence=evidence(work, books), flags=list(work.flags), entry=entry)


def _log(step_id: str, tier: str, stats: Iterable[CallStats], summary: str) -> StepLog:
    stats = list(stats)
    return StepLog(
        id=step_id, tier=tier, model=stats[0].model if stats else None,
        latency_ms=sum(s.latency_ms for s in stats),
        tokens_in=sum(s.prompt_tokens for s in stats),
        tokens_out=sum(s.completion_tokens for s in stats),
        calls=len(stats), summary=summary)


async def run_agents(
    dataset: Dataset,
    client: LLMClient,
    *,
    policy: Policy | None = None,
    rules: Sequence[Rule] = (),
    use_critic: bool = True,
    concurrency: int = 4,  # 8 parallel Super calls stalled to the timeout in the live run
    on_step: OnStep | None = None,
) -> AgentRun:
    policy = policy or load_policy()
    accounts = load_accounts()
    base = Books(dataset, policy, accounts, tuple(rules))
    steps: list[StepLog] = []

    async def notify(stage_id: str, step: StepLog | None) -> None:
        # Progress is for display: a failing hook is logged and the run carries on. The caller
        # still gets every StepLog in the result.
        if on_step is None:
            return
        try:
            await on_step(stage_id, step)
        except Exception as e:
            log.warning("on_step failed for %s: %s", stage_id, type(e).__name__)

    async def end(step: StepLog) -> None:
        steps.append(step)
        await notify(step.id, step)

    await notify("match-rules", None)
    result = match(dataset.bank, dataset.gl, load_match_policy())
    await end(StepLog(id="match-rules", tier="code",
                      summary=f"{len(result.matches)} matches, {len(result.candidates)} candidate groups"))

    await notify("match-fuzzy", None)
    fuzzy = await asyncio.gather(*(fuzzy_match(client, g, base) for g in result.candidates))
    picked = [m for ms, _ in fuzzy for m in ms]
    fuzzy_stats = [s for _, ss in fuzzy for s in ss]
    await end(_log("match-fuzzy", "nano", fuzzy_stats, f"{len(picked)} pairs picked"))

    all_matches = list(result.matches) + picked
    matched_gl = frozenset(g for m in all_matches for g in m.gl_ids)
    books = Books(dataset, policy, accounts, tuple(rules), matched_gl_ids=matched_gl)
    used = {i for m in all_matches for i in m.bank_ids + m.gl_ids}
    left_bank = [b.txn_id for b in dataset.bank if b.txn_id not in used]
    left_gl = [g.entry_id for g in dataset.gl if g.entry_id not in used]

    await notify("classify", None)
    work, classify_stats = await classify(client, left_bank, left_gl, books)
    work = [w.model_copy(update={"flags": _flags(books, w.bank_ids, w.gl_ids)}) for w in work]
    by_code = sum(w.source == "code" for w in work)
    await end(_log("classify", "nano", classify_stats,
                   f"{len(work)} items classified: {by_code} by code, {len(work) - by_code} by Nano"))

    gate = asyncio.Semaphore(concurrency)

    async def one(w: WorkItem):
        async with gate:
            return await review_item(client, w, books, use_critic=use_critic)

    # Resolve and the critic interleave per item (critic feedback goes back into resolve), so the
    # two stages start together and end together.
    await notify("resolve", None)
    await notify("review", None)
    reviewed = await asyncio.gather(*(one(w) for w in work))
    resolve_stats = [s for _, rs, _ in reviewed for s in rs]
    critic_stats = [s for _, _, cs in reviewed for s in cs]
    ultra = sum(s.tier == "ultra" for s in resolve_stats)
    await end(_log("resolve", "super", resolve_stats,
                   f"{len(work)} items, {len(resolve_stats)} attempts, {ultra} on Ultra"))
    await end(_log("review", "super", critic_stats,
                   f"{sum(not i.checks_passed for i, _, _ in reviewed)} failed checks, "
                   f"{sum(i.critic_skipped for i, _, _ in reviewed)} critic calls failed"))

    await notify("decide", None)
    items = [_match_item(m, books, "rules") for m in result.matches]
    items += [_match_item(m, books, "fuzzy") for m in picked]
    items += [item for item, _, _ in reviewed]
    status = Counter(i.status for i in items)
    await end(StepLog(id="decide", tier="code", summary=", ".join(
        f"{n} {s}" for s, n in sorted(status.items()))))
    return AgentRun(items=items, steps=steps)


def total_entries(items: Iterable[AgentItem]) -> Decimal:
    """Net effect of all draft entries on the book cash balance (debit cash is +)."""
    net = Decimal("0.00")
    for i in items:
        if i.entry:
            net += i.entry.amount if i.entry.debit_account == CASH else -i.entry.amount
    return net
