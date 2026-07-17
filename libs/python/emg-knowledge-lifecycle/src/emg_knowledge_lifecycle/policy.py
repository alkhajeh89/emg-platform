"""Lifecycle + retention policy (FEAT-05-5).

`LifecyclePolicy` is the immutable, versioned configuration governing which
managed transitions are permitted (on top of the fixed state-machine table) and
whether an event must carry a reason. `RetentionPolicy` is the immutable,
versioned configuration for how long versions in each terminal-ish state are
retained, when they become archive-eligible, and how long they remain
restore-eligible after archiving. Both are pure configuration — no scheduler, no
clock, no persistence — evaluated deterministically against an explicit `as_of`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .limits import MAX_RETENTION_DAYS
from .states import VersionState, is_restore_transition, is_valid_transition

LIFECYCLE_POLICY_VERSION = 1
RETENTION_POLICY_VERSION = 1


class LifecyclePolicy(BaseModel):
    """Immutable transition policy layered over the fixed state machine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: int = LIFECYCLE_POLICY_VERSION
    allow_restore: bool = True
    # When True, a LifecycleEvent must carry a reason. Enforced by
    # LifecycleValidator.validate_event / assert_event (raising MissingReasonError);
    # a whitespace-only reason is separately rejected at event construction.
    require_reason: bool = False

    def permits_transition(self, from_state: VersionState, to_state: VersionState) -> bool:
        """True iff the transition is permitted: it must be legal in the fixed
        state machine, and (if it is the restore transition) restore must be
        enabled by this policy. Pure and deterministic."""
        if not is_valid_transition(from_state, to_state):
            return False
        # The archive->restore transition additionally requires restore to be
        # enabled by this policy.
        return not (is_restore_transition(from_state, to_state) and not self.allow_restore)


class RetentionPolicy(BaseModel):
    """Immutable retention configuration. Windows are whole days measured from a
    version's retention anchor (its ``effective_to`` if set, else
    ``effective_from``). ``None`` means "retain indefinitely"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: int = RETENTION_POLICY_VERSION
    # Per-state retention windows (days). Live states are retained indefinitely by
    # default; superseded/retired have finite defaults.
    retain_deprecated_days: int | None = Field(default=None, ge=0, le=MAX_RETENTION_DAYS)
    retain_superseded_days: int | None = Field(default=365, ge=0, le=MAX_RETENTION_DAYS)
    retain_retired_days: int | None = Field(default=30, ge=0, le=MAX_RETENTION_DAYS)
    # How long after retention expiry a version becomes archive-eligible.
    archive_after_days: int = Field(default=0, ge=0, le=MAX_RETENTION_DAYS)
    # How long after its retention anchor an archived version stays restorable.
    restore_window_days: int = Field(default=3650, ge=0, le=MAX_RETENTION_DAYS)

    def retention_days_for(self, state: VersionState) -> int | None:
        """The retention window (days) for a state, or None for indefinite."""
        if state is VersionState.DEPRECATED:
            return self.retain_deprecated_days
        if state is VersionState.SUPERSEDED:
            return self.retain_superseded_days
        if state is VersionState.RETIRED:
            return self.retain_retired_days
        # PROPOSED / ACTIVE / ARCHIVED are retained indefinitely (archived items
        # are already at their retention endpoint).
        return None


DEFAULT_LIFECYCLE_POLICY = LifecyclePolicy()
DEFAULT_RETENTION_POLICY = RetentionPolicy()
