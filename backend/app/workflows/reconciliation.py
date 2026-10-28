"""Inngest entry point and deterministic matching stage for reconciliation runs."""

from datetime import date

import inngest
from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.recon.matcher import load_match_policy, match
from app.recon.store import CsvStore, DbStore, ReadStore
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


@inngest_client.create_function(
    fn_id="reconciliation-run",
    trigger=inngest.TriggerEvent(event="bridge/reconciliation.requested"),
)
async def reconciliation_run(ctx: inngest.Context) -> dict[str, object]:
    """Load the requested period and produce code-based matches and candidates."""
    request = ReconciliationRequested.model_validate(ctx.event.data)

    async def load_and_match() -> dict[str, object]:
        settings = get_settings()
        store: ReadStore = DbStore(settings.database_url) if settings.database_url else CsvStore(settings.dataset)
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

        # Inngest persists step outputs. Store only row IDs and counts here;
        # future agent steps can reload the dataset from these references.
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
        return {
            "run_id": request.run_id,
            "matches": matches,
            "candidate_groups": candidates,
            "unmatched_bank_ids": list(result.unmatched_bank_ids),
            "unmatched_gl_ids": list(result.unmatched_gl_ids),
            "counts": {
                "bank_transactions": len(bank),
                "gl_entries": len(gl),
                "matches": len(matches),
                "candidate_groups": len(candidates),
                "candidate_options": candidate_options,
                "unmatched_bank": len(result.unmatched_bank_ids),
                "unmatched_gl": len(result.unmatched_gl_ids),
            },
        }

    return await ctx.step.run("load-and-match", load_and_match)
