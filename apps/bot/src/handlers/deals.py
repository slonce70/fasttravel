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

from typing import Any

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.config import get_settings
from src.infra.api_client import ApiError, get_deals
from src.infra.logging import get_logger
from src.keyboards.main_menu import main_menu_kb
from src.templates.deal import render_deal

router = Router(name="deals")
log = get_logger(__name__)

_PAGE_SIZE = 5
_MAX_FETCH = 50  # one /api/deals call covers up to 10 pages
_BEST_COUNT = 10  # `/best` shows the top 10 by discount in a single message


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
        deep_link = d.get("deep_link")
        hotel_name = (d.get("hotel_name_uk") or "Готель")[:24]
        url = deep_link
        if not url and slug and settings.public_site_url:
            url = (
                f"{settings.public_site_url.rstrip('/')}/hotels/{slug}"
                "?utm_source=tg_bot&utm_medium=deals"
            )
        if url:
            rows.append([InlineKeyboardButton(text=f"📖 {hotel_name}", url=url)])

    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"d:page:{page - 1}"))
    nav.append(
        InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="d:noop")
    )
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"d:page:{page + 1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_page(deals: list[dict[str, Any]], page: int, total_pages: int) -> str:
    header = f"🔥 *Гарячі знижки* · сторінка *{page}/{total_pages}*"
    body = "\n\n— · — · —\n\n".join(render_deal(d) for d in deals)
    return f"{header}\n\n{body}"


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
            "Сервіс знижок тимчасово недоступний\\. Спробуйте за хвилину\\.",
            reply_markup=main_menu_kb(),
        )
        return

    items: list[dict[str, Any]] = payload.get("items", [])
    if not items:
        text = "Зараз немає активних знижок\\. Завітайте пізніше або підпишіться на канал\\."
        if edit:
            await message.edit_text(text, reply_markup=main_menu_kb())
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
            log.debug("deals.edit_skip", error=str(exc))
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


async def _best_keyboard(deals: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    settings = get_settings()
    rows: list[list[InlineKeyboardButton]] = []
    for d in deals[:5]:
        # Only the top-5 get individual booking buttons so the message
        # doesn't blow past Telegram's 100-button-per-message cap when
        # the feed surfaces lots of hotels.
        slug = d.get("hotel_slug")
        deep_link = d.get("deep_link")
        discount = int(round(float(d.get("discount_pct") or 0)))
        hotel_name = (d.get("hotel_name_uk") or "Готель")[:22]
        url = deep_link
        if not url and slug and settings.public_site_url:
            url = (
                f"{settings.public_site_url.rstrip('/')}/hotels/{slug}"
                "?utm_source=tg_bot&utm_medium=best"
            )
        if url:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"−{discount}% · {hotel_name}", url=url
                    )
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔔 Підписатись на знижки", callback_data="best:subscribe"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("best"))
async def cmd_best(message: Message) -> None:
    """Top-N current deals — single message, deepest discount first.

    `/deals` paginates the full feed; `/best` is the "show me the
    headlines" command. Useful when a channel-shy user wants a quick
    snapshot in DM.
    """
    try:
        payload = await get_deals(limit=_BEST_COUNT, offset=0, sort="discount")
    except ApiError:
        await message.answer(
            "Сервіс знижок тимчасово недоступний\\. Спробуйте за хвилину\\.",
            reply_markup=main_menu_kb(),
        )
        return

    items: list[dict[str, Any]] = payload.get("items", [])
    if not items:
        await message.answer(
            "Зараз немає активних знижок\\. Підпишіться на канал — там кожна нова з'являється першою\\.",
            reply_markup=main_menu_kb(),
        )
        return

    header = "🏆 *Топ\\-знижки зараз*"
    body = "\n\n— · — · —\n\n".join(render_deal(d) for d in items)
    text = f"{header}\n\n{body}"
    kb = await _best_keyboard(items)

    await message.answer(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
        reply_markup=kb,
    )


@router.callback_query(F.data == "best:subscribe")
async def cb_best_subscribe(query: CallbackQuery) -> None:
    # Late import — same circular-dep dodge the F.text dispatcher uses.
    from src.handlers.subscribe import show_subscriptions

    if query.message is not None:
        await show_subscriptions(query.message)
    await query.answer()


@router.callback_query(F.data.startswith("d:page:"))
async def cb_page(query: CallbackQuery) -> None:
    try:
        page = int((query.data or "").split(":")[2])
    except (IndexError, ValueError):
        await query.answer()
        return
    await _send_page(query.message, page=page, edit=True)
    await query.answer()


@router.callback_query(F.data == "d:noop")
async def cb_noop(query: CallbackQuery) -> None:
    await query.answer()
