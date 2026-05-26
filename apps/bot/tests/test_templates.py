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

    assert "⚠️ ціна за 7 ноч" in out
    assert "не за 8" in out


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
    assert "\\-38%" in out  # discount in MarkdownV2-escaped form
    assert "Belport Beach Hotel" in out
    assert "⭐⭐⭐⭐" in out
    assert "Туреччина" in out
    assert "14 черв" in out  # date formatter
    assert "32 200 ₴" in out
    assert "51 500 ₴" in out
    assert "Все включено" in out


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
