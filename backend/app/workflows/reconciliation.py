"""Inngest entry point and matching/decision stages for reconciliation runs."""

import json
from datetime import date
from decimal import Decimal

import inngest
from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.llm import get_llm_client
from app.recon.loader import DATA_DIR
from app.recon.matching_models import CandidateGroup, Match
from app.recon.matcher import load_match_policy, match
from app.recon.store import CsvStore, DbStore, MEMORY_RUN_STORE, ReadStore
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
            "id": str(item.get("item_id") or f"item-{item['group_index']}"),
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
            "model": item.get("model") or ("llm-super" if item.get("confidence") is not None else "code"),
            "confidence": item.get("confidence"),
            "rule_id": None,
        }
        counter_account = counter_accounts.get(str(item["kind"]), "2400")
        if resolution == "auto_match_with_writeoff" and delta != 0:
            writeoff_account = str(policy.get("auto_writeoff_account", "6990"))
            if delta > 0:
                debit_account, credit_account = cash_account, writeoff_account
            else:
                debit_account, credit_account = writeoff_account, cash_account
            materialized["proposed_entry"] = {
                "id": f"entry-{item.get('item_id') or item['group_index']}",
                "debit_account": debit_account,
                "credit_account": credit_account,
                "amount": str(abs(delta)),
                "memo": "Automatic rounding write-off",
                "status": "posted",
            }
        elif resolution == "escalate" and delta != 0:
            if delta > 0:
                debit_account, credit_account = cash_account, counter_account
            else:
                debit_account, credit_account = counter_account, cash_account
            materialized["proposed_entry"] = {
                "id": f"entry-{item.get('item_id') or item['group_index']}",
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
        store: ReadStore = DbStore(settings.database_url) if settings.database_url else CsvStore(request.dataset)
        if isinstance(store, DbStore):
            await store.start_run(request.run_id)
        else:
            await MEMORY_RUN_STORE.start_run(request.run_id)
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
        match_result = match(bank, gl, load_match_policy())

        matches = [
            {"bank_ids": list(item.bank_ids), "gl_ids": list(item.gl_ids)}
            for item in match_result.matches
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
            for group in match_result.candidates
        ]
        candidate_options = sum(len(group.options) for group in match_result.candidates)
        resolved_candidates = [
            await _resolve_candidate_group(group, group_index=i)
            for i, group in enumerate(match_result.candidates)
        ]
        policy_decisions = []
        for i, matched in enumerate(match_result.matches):
            resolved_match = {"kind": matched.kind, "delta": str(matched.amount_delta)}
            rule = _apply_policy(resolved_match)
            policy_decisions.append({
                "group_index": i,
                "item_id": f"match-{i}",
                "run_id": request.run_id,
                "bank_ids": list(matched.bank_ids),
                "gl_ids": list(matched.gl_ids),
                "selected_bank_ids": list(matched.bank_ids),
                "selected_gl_ids": list(matched.gl_ids),
                "kind": rule["kind"],
                "resolution": rule["resolution"],
                "policy_basis": rule["policy_basis"],
                "delta": str(matched.amount_delta),
                "confidence": None,
                "reason": f"Deterministic {matched.kind} match",
                "model": "code",
            })

        bank_by_id = {txn.txn_id: txn for txn in bank}
        gl_by_id = {entry.entry_id: entry for entry in gl}
        for item in resolved_candidates:
            if item.get("status") == "resolved":
                rule = _apply_policy(item)
                policy_decisions.append({
                    "group_index": item["group_index"],
                    "item_id": f"candidate-{item['group_index']}",
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
                    "item_id": f"candidate-{item['group_index']}",
                    "run_id": request.run_id,
                    "bank_ids": item["bank_ids"],
                    "gl_ids": item["gl_ids"],
                    "selected_bank_ids": [],
                    "selected_gl_ids": [],
                    "kind": "unknown",
                    "resolution": "escalate",
                    "policy_basis": "manual_review",
                    "delta": str(_group_delta(item, bank_by_id, gl_by_id)),
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
            "unmatched_bank_ids": list(match_result.unmatched_bank_ids),
            "unmatched_gl_ids": list(match_result.unmatched_gl_ids),
            "counts": {
                "bank_transactions": len(bank),
                "gl_entries": len(gl),
                "matches": len(matches),
                "candidate_groups": len(candidates),
                "candidate_options": candidate_options,
                "resolved_candidates": len([item for item in resolved_candidates if item["status"] == "resolved"]),
                "auto_resolved": auto_resolved,
                "unmatched_bank": len(match_result.unmatched_bank_ids),
                "unmatched_gl": len(match_result.unmatched_gl_ids),
            },
        }

        if isinstance(store, DbStore):
            item_ids = await store.complete_run(request.run_id, result)
        else:
            item_ids = await MEMORY_RUN_STORE.complete_run(request.run_id, result)
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
        else:
            await MEMORY_RUN_STORE.fail_run(request.run_id, str(exc))
        raise
