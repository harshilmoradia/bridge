from datetime import date
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.rag.search import (
    MAX_RESULTS,
    RagSearchService,
    SearchFilters,
    _HYBRID_SEARCH_SQL,
    search_local,
)
from app.recon.models import Balances, BankTxn, Dataset, GlEntry
from app.schemas.runs import Item


def _dataset() -> Dataset:
    return Dataset(
        id="demo",
        balances=Balances(
            company="Demo Co", cash_account="1010", period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31), bank_opening_balance=Decimal("0"),
            bank_closing_balance=Decimal("100"), gl_opening_balance=Decimal("0"),
            gl_closing_balance=Decimal("100"),
        ),
        bank=(
            BankTxn(txn_id="BANK-FEE", posted_date=date(2026, 10, 2),
                    description="MONTHLY SERVICE CHARGE", amount=Decimal("-25.00"), type="ACH"),
            BankTxn(txn_id="BANK-RENT", posted_date=date(2026, 10, 3),
                    description="OFFICE RENT PAYMENT", amount=Decimal("-500.00"), type="ACH"),
        ),
        gl=(
            GlEntry(entry_id="GL-FEE", date=date(2026, 10, 2),
                    description="Bank service charge", amount=Decimal("-25.00"), method="ACH",
                    account="6800", counter_account="1010"),
        ),
    )


class MeaningProvider:
    model = "test-meaning-v1"
    dimensions = 2

    def __init__(self):
        self.inputs: list[str] = []

    async def embed(self, texts):
        self.inputs.extend(texts)
        vectors = []
        for text in texts:
            lowered = text.casefold()
            vectors.append([1.0, 0.0] if any(word in lowered for word in ("fee", "service charge")) else [0.0, 1.0])
        return vectors


class NullProvider:
    model = "test"
    dimensions = 2

    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _pending_item() -> Item:
    return Item(
        id="item-pending", run_id="run-1", kind="bank_fee_missing_in_gl", resolution="escalate",
        status="needs_approval", bank_ids=["BANK-FEE"], gl_ids=[], amount_delta=Decimal("-25.00"),
        reasoning="Review fee", evidence=[], flags=[], model=None, confidence=None, rule_id=None,
        proposed_entry=None, created_at="2026-10-04T00:00:00Z",
    )


async def test_hybrid_local_search_finds_related_wording() -> None:
    provider = MeaningProvider()
    results = await search_local(
        _dataset(), [], "bank fee", SearchFilters(dataset="demo"), provider=provider,
    )

    assert results
    assert results[0]["source"]["source_id"] in {"BANK-FEE", "GL-FEE"}
    assert "vector" in results[0]["matched_by"]
    assert any("service charge" in text.casefold() for text in provider.inputs)


async def test_local_search_exact_id_ranks_first() -> None:
    results = await search_local(_dataset(), [], "Find transaction BANK-RENT", SearchFilters(dataset="demo"))
    assert results[0]["source"]["source_id"] == "BANK-RENT"
    assert "exact" in results[0]["matched_by"]


async def test_local_search_applies_date_amount_source_and_status_filters() -> None:
    results = await search_local(
        _dataset(), [_pending_item()], "fee",
        SearchFilters(
            dataset="demo", source_type="bank_transaction",
            date_from=date(2026, 10, 2), date_to=date(2026, 10, 2),
            amount=Decimal("-25.00"), status="needs_approval",
        ),
    )
    assert [r["source"]["source_id"] for r in results] == ["BANK-FEE"]
    assert results[0]["status"] == "needs_approval"
    assert results[0]["item"]["id"] == "item-pending"


async def test_local_search_honors_unmatched_status() -> None:
    results = await search_local(
        _dataset(), [_pending_item()], "fee",
        SearchFilters(dataset="demo", status="unmatched"),
    )
    assert all(result["source"]["source_id"] != "BANK-FEE" for result in results)


async def test_local_search_is_lexical_when_embedding_provider_fails() -> None:
    class FailureProvider:
        model = "broken"
        dimensions = 2

        async def embed(self, _texts):
            raise RuntimeError("never echo sensitive request text")

    results = await search_local(
        _dataset(), [], "MONTHLY SERVICE CHARGE", SearchFilters(dataset="demo"), provider=FailureProvider(),
    )
    assert results[0]["source"]["source_id"] == "BANK-FEE"
    assert results[0]["matched_by"] == ["exact", "full_text"]


async def test_local_search_limits_results_and_rejects_long_queries() -> None:
    results = await search_local(_dataset(), [], "fee", SearchFilters(dataset="demo"), limit=MAX_RESULTS + 100)
    assert len(results) <= MAX_RESULTS
    with pytest.raises(ValueError, match="too long"):
        await search_local(_dataset(), [], "x" * 501, SearchFilters(dataset="demo"))


def test_postgres_query_uses_rrf_current_source_rows_and_live_latest_run_status() -> None:
    assert "sum(1.0 / (60 + rank))" in _HYBRID_SEARCH_SQL
    assert "websearch_to_tsquery('simple'" in _HYBRID_SEARCH_SQL
    assert "extensions.vector" in _HYBRID_SEARCH_SQL
    assert "join public.bank_transactions" in _HYBRID_SEARCH_SQL
    assert "join public.gl_entries" in _HYBRID_SEARCH_SQL
    assert "order by latest.created_at desc limit 1" in _HYBRID_SEARCH_SQL
    assert "coalesce((d.o->>'amount')::numeric" in _HYBRID_SEARCH_SQL
    assert "q.status is null or coalesce(i.status, 'unmatched') = q.status" in _HYBRID_SEARCH_SQL


async def test_service_rejects_reversed_date_range() -> None:
    service = RagSearchService.__new__(RagSearchService)
    service.settings = None
    service.provider = None
    with pytest.raises(ValueError, match="date_from"):
        await service.search(
            SearchFilters(dataset="demo", date_from=date(2026, 10, 5), date_to=date(2026, 10, 1)),
            "fee",
        )


async def test_postgres_search_passes_typed_filters_in_placeholder_order() -> None:
    settings = Settings(_env_file=None, database_url="postgres://unused")
    service = RagSearchService(settings, provider=None)
    captured: dict = {}

    class Cursor:
        async def fetchall(self):
            return []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return Cursor()

    async def connect():
        return Connection()

    service._connect = connect
    result = await service.search(
        SearchFilters(
            dataset="demo", source_type="gl_entry", date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 31), amount=Decimal("-25.00"), status="needs_approval",
        ),
        "bank service fee", limit=7,
    )

    assert result == []
    assert captured["sql"].count("%s") == 11
    assert captured["params"] == (
        "demo", "bank service fee", None, None,
        date(2026, 10, 1), date(2026, 10, 31), Decimal("-25.00"),
        "gl_entry", "needs_approval", [], 7,
    )
