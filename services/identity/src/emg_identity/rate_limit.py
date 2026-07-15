"""Rate-limiting readiness for token-issuance endpoints (Sprint 3, Required
Security Controls: "Rate-limiting readiness for token requests").

This is explicitly *readiness*, not a production control: `InMemoryRateLimiter`
is single-process and resets on restart, which is unsuitable for a
horizontally-scaled deployment (Engineering Master Plan §5, ADR-017 §2).
The `RateLimiter` Protocol is the swap-in seam — a Redis- or
gateway-backed limiter can replace `InMemoryRateLimiter` in
`dependencies.py` without changing `routers/auth.py`, the same pattern
Sprint 2 used for `AuditEventSink`/`StructuredLogAuditSink`.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Protocol

from emg_errors import EMGError


class RateLimitedError(EMGError):
    """Raised when a caller has exceeded the configured attempt budget."""

    error_code = "RATE_LIMITED"


class RateLimiter(Protocol):
    def check(self, key: str) -> None:
        """Raise RateLimitedError if `key` has exceeded its budget; return
        None (record the attempt) otherwise."""
        ...


class InMemoryRateLimiter:
    """Fixed-window-ish limiter: at most `max_attempts` calls to `check()`
    for a given key within `window_seconds`, tracked in memory."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        now = time.monotonic()
        window_start = now - self._window_seconds
        attempts = self._attempts.setdefault(key, deque())

        while attempts and attempts[0] < window_start:
            attempts.popleft()

        if len(attempts) >= self._max_attempts:
            raise RateLimitedError(f"Too many attempts for '{key}'; try again later")

        attempts.append(now)
