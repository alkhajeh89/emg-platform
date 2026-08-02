"""Typed error hierarchy for emg-persistence (Phase 2 — Persistence Binding).

All operational failures raised by this package derive from ``PersistenceError``,
which derives from the platform-wide ``emg_errors.EMGError`` so callers can catch
persistence problems specifically or platform problems generally. Malformed
*configuration* still raises ``pydantic.ValidationError`` at construction; these
typed errors cover *operational* failures in the persistence layer.

The hierarchy is defined up front (Sprint 1) so the public error surface is
stable across the remaining Phase 2 sprints; the sites that raise these errors
are implemented in the sprints that add the corresponding behaviour (per
PHASE2_ARCHITECTURE.md Revision 3 and PHASE2_PLAN.md).
"""

from __future__ import annotations

from emg_errors import EMGError


class PersistenceError(EMGError):
    """Base class for every emg-persistence operational error."""


class PersistenceConflictError(PersistenceError):
    """A write could not be committed because the authoritative PostgreSQL head
    advanced concurrently (optimistic-concurrency conflict).

    Raised *before* any durable change — the caller should re-open the
    transaction (which observes the new head) and retry. Also covers the
    first-revision race and the no-op stale-head case (ADR-5, §7).
    """


class ProjectionLagError(PersistenceError):
    """The Neo4j serving projection is behind the authoritative PostgreSQL head.

    Internal signal only (read-repair / ``catch_up_projection``); per ADR-2/ADR-6
    it is **never** surfaced from ``GraphStore.write()`` or ``read()`` — reads
    fall back to PostgreSQL when the projection is unavailable or lagging.
    """


class EvidenceLedgerIntegrityError(PersistenceError):
    """Stored evidence-ledger content failed non-retryable integrity checks."""
