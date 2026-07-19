"""Immutable migration metadata models (Phase 2, Sprint 2).

These frozen value types describe migrations discovered on disk and migrations
already applied (recorded in the history table / marker). They carry no I/O and
no backend specifics — the database-agnostic runner and the concrete backend
executors both speak in terms of these models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# 64-char lowercase hex SHA-256 digest.
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class MigrationKind(str, Enum):
    """Which datastore a migration targets."""

    POSTGRES = "postgres"
    NEO4J = "neo4j"


class Migration(BaseModel):
    """A migration discovered on disk: its ordering ``version``, human ``name``,
    target ``kind``, raw ``statements`` text, and content ``checksum``.

    ``version`` is the forward-only ordering key (strictly increasing, unique per
    kind). ``checksum`` is the SHA-256 of the file's bytes and is immutable once
    applied (the runner rejects any change).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(min_length=1)
    kind: MigrationKind
    statements: str
    checksum: str = Field(pattern=_SHA256_PATTERN)


class AppliedMigration(BaseModel):
    """A migration recorded as applied (from the history table / Neo4j marker).

    ``success`` False marks a *failed* application; ``dirty`` True marks an
    application that started but did not cleanly finish (e.g. the process died
    mid-migration). Either state halts the runner until resolved.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(min_length=1)
    kind: MigrationKind
    checksum: str = Field(pattern=_SHA256_PATTERN)
    applied_at: datetime
    success: bool = True
    dirty: bool = False


class MigrationStatus(BaseModel):
    """A point-in-time report of migration state for one datastore."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: MigrationKind
    applied: tuple[AppliedMigration, ...] = ()
    pending: tuple[Migration, ...] = ()

    @property
    def is_dirty(self) -> bool:
        """True if any applied migration is in a dirty or failed state."""
        return any(a.dirty or not a.success for a in self.applied)

    @property
    def is_up_to_date(self) -> bool:
        """True if there are no pending migrations and none are dirty/failed."""
        return not self.pending and not self.is_dirty
