"""Migration orchestration entrypoints (Phase 2, Sprint 2).

Thin, database-agnostic glue that ties migration *discovery* to the
:class:`~emg_persistence.migrations.runner.MigrationRunner` for a given
:class:`~emg_persistence.migrations.executor.MigrationExecutor`. The executor
(PostgreSQL or Neo4j) is injected, so these functions are fully unit-testable
without a live database and work identically against either backend.

The baseline migration files ship inside the package:

* PostgreSQL: ``emg_persistence/migrations/postgres/V001__baseline.sql``
* Neo4j:      ``emg_persistence/migrations/neo4j/M001__constraints.cypher``
"""

from __future__ import annotations

from pathlib import Path

from .migrations.discovery import discover_migrations
from .migrations.executor import MigrationExecutor
from .migrations.model import AppliedMigration, MigrationKind, MigrationStatus
from .migrations.runner import MigrationRunner

_MIGRATIONS_ROOT = Path(__file__).resolve().parent / "migrations"
_SUBDIR = {MigrationKind.POSTGRES: "postgres", MigrationKind.NEO4J: "neo4j"}


def default_migrations_dir(kind: MigrationKind) -> Path:
    """Return the packaged baseline migrations directory for ``kind``."""
    return _MIGRATIONS_ROOT / _SUBDIR[kind]


def audit_migrations_dir() -> Path:
    """Return the packaged ADR-041 Audit PostgreSQL migration stream."""

    return _MIGRATIONS_ROOT / "audit_postgres"


def run_migrations(
    executor: MigrationExecutor, migrations_dir: Path | None = None
) -> tuple[AppliedMigration, ...]:
    """Discover and apply pending migrations for ``executor``'s datastore.

    Args:
        executor: the backend executor (PostgreSQL or Neo4j).
        migrations_dir: directory of migration files; defaults to the packaged
            baseline directory for ``executor.kind``.

    Returns:
        The migrations applied by this call (empty when already up to date).
    """
    if migrations_dir is None:
        migrations_dir = default_migrations_dir(executor.kind)
    discovered = discover_migrations(migrations_dir, executor.kind)
    return MigrationRunner(executor).run(discovered)


def migration_status(
    executor: MigrationExecutor, migrations_dir: Path | None = None
) -> MigrationStatus:
    """Report applied vs pending migrations for ``executor``'s datastore."""
    if migrations_dir is None:
        migrations_dir = default_migrations_dir(executor.kind)
    discovered = discover_migrations(migrations_dir, executor.kind)
    return MigrationRunner(executor).status(discovered)
