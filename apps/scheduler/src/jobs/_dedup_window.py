"""Legacy import shim for recent Farvater price-observation dedup."""

from src.services.dedup_window import DEDUP_WINDOW_HOURS, DedupKey, existing_dedup_keys

__all__ = ["DEDUP_WINDOW_HOURS", "DedupKey", "existing_dedup_keys"]
