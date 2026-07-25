"""Application-service boundary for Module 7 orchestration."""

from __future__ import annotations

from emg_memory_graph import MemoryGraphBuilder, MemoryGraphError
from emg_platform_core.ports import GraphStore

from .commands import BuildRevisionCommand
from .errors import InvalidRevisionCommandError, RevisionBuildError
from .results import BuildRevisionResult


class KnowledgeGraphApplication:
    """Application/orchestration layer over the platform GraphStore boundary."""

    def __init__(
        self,
        graph_store: GraphStore,
        *,
        builder: MemoryGraphBuilder | None = None,
    ) -> None:
        self._graph_store = graph_store
        self._builder = builder or MemoryGraphBuilder()

    def build_revision(self, command: BuildRevisionCommand) -> BuildRevisionResult:
        """Build and atomically commit the next immutable tenant snapshot."""
        if not isinstance(command, BuildRevisionCommand):
            raise InvalidRevisionCommandError("command must be a BuildRevisionCommand")
        command.validate()

        with self._graph_store.transaction(command.tenant, command.principal) as transaction:
            current = transaction.read()
            try:
                build = self._builder.from_ontology(
                    entities=command.entities,
                    relationships=command.relationships,
                    as_of=command.as_of,
                    base=current,
                )
            except MemoryGraphError as exc:
                raise RevisionBuildError(
                    f"failed to build revision for tenant {command.tenant.value!r}: {exc}"
                ) from exc
            transaction.stage(build.graph)

        receipt = transaction.receipt
        return BuildRevisionResult(
            tenant=receipt.tenant,
            principal=receipt.principal,
            content_hash=receipt.content_hash,
            node_count=receipt.node_count,
            edge_count=receipt.edge_count,
            nodes_created=build.nodes_created,
            edges_created=build.edges_created,
            node_inputs_merged=build.node_inputs_merged,
            edge_inputs_merged=build.edge_inputs_merged,
        )
