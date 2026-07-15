"""Base exception every EMG service-level error derives from."""

from __future__ import annotations


class EMGError(Exception):
    """Base class for all EMG platform errors.

    Attributes:
        error_code: Stable, machine-readable code (e.g. "VALIDATION_ERROR").
            Consumed by emg_api_contracts when mapping to an API error
            envelope, and included in structured log events (ADR-015 §1).
        message: Human-readable description.
    """

    error_code: str = "EMG_ERROR"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
