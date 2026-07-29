"""Read-only mutation authorization preflight contracts (ADR-027 Revision 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from emg_common_types import Classification
from emg_memory_graph import MemoryGraph
from emg_platform_core import TenantId

from .commands import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    MergeEntitiesCommand,
    MutationCommand,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
)
from .errors import MutationResourceMetadataError


@dataclass(frozen=True, slots=True)
class ResourceMetadata:
    """Minimum current-state metadata required by ADR-027 authorization."""

    resource_type: str
    resource_id: str
    classification: Classification
    owner: str | None
    source_id: str | None = None
    target_id: str | None = None


@runtime_checkable
class IResourceMetadataReader(Protocol):
    """Application-owned, read-only resource metadata interface."""

    def read_entity(self, tenant: TenantId, entity_id: str) -> ResourceMetadata | None:
        """Read current entity metadata without opening a write transaction."""
        ...

    def read_relationship(self, tenant: TenantId, relationship_id: str) -> ResourceMetadata | None:
        """Read current relationship metadata without opening a write transaction."""
        ...


@dataclass(frozen=True, slots=True)
class MutationAuthorizationContext:
    """Current and proposed classifications supplied to the existing PEP."""

    current_resources: tuple[ResourceMetadata, ...]
    proposed_classifications: tuple[Classification, ...]


@runtime_checkable
class MutationAuthorizationEvaluator(Protocol):
    """Authorization adapter invoked after metadata collection."""

    def authorize(
        self,
        command: MutationCommand,
        context: MutationAuthorizationContext,
    ) -> None:
        """Raise the existing permission error on deny; otherwise return."""
        ...


class MutationAuthorizationPreflight:
    """Collect metadata before delegating the decision to the PEP adapter."""

    def __init__(
        self,
        metadata_reader: IResourceMetadataReader,
        evaluator: MutationAuthorizationEvaluator,
    ) -> None:
        self._metadata_reader = metadata_reader
        self._evaluator = evaluator

    def __call__(self, command: MutationCommand) -> MutationAuthorizationContext:
        current, proposed = self._context_for(command)
        context = MutationAuthorizationContext(
            current_resources=current,
            proposed_classifications=proposed,
        )
        self._evaluator.authorize(command, context)
        return context

    def revalidate(
        self,
        command: MutationCommand,
        expected: MutationAuthorizationContext,
        graph: MemoryGraph,
    ) -> None:
        """Authorize the exact immutable graph snapshot about to be mutated."""

        current, proposed = self._context_for_graph(command, graph)
        actual = MutationAuthorizationContext(
            current_resources=current,
            proposed_classifications=proposed,
        )
        if actual != expected:
            from .errors import MutationAuthorizationConflictError

            raise MutationAuthorizationConflictError(
                "authorization-relevant resource metadata changed during mutation"
            )
        self._evaluator.authorize(command, actual)

    def authorize_current(self, command: MutationCommand) -> None:
        """Authorize a replay against current resource metadata."""

        current, proposed = self._context_for(command)
        self._evaluator.authorize(
            command,
            MutationAuthorizationContext(
                current_resources=current,
                proposed_classifications=proposed,
            ),
        )

    def _require_entity(self, tenant: TenantId, entity_id: str) -> ResourceMetadata:
        metadata = self._metadata_reader.read_entity(tenant, entity_id)
        if metadata is None:
            raise MutationResourceMetadataError(
                f"entity {entity_id!r} is unavailable for authorization preflight"
            )
        return metadata

    def _require_relationship(self, tenant: TenantId, relationship_id: str) -> ResourceMetadata:
        metadata = self._metadata_reader.read_relationship(tenant, relationship_id)
        if metadata is None:
            raise MutationResourceMetadataError(
                f"relationship {relationship_id!r} is unavailable for authorization preflight"
            )
        return metadata

    def _relationship_context(
        self, tenant: TenantId, relationship_id: str
    ) -> tuple[ResourceMetadata, ...]:
        relationship = self._require_relationship(tenant, relationship_id)
        if relationship.source_id is None or relationship.target_id is None:
            raise MutationResourceMetadataError(
                f"relationship {relationship_id!r} has incomplete endpoint metadata"
            )
        return (
            relationship,
            self._require_entity(tenant, relationship.source_id),
            self._require_entity(tenant, relationship.target_id),
        )

    def _context_for(
        self, command: MutationCommand
    ) -> tuple[tuple[ResourceMetadata, ...], tuple[Classification, ...]]:
        if isinstance(command, CreateEntityCommand):
            return (), (command.entity.classification,)
        if isinstance(command, ReplaceEntityCommand):
            return (
                (self._require_entity(command.tenant, command.replacement.node_id),),
                (command.replacement.classification,),
            )
        if isinstance(command, ReplaceRelationshipCommand):
            return (
                self._relationship_context(command.tenant, command.replacement.edge_id),
                (command.replacement.classification,),
            )
        if isinstance(command, CloseRelationshipCommand):
            return self._relationship_context(command.tenant, command.edge_id), ()
        if isinstance(command, MergeEntitiesCommand):
            identifiers = (command.survivor_id, *command.source_ids)
            return (
                tuple(self._require_entity(command.tenant, entity_id) for entity_id in identifiers),
                (),
            )
        raise MutationResourceMetadataError(
            f"unsupported mutation command type: {type(command).__name__}"
        )

    @staticmethod
    def _entity_from_graph(graph: MemoryGraph, entity_id: str) -> ResourceMetadata:
        node = graph.node(entity_id)
        if node is None:
            raise MutationResourceMetadataError(
                f"entity {entity_id!r} is unavailable for transactional authorization"
            )
        return ResourceMetadata(
            resource_type="knowledge-graph.entity",
            resource_id=node.node_id,
            classification=node.classification,
            owner=node.owner or None,
        )

    @staticmethod
    def _relationship_from_graph(graph: MemoryGraph, relationship_id: str) -> ResourceMetadata:
        edge = graph.edge(relationship_id)
        if edge is None:
            raise MutationResourceMetadataError(
                f"relationship {relationship_id!r} is unavailable for transactional authorization"
            )
        return ResourceMetadata(
            resource_type="knowledge-graph.relationship",
            resource_id=edge.edge_id,
            classification=edge.classification,
            owner=None,
            source_id=edge.source_id,
            target_id=edge.target_id,
        )

    def _relationship_context_from_graph(
        self, graph: MemoryGraph, relationship_id: str
    ) -> tuple[ResourceMetadata, ...]:
        relationship = self._relationship_from_graph(graph, relationship_id)
        assert relationship.source_id is not None
        assert relationship.target_id is not None
        return (
            relationship,
            self._entity_from_graph(graph, relationship.source_id),
            self._entity_from_graph(graph, relationship.target_id),
        )

    def _context_for_graph(
        self, command: MutationCommand, graph: MemoryGraph
    ) -> tuple[tuple[ResourceMetadata, ...], tuple[Classification, ...]]:
        if isinstance(command, CreateEntityCommand):
            return (), (command.entity.classification,)
        if isinstance(command, ReplaceEntityCommand):
            return (
                (self._entity_from_graph(graph, command.replacement.node_id),),
                (command.replacement.classification,),
            )
        if isinstance(command, ReplaceRelationshipCommand):
            return (
                self._relationship_context_from_graph(graph, command.replacement.edge_id),
                (command.replacement.classification,),
            )
        if isinstance(command, CloseRelationshipCommand):
            return self._relationship_context_from_graph(graph, command.edge_id), ()
        if isinstance(command, MergeEntitiesCommand):
            identifiers = (command.survivor_id, *command.source_ids)
            return (
                tuple(self._entity_from_graph(graph, entity_id) for entity_id in identifiers),
                (),
            )
        raise MutationResourceMetadataError(
            f"unsupported mutation command type: {type(command).__name__}"
        )
