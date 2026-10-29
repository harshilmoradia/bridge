"""decide (code): policy kind plus passing code checks, and (B-13) a learned rule. Nothing else.

Model confidence and the injection flag are display-only, so neither is a parameter here.

A learned rule is a narrow, explicit exception to `always_escalate_kinds`: a human approved this
exact pattern, amount and entry with "remember" (`agents/rules.matching_rule` checks all of that).
The kinds below never auto-resolve by rule, whatever a rule says: each is a judgment about *which*
rows are wrong, not a recurring posting.
"""

from typing import TYPE_CHECKING

from app.agents.models import WorkItem

if TYPE_CHECKING:
    from app.agents.context import Policy, Rule

MATCH_KINDS = frozenset({"exact", "timing", "check_number", "one_to_many"})
ESCALATE = ("escalate", "needs_approval")
RULE_EXCLUDED_KINDS = frozenset({"unknown", "duplicate_gl_entry", "unidentified_receipt", "transposition"})


def decide(item: WorkItem, *, checks_passed: bool, policy: "Policy", rule: "Rule | None" = None) -> tuple[str, str]:
    """Return (resolution, status) for an item. `rule` is one `matching_rule` already found."""
    if not checks_passed:
        return ESCALATE
    kind, size = item.kind, abs(item.amount_delta)
    if rule is not None and rule.kind == kind and kind not in RULE_EXCLUDED_KINDS \
            and size <= policy.max_auto_amount:
        return ("apply_rule", "auto_resolved")
    if kind in policy.auto_resolve_kinds:
        if size > policy.max_auto_amount:
            return ESCALATE
        if kind == "rounding":
            if size > policy.auto_writeoff_tolerance:
                return ESCALATE
            return ("auto_match_with_writeoff", "auto_resolved")
        return ("auto_match", "matched" if kind in MATCH_KINDS else "auto_resolved")
    if kind in policy.reconciling_item_kinds:
        return ("reconciling_item", "reconciling_item")
    return ESCALATE
