"""Pure retention / archive / restore evaluation (FEAT-05-5).

Deterministic evaluators that answer three questions about a version *at an
explicit moment* (`as_of`; never a wall-clock read):

  * `evaluate_retention` — is the version still retained, and when does retention
    expire?
  * `evaluate_archive`    — is the version eligible to be archived yet?
  * `evaluate_restore`    — is an archived version still eligible to be restored?

There is **no scheduler, no execution engine, and no persistence** here — these
functions only compute a decision from a version, a policy, and a timestamp, and
return an immutable, explainable decision model.

**Retention anchor (explicit semantics).** All three evaluators measure their
windows from a version's *effective-end reference*: its ``effective_to`` (when it
stopped being effective) if set, else its ``effective_from``. In particular,
``restore_window_days`` is measured from this **effective-end reference, not from
the actual moment of archival** — this library models no archival-event timestamp
(FEAT-05-5 is storage-independent and event-emission is a future binding concern),
so "restorable for N days after it left service" is the defined, deterministic
semantics. A consumer that needs restore measured from a true ``archived_at`` must
supply that at the binding layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .decisions import ArchiveDecision, RestoreDecision, RetentionDecision
from .policy import DEFAULT_RETENTION_POLICY, RetentionPolicy
from .states import VersionState
from .version import KnowledgeVersion

# States that can be archived (cold) — a version must have left live service first.
_ARCHIVE_ELIGIBLE_STATES: frozenset[VersionState] = frozenset(
    {VersionState.SUPERSEDED, VersionState.RETIRED}
)


def _anchor(version: KnowledgeVersion) -> datetime:
    return version.effective_to if version.effective_to is not None else version.effective_from


def evaluate_retention(
    version: KnowledgeVersion,
    as_of: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> RetentionDecision:
    """Whether `version` is still retained at `as_of`. Deterministic."""
    days = policy.retention_days_for(version.state)
    if days is None:
        return RetentionDecision(
            version=version.identifier,
            state=version.state,
            retain=True,
            expires_on=None,
            reason=f"state {version.state.value} is retained indefinitely",
        )
    expires_on = _anchor(version) + timedelta(days=days)
    retain = as_of < expires_on
    reason = (
        f"retained until {expires_on.isoformat()} ({days}d window)"
        if retain
        else f"retention expired on {expires_on.isoformat()} ({days}d window)"
    )
    return RetentionDecision(
        version=version.identifier,
        state=version.state,
        retain=retain,
        expires_on=expires_on,
        reason=reason,
    )


def evaluate_archive(
    version: KnowledgeVersion,
    as_of: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> ArchiveDecision:
    """Whether `version` is eligible to be archived at `as_of`. A version becomes
    archive-eligible once it is in a cold state (superseded/retired) and its
    retention window has expired plus `archive_after_days`. Deterministic."""
    if version.state is VersionState.ARCHIVED:
        return ArchiveDecision(
            version=version.identifier, eligible=False, reason="already archived"
        )
    if version.state not in _ARCHIVE_ELIGIBLE_STATES:
        return ArchiveDecision(
            version=version.identifier,
            eligible=False,
            reason=f"state {version.state.value} is not archive-eligible "
            "(must be superseded or retired)",
        )
    retention = evaluate_retention(version, as_of, policy)
    if retention.retain or retention.expires_on is None:
        return ArchiveDecision(
            version=version.identifier,
            eligible=False,
            reason="retention window has not expired",
        )
    archive_ready_on = retention.expires_on + timedelta(days=policy.archive_after_days)
    eligible = as_of >= archive_ready_on
    reason = (
        f"archive-eligible since {archive_ready_on.isoformat()}"
        if eligible
        else f"archive-eligible on {archive_ready_on.isoformat()}"
    )
    return ArchiveDecision(version=version.identifier, eligible=eligible, reason=reason)


def evaluate_restore(
    version: KnowledgeVersion,
    as_of: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> RestoreDecision:
    """Whether an archived `version` is still eligible to be restored at `as_of`.
    Only archived versions are restorable, and only within `restore_window_days`
    of the **effective-end reference** (`effective_to` if set, else
    `effective_from`) — not from the actual archival moment, which this
    storage-independent library does not model. Deterministic."""
    if version.state is not VersionState.ARCHIVED:
        return RestoreDecision(
            version=version.identifier,
            eligible=False,
            reason=f"only archived versions can be restored (state is {version.state.value})",
        )
    restore_deadline = _anchor(version) + timedelta(days=policy.restore_window_days)
    eligible = as_of < restore_deadline
    reason = (
        f"restorable until {restore_deadline.isoformat()} "
        f"({policy.restore_window_days}d window)"
        if eligible
        else f"restore window closed on {restore_deadline.isoformat()}"
    )
    return RestoreDecision(version=version.identifier, eligible=eligible, reason=reason)
