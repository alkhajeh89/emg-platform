"""Typed errors for the migration framework (Phase 2, Sprint 2).

All derive from ``PersistenceError`` so migration failures are catchable as
persistence problems (or platform problems via ``emg_errors.EMGError``).
"""

from __future__ import annotations

from ..errors import PersistenceError


class MigrationError(PersistenceError):
    """Base class for every migration-framework error."""


class MigrationDiscoveryError(MigrationError):
    """A migration file is malformed or a version number is duplicated."""


class ChecksumMismatchError(MigrationError):
    """An already-applied migration's on-disk checksum has changed.

    Applied migrations are immutable; editing one after it has been applied is a
    correctness hazard, so the runner refuses to proceed.
    """


class DirtyMigrationError(MigrationError):
    """A previously-started migration did not finish cleanly (dirty state).

    The runner halts rather than risk applying on top of a partial schema.
    """


class FailedMigrationError(MigrationError):
    """A migration failed to apply (recorded ``success = false``), or the current
    application raised. The runner halts until the failure is resolved."""
