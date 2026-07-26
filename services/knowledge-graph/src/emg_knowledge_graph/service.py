"""Application-service boundary for Module 7 orchestration."""

from __future__ import annotations

from emg_memory_graph import MemoryGraphBuilder, MemoryGraphError, diff_graphs
from emg_platform_core import RevisionNotFoundError as _PlatformRevisionNotFoundError
from emg_platform_core.ports import GraphRevisionReader, GraphStore, RevisionMetadata

from .commands import (
    BuildRevisionCommand,
    CompareRevisionsQuery,
    GetRevisionQuery,
    ListRevisionsQuery,
    RestoreRevisionCommand,
)
from .errors import (
    InvalidHistoryQueryError,
    InvalidRevisionCommandError,
    RevisionBuildError,
    RevisionNotFoundError,
    RevisionRestoreError,
    UnsupportedHistoryCapabilityError,
)
from .results import (
    BuildRevisionResult,
    RestoreRevisionResult,
    RevisionDetails,
    RevisionDiff,
    RevisionSummary,
)


def _summary_from_metadata(metadata: RevisionMetadata) -> RevisionSummary:
    return RevisionSummary(
        tenant=metadata.tenant,
        revision_number=metadata.revision_number,
        content_hash=metadata.content_hash,
        parent_hash=metadata.parent_hash,
        principal=metadata.principal,
        node_count=metadata.node_count,
        edge_count=metadata.edge_count,
        created_at=metadata.created_at,
    )


class KnowledgeGraphApplication:
    """Application/orchestration layer over the platform GraphStore boundary.

    ``revision_reader`` (ADR-023) is a separate, optional, read-only
    dependency — a caller may supply the same concrete adapter object for
    both ``graph_store`` and ``revision_reader`` (both existing adapters
    implement both Protocols structurally), but the two port types are never
    collapsed into one parameter.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        *,
        builder: MemoryGraphBuilder | None = None,
        revision_reader: GraphRevisionReader | None = None,
    ) -> None:
        self._graph_store = graph_store
        self._builder = builder or MemoryGraphBuilder()
        self._revision_reader = revision_reader

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

    def list_revisions(self, query: ListRevisionsQuery) -> tuple[RevisionSummary, ...]:
        """List a tenant's revision history, newest first. Never loads a graph."""
        if not isinstance(query, ListRevisionsQuery):
            raise InvalidHistoryQueryError("query must be a ListRevisionsQuery")
        query.validate()
        self._require_revision_reader()

        records = self._revision_reader.list_revisions(  # type: ignore[union-attr]
            query.tenant, limit=query.limit, before_revision_number=query.before_revision_number
        )
        return tuple(_summary_from_metadata(record) for record in records)

    def get_revision(self, query: GetRevisionQuery) -> RevisionDetails:
        """Read one historical revision's metadata and exact graph."""
        if not isinstance(query, GetRevisionQuery):
            raise InvalidHistoryQueryError("query must be a GetRevisionQuery")
        query.validate()
        self._require_revision_reader()

        try:
            historical = self._revision_reader.read_revision(  # type: ignore[union-attr]
                query.tenant, query.revision_number
            )
        except _PlatformRevisionNotFoundError as exc:
            raise RevisionNotFoundError(
                f"no revision {query.revision_number} for tenant {query.tenant.value!r}"
            ) from exc
        return RevisionDetails(
            summary=_summary_from_metadata(historical.metadata), graph=historical.graph
        )

    def compare_revisions(self, query: CompareRevisionsQuery) -> RevisionDiff:
        """Diff two of a tenant's revisions using the existing diff_graphs.

        Self-comparison (``from == to``) and reverse comparison
        (``from > to``) are both valid and produce the diff ``diff_graphs``
        naturally produces for the given argument order.
        """
        if not isinstance(query, CompareRevisionsQuery):
            raise InvalidHistoryQueryError("query must be a CompareRevisionsQuery")
        query.validate()
        self._require_revision_reader()

        try:
            from_revision = self._revision_reader.read_revision(  # type: ignore[union-attr]
                query.tenant, query.from_revision_number
            )
            to_revision = self._revision_reader.read_revision(  # type: ignore[union-attr]
                query.tenant, query.to_revision_number
            )
        except _PlatformRevisionNotFoundError as exc:
            raise RevisionNotFoundError(str(exc)) from exc

        diff = diff_graphs(from_revision.graph, to_revision.graph)
        return RevisionDiff(
            tenant=query.tenant,
            from_revision_number=query.from_revision_number,
            to_revision_number=query.to_revision_number,
            diff=diff,
        )

    def restore_revision(self, command: RestoreRevisionCommand) -> RestoreRevisionResult:
        """Restore a historical revision by committing it as the next
        immutable revision, attributed to the restoring principal.

        Does not call ``MemoryGraphBuilder.from_ontology`` — the historical
        graph is staged directly, preserving its internal temporal fields
        exactly. Restoring content identical to the current head is a valid
        no-op (ADR-023 §16): no new revision row, no new outbox event, and the
        result identifies the existing head with ``revision_created=False``.
        """
        if not isinstance(command, RestoreRevisionCommand):
            raise InvalidRevisionCommandError("command must be a RestoreRevisionCommand")
        command.validate()
        self._require_revision_reader()

        try:
            source = self._revision_reader.read_revision(  # type: ignore[union-attr]
                command.tenant, command.source_revision_number
            )
        except _PlatformRevisionNotFoundError as exc:
            raise RevisionNotFoundError(
                f"no revision {command.source_revision_number} "
                f"for tenant {command.tenant.value!r}"
            ) from exc

        with self._graph_store.transaction(command.tenant, command.principal) as transaction:
            try:
                transaction.stage(source.graph)
            except MemoryGraphError as exc:  # pragma: no cover - defensive
                raise RevisionRestoreError(
                    f"failed to stage revision {command.source_revision_number} "
                    f"for tenant {command.tenant.value!r}: {exc}"
                ) from exc

        receipt = transaction.receipt
        return RestoreRevisionResult(
            tenant=receipt.tenant,
            principal=receipt.principal,
            source_revision_number=command.source_revision_number,
            revision_number=receipt.revision_number,
            content_hash=receipt.content_hash,
            node_count=receipt.node_count,
            edge_count=receipt.edge_count,
            committed_at=receipt.committed_at,
            revision_created=receipt.revision_created,
        )

    def _require_revision_reader(self) -> None:
        if self._revision_reader is None:
            raise UnsupportedHistoryCapabilityError(
                "KnowledgeGraphApplication was constructed without a GraphRevisionReader"
            )
