"""InMemoryRateLimiter tests (Required Security Control: "Rate-limiting
readiness for token requests"). Unit-level only; the /auth/login 429
integration is covered in test_auth_router.py-adjacent coverage below."""

from __future__ import annotations

import pytest
from emg_identity.rate_limit import InMemoryRateLimiter, RateLimitedError


def test_allows_up_to_max_attempts_within_window():
    limiter = InMemoryRateLimiter(max_attempts=3, window_seconds=60.0)
    for _ in range(3):
        limiter.check("dev.investigator")  # must not raise


def test_raises_once_max_attempts_exceeded():
    limiter = InMemoryRateLimiter(max_attempts=3, window_seconds=60.0)
    for _ in range(3):
        limiter.check("dev.investigator")

    with pytest.raises(RateLimitedError):
        limiter.check("dev.investigator")


def test_limits_are_tracked_independently_per_key():
    limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60.0)
    limiter.check("user-a")  # consumes user-a's only slot

    limiter.check("user-b")  # must not raise — independent key


def test_window_expiry_allows_further_attempts(monkeypatch):
    limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=10.0)
    current_time = [1000.0]
    monkeypatch.setattr("emg_identity.rate_limit.time.monotonic", lambda: current_time[0])

    limiter.check("dev.investigator")
    with pytest.raises(RateLimitedError):
        limiter.check("dev.investigator")

    current_time[0] += 11.0  # advance past the window
    limiter.check("dev.investigator")  # must not raise
