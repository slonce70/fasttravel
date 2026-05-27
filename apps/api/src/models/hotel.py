from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.db import Base

if TYPE_CHECKING:
    from src.models.destination import Destination
    from src.models.hotel_operator_mapping import HotelOperatorMapping
    from src.models.hotel_slug_alias import HotelSlugAlias


class Hotel(Base):
    """Canonical hotel record, deduplicated across operators."""

    __tablename__ = "hotels"
    __table_args__ = (CheckConstraint("stars BETWEEN 1 AND 5", name="stars_range"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    name_uk: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    stars: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="SET NULL"), nullable=True
    )

    # NOTE: Postgres built-in `point` type — no spatial index on MVP.
    # Migrate to PostGIS + GIST when proximity search matters.
    # We declare as Text in the ORM and write the column via raw DDL in
    # the migration so SQLAlchemy doesn't try to convert tuples.
    coords: Mapped[str | None] = mapped_column(Text, nullable=True)

    tbo_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    giata_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description_uk: Mapped[str | None] = mapped_column(Text, nullable=True)
    photos_jsonb: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    amenities: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # Audit 1.3 Low — SQLAlchemy returns Numeric columns as Decimal, not
    # float. Annotation was a quiet lie; consumers doing
    # `float(hotel.review_score)` worked but consumers doing arithmetic
    # without coercion silently mixed Decimal + float and lost
    # precision. Now the type matches the runtime; convert at the
    # serialization boundary (`float(...)` in templates / pydantic).
    review_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    destination: Mapped["Destination | None"] = relationship(back_populates="hotels")
    operator_mappings: Mapped[list["HotelOperatorMapping"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
    slug_aliases: Mapped[list["HotelSlugAlias"]] = relationship(
        back_populates="hotel", cascade="all, delete-orphan"
    )
