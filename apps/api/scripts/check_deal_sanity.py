"""Fail fast when public deals contain non-discounts.

Run inside the api container:
    python -m scripts.check_deal_sanity
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from src.infra.db import async_session_factory


async def main() -> int:
    async with async_session_factory() as db:
        bad_public = (
            await db.execute(
                text(
                    """SELECT COUNT(*)
                       FROM deals
                       WHERE source IN ('farvater_scrape', 'live_refresh', 'ittour')
                         AND discount_pct <= 0"""
                )
            )
        ).scalar_one()
        bad_unposted_bucket = (
            await db.execute(
                text(
                    """SELECT COUNT(*)
                       FROM deals
                       WHERE posted_at IS NULL
                         AND detection_method LIKE 'bucket_%'"""
                )
            )
        ).scalar_one()

    if bad_public or bad_unposted_bucket:
        print(
            "deal sanity failed: "
            f"non_discount_public={bad_public}, "
            f"unposted_bucket_deals={bad_unposted_bucket}",
            file=sys.stderr,
        )
        return 1
    print("deal sanity ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
