"""decide (code): policy kind plus passing code checks. Nothing else is an input.

Model confidence and the injection flag are display-only, so neither is a parameter here.
"""

from app.agents.context import Policy
from app.agents.models import WorkItem

MATCH_KINDS = frozenset({"exact", "timing", "check_number", "one_to_many"})
ESCALATE = ("escalate", "needs_approval")


def decide(item: WorkItem, *, checks_passed: bool, policy: Policy) -> tuple[str, str]:
    """Return (resolution, status) for an item."""
    if not checks_passed:
        return ESCALATE
    kind, size = item.kind, abs(item.amount_delta)
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
