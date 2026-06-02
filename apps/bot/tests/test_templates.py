"""Templates produce MarkdownV2-safe strings.

We don't reparse the rendered markdown (Telegram does that on send),
but we DO assert the basics: required fields appear, special chars in
DB-supplied substrings get backslash-escaped, and the layout has the
emoji header so users can scan the chat by sigil alone.
"""

from __future__ import annotations

from src.templates.deal import render_deal, render_search_hit


def test_render_search_hit_minimal():
    hit = {"name_uk": "Belport Beach", "min_price_uah": 32200}
    out = render_search_hit(hit)
    assert "Belport Beach" in out
    assert "32 200 ₴" in out


def test_render_search_hit_full():
    hit = {
        "name_uk": "Pickalbatros Vita",
        "stars": 5,
        "destination_name": "Єгипет",
        "min_price_uah": 119110,
        "review_score": 8.6,
        "review_count": 115,
    }
    out = render_search_hit(hit)
    assert "Pickalbatros Vita" in out
    assert "⭐⭐⭐⭐⭐" in out
    assert "Єгипет" in out
    # Discount badge / review formatting — '.' in 8.6 must be escaped
    assert "8\\.6/10" in out
    assert "115 відгуків" in out


def test_render_search_hit_pluralizes_review_counts():
    one = render_search_hit(
        {
            "name_uk": "One Review Hotel",
            "min_price_uah": 30000,
            "review_score": 9.0,
            "review_count": 1,
        }
    )
    few = render_search_hit(
        {
            "name_uk": "Few Reviews Hotel",
            "min_price_uah": 30000,
            "review_score": 9.0,
            "review_count": 2,
        }
    )
    many = render_search_hit(
        {
            "name_uk": "Many Reviews Hotel",
            "min_price_uah": 30000,
            "review_score": 9.0,
            "review_count": 5,
        }
    )

    assert "1 відгук" in one
    assert "2 відгуки" in few
    assert "5 відгуків" in many


def test_render_search_hit_escapes_special_chars_in_name():
    """Hotel name with characters MarkdownV2 reserves must come out escaped."""
    hit = {"name_uk": "Hotel (Beach) - Premium!", "min_price_uah": 30000}
    out = render_search_hit(hit)
    # Each of ( ) - ! must be backslash-prefixed.
    assert "\\(Beach\\)" in out
    assert "\\-" in out
    assert "\\!" in out


def test_render_search_hit_marks_nights_fallback():
    hit = {
        "name_uk": "Bin Billa Hotel",
        "min_price_uah": 27401,
        "requested_nights": 8,
        "effective_nights": 7,
        "nights_fallback": True,
    }
    out = render_search_hit(hit)

    assert "⚠️ ціна за 7 ночей" in out
    assert "не за 8 ночей" in out


def test_render_deal_full():
    row = {
        "discount_pct": 38,
        "hotel_name_uk": "Belport Beach Hotel",
        "hotel_stars": 4,
        "destination_name": "Туреччина",
        "check_in": "2026-06-14",
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 32200,
        "baseline_p50": 51500,
    }
    out = render_deal(row)
    assert "На 38% нижче за ціновий орієнтир" in out
    assert "Belport Beach Hotel" in out
    assert "⭐⭐⭐⭐" in out
    assert "Туреччина" in out
    assert "14 черв" in out  # date formatter
    assert "7 ночей" in out
    assert "32 200 ₴" in out
    assert "51 500 ₴" in out
    assert "Все включено" in out
    assert "економія" not in out
    assert "~51 500 ₴~" not in out


def test_render_deal_handles_missing_destination():
    row = {
        "discount_pct": 12,
        "hotel_name_uk": "Test Hotel",
        "hotel_stars": None,
        "destination_name": None,
        "check_in": "2026-07-01",
        "nights": 10,
        "meal_plan": "HB",
        "price_uah": 25000,
        "baseline_p50": 28500,
    }
    out = render_deal(row)
    # Doesn't crash, no destination line emitted
    assert "Test Hotel" in out
    assert "📍" not in out


def test_render_deal_calendar_anomaly_shows_neighbour_average_strikethrough():
    row = {
        "discount_pct": 19,
        "hotel_name_uk": "Albatros Dana Beach Resort",
        "hotel_stars": 5,
        "destination_name": "Єгипет",
        "check_in": "2026-06-01",
        "nights": 9,
        "meal_plan": "AI",
        "price_uah": 104678,
        "baseline_p50": 128602,
        "detection_method": "calendar_anomaly",
    }

    out = render_deal(row)

    assert "📉" in out
    assert "дешевше за сусідні дати в цьому готелі" in out
    assert "звичайна ціна ~128 602 ₴~" in out
    assert "у середньому" not in out
    assert "економія" not in out


def test_render_deal_percentile_uses_same_hotel_baseline_without_savings_claim():
    row = {
        "discount_pct": 18,
        "hotel_name_uk": "Historical Hotel",
        "hotel_stars": 4,
        "destination_name": "Анталія",
        "check_in": "2026-07-10",
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 32000,
        "baseline_p50": 39000,
        "detection_method": "percentile",
    }

    out = render_deal(row)

    assert "нижча за звичайну" in out
    assert "орієнтир" in out
    assert "економія" not in out
    assert "~39 000 ₴~" not in out


def test_render_deal_peer_anomaly_names_peer_baseline_without_savings_claim():
    row = {
        "discount_pct": 29,
        "hotel_name_uk": "Peer Hotel",
        "hotel_stars": 4,
        "destination_name": "Анталія",
        "check_in": "2026-07-10",
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 32000,
        "baseline_p50": 45500,
        "detection_method": "peer_anomaly",
    }

    out = render_deal(row)

    assert "дешевше за схожі готелі" in out
    assert "орієнтир схожих" in out
    assert "економія" not in out
    assert "~45 500 ₴~" not in out


def test_render_deal_promo_discount_uses_operator_savings_claim():
    row = {
        "discount_pct": 37,
        "hotel_name_uk": "Promo Hotel",
        "hotel_stars": 4,
        "destination_name": "Анталія",
        "check_in": "2026-07-10",
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 21000,
        "baseline_p50": 33500,
        "detection_method": "promo_discount",
    }

    out = render_deal(row)

    assert "економія 12 500 ₴" in out
    assert "~33 500 ₴~" in out
    assert "Спецціна від оператора" in out


def test_render_deal_unknown_method_uses_neutral_baseline_without_savings_claim():
    row = {
        "discount_pct": 18,
        "hotel_name_uk": "Mystery Hotel",
        "hotel_stars": 4,
        "destination_name": "Анталія",
        "check_in": "2026-07-10",
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 32000,
        "baseline_p50": 39000,
        "detection_method": "legacy_experiment",
    }

    out = render_deal(row)

    assert "орієнтир" in out
    assert "економія" not in out
    assert "~39 000 ₴~" not in out
    assert "нижча за звичайну" not in out


def test_render_deal_includes_optional_short_hotel_context():
    row = {
        "discount_pct": 38,
        "hotel_name_uk": "Belport Beach Hotel",
        "hotel_stars": 4,
        "destination_name": "Туреччина",
        "check_in": "2026-06-14",
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 32200,
        "baseline_p50": 51500,
        "review_score": 8.6,
        "review_count": 2,
        "description_uk": "Пляжний готель (центр) - family_friendly!",
    }

    out = render_deal(row)

    assert "⭐ 8\\.6/10 · 2 відгуки" in out
    assert "Пляжний готель \\(центр\\) \\- family\\_friendly\\!" in out


def test_render_deal_keeps_long_hotel_description_useful():
    description = (
        "Готель розташований на першій лінії біля моря з приватним пляжем, "
        "великим басейном, сучасним спа-центром та просторими номерами. "
        "До центру курорту можна дістатися за кілька хвилин, поруч є набережна, "
        "ресторани та зони для вечірніх прогулянок. "
        "Гості часто відзначають уважний сервіс, якісні сніданки, чисту територію "
        "та спокійну атмосферу для відпочинку з родиною. "
        "Важливий маркер опису після старого ліміту."
    )
    row = {
        "discount_pct": 38,
        "hotel_name_uk": "Belport Beach Hotel",
        "hotel_stars": 4,
        "destination_name": "Туреччина",
        "check_in": "2026-06-14",
        "nights": 7,
        "meal_plan": "AI",
        "price_uah": 32200,
        "baseline_p50": 51500,
        "description_uk": description,
    }

    out = render_deal(row)

    assert "Важливий маркер опису після старого ліміту" in out
    assert len(out) < 4096


def test_render_deal_expands_raw_and_cyrillic_meal_codes():
    cyrillic_code = render_deal(
        {
            "discount_pct": 20,
            "hotel_name_uk": "Breakfast Hotel",
            "hotel_stars": 4,
            "destination_name": "Туреччина",
            "check_in": "2026-06-14",
            "nights": 7,
            "meal_plan": "ВВ",
            "price_uah": 30000,
            "baseline_p50": 38000,
        }
    )
    raw_label = render_deal(
        {
            "discount_pct": 20,
            "hotel_name_uk": "Breakfast Hotel",
            "hotel_stars": 4,
            "destination_name": "Туреччина",
            "check_in": "2026-06-14",
            "nights": 7,
            "meal_plan": "Сніданок (BB)",
            "price_uah": 30000,
            "baseline_p50": 38000,
        }
    )

    assert "7 ночей · Сніданок" in cyrillic_code
    assert "ВВ" not in cyrillic_code
    assert "7 ночей · Сніданок" in raw_label
    assert "\\(BB\\)" not in raw_label
