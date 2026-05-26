from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.db import Base

if TYPE_CHECKING:
    from src.models.hotel import Hotel


class HotelSlugAlias(Base):
    """Historical hotel slug that should resolve to a canonical Hotel."""

    __tablename__ = "hotel_slug_aliases"

    source_slug: Mapped[str] = mapped_column(String(160), primary_key=True)
    hotel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    hotel: Mapped["Hotel"] = relationship(back_populates="slug_aliases")
