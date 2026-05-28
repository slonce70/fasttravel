"""ORM model for operator-flagged promotion offers from farvater.

Backs migration 012. See that file for design rationale; this module
just mirrors the schema so application code can query promo_offers via
SQLAlchemy instead of raw SQL.

DESIGN NOTE: this is intentionally a *separate* table from
`price_observations`. Promotions have their own lifecycle (LoadedDate,
promotionEndDate) and are ingested by a different job at a different
cadence. Mixing them into the price-observation stream would corrupt
calendar/history analytics and blur the separate `/api/promotions`
surface.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infra.db import Base


class PromoOffer(Base):
    """A single tour-level promotion row scraped from farvater's
    static-tours endpoint, keyed by (system_key, bucket_slug, observed_at)."""

    __tablename__ = "promo_offers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False
    )
    # See migration 012 — operator may be unknown at fetch time.
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id", ondelete="SET NULL"), nullable=True
    )
    bucket_slug: Mapped[str] = mapped_column(String(32), nullable=False)
    system_key: Mapped[str] = mapped_column(String(64), nullable=False)
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    meal_plan: Mapped[str] = mapped_column(String(16), nullable=False)

    # Per-row boolean flags. Defaults match migration's server_default.
    is_hot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_early: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_best_deal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_choice_farvater: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_otp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_last_seats: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_black_friday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_vip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    hot_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    early_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    price_uah: Mapped[int] = mapped_column(Integer, nullable=False)
    red_price_uah: Mapped[int | None] = mapped_column(Integer, nullable=True)

    promotion_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    loaded_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    operator_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator_id_int: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
