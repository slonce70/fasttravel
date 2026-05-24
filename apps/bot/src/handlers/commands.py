"""Top-level commands and main-menu text-filter handlers.

Each main-menu reply-keyboard button sends its label as a plain text
message. We dispatch that label to the corresponding command handler via
`F.text == LABEL`. Keeping the routing in one module makes it easy to
audit which entrypoints exist.

Wizard-specific entrypoints (e.g. /search opening the search FSM) live
in their own router modules so the wizard machinery doesn't leak here.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from shared.publishers.broadcast import escape_markdown_v2
from src.config import get_settings
from src.keyboards.main_menu import (
    DEALS,
    DESTINATIONS,
    HELP,
    PROFILE,
    SEARCH,
    SUBSCRIBE,
    main_menu_kb,
)

router = Router(name="commands")


def _channel_buttons() -> InlineKeyboardMarkup:
    s = get_settings()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📡 Канал з знижками", url=s.public_channel_link),
                InlineKeyboardButton(text="🌐 Сайт", url=s.public_site_url),
            ]
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    # Clear any in-flight FSM state — /start is always a fresh entrypoint.
    await state.clear()
    name = escape_markdown_v2(message.from_user.first_name if message.from_user else "")
    body = (
        f"Привіт{', ' + name if name else ''}\\! 👋\n\n"
        "*FastTravel* шукає аномально низькі ціни на тури в Туреччину, Єгипет, "
        "ОАЕ, Грецію та інші напрямки\\.\n\n"
        "Скористайтесь меню нижче — або введіть команду:\n"
        "  • /search — знайти тур\n"
        "  • /deals — гарячі знижки сьогодні\n"
        "  • /destinations — каталог країн\n"
        "  • /subscribe — алерт коли впаде ціна"
    )
    await message.answer(
        body,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu_kb(),
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
@router.message(F.text == HELP)
async def cmd_help(message: Message) -> None:
    body = (
        "*Допомога*\n\n"
        "Команди:\n"
        "  • /start — головне меню\n"
        "  • /search — знайти тур \\(майстер з 6 кроків\\)\n"
        "  • /deals — топ\\-10 гарячих знижок зараз\n"
        "  • /destinations — каталог країн\n"
        "  • /subscribe — підписатися на персональні алерти\n"
        "  • /profile — мій профіль і підписки\n"
        "  • /channel — публічний канал з усіма знижками\n\n"
        "Сайт із календарем цін: https://fasttravel\\.com\\.ua\n"
        "Питання: hello@fasttravel\\.com\\.ua"
    )
    await message.answer(
        body,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu_kb(),
        disable_web_page_preview=True,
    )


@router.message(Command("channel"))
async def cmd_channel(message: Message) -> None:
    await message.answer(
        "Канал з гарячими знижками 📡",
        reply_markup=_channel_buttons(),
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------
# Reply-keyboard text → command bridges. Each ReplyKeyboard label sends
# its text on tap; we re-dispatch to the corresponding handler so the user
# experiences "menu button = command" with zero cognitive overhead.
# Wizard / multi-step flows are routed in their own modules and registered
# AFTER this commands router so the F.text filters fall through.
# ---------------------------------------------------------------------------


@router.message(F.text == DEALS)
async def text_deals(message: Message) -> None:
    # Late import — avoids the circular dependency that would happen if
    # handlers/__init__ imported every router at module-load time.
    from src.handlers.deals import show_deals

    await show_deals(message)


@router.message(F.text == DESTINATIONS)
async def text_destinations(message: Message) -> None:
    from src.handlers.destinations import show_destinations

    await show_destinations(message)


@router.message(F.text == SUBSCRIBE)
async def text_subscribe(message: Message) -> None:
    from src.handlers.subscribe import show_subscriptions

    await show_subscriptions(message)


@router.message(F.text == PROFILE)
async def text_profile(message: Message) -> None:
    from src.handlers.profile import show_profile

    await show_profile(message)


@router.message(F.text == SEARCH)
async def text_search(message: Message, state: FSMContext) -> None:
    from src.handlers.search_wizard import start_wizard

    await start_wizard(message, state)
