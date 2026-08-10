"""emg_telemetry — structured logging + correlation-ID propagation client.

Scaffolded in Sprint 1 (FEAT-01-2 / Engineering Master Plan §2: "logging/
telemetry client (ADR-015)"). Implements the shared Logs primitive from
ADR-015 Section 1. Metrics (ADR-015 Section 2) are implemented by the
`metrics` submodule (RC-C, EMG v1 RC closure): a dependency-free
Prometheus-text-exposition registry, deliberately not re-exported here so
importing `emg_telemetry` never requires anything metrics-related. FastAPI
HTTP-metrics glue lives in the separate `http_metrics` submodule for the
same reason (see its module docstring). Traces, and per-layer extensions
(Graph/Search/Decision Observability) beyond what RC-C instruments, remain
unimplemented; see `docs/release/EMG_V1_RELEASE_CANDIDATE_CLOSURE_REVIEW.md`.
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
