"""DbStore against a seeded Supabase database. Skipped unless DATABASE_URL is set in the environment."""

import os
from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.recon.store import DbStore

DATASET = "northbrook-2026-10"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not set")


async def test_db_store_reads_the_seeded_dataset():
    store = DbStore(DATABASE_URL)
    dataset = await store.dataset(DATASET)
    assert dataset is not None
    assert (len(dataset.bank), len(dataset.gl)) == (112, 114)
    assert dataset.balances.bank_closing_balance - dataset.balances.gl_closing_balance == Decimal("864.09")
    assert DATASET in [d.id for d in await store.datasets()]


async def test_db_store_unknown_dataset_and_run():
    store = DbStore(DATABASE_URL)
    assert await store.dataset("no-such-dataset") is None
    with pytest.raises(AppError) as err:
        await store.run_items(DATASET, "00000000-0000-0000-0000-000000000000")
    assert err.value.code == "run_not_found"
