"""Shared deal-signal labels for Telegram and scheduler surfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DealSignalCopy:
    why_line: str
    peer_comparison: bool = False
    # date_anomaly = baseline is the median of NEIGHBOURING check-in dates
    # for the same hotel/nights/meal, not a price the user would otherwise
    # have paid for THIS booking. Renderers use this flag to drop the
    # "економія X ₴" wording and the ~strikethrough~, which together read
    # like a "old price → new price" promise the baseline can't keep.
    date_anomaly: bool = False


_SIGNALS: dict[str, DealSignalCopy] = {
    "calendar_anomaly": DealSignalCopy(
        "",  # headline already says it; no second redundant line
        date_anomaly=True,
    ),
    "promo_discount": DealSignalCopy("🏷 Спецціна від оператора — обмежена пропозиція"),
    "percentile": DealSignalCopy("📊 Ціна нижча за звичайну для цього готелю"),
    "peer_anomaly": DealSignalCopy(
        "📊 Дешевше за аналогічні готелі в цьому регіоні",
        peer_comparison=True,
    ),
}


def normalize_detection_method(method: str | None) -> str:
    return (method or "percentile").strip().lower() or "percentile"


def get_deal_signal_copy(method: str | None) -> DealSignalCopy:
    return _SIGNALS.get(normalize_detection_method(method), _SIGNALS["percentile"])


def metric_detection_method_for_reason(reason: str) -> str:
    return {
        "warm": "percentile",
        "cold": "peer_anomaly",
        "bucket": "promo_discount",
        "date_dip": "calendar_anomaly",
        "stay_inversion": "calendar_anomaly",
    }.get(reason, "unknown")
