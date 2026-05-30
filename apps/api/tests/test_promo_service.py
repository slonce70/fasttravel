from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from shared.deal_detection import PROMO_MAX_DISCOUNT_PCT
from sqlalchemy.dialects import postgresql

from src.services.promo_service import _row_to_out, list_promotions


def _promo_row(*, price_uah: int, red_price_uah: int | None) -> SimpleNamespace:
    """A promo_offers+hotel join row as `_row_to_out` consumes it."""
    return SimpleNamespace(
        id=1,
        observed_at=datetime(2026, 5, 30, 12, 0, 0),
        bucket_slug="gorjashhie-tury",
        system_key="sys-key-1",
        check_in=date(2026, 7, 1),
        nights=7,
        meal_plan="AI",
        price_uah=price_uah,
        red_price_uah=red_price_uah,
        is_hot=True,
        is_early=False,
        is_best_deal=False,
        is_recommended=False,
        is_choice_farvater=False,
        is_otp=False,
        is_last_seats=False,
        is_black_friday=False,
        is_vip=False,
        operator_name="Test Operator",
        promotion_end_date=None,
        hotel_id=10,
        hotel_slug="fv-tr-test-hotel",
        hotel_name_uk="Тест Готель",
        hotel_stars=4,
        hotel_photo_url=None,
        destination_name="Анталія",
        country_iso2="TR",
    )


def test_implausible_strike_through_is_not_framed_as_a_discount() -> None:
    """An inflated anchor (red 100 000 ₴ vs live 10 000 ₴ = -90 %) must not
    be shown as a discount. It degrades to the same honest "no real
    discount" state as a promo with no strike-through at all — the tour
    still lists, we just don't vouch for a fake saving."""
    out = _row_to_out(_promo_row(price_uah=10000, red_price_uah=100000))
    assert out.has_real_discount is False
    assert out.discount_pct == 0.0


def test_plausible_strike_through_keeps_its_discount() -> None:
    """Guards the ceiling against over-suppression: a 35 % strike-through is
    a believable operator promo and keeps its discount framing."""
    out = _row_to_out(_promo_row(price_uah=65000, red_price_uah=100000))
    assert out.has_real_discount is True
    assert out.discount_pct == 35.0


class _FakeResult:
    def all(self) -> list[Any]:
        return []


class _CapturingSession:
    async def scalar(self, statement) -> int:  # type: ignore[no-untyped-def]
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "promo_offers.price_uah > 0" in sql
        assert "<= %(max_pct)s" in sql
        assert compiled.params["max_pct"] == PROMO_MAX_DISCOUNT_PCT
        return 0

    async def execute(self, statement) -> _FakeResult:  # type: ignore[no-untyped-def]
        return _FakeResult()


@pytest.mark.asyncio
async def test_min_discount_filter_requires_positive_price_and_caps_discount() -> None:
    await list_promotions(_CapturingSession(), min_discount_pct=20)  # type: ignore[arg-type]
