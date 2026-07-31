"""PostgreSQL migration executor — transactional migrations (Phase 2, Sprint 2).

Implements the :class:`~emg_persistence.migrations.executor.MigrationExecutor`
contract for PostgreSQL. Each migration's SQL **and** its history row are applied
in a **single transaction** (all-or-nothing); on failure the transaction rolls
back and a dirty/failed marker is recorded so the next run halts.

Only the pure surface (``kind``, construction) is unit-tested; the methods that
touch a live database are integration-tested by the CI ``persistence`` job and
are marked ``# pragma: no cover`` here because they cannot run without PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..migrations.errors import FailedMigrationError
from ..migrations.model import AppliedMigration, Migration, MigrationKind

if TYPE_CHECKING:
    from psycopg import Connection

_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    kind        text        NOT NULL,
    version     integer     NOT NULL,
    name        text        NOT NULL,
    checksum    text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    success     boolean     NOT NULL DEFAULT true,
    dirty       boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (kind, version)
)
"""
_SELECT_APPLIED = (
    "SELECT version, name, checksum, applied_at, success, dirty "
    "FROM schema_migrations WHERE kind = %(kind)s ORDER BY version"
)
_INSERT_SUCCESS = (
    "INSERT INTO schema_migrations (kind, version, name, checksum, applied_at, success, dirty) "
    "VALUES (%(kind)s, %(version)s, %(name)s, %(checksum)s, %(applied_at)s, true, false)"
)
_MARK_DIRTY = (
    "INSERT INTO schema_migrations (kind, version, name, checksum, applied_at, success, dirty) "
    "VALUES (%(kind)s, %(version)s, %(name)s, %(checksum)s, %(applied_at)s, false, true) "
    "ON CONFLICT (kind, version) DO UPDATE SET success = false, dirty = true"
)


class PostgresMigrationExecutor:
    """A :class:`MigrationExecutor` backed by a PostgreSQL connection."""

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    @property
    def kind(self) -> MigrationKind:
        return MigrationKind.POSTGRES

    def ensure_history(self) -> None:  # pragma: no cover - requires a live PostgreSQL
        with self._connection.cursor() as cur:
            cur.execute(_HISTORY_DDL)
        self._connection.commit()

    def fetch_applied(self) -> tuple[AppliedMigration, ...]:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(_SELECT_APPLIED, {"kind": MigrationKind.POSTGRES.value})
            rows = cur.fetchall()
        # psycopg starts an implicit transaction for the SELECT above. End that
        # read-only scope so each subsequent ``apply()`` owns a real top-level
        # transaction rather than only a savepoint whose outer transaction
        # would be rolled back when the migration connection closes.
        self._connection.commit()
        return tuple(
            AppliedMigration(
                version=row[0],
                name=row[1],
                kind=MigrationKind.POSTGRES,
                checksum=row[2],
                applied_at=row[3],
                success=row[4],
                dirty=row[5],
            )
            for row in rows
        )

    def apply(self, migration: Migration) -> AppliedMigration:  # pragma: no cover - live DB
        applied_at = datetime.now(timezone.utc)
        params = {
            "kind": MigrationKind.POSTGRES.value,
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
            "applied_at": applied_at,
        }
        try:
            with self._connection.transaction(), self._connection.cursor() as cur:
                cur.execute(migration.statements)
                cur.execute(_INSERT_SUCCESS, params)
        except Exception as exc:
            self._mark_dirty(params)
            raise FailedMigrationError(
                f"PostgreSQL migration V{migration.version} ({migration.name}) failed: {exc}"
            ) from exc
        return AppliedMigration(
            version=migration.version,
            name=migration.name,
            kind=MigrationKind.POSTGRES,
            checksum=migration.checksum,
            applied_at=applied_at,
            success=True,
            dirty=False,
        )

    def _mark_dirty(self, params: dict[str, object]) -> None:  # pragma: no cover - live DB
        try:
            with self._connection.transaction(), self._connection.cursor() as cur:
                cur.execute(_MARK_DIRTY, params)
        except Exception:
            # Best-effort; the migration failure is already being raised.
            self._connection.rollback()
