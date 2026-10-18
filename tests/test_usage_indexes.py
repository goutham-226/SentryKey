# tests/test_usage_indexes.py

# Test the usage_records indexes exist and are used by the ledger queries.

import pytest
from sqlalchemy import text

from app.db import engine

"""
Test if the migrations created both usage_records indexes.
"""
async def test_usage_record_indexes_exist():
    async with engine.connect() as db:
        result = await db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'usage_records'"))
        indexes = set(result.scalars().all())

    assert 'ix_usage_records_api_key_id_requested_at' in indexes
    assert 'ix_usage_records_reserved_requested_at' in indexes

"""
Test if each ledger query can use its index.

the test table is tiny, so Postgres would pick a sequential scan anyway ->
seqscans are turned off for the transaction to check the index is usable at all.

the quota SUMs (get_total_tokens, trim_message_history) -> the composite index.
the reservation sweep (release_stale_reservations) -> the partial 'Reserved' index.
"""
@pytest.mark.parametrize('query, index', [
    ("SELECT coalesce(sum(prompt_tokens + completion_tokens), 0) FROM usage_records "
     "WHERE api_key_id = 1 AND requested_at > now() - INTERVAL '1 day'",
     'ix_usage_records_api_key_id_requested_at'),
    ("SELECT coalesce(sum(context_tokens), 0) FROM usage_records "
     "WHERE api_key_id = 1 AND requested_at > now() - INTERVAL '1 day'",
     'ix_usage_records_api_key_id_requested_at'),
    ("UPDATE usage_records SET status = 'Expired' "
     "WHERE status = 'Reserved' AND requested_at < now() - INTERVAL '15 minutes'",
     'ix_usage_records_reserved_requested_at'),
])
async def test_ledger_queries_use_indexes(query, index):
    async with engine.connect() as db:
        async with db.begin():
            await db.execute(text('SET LOCAL enable_seqscan = off'))
            plan = '\n'.join((await db.execute(text(f'EXPLAIN {query}'))).scalars().all())
            await db.rollback()

    assert index in plan
