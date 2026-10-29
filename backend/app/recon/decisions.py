"""Human decisions on escalated items: override checks, the audit row and remembered rules.

`write_audit` and `save_rule` are what the `item-decided` Inngest function runs, one step each;
`POST /items/{id}/decision` runs them inline when Inngest is unreachable, so a decision is never
left without its audit row.

A human override is checked for structure only (accounts in the chart, two different accounts,
a positive amount in cents, a memo). It is not held to the agent rule that the amount must close
the item's delta: the reviewer may know better, and the statement shows the result either way.
"""

from decimal import Decimal
from typing import Any

from app.agents.context import load_accounts
from app.agents.rules import description_pattern, direction, row_pattern  # noqa: F401  (re-exported)
from app.recon.models import Dataset
from app.recon.run_store import Decision, RunStore, item_not_found
from app.schemas.runs import EntryOverride, Item

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")  # numeric(14,2)


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


def rule_for(item: Item, dataset: Dataset) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(pattern, action) learned from an approved item with an entry, or None if nothing to learn.

    Pattern: `description_regex` from the item's first bank row (else its first GL row), the GL
    counterparty when it is a business, and the `direction` (out or in) of the item's amount. Action:
    the approved entry's accounts and amount. B-13 applies a rule only when all of these match
    (`agents/rules.matching_rule`); the text came from untrusted rows, so it is only ever compared.
    """
    entry = item.proposed_entry
    if entry is None:
        return None
    pattern = row_pattern(item.bank_ids, item.gl_ids, dataset)
    if not pattern:
        return None
    pattern["direction"] = direction(item.amount_delta)
    return pattern, {"debit": entry.debit_account, "credit": entry.credit_account, "amount": str(entry.amount)}


async def _load(store: RunStore, item_id: str, decision_id: str) -> tuple[Item, Decision]:
    item = await store.get_item(item_id)
    decision = await store.get_decision(decision_id)
    if item is None or decision is None or decision.item_id != item_id:
        raise item_not_found(item_id)
    return item, decision


async def write_audit(store: RunStore, *, item_id: str, decision_id: str, run_id: str) -> int:
    item, d = await _load(store, item_id, decision_id)
    return await store.add_audit(
        run_id=run_id, entity_type="item", entity_id=item_id, action=d.decision, actor=d.actor,
        detail={"decision_id": decision_id, "bank_ids": list(item.bank_ids), "gl_ids": list(item.gl_ids),
                "remember": d.remember, "note": d.note,
                "entry_override": d.entry_override.model_dump(mode="json") if d.entry_override else None},
    )


async def save_rule(store: RunStore, dataset: Dataset, *, item_id: str, decision_id: str) -> int | None:
    """Store a rule when the reviewer approved with "remember"; rejections teach nothing, and neither
    does an injection-flagged item (its text may have been written to be learned)."""
    item, d = await _load(store, item_id, decision_id)
    if not d.remember or d.decision != "approve" or "injection_flagged" in item.flags:
        return None
    learned = rule_for(item, dataset)
    if learned is None:
        return None
    pattern, action = learned
    return await store.add_rule(kind=item.kind, pattern=pattern, action=action, source_item=item_id,
                                created_by=d.actor, dataset=dataset.id, origin="learned")
