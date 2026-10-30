"""Hybrid search over the derived Supabase index with a CSV/memory fallback."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import logging
import math
import re
from typing import Any

from app.core.config import Settings
from app.guardrails import screen_text
from app.guardrails.callouts import bank_guardrail, gl_guardrail
from app.rag.documents import SearchDocument, SourceType, build_search_document
from app.rag.embeddings import EmbeddingProvider, get_embedding_provider
from app.recon.models import Dataset
from app.recon.run_store import get_run_store
from app.recon.store import read_store
from app.schemas.runs import Item

log = logging.getLogger(__name__)
RRF_K = 60
SEARCH_POOL = 50
MAX_RESULTS = 25
MAX_QUERY_LENGTH = 500
VECTOR_MIN_SIMILARITY = 0.45
_LOCAL_VECTORS: dict[tuple[str, str], list[float]] = {}
_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_SOURCE_ID = re.compile(r"\b(?:BANK|GL)[A-Z0-9_-]+\b", re.IGNORECASE)


@dataclass(frozen=True)
class SearchFilters:
    dataset: str
    source_type: SourceType | None = None
    date_from: date | None = None
    date_to: date | None = None
    amount: Decimal | None = None
    status: str | None = None


@dataclass(frozen=True)
class _Candidate:
    document: SearchDocument
    row: dict[str, Any]
    item: Item | None


def _limit(value: int) -> int:
    return min(MAX_RESULTS, max(1, value))


def _vector_literal(vector: Sequence[float] | None) -> str | None:
    if vector is None:
        return None
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("query embedding must contain only finite numbers")
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _query_tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(text) if len(token) > 1}


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)


def _fuse(ranks: dict[str, dict[tuple[str, str, str], int]]) -> list[tuple[tuple[str, str, str], float, list[str]]]:
    scores: dict[tuple[str, str, str], float] = defaultdict(float)
    methods: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for method, ranked in ranks.items():
        for key, rank in ranked.items():
            scores[key] += 1 / (RRF_K + rank)
            methods[key].append(method)
    return sorted(((key, score, methods[key]) for key, score in scores.items()),
                  key=lambda result: (-result[1], result[0]))


def _item_for_source(items: Sequence[Item], source_type: SourceType, source_id: str) -> Item | None:
    for item in reversed(items):
        ids = item.bank_ids if source_type == "bank_transaction" else item.gl_ids
        if source_id in ids:
            return item
    return None


def _row_dict(row: object) -> dict[str, Any]:
    return row.model_dump()  # type: ignore[attr-defined]


def _passes_filters(row: dict[str, Any], source_type: SourceType, filters: SearchFilters, item: Item | None) -> bool:
    if filters.source_type is not None and filters.source_type != source_type:
        return False
    row_date = row["posted_date"] if source_type == "bank_transaction" else row["date"]
    if filters.date_from is not None and row_date < filters.date_from:
        return False
    if filters.date_to is not None and row_date > filters.date_to:
        return False
    if filters.amount is not None and row["amount"] != filters.amount:
        return False
    status = item.status if item is not None else "unmatched"
    return filters.status is None or status == filters.status


def _local_result(candidate: _Candidate, *, score: float, matched_by: list[str]) -> dict[str, Any]:
    source_type = candidate.document.source_type
    row = candidate.row
    if source_type == "bank_transaction":
        source = {
            "source_type": source_type, "source_id": candidate.document.source_id,
            "date": row["posted_date"].isoformat(), "amount": str(row["amount"]),
            "description": row["description"], "type": row["type"],
            "check_number": row["check_number"],
            "running_balance": str(row["running_balance"]) if row["running_balance"] is not None else None,
            "account": None, "counter_account": None, "counterparty": None,
            "guardrail": bank_guardrail(row["description"]).model_dump(),
        }
    else:
        source = {
            "source_type": source_type, "source_id": candidate.document.source_id,
            "date": row["date"].isoformat(), "amount": str(row["amount"]),
            "description": row["description"], "type": row["method"],
            "check_number": row["check_number"], "running_balance": None,
            "account": row["account"], "counter_account": row["counter_account"],
            "counterparty": row["counterparty"],
            "guardrail": gl_guardrail(row["description"], row["counterparty"]).model_dump(),
        }
    return {
        "source": source,
        "status": candidate.item.status if candidate.item else "unmatched",
        "item": candidate.item.model_dump(mode="json") if candidate.item else None,
        "score": score,
        "matched_by": matched_by,
    }


async def search_local(
    dataset: Dataset,
    items: Sequence[Item],
    query: str,
    filters: SearchFilters,
    *,
    provider: EmbeddingProvider | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Search the local CSV/memory dataset; document vectors are cached in process memory."""
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError("query is too long")
    screened_query = screen_text(query).text.strip()
    if not screened_query:
        return []

    candidates: list[_Candidate] = []
    for row in dataset.bank:
        data = _row_dict(row)
        item = _item_for_source(items, "bank_transaction", row.txn_id)
        if _passes_filters(data, "bank_transaction", filters, item):
            document = build_search_document(dataset.id, "bank_transaction", row.txn_id, data)
            candidates.append(_Candidate(document, data, item))
    for row in dataset.gl:
        data = _row_dict(row)
        item = _item_for_source(items, "gl_entry", row.entry_id)
        if _passes_filters(data, "gl_entry", filters, item):
            document = build_search_document(dataset.id, "gl_entry", row.entry_id, data)
            candidates.append(_Candidate(document, data, item))

    ranks: dict[str, dict[tuple[str, str, str], int]] = {}
    requested_ids = {match.group(0).casefold() for match in _SOURCE_ID.finditer(screened_query)}
    exact = [candidate for candidate in candidates if (
        candidate.document.source_id.casefold() in requested_ids
        or screened_query.casefold() == candidate.document.source_id.casefold()
        or screened_query.casefold() in candidate.document.search_text.casefold()
    )]
    exact.sort(key=lambda candidate: (
        candidate.document.source_id.casefold() not in requested_ids
        and candidate.document.source_id.casefold() != screened_query.casefold(),
        candidate.document.search_text.casefold().find(screened_query.casefold()),
        candidate.document.source_id,
    ))
    ranks["exact"] = {
        (candidate.document.dataset, candidate.document.source_type, candidate.document.source_id): rank
        for rank, candidate in enumerate(exact[:SEARCH_POOL], start=1)
    }

    tokens = _query_tokens(screened_query)
    lexical: list[tuple[_Candidate, float]] = []
    if tokens:
        for candidate in candidates:
            overlap = len(tokens & _query_tokens(candidate.document.search_text))
            if overlap:
                lexical.append((candidate, overlap / len(tokens)))
    lexical.sort(key=lambda match: (-match[1], match[0].document.source_id))
    ranks["full_text"] = {
        (candidate.document.dataset, candidate.document.source_type, candidate.document.source_id): rank
        for rank, (candidate, _score) in enumerate(lexical[:SEARCH_POOL], start=1)
    }

    if provider is not None and candidates:
        try:
            query_vectors = await provider.embed([screened_query])
            if len(query_vectors) != 1 or len(query_vectors[0]) != provider.dimensions:
                raise ValueError("invalid query embedding shape")
            query_vector = query_vectors[0]
            missing: list[_Candidate] = []
            for candidate in candidates:
                if (provider.model, candidate.document.content_hash) not in _LOCAL_VECTORS:
                    missing.append(candidate)
            for offset in range(0, len(missing), 32):
                chunk = missing[offset:offset + 32]
                vectors = await provider.embed([candidate.document.search_text for candidate in chunk])
                if len(vectors) != len(chunk):
                    raise ValueError("document embedding count mismatch")
                for candidate, vector in zip(chunk, vectors, strict=True):
                    if len(vector) == provider.dimensions and all(math.isfinite(value) for value in vector):
                        _LOCAL_VECTORS[(provider.model, candidate.document.content_hash)] = vector
            similarities = []
            for candidate in candidates:
                vector = _LOCAL_VECTORS.get((provider.model, candidate.document.content_hash))
                similarity = _cosine(query_vector, vector) if vector is not None else -1.0
                if similarity >= VECTOR_MIN_SIMILARITY:
                    similarities.append((candidate, similarity))
            similarities.sort(key=lambda match: (-match[1], match[0].document.source_id))
            ranks["vector"] = {
                (candidate.document.dataset, candidate.document.source_type, candidate.document.source_id): rank
                for rank, (candidate, _similarity) in enumerate(similarities[:SEARCH_POOL], start=1)
            }
        except Exception as exc:
            log.warning("Local RAG embedding search unavailable: %s", type(exc).__name__)

    lookup = {
        (candidate.document.dataset, candidate.document.source_type, candidate.document.source_id): candidate
        for candidate in candidates
    }
    return [
        _local_result(lookup[key], score=score, matched_by=matched_by)
        for key, score, matched_by in _fuse(ranks)[:_limit(limit)]
    ]


class RagSearchService:
    def __init__(self, settings: Settings, provider: EmbeddingProvider | None = None) -> None:
        self.settings = settings
        self.provider = provider if provider is not None else get_embedding_provider(settings)

    async def search(self, filters: SearchFilters, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        if not filters.dataset.strip():
            raise ValueError("dataset is required")
        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError("query is too long")
        if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
            raise ValueError("date_from must not be after date_to")
        if self.settings.database_url:
            return await self._search_postgres(filters, query, limit)
        dataset = await read_store(self.settings).dataset(filters.dataset)
        if dataset is None:
            return []
        runs = get_run_store(self.settings)
        run_id = await runs.latest_run_id(dataset.id)
        items = await runs.list_items(run_id) if run_id is not None else []
        return await search_local(dataset, items, query, filters, provider=self.provider, limit=limit)

    async def dataset_exists(self, dataset_id: str) -> bool:
        if self.settings.database_url:
            async with await self._connect() as conn:
                row = await (await conn.execute(
                    "select 1 from public.balances where dataset = %s limit 1", (dataset_id,)
                )).fetchone()
            return row is not None
        return await read_store(self.settings).dataset(dataset_id) is not None

    async def _search_postgres(self, filters: SearchFilters, query: str, limit: int) -> list[dict[str, Any]]:
        screened_query = screen_text(query).text.strip()
        if not screened_query:
            return []
        query_vector: list[float] | None = None
        if self.provider is not None:
            try:
                result = await self.provider.embed([screened_query])
                if (len(result) == 1 and len(result[0]) == self.provider.dimensions
                        and all(math.isfinite(value) for value in result[0])):
                    query_vector = result[0]
            except Exception as exc:
                log.warning("Postgres RAG embedding search unavailable: %s", type(exc).__name__)
        params = (
            filters.dataset, screened_query, _vector_literal(query_vector),
            self.provider.model if self.provider is not None and query_vector is not None else None,
            filters.date_from, filters.date_to, filters.amount, filters.source_type, filters.status,
            [match.group(0) for match in _SOURCE_ID.finditer(screened_query)], _limit(limit),
        )
        async with await self._connect() as conn:
            rows = await (await conn.execute(_HYBRID_SEARCH_SQL, params)).fetchall()
        return [_postgres_result(row) for row in rows]

    async def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return await psycopg.AsyncConnection.connect(
            self.settings.database_url, prepare_threshold=None, row_factory=dict_row
        )


def _postgres_result(row: dict[str, Any]) -> dict[str, Any]:
    source_type: SourceType = row["source_type"]
    description = row["description"]
    counterparty = row["counterparty"]
    source = {
        "source_type": source_type, "source_id": row["source_id"],
        "date": row["source_date"].isoformat(), "amount": str(row["source_amount"]),
        "description": description, "type": row["type_label"],
        "check_number": row["check_number"],
        "running_balance": str(row["running_balance"]) if row["running_balance"] is not None else None,
        "account": row["account"], "counter_account": row["counter_account"],
        "counterparty": counterparty,
        "guardrail": (
            bank_guardrail(description).model_dump() if source_type == "bank_transaction"
            else gl_guardrail(description, counterparty).model_dump()
        ),
    }
    item = None
    if row["item_id"] is not None:
        entry = None
        if row["entry_id"] is not None:
            entry = {
                "id": row["entry_id"], "debit_account": row["debit_account"],
                "credit_account": row["credit_account"], "amount": str(row["entry_amount"]),
                "memo": row["memo"], "status": row["entry_status"],
            }
        item = {
            "id": row["item_id"], "run_id": row["run_id"], "kind": row["kind"],
            "status": row["item_status"], "amount_delta": str(row["amount_delta"]),
            "reasoning": row["reasoning"], "evidence": row["evidence"], "flags": row["flags"],
            "model": row["model"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            "proposed_entry": entry,
        }
    return {"source": source, "status": row["item_status"] or "unmatched", "item": item,
            "score": float(row["score"]), "matched_by": row["matched_by"]}


_HYBRID_SEARCH_SQL = """
with query_input as (
  select %s::text as dataset, %s::text as query_text,
         %s::extensions.vector as query_embedding, %s::text as embedding_model,
         %s::date as date_from, %s::date as date_to, %s::numeric as amount,
         %s::text as source_type, %s::text as status, %s::text[] as source_ids
), eligible as not materialized (
  select sd.dataset, sd.source_type, sd.source_id, sd.search_text, sd.search_tsv,
         sd.embedding, sd.embedding_model, b.posted_date as source_date, b.amount as source_amount,
         b.description, b.type as type_label, b.check_number, b.running_balance,
         null::text as account, null::text as counter_account, null::text as counterparty
  from public.bridge_rag_search_documents sd
  join public.bank_transactions b on b.dataset = sd.dataset and b.txn_id = sd.source_id
  cross join query_input q
  where sd.dataset = q.dataset and sd.source_type = 'bank_transaction'
    and (q.source_type is null or q.source_type = sd.source_type)
    and (q.date_from is null or b.posted_date >= q.date_from)
    and (q.date_to is null or b.posted_date <= q.date_to)
    and (q.amount is null or b.amount = q.amount)
  union all
  select sd.dataset, sd.source_type, sd.source_id, sd.search_text, sd.search_tsv,
         sd.embedding, sd.embedding_model, g.date as source_date, g.amount as source_amount,
         g.description, g.method as type_label, g.check_number, null::numeric as running_balance,
         g.account, g.counter_account, g.counterparty
  from public.bridge_rag_search_documents sd
  join public.gl_entries g on g.dataset = sd.dataset and g.entry_id = sd.source_id
  cross join query_input q
  where sd.dataset = q.dataset and sd.source_type = 'gl_entry'
    and (q.source_type is null or q.source_type = sd.source_type)
    and (q.date_from is null or g.date >= q.date_from)
    and (q.date_to is null or g.date <= q.date_to)
    and (q.amount is null or g.amount = q.amount)
), exact_hits as (
  select e.dataset, e.source_type, e.source_id,
         row_number() over (
                     order by (lower(e.source_id) = any(array(
                                            select lower(id) from unnest(q.source_ids) as requested(id)
                                        ))) desc,
                    position(lower(q.query_text) in lower(e.search_text)), e.source_type, e.source_id
         ) as rank
  from eligible e cross join query_input q
    where lower(e.source_id) = any(array(
                    select lower(id) from unnest(q.source_ids) as requested(id)
                ))
         or lower(e.source_id) = lower(q.query_text)
     or position(lower(q.query_text) in lower(e.search_text)) > 0
  order by rank limit 50
), lexical_hits as (
  select e.dataset, e.source_type, e.source_id,
         row_number() over (
           order by ts_rank_cd(e.search_tsv, websearch_to_tsquery('simple', q.query_text)) desc,
                    e.source_type, e.source_id
         ) as rank
  from eligible e cross join query_input q
  where e.search_tsv @@ websearch_to_tsquery('simple', q.query_text)
  order by rank limit 50
), vector_hits as (
  select e.dataset, e.source_type, e.source_id,
         row_number() over (order by e.embedding <=> q.query_embedding, e.source_type, e.source_id) as rank
  from eligible e cross join query_input q
  where q.query_embedding is not null and e.embedding is not null
    and e.embedding_model = q.embedding_model
    and 1 - (e.embedding <=> q.query_embedding) >= 0.45
  order by e.embedding <=> q.query_embedding limit 50
), ranked as (
  select dataset, source_type, source_id, rank, 'exact'::text as method from exact_hits
  union all
  select dataset, source_type, source_id, rank, 'full_text'::text as method from lexical_hits
  union all
  select dataset, source_type, source_id, rank, 'vector'::text as method from vector_hits
), fused as (
  select dataset, source_type, source_id, sum(1.0 / (60 + rank)) as score,
         array_agg(distinct method order by method) as matched_by
  from ranked group by dataset, source_type, source_id
)
select e.dataset, e.source_type, e.source_id, e.source_date, e.source_amount,
       e.description, e.type_label, e.check_number, e.running_balance, e.account,
       e.counter_account, e.counterparty, f.score, f.matched_by,
       i.id::text as item_id, i.run_id::text as run_id, i.kind, i.status as item_status,
       i.amount_delta, i.reasoning, i.evidence, i.flags, i.model, i.confidence::float as confidence,
       pe.id::text as entry_id, pe.debit_account, pe.credit_account, pe.entry_amount,
       pe.memo, pe.status as entry_status
from fused f
join eligible e using (dataset, source_type, source_id)
left join lateral (
  select i.id, i.run_id, i.kind, i.status, i.amount_delta, i.reasoning, i.evidence, i.flags,
         i.model, i.confidence
  from public.items i
  join public.runs r on r.id = i.run_id
  where r.dataset = e.dataset and r.status in ('running', 'completed')
    and r.id = (select latest.id from public.runs latest
                where latest.dataset = e.dataset and latest.status in ('running', 'completed')
                order by latest.created_at desc limit 1)
    and ((e.source_type = 'bank_transaction' and e.source_id = any(i.bank_ids))
      or (e.source_type = 'gl_entry' and e.source_id = any(i.gl_ids)))
  order by i.created_at desc, i.id limit 1
) i on true
left join lateral (
    select p.id, p.status,
                 coalesce(d.o->>'debit_account', p.debit_account) as debit_account,
                 coalesce(d.o->>'credit_account', p.credit_account) as credit_account,
                 coalesce((d.o->>'amount')::numeric(14,2), p.amount) as entry_amount,
                 coalesce(d.o->>'memo', p.memo) as memo
    from public.proposed_entries p
  left join lateral (
    select entry_override as o from public.decisions x
    where x.item_id = i.id order by x.created_at desc limit 1
  ) d on true
    where p.item_id = i.id order by p.created_at desc limit 1
) pe on true
cross join query_input q
where q.status is null or coalesce(i.status, 'unmatched') = q.status
order by f.score desc, e.source_date desc, e.source_type, e.source_id
limit %s
"""
