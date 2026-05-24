"""ORM model registry.

ALL models must be imported here so SQLAlchemy's metadata sees them
(important for Alembic autogenerate and create_all in tests).
"""

from __future__ import annotations

from src.infra.db import Base
from src.models.deal import Deal
from src.models.destination import Destination
from src.models.hotel import Hotel
from src.models.hotel_operator_mapping import HotelOperatorMapping
from src.models.operator import Operator
from src.models.price_observation import PriceObservation
from src.models.scrape_run import ScrapeRun
from src.models.telegram_subscriber import TelegramSubscriber

__all__ = [
    "Base",
    "Deal",
    "Destination",
    "Hotel",
    "HotelOperatorMapping",
    "Operator",
    "PriceObservation",
    "ScrapeRun",
    "TelegramSubscriber",
]
