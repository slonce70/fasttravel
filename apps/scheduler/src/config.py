"""Scheduler configuration — inherits shared base, adds Telegram + job knobs."""

from __future__ import annotations

from functools import lru_cache

from shared.infra.base_settings import BaseAppSettings


class Settings(BaseAppSettings):
    # --- Database tuning (scheduler runs heavier jobs, smaller pool) ---
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    # --- Telegram ---
    # We accept str | None — channel id can be -100... numeric or @slug string.
    # Bot token absence is a first-class state: post_deals skips gracefully.
    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None
    public_site_url: str = "https://fasttravel.com.ua"

    # --- Job tuning ---
    # Telegram channel daily post cap (anti-spam contract with subscribers).
    deals_daily_cap: int = 30
    # How many unposted deals to consider per post_deals tick.
    deals_per_post_tick: int = 5
    # Sleep between sendMessage calls to stay under Telegram's 30 msg/sec
    # per-chat soft limit. 2s is conservative and keeps the worker simple
    # (no aiogram throttling middleware needed for MVP).
    telegram_send_delay_seconds: float = 2.0
    # Retention for price_observations partitions (days).
    partition_retention_days: int = 60

    # --- Scheduler / timezone ---
    scheduler_timezone: str = "Europe/Kyiv"

    # --- Prometheus metrics ---
    # Plain int (not None) so the metrics HTTP server always boots; if
    # operators want to disable scraping in dev they can firewall the port.
    metrics_port: int = 9101

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token) and bool(self.telegram_channel_id)

    def _extra_prod_offenders(self) -> list[str]:
        offenders: list[str] = []
        # Telegram is required in prod only when the channel posting is
        # actually enabled. Skip when ops deliberately set daily_cap=0
        # (kill switch for the broadcast).
        if self.deals_daily_cap > 0:
            if not self.telegram_bot_token:
                offenders.append("TELEGRAM_BOT_TOKEN")
            if not self.telegram_channel_id:
                offenders.append("TELEGRAM_CHANNEL_ID")
        return offenders


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — read once per process."""
    return Settings()
