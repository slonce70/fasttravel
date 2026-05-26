"""Tests for the resilient wrapper around sitemap_long_tail_ingest.

Covers the active incident from the May 2026 audit: scheduler startup
hit `httpx.ConnectError: [Errno -5] No address associated with hostname`
and the job died until the next weekly Sunday tick.

The wrapper must:
  1. Retry transient network errors with exponential backoff.
  2. Record final failure in scrape_runs so monitoring can alert.
  3. Never re-raise — APScheduler must keep running.
"""

from __future__ import annotations

import socket
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.jobs import sitemap_long_tail as sl


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse exponential backoff to zero — tests should run in ms not
    minutes. The retry-count semantics still get exercised."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(sl.asyncio, "sleep", _no_sleep)


@pytest.fixture
def fake_record_run(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch _record_sitemap_run so tests don't need a live DB."""
    mock = AsyncMock()
    monkeypatch.setattr(sl, "_record_sitemap_run", mock)
    return mock


async def test_succeeds_first_attempt(fake_record_run: AsyncMock) -> None:
    """Happy path — single call to inner, success, NO scrape_runs failure row."""
    inner = AsyncMock(return_value=42)
    with patch.object(sl, "sitemap_long_tail_ingest", inner):
        result = await sl.sitemap_long_tail_ingest_resilient()

    assert result == 42
    assert inner.await_count == 1
    fake_record_run.assert_not_awaited()


async def test_retries_on_dns_failure_then_succeeds(
    fake_record_run: AsyncMock,
) -> None:
    """Reproduces the live incident: 2x DNS errors then success on attempt 3."""
    inner = AsyncMock(
        side_effect=[
            httpx.ConnectError("[Errno -5] No address associated with hostname"),
            socket.gaierror("DNS still flapping"),
            17,
        ]
    )
    with patch.object(sl, "sitemap_long_tail_ingest", inner):
        result = await sl.sitemap_long_tail_ingest_resilient()

    assert result == 17
    assert inner.await_count == 3
    fake_record_run.assert_not_awaited()  # eventual success — no failure row


async def test_exhausts_retries_records_failure_returns_zero(
    fake_record_run: AsyncMock,
) -> None:
    """5 consecutive DNS errors → record failure, return 0, never raise."""
    inner = AsyncMock(side_effect=httpx.ConnectError("DNS down for the entire window"))
    with patch.object(sl, "sitemap_long_tail_ingest", inner):
        result = await sl.sitemap_long_tail_ingest_resilient(max_attempts=5)

    assert result == 0
    assert inner.await_count == 5
    fake_record_run.assert_awaited_once()
    args, kwargs = fake_record_run.await_args
    # First positional is status="failed"
    assert args[0] == "failed" or kwargs.get("status") == "failed"
    # rows_inserted=0 — second positional
    if len(args) >= 2:
        assert args[1] == 0
    # error must mention exhausted_retries for downstream alert filtering
    error_field = args[2] if len(args) >= 3 else kwargs.get("error", "")
    assert "exhausted_retries" in error_field


async def test_non_transient_error_records_and_does_not_retry(
    fake_record_run: AsyncMock,
) -> None:
    """ValueError (programming error) → record immediately, no retry, no raise."""
    inner = AsyncMock(side_effect=ValueError("schema drift, parser broken"))
    with patch.object(sl, "sitemap_long_tail_ingest", inner):
        result = await sl.sitemap_long_tail_ingest_resilient()

    assert result == 0
    assert inner.await_count == 1  # NOT retried
    fake_record_run.assert_awaited_once()


async def test_never_raises(fake_record_run: AsyncMock) -> None:
    """Hard contract: APScheduler MUST NOT see an exception.

    Even if _record_sitemap_run itself blows up, the wrapper swallows.
    """
    inner = AsyncMock(side_effect=httpx.ConnectError("dns"))
    # Simulate scrape_runs INSERT itself failing — wrapper still must not raise.
    fake_record_run.side_effect = RuntimeError("postgres also down")
    with patch.object(sl, "sitemap_long_tail_ingest", inner):
        # Critically: no pytest.raises here. If this throws, test FAILS.
        result = await sl.sitemap_long_tail_ingest_resilient(max_attempts=2)
    assert result == 0


async def test_record_sitemap_run_swallows_db_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_record_sitemap_run wraps its DB INSERT in try/except so a DB outage
    cannot crash the scheduler. The contract: log + return None.
    """

    class BrokenSessionFactory:
        def __call__(self) -> object:
            raise RuntimeError("postgres unreachable")

    monkeypatch.setattr(sl, "async_session_factory", BrokenSessionFactory())

    # No raise expected.
    await sl._record_sitemap_run("failed", 0, "test")


async def test_backoff_delays_increase(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sleep should be called with monotonically non-decreasing delays
    (exponential up to max_delay_s)."""
    delays: list[float] = []

    async def _capture_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(sl.asyncio, "sleep", _capture_sleep)

    inner = AsyncMock(side_effect=httpx.ConnectError("dns"))
    with (
        patch.object(sl, "sitemap_long_tail_ingest", inner),
        patch.object(sl, "_record_sitemap_run", AsyncMock()),
    ):
        await sl.sitemap_long_tail_ingest_resilient(
            max_attempts=4, base_delay_s=1.0, max_delay_s=8.0
        )

    # 4 attempts → 3 sleeps between them (no sleep after final failure).
    assert delays == [1.0, 2.0, 4.0]


async def test_record_started_at_is_set(
    fake_record_run: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """started_at must reflect the wrapper's start time, not each retry's
    individual time — so the scrape_runs duration covers the full window."""
    inner = AsyncMock(side_effect=httpx.ConnectError("dns"))
    with patch.object(sl, "sitemap_long_tail_ingest", inner):
        before = datetime.now(sl.UTC)
        await sl.sitemap_long_tail_ingest_resilient(max_attempts=3)
        after = datetime.now(sl.UTC)

    args, kwargs = fake_record_run.await_args
    started_at = args[3] if len(args) >= 4 else kwargs.get("started_at")
    assert started_at is not None
    assert before <= started_at <= after


def test_already_ingested_only_skips_completed_price_probes() -> None:
    sql = str(sl._ALREADY_INGESTED_SQL)

    assert "last_priced_at IS NOT NULL" in sql
