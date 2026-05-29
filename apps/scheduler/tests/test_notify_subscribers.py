from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.jobs.notify_subscribers import _render


def test_render_peer_anomaly_uses_neighboring_hotels_copy_without_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=28,
        hotel_name_uk="Peer Resort",
        hotel_stars=4,
        destination_name="Анталія",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=32000,
        baseline_p50=45500,
        detection_method="peer_anomaly",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "Варіант за вашою підпискою" in out
    assert "дешевше за схожі готелі" in out
    assert "орієнтир схожих" in out
    assert "економія" not in out
    assert "~45 500 ₴~" not in out


def test_render_calendar_anomaly_shows_neighbour_average_strikethrough() -> None:
    # The date-dip baseline is the average across nearby dates. Show it
    # struck-through ("у середньому ~X~") so the card answers "cheaper than
    # what?" — but never as a fake "економія"/"save by buying now" claim.
    row = SimpleNamespace(
        discount_pct=19,
        hotel_name_uk="Albatros Dana Beach Resort",
        hotel_stars=5,
        destination_name="Хургада",
        country_name="Єгипет",
        check_in=date(2026, 6, 1),
        nights=9,
        meal_plan="AI",
        price_uah=104678,
        baseline_p50=128602,
        detection_method="calendar_anomaly",
        country_iso2="EG",
    )

    out = _render(row, "https://fasttravel.test")

    assert "Цікава дата за вашою підпискою" in out
    assert "дешевше за сусідні дати" in out
    assert "у середньому ~128 602 ₴~" in out
    assert "економія" not in out


def test_render_includes_rating_and_description_when_present() -> None:
    row = SimpleNamespace(
        discount_pct=19,
        hotel_name_uk="Blue Istanbul Hotel",
        hotel_stars=4,
        destination_name="Стамбул",
        country_name="Туреччина",
        check_in=date(2026, 6, 13),
        nights=7,
        meal_plan="RO",
        price_uah=27401,
        baseline_p50=38389,
        detection_method="calendar_anomaly",
        country_iso2="TR",
        review_score=8.6,
        review_count=412,
        description_uk="Сучасний готель у центрі Стамбула, поряд із Блакитною мечеттю.",
    )

    out = _render(row, "https://fasttravel.test")

    assert "⭐ 8\\.6/10" in out
    assert "відгук" in out  # review-count word (declined form)
    assert "Сучасний готель у центрі Стамбула" in out


def test_render_percentile_uses_same_hotel_baseline_without_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=18,
        hotel_name_uk="Historical Resort",
        hotel_stars=4,
        destination_name="Анталія",
        country_name="Туреччина",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=32000,
        baseline_p50=39000,
        detection_method="percentile",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "нижча за звичайну" in out
    assert "орієнтир" in out
    assert "економія" not in out
    assert "~39 000 ₴~" not in out


def test_render_promo_discount_uses_operator_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=37,
        hotel_name_uk="Promo Resort",
        hotel_stars=4,
        destination_name="Анталія",
        country_name="Туреччина",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=21000,
        baseline_p50=33500,
        detection_method="promo_discount",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "Знижка за вашою підпискою" in out
    assert "економія 12 500 ₴" in out
    assert "~33 500 ₴~" in out
    assert "Спецціна від оператора" in out


def test_render_unknown_method_uses_neutral_baseline_without_savings_claim() -> None:
    row = SimpleNamespace(
        discount_pct=18,
        hotel_name_uk="Mystery Resort",
        hotel_stars=4,
        destination_name="Анталія",
        country_name="Туреччина",
        check_in=date(2026, 7, 10),
        nights=7,
        meal_plan="AI",
        price_uah=32000,
        baseline_p50=39000,
        detection_method="legacy_experiment",
        country_iso2="TR",
    )

    out = _render(row, "https://fasttravel.test")

    assert "орієнтир" in out
    assert "економія" not in out
    assert "~39 000 ₴~" not in out
    assert "нижча за звичайну" not in out
