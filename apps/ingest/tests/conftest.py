"""Shared pytest fixtures for apps/ingest tests.

We deliberately keep this lean — DB integration tests live in
apps/scheduler (which actually owns the snapshot job). Here we
test pure logic: normalizers, dedup, client circuit breakers.
"""
from __future__ import annotations

import pytest
from fakeredis.aioredis import FakeRedis


@pytest.fixture
async def redis():
    """Per-test isolated FakeRedis. The fake honours TTLs and SET NX EX,
    which is everything dedup.py and farvater_scraper.py care about."""
    client = FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()
