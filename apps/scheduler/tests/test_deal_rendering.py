from __future__ import annotations

from shared.deal_rendering import render_deal_hotel_context, render_deal_price_semantics


def test_calendar_anomaly_semantics_show_average_baseline() -> None:
    rendered = render_deal_price_semantics(
        detection_method="calendar_anomaly",
        discount_pct=19,
        price_uah=104678,
        baseline_uah=128602,
    )

    assert rendered.headline == "📉 *На 19% дешевше за сусідні дати в цьому готелі*"
    # Show the neighbour-dates average struck-through next to the deal price so
    # users see what it's discounted *from* — not just a bare percentage.
    assert rendered.price_line == "💰 *104 678 ₴* · у середньому ~128 602 ₴~"
    assert rendered.why_line == ""
    assert "економія" not in rendered.headline


def test_calendar_anomaly_semantics_omit_baseline_when_not_cheaper() -> None:
    rendered = render_deal_price_semantics(
        detection_method="calendar_anomaly",
        discount_pct=0,
        price_uah=104678,
        baseline_uah=104678,
    )

    assert rendered.price_line == "💰 *104 678 ₴*"
    assert "~" not in rendered.price_line


def test_promo_discount_semantics_keep_operator_savings_claim() -> None:
    rendered = render_deal_price_semantics(
        detection_method="promo_discount",
        discount_pct=37,
        price_uah=21000,
        baseline_uah=33500,
    )

    assert rendered.headline == "🔥 *\\-37% · економія 12 500 ₴*"
    assert rendered.price_line == "💰 *21 000 ₴* ~33 500 ₴~"
    assert rendered.why_line == "🏷 Спецціна від оператора — обмежена пропозиція"


def test_unknown_method_semantics_use_neutral_baseline() -> None:
    rendered = render_deal_price_semantics(
        detection_method="legacy_experiment",
        discount_pct=18,
        price_uah=32000,
        baseline_uah=39000,
    )

    assert rendered.headline == "ℹ️ *На 18% нижче за ціновий орієнтир*"
    assert rendered.price_line == "💰 *32 000 ₴* · орієнтир 39 000 ₴"
    assert rendered.why_line == "ℹ️ Порівняльний орієнтир ціни"
    assert "економія" not in rendered.headline
    assert "~" not in rendered.price_line


def test_hotel_context_renders_reviews_and_escaped_description() -> None:
    rendered = render_deal_hotel_context(
        review_score=9.0,
        review_count=1,
        description_uk="Тихий готель (центр) - family_friendly!",
    )

    assert rendered == (
        "⭐ 9\\.0/10 · 1 відгук\n" "ℹ️ Тихий готель \\(центр\\) \\- family\\_friendly\\!\n"
    )


def test_hotel_context_keeps_long_description_within_telegram_limit() -> None:
    description = " ".join(f"слово{i}" for i in range(120))

    rendered = render_deal_hotel_context(
        review_score=None,
        review_count=0,
        description_uk=description,
    )

    assert rendered.startswith("ℹ️ слово0")
    assert rendered.endswith("\\.\\.\\.\n")
    assert len(rendered) < 700
