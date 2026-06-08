"""/deals — list the latest discounts pulled from /api/deals.

Pagination: 5 deals per page rendered as one summary message followed by
nav buttons. Tapping ◀▶ edits the same message so the chat doesn't
balloon. Each card gets one action button: the hotel name, linked to the
live operator offer when available.

State is held entirely in callback_data — no FSM context required, so a
user can use /deals while a /search wizard is mid-flight without losing
their place.
"""

from __future__ import annotations

from typing import Any, Literal

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from shared.site_urls import public_hotel_url
from shared.text_uk import format_nights
from src.config import get_settings
from src.infra.api_client import ApiError, get_deals
from src.infra.callbacks import callback_int_tail, callback_message, callback_tail
from src.infra.logging import get_logger
from src.infra.telegram_text import fit_markdown_v2_message
from src.infra.url_safety import safe_http_url
from src.keyboards.main_menu import main_menu_kb
from src.templates.deal import render_deal

router = Router(name="deals")
log = get_logger(__name__)

_PAGE_SIZE = 5
_MAX_FETCH = 50  # one /api/deals call covers up to 10 pages
_BEST_COUNT = 20  # `/best` shows the top 20 by discount in a single message
_DEALS_SEPARATOR = "\n\n— · — · —\n\n"
_TRUNCATED_FOOTER = "Повний список доступний через /deals або сайт\\."

# Quick-filter buckets for /best. Tuples are (label, nights_min, nights_max).
# Picked to match what's actually in `deals` for current ingest: 7n / 9n and
# everything 10-14n. Keeping it short — three buttons fit one row on mobile.
_BEST_NIGHTS_FILTERS: list[tuple[str, int, int]] = [
    ("7н", 7, 7),
    ("9н", 9, 9),
    ("10-14н", 10, 14),
]


def _build_keyboard(
    deals: list[dict[str, Any]],
    *,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    settings = get_settings()
    rows: list[list[InlineKeyboardButton]] = []
    for d in deals:
        slug = d.get("hotel_slug")
        deep_link = safe_http_url(d.get("deep_link"))
        hotel_name = (d.get("hotel_name_uk") or "Готель")[:24]
        url = deep_link
        if not url:
            url = public_hotel_url(settings.public_site_url, slug, medium="deals")
        if url:
            rows.append([InlineKeyboardButton(text=f"📖 {hotel_name}", url=url)])

    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"d:page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="d:noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"d:page:{page + 1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_row_for_message(row: dict[str, Any]) -> dict[str, Any]:
    """Keep unsafe operator URLs out of Markdown links in message bodies."""
    clean = dict(row)
    clean["deep_link"] = safe_http_url(row.get("deep_link"))
    return clean


def _render_page(deals: list[dict[str, Any]], page: int, total_pages: int) -> str:
    header = f"🔥 *Гарячі варіанти* · сторінка *{page}/{total_pages}*"
    blocks = [render_deal(_render_row_for_message(d)) for d in deals]
    return fit_markdown_v2_message(header, blocks, _TRUNCATED_FOOTER, _DEALS_SEPARATOR)


def _is_message_not_modified_error(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


async def _fallback_send_after_edit_failure(
    message: Message,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    log_event: str,
    error: Exception,
) -> None:
    if _is_message_not_modified_error(error):
        log.debug(log_event.replace("failed_fallback_send", "not_modified_noop"), error=str(error))
        return
    log.warning(log_event, error=str(error))
    await message.answer(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


async def _send_page(
    message: Message,
    *,
    page: int,
    edit: bool,
) -> None:
    try:
        payload = await get_deals(limit=_MAX_FETCH, offset=0)
    except ApiError:
        await message.answer(
            "Сервіс варіантів тимчасово недоступний\\. Спробуйте за хвилину\\.",
            reply_markup=main_menu_kb(),
        )
        return

    items: list[dict[str, Any]] = payload.get("items", [])
    if not items:
        text = "Зараз немає активних варіантів\\. Завітайте пізніше або підпишіться на канал\\."
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text, reply_markup=main_menu_kb())
        return

    total_pages = max(1, (len(items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(1, min(page, total_pages))
    chunk = items[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]
    text = _render_page(chunk, page, total_pages)
    kb = _build_keyboard(chunk, page=page, total_pages=total_pages)

    if edit:
        try:
            await message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                reply_markup=kb,
            )
        except Exception as exc:  # noqa: BLE001
            await _fallback_send_after_edit_failure(
                message,
                text=text,
                reply_markup=kb,
                log_event="deals.edit_failed_fallback_send",
                error=exc,
            )
    else:
        await message.answer(
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
            reply_markup=kb,
        )


async def show_deals(message: Message) -> None:
    """Used by /deals command + the reply-keyboard tap dispatcher."""
    await _send_page(message, page=1, edit=False)


@router.message(Command("deals"))
async def cmd_deals(message: Message) -> None:
    await show_deals(message)


def _nights_filter_row(active: tuple[int, int] | None) -> list[InlineKeyboardButton]:
    """Render the [7н][9н][10-14н][↺ Усі] row. ``active`` marks the current
    selection with ✓; the reset button appears only when a filter is on."""
    row: list[InlineKeyboardButton] = []
    for label, lo, hi in _BEST_NIGHTS_FILTERS:
        is_on = active == (lo, hi)
        row.append(
            InlineKeyboardButton(
                text=f"✓ {label}" if is_on else label,
                callback_data=f"best:nights:{lo}:{hi}",
            )
        )
    if active is not None:
        row.append(InlineKeyboardButton(text="↺ Усі", callback_data="best:nights:all"))
    return row


async def _best_keyboard(
    deals: list[dict[str, Any]],
    *,
    active_nights: tuple[int, int] | None = None,
) -> InlineKeyboardMarkup:
    settings = get_settings()
    rows: list[list[InlineKeyboardButton]] = [_nights_filter_row(active_nights)]
    for d in deals[:5]:
        # Only the top-5 get individual booking buttons so the message
        # doesn't blow past Telegram's 100-button-per-message cap when
        # the feed surfaces lots of hotels.
        slug = d.get("hotel_slug")
        deep_link = safe_http_url(d.get("deep_link"))
        discount = int(round(float(d.get("discount_pct") or 0)))
        hotel_name = (d.get("hotel_name_uk") or "Готель")[:22]
        url = deep_link
        if not url:
            url = public_hotel_url(settings.public_site_url, slug, medium="best")
        if url:
            rows.append([InlineKeyboardButton(text=f"−{discount}% · {hotel_name}", url=url)])
    rows.append(
        [
            InlineKeyboardButton(
                text="🔔 Підписатись на цікаві варіанти",
                callback_data="best:subscribe",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _best_header(active: tuple[int, int] | None) -> str:
    if active is None:
        return "🏆 *Топ\\-варіанти зараз*"
    lo, hi = active
    label = f"{lo}\\-{hi} ночей" if lo != hi else format_nights(lo)
    return f"🏆 *Топ\\-варіанти зараз* · {label}"


def _parse_best_nights_filter(data: str | None) -> tuple[int, int] | None | Literal[False]:
    payload = callback_tail(data, "best:nights:")
    if payload is None:
        return False
    if payload == "all":
        return None
    try:
        lo_s, hi_s = payload.split(":", 1)
        lo = int(lo_s)
        hi = int(hi_s)
    except ValueError:
        return False
    if lo < 1 or hi < lo:
        return False
    return (lo, hi)


async def _send_best(
    message: Message,
    *,
    nights_filter: tuple[int, int] | None,
    edit: bool,
) -> None:
    nights_min, nights_max = nights_filter if nights_filter is not None else (None, None)
    try:
        payload = await get_deals(
            limit=_BEST_COUNT,
            offset=0,
            sort="discount",
            nights_min=nights_min,
            nights_max=nights_max,
        )
    except ApiError:
        text = "Сервіс варіантів тимчасово недоступний\\. Спробуйте за хвилину\\."
        if edit:
            await message.edit_text(text)
        else:
            await message.answer(text, reply_markup=main_menu_kb())
        return

    items: list[dict[str, Any]] = payload.get("items", [])
    if not items:
        # Empty-after-filter must still keep the filter row so the user can
        # widen or reset without re-typing /best.
        empty_text = (
            "За вибраною тривалістю наразі немає варіантів\\. Спробуйте іншу тривалість\\."
            if nights_filter is not None
            else "Зараз немає активних варіантів\\. Підпишіться на канал — "
            "там кожна нова з'являється першою\\."
        )
        empty_kb = InlineKeyboardMarkup(inline_keyboard=[_nights_filter_row(nights_filter)])
        if edit:
            await message.edit_text(empty_text, reply_markup=empty_kb)
        else:
            await message.answer(empty_text, reply_markup=empty_kb)
        return

    header = _best_header(nights_filter)
    blocks = [render_deal(_render_row_for_message(d)) for d in items]
    text = fit_markdown_v2_message(header, blocks, _TRUNCATED_FOOTER, _DEALS_SEPARATOR)
    kb = await _best_keyboard(items, active_nights=nights_filter)

    if edit:
        try:
            await message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                reply_markup=kb,
            )
        except Exception as exc:  # noqa: BLE001
            await _fallback_send_after_edit_failure(
                message,
                text=text,
                reply_markup=kb,
                log_event="best.edit_failed_fallback_send",
                error=exc,
            )
    else:
        await message.answer(
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
            reply_markup=kb,
        )


@router.message(Command("best"))
async def cmd_best(message: Message) -> None:
    """Top-N current deals — single message, deepest discount first.

    `/deals` paginates the full feed; `/best` is the "show me the
    headlines" command. Useful when a channel-shy user wants a quick
    snapshot in DM.
    """
    await _send_best(message, nights_filter=None, edit=False)


@router.callback_query(F.data == "best:subscribe")
async def cb_best_subscribe(query: CallbackQuery) -> None:
    # Late import — same circular-dep dodge the F.text dispatcher uses.
    from src.handlers.subscribe import show_subscriptions

    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await show_subscriptions(message)
    await query.answer()


@router.callback_query(F.data.startswith("best:nights:"))
async def cb_best_nights(query: CallbackQuery) -> None:
    nights_filter = _parse_best_nights_filter(query.data)
    if nights_filter is False:
        await query.answer()
        return
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await _send_best(message, nights_filter=nights_filter, edit=True)
    await query.answer()


@router.callback_query(F.data.startswith("d:page:"))
async def cb_page(query: CallbackQuery) -> None:
    page = callback_int_tail(query.data, "d:page:")
    if page is None:
        await query.answer()
        return
    message = callback_message(query)
    if message is None:
        await query.answer("Повідомлення недоступне", show_alert=False)
        return
    await _send_page(message, page=page, edit=True)
    await query.answer()


@router.callback_query(F.data == "d:noop")
async def cb_noop(query: CallbackQuery) -> None:
    await query.answer()
