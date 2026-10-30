"""Bounded cron worker that refreshes the derived Supabase RAG index.

The single durable step returns counts only. Claims, transaction text, and vectors stay inside the
step implementation and are never saved as Inngest step output.
"""

import logging
from typing import Any

import inngest

from app.core.config import get_settings
from app.rag.embeddings import get_embedding_provider
from app.rag.index_store import RagIndexStore, RagIndexWorker
from app.workflows.client import inngest_client

log = logging.getLogger(__name__)


async def process_rag_index_batch() -> dict[str, int]:
    settings = get_settings()
    if not settings.database_url:
        return {"claimed": 0, "indexed": 0, "deleted": 0, "unchanged": 0, "failed": 0}
    store = RagIndexStore(
        settings.database_url,
        batch_size=settings.rag_index_batch_size,
        lease_seconds=settings.rag_index_lease_seconds,
    )
    provider = get_embedding_provider(settings)
    worker = RagIndexWorker(store, provider, settings.rag_embedding_model)
    try:
        return (await worker.run_batch()).as_dict()
    except Exception as exc:
        # Database exceptions can include parameter values. Keep both logs and durable outputs safe.
        log.warning("RAG index batch failed: %s", type(exc).__name__)
        return {"claimed": 0, "indexed": 0, "deleted": 0, "unchanged": 0, "failed": 1}


@inngest_client.create_function(
    fn_id="rag-index-outbox",
    retries=0,
    trigger=inngest.TriggerCron(cron="*/1 * * * *"),
)
async def rag_index_outbox(ctx: inngest.Context) -> dict[str, Any]:
    result = await ctx.step.run("index-batch", process_rag_index_batch)
    return {"indexed": result["indexed"], "deleted": result["deleted"],
            "failed": result["failed"]}
