"""Shared detector policy + SQL for regime-local calendar-anomaly deals.

A ``calendar_anomaly`` ("date dip") is a check-in date whose price is a genuine
local *valley*: cheaper than the surrounding dates of the SAME hotel / operator /
nights / meal / room-family, where those surrounding dates are at one stable
price level. This is the product's core promise — "this exact date is cheaper
than the normal price for these dates" — not "cheaper than peak season".

The detector is REGIME-LOCAL and two-sided. For each per-date family-minimum
price it looks at two temporal frames — the ``shoulder_frame_days`` preceding and
following calendar days — and only flags a date when ALL hold:

  1. at least ``min_neighbors_per_side`` priced dates exist on EACH side
     (gap-awareness — isolated points after a data gap are not dips);
  2. the price is strictly below the cheapest neighbouring date on BOTH sides
     (a true V-bottom, not the edge of a step);
  3. the two sides' average levels match within ``side_match_ratio``
     (return-to-baseline — rejects seasonal steps where the two sides are
     different price regimes);
  4. the dip is at least ``dip_threshold_pct`` below the local baseline and no
     deeper than ``max_depth_pct`` (a glitch-cliff guard), and the absolute
     saving is at least ``min_absolute_saving_uah``.

The displayed baseline is the matched-side AVERAGE — the honest "typical price
for these dates" — so the card's struck-through "у середньому" is literally true.

Both the scheduler channel detector (``detect_deals``) and the API hotel
calendar (``calendar_service``) build on :func:`date_dip_local_v_cte_sql` so the
definition of a cheap date is identical on every surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DateDipPolicy:
    lookahead_start_days: int
    lookahead_end_days: int
    shoulder_frame_days: int
    min_neighbors_per_side: int
    side_match_ratio: Decimal
    dip_threshold_pct: int
    max_depth_pct: int
    min_absolute_saving_uah: int

    def __post_init__(self) -> None:
        if self.lookahead_start_days < 0:
            raise ValueError("lookahead_start_days must be non-negative")
        if self.lookahead_end_days <= self.lookahead_start_days:
            raise ValueError("lookahead_end_days must exceed lookahead_start_days")
        if self.shoulder_frame_days <= 0:
            raise ValueError("shoulder_frame_days must be positive")
        if self.min_neighbors_per_side <= 0:
            raise ValueError("min_neighbors_per_side must be positive")
        if self.side_match_ratio <= Decimal("1"):
            raise ValueError("side_match_ratio must be greater than 1")
        if not 0 < self.dip_threshold_pct < self.max_depth_pct:
            raise ValueError("dip_threshold_pct must be in (0, max_depth_pct)")
        if not 0 < self.max_depth_pct <= 100:
            raise ValueError("max_depth_pct must be in (0, 100]")
        if self.min_absolute_saving_uah <= 0:
            raise ValueError("min_absolute_saving_uah must be positive")

    @property
    def side_match_ratio_sql(self) -> str:
        return str(self.side_match_ratio)

    @property
    def dip_threshold_pct_sql(self) -> str:
        return str(self.dip_threshold_pct)

    @property
    def max_depth_pct_sql(self) -> str:
        return str(self.max_depth_pct)


# Owner-governed detection policy (see docs/DEAL_DETECTOR_REDESIGN.md). Each knob
# was set with anchor-justified margins on real data: genuine V-dips score
# side_ratio <= 1.025 while seasonal-step artifacts score >= 1.31, so 1.15 cleanly
# separates them; depth cap 35% drops glitch cliffs while keeping the deepest real
# dip (~27%); dip_threshold 8% sits above the borderline noise band (~5-7%).
DATE_DIP_POLICY = DateDipPolicy(
    lookahead_start_days=5,
    lookahead_end_days=90,
    shoulder_frame_days=7,
    min_neighbors_per_side=3,
    side_match_ratio=Decimal("1.15"),
    dip_threshold_pct=8,
    max_depth_pct=35,
    min_absolute_saving_uah=1500,
)


def date_dip_local_v_cte_sql(*, extra_series_filter: str = "") -> str:
    """Render the ``series`` -> ``framed`` -> ``local_stats`` CTE chain for the
    regime-local two-sided V date-dip detector.

    ``local_stats`` yields one row per V-bottom candidate
    ``(hotel_id, operator_id, nights, meal_plan, room_family, check_in)`` that
    passes the SHAPE gates (>=N priced dates each side within +-frame, strictly
    below both side minima, the two sides within ``side_match_ratio``), already
    carrying ``baseline_p50`` (matched-side average), ``discount_pct``,
    ``sample_n`` and the cheapest underlying ``room_category`` / ``deep_link``
    for that dip date. Callers apply the magnitude thresholds
    (``dip_threshold_pct`` / ``max_depth_pct`` / ``min_absolute_saving_uah``)
    and any selection/ranking.

    ``extra_series_filter`` is an optional fixed predicate appended to the series
    scan (e.g. ``"AND cp.hotel_id = :hotel_id"`` for the per-hotel calendar) — it
    must be a trusted literal, never interpolated user input.
    """
    p = DATE_DIP_POLICY
    return f"""
    series AS (
        -- Per-date family MIN over the full MV window (incl. the <+{p.lookahead_start_days}d
        -- left shoulder so early-window candidates still have a preceding frame;
        -- the MV floor is CURRENT_DATE so the -frame edge simply adds nothing).
        --
        -- Same-room casing/whitespace duplicates on ONE date (e.g. 'Deluxe Room'
        -- 79793 vs 'DELUXE ROOM' 108285) are first collapsed to their MAX, so a
        -- phantom cheap re-listing of a room can't manufacture a one-day dip.
        -- MAX can only SUPPRESS such artifacts, never create a dip, so genuine
        -- single-listing dips are unaffected.
        SELECT rooms.hotel_id, rooms.operator_id, rooms.nights, rooms.meal_plan,
               rooms.room_family, rooms.check_in, MIN(rooms.room_price) AS price_uah
        FROM (
            SELECT cp.hotel_id, cp.operator_id, cp.nights, cp.meal_plan, cp.room_family,
                   cp.check_in, MAX(cp.price_uah) AS room_price
            FROM current_prices cp
            WHERE cp.check_in BETWEEN CURRENT_DATE - INTERVAL '{p.shoulder_frame_days} days'
                                 AND CURRENT_DATE + INTERVAL '{p.lookahead_end_days} days'
                  {extra_series_filter}
            GROUP BY cp.hotel_id, cp.operator_id, cp.nights, cp.meal_plan, cp.room_family,
                     cp.check_in, lower(btrim(cp.room_category))
        ) rooms
        GROUP BY rooms.hotel_id, rooms.operator_id, rooms.nights, rooms.meal_plan,
                 rooms.room_family, rooms.check_in
    ),
    framed AS (
        SELECT s.*,
            MIN(s.price_uah) OVER w_prec AS prec_min,
            AVG(s.price_uah) OVER w_prec AS prec_avg,
            COUNT(*)         OVER w_prec AS prec_n,
            MIN(s.price_uah) OVER w_foll AS foll_min,
            AVG(s.price_uah) OVER w_foll AS foll_avg,
            COUNT(*)         OVER w_foll AS foll_n
        FROM series s
        WINDOW
            w_prec AS (PARTITION BY s.hotel_id, s.operator_id, s.nights, s.meal_plan, s.room_family
                       ORDER BY s.check_in
                       RANGE BETWEEN INTERVAL '{p.shoulder_frame_days} days' PRECEDING
                                 AND INTERVAL '1 day' PRECEDING),
            w_foll AS (PARTITION BY s.hotel_id, s.operator_id, s.nights, s.meal_plan, s.room_family
                       ORDER BY s.check_in
                       RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                                 AND INTERVAL '{p.shoulder_frame_days} days' FOLLOWING)
    ),
    local_stats AS (
        SELECT f.hotel_id, f.operator_id, f.check_in, f.nights, f.meal_plan, f.room_family,
            f.price_uah,
            cheapest.room_category,
            cheapest.deep_link,
            ROUND((f.prec_avg + f.foll_avg) / 2)::int AS baseline_p50,
            ROUND(100 * (1 - f.price_uah::numeric / ((f.prec_avg + f.foll_avg) / 2)), 2) AS discount_pct,
            (f.prec_n + f.foll_n)::int AS sample_n
        FROM framed f
        JOIN LATERAL (
            -- room_category + deep_link of the row matching the collapsed family
            -- minimum (>= guards against pointing at a sub-min phantom that the
            -- MAX-collapse already discarded from the dip math).
            SELECT cp.room_category, cp.deep_link
            FROM current_prices cp
            WHERE cp.hotel_id = f.hotel_id AND cp.operator_id = f.operator_id
              AND cp.nights = f.nights AND cp.meal_plan = f.meal_plan
              AND cp.room_family = f.room_family AND cp.check_in = f.check_in
              AND cp.price_uah >= f.price_uah
            ORDER BY cp.price_uah ASC, cp.room_category ASC, cp.deep_link ASC
            LIMIT 1
        ) cheapest ON TRUE
        WHERE f.check_in BETWEEN CURRENT_DATE + INTERVAL '{p.lookahead_start_days} days'
                             AND CURRENT_DATE + INTERVAL '{p.lookahead_end_days} days'
          AND f.prec_n >= {p.min_neighbors_per_side}
          AND f.foll_n >= {p.min_neighbors_per_side}
          AND f.price_uah < f.prec_min
          AND f.price_uah < f.foll_min
          AND GREATEST(f.prec_avg, f.foll_avg) <= LEAST(f.prec_avg, f.foll_avg) * {p.side_match_ratio_sql}
    )"""
