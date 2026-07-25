"""Immutable command contracts for knowledge-graph application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from emg_ontology import Entity, Relationship
from emg_platform_core import PrincipalRef, TenantId

from .errors import InvalidRevisionCommandError


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
