from decimal import Decimal
from uuid import uuid4

import pytest

from app.rag.documents import SearchDocument
from app.rag.embeddings import EMBEDDING_DIMENSIONS
from app.rag.index_store import (
    ExistingDocument,
    IndexBatchResult,
    OutboxClaim,
    RagIndexWorker,
)


class FakeStore:
    batch_size = 16

    def __init__(self, *, claims, sources, existing=None):
        self.claims = claims
        self.sources = sources
        self.existing = existing or {}
        self.documents = []
        self.delete_keys = []
        self.finish_kwargs = None
        self.missing_calls = 0

    async def enqueue_missing_embeddings(self, limit):
        self.missing_calls += 1
        return 0

    async def claim(self):
        return self.claims

    async def read_sources(self, _claims):
        return self.sources

    async def existing_documents(self, _claims):
        return self.existing

    async def finish(self, claims, **kwargs):
        self.finish_kwargs = kwargs
        self.documents = kwargs["documents"]
        self.delete_keys = kwargs["delete_keys"]
        retry_keys = kwargs.get("retry_keys") or set()
        return IndexBatchResult(claimed=len(claims), indexed=len(self.documents),
                                deleted=len(self.delete_keys), unchanged=kwargs["unchanged"],
                    failed=len(retry_keys))


def _claim(source_type="bank_transaction", source_id="BANK004", operation="refresh"):
    return OutboxClaim(1, "demo", source_type, source_id, operation, uuid4())


def _bank_row():
    return {
        "source_id": "BANK004", "posted_date": "2026-10-02", "amount": Decimal("-120.00"),
        "type": "ACH", "check_number": None,
        "description": "ACH DEBIT REIMB SARAH PATEL ACCT 000123456789",
    }


class FakeEmbeddingProvider:
    model = "BAAI/bge-en-icl"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, *, fail=False):
        self.inputs = []
        self.fail = fail

    async def embed(self, texts):
        self.inputs.extend(texts)
        if self.fail:
            raise RuntimeError("provider failure with sensitive payload")
        return [[0.1] * self.dimensions for _ in texts]


async def test_worker_embeds_only_screened_text_and_persists_vector_metadata() -> None:
    claim = _claim()
    provider = FakeEmbeddingProvider()
    store = FakeStore(claims=[claim], sources={("demo", "bank_transaction", "BANK004"): _bank_row()})

    result = await RagIndexWorker(store, provider, provider.model).run_batch()

    assert "SARAH" not in provider.inputs[0]
    assert "000123456789" not in provider.inputs[0]
    assert "[PERSON]" in provider.inputs[0] and "****6789" in provider.inputs[0]
    assert result.indexed == 1 and result.failed == 0
    document, vector, model = store.documents[0]
    assert isinstance(document, SearchDocument)
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert model == provider.model
    assert store.missing_calls == 1


async def test_worker_keeps_lexical_document_when_provider_fails_and_requeues() -> None:
    claim = _claim()
    provider = FakeEmbeddingProvider(fail=True)
    store = FakeStore(claims=[claim], sources={("demo", "bank_transaction", "BANK004"): _bank_row()})

    result = await RagIndexWorker(store, provider, provider.model).run_batch()

    assert result.indexed == 1 and result.failed == 1
    document, vector, model = store.documents[0]
    assert "SARAH" not in document.search_text
    assert vector is None and model is None
    assert store.finish_kwargs["retry_error_code"] == "RuntimeError"
    assert store.finish_kwargs["retry_keys"] == {("demo", "bank_transaction", "BANK004")}


async def test_failed_embedding_does_not_retry_deletes_or_unrelated_rows() -> None:
    refresh = _claim()
    delete = _claim(source_id="BANK-OLD", operation="delete")
    provider = FakeEmbeddingProvider(fail=True)
    store = FakeStore(
        claims=[refresh, delete],
        sources={("demo", "bank_transaction", "BANK004"): _bank_row()},
    )

    result = await RagIndexWorker(store, provider, provider.model).run_batch()

    assert result.failed == 1 and result.deleted == 1
    assert store.finish_kwargs["retry_keys"] == {("demo", "bank_transaction", "BANK004")}
    assert store.delete_keys == [("demo", "bank_transaction", "BANK-OLD")]


async def test_worker_stays_lexical_when_embedding_key_is_not_configured() -> None:
    claim = _claim()
    store = FakeStore(claims=[claim], sources={("demo", "bank_transaction", "BANK004"): _bank_row()})

    result = await RagIndexWorker(store, None, "BAAI/bge-en-icl").run_batch()

    assert result.indexed == 1 and result.failed == 0
    assert store.missing_calls == 0
    document, vector, model = store.documents[0]
    assert "****6789" in document.search_text and vector is None and model is None


async def test_unchanged_document_skips_embedding_and_preserves_vector() -> None:
    claim = _claim()
    # The hash is derived from exactly the screened allowlisted text.
    from app.rag.documents import build_search_document

    document = build_search_document("demo", "bank_transaction", "BANK004", _bank_row())
    store = FakeStore(
        claims=[claim],
        sources={("demo", "bank_transaction", "BANK004"): _bank_row()},
        existing={("demo", "bank_transaction", "BANK004"): ExistingDocument(document.content_hash, "BAAI/bge-en-icl")},
    )

    result = await RagIndexWorker(store, None, "BAAI/bge-en-icl").run_batch()

    assert result.unchanged == 1
    assert store.documents == []


async def test_worker_deletes_index_for_delete_or_missing_source() -> None:
    claim = _claim(operation="delete")
    store = FakeStore(claims=[claim], sources={})

    result = await RagIndexWorker(store, None, "BAAI/bge-en-icl").run_batch()

    assert result.deleted == 1
    assert store.delete_keys == [("demo", "bank_transaction", "BANK004")]
    assert store.documents == []
