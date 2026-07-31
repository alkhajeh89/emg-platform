"""Correlation-ID propagation via contextvars.

Implements ADR-015 Section 3 (Traces): "Every stage of both lifecycles
propagates a single correlation identifier end-to-end." This module provides
the propagation primitive; actual cross-service header propagation (HTTP/
gRPC middleware) is implemented per-service starting with Module 4 (EPIC-02),
consistent with Engineering Master Plan §11 (Module Implementation Order:
"Observability ... instrumented starting with Module 4").
"""

from __future__ import annotations

import re
from contextvars import ContextVar

from emg_common_types import CorrelationId, new_correlation_id

correlation_id_var: ContextVar[CorrelationId | None] = ContextVar(
    "emg_correlation_id", default=None
)
MAX_CORRELATION_ID_LENGTH = 128
_CORRELATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def set_correlation_id(correlation_id: CorrelationId | None = None) -> CorrelationId:
    """Set a bounded safe correlation ID, replacing invalid input."""
    cid = (
        correlation_id
        if correlation_id
        and len(correlation_id) <= MAX_CORRELATION_ID_LENGTH
        and _CORRELATION_ID_PATTERN.fullmatch(correlation_id)
        else new_correlation_id()
    )
    correlation_id_var.set(cid)
    return cid


def get_correlation_id() -> CorrelationId | None:
    """Return the correlation ID for the current execution context, if set."""
    return correlation_id_var.get()
