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
