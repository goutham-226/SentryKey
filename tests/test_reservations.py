# tests/test_reservations.py

# Test releasing reservations abandoned by a crashed worker.

import asyncio
from datetime import timedelta

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import ApiKeys, UsageRecords
from app.services.provider_service import release_stale_reservations, sweep_stale_reservations

"""
Insert a usage record for the test api_key,
requested age_minutes ago, and return its id.

the api_key fixture creates the only key in the database,
so its id is read straight from api_keys.
"""
async def add_usage_record(status: str, age_minutes: int) -> int:
    async with SessionLocal() as db:
        key_id = (await db.execute(select(ApiKeys.id))).scalar_one()
        row = UsageRecords(
            api_key_id=key_id,
            prompt_tokens=100,
            completion_tokens=500,
            context_tokens=50,
            status=status,
            status_code=429 if status == 'Reserved' else 200,
            requested_at=func.now() - timedelta(minutes=age_minutes),
        )
        db.add(row)
        await db.commit()
        return row.id

async def get_usage_record(row_id: int) -> UsageRecords:
    async with SessionLocal() as db:
        return (await db.execute(select(UsageRecords).where(UsageRecords.id == row_id))).scalar_one()

"""
Test if a reservation older than the timeout
is released to 0 tokens with status 'Expired'.
"""
async def test_stale_reservation_is_released(api_key):
    row_id = await add_usage_record(status='Reserved', age_minutes=30)

    async with SessionLocal() as db:
        released = await release_stale_reservations(older_than=timedelta(minutes=15), db=db)

    assert released == 1
    row = await get_usage_record(row_id)
    assert row.status == 'Expired'
    assert row.status_code == 500
    assert (row.prompt_tokens, row.completion_tokens, row.context_tokens) == (0, 0, 0)

"""
Test if a reservation younger than the timeout
is left alone -> its request may still be running.
"""
async def test_fresh_reservation_is_kept(api_key):
    row_id = await add_usage_record(status='Reserved', age_minutes=1)

    async with SessionLocal() as db:
        released = await release_stale_reservations(older_than=timedelta(minutes=15), db=db)

    assert released == 0
    row = await get_usage_record(row_id)
    assert row.status == 'Reserved'
    assert (row.prompt_tokens, row.completion_tokens, row.context_tokens) == (100, 500, 50)

"""
Test if an old settled row is never touched,
only rows still 'Reserved' are released.
"""
async def test_settled_row_is_kept(api_key):
    row_id = await add_usage_record(status='Completed', age_minutes=30)

    async with SessionLocal() as db:
        released = await release_stale_reservations(older_than=timedelta(minutes=15), db=db)

    assert released == 0
    row = await get_usage_record(row_id)
    assert row.status == 'Completed'
    assert (row.prompt_tokens, row.completion_tokens, row.context_tokens) == (100, 500, 50)

"""
Test if the background sweeper releases a stale reservation
on its first pass, and stops cleanly when cancelled.
"""
async def test_sweeper_releases_on_first_pass(api_key):
    row_id = await add_usage_record(status='Reserved', age_minutes=30)

    sweeper = asyncio.create_task(sweep_stale_reservations(
        interval_seconds=60,
        older_than=timedelta(minutes=15),
        session_factory=SessionLocal,
    ))
    try:
        for _ in range(50):
            if (await get_usage_record(row_id)).status == 'Expired':
                break
            await asyncio.sleep(0.05)
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass

    assert (await get_usage_record(row_id)).status == 'Expired'
