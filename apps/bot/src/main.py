"""Bot entrypoint.

Boots aiogram 3 polling with:
- RedisStorage FSM (logical DB /2 so we don't collide with refresh:queue)
- BotFather-style command list (`set_my_commands`) so the synth `/` UI
  in Telegram lists every entrypoint
- MenuButtonCommands so the blue strip next to the chat input opens that
  same command list
- Sentry + Prometheus exporter when env vars are present

If `TELEGRAM_BOT_TOKEN` is unset the bot idles until SIGTERM — keeps the
docker-compose stack healthy on an unconfigured dev environment.
"""

from __future__ import annotations

import asyncio
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonCommands

from src.config import get_settings
from src.infra.api_client import close_client
from src.infra.db import close_engine
from src.infra.logging import configure_logging, get_logger
from src.infra.metrics import start_metrics_server
from src.infra.middleware import MetricsMiddleware, ThrottleMiddleware
from src.infra.sentry import configure_sentry

log = get_logger("bot.main")


PUBLIC_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Почати"),
    BotCommand(command="search", description="🔍 Знайти тур"),
    BotCommand(command="deals", description="🔥 Гарячі знижки"),
    BotCommand(command="destinations", description="🌍 Напрямки"),
    BotCommand(command="subscribe", description="🔔 Підписки на знижки"),
    BotCommand(command="profile", description="👤 Профіль"),
    BotCommand(command="help", description="ℹ️ Допомога"),
]


def _build_storage(redis_url: str) -> RedisStorage | MemoryStorage:
    """RedisStorage when the URL is set + reachable, otherwise fall back to
    in-memory so the bot still boots in a single-container test scenario."""
    try:
        return RedisStorage.from_url(redis_url)
    except Exception as exc:  # noqa: BLE001 — Redis down shouldn't crash boot
        log.warning("bot.fsm.redis_unavailable", error=str(exc), fallback="memory")
        return MemoryStorage()


async def _idle_until_signal() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def main() -> None:
    configure_logging()
    settings = get_settings()

    # Optional observability — Sentry only init's when SENTRY_DSN is set,
    # Prometheus exporter always boots (scrape is opt-in via Prometheus config).
    sentry_enabled = configure_sentry()
    start_metrics_server(settings.metrics_port)
    log.info(
        "bot.booting",
        environment=settings.environment,
        sentry=sentry_enabled,
        metrics_port=settings.metrics_port,
    )

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
    storage = _build_storage(settings.redis_url)
    dp = Dispatcher(storage=storage)

    # Middlewares run for every Telegram update before it reaches a handler.
    # Throttle first so a flood gets dropped before we spend latency on a
    # metric observation we'd just discard.
    dp.update.outer_middleware(ThrottleMiddleware())
    dp.message.middleware(MetricsMiddleware())
    dp.callback_query.middleware(MetricsMiddleware())

    # Routers register in dependency order: commands first (text-filter
    # main-menu dispatch), wizards / sub-flows after so their FSM-state
    # filters fall through to the catch-all only when no state is active.
    # Late imports keep the entrypoint side-effect-free for test imports.
    from src.handlers.commands import router as commands_router
    from src.handlers.deals import router as deals_router
    from src.handlers.destinations import router as destinations_router
    from src.handlers.profile import router as profile_router
    from src.handlers.search_wizard import router as wizard_router
    from src.handlers.subscribe import router as subscribe_router

    dp.include_router(commands_router)
    dp.include_router(wizard_router)
    dp.include_router(deals_router)
    dp.include_router(destinations_router)
    dp.include_router(subscribe_router)
    dp.include_router(profile_router)

    log.info("bot.starting", environment=settings.environment)
    try:
        # Publish command list + open it via the blue MenuButton. Idempotent;
        # cheap to call on every boot so we don't drift if @BotFather is
        # later edited by hand.
        await bot.set_my_commands(
            PUBLIC_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

        # Drop any pending updates queued while the bot was offline.
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await close_client()
        await close_engine()
        await bot.session.close()
        log.info("bot.stopped")


if __name__ == "__main__":
    asyncio.run(main())
