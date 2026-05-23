from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.db import Base

if TYPE_CHECKING:
    from src.models.operator import Operator


class PriceObservation(Base):
    """One price snapshot from one operator for one (hotel, date, config).

    The actual table is PARTITIONED BY RANGE (observed_at) via pg_partman.
    The ORM declaration here matches the parent-table shape; partitioning
    DDL lives in migration 001.
    """

    __tablename__ = "price_observations"
    __table_args__ = (
        # Composite PK including the partition key — required by Postgres
        # for partitioned tables.
        PrimaryKeyConstraint("id", "observed_at", name="pk_price_observations"),
        {"postgresql_partition_by": "RANGE (observed_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False
    )
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    nights: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    meal_plan: Mapped[str] = mapped_column(String(16), nullable=False)
    room_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    adults: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2")
    departure_city: Mapped[str | None] = mapped_column(String(32), nullable=True)

    price_uah: Mapped[int] = mapped_column(Integer, nullable=False)
    price_original: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="UAH")
    fx_rate_to_uah: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    deep_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    operator: Mapped["Operator"] = relationship(back_populates="observations")


# Mark Text as used to silence linters — Text is referenced in column types above
_ = Text
