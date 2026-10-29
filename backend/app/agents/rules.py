"""Learned rules (B-13): the pattern a rule is learned from, and when a rule applies to an item.

A reviewer who approves an item with "remember" saves a rule (`recon/decisions.save_rule`). The
pattern is built here, from screened text with no names, so learning and matching use one
derivation. A rule applies to a later item only when every criterion in `matching_rule` holds; then
`decide` may auto-resolve it, a narrow exception to `always_escalate_kinds`.
"""

import re
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agents.context import Books, Rule
from app.agents.decide import RULE_EXCLUDED_KINDS
from app.agents.models import DraftEntry, WorkItem
from app.guardrails import screen_text
from app.recon.models import Dataset

_WORD = re.compile(r"[A-Za-z][A-Za-z&'.-]*")
MAX_PATTERN_WORDS = 4
# Words that introduce a payee or sender: what follows may be a person's name, which mask_pii can
# miss outside its known contexts, so a learned pattern stops before them.
NAME_CUES = frozenset({"FROM", "TO", "BNF", "PAYEE", "REIMB", "PAYROLL", "ORDER", "ATTN", "FOR", "BY"})


def description_pattern(description: str) -> str:
    """The row's leading plain words, after PII masking. Stops at the first number, reference, mask
    or payee cue (FROM, TO, REIMB, ...), so no personal data is kept.

    It also stops at a name-like token with no cue: a Title-case pair (`WIRE John Smith` gives
    `WIRE`) or a mixed-case token (`McDonald`). One in the first token gives "": `John Smith 4417`
    and `McDonald Fee` teach nothing. The exception is a leading Title-case pair followed by ` - `,
    the GL category label: `Check Payment - Office Supplies - DeskPro Supply` gives `Check Payment`.

    `ZELLE FROM J MARTINEZ ACCT ****4417 ...` gives `ZELLE`; `MONTHLY SERVICE FEE` stays whole.
    """
    words: list[str] = []
    tokens = screen_text(description).text.split()
    for n, token in enumerate(tokens):
        if not _WORD.fullmatch(token) or token.upper() in NAME_CUES or len(words) == MAX_PATTERN_WORDS:
            break
        if _name_like(token, tokens[n + 1] if n + 1 < len(tokens) else "") and not _category(tokens, n):
            break
        words.append(token)
    return " ".join(re.escape(w) for w in words)


_TITLE = re.compile(r"[A-Z][a-z'-]+")


def _name_like(token: str, following: str) -> bool:
    """A Title-case token followed by another (`John Smith`), or a mixed-case token that is not plain
    Title case (`McDonald`)."""
    if _TITLE.fullmatch(token):
        return bool(_TITLE.fullmatch(following))
    return any(c.isupper() for c in token) and any(c.islower() for c in token)


def _category(tokens: Sequence[str], n: int) -> bool:
    """Token 0 opens a Title-case pair that is a GL category label, not a name: the pair is followed
    by the ` - ` separator (`Check Payment - Office Supplies - ...`, `Employee Salary - Michael Chen`).
    Only plain Title-case words qualify, so `McDonald - Fee` is still a name."""
    return (n == 0 and len(tokens) > 2 and tokens[2] == "-"
            and bool(_TITLE.fullmatch(tokens[0])) and bool(_TITLE.fullmatch(tokens[1])))


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


def row_pattern(bank_ids: Sequence[str], gl_ids: Sequence[str], dataset: Dataset) -> dict[str, Any]:
    """`description_regex` from the first bank row (else the first GL row), plus the GL counterparty
    when it is a business. Empty when there is nothing to learn from."""
    bank = {t.txn_id: t for t in dataset.bank}
    gl = {g.entry_id: g for g in dataset.gl}
    pattern: dict[str, Any] = {}
    if bank_ids and bank_ids[0] in bank:
        text = description_pattern(bank[bank_ids[0]].description)
    elif gl_ids and gl_ids[0] in gl:
        row = gl[gl_ids[0]]
        text = description_pattern(row.description)
        if row.counterparty and _is_business(row.counterparty, dataset):
            pattern["counterparty"] = row.counterparty
    else:
        text = ""
    return {"description_regex": text, **pattern} if text else pattern


def direction(amount_delta: Decimal) -> str:
    """`out` when the item takes money out of the bank side, else `in`."""
    return "out" if amount_delta < 0 else "in"


def agent_rule(stored: Any, dataset: str) -> Rule | None:
    """An API `Rule` (store row) as an agent rule, or None when it lacks what matching needs. Rules
    learned before B-13 carry no direction or amount: they can still be found, never applied."""
    pattern, action = stored.pattern or {}, stored.action or {}
    try:
        amount = Decimal(str(action["amount"])) if action.get("amount") is not None else None
    except InvalidOperation:
        amount = None
    if not pattern.get("description_regex") or not action.get("debit") or not action.get("credit"):
        return None
    return Rule(id=stored.id, kind=stored.kind, pattern=pattern["description_regex"],
                debit_account=action["debit"], credit_account=action["credit"],
                approved_by=stored.created_by, dataset=dataset, direction=pattern.get("direction", ""),
                amount=amount, counterparty=pattern.get("counterparty"))


def approver(rule: Rule) -> str:
    """`user:demo@bridge.local` -> `demo@bridge.local`, for "applied rule #N (approved by ...)"."""
    return rule.approved_by.split(":", 1)[-1] or "a reviewer"


def matching_rule(item: WorkItem, entry: DraftEntry | None, books: Books,
                  rules: Iterable[Rule] | None = None) -> Rule | None:
    """The first rule that applies to this item and its checked entry, or None.

    All must hold: the kind is not excluded; same kind, dataset and direction (amount sign); the
    item's screened description pattern equals the rule's (and its counterparty, if the rule has
    one); the item's amount equals the amount a human approved and is within max_auto_amount; and
    the entry equals the rule's entry (same accounts, that amount). Confidence plays no part, and an
    injection-flagged item never matches: its text may be steering the agents.
    """
    if entry is None or item.kind in RULE_EXCLUDED_KINDS or "injection_flagged" in item.flags:
        return None
    size = abs(item.amount_delta)
    if size > books.policy.max_auto_amount:
        return None
    pattern = row_pattern(item.bank_ids, item.gl_ids, books.dataset)
    for rule in books.rules if rules is None else rules:
        if (rule.kind, rule.dataset, rule.direction) != (item.kind, books.dataset.id, direction(item.amount_delta)):
            continue
        if not rule.pattern or rule.pattern != pattern.get("description_regex"):
            continue
        if rule.counterparty is not None and rule.counterparty != pattern.get("counterparty"):
            continue
        if rule.amount is None or rule.amount != size:
            continue
        if (entry.debit_account, entry.credit_account, entry.amount) != \
                (rule.debit_account, rule.credit_account, rule.amount):
            continue
        return rule
    return None


def candidate_rules(item: WorkItem, books: Books) -> list[Rule]:
    """Rules that would apply if the entry matched: what resolve shows the model up front."""
    return [r for r in books.rules
            if matching_rule(item, DraftEntry(debit_account=r.debit_account, credit_account=r.credit_account,
                                              amount=abs(item.amount_delta), memo="-"), books, [r])]
