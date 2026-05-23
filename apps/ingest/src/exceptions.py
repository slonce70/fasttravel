"""Ingest-layer exception hierarchy.

Design rule: every failure mode that the pipeline can recover from gets
its own exception class so `pipeline.run_snapshot` can decide whether to
mark a `scrape_runs` row as `failed`, `skipped_no_token`, or
`partial_success`. Bare `Exception` from a client always means "we don't
know what happened, fail loud".
"""
from __future__ import annotations


class IngestError(Exception):
    """Base class for everything raised inside apps/ingest."""


class IngestConfigError(IngestError):
    """Misconfiguration — bad URL, missing required env, etc. Fail loud."""


class ClientNotConfigured(IngestError):
    """A required credential (API token, basic-auth user) is empty.

    Pipeline treats this as a graceful skip — `scrape_runs.status` is
    set to `skipped_no_token` and the run finishes without errors.
    """

    def __init__(self, source: str, missing_env: str) -> None:
        self.source = source
        self.missing_env = missing_env
        super().__init__(
            f"{source} client not configured — set env var {missing_env} to enable"
        )


class ITTourNotConfigured(ClientNotConfigured):
    def __init__(self) -> None:
        super().__init__("ittour", "ITTOUR_API_TOKEN")


class TBONotConfigured(ClientNotConfigured):
    def __init__(self) -> None:
        super().__init__("tbo", "TBO_USERNAME / TBO_PASSWORD")


class UpstreamHTTPError(IngestError):
    """Non-2xx response from an upstream source after retries are exhausted."""

    def __init__(self, source: str, status_code: int, body_excerpt: str) -> None:
        self.source = source
        self.status_code = status_code
        self.body_excerpt = body_excerpt
        super().__init__(
            f"{source} returned HTTP {status_code}: {body_excerpt[:200]}"
        )


class RateLimitExceeded(UpstreamHTTPError):
    """Upstream said 429. Caller may decide to circuit-break."""


class ForbiddenByUpstream(UpstreamHTTPError):
    """Upstream said 403 — often a Cloudflare/anti-bot block."""


class CircuitBreakerTripped(IngestError):
    """We saw too many consecutive 429/403 — stop hammering, alert operators.

    Specific to the farvater scraper. The pipeline catches this and marks
    the run as `circuit_breaker` so the scheduler can disable the source.
    """


class NormalizationError(IngestError):
    """A raw payload row failed to normalize. Caller should skip the row,
    log a warn with the reason, and continue with siblings."""


class DataLossDetected(IngestError):
    """source_count != success + quarantine — Sev-1.

    Borrowed from the remediation-layer reconciliation contract: if we
    cannot prove every row landed somewhere (DB or quarantine log) the
    run must NOT be marked successful.
    """


class BootstrapBreakerOpen(IngestError):
    """Farvater-specific circuit breaker tripped — stop until cooldown."""

    def __init__(self, source: str, until_iso: str) -> None:
        self.source = source
        self.until_iso = until_iso
        super().__init__(
            f"{source} circuit breaker open until {until_iso} — "
            "too many consecutive 429/403"
        )


class BootstrapDailyCapHit(IngestError):
    """Farvater daily request cap reached — wait for UTC midnight."""

    def __init__(self, source: str, used: int) -> None:
        self.source = source
        self.used = used
        super().__init__(
            f"{source} daily cap reached ({used} requests) — "
            "will reset at next UTC midnight"
        )
