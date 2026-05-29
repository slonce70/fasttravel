"""Shared detector policy values for calendar-anomaly deals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class DateDipPolicy:
    lookahead_start_days: int
    lookahead_end_days: int
    neighbor_window_days: int
    min_sample_size: int
    max_spread_ratio: Decimal
    discount_multiplier: Decimal
    min_absolute_saving_uah: int
    max_discount_pct: int

    def __post_init__(self) -> None:
        if self.lookahead_start_days < 0:
            raise ValueError("lookahead_start_days must be non-negative")
        if self.lookahead_end_days <= self.lookahead_start_days:
            raise ValueError("lookahead_end_days must exceed lookahead_start_days")
        if self.neighbor_window_days <= 0:
            raise ValueError("neighbor_window_days must be positive")
        if self.min_sample_size <= 0:
            raise ValueError("min_sample_size must be positive")
        if self.max_spread_ratio <= Decimal("1"):
            raise ValueError("max_spread_ratio must be greater than 1")
        if not Decimal("0") < self.discount_multiplier < Decimal("1"):
            raise ValueError("discount_multiplier must be between 0 and 1")
        if self.min_absolute_saving_uah <= 0:
            raise ValueError("min_absolute_saving_uah must be positive")
        if not 0 < self.max_discount_pct <= 100:
            raise ValueError("max_discount_pct must be in (0, 100]")

    @property
    def max_spread_ratio_sql(self) -> str:
        return str(self.max_spread_ratio)

    @property
    def discount_multiplier_sql(self) -> str:
        return str(self.discount_multiplier)

    @property
    def max_discount_pct_sql(self) -> str:
        """Upper discount bound for the channel, as a SQL numeric literal.

        Real tour date-dips are modest; a larger "discount" is almost always a
        baseline artifact (synthetic placeholder price, or a ±neighbour window
        straddling a seasonal price step). Cap it so those never publish."""
        return str(self.max_discount_pct)

    @property
    def min_price_ratio_sql(self) -> str:
        """price / baseline floor equivalent to ``max_discount_pct`` — for SQL
        that filters on price rather than on a computed discount column."""
        return str((Decimal(100) - Decimal(self.max_discount_pct)) / Decimal(100))


DATE_DIP_POLICY = DateDipPolicy(
    lookahead_start_days=5,
    lookahead_end_days=90,
    neighbor_window_days=14,
    min_sample_size=4,
    # Reject bimodal neighbourhoods: if the priciest nearby date is >1.8x the
    # cheapest, the ±window is straddling a seasonal price step and the target
    # is "cheap" only versus the wrong season. Real same-hotel date-dips are
    # unimodal (spread well under 1.8); cross-season artifacts run ~2.0-2.2.
    max_spread_ratio=Decimal("1.8"),
    discount_multiplier=Decimal("0.96"),
    min_absolute_saving_uah=1500,
    max_discount_pct=50,
)


def date_dip_neighbor_stats_lateral_sql(*, candidate_alias: str = "cp") -> str:
    """Render the shared local-neighbour baseline block for date-dip SQL.

    `sample_n` is the count of unique neighbouring check-in dates after
    collapsing equivalent room aliases within one date to the cheapest
    family price. That keeps the public "neighboring dates" promise honest:
    four labels on the same date are one comparison point, not four.
    """
    if not _SQL_IDENTIFIER_RE.fullmatch(candidate_alias):
        raise ValueError("candidate_alias must be a simple SQL identifier")

    return f"""
                JOIN LATERAL (
                    SELECT
                        AVG(CASE WHEN rnk BETWEEN 0.25 AND 0.75 THEN price_uah END)::int AS trimmed_mean,
                        COUNT(*) AS sample_n,
                        MIN(price_uah) AS p_min,
                        MAX(price_uah) AS p_max
                    FROM (
                        SELECT
                            neighbor_day.price_uah,
                            PERCENT_RANK() OVER (ORDER BY neighbor_day.price_uah) AS rnk
                        FROM (
                            SELECT
                                neighbor.check_in,
                                MIN(neighbor.price_uah) AS price_uah
                            FROM current_prices neighbor
                            WHERE neighbor.hotel_id = {candidate_alias}.hotel_id
                              AND neighbor.operator_id = {candidate_alias}.operator_id
                              AND neighbor.nights = {candidate_alias}.nights
                              AND neighbor.meal_plan = {candidate_alias}.meal_plan
                              AND neighbor.room_family = {candidate_alias}.room_family
                              AND neighbor.check_in BETWEEN {candidate_alias}.check_in - INTERVAL '{DATE_DIP_POLICY.neighbor_window_days} days'
                                                        AND {candidate_alias}.check_in + INTERVAL '{DATE_DIP_POLICY.neighbor_window_days} days'
                              AND neighbor.check_in <> {candidate_alias}.check_in
                            GROUP BY neighbor.check_in
                        ) neighbor_day
                    ) ranked
                ) hs ON hs.sample_n >= {DATE_DIP_POLICY.min_sample_size}
                      AND hs.trimmed_mean IS NOT NULL
                      AND hs.p_max <= hs.p_min * {DATE_DIP_POLICY.max_spread_ratio_sql}
    """
