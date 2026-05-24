"""CLI wrapper for the long-tail sitemap ingest.

The real implementation lives in `src.jobs.sitemap_long_tail` so it can
be registered as an APScheduler job too. This wrapper is kept so an
operator can kick a one-off run on demand:

    docker exec -d -w /app ft_scheduler python scripts/ingest_sitemap_catalog.py [CAP]

The job is idempotent (slug-dedup), safe to re-run mid-flight.
"""
from __future__ import annotations

import asyncio
import sys

from src.jobs.sitemap_long_tail import main


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(main(cap))
