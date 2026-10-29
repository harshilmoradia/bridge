"""Human decisions on escalated items: override checks, the audit row and remembered rules.

`write_audit` and `save_rule` are what the `item-decided` Inngest function runs, one step each;
`POST /items/{id}/decision` runs them inline when Inngest is unreachable, so a decision is never
left without its audit row.

A human override is checked for structure only (accounts in the chart, two different accounts,
a positive amount in cents, a memo). It is not held to the agent rule that the amount must close
the item's delta: the reviewer may know better, and the statement shows the result either way.
"""

import re
from decimal import Decimal
from typing import Any

from app.agents.context import load_accounts
from app.guardrails import screen_text
from app.recon.models import Dataset
from app.recon.run_store import Decision, RunStore, item_not_found
from app.schemas.runs import EntryOverride, Item

CENT = Decimal("0.01")
_WORD = re.compile(r"[A-Za-z][A-Za-z&'.-]*")
MAX_PATTERN_WORDS = 4
MAX_AMOUNT = Decimal("999999999999.99")  # numeric(14,2)
# Words that introduce a payee or sender: what follows may be a person's name, which mask_pii can
# miss outside its known contexts, so a learned pattern stops before them.
NAME_CUES = frozenset({"FROM", "TO", "BNF", "PAYEE", "REIMB", "PAYROLL", "ORDER", "ATTN", "FOR", "BY"})


def override_problems(override: EntryOverride, accounts: dict[str, Any] | None = None) -> list[str]:
    accounts = accounts if accounts is not None else load_accounts()
    problems = [f"account {a} is not in the chart of accounts"
                for a in (override.debit_account, override.credit_account) if a not in accounts]
    if override.debit_account == override.credit_account:
        problems.append("debit and credit accounts must differ")
    if override.amount != override.amount.quantize(CENT):
        problems.append("amount must be in whole cents")
    if override.amount > MAX_AMOUNT:
        problems.append(f"amount must not exceed {MAX_AMOUNT}")
    if not override.memo.strip():
        problems.append("memo must not be blank")
    return problems


def description_pattern(description: str) -> str:
    """The row's leading plain words, after PII masking. Stops at the first number, reference, mask
    or payee cue (FROM, TO, REIMB, ...), so no personal data is kept.

    `ZELLE FROM J MARTINEZ ACCT ****4417 ...` gives `ZELLE`; `MONTHLY SERVICE FEE` stays whole.
    """
    words: list[str] = []
    for token in screen_text(description).text.split():
        if not _WORD.fullmatch(token) or token.upper() in NAME_CUES or len(words) == MAX_PATTERN_WORDS:
            break
        words.append(token)
    return " ".join(re.escape(w) for w in words)


_FIRST_LAST = re.compile(r"[A-Z][a-z'-]+ [A-Z][a-z'-]+")


def _masks(text: str) -> bool:
    return screen_text(text).pii_masked


def _is_business(counterparty: str, dataset: Dataset) -> bool:
    """Keep a GL counterparty in a rule only when nothing suggests a person. Dropped when masking
    changes it, when any GL row for it has a name masked (GL069 `Employee Salary - Michael Chen`), or
    when it reads as a bare `First Last` (unseen people). Losing one weakens a rule; keeping one leaks."""
    if _masks(counterparty) or _FIRST_LAST.fullmatch(counterparty.strip()):
        return False
    return not any(_masks(g.description) for g in dataset.gl if g.counterparty == counterparty)


def rule_for(item: Item, dataset: Dataset) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(pattern, action) learned from an approved item with an entry, or None if nothing to learn.

    Pattern: `description_regex` from the item's first bank row (else its first GL row), plus the GL
    counterparty when there is one. Both come from untrusted text, so B-13 must still treat them as data.
    """
    entry = item.proposed_entry
    if entry is None:
        return None
    pattern: dict[str, Any] = {}
    bank = {t.txn_id: t for t in dataset.bank}
    gl = {g.entry_id: g for g in dataset.gl}
    if item.bank_ids and item.bank_ids[0] in bank:
        text = description_pattern(bank[item.bank_ids[0]].description)
    elif item.gl_ids and item.gl_ids[0] in gl:
        row = gl[item.gl_ids[0]]
        text = description_pattern(row.description)
        if row.counterparty and _is_business(row.counterparty, dataset):
            pattern["counterparty"] = row.counterparty
    else:
        text = ""
    if text:
        pattern = {"description_regex": text, **pattern}
    if not pattern:
        return None
    return pattern, {"debit": entry.debit_account, "credit": entry.credit_account}


async def _load(store: RunStore, item_id: str, decision_id: str) -> tuple[Item, Decision]:
    item = await store.get_item(item_id)
    decision = await store.get_decision(decision_id)
    if item is None or decision is None or decision.item_id != item_id:
        raise item_not_found(item_id)
    return item, decision


async def write_audit(store: RunStore, *, item_id: str, decision_id: str, run_id: str) -> int:
    _item, d = await _load(store, item_id, decision_id)
    return await store.add_audit(
        run_id=run_id, entity_type="item", entity_id=item_id, action=d.decision, actor=d.actor,
        detail={"decision_id": decision_id, "remember": d.remember, "note": d.note,
                "entry_override": d.entry_override.model_dump(mode="json") if d.entry_override else None},
    )


async def save_rule(store: RunStore, dataset: Dataset, *, item_id: str, decision_id: str) -> int | None:
    """Store a rule when the reviewer approved with "remember"; rejections teach nothing."""
    item, d = await _load(store, item_id, decision_id)
    if not d.remember or d.decision != "approve":
        return None
    learned = rule_for(item, dataset)
    if learned is None:
        return None
    pattern, action = learned
    return await store.add_rule(kind=item.kind, pattern=pattern, action=action, source_item=item_id,
                                created_by=d.actor, dataset=dataset.id, origin="learned")
