from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.db import Base

if TYPE_CHECKING:
    from src.models.deal import Deal
    from src.models.hotel_operator_mapping import HotelOperatorMapping
    from src.models.price_observation import PriceObservation
    from src.models.scrape_run import ScrapeRun


class Operator(Base):
    """A tour operator (Join UP, Coral Travel UA, ALF, ...). 3-5 rows on MVP."""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Template URL with {hotel_external_id}, {check_in}, etc. placeholders.
    affiliate_url_template: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    mappings: Mapped[list["HotelOperatorMapping"]] = relationship(back_populates="operator")
    observations: Mapped[list["PriceObservation"]] = relationship(back_populates="operator")
    deals: Mapped[list["Deal"]] = relationship(back_populates="operator")
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(back_populates="operator")
