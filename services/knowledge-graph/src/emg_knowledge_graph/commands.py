"""Immutable command/query contracts for knowledge-graph application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from emg_ontology import Entity, Relationship
from emg_platform_core import (
    DEFAULT_REVISION_LIST_LIMIT,
    MAX_REVISION_LIST_LIMIT,
    PrincipalRef,
    TenantId,
)

from .errors import InvalidHistoryQueryError, InvalidRevisionCommandError


@dataclass(frozen=True, slots=True)
class BuildRevisionCommand:
    """Validated ontology input for one tenant-scoped revision build."""

    tenant: TenantId
    principal: PrincipalRef
    entities: tuple[Entity, ...]
    relationships: tuple[Relationship, ...]
    as_of: datetime

    def validate(self) -> None:
        """Validate application-command invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidRevisionCommandError("tenant must be a TenantId")
        if not isinstance(self.principal, PrincipalRef):
            raise InvalidRevisionCommandError("principal must be a PrincipalRef")
        if not isinstance(self.entities, tuple) or not all(
            isinstance(item, Entity) for item in self.entities
        ):
            raise InvalidRevisionCommandError("entities must be a tuple of ontology Entity objects")
        if not isinstance(self.relationships, tuple) or not all(
            isinstance(item, Relationship) for item in self.relationships
        ):
            raise InvalidRevisionCommandError(
                "relationships must be a tuple of ontology Relationship objects"
            )
        if not self.entities and not self.relationships:
            raise InvalidRevisionCommandError(
                "revision command must contain at least one entity or relationship"
            )
        if not isinstance(self.as_of, datetime):
            raise InvalidRevisionCommandError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise InvalidRevisionCommandError("as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ListRevisionsQuery:
    """A tenant's revision history, newest first, bounded and cursor-paged
    (ADR-023 §12, §13). Read-only: deliberately carries no ``PrincipalRef``."""

    tenant: TenantId
    limit: int = DEFAULT_REVISION_LIST_LIMIT
    before_revision_number: int | None = None

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidHistoryQueryError("tenant must be a TenantId")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise InvalidHistoryQueryError("limit must be an int")
        if not (1 <= self.limit <= MAX_REVISION_LIST_LIMIT):
            raise InvalidHistoryQueryError(
                f"limit must be in [1, {MAX_REVISION_LIST_LIMIT}]: {self.limit!r}"
            )
        if self.before_revision_number is not None:
            if isinstance(self.before_revision_number, bool) or not isinstance(
                self.before_revision_number, int
            ):
                raise InvalidHistoryQueryError("before_revision_number must be an int")
            if self.before_revision_number < 1:
                raise InvalidHistoryQueryError("before_revision_number must be >= 1")


@dataclass(frozen=True, slots=True)
class GetRevisionQuery:
    """One tenant's historical revision, identified by number (ADR-023 §12).
    Read-only: deliberately carries no ``PrincipalRef``."""

    tenant: TenantId
    revision_number: int

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidHistoryQueryError("tenant must be a TenantId")
        if isinstance(self.revision_number, bool) or not isinstance(self.revision_number, int):
            raise InvalidHistoryQueryError("revision_number must be an int")
        if self.revision_number < 1:
            raise InvalidHistoryQueryError("revision_number must be >= 1")


@dataclass(frozen=True, slots=True)
class CompareRevisionsQuery:
    """A diff between two of a tenant's historical revisions (ADR-023 §12,
    §14). Self-comparison (``from == to``) and reverse comparison
    (``from > to``) are both valid and are not rejected. Read-only:
    deliberately carries no ``PrincipalRef``."""

    tenant: TenantId
    from_revision_number: int
    to_revision_number: int

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidHistoryQueryError("tenant must be a TenantId")
        for name, value in (
            ("from_revision_number", self.from_revision_number),
            ("to_revision_number", self.to_revision_number),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidHistoryQueryError(f"{name} must be an int")
            if value < 1:
                raise InvalidHistoryQueryError(f"{name} must be >= 1")


@dataclass(frozen=True, slots=True)
class RestoreRevisionCommand:
    """Restore a tenant's historical revision by committing it as the next
    immutable revision (ADR-023 §12, §15). Carries no ``as_of`` — no concrete
    domain meaning was identified for a caller-supplied restore timestamp; the
    commit's own ``committed_at`` is server-clock, not caller-supplied."""

    tenant: TenantId
    principal: PrincipalRef
    source_revision_number: int

    def validate(self) -> None:
        """Validate application-command invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidRevisionCommandError("tenant must be a TenantId")
        if not isinstance(self.principal, PrincipalRef):
            raise InvalidRevisionCommandError("principal must be a PrincipalRef")
        if isinstance(self.source_revision_number, bool) or not isinstance(
            self.source_revision_number, int
        ):
            raise InvalidRevisionCommandError("source_revision_number must be an int")
        if self.source_revision_number < 1:
            raise InvalidRevisionCommandError("source_revision_number must be >= 1")
