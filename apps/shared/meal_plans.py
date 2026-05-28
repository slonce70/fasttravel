"""Shared meal-plan code maps for API filters and user-facing copy."""

from __future__ import annotations

# Raw operator code -> canonical product key. Raw order is significant for
# stable SQL expanding-bind order in API search/calendar filters.
RAW_TO_CANONICAL: dict[str, str] = {
    "AI": "all_inclusive",
    "UAI": "all_inclusive",
    "HB": "half_board",
    "BB": "breakfast",
    "RO": "room_only",
    "FB": "full_board",
}

CANONICAL_LABELS_UK: dict[str, str] = {
    "all_inclusive": "All Inclusive",
    "half_board": "Напівпансіон",
    "breakfast": "Сніданок",
    "room_only": "Без харчування",
    "full_board": "Повний пансіон",
}

RAW_LABELS_UK: dict[str, str] = {
    "AI": "Все включено",
    "UAI": "Ультра все включено",
    "HB": "Напівпансіон",
    "BB": "Сніданок",
    "FB": "Повний пансіон",
    "RO": "Без харчування",
}


def canonical_to_raw() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for raw, canonical in RAW_TO_CANONICAL.items():
        out.setdefault(canonical, []).append(raw)
    return out


def meal_plan_match_sql(
    *,
    filter_expr: str = "f.meal_plan",
    candidate_expr: str = "d.meal_plan",
) -> str:
    """Return a SQL predicate matching nullable raw/canonical meal filters."""
    clauses = [
        f"{filter_expr} IS NULL",
        f"{candidate_expr} = {filter_expr}",
    ]
    for canonical, raw_codes in canonical_to_raw().items():
        quoted_raw = ", ".join(f"'{raw}'" for raw in raw_codes)
        clauses.append(f"({filter_expr} = '{canonical}' AND {candidate_expr} IN ({quoted_raw}))")
    return "(\n        " + "\n        OR ".join(clauses) + "\n      )"
