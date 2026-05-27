"""Shared deal-signal labels for Telegram and scheduler surfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DealSignalCopy:
    why_line: str
    peer_comparison: bool = False


_SIGNALS: dict[str, DealSignalCopy] = {
    "calendar_anomaly": DealSignalCopy("📉 Аномально дешева дата у цьому готелі"),
    "promo_discount": DealSignalCopy("🏷 Спецціна оператора"),
    "percentile": DealSignalCopy("📊 Нижче історичної ціни цього готелю"),
    "peer_anomaly": DealSignalCopy(
        "📊 Дешевше за середнє по сусідніх готелях",
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
