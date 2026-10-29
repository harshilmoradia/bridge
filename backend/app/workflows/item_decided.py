"""Inngest function `item-decided`: the audit row, then a learned rule when "remember" was ticked.

Triggered by `bridge/item.decided {item_id, decision_id, run_id}` from `POST /items/{id}/decision`.
Step outputs are IDs only.
"""

from typing import Any

import inngest
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.recon.decisions import save_rule, write_audit
from app.recon.run_store import RunStore, get_run_store
from app.recon.store import read_store
from app.workflows.client import inngest_client

ITEM_DECIDED = "bridge/item.decided"


class ItemDecided(BaseModel):
    item_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


async def record_decided(store: RunStore, event: ItemDecided) -> dict[str, Any]:
    """Both steps in one call: the inline fallback when the event cannot be sent."""
    audit_id = await write_audit(store, **event.model_dump())
    rule_id = await _rule(store, event)
    return {"audit_id": audit_id, "rule_id": rule_id}


async def _rule(store: RunStore, event: ItemDecided) -> int | None:
    run = await store.get_run(event.run_id)
    dataset = await read_store(get_settings()).dataset(run.dataset) if run else None
    if dataset is None:
        return None
    return await save_rule(store, dataset, item_id=event.item_id, decision_id=event.decision_id)


@inngest_client.create_function(fn_id="item-decided", trigger=inngest.TriggerEvent(event=ITEM_DECIDED))
async def item_decided(ctx: inngest.Context) -> dict[str, Any]:
    event = ItemDecided.model_validate(ctx.event.data)
    store = get_run_store(get_settings())

    async def audit() -> dict[str, Any]:
        return {"audit_id": await write_audit(store, **event.model_dump())}

    async def rule() -> dict[str, Any]:
        return {"rule_id": await _rule(store, event)}

    a = await ctx.step.run("audit", audit)
    r = await ctx.step.run("rule", rule)
    return {"item_id": event.item_id, "decision_id": event.decision_id, **a, **r}
