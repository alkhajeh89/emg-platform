"""PostgreSQL-authoritative direct graph persistence."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from emg_memory_graph import EMPTY_GRAPH, MemoryGraph, diff_graphs
from emg_platform_core import (
    GraphTransaction,
    PrincipalRef,
    RevisionNotFoundError,
    SnapshotIntegrityError,
    TenantId,
    TransactionStateError,
    WriteReceipt,
)
from emg_platform_core.ports import (
    DEFAULT_REVISION_LIST_LIMIT,
    HistoricalGraphRevision,
    RevisionMetadata,
)
from psycopg import Error as PsycopgError
from pydantic import ValidationError

from .errors import PersistenceConflictError, PersistenceError
from .neo4j.lazy import LazyNeo4jProjection
from .neo4j.projection import Neo4jGraphProjection
from .outbox import OutboxEvent, OutboxRepository
from .postgres.outbox_repository import PostgresOutboxRepository
from .postgres.revision_repository import PostgresRevisionRepository
from .postgres.search_repository import PostgresSearchRepository
from .postgres.transactions import TransactionProvider
from .revisions import Revision, RevisionHead, RevisionRepository

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from psycopg import Connection

RevisionRepositoryFactory = Callable[["Connection[Any]"], RevisionRepository]
OutboxRepositoryFactory = Callable[["Connection[Any]"], OutboxRepository]
Clock = Callable[[], datetime]
ProjectionSource = Neo4jGraphProjection | LazyNeo4jProjection | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class _CommitOutcome:
    """Authoritative revision identity produced by one ``_persist`` call
    (ADR-023 §11) — never inferred by a second list/read call after commit."""

    revision_number: int
    committed_at: datetime
    revision_created: bool


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
    """PostgreSQL-authoritative store with optional Neo4j serving reads."""

    def __init__(
        self,
        transactions: TransactionProvider,
        *,
        repository_factory: RevisionRepositoryFactory = PostgresRevisionRepository,
        outbox_repository_factory: OutboxRepositoryFactory = PostgresOutboxRepository,
        projection: ProjectionSource = None,
        clock: Clock = _utcnow,
        search_representation_retention: timedelta = timedelta(minutes=60),
        search_cleanup_interval: timedelta = timedelta(minutes=15),
        search_cleanup_batch_size: int = 500,
    ) -> None:
        self._transactions = transactions
        self._repository_factory = repository_factory
        self._outbox_repository_factory = outbox_repository_factory
        self._projection = projection
        self._clock = clock
        self._search_representation_retention = search_representation_retention
        self._search_cleanup_interval = search_cleanup_interval
        self._search_cleanup_batch_size = search_cleanup_batch_size
        self._next_search_cleanup_at: datetime | None = None
        self._search_cleanup_lock = Lock()
        self._search_persistence_available: bool | None = None

    def read(self, tenant: TenantId) -> MemoryGraph:
        """Prefer Neo4j serving projection with read-repair; fall back to PostgreSQL."""
        head = self._read_authoritative_head(tenant)
        if head is None:
            return EMPTY_GRAPH
        try:
            projection = self._resolve_projection()
        except Exception:
            projection = None
        if projection is None:
            return self._read_authoritative_snapshot(tenant, head)[1]
        return self._read_via_projection(tenant, projection, head)

    def write(
        self, tenant: TenantId, graph: MemoryGraph, *, principal: PrincipalRef
    ) -> WriteReceipt:
        """Durably persist ``graph`` and return proof only after commit."""
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                outbox = self._outbox_repository_factory(connection)
                outcome = self._persist(
                    repository,
                    outbox,
                    tenant,
                    graph,
                    principal,
                    self._search_repository(connection),
                )
        except PersistenceConflictError:
            raise
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to write authoritative graph for tenant {tenant.value!r}"
            ) from exc
        if outcome.revision_created and outcome.revision_number > 1:
            self._schedule_previous_search_retirement(tenant, outcome.revision_number)
        return _receipt_for(tenant, graph, principal, outcome)

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
        outcome: _CommitOutcome | None = None
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                outbox = self._outbox_repository_factory(connection)
                current = _read_from_repository(repository, tenant)
                transaction = _PersistentGraphTransaction(tenant, principal, current)
                try:
                    yield transaction
                    outcome = self._persist(
                        repository,
                        outbox,
                        tenant,
                        transaction.read(),
                        principal,
                        self._search_repository(connection),
                    )
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
            assert outcome is not None
            if outcome.revision_created and outcome.revision_number > 1:
                self._schedule_previous_search_retirement(tenant, outcome.revision_number)
            receipt = _receipt_for(tenant, transaction.read(), principal, outcome)
            transaction.commit(receipt)

    def _persist(
        self,
        repository: RevisionRepository,
        outbox: OutboxRepository,
        tenant: TenantId,
        graph: MemoryGraph,
        principal: PrincipalRef,
        search_repository: PostgresSearchRepository | None,
    ) -> _CommitOutcome:
        """Apply direct-write orchestration using an already-owned transaction.

        Returns the authoritative revision identity the commit resolved to
        (ADR-023 §11) — a no-op never creates a revision row or outbox event
        and identifies the existing head; an append does both and identifies
        the newly created revision.
        """
        head = repository.get_head(tenant)
        if head is None:
            revision = self._revision_for(tenant, graph, principal, head)
            repository.create_first_revision(revision)
            if search_repository is not None:
                search_repository.index_revision(
                    tenant, revision.revision_number, revision.content_hash, graph
                )
            outbox.append(self._outbox_event_for(revision))
            return _CommitOutcome(
                revision_number=revision.revision_number,
                committed_at=revision.created_at,
                revision_created=True,
            )

        head_revision = _load_head_revision(repository, tenant, head)
        opened = _deserialize_snapshot(head_revision)
        staged_hash = graph.content_hash()
        graph_diff = diff_graphs(opened, graph)

        if staged_hash == head.content_hash:
            if not graph_diff.is_empty:
                raise PersistenceError(
                    f"equal graph hashes produced a non-empty diff for tenant {tenant.value!r}"
                )
            if not repository.revalidate_head(tenant, head):
                raise PersistenceConflictError(
                    f"authoritative head changed while confirming no-op for tenant {tenant.value!r}"
                )
            return _CommitOutcome(
                revision_number=head.revision_number,
                committed_at=head_revision.created_at,
                revision_created=False,
            )

        if graph_diff.is_empty:
            raise PersistenceError(
                f"different graph hashes produced an empty diff for tenant {tenant.value!r}"
            )
        revision = self._revision_for(tenant, graph, principal, head)
        repository.append_revision(revision)
        if search_repository is not None:
            search_repository.index_revision(
                tenant, revision.revision_number, revision.content_hash, graph
            )
        outbox.append(self._outbox_event_for(revision))
        return _CommitOutcome(
            revision_number=revision.revision_number,
            committed_at=revision.created_at,
            revision_created=True,
        )

    def search_candidates(
        self,
        tenant: TenantId,
        revision_number: int | None,
        normalized_query: str,
        *,
        after_tier: int,
        after_node_id: str,
        candidate_ceiling: int,
    ) -> tuple[
        int,
        datetime,
        bool,
        datetime | None,
        tuple[tuple[Any, ...], ...],
    ]:
        """Resolve authority and return indexed candidates without graph loading."""
        self._maybe_cleanup_search_representations()
        with self._transactions.transaction() as connection:
            repository = PostgresSearchRepository(connection)
            resolved = repository.resolve_revision(tenant, revision_number)
            if resolved is None:
                raise PersistenceError("retained governed-search representation is unavailable")
            resolved_revision, committed_at, is_current, representation_expiry = resolved
            rows = repository.search(
                tenant,
                resolved_revision,
                normalized_query,
                after_tier=after_tier,
                after_node_id=after_node_id,
                limit=candidate_ceiling + 1,
            )
            return (
                resolved_revision,
                committed_at,
                is_current,
                representation_expiry,
                rows,
            )

    def cleanup_search_representations(self, now: datetime) -> int:
        with self._transactions.transaction() as connection:
            repository = PostgresSearchRepository(connection)
            repository.expire_unscheduled_previous(
                now + self._search_representation_retention,
                limit=self._search_cleanup_batch_size,
            )
            return repository.delete_expired(now, limit=self._search_cleanup_batch_size)

    def search_representation_metrics(self) -> tuple[tuple[Any, ...], ...]:
        """Return operator-facing row and storage cardinality observations."""
        with self._transactions.transaction() as connection:
            return PostgresSearchRepository(connection).representation_metrics()

    def _schedule_previous_search_retirement(self, tenant: TenantId, revision_number: int) -> None:
        """Start retention after the new head transaction has committed."""
        if self._search_persistence_available is False:
            return
        try:
            with self._transactions.transaction() as connection:
                PostgresSearchRepository(connection).expire_previous(
                    tenant,
                    revision_number,
                    self._clock() + self._search_representation_retention,
                )
        except Exception:
            logger.warning("governed-search retirement scheduling delayed", exc_info=True)

    def _maybe_cleanup_search_representations(self) -> None:
        """Run best-effort cleanup; failures retain excess state and do not fail search."""
        now = self._clock()
        if self._next_search_cleanup_at is not None and now < self._next_search_cleanup_at:
            return
        if not self._search_cleanup_lock.acquire(blocking=False):
            return
        try:
            if self._next_search_cleanup_at is not None and now < self._next_search_cleanup_at:
                return
            try:
                self.cleanup_search_representations(now)
            except Exception:
                logger.warning("governed-search representation cleanup delayed", exc_info=True)
            finally:
                self._next_search_cleanup_at = now + self._search_cleanup_interval
        finally:
            self._search_cleanup_lock.release()

    def _search_repository(self, connection: object) -> PostgresSearchRepository | None:
        """Build the adapter for real DB connections.

        Several port-level store tests intentionally use an opaque transaction token;
        those tests exercise orchestration without pretending to be a SQL connection.
        PostgreSQL integration tests use a connection exposing ``cursor``.
        """
        if not callable(getattr(connection, "cursor", None)):
            self._search_persistence_available = False
            return None
        self._search_persistence_available = True
        return PostgresSearchRepository(cast("Connection[Any]", connection))

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

    def _read_authoritative_head(self, tenant: TenantId) -> RevisionHead | None:
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                return repository.get_head(tenant)
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to read authoritative graph for tenant {tenant.value!r}"
            ) from exc

    def _read_authoritative_snapshot(
        self, tenant: TenantId, head: RevisionHead
    ) -> tuple[Revision, MemoryGraph]:
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                revision = _load_head_revision(repository, tenant, head)
                return revision, _deserialize_snapshot(revision)
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
        head: RevisionHead,
    ) -> MemoryGraph:
        projection_available = True
        try:
            proj_head = projection.get_projection_head(tenant)
            if (
                proj_head is not None
                and proj_head.revision_number == head.revision_number
                and proj_head.content_hash == head.content_hash
            ):
                graph = projection.reconstruct(tenant)
                if graph.content_hash() == head.content_hash:
                    return graph
        except Exception:
            projection_available = False
            proj_head = None

        revision, fallback = self._read_authoritative_snapshot(tenant, head)
        if projection_available and (
            proj_head is None or proj_head.revision_number < head.revision_number
        ):
            self._attempt_read_repair(tenant, projection, head, revision)
        return fallback

    def _attempt_read_repair(
        self,
        tenant: TenantId,
        projection: Neo4jGraphProjection,
        head: RevisionHead,
        head_revision: Revision,
    ) -> None:
        def load_head(requested_tenant: TenantId) -> tuple[int, str] | None:
            if requested_tenant != tenant:
                return None
            return head.revision_number, head.content_hash

        def load_revision(requested_tenant: TenantId, revision_number: int) -> Revision | None:
            if requested_tenant != tenant:
                return None
            if revision_number == head.revision_number:
                return head_revision
            return self._load_revision(requested_tenant, revision_number)

        try:
            projection.read_repair(
                tenant,
                load_head=load_head,
                load_revision=load_revision,
            )
        except Exception:
            # PostgreSQL fallback is already integrity-checked and remains
            # available even when best-effort projection repair fails.
            return

    def _load_revision(self, tenant: TenantId, revision_number: int) -> Revision | None:
        with self._transactions.transaction() as connection:
            return self._repository_factory(connection).get_revision(tenant, revision_number)

    # --- GraphRevisionReader (ADR-023) --------------------------------------
    def list_revisions(
        self,
        tenant: TenantId,
        *,
        limit: int = DEFAULT_REVISION_LIST_LIMIT,
        before_revision_number: int | None = None,
    ) -> tuple[RevisionMetadata, ...]:
        """Metadata-only listing; never deserializes or hash-verifies a
        graph snapshot (ADR-023 §13, §18)."""
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                records = repository.list_revisions(
                    tenant, limit=limit, before_revision_number=before_revision_number
                )
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError(f"failed to list revisions for tenant {tenant.value!r}") from exc
        return tuple(
            RevisionMetadata(
                tenant=record.tenant,
                revision_number=record.revision_number,
                content_hash=record.content_hash,
                parent_hash=record.parent_hash,
                principal=record.principal,
                node_count=record.node_count,
                edge_count=record.edge_count,
                created_at=record.created_at,
            )
            for record in records
        )

    def read_revision(self, tenant: TenantId, revision_number: int) -> HistoricalGraphRevision:
        """Full historical read: fetch, deserialize, and hash-verify the
        requested revision, reusing the same snapshot logic that already
        guards head reads (``_deserialize_snapshot``) rather than
        duplicating it (ADR-023 §9, §13)."""
        try:
            with self._transactions.transaction() as connection:
                repository = self._repository_factory(connection)
                revision = repository.get_revision(tenant, revision_number)
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to read revision {revision_number} for tenant {tenant.value!r}"
            ) from exc
        if revision is None:
            raise RevisionNotFoundError(
                f"no revision {revision_number} for tenant {tenant.value!r}"
            )
        try:
            graph = _deserialize_snapshot(revision)
        except PersistenceError as exc:
            raise SnapshotIntegrityError(str(exc)) from exc
        metadata = RevisionMetadata(
            tenant=revision.tenant,
            revision_number=revision.revision_number,
            content_hash=revision.content_hash,
            parent_hash=revision.parent_hash,
            principal=revision.principal,
            node_count=revision.node_count,
            edge_count=revision.edge_count,
            created_at=revision.created_at,
        )
        return HistoricalGraphRevision(metadata=metadata, graph=graph)


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
    revision = _load_head_revision(repository, tenant, head)
    return _deserialize_snapshot(revision)


def _load_head_revision(
    repository: RevisionRepository, tenant: TenantId, head: RevisionHead
) -> Revision:
    """Fetch and integrity-check the ``Revision`` row the head points at
    (without deserializing its graph). Callers that also need the graph call
    :func:`_deserialize_snapshot` on the returned ``Revision`` themselves —
    this avoids a second ``get_revision`` round trip for callers (e.g. the
    no-op commit path) that only need the revision's metadata, such as
    ``created_at`` (ADR-023 §11)."""
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
    return revision


def _receipt_for(
    tenant: TenantId, graph: MemoryGraph, principal: PrincipalRef, outcome: _CommitOutcome
) -> WriteReceipt:
    return WriteReceipt(
        tenant=tenant,
        principal=principal,
        content_hash=graph.content_hash(),
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        revision_number=outcome.revision_number,
        committed_at=outcome.committed_at,
        revision_created=outcome.revision_created,
    )
