"""Shared Redis refresh queue primitives.

Both API user refreshes and scheduler hot-priority refreshes push into the
same Redis list. Keep the hard cap here so every producer enforces the same
capacity contract.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Any

REFRESH_QUEUE_KEY = "refresh:queue"
REFRESH_QUEUE_MAX_LEN = 200

_ENQUEUE_WITH_CAP_SCRIPT = """
local current = redis.call('LLEN', KEYS[1])
local cap = tonumber(ARGV[1])
if current >= cap then
  return {0, current}
end
redis.call('LPUSH', KEYS[1], ARGV[2])
return {1, current + 1}
"""


class RefreshQueueFullError(RuntimeError):
    def __init__(self, current: int, cap: int) -> None:
        self.current = current
        self.cap = cap
        super().__init__(f"refresh queue full ({current}/{cap})")


class RefreshQueueUnavailableError(RuntimeError):
    """Raised when Redis cannot run the atomic queue-cap script."""


async def _await_if_needed(value: Awaitable[Any] | Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def push_refresh_job_with_cap(
    redis: Any,
    payload_json: str,
    *,
    queue_key: str = REFRESH_QUEUE_KEY,
    max_len: int = REFRESH_QUEUE_MAX_LEN,
) -> int:
    """Atomically push one refresh job unless the shared queue is full.

    Returns the queue length after a successful push.
    """
    try:
        raw = await _await_if_needed(
            redis.eval(
                _ENQUEUE_WITH_CAP_SCRIPT,
                1,
                queue_key,
                str(max_len),
                payload_json,
            )
        )
        inserted = int(raw[0])
        current = int(raw[1])
    except (IndexError, TypeError, ValueError) as exc:
        raise RefreshQueueUnavailableError("refresh queue unavailable") from exc

    if not inserted:
        raise RefreshQueueFullError(current, max_len)
    return current
