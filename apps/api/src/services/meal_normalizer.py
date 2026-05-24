"""Meal-plan code normalization.

Farvater (and several other Ukrainian operators) emit raw 2–3-letter meal
codes — ``AI``, ``UAI``, ``HB``, ``BB``, ``RO``, ``FB`` — but several of
those map onto the same product category from a user's perspective
(``AI`` "All Inclusive" and ``UAI`` "Ultra All Inclusive" are both
"все включено" for the purpose of picking a tour). The UI exposes the
canonical product category; the storage layer keeps the raw code so we
never lose information.

This module is the single source of truth for the mapping. It is
deliberately tiny and side-effect free so it can be imported from API
routes, services, and (in future) the deal-detection job without
pulling in DB dependencies.

Public surface
--------------

* :data:`MEAL_CANONICAL` — raw → canonical (single source of truth).
* :data:`MEAL_LABELS_UK` — canonical → user-facing Ukrainian label.
* :func:`canonical` — raw code or canonical key → canonical key. Unknown
  input is returned unchanged so callers can still pass through novel
  operator codes without crashing.
* :func:`labels` — copy of :data:`MEAL_LABELS_UK` for API responses.
* :func:`raw_codes_for` — canonical key → list of raw codes for use in
  ``WHERE meal_plan IN (...)``. Accepts raw codes too (returns
  ``[code]``) for backward-compatible API calls (``?meal=AI``). Unknown
  input passes through as ``[input]`` so the SQL filter degrades to the
  legacy ``= input`` behavior.
"""

from __future__ import annotations

# Raw operator code → canonical product key. Keep keys upper-cased so the
# caller can normalize case with ``.upper()`` without a second lookup.
MEAL_CANONICAL: dict[str, str] = {
    "AI": "all_inclusive",
    "UAI": "all_inclusive",
    "HB": "half_board",
    "BB": "breakfast",
    "RO": "room_only",
    "FB": "full_board",
}

# Reverse index, built once at import. Used by :func:`raw_codes_for` to
# expand a canonical key into the set of raw codes stored in the MV.
_CANONICAL_TO_RAW: dict[str, list[str]] = {}
for _raw, _canon in MEAL_CANONICAL.items():
    _CANONICAL_TO_RAW.setdefault(_canon, []).append(_raw)

# Canonical key → Ukrainian label. Used by the API contract test and any
# future ``GET /api/meta/meal-plans`` discovery endpoint.
MEAL_LABELS_UK: dict[str, str] = {
    "all_inclusive": "All Inclusive",
    "half_board": "Напівпансіон",
    "breakfast": "Сніданок",
    "room_only": "Без харчування",
    "full_board": "Повний пансіон",
}


def canonical(raw: str) -> str:
    """Map a raw operator code (or canonical key) to its canonical key.

    * ``'AI'`` / ``'ai'`` / ``'UAI'`` → ``'all_inclusive'``
    * ``'all_inclusive'`` → ``'all_inclusive'`` (idempotent)
    * Unknown input is returned unchanged so the caller can decide
      whether to filter, log, or pass it through.
    """
    if not raw:
        return raw
    upper = raw.upper()
    if upper in MEAL_CANONICAL:
        return MEAL_CANONICAL[upper]
    # Already canonical (or unknown): pass through.
    return raw


def labels() -> dict[str, str]:
    """Return a *copy* of the canonical → UA-label map.

    A copy is returned so callers can mutate (e.g. for serialization)
    without polluting module state.
    """
    return dict(MEAL_LABELS_UK)


def raw_codes_for(meal: str) -> list[str]:
    """Expand a canonical key or raw code into the list of raw codes
    to use inside a ``WHERE meal_plan IN (...)`` filter.

    * Canonical key (``'all_inclusive'``) → ``['AI', 'UAI']``.
    * Raw code (``'AI'``) → ``['AI']``. This keeps the legacy
      ``?meal=AI`` API contract working unchanged.
    * Unknown input → ``[meal]`` (passthrough — the SQL filter then
      reduces to the legacy ``= :meal`` shape).

    Output order is stable (insertion order from ``MEAL_CANONICAL``) so
    SQL plans are reproducible and queries cache well.
    """
    if not meal:
        return [meal]
    # Canonical key wins first — both 'all_inclusive' and 'AI' resolve
    # cleanly. (A canonical key is always lower-cased; raw codes are
    # always upper-cased — no collision is possible.)
    if meal in _CANONICAL_TO_RAW:
        return list(_CANONICAL_TO_RAW[meal])
    upper = meal.upper()
    if upper in MEAL_CANONICAL:
        # Raw operator code → list with just itself. Backward compat for
        # legacy ``?meal=AI`` calls (do NOT expand AI to AI+UAI here:
        # callers asking for a specific raw code want exact-match).
        return [upper]
    # Unknown — pass through so SQL still functions as a literal filter.
    return [meal]
