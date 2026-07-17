"""Decision result models (FEAT-05-5).

The immutable, explainable **outputs** of the pure retention/archive/restore
evaluators (`retention.py`). Each decision names the version it concerns, a
boolean verdict, and a human-readable reason. They are engine outputs: a caller
obtains them from the evaluators and must not fabricate one in place of a real
evaluation (the documented trust boundary; they remain internally consistent).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .identifiers import VersionIdentifier
from .states import VersionState


class RetentionDecision(BaseModel):
    """Whether a version is still retained at the evaluation time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: VersionIdentifier
    state: VersionState
    retain: bool
    expires_on: datetime | None  # None => retained indefinitely
    reason: str


class ArchiveDecision(BaseModel):
    """Whether a version is eligible to be archived at the evaluation time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: VersionIdentifier
    eligible: bool
    reason: str


class RestoreDecision(BaseModel):
    """Whether an archived version is eligible to be restored at the evaluation
    time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: VersionIdentifier
    eligible: bool
    reason: str
