"""Typed error hierarchy for emg-platform-core (Phase 1 — Platform Foundation).

All operational failures raised by this package derive from
``PlatformCoreError``, which derives from the platform-wide
``emg_errors.EMGError`` so callers can catch platform-foundation problems
specifically or platform problems generally. Malformed *models* still raise
``pydantic.ValidationError`` at construction; these typed errors cover
*operational* failures in the storage seam (missing graph, tenant mismatch,
misused transaction).
"""

from __future__ import annotations

from emg_errors import EMGError


class PlatformCoreError(EMGError):
    """Base class for every emg-platform-core operational error."""


class TransactionStateError(PlatformCoreError):
    """A graph transaction was used outside its valid lifecycle (e.g. read or
    stage after the unit of work has already been committed or aborted)."""


class RevisionNotFoundError(PlatformCoreError):
    """A ``GraphRevisionReader`` could not resolve ``(tenant, revision_number)``.

    Raised identically whether the revision number is simply unused or belongs
    to a different tenant — the two cases must be indistinguishable to the
    caller (ADR-023 §22)."""


class SnapshotIntegrityError(PlatformCoreError):
    """A deserialized historical graph payload's recomputed content hash does
    not match its stored ``content_hash`` (ADR-023 §17)."""


class UnsupportedHistoryCapabilityError(PlatformCoreError):
    """A ``GraphStore`` adapter does not support ``GraphRevisionReader``
    history operations for the requested tenant/revision (ADR-023 §9).

    Reserved for forward compatibility; neither ``InMemoryGraphStore`` nor
    ``PostgresNeo4jGraphStore`` is expected to raise this today."""
