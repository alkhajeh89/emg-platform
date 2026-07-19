"""Migration metadata models (Sprint 2)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from _migr_helpers import make_applied, make_migration
from emg_persistence.migrations import AppliedMigration, MigrationKind, MigrationStatus
from pydantic import ValidationError

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HASH = "a" * 64


def test_migration_rejects_bad_version_and_checksum() -> None:
    with pytest.raises(ValidationError):
        make_migration(0)  # version must be >= 1
    with pytest.raises(ValidationError):
        make_migration(1, checksum="not-a-hash")


def test_migration_is_frozen() -> None:
    m = make_migration(1)
    with pytest.raises(ValidationError):
        m.version = 2  # type: ignore[misc]


def test_applied_migration_defaults() -> None:
    a = AppliedMigration(
        version=1, name="baseline", kind=MigrationKind.POSTGRES, checksum=_HASH, applied_at=_T0
    )
    assert a.success is True and a.dirty is False


def test_status_flags() -> None:
    clean = MigrationStatus(
        kind=MigrationKind.POSTGRES,
        applied=(make_applied(1, _HASH),),
        pending=(),
    )
    assert clean.is_dirty is False
    assert clean.is_up_to_date is True

    with_pending = MigrationStatus(
        kind=MigrationKind.POSTGRES, applied=(), pending=(make_migration(1),)
    )
    assert with_pending.is_up_to_date is False

    dirty = MigrationStatus(
        kind=MigrationKind.POSTGRES,
        applied=(make_applied(1, _HASH, dirty=True),),
    )
    assert dirty.is_dirty is True
    assert dirty.is_up_to_date is False

    failed = MigrationStatus(
        kind=MigrationKind.POSTGRES,
        applied=(make_applied(1, _HASH, success=False),),
    )
    assert failed.is_dirty is True
