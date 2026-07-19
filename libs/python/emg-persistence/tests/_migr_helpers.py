"""In-memory MigrationExecutor + constructors for migration-framework tests.

The fake executor lets the database-agnostic runner be exercised exhaustively
(ordering, checksum immutability, dirty/failed detection, forward-only apply,
history, idempotent re-runs) without any real datastore.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from emg_persistence.migrations import (
    AppliedMigration,
    Migration,
    MigrationKind,
    sha256_hex,
)
from emg_persistence.migrations.errors import FailedMigrationError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_migration(
    version: int,
    name: str = "m",
    *,
    kind: MigrationKind = MigrationKind.POSTGRES,
    statements: str | None = None,
    checksum: str | None = None,
) -> Migration:
    """Build a Migration; checksum defaults to the hash of ``statements``."""
    body = statements if statements is not None else f"-- migration {version}"
    digest = checksum if checksum is not None else sha256_hex(body.encode("utf-8"))
    return Migration(version=version, name=name, kind=kind, statements=body, checksum=digest)


def make_applied(
    version: int,
    checksum: str,
    *,
    name: str = "m",
    kind: MigrationKind = MigrationKind.POSTGRES,
    success: bool = True,
    dirty: bool = False,
) -> AppliedMigration:
    return AppliedMigration(
        version=version,
        name=name,
        kind=kind,
        checksum=checksum,
        applied_at=_now(),
        success=success,
        dirty=dirty,
    )


class FakeMigrationExecutor:
    """A deterministic in-memory :class:`MigrationExecutor` for unit tests."""

    def __init__(
        self,
        kind: MigrationKind = MigrationKind.POSTGRES,
        *,
        applied: Iterable[AppliedMigration] = (),
        fail_versions: Iterable[int] = (),
    ) -> None:
        self._kind = kind
        self._applied: list[AppliedMigration] = list(applied)
        self._fail_versions = frozenset(fail_versions)
        self.ensure_history_calls = 0

    @property
    def kind(self) -> MigrationKind:
        return self._kind

    def ensure_history(self) -> None:
        self.ensure_history_calls += 1

    def fetch_applied(self) -> tuple[AppliedMigration, ...]:
        return tuple(self._applied)

    def apply(self, migration: Migration) -> AppliedMigration:
        if migration.version in self._fail_versions:
            # Model a failed application: a dirty/failed marker is recorded (as a
            # real transactional backend would after rollback) and the error is
            # raised, so a subsequent run detects the dirty state and halts.
            self._applied.append(
                make_applied(
                    migration.version,
                    migration.checksum,
                    name=migration.name,
                    kind=self._kind,
                    success=False,
                    dirty=True,
                )
            )
            raise FailedMigrationError(f"simulated failure applying version {migration.version}")
        record = make_applied(
            migration.version, migration.checksum, name=migration.name, kind=self._kind
        )
        self._applied.append(record)
        return record
