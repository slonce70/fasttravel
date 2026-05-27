"""Small Ukrainian text formatters shared by Telegram surfaces."""

from __future__ import annotations

import re


def plural_uk(count: int, one: str, few: str, many: str) -> str:
    """Return the Ukrainian noun form for an integer count."""
    n = abs(int(count))
    last_two = n % 100
    last = n % 10
    if last == 1 and last_two != 11:
        return one
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return few
    return many


def format_count_uk(count: int, one: str, few: str, many: str) -> str:
    return f"{int(count)} {plural_uk(count, one, few, many)}"


def format_nights(count: int) -> str:
    return format_count_uk(count, "ніч", "ночі", "ночей")


def format_hotels(count: int) -> str:
    return format_count_uk(count, "готель", "готелі", "готелів")


def format_reviews(count: int) -> str:
    return format_count_uk(count, "відгук", "відгуки", "відгуків")


def format_tours(count: int) -> str:
    return format_count_uk(count, "тур", "тури", "турів")


_CYRILLIC_MEAL_CODE_TRANSLATION = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Н": "H",
        "І": "I",
        "О": "O",
        "Р": "P",
        "У": "U",
        "а": "A",
        "в": "B",
        "н": "H",
        "і": "I",
        "о": "O",
        "р": "P",
        "у": "U",
    }
)

_MEAL_LABELS = {
    "AI": "Все включено",
    "UAI": "Ультра все включено",
    "HB": "Напівпансіон",
    "BB": "Сніданок",
    "FB": "Повний пансіон",
    "RO": "Без харчування",
}


def _meal_code(raw: str) -> str | None:
    normalized = raw.translate(_CYRILLIC_MEAL_CODE_TRANSLATION).upper()
    match = re.search(r"UAI|AI|HB|BB|FB|RO", normalized)
    return match.group(0) if match else None


def format_meal_plan(raw: str | None) -> str:
    """Return customer-friendly meal text without raw operator codes."""
    if not raw:
        return ""
    text = " ".join(str(raw).split())
    code = _meal_code(text)
    if code:
        return _MEAL_LABELS[code]

    folded = text.casefold()
    if "ультра" in folded and "включ" in folded:
        return _MEAL_LABELS["UAI"]
    if "all inclusive" in folded or "все включ" in folded:
        return _MEAL_LABELS["AI"]
    if "half board" in folded or "напівпанс" in folded or "полупанс" in folded:
        return _MEAL_LABELS["HB"]
    if "breakfast" in folded or "снідан" in folded or "завтрак" in folded:
        return _MEAL_LABELS["BB"]
    if "full board" in folded or "повний панс" in folded or "полный панс" in folded:
        return _MEAL_LABELS["FB"]
    if "room only" in folded or "без харч" in folded or "без питан" in folded:
        return _MEAL_LABELS["RO"]
    return text
