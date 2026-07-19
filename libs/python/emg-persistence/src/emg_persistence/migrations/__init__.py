"""Migration framework (Phase 2, Sprint 2).

A database-agnostic runner (``MigrationRunner``) plus discovery/checksum helpers
and the ``MigrationExecutor`` contract. Concrete PostgreSQL/Neo4j executors live
in ``emg_persistence.postgres`` / ``emg_persistence.neo4j``.
"""

from __future__ import annotations

from .discovery import discover_migrations, parse_migration_filename, sha256_hex
from .errors import (
    ChecksumMismatchError,
    DirtyMigrationError,
    FailedMigrationError,
    MigrationDiscoveryError,
    MigrationError,
)
from .executor import MigrationExecutor
from .model import AppliedMigration, Migration, MigrationKind, MigrationStatus
from .runner import MigrationRunner

__all__ = [
    "AppliedMigration",
    "ChecksumMismatchError",
    "DirtyMigrationError",
    "FailedMigrationError",
    "Migration",
    "MigrationDiscoveryError",
    "MigrationError",
    "MigrationExecutor",
    "MigrationKind",
    "MigrationRunner",
    "MigrationStatus",
    "discover_migrations",
    "parse_migration_filename",
    "sha256_hex",
]
