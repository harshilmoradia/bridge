"""Pipelines the eval can score. Each is an async `(Dataset) -> PipelineResult` and reads only
demo-data/ (never the answer key).

`rules_only` is the code-only baseline: the B-03 matcher plus the policy gate on its match kinds.
It has no classify or resolve step, so whatever the matcher cannot pair stays undecided (kind
`unknown`, no resolution). B-09's agent pipeline registers here as another entry in PIPELINES.
"""

import json
from decimal import Decimal
from pathlib import Path

from app.recon.loader import DATA_DIR
from app.recon.matcher import load_match_policy, match
from app.recon.matching_models import Match
from app.recon.models import Dataset, ProposedEntry
from evals.types import EvalItem, Pipeline, PipelineResult


def _write_off(m: Match, cash: str, account: str) -> ProposedEntry:
    """Move the book onto the bank amount: a bank shortfall credits cash, a surplus debits it."""
    short = m.amount_delta < 0
    return ProposedEntry(
        debit_account=account if short else cash,
        credit_account=cash if short else account,
        amount=abs(m.amount_delta),
        memo=f"Rounding write-off {', '.join((*m.bank_ids, *m.gl_ids))}",
    )


async def rules_only(dataset: Dataset, data_dir: Path = DATA_DIR) -> PipelineResult:
    policy = json.loads((data_dir / "policy.json").read_text(encoding="utf-8"), parse_float=Decimal)
    auto_kinds = set(policy["auto_resolve_kinds"])
    cash = dataset.balances.cash_account
    result = match(dataset.bank, dataset.gl, load_match_policy(data_dir))

    items: list[EvalItem] = []
    for m in result.matches:
        if m.kind not in auto_kinds:
            items.append(EvalItem(kind=m.kind, resolution=None, bank_ids=m.bank_ids, gl_ids=m.gl_ids))
        elif m.kind == "rounding":
            entry = _write_off(m, cash, policy["auto_writeoff_account"])
            items.append(EvalItem(
                kind=m.kind, resolution="auto_match_with_writeoff", bank_ids=m.bank_ids, gl_ids=m.gl_ids, entry=entry
            ))
        else:
            items.append(EvalItem(kind=m.kind, resolution="auto_match", bank_ids=m.bank_ids, gl_ids=m.gl_ids))
    # Candidate groups need the fuzzy step to pick an option; rules-only leaves each group open.
    for c in result.candidates:
        items.append(EvalItem(kind="unknown", resolution=None, bank_ids=c.bank_ids, gl_ids=c.gl_ids))
    for b in result.unmatched_bank_ids:
        items.append(EvalItem(kind="unknown", resolution=None, bank_ids=(b,), gl_ids=()))
    for g in result.unmatched_gl_ids:
        items.append(EvalItem(kind="unknown", resolution=None, bank_ids=(), gl_ids=(g,)))
    return PipelineResult(items=tuple(items))


PIPELINES: dict[str, Pipeline] = {"rules": rules_only}
