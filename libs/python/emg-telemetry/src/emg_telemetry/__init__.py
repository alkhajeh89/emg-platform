"""emg_telemetry — structured logging + correlation-ID propagation client.

Scaffolded in Sprint 1 (FEAT-01-2 / Engineering Master Plan §2: "logging/
telemetry client (ADR-015)"). Implements the shared Logs primitive from
ADR-015 Section 1 only; Metrics/Traces emitters, per-layer extensions
(Graph/Search/Decision Observability), dashboards, and alerting land with
FEAT-12-3/12-4 (EPIC-12).
"""

from .context import (
    MAX_CORRELATION_ID_LENGTH,
    correlation_id_var,
    get_correlation_id,
    set_correlation_id,
)
from .logger import get_logger

__version__ = "0.1.0"

__all__ = [
    "get_logger",
    "correlation_id_var",
    "MAX_CORRELATION_ID_LENGTH",
    "get_correlation_id",
    "set_correlation_id",
    "__version__",
]
