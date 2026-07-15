"""Correlation identifier type shared across logs, metrics, traces, and audit
records, per ADR-015 Section 3 (Traces): "Every stage ... propagates a
single correlation identifier end-to-end."
"""

from __future__ import annotations

import uuid

CorrelationId = str
"""Type alias documenting intent; kept as `str` (not a wrapper class) so it
serializes identically across every service's log/metric/trace/audit
emission without custom (de)serialization code."""


def new_correlation_id() -> CorrelationId:
    """Generate a new correlation identifier (UUIDv4)."""
    return str(uuid.uuid4())
