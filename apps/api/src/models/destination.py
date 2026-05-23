from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CHAR, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.db import Base

if TYPE_CHECKING:
    from src.models.hotel import Hotel


class Destination(Base):
    """Hierarchical destination (country -> region -> resort)."""

    __tablename__ = "destinations"
    __table_args__ = (
        UniqueConstraint("country_iso2", "region_slug", name="uq_destinations_country_region"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_iso2: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    region_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name_uk: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="SET NULL"), nullable=True
    )

    parent: Mapped["Destination | None"] = relationship(
        "Destination", remote_side="Destination.id", back_populates="children"
    )
    children: Mapped[list["Destination"]] = relationship(
        "Destination", back_populates="parent"
    )
    hotels: Mapped[list["Hotel"]] = relationship(back_populates="destination")
