"""Semantic-layer error types (FEAT-05-4).

A malformed semantic query is rejected with a typed, stable-coded error derived
from the platform-wide `emg_errors.EMGError` hierarchy, so query rejection is
handled and logged the same way as every other EMG error (ADR-015 §1). Field- and
structure-level rejections raised inside pydantic validators surface as
`pydantic.ValidationError`; cross-model semantic rejections (raised by the pure
planner/validator) surface as `SemanticQueryError`.
"""

from __future__ import annotations

from emg_errors import ValidationError


class SemanticQueryError(ValidationError):
    """Raised when a semantic query is structurally valid per field types but
    semantically malformed (e.g. an ordering key that projects nothing, a
    traversal deeper than the governed maximum). Subclasses the shared
    `ValidationError` so callers can catch it generically."""

    error_code = "SEMANTIC_QUERY_ERROR"
