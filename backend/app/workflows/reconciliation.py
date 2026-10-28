"""Inngest entry point for reconciliation runs.

The API (or another trusted caller) creates the run record first, then sends
``bridge/reconciliation.requested`` with its ID and dataset period. The actual
pipeline stages will be added behind this entry point in subsequent slices.
"""

from datetime import date

import inngest
from pydantic import BaseModel, Field, model_validator

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
async def reconciliation_run(ctx: inngest.Context) -> dict[str, str]:
    """Accept a run request; later slices will implement the pipeline stages."""
    request = ReconciliationRequested.model_validate(ctx.event.data)

    # Keep durable step output to identifiers only; do not persist transaction
    # rows or prompt text in Inngest step state.
    async def initialize_run() -> dict[str, str]:
        return {"run_id": request.run_id}

    return await ctx.step.run("initialize-run", initialize_run)
