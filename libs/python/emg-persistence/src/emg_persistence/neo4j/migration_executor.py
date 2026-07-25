"""Neo4j migration executor — idempotent migrations (Phase 2, Sprint 2).

Implements the :class:`~emg_persistence.migrations.executor.MigrationExecutor`
contract for Neo4j. Neo4j has no transactional DDL, so migrations are made
**idempotent** at authorship time (``CREATE CONSTRAINT/INDEX IF NOT EXISTS``);
each version's completion is recorded as a ``:SchemaMigration`` marker so
re-running is safe.

``split_cypher_statements`` is pure and unit-tested; the driver-backed methods
require a live Neo4j and are integration-tested by the CI ``persistence`` job
(marked ``# pragma: no cover`` here).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..migrations.errors import FailedMigrationError
from ..migrations.model import AppliedMigration, Migration, MigrationKind

if TYPE_CHECKING:
    from neo4j import Driver

_MARKER_CONSTRAINT = (
    "CREATE CONSTRAINT schema_migration_version IF NOT EXISTS "
    "FOR (m:SchemaMigration) REQUIRE m.version IS UNIQUE"
)
_SELECT_APPLIED = (
    "MATCH (m:SchemaMigration) "
    "RETURN m.version AS version, m.name AS name, m.checksum AS checksum, "
    "m.applied_at AS applied_at, m.success AS success, m.dirty AS dirty "
    "ORDER BY m.version"
)
_MERGE_SUCCESS = (
    "MERGE (m:SchemaMigration {version: $version}) "
    "SET m.name = $name, m.checksum = $checksum, m.applied_at = $applied_at, "
    "m.success = true, m.dirty = false"
)
_MERGE_DIRTY = (
    "MERGE (m:SchemaMigration {version: $version}) "
    "SET m.name = $name, m.checksum = $checksum, m.applied_at = $applied_at, "
    "m.success = false, m.dirty = true"
)


def split_cypher_statements(text: str) -> tuple[str, ...]:
    """Split a Cypher migration into individual statements on ``;``.

    Comments are stripped *before* splitting on ``;``, not after: cutting each
    line at its first ``//`` removes both full-line and inline trailing
    comments, and — critically — removes a comment in its entirety before any
    ``;`` inside that comment's prose can be mistaken for a statement
    separator. Splitting first and filtering ``//``-prefixed lines per
    resulting chunk (the previous approach) breaks exactly on that case: a
    comment containing a semicolon gets cut in half, and the tail half no
    longer starts with ``//`` so it leaks into the next statement.
    Blank/whitespace-only statements are dropped. Pure — no driver
    involvement — so migration authoring is unit-testable.

    Known limitation: this is a line-oriented scan, not a Cypher-aware
    tokenizer. A string literal containing ``//`` would be truncated as if it
    were a comment. None of the packaged migrations do this; a future
    migration that needs a literal ``//`` in a string should avoid this
    helper or the helper should be upgraded to a proper tokenizer first.
    """
    code_only = "\n".join(line.partition("//")[0] for line in text.splitlines())
    statements: list[str] = []
    for chunk in code_only.split(";"):
        body = chunk.strip()
        if body:
            statements.append(body)
    return tuple(statements)


class Neo4jMigrationExecutor:
    """A :class:`MigrationExecutor` backed by a Neo4j driver."""

    def __init__(self, driver: Driver, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @property
    def kind(self) -> MigrationKind:
        return MigrationKind.NEO4J

    def ensure_history(self) -> None:  # pragma: no cover - requires a live Neo4j
        with self._driver.session(database=self._database) as session:
            session.run(_MARKER_CONSTRAINT)

    def fetch_applied(self) -> tuple[AppliedMigration, ...]:  # pragma: no cover - live DB
        with self._driver.session(database=self._database) as session:
            records = list(session.run(_SELECT_APPLIED))
        return tuple(
            AppliedMigration(
                version=rec["version"],
                name=rec["name"],
                kind=MigrationKind.NEO4J,
                checksum=rec["checksum"],
                applied_at=_as_datetime(rec["applied_at"]),
                success=bool(rec["success"]),
                dirty=bool(rec["dirty"]),
            )
            for rec in records
        )

    def apply(self, migration: Migration) -> AppliedMigration:  # pragma: no cover - live DB
        applied_at = datetime.now(timezone.utc)
        params = {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
            "applied_at": applied_at,
        }
        try:
            with self._driver.session(database=self._database) as session:
                for statement in split_cypher_statements(migration.statements):
                    session.run(statement)
                session.run(_MERGE_SUCCESS, params)
        except Exception as exc:
            self._mark_dirty(params)
            raise FailedMigrationError(
                f"Neo4j migration M{migration.version} ({migration.name}) failed: {exc}"
            ) from exc
        return AppliedMigration(
            version=migration.version,
            name=migration.name,
            kind=MigrationKind.NEO4J,
            checksum=migration.checksum,
            applied_at=applied_at,
            success=True,
            dirty=False,
        )

    def _mark_dirty(self, params: dict[str, object]) -> None:  # pragma: no cover - live DB
        try:
            with self._driver.session(database=self._database) as session:
                session.run(_MERGE_DIRTY, params)
        except Exception:
            # Best-effort; the migration failure is already being raised.
            pass


def _as_datetime(value: object) -> datetime:  # pragma: no cover - live DB value conversion
    """Coerce a Neo4j temporal value to a native ``datetime``."""
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        native = to_native()
        if isinstance(native, datetime):
            return native
    if isinstance(value, datetime):
        return value
    raise TypeError(f"unexpected applied_at value: {value!r}")
