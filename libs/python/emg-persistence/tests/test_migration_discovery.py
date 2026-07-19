"""Migration discovery, checksums, ordering, filename parsing (Sprint 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from emg_persistence.migrations import (
    MigrationDiscoveryError,
    MigrationKind,
    discover_migrations,
    parse_migration_filename,
    sha256_hex,
)


def _write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


def test_sha256_hex_is_stable() -> None:
    assert sha256_hex(b"abc") == sha256_hex(b"abc")
    assert len(sha256_hex(b"x")) == 64


def test_parse_filename() -> None:
    assert parse_migration_filename("V001__baseline.sql", MigrationKind.POSTGRES) == (1, "baseline")
    assert parse_migration_filename("M12__x.cypher", MigrationKind.NEO4J) == (12, "x")
    assert parse_migration_filename("README.md", MigrationKind.POSTGRES) is None


def test_discovery_orders_by_version_and_hashes(tmp_path: Path) -> None:
    _write(tmp_path, "V002__second.sql", "SELECT 2;")
    _write(tmp_path, "V001__first.sql", "SELECT 1;")
    _write(tmp_path, "README.md", "ignored")  # non-.sql ignored
    migrations = discover_migrations(tmp_path, MigrationKind.POSTGRES)
    assert [m.version for m in migrations] == [1, 2]
    assert migrations[0].name == "first"
    assert migrations[0].checksum == sha256_hex(b"SELECT 1;")


def test_discovery_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationDiscoveryError):
        discover_migrations(tmp_path / "nope", MigrationKind.POSTGRES)


def test_discovery_malformed_filename(tmp_path: Path) -> None:
    _write(tmp_path, "V1_missing_double_underscore.sql", "x")
    with pytest.raises(MigrationDiscoveryError):
        discover_migrations(tmp_path, MigrationKind.POSTGRES)


def test_discovery_duplicate_version(tmp_path: Path) -> None:
    _write(tmp_path, "V001__a.sql", "a")
    _write(tmp_path, "V001__b.sql", "b")
    with pytest.raises(MigrationDiscoveryError):
        discover_migrations(tmp_path, MigrationKind.POSTGRES)


def test_discovery_neo4j_extension(tmp_path: Path) -> None:
    _write(tmp_path, "M001__constraints.cypher", "CREATE CONSTRAINT x IF NOT EXISTS ...;")
    _write(tmp_path, "V001__baseline.sql", "SELECT 1;")  # wrong kind, ignored
    migrations = discover_migrations(tmp_path, MigrationKind.NEO4J)
    assert [m.version for m in migrations] == [1]
    assert migrations[0].kind is MigrationKind.NEO4J
