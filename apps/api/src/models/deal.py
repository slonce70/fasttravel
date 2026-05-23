from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.db import Base

if TYPE_CHECKING:
    from src.models.operator import Operator


class Deal(Base):
    """A detected price anomaly worth broadcasting."""

    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    meal_plan: Mapped[str] = mapped_column(String(16), nullable=False)
    price_uah: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_p50: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    deep_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Provenance — added in migration 004. Used by the public /api/deals
    # endpoint and the Telegram broadcaster to hide synthetic / demo rows.
    # Real values today: 'farvater_scrape', 'live_refresh', 'ittour'.
    # NULL = legacy / unknown → treated as non-real and filtered out.
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    operator: Mapped["Operator"] = relationship(back_populates="deals")
