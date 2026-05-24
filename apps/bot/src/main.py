"""Bot entrypoint.

Long-polls Telegram via aiogram 3. The companion `scheduler.post_deals`
job pushes broadcast posts directly to the channel via the shared
`shared.publishers.broadcast` helper, so the bot's only job here is the
small user-facing surface: /start funnel, /help, /channel link.

If TELEGRAM_BOT_TOKEN is not set the bot logs once and exits — keeping
the docker stack green during local-dev without a Telegram setup.
"""

from __future__ import annotations

import asyncio
import logging
import signal

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import get_settings
from src.handlers import commands_router

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

log = structlog.get_logger(service="bot")


async def _idle_until_signal() -> None:
    """Block until SIGINT/SIGTERM. Used when no token is configured —
    keeps the container alive so the rest of docker-compose stays healthy."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.warning(
            "bot.no_token",
            note="TELEGRAM_BOT_TOKEN unset — bot idle, scheduler.post_deals also no-ops",
        )
        await _idle_until_signal()
        log.info("bot.stopped", reason="no_token")
        return

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )
    dp = Dispatcher()
    dp.include_router(commands_router)

    log.info("bot.starting", environment=settings.environment)
    try:
        # Skip any backlog of updates queued while the bot was offline.
        # We don't want a flood of stale /start replies on first deploy.
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await bot.session.close()
        log.info("bot.stopped")


if __name__ == "__main__":
    asyncio.run(main())
