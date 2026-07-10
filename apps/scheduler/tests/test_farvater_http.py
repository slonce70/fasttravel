"""Tests for the production-tier FarvaterProdClient.

This is critical infra — without tests, the breaker / cap / throttle
guards are claims, not facts. The Sprint 3.8 backfill makes them
verifiable.

We stub the actual HTTP call by patching `httpx.AsyncClient.post` so
we don't make any network requests; the breaker/cap/throttle logic
lives in our wrapper, not in httpx itself.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fakeredis.aioredis import FakeRedis

from src.infra.farvater_http import (
    _BREAKER_KEY,
    _CONSECUTIVE_BAD_KEY,
    BREAKER_THRESHOLD,
    DEFAULT_MIN_INTERVAL_S,
    BreakerOpen,
    DailyCapHit,
    FarvaterProdClient,
    ProdTierConfig,
    UpstreamRateLimited,
)


@pytest.fixture
async def redis() -> FakeRedis:
    r = FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


@pytest.fixture
def fast_config() -> ProdTierConfig:
    """Zero-delay config so throttle tests don't sleep."""
    return ProdTierConfig(
        concurrency=3,
        min_interval_s=0.0,  # disable for tests; throttle test sets explicitly
        daily_cap=100,
        timeout_s=5.0,
    )


def _ok_response(payload: dict | None = None) -> MagicMock:
    """Build a stand-in for httpx.Response — minimal surface used by our wrapper."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = payload or {"ok": True}
    resp.raise_for_status = MagicMock()
    return resp


def _rate_limited_response(status: int = 429) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = {}
    resp.raise_for_status = MagicMock()
    return resp


def test_default_throttle_keeps_snapshot_in_production_tempo() -> None:
    assert pytest.approx(0.05) == DEFAULT_MIN_INTERVAL_S


# ── happy path ──────────────────────────────────────────────────────────


async def test_post_json_returns_parsed_response(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(client._client, "post", AsyncMock(return_value=_ok_response({"x": 1}))):
            out = await client.post_json("https://farvater.travel/x")
    assert out == {"x": 1}


async def test_get_text_returns_response_body(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = "<html>ok</html>"
    resp.raise_for_status = MagicMock()

    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            out = await client.get_text("https://farvater.travel/hotel")

    assert out == "<html>ok</html>"


async def test_get_returns_response_for_legacy_callers(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = "<xml>ok</xml>"
    resp.raise_for_status = MagicMock()

    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(client._client, "get", AsyncMock(return_value=resp)) as get:
            out = await client.get(
                "https://farvater.travel/sitemap.xml",
                headers={"User-Agent": "test"},
                timeout=60,
            )

    assert out is resp
    get.assert_awaited_once_with(
        "https://farvater.travel/sitemap.xml",
        params=None,
        headers={
            "User-Agent": "test",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=60,
    )


async def test_get_without_timeout_uses_client_default(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    """Passing timeout=None to httpx disables ALL timeouts (Timeout(None));
    the wrapper must forward USE_CLIENT_DEFAULT so the client-level timeout
    keeps protecting hotel-page fetches that never set one explicitly."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.text = "<html>ok</html>"
    resp.raise_for_status = MagicMock()

    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(client._client, "get", AsyncMock(return_value=resp)) as get:
            await client.get_text("https://farvater.travel/hotel")

    assert get.await_args.kwargs["timeout"] is httpx.USE_CLIENT_DEFAULT


async def test_success_clears_consecutive_bad_counter(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    """Healthy response resets the bad counter so a single transient
    blip doesn't accumulate forever toward the breaker threshold."""
    await redis.set(_CONSECUTIVE_BAD_KEY, b"2")
    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(client._client, "post", AsyncMock(return_value=_ok_response())):
            await client.post_json("https://farvater.travel/x")
    assert await redis.get(_CONSECUTIVE_BAD_KEY) is None


# ── circuit breaker ─────────────────────────────────────────────────────


async def test_429_increments_bad_counter(redis: FakeRedis, fast_config: ProdTierConfig) -> None:
    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(
            client._client, "post", AsyncMock(return_value=_rate_limited_response(429))
        ):
            with pytest.raises(UpstreamRateLimited):
                await client.post_json("https://farvater.travel/x")
    assert int(await redis.get(_CONSECUTIVE_BAD_KEY)) == 1


async def test_403_also_counts_toward_breaker(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    """403 is treated the same as 429 — both indicate upstream is
    blocking us, both should push the breaker closer to opening."""
    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(
            client._client, "post", AsyncMock(return_value=_rate_limited_response(403))
        ):
            with pytest.raises(UpstreamRateLimited):
                await client.post_json("https://farvater.travel/x")
    assert int(await redis.get(_CONSECUTIVE_BAD_KEY)) == 1


async def test_breaker_opens_after_threshold_consecutive_bad(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    """5 consecutive 429s within the window → breaker opens for 1h."""
    async with FarvaterProdClient(redis, fast_config) as client:
        bad = AsyncMock(return_value=_rate_limited_response(429))
        with patch.object(client._client, "post", bad):
            for _ in range(BREAKER_THRESHOLD):
                with pytest.raises(UpstreamRateLimited):
                    await client.post_json("https://farvater.travel/x")
        # Counter reset; breaker key set with cooldown
        assert await redis.exists(_BREAKER_KEY)
        # Bad counter cleared once breaker tripped (replaced by breaker state)
        assert await redis.get(_CONSECUTIVE_BAD_KEY) is None


async def test_breaker_open_blocks_next_request(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    """While breaker is open, subsequent requests fail fast with
    BreakerOpen — no httpx call at all."""
    open_until = time.time() + 3600
    await redis.set(_BREAKER_KEY, str(open_until).encode())

    async with FarvaterProdClient(redis, fast_config) as client:
        post = AsyncMock(return_value=_ok_response())
        with patch.object(client._client, "post", post), pytest.raises(BreakerOpen):
            await client.post_json("https://farvater.travel/x")
        post.assert_not_awaited()  # critical — no upstream call


async def test_breaker_clears_after_cooldown(redis: FakeRedis, fast_config: ProdTierConfig) -> None:
    """Past the cooldown, the next call clears the breaker and proceeds."""
    expired = time.time() - 10
    await redis.set(_BREAKER_KEY, str(expired).encode())
    await redis.set(_CONSECUTIVE_BAD_KEY, b"5")

    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(client._client, "post", AsyncMock(return_value=_ok_response())):
            await client.post_json("https://farvater.travel/x")
    # Both keys gone
    assert not await redis.exists(_BREAKER_KEY)
    assert not await redis.exists(_CONSECUTIVE_BAD_KEY)


# ── daily cap ───────────────────────────────────────────────────────────


async def test_daily_cap_hit_blocks_further_calls(
    redis: FakeRedis, fast_config: ProdTierConfig
) -> None:
    """When daily_cap is reached, next call → DailyCapHit, no upstream."""
    async with FarvaterProdClient(redis, fast_config) as client:
        post = AsyncMock(return_value=_ok_response())
        with patch.object(client._client, "post", post):
            # Exhaust the cap (config = 100)
            for _ in range(100):
                await client.post_json("https://farvater.travel/x")
            # 101st request must reject
            with pytest.raises(DailyCapHit):
                await client.post_json("https://farvater.travel/x")
        assert post.await_count == 100  # 101st never made it


async def test_daily_cap_has_ttl(redis: FakeRedis, fast_config: ProdTierConfig) -> None:
    """Counter key gets a TTL on first set so it expires at UTC midnight."""
    async with FarvaterProdClient(redis, fast_config) as client:
        with patch.object(client._client, "post", AsyncMock(return_value=_ok_response())):
            await client.post_json("https://farvater.travel/x")

    # The key matching today's date should have a positive TTL
    from datetime import UTC, datetime

    ymd = datetime.now(UTC).strftime("%Y%m%d")
    key = f"scheduler:farvater:daily_count:{ymd}"
    ttl = await redis.ttl(key)
    # TTL > 0 and < 86400 (one day)
    assert 0 < ttl <= 86400


async def test_daily_cap_zero_disables_blocking_but_keeps_counter(
    redis: FakeRedis,
) -> None:
    """daily_cap=0 means unlimited requests; Redis counter remains telemetry."""
    config = ProdTierConfig(concurrency=3, min_interval_s=0.0, daily_cap=0, timeout_s=5.0)

    async with FarvaterProdClient(redis, config) as client:
        post = AsyncMock(return_value=_ok_response())
        with patch.object(client._client, "post", post):
            for _ in range(105):
                await client.post_json("https://farvater.travel/x")

    assert post.await_count == 105
    from datetime import UTC, datetime

    key = f"scheduler:farvater:daily_count:{datetime.now(UTC).strftime('%Y%m%d')}"
    assert int(await redis.get(key)) == 105


# ── throttle ────────────────────────────────────────────────────────────


async def test_throttle_inserts_delay_between_requests(
    redis: FakeRedis,
) -> None:
    """Two back-to-back calls with min_interval=0.1s — second must wait."""
    config = ProdTierConfig(concurrency=3, min_interval_s=0.1, daily_cap=100, timeout_s=5.0)
    async with FarvaterProdClient(redis, config) as client:
        with patch.object(client._client, "post", AsyncMock(return_value=_ok_response())):
            t0 = time.monotonic()
            await client.post_json("https://farvater.travel/x")
            await client.post_json("https://farvater.travel/x")
            elapsed = time.monotonic() - t0
    # At least 100ms gap between the two requests.
    assert elapsed >= 0.09


async def test_concurrency_semaphore_limits_parallel(
    redis: FakeRedis,
) -> None:
    """concurrency=2 means at most 2 in-flight POSTs at any moment."""
    import asyncio

    config = ProdTierConfig(concurrency=2, min_interval_s=0.0, daily_cap=100, timeout_s=5.0)

    in_flight = 0
    max_in_flight = 0

    async def _track_post(*_args, **_kwargs):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return _ok_response()

    async with FarvaterProdClient(redis, config) as client:
        with patch.object(client._client, "post", side_effect=_track_post):
            await asyncio.gather(
                *(client.post_json("https://farvater.travel/x") for _ in range(10))
            )
    assert max_in_flight <= 2


# ── context manager hygiene ─────────────────────────────────────────────


async def test_session_closed_on_exit(redis: FakeRedis, fast_config: ProdTierConfig) -> None:
    client = FarvaterProdClient(redis, fast_config)
    async with client:
        assert client._client is not None
    # After exit, the wrapper releases the httpx client.
    assert client._client is None


async def test_post_without_enter_raises(redis: FakeRedis, fast_config: ProdTierConfig) -> None:
    client = FarvaterProdClient(redis, fast_config)
    with pytest.raises(AssertionError):
        await client.post_json("https://farvater.travel/x")
