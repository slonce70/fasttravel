"""Small Ukrainian text formatters shared by Telegram surfaces."""

from __future__ import annotations


def plural_uk(count: int, one: str, few: str, many: str) -> str:
    """Return the Ukrainian noun form for an integer count."""
    n = abs(int(count))
    last_two = n % 100
    last = n % 10
    if last == 1 and last_two != 11:
        return one
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return few
    return many


def format_count_uk(count: int, one: str, few: str, many: str) -> str:
    return f"{int(count)} {plural_uk(count, one, few, many)}"


def format_nights(count: int) -> str:
    return format_count_uk(count, "ніч", "ночі", "ночей")


def format_hotels(count: int) -> str:
    return format_count_uk(count, "готель", "готелі", "готелів")


def format_reviews(count: int) -> str:
    return format_count_uk(count, "відгук", "відгуки", "відгуків")


def format_tours(count: int) -> str:
    return format_count_uk(count, "тур", "тури", "турів")
