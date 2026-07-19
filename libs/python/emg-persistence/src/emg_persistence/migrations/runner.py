"""The database-agnostic migration runner (Phase 2, Sprint 2).

``MigrationRunner`` owns all migration *logic* — ordering validation, checksum
immutability, dirty/failed detection, forward-only application, and status
reporting — expressed purely against the :class:`MigrationExecutor` contract.
The concrete PostgreSQL/Neo4j executors provide the datastore I/O and the
transactional/idempotent guarantees; this class contains no SQL or Cypher.
"""

from __future__ import annotations

from collections.abc import Sequence

from .errors import (
    ChecksumMismatchError,
    DirtyMigrationError,
    FailedMigrationError,
    MigrationDiscoveryError,
)
from .executor import MigrationExecutor
from .model import AppliedMigration, Migration, MigrationStatus


def _validate_ordering(discovered: Sequence[Migration]) -> tuple[Migration, ...]:
    """Return ``discovered`` sorted by version, rejecting mixed kinds or
    duplicate versions."""
    kinds = {m.kind for m in discovered}
    if len(kinds) > 1:
        raise MigrationDiscoveryError(
            f"migrations span multiple kinds: {sorted(k.value for k in kinds)}"
        )
    seen: set[int] = set()
    for m in discovered:
        if m.version in seen:
            raise MigrationDiscoveryError(f"duplicate migration version {m.version}")
        seen.add(m.version)
    return tuple(sorted(discovered, key=lambda m: m.version))


class MigrationRunner:
    """Applies pending migrations through a :class:`MigrationExecutor`, enforcing
    checksum immutability, dirty/failed halting, and forward-only ordering."""

    def __init__(self, executor: MigrationExecutor) -> None:
        self._executor = executor

    # --- read-only status ----------------------------------------------------
    def status(self, discovered: Sequence[Migration]) -> MigrationStatus:
        """Report applied vs pending migrations (non-raising for dirty/failed —
        the dirty/failed condition is surfaced via ``MigrationStatus``)."""
        ordered = _validate_ordering(discovered)
        self._executor.ensure_history()
        applied = self._executor.fetch_applied()
        applied_versions = {a.version for a in applied}
        pending = tuple(m for m in ordered if m.version not in applied_versions)
        return MigrationStatus(kind=self._executor.kind, applied=applied, pending=pending)

    # --- apply ---------------------------------------------------------------
    def run(self, discovered: Sequence[Migration]) -> tuple[AppliedMigration, ...]:
        """Verify integrity then apply every pending migration in order.

        Returns the migrations applied by *this* invocation (empty when already
        up to date — repeated runs are idempotent at the framework level).

        Raises:
            DirtyMigrationError: a prior migration is in a dirty state.
            FailedMigrationError: a prior migration is recorded failed, or an
                application raises.
            ChecksumMismatchError: an applied migration changed on disk, or is
                missing from disk.
            MigrationDiscoveryError: malformed/duplicate/forward-only violation.
        """
        ordered = _validate_ordering(discovered)
        self._executor.ensure_history()
        applied = self._executor.fetch_applied()

        self._halt_if_dirty_or_failed(applied)
        self._verify_checksums(ordered, applied)

        applied_versions = {a.version for a in applied}
        pending = tuple(m for m in ordered if m.version not in applied_versions)
        self._check_forward_only(pending, applied)

        newly: list[AppliedMigration] = []
        for migration in pending:
            newly.append(self._executor.apply(migration))
        return tuple(newly)

    # --- verification helpers (pure) -----------------------------------------
    @staticmethod
    def _halt_if_dirty_or_failed(applied: Sequence[AppliedMigration]) -> None:
        dirty = [a for a in applied if a.dirty]
        if dirty:
            versions = ", ".join(str(a.version) for a in dirty)
            raise DirtyMigrationError(
                f"dirty migration(s) detected (version {versions}); "
                "resolve the partial state before running migrations"
            )
        failed = [a for a in applied if not a.success]
        if failed:
            versions = ", ".join(str(a.version) for a in failed)
            raise FailedMigrationError(
                f"failed migration(s) recorded (version {versions}); "
                "resolve before running migrations"
            )

    @staticmethod
    def _verify_checksums(
        ordered: Sequence[Migration], applied: Sequence[AppliedMigration]
    ) -> None:
        by_version = {m.version: m for m in ordered}
        for record in applied:
            migration = by_version.get(record.version)
            if migration is None:
                raise ChecksumMismatchError(
                    f"applied migration version {record.version} ({record.name!r}) "
                    "is not present on disk; history integrity cannot be verified"
                )
            if migration.checksum != record.checksum:
                raise ChecksumMismatchError(
                    f"migration version {record.version} changed on disk after being applied "
                    f"(recorded {record.checksum[:12]}…, on disk {migration.checksum[:12]}…); "
                    "applied migrations are immutable"
                )

    @staticmethod
    def _check_forward_only(
        pending: Sequence[Migration], applied: Sequence[AppliedMigration]
    ) -> None:
        if not applied or not pending:
            return
        max_applied = max(a.version for a in applied)
        backfilled = [m for m in pending if m.version <= max_applied]
        if backfilled:
            versions = ", ".join(str(m.version) for m in backfilled)
            raise MigrationDiscoveryError(
                f"forward-only violation: pending migration(s) {versions} are "
                f"not greater than the latest applied version {max_applied}"
            )
