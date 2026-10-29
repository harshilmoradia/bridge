"""Inngest entry point and matching/decision stages for reconciliation runs."""

import json
from datetime import date
from decimal import Decimal

import inngest
from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.llm import get_llm_client
from app.recon.loader import DATA_DIR
from app.recon.matching_models import CandidateGroup
from app.recon.matcher import load_match_policy, match
from app.recon.store import CsvStore, DbStore, ReadStore
from app.schemas.chat import ChatMessage
from app.workflows.client import inngest_client


class ReconciliationRequested(BaseModel):
    """Validated metadata carried by a reconciliation-requested event."""

    run_id: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def period_is_ordered(self) -> "ReconciliationRequested":
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self


class CandidateDecision(BaseModel):
    """Single-choice resolution for an ambiguous candidate group."""

    selected_option_index: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=300)


async def _resolve_candidate_group(group: CandidateGroup, *, group_index: int) -> dict[str, object]:
    """Ask the LLM to select one valid option; return a structured decision or a skip."""
    if not group.options:
        return {
            "group_index": group_index,
            "status": "skipped",
            "bank_ids": list(group.bank_ids),
            "gl_ids": list(group.gl_ids),
            "selected_option_index": None,
            "selected_bank_ids": [],
            "selected_gl_ids": [],
            "confidence": None,
            "reason": "no options available",
        }

    options = [
        {
            "index": i,
            "bank_ids": list(option.bank_ids),
            "gl_ids": list(option.gl_ids),
            "kind": option.kind,
            "amount_delta": str(option.amount_delta),
            "date_gap_days": option.date_gap_days,
        }
        for i, option in enumerate(group.options)
    ]
    prompts = [
        ChatMessage(
            role="user",
            content=(
                "Select the single best option for this ambiguous match group. "
                "Return JSON with keys selected_option_index, confidence, and reason. "
                "Use only indexes from the options list. "
                "Do not invent rows.\n\n"
                f"bank_ids={list(group.bank_ids)}\n"
                f"gl_ids={list(group.gl_ids)}\n"
                f"options={options}"
            ),
        )
    ]

    try:
        client = get_llm_client(get_settings())
        decision, _ = await client.complete_json("super", prompts, CandidateDecision)
        if decision.selected_option_index >= len(group.options):
            raise ValueError("selected_option_index is outside the available option list")
        option = group.options[decision.selected_option_index]
        return {
            "group_index": group_index,
            "status": "resolved",
            "bank_ids": list(group.bank_ids),
            "gl_ids": list(group.gl_ids),
            "selected_option_index": decision.selected_option_index,
            "selected_bank_ids": list(option.bank_ids),
            "selected_gl_ids": list(option.gl_ids),
            "kind": option.kind,
            "delta": str(option.amount_delta),
            "confidence": decision.confidence,
            "reason": decision.reason,
        }
    except Exception:
        return {
            "group_index": group_index,
            "status": "skipped",
            "bank_ids": list(group.bank_ids),
            "gl_ids": list(group.gl_ids),
            "selected_option_index": None,
            "selected_bank_ids": [],
            "selected_gl_ids": [],
            "kind": None,
            "delta": None,
            "confidence": None,
            "reason": "LLM resolution unavailable; candidate left for manual review",
        }


def _apply_policy(resolved: dict[str, object]) -> dict[str, object]:
    """Map the chosen match kind to the policy outcome the run should carry."""
    policy = json.loads((DATA_DIR / "policy.json").read_text(encoding="utf-8"))
    auto_resolve_kinds = set(policy.get("auto_resolve_kinds", []))
    reconciling_item_kinds = set(policy.get("reconciling_item_kinds", []))
    tolerance = policy.get("auto_writeoff_tolerance", "0.00")
    kind = resolved.get("kind")
    amount_delta = resolved.get("delta")

    if kind == "rounding" and amount_delta is not None:
        delta = abs(float(str(amount_delta)))
        if delta <= float(tolerance):
            return {
                "kind": kind,
                "resolution": "auto_match_with_writeoff",
                "policy_basis": "auto_writeoff_tolerance",
            }
    if kind in reconciling_item_kinds:
        return {
            "kind": kind,
            "resolution": "reconciling_item",
            "policy_basis": "reconciling_item_kinds",
        }
    if kind in auto_resolve_kinds:
        return {
            "kind": kind,
            "resolution": "auto_match",
            "policy_basis": "auto_resolve_kinds",
        }
    return {
        "kind": kind,
        "resolution": "escalate",
        "policy_basis": "always_escalate_kinds",
    }


def _materialize_items(
    policy_decisions: list[dict[str, object]],
    *,
    cash_account: str,
) -> list[dict[str, object]]:
    """Turn accepted policy decisions into canonical item records the run can persist or display."""
    policy = json.loads((DATA_DIR / "policy.json").read_text(encoding="utf-8"))
    counter_accounts = policy.get("proposed_entry_counter_accounts", {})
    items: list[dict[str, object]] = []
    for item in policy_decisions:
        resolution = item["resolution"]
        status_map = {
            "auto_match": "matched",
            "auto_match_with_writeoff": "auto_resolved",
            "reconciling_item": "reconciling_item",
            "escalate": "needs_approval",
        }
        delta = Decimal(str(item.get("delta") or "0.00"))
        bank_ids = item.get("selected_bank_ids") or item.get("bank_ids", [])
        gl_ids = item.get("selected_gl_ids") or item.get("gl_ids", [])
        materialized = {
            "id": f"item-{item['group_index']}",
            "run_id": item.get("run_id"),
            "kind": item["kind"],
            "resolution": resolution,
            "status": status_map.get(resolution, "needs_approval"),
            "bank_ids": bank_ids,
            "gl_ids": gl_ids,
            "amount_delta": str(delta),
            "reasoning": item.get("reason"),
            "evidence": [
                {"type": "policy", "id": item.get("policy_basis"), "note": None},
                {"type": "bank_transaction", "id": item["bank_ids"][0] if item.get("bank_ids") else None, "note": None},
            ] if item.get("bank_ids") else [{"type": "policy", "id": item.get("policy_basis"), "note": None}],
            "flags": [],
            "model": "llm-super",
            "confidence": item.get("confidence"),
            "rule_id": None,
        }
        counter_account = counter_accounts.get(str(item["kind"]), "2400")
        if resolution == "escalate" and delta != 0:
            if delta > 0:
                debit_account, credit_account = cash_account, counter_account
            else:
                debit_account, credit_account = counter_account, cash_account
            materialized["proposed_entry"] = {
                "id": f"entry-{item['group_index']}",
                "debit_account": debit_account,
                "credit_account": credit_account,
                "amount": str(abs(delta)),
                "memo": item.get("reason") or f"Reconciliation adjustment: {item['kind']}",
                "status": "draft",
            }
        items.append(materialized)
    return items


def _group_delta(item: dict[str, object], bank_by_id, gl_by_id) -> Decimal:
    bank_total = sum((bank_by_id[row_id].amount for row_id in item.get("bank_ids", [])), Decimal("0"))
    gl_total = sum((gl_by_id[row_id].amount for row_id in item.get("gl_ids", [])), Decimal("0"))
    return bank_total - gl_total


@inngest_client.create_function(
    fn_id="reconciliation-run",
    trigger=inngest.TriggerEvent(event="bridge/reconciliation.requested"),
)
async def reconciliation_run(ctx: inngest.Context) -> dict[str, object]:
    """Load the requested period, run deterministic matching, and resolve ambiguous groups when possible."""
    request = ReconciliationRequested.model_validate(ctx.event.data)

    async def load_and_match() -> dict[str, object]:
        settings = get_settings()
        store: ReadStore = DbStore(settings.database_url) if settings.database_url else CsvStore(settings.dataset)
        if isinstance(store, DbStore):
            await store.start_run(request.run_id)
        dataset = await store.dataset(request.dataset)
        if dataset is None:
            raise ValueError(f"Dataset {request.dataset} does not exist")

        bank = [
            txn for txn in dataset.bank
            if request.period_start <= txn.posted_date <= request.period_end
        ]
        gl = [
            entry for entry in dataset.gl
            if request.period_start <= entry.date <= request.period_end
        ]
        result = match(bank, gl, load_match_policy())

        matches = [
            {"bank_ids": list(item.bank_ids), "gl_ids": list(item.gl_ids)}
            for item in result.matches
        ]
        candidates = [
            {
                "bank_ids": list(group.bank_ids),
                "gl_ids": list(group.gl_ids),
                "options": [
                    {"bank_ids": list(option.bank_ids), "gl_ids": list(option.gl_ids)}
                    for option in group.options
                ],
            }
            for group in result.candidates
        ]
        candidate_options = sum(len(group.options) for group in result.candidates)
        resolved_candidates = [
            await _resolve_candidate_group(group, group_index=i)
            for i, group in enumerate(result.candidates)
        ]
        policy_decisions = []
        for item in resolved_candidates:
            if item.get("status") == "resolved":
                rule = _apply_policy(item)
                policy_decisions.append({
                    "group_index": item["group_index"],
                    "run_id": request.run_id,
                    "bank_ids": item["bank_ids"],
                    "gl_ids": item["gl_ids"],
                    "selected_option_index": item["selected_option_index"],
                    "selected_bank_ids": item["selected_bank_ids"],
                    "selected_gl_ids": item["selected_gl_ids"],
                    "kind": rule["kind"],
                    "resolution": rule["resolution"],
                    "policy_basis": rule["policy_basis"],
                    "delta": item.get("delta"),
                    "confidence": item.get("confidence"),
                    "reason": item.get("reason"),
                })
            else:
                # Preserve ambiguous groups for a human rather than silently dropping their rows.
                policy_decisions.append({
                    "group_index": item["group_index"],
                    "run_id": request.run_id,
                    "bank_ids": item["bank_ids"],
                    "gl_ids": item["gl_ids"],
                    "selected_bank_ids": [],
                    "selected_gl_ids": [],
                    "kind": "unknown",
                    "resolution": "escalate",
                    "policy_basis": "manual_review",
                    "delta": str(_group_delta(item, {txn.txn_id: txn for txn in bank}, {entry.entry_id: entry for entry in gl})),
                    "confidence": None,
                    "reason": item.get("reason") or "Ambiguous candidate requires manual review",
                })
        items = _materialize_items(policy_decisions, cash_account=dataset.balances.cash_account)
        auto_resolved = sum(1 for item in policy_decisions if item["resolution"] in {"auto_match", "auto_match_with_writeoff"})
        result = {
            "run_id": request.run_id,
            "matches": matches,
            "candidate_groups": candidates,
            "resolved_candidates": resolved_candidates,
            "policy_decisions": policy_decisions,
            "items": items,
            "unmatched_bank_ids": list(result.unmatched_bank_ids),
            "unmatched_gl_ids": list(result.unmatched_gl_ids),
            "counts": {
                "bank_transactions": len(bank),
                "gl_entries": len(gl),
                "matches": len(matches),
                "candidate_groups": len(candidates),
                "candidate_options": candidate_options,
                "resolved_candidates": len([item for item in resolved_candidates if item["status"] == "resolved"]),
                "auto_resolved": auto_resolved,
                "unmatched_bank": len(result.unmatched_bank_ids),
                "unmatched_gl": len(result.unmatched_gl_ids),
            },
        }

        if isinstance(store, DbStore):
            item_ids = await store.complete_run(request.run_id, result)
        else:
            item_ids = [str(item["id"]) for item in items]
        return {
            "run_id": request.run_id,
            "item_ids": item_ids,
            "counts": result["counts"],
        }

    try:
        return await ctx.step.run("load-and-match", load_and_match)
    except Exception as exc:
        settings = get_settings()
        if settings.database_url:
            try:
                await DbStore(settings.database_url).fail_run(request.run_id, str(exc))
            except Exception:
                pass
        raise
