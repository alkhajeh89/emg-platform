"""Lifecycle transition events (FEAT-05-5).

`LifecycleEvent` is an immutable record of a single managed state transition for a
version: which version, from which state to which state, when, by whom, and why.
It is a value object only — this library records nothing and persists nothing; a
consumer (or a future audit binding) is responsible for emitting/storing events.
An event is **self-validating**: it can only describe a transition that the state
machine permits, so a `LifecycleEvent` can never represent an illegal transition.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from .identifiers import VersionIdentifier
from .labels import SafeLabel, SafeText
from .states import VersionState, is_valid_transition


class LifecycleEvent(BaseModel):
    """An immutable, self-validating record of one legal state transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: VersionIdentifier
    from_state: VersionState
    to_state: VersionState
    occurred_at: datetime
    actor: SafeLabel
    reason: SafeText | None = None

    @model_validator(mode="after")
    def _validate_transition(self) -> LifecycleEvent:
        if not is_valid_transition(self.from_state, self.to_state):
            raise ValueError(
                f"illegal lifecycle transition {self.from_state.value} -> {self.to_state.value}"
            )
        return self

    @property
    def is_restore(self) -> bool:
        from .states import is_restore_transition

        return is_restore_transition(self.from_state, self.to_state)
