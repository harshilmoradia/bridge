"""Inngest function `item-decided`: the decision's audit row.

Triggered by `bridge/item.decided {item_id, decision_id, run_id}` from `POST /items/{id}/decision`.
The route saves a remembered rule itself (B-14), so its response can say whether one was saved; this
job never saves rules, so nothing is saved twice. Step outputs are IDs only.
"""

from typing import Any

import inngest
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.recon.decisions import write_audit
from app.recon.run_store import RunStore, get_run_store
from app.workflows.client import inngest_client

ITEM_DECIDED = "bridge/item.decided"


class ItemDecided(BaseModel):
    item_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


async def record_decided(store: RunStore, event: ItemDecided) -> dict[str, Any]:
    """The job's work in one call: the inline fallback when the event cannot be sent."""
    return {"audit_id": await write_audit(store, **event.model_dump())}


@inngest_client.create_function(fn_id="item-decided", trigger=inngest.TriggerEvent(event=ITEM_DECIDED))
async def item_decided(ctx: inngest.Context) -> dict[str, Any]:
    event = ItemDecided.model_validate(ctx.event.data)
    store = get_run_store(get_settings())

    async def audit() -> dict[str, Any]:
        return await record_decided(store, event)

    a = await ctx.step.run("audit", audit)
    return {"item_id": event.item_id, "decision_id": event.decision_id, **a}
