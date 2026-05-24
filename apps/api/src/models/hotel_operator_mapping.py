from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.db import Base

if TYPE_CHECKING:
    from src.models.hotel import Hotel
    from src.models.operator import Operator


class HotelOperatorMapping(Base):
    """Maps an operator's external hotel id to our canonical Hotel."""

    __tablename__ = "hotel_operator_mapping"

    # Composite PK on (operator_id, external_id) — the natural key on the
    # operator's side. hotel_id is a regular FK column.
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), primary_key=True
    )
    external_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    operator: Mapped["Operator"] = relationship(back_populates="mappings")
    hotel: Mapped["Hotel"] = relationship(back_populates="operator_mappings")
