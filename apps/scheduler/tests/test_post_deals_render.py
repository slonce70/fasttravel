from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.jobs.post_deals import _render_deal


def _row(**overrides):
    values = {
        "discount_pct": 38,
        "hotel_name": "Belport Beach Hotel",
        "stars": 4,
        "region_name": "Кемер",
        "country_name": "Туреччина",
        "check_in": date(2026, 6, 14),
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 32200,
        "baseline_p50": 51500,
        "operator_display_name": "Farvater",
        "deep_link": "https://farvater.travel/uk/hotel/tr/belport",
        "detection_method": "calendar_anomaly",
        "description_uk": "Пляжний готель біля моря з компактною територією.",
        "review_score": 8.6,
        "review_count": 115,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_render_deal_includes_short_hotel_context() -> None:
    out = _render_deal(_row())

    assert "⭐ 8\\.6/10 · 115 відгуків" in out
    assert "ℹ️ Пляжний готель біля моря з компактною територією\\." in out
    assert "7 ночей" in out


def test_render_deal_escapes_short_hotel_context_markdown_v2() -> None:
    out = _render_deal(
        _row(
            description_uk="Тихий готель (центр) - family_friendly!",
            review_score=9.0,
            review_count=1,
        )
    )

    assert "⭐ 9\\.0/10 · 1 відгук" in out
    assert "Тихий готель \\(центр\\) \\- family\\_friendly\\!" in out


def test_render_deal_keeps_long_hotel_description_useful() -> None:
    description = (
        "Готель розташований на першій лінії біля моря з приватним пляжем, "
        "великим басейном, сучасним спа-центром та просторими номерами. "
        "До центру курорту можна дістатися за кілька хвилин, поруч є набережна, "
        "ресторани та зони для вечірніх прогулянок. "
        "Гості часто відзначають уважний сервіс, якісні сніданки, чисту територію "
        "та спокійну атмосферу для відпочинку з родиною. "
        "Важливий маркер опису після старого ліміту."
    )

    out = _render_deal(_row(description_uk=description))

    assert "Важливий маркер опису після старого ліміту" in out
    assert len(out) < 4096


def test_render_deal_expands_cyrillic_bb_meal_code() -> None:
    out = _render_deal(_row(meal_plan="ВВ"))

    assert "7 ночей · Сніданок" in out
    assert "ВВ" not in out
    assert "BB" not in out


def test_render_deal_calendar_anomaly_drops_savings_and_strikethrough() -> None:
    # Regression: date_dip baseline is the median of neighbouring check-in
    # dates for the same nights/meal at this hotel, NOT a price the user
    # would otherwise pay for THIS booking. The old "🔥 -X% · економія Y ₴"
    # + ~strikethrough~ rendering implied "save by buying now" — which the
    # baseline can't honor. We now render an honest comparison only.
    out = _render_deal(
        _row(
            discount_pct=19,
            price_uah=104678,
            baseline_p50=128602,
            detection_method="calendar_anomaly",
        )
    )

    assert "📉" in out
    assert "дешевше за сусідні дати в цьому готелі" in out
    assert "економія" not in out
    assert "~128 602 ₴~" not in out
    assert "🔥" not in out
