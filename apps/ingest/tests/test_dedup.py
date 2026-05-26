"""Dedup contract:
  * First sighting of a fingerprint → NOT duplicate, fingerprint registered.
  * Subsequent sighting within TTL → IS duplicate.
  * Different fingerprints → independent.

We don't test the TTL expiry itself — fakeredis honours `ex=` and we
trust Redis to do its job. What matters is the SET-NX-EX atomicity
(no GET-then-SET race).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.dedup import is_duplicate, offer_fingerprint
from src.normalizers.base import NormalizedOffer


def _offer(price: int = 22400, deep_link: str = "https://op.example/tour/42") -> NormalizedOffer:
    return NormalizedOffer(
        hotel_external_id="HOTEL-1",
        operator_code="joinup",
        check_in=date(2026, 6, 15),
        nights=7,
        meal_plan="AI",
        price_uah=price,
        price_original=540,
        currency="USD",
        fx_rate_to_uah=Decimal("41.5"),
        deep_link=deep_link,
    )


def test_fingerprint_is_stable_across_calls():
    a = offer_fingerprint(_offer())
    b = offer_fingerprint(_offer())
    assert a == b


def test_fingerprint_changes_when_price_changes():
    a = offer_fingerprint(_offer(price=22400))
    b = offer_fingerprint(_offer(price=22000))
    assert a != b


def test_fingerprint_ignores_deep_link_variations():
    """Deep links often carry utm_* or timestamps that differ run-to-run
    while the offer is semantically identical. We hash only on price +
    identity fields, NOT on deep_link."""
    a = offer_fingerprint(_offer(deep_link="https://op.example/tour/42?utm=morning"))
    b = offer_fingerprint(_offer(deep_link="https://op.example/tour/42?utm=evening"))
    assert a == b


@pytest.mark.asyncio
async def test_first_sighting_not_duplicate(redis):
    fp = offer_fingerprint(_offer())
    assert await is_duplicate(redis, fp) is False


@pytest.mark.asyncio
async def test_second_sighting_is_duplicate(redis):
    fp = offer_fingerprint(_offer())
    assert await is_duplicate(redis, fp) is False
    assert await is_duplicate(redis, fp) is True


@pytest.mark.asyncio
async def test_different_fingerprints_independent(redis):
    fp1 = offer_fingerprint(_offer(price=22400))
    fp2 = offer_fingerprint(_offer(price=22000))
    assert await is_duplicate(redis, fp1) is False
    assert await is_duplicate(redis, fp2) is False
    # Each one is now duplicate independently.
    assert await is_duplicate(redis, fp1) is True
    assert await is_duplicate(redis, fp2) is True
