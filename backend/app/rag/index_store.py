"""Postgres outbox and derived-document persistence for RAG indexing."""

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any, Literal
from uuid import UUID

from app.rag.documents import SearchDocument, SourceType
from app.rag.embeddings import EmbeddingProvider

Operation = Literal["refresh", "delete"]


@dataclass(frozen=True)
class OutboxClaim:
    id: int
    dataset: str
    source_type: SourceType
    source_id: str
    operation: Operation
    claim_token: UUID


@dataclass(frozen=True)
class ExistingDocument:
    content_hash: str
    embedding_model: str | None


@dataclass(frozen=True)
class IndexBatchResult:
    claimed: int = 0
    indexed: int = 0
    deleted: int = 0
    unchanged: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "indexed": self.indexed,
            "deleted": self.deleted,
            "unchanged": self.unchanged,
            "failed": self.failed,
        }


class RagIndexStore:
    """Use short Postgres transactions; never hold a DB connection during a provider request."""

    def __init__(self, database_url: str, *, batch_size: int = 32, lease_seconds: int = 900) -> None:
        self.database_url = database_url
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds

    async def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return await psycopg.AsyncConnection.connect(
            self.database_url, prepare_threshold=None, row_factory=dict_row
        )

    async def enqueue_missing_embeddings(self, limit: int) -> int:
        """Queue a bounded set of lexical-only docs when a provider becomes available."""
        async with await self._connect() as conn:
            async with conn.transaction():
                rows = await (await conn.execute(
                    """
                    with missing as (
                      select d.dataset, d.source_type, d.source_id
                      from public.bridge_rag_search_documents d
                      where d.embedding is null
                        and not exists (
                          select 1 from public.bridge_rag_search_outbox o
                          where o.dataset = d.dataset and o.source_type = d.source_type
                            and o.source_id = d.source_id and o.processed_at is null
                        )
                      order by d.dataset, d.source_type, d.source_id
                      limit %s
                      for update of d skip locked
                    )
                    insert into public.bridge_rag_search_outbox
                      (dataset, source_type, source_id, operation)
                    select dataset, source_type, source_id, 'refresh' from missing
                    on conflict (dataset, source_type, source_id) do update
                      set operation = 'refresh', queued_at = clock_timestamp(), attempts = 0,
                          locked_at = null, claim_token = null, processed_at = null,
                          last_error_code = null
                    returning id
                    """,
                    (limit,),
                )).fetchall()
        return len(rows)

    async def claim(self) -> list[OutboxClaim]:
        """Claim at most one bounded batch; stale leases become reclaimable after a crash."""
        async with await self._connect() as conn:
            async with conn.transaction():
                candidates = await (await conn.execute(
                    """
                    select id
                    from public.bridge_rag_search_outbox
                    where processed_at is null and queued_at <= clock_timestamp()
                      and (locked_at is null or locked_at < clock_timestamp() - (%s * interval '1 second'))
                    order by queued_at, id
                    limit %s
                                        for update skip locked
                    """,
                    (self.lease_seconds, self.batch_size),
                )).fetchall()
                claims: list[OutboxClaim] = []
                for candidate in candidates:
                    row = await (await conn.execute(
                        """
                        update public.bridge_rag_search_outbox
                        set locked_at = clock_timestamp(), claim_token = gen_random_uuid()
                        where id = %s
                        returning id, dataset, source_type, source_id, operation, claim_token
                        """,
                        (candidate["id"],),
                    )).fetchone()
                    if row is not None:
                        claims.append(OutboxClaim(**row))
        return claims

    async def read_sources(self, claims: list[OutboxClaim]) -> dict[tuple[str, SourceType, str], dict[str, Any]]:
        groups: dict[tuple[str, SourceType], list[str]] = defaultdict(list)
        for claim in claims:
            if claim.operation == "refresh":
                groups[(claim.dataset, claim.source_type)].append(claim.source_id)
        found: dict[tuple[str, SourceType, str], dict[str, Any]] = {}
        async with await self._connect() as conn:
            for (dataset, source_type), source_ids in groups.items():
                if source_type == "bank_transaction":
                    sql = """select txn_id as source_id, posted_date, amount, type, check_number, description
                             from public.bank_transactions where dataset = %s and txn_id = any(%s)"""
                else:
                    sql = """select entry_id as source_id, date, amount, method, check_number, account,
                                    counter_account, description, counterparty
                             from public.gl_entries where dataset = %s and entry_id = any(%s)"""
                rows = await (await conn.execute(sql, (dataset, source_ids))).fetchall()
                found.update({(dataset, source_type, row["source_id"]): row for row in rows})
        return found

    async def existing_documents(
        self, claims: list[OutboxClaim]
    ) -> dict[tuple[str, SourceType, str], ExistingDocument]:
        groups: dict[tuple[str, SourceType], list[str]] = defaultdict(list)
        for claim in claims:
            groups[(claim.dataset, claim.source_type)].append(claim.source_id)
        found: dict[tuple[str, SourceType, str], ExistingDocument] = {}
        async with await self._connect() as conn:
            for (dataset, source_type), source_ids in groups.items():
                rows = await (await conn.execute(
                    """select source_id, content_hash, embedding_model
                       from public.bridge_rag_search_documents
                       where dataset = %s and source_type = %s and source_id = any(%s)""",
                    (dataset, source_type, source_ids),
                )).fetchall()
                found.update({
                    (dataset, source_type, row["source_id"]): ExistingDocument(
                        content_hash=row["content_hash"], embedding_model=row["embedding_model"]
                    ) for row in rows
                })
        return found

    async def finish(
        self,
        claims: list[OutboxClaim],
        *,
        documents: list[tuple[SearchDocument, list[float] | None, str | None]],
        delete_keys: list[tuple[str, SourceType, str]],
        unchanged: int,
        retry_error_code: str | None = None,
        retry_keys: set[tuple[str, SourceType, str]] | None = None,
    ) -> IndexBatchResult:
        """Apply documents only for claims whose lease token is still current.

        The token check prevents a slow embedding response from overwriting a newer source change.
        On provider failure, screened lexical text is saved and only the vector work is retried.
        """
        if not claims:
            return IndexBatchResult()
        claim_by_id = {claim.id: claim for claim in claims}
        async with await self._connect() as conn:
            async with conn.transaction():
                rows = await (await conn.execute(
                    """select id, claim_token from public.bridge_rag_search_outbox
                       where id = any(%s) for update""",
                    (list(claim_by_id),),
                )).fetchall()
                active = {
                    row["id"] for row in rows
                    if (claim := claim_by_id.get(row["id"])) is not None
                    and row["claim_token"] == claim.claim_token
                }
                active_claims = [claim_by_id[i] for i in active]
                active_keys = {(c.dataset, c.source_type, c.source_id) for c in active_claims}
                write_docs = [entry for entry in documents if (
                    entry[0].dataset, entry[0].source_type, entry[0].source_id
                ) in active_keys]
                remove_keys = [key for key in delete_keys if key in active_keys]

                if remove_keys:
                    for dataset, source_type, source_id in remove_keys:
                        await conn.execute(
                            """delete from public.bridge_rag_search_documents
                               where dataset = %s and source_type = %s and source_id = %s""",
                            (dataset, source_type, source_id),
                        )
                if write_docs:
                    async with conn.cursor() as cursor:
                        await cursor.executemany(
                        """insert into public.bridge_rag_search_documents
                             (dataset, source_type, source_id, search_text, embedding,
                              embedding_model, content_hash, indexed_at)
                           values (%s, %s, %s, %s, %s::extensions.vector, %s, %s, clock_timestamp())
                           on conflict (dataset, source_type, source_id) do update set
                             search_text = excluded.search_text,
                             embedding = excluded.embedding,
                             embedding_model = excluded.embedding_model,
                             content_hash = excluded.content_hash,
                             indexed_at = excluded.indexed_at""",
                        [
                            (
                                doc.dataset, doc.source_type, doc.source_id, doc.search_text,
                                _vector_literal(vector), model, doc.content_hash,
                            )
                            for doc, vector, model in write_docs
                        ],
                        )

                retry_ids = [
                    claim.id for claim in active_claims
                    if retry_error_code is not None and retry_keys is not None
                    and (claim.dataset, claim.source_type, claim.source_id) in retry_keys
                ]
                completed_ids = list(active - set(retry_ids))
                if completed_ids:
                    await conn.execute(
                        """update public.bridge_rag_search_outbox
                           set processed_at = clock_timestamp(), locked_at = null, claim_token = null,
                               last_error_code = null
                           where id = any(%s)""",
                        (completed_ids,),
                    )
                if retry_ids and retry_error_code is not None:
                    await conn.execute(
                        """update public.bridge_rag_search_outbox
                           set attempts = attempts + 1,
                               queued_at = clock_timestamp() +
                                 (least(3600, 15 * power(2, least(attempts, 8))) * interval '1 second'),
                               locked_at = null, claim_token = null, processed_at = null,
                               last_error_code = %s
                           where id = any(%s)""",
                        (retry_error_code[:80], retry_ids),
                    )

        failed = len(retry_ids)
        if failed:
            return IndexBatchResult(claimed=len(claims), indexed=len(write_docs), deleted=len(remove_keys),
                                    unchanged=unchanged, failed=failed)
        return IndexBatchResult(claimed=len(claims), indexed=len(write_docs), deleted=len(remove_keys),
                                unchanged=unchanged + (len(claims) - len(active)))


def _vector_literal(vector: list[float] | None) -> str | None:
    if vector is None:
        return None
    return "[" + ",".join(repr(value) for value in vector) + "]"


class RagIndexWorker:
    def __init__(self, store: RagIndexStore, provider: EmbeddingProvider | None, model: str) -> None:
        self.store = store
        self.provider = provider
        self.model = model

    async def run_batch(self) -> IndexBatchResult:
        target_model = self.provider.model if self.provider is not None else self.model
        if self.provider is not None:
            await self.store.enqueue_missing_embeddings(self.store.batch_size)
        claims = await self.store.claim()
        if not claims:
            return IndexBatchResult()
        sources = await self.store.read_sources(claims)
        existing = await self.store.existing_documents(claims)
        documents: list[SearchDocument] = []
        delete_keys: list[tuple[str, SourceType, str]] = []
        unchanged = 0
        for claim in claims:
            key = (claim.dataset, claim.source_type, claim.source_id)
            row = sources.get(key)
            if claim.operation == "delete" or row is None:
                delete_keys.append(key)
                continue
            from app.rag.documents import build_search_document

            document = build_search_document(claim.dataset, claim.source_type, claim.source_id, row)
            previous = existing.get(key)
            if previous and previous.content_hash == document.content_hash and (
                self.provider is None or previous.embedding_model == target_model
            ):
                unchanged += 1
                continue
            documents.append(document)

        vectors: list[list[float] | None] = [None] * len(documents)
        error_code: str | None = None
        retry_keys: set[tuple[str, SourceType, str]] | None = None
        if self.provider is not None:
            to_embed = [
                index for index, doc in enumerate(documents)
                if existing.get((doc.dataset, doc.source_type, doc.source_id)) is None
                or existing[(doc.dataset, doc.source_type, doc.source_id)].content_hash != doc.content_hash
                or existing[(doc.dataset, doc.source_type, doc.source_id)].embedding_model != target_model
            ]
            if to_embed:
                try:
                    embedded = await self.provider.embed([documents[index].search_text for index in to_embed])
                    if len(embedded) != len(to_embed):
                        raise ValueError("embedding count mismatch")
                    if any(
                        len(vector) != self.provider.dimensions
                        or any(not math.isfinite(value) for value in vector)
                        for vector in embedded
                    ):
                        raise ValueError("embedding shape or values invalid")
                    for index, vector in zip(to_embed, embedded, strict=True):
                        vectors[index] = vector
                except Exception as exc:
                    # No exception body or provider response is persisted or logged.
                    error_code = type(exc).__name__
                    retry_keys = {
                        (documents[index].dataset, documents[index].source_type, documents[index].source_id)
                        for index in to_embed
                    }

        rows_to_write: list[tuple[SearchDocument, list[float] | None, str | None]] = []
        for document, vector in zip(documents, vectors, strict=True):
            previous = existing.get((document.dataset, document.source_type, document.source_id))
            if self.provider is not None and error_code is None:
                rows_to_write.append((document, vector, target_model))
            elif error_code is not None:
                # Preserve lexical recall while retrying unavailable/invalid embedding work.
                rows_to_write.append((document, None, None))
            elif previous is None or previous.content_hash != document.content_hash:
                rows_to_write.append((document, None, None))

        return await self.store.finish(
            claims, documents=rows_to_write, delete_keys=delete_keys, unchanged=unchanged,
            retry_error_code=error_code, retry_keys=retry_keys,
        )
