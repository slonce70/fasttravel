"""Shared deal-signal labels for Telegram and scheduler surfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DealSignalCopy:
    why_line: str
    peer_comparison: bool = False
    strike_baseline: bool = False
    neutral_comparison: bool = False
    # date_anomaly = baseline is a trimmed local comparison of NEIGHBOURING check-in dates
    # for the same hotel/nights/meal, not a price the user would otherwise
    # have paid for THIS booking. Renderers use this flag to drop the
    # "економія X ₴" wording and the ~strikethrough~, which together read
    # like a "old price → new price" promise the baseline can't keep.
    date_anomaly: bool = False


_SIGNALS: dict[str, DealSignalCopy] = {
    "calendar_anomaly": DealSignalCopy(
        "",  # headline already says it; no second redundant line
        strike_baseline=False,
        date_anomaly=True,
    ),
    "promo_discount": DealSignalCopy(
        "🏷 Спецціна від оператора — обмежена пропозиція",
        strike_baseline=True,
    ),
    "percentile": DealSignalCopy(
        "📊 Ціна нижча за звичайну для цього готелю",
        neutral_comparison=True,
    ),
    "peer_anomaly": DealSignalCopy(
        "📊 Дешевше за схожі готелі в цьому регіоні",
        peer_comparison=True,
        strike_baseline=False,
    ),
}

_UNKNOWN_SIGNAL = DealSignalCopy(
    "ℹ️ Порівняльний орієнтир ціни",
    strike_baseline=False,
    neutral_comparison=True,
)


def normalize_detection_method(method: str | None) -> str:
    return (method or "").strip().lower()


def get_deal_signal_copy(method: str | None) -> DealSignalCopy:
    normalized = normalize_detection_method(method)
    if not normalized:
        return _SIGNALS["percentile"]
    return _SIGNALS.get(normalized, _UNKNOWN_SIGNAL)


def metric_detection_method_for_reason(reason: str) -> str:
    return {
        "date_dip": "calendar_anomaly",
        "promo_discount": "promo_discount",
    }.get(reason, "unknown")
