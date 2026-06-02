"""/cheap — «🔥 Найдешевші тури»: absolute-cheap upcoming tours by country.

Distinct from /deals and /best (the anomaly deal-detector surfaces): this
shows the cheapest available tours per country, honest «ціна від» copy,
NEVER a discount / «−X%» / strike-through. Data comes from
`/api/cheapest-tours` (a flat ranked list the client groups by country).

Single digest message — deep links render inline in the body (not as
per-card buttons) so a TOP-3 × many-country digest can't blow Telegram's
100-button-per-message cap; the country count is capped in the template so
the 4096-char message cap holds too.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from src.config import get_settings
from src.infra.api_client import ApiError, get_cheapest_tours
from src.infra.logging import get_logger
from src.keyboards.main_menu import main_menu_kb
from src.templates.cheap import render_cheap_digest

router = Router(name="cheap")
log = get_logger(__name__)


def _site_cheap_url() -> str | None:
    """Link to the website's «Найдешевші тури» page, used in the digest
    footer when not all countries fit in one message."""
    base = (get_settings().public_site_url or "").rstrip("/")
    return f"{base}/cheap?utm_source=tg_bot&utm_medium=cheap" if base else None


async def show_cheap(message: Message) -> None:
    """Used by /cheap command + the reply-keyboard tap dispatcher."""
    try:
        rows = await get_cheapest_tours()
    except ApiError:
        await message.answer(
            "Сервіс варіантів тимчасово недоступний\\. Спробуйте за хвилину\\.",
            reply_markup=main_menu_kb(),
        )
        return

    text = render_cheap_digest(rows, site_cheap_url=_site_cheap_url())
    await message.answer(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
        reply_markup=main_menu_kb(),
    )


@router.message(Command("cheap"))
async def cmd_cheap(message: Message) -> None:
    await show_cheap(message)
