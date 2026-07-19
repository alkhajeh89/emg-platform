"""The backend-agnostic migration executor contract (Phase 2, Sprint 2).

The :class:`MigrationExecutor` ``Protocol`` is the seam between the pure
:class:`~emg_persistence.migrations.runner.MigrationRunner` (which owns
ordering, checksum immutability, dirty/failed detection, and forward-only
application) and the concrete backends (PostgreSQL transactional migrations,
Neo4j idempotent migrations). The runner depends only on this contract, so it is
fully unit-testable against an in-memory fake, and the same logic drives both
real datastores.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import AppliedMigration, Migration, MigrationKind


@runtime_checkable
class MigrationExecutor(Protocol):
    """Backend contract for recording and applying migrations."""

    @property
    def kind(self) -> MigrationKind:
        """The datastore this executor targets."""
        ...

    def ensure_history(self) -> None:
        """Idempotently create the migration-history store (the PostgreSQL
        ``schema_migrations`` table / the Neo4j ``:SchemaMigration`` marker
        constraint) if it does not already exist."""
        ...

    def fetch_applied(self) -> tuple[AppliedMigration, ...]:
        """Return every recorded migration (including failed/dirty ones), so the
        runner can verify checksums and detect dirty/failed state."""
        ...

    def apply(self, migration: Migration) -> AppliedMigration:
        """Apply ``migration`` and record it as applied.

        Backends provide the required guarantees: PostgreSQL applies the SQL and
        writes the history row in a **single transaction** (all-or-nothing);
        Neo4j applies **idempotent** statements then writes its marker. On
        failure the executor records a dirty/failed state (best effort) and
        raises :class:`~emg_persistence.migrations.errors.FailedMigrationError`.
        """
        ...
