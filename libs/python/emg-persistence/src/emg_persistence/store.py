"""PostgreSQL-authoritative direct graph persistence."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from emg_memory_graph import EMPTY_GRAPH, MemoryGraph, diff_graphs
from emg_platform_core import (
    GraphTransaction,
    PrincipalRef,
    TenantId,
    TransactionStateError,
    WriteReceipt,
)
from psycopg import Error as PsycopgError
from pydantic import ValidationError

from .errors import PersistenceConflictError, PersistenceError
from .neo4j.lazy import LazyNeo4jProjection
from .neo4j.projection import Neo4jGraphProjection
from .outbox import OutboxEvent, OutboxRepository
from .postgres.outbox_repository import PostgresOutboxRepository
from .postgres.revision_repository import PostgresRevisionRepository
from .postgres.transactions import TransactionProvider
from .revisions import Revision, RevisionHead, RevisionRepository

if TYPE_CHECKING:
    from psycopg import Connection

RevisionRepositoryFactory = Callable[["Connection[Any]"], RevisionRepository]
OutboxRepositoryFactory = Callable[["Connection[Any]"], OutboxRepository]
Clock = Callable[[], datetime]
ProjectionSource = Neo4jGraphProjection | LazyNeo4jProjection | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _TransactionState(Enum):
    OPEN = "open"
    COMMITTED = "committed"
    ABORTED = "aborted"


class _PersistentGraphTransaction:
    """Internal staged graph transaction; database ownership stays in the store."""

    def __init__(self, tenant: TenantId, principal: PrincipalRef, current: MemoryGraph) -> None:
        self._tenant = tenant
        self._principal = principal
        self._staged = current
        self._state = _TransactionState.OPEN
        self._receipt: WriteReceipt | None = None

    @property
    def tenant(self) -> TenantId:
        return self._tenant

    @property
    def principal(self) -> PrincipalRef:
        return self._principal

    @property
    def receipt(self) -> WriteReceipt:
        if self._state is not _TransactionState.COMMITTED or self._receipt is None:
            raise TransactionStateError(
                "receipt is only available after a successful commit "
                f"(transaction is {self._state.value})"
            )
        return self._receipt

    def read(self) -> MemoryGraph:
        self._require_open()
        return self._staged

    def stage(self, graph: MemoryGraph) -> None:
        self._require_open()
        self._staged = graph

    def commit(self, receipt: WriteReceipt) -> None:
        self._require_open()
        self._receipt = receipt
        self._state = _TransactionState.COMMITTED

    def abort(self) -> None:
        self._require_open()
        self._state = _TransactionState.ABORTED

    def _abort_if_open(self) -> None:
        if self._state is _TransactionState.OPEN:
            self._state = _TransactionState.ABORTED

    def _require_open(self) -> None:
        if self._state is not _TransactionState.OPEN:
            raise TransactionStateError(
                f"transaction is {self._state.value}; operation is no longer permitted"
            )


class PostgresNeo4jGraphStore:
    """Persistent store with PostgreSQL-authoritative direct read/write paths.

    The name reflects the complete Phase 2 adapter described by the architecture;
    Neo4j is not constructed or consulted by this implementation.
    """

    def __init__(
        self,
        transactions: TransactionProvider,
        *,
        repository_factory: RevisionRepositoryFactory = PostgresRevisionRepository,
        outbox_repository_factory: OutboxRepositoryFactory = PostgresOutboxRepository,
        projection: ProjectionSource = None,
        clock: Clock = _utcnow,
    ) -> None:
        self._transactions = transactions
        self._repository_factory = repository_factory
        self._outbox_repository_factory = outbox_repository_factory
        self._projection = projection
        self._clock = clock

    def read(self, tenant: TenantId) -> MemoryGraph:
        """Prefer Neo4j serving projection with read-repair; fall back to PostgreSQL."""
        pg_graph = self._read_authoritative(tenant)
        projection = self._resolve_projection()
        if projection is None:
            return pg_graph
        try:
            return self._read_via_projection(tenant, projection, pg_graph)
        except PersistenceError:
            raise
        except Exception:
            return pg_graph

    def write(
        self, tenant: TenantId, graph: MemoryGraph, *, principal: PrincipalRef
    ) -> WriteReceipt:
        """Durably persist ``graph`` and return proof only after commit."""
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                outbox = self._outbox_repository_factory(connection)
                self._persist(repository, outbox, tenant, graph, principal)
        except PersistenceConflictError:
            raise
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to write authoritative graph for tenant {tenant.value!r}"
            ) from exc
        return _receipt_for(tenant, graph, principal)

    def tenants(self) -> tuple[TenantId, ...]:
        """Return tenants with authoritative PostgreSQL heads."""
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                return repository.tenants()
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError("failed to list authoritative graph tenants") from exc

    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef) -> Iterator[GraphTransaction]:
        """Open one PostgreSQL transaction for an atomic staged graph update."""
        transaction: _PersistentGraphTransaction | None = None
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                outbox = self._outbox_repository_factory(connection)
                current = _read_from_repository(repository, tenant)
                transaction = _PersistentGraphTransaction(tenant, principal, current)
                try:
                    yield transaction
                    self._persist(repository, outbox, tenant, transaction.read(), principal)
                except BaseException:
                    transaction.abort()
                    raise
        except PersistenceConflictError:
            if transaction is not None:
                transaction._abort_if_open()
            raise
        except PersistenceError:
            if transaction is not None:
                transaction._abort_if_open()
            raise
        except PsycopgError as exc:
            if transaction is not None:
                transaction._abort_if_open()
            raise PersistenceError(
                f"failed to transact on authoritative graph for tenant {tenant.value!r}"
            ) from exc
        except BaseException:
            if transaction is not None:
                transaction._abort_if_open()
            raise
        else:
            assert transaction is not None
            receipt = _receipt_for(tenant, transaction.read(), principal)
            transaction.commit(receipt)

    def _persist(
        self,
        repository: RevisionRepository,
        outbox: OutboxRepository,
        tenant: TenantId,
        graph: MemoryGraph,
        principal: PrincipalRef,
    ) -> None:
        """Apply direct-write orchestration using an already-owned transaction."""
        head = repository.get_head(tenant)
        if head is None:
            revision = self._revision_for(tenant, graph, principal, head)
            repository.create_first_revision(revision)
            outbox.append(self._outbox_event_for(revision))
            return

        opened = _load_head_snapshot(repository, tenant, head)
        staged_hash = graph.content_hash()
        graph_diff = diff_graphs(opened, graph)

        if staged_hash == head.content_hash:
            if not graph_diff.is_empty:
                raise PersistenceError(
                    "equal graph hashes produced a non-empty diff for " f"tenant {tenant.value!r}"
                )
            if not repository.revalidate_head(tenant, head):
                raise PersistenceConflictError(
                    f"authoritative head changed while confirming no-op "
                    f"for tenant {tenant.value!r}"
                )
            return

        if graph_diff.is_empty:
            raise PersistenceError(
                "different graph hashes produced an empty diff for " f"tenant {tenant.value!r}"
            )
        revision = self._revision_for(tenant, graph, principal, head)
        repository.append_revision(revision)
        outbox.append(self._outbox_event_for(revision))

    def _revision_for(
        self,
        tenant: TenantId,
        graph: MemoryGraph,
        principal: PrincipalRef,
        head: RevisionHead | None,
    ) -> Revision:
        return Revision(
            tenant=tenant,
            revision_number=1 if head is None else head.revision_number + 1,
            content_hash=graph.content_hash(),
            parent_hash=None if head is None else head.content_hash,
            principal=principal,
            node_count=graph.node_count,
            edge_count=graph.edge_count,
            graph_json=graph.model_dump(mode="json"),
            created_at=self._clock(),
        )

    @staticmethod
    def _outbox_event_for(revision: Revision) -> OutboxEvent:
        """Build the single baseline event owned by a committed revision."""
        return OutboxEvent(
            event_id=uuid4(),
            tenant=revision.tenant,
            revision_number=revision.revision_number,
            content_hash=revision.content_hash,
            event_type="graph.revision.committed",
            schema_version=1,
            idempotency_key=f"{revision.tenant.value}:{revision.revision_number}",
            payload={
                "tenant_id": revision.tenant.value,
                "revision_number": revision.revision_number,
                "content_hash": revision.content_hash,
                "parent_hash": revision.parent_hash,
                "principal_id": revision.principal.principal_id,
                "principal_kind": revision.principal.kind.value,
                "node_count": revision.node_count,
                "edge_count": revision.edge_count,
                "created_at": revision.created_at.isoformat(),
            },
            created_at=revision.created_at,
        )

    def _resolve_projection(self) -> Neo4jGraphProjection | None:
        if self._projection is None:
            return None
        if isinstance(self._projection, LazyNeo4jProjection):
            return self._projection.get()
        return self._projection

    def _read_authoritative(self, tenant: TenantId) -> MemoryGraph:
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                return _read_from_repository(repository, tenant)
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to read authoritative graph for tenant {tenant.value!r}"
            ) from exc

    def _read_via_projection(
        self,
        tenant: TenantId,
        projection: Neo4jGraphProjection,
        pg_fallback: MemoryGraph,
    ) -> MemoryGraph:
        pg_head = self._load_pg_head(tenant)
        if pg_head is None:
            return EMPTY_GRAPH
        pg_revision, expected_hash = pg_head
        try:
            proj_head = projection.get_projection_head(tenant)
            if (
                proj_head is not None
                and proj_head.revision_number == pg_revision
                and proj_head.content_hash == expected_hash
            ):
                graph = projection.reconstruct(tenant)
                if graph.content_hash() == expected_hash:
                    return graph
            return projection.read_repair(
                tenant,
                load_head=self._load_pg_head,
                load_revision=self._load_revision,
            )
        except PersistenceError:
            return pg_fallback

    def _load_pg_head(self, tenant: TenantId) -> tuple[int, str] | None:
        with self._transactions.transaction() as connection:
            head = self._repository_factory(connection).get_head(tenant)
            if head is None:
                return None
            return head.revision_number, head.content_hash

    def _load_revision(self, tenant: TenantId, revision_number: int) -> Revision | None:
        with self._transactions.transaction() as connection:
            return self._repository_factory(connection).get_revision(tenant, revision_number)


def _deserialize_snapshot(revision: Revision) -> MemoryGraph:
    try:
        graph = MemoryGraph.model_validate(revision.graph_json)
    except ValidationError as exc:
        raise PersistenceError(
            f"invalid graph snapshot at revision {revision.revision_number} "
            f"for tenant {revision.tenant.value!r}"
        ) from exc

    actual_hash = graph.content_hash()
    if actual_hash != revision.content_hash:
        raise PersistenceError(
            f"graph snapshot hash mismatch at revision {revision.revision_number} "
            f"for tenant {revision.tenant.value!r}"
        )
    return graph


def _read_from_repository(repository: RevisionRepository, tenant: TenantId) -> MemoryGraph:
    head = repository.get_head(tenant)
    if head is None:
        return EMPTY_GRAPH
    return _load_head_snapshot(repository, tenant, head)


def _load_head_snapshot(
    repository: RevisionRepository, tenant: TenantId, head: RevisionHead
) -> MemoryGraph:
    revision = repository.get_revision(tenant, head.revision_number)
    if revision is None:
        raise PersistenceError(
            f"authoritative head revision {head.revision_number} is missing "
            f"for tenant {tenant.value!r}"
        )
    if revision.content_hash != head.content_hash:
        raise PersistenceError(
            f"head/revision hash mismatch for tenant {tenant.value!r} "
            f"at revision {head.revision_number}"
        )
    return _deserialize_snapshot(revision)


def _receipt_for(tenant: TenantId, graph: MemoryGraph, principal: PrincipalRef) -> WriteReceipt:
    return WriteReceipt(
        tenant=tenant,
        principal=principal,
        content_hash=graph.content_hash(),
        node_count=graph.node_count,
        edge_count=graph.edge_count,
    )
