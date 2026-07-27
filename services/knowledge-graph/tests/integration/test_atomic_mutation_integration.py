"""PostgreSQL-gated ADR-030 atomicity and concurrency verification."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest
from emg_common_types import Classification
from emg_knowledge_graph import (
    CommittedMutation,
    CreateEntityCommand,
    KnowledgeGraphApplication,
    MutationAuditIntent,
    MutationExecutionRequest,
    MutationResult,
)
from emg_knowledge_graph_infrastructure import PostgresAtomicMutationExecution
from emg_ontology import Entity, ProvenanceReference
from emg_persistence import PersistenceSettings
from emg_persistence.migrate import run_migrations
from emg_persistence.postgres import (
    ContextBoundTransactionProvider,
    PostgresMigrationExecutor,
    PostgresOutboxRepository,
    PostgresRevisionRepository,
    connect,
)
from emg_persistence.store import PostgresNeo4jGraphStore
from emg_platform_core import PrincipalRef, TenantId, WriteReceipt
from psycopg import Connection

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)
_SCHEMA = "stage3_atomic_mutation_test"
_TENANT = TenantId.of("stage3-tenant")
_PRINCIPAL = PrincipalRef.service("stage3-writer")
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _SchemaConnections:
    def __init__(self, settings: PersistenceSettings) -> None:
        self._settings = settings

    @contextmanager
    def acquire(self) -> Iterator[Connection[Any]]:
        connection = connect(self._settings)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SET search_path TO {_SCHEMA}")
            connection.commit()
            yield connection
        finally:
            connection.close()


def _entity(entity_id: str = "entity-1") -> Entity:
    return Entity(
        entity_id=entity_id,
        entity_type="person",
        classification=Classification.INTERNAL,
        trust_score=0.9,
        provenance_reference=ProvenanceReference(source_principal="connector", event_id="event-1"),
        owner="owner-a",
        effective_from=_NOW,
    )


def _command(entity_id: str = "entity-1") -> CreateEntityCommand:
    return CreateEntityCommand(
        tenant=_TENANT,
        principal=_PRINCIPAL,
        entity=_entity(entity_id),
        idempotency_key="stage3-key",
        as_of=_NOW,
    )


def _app(
    settings: PersistenceSettings,
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> KnowledgeGraphApplication:
    connections = _SchemaConnections(settings)
    transactions = ContextBoundTransactionProvider(connections)
    store = PostgresNeo4jGraphStore(
        transactions,
        repository_factory=PostgresRevisionRepository,
        outbox_repository_factory=PostgresOutboxRepository,
    )
    atomic = PostgresAtomicMutationExecution(transactions, failure_injector=failure_injector)
    return KnowledgeGraphApplication(
        store,
        atomic_mutation_execution=atomic,
    )


@pytest.fixture
def settings() -> Iterator[PersistenceSettings]:  # pragma: no cover - live DB
    configured = PersistenceSettings(postgres_dsn=_PG_DSN)
    connection = connect(configured)
    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        cursor.execute(f"CREATE SCHEMA {_SCHEMA}")
        cursor.execute(f"SET search_path TO {_SCHEMA}")
    connection.commit()
    run_migrations(PostgresMigrationExecutor(connection))
    connection.close()
    try:
        yield configured
    finally:
        connection = connect(configured)
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        connection.commit()
        connection.close()


@requires_postgres
def test_first_execution_and_replay_commit_one_complete_unit(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB
    app = _app(settings)
    first = app.create_entity(_command())
    replay = app.create_entity(_command())

    assert replay == first
    with (
        _SchemaConnections(settings).acquire() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT count(*) FROM graph_revisions")
        assert cursor.fetchone() == (1,)
        cursor.execute("SELECT count(*) FROM mutation_ledger")
        assert cursor.fetchone() == (1,)
        cursor.execute("SELECT state FROM mutation_idempotency")
        assert cursor.fetchone() == ("succeeded",)
        cursor.execute("SELECT channel FROM mutation_dispatch ORDER BY channel")
        assert cursor.fetchall() == [("audit",), ("event",)]


@requires_postgres
def test_duplicate_request_race_has_one_graph_and_ledger_write(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB
    barrier = threading.Barrier(2)
    results = []
    failures: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            results.append(_app(settings).create_entity(_command()))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert failures == []
    assert len(results) == 2
    assert results[0] == results[1]
    with (
        _SchemaConnections(settings).acquire() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT count(*) FROM graph_revisions")
        assert cursor.fetchone() == (1,)
        cursor.execute("SELECT count(*) FROM mutation_ledger")
        assert cursor.fetchone() == (1,)


@requires_postgres
@pytest.mark.parametrize("failure_point", ["after_graph_write", "after_ledger_write"])
def test_failure_injection_rolls_back_graph_claim_ledger_and_dispatch(
    settings: PersistenceSettings,
    failure_point: str,
) -> None:  # pragma: no cover - live DB
    def fail(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"injected {point}")

    with pytest.raises(RuntimeError, match="injected"):
        _app(settings, failure_injector=fail).create_entity(_command())

    with (
        _SchemaConnections(settings).acquire() as connection,
        connection.cursor() as cursor,
    ):
        for table in (
            "graph_revisions",
            "graph_head",
            "mutation_idempotency",
            "mutation_ledger",
            "mutation_ledger_resource",
            "mutation_dispatch",
        ):
            cursor.execute(f"SELECT count(*) FROM {table}")
            assert cursor.fetchone() == (0,)

    assert _app(settings).create_entity(_command()).revision_number == 1


@requires_postgres
def test_expired_key_is_reclaimed_without_deleting_immutable_history(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB
    assert _app(settings).create_entity(_command()).revision_number == 1
    with (
        _SchemaConnections(settings).acquire() as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE mutation_idempotency "
            "SET expires_at = clock_timestamp() - interval '1 second' "
            "WHERE tenant_id = %s AND principal_id = %s AND idempotency_key = %s",
            (_TENANT.value, str(_PRINCIPAL.principal_id), "stage3-key"),
        )

    second = _app(settings).create_entity(_command("entity-2"))
    assert second.revision_number == 2
    with (
        _SchemaConnections(settings).acquire() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT count(*) FROM mutation_ledger")
        assert cursor.fetchone() == (2,)
        cursor.execute("SELECT count(*) FROM mutation_idempotency")
        assert cursor.fetchone() == (1,)


@requires_postgres
def test_batch_resources_persist_by_ordinal_without_synthetic_identity(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB
    first = _app(settings).create_entity(_command())
    with (
        _SchemaConnections(settings).acquire() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT created_at FROM graph_revisions "
            "WHERE tenant_id = %s AND revision_number = %s",
            (_TENANT.value, first.revision_number),
        )
        graph_revision_at = cursor.fetchone()[0]

    intent = MutationAuditIntent(
        tenant=_TENANT,
        principal=_PRINCIPAL,
        idempotency_key="batch-key",
        action="update",
        resource_type="knowledge-graph.entity",
        resource_id="entity-1",
        related_resource_ids=(),
        classification=Classification.INTERNAL,
        reason="batch",
        revision_number=first.revision_number,
        content_hash=first.content_hash,
    )
    result = MutationResult(
        tenant=_TENANT,
        principal=_PRINCIPAL,
        revision_number=first.revision_number,
        content_hash=first.content_hash,
        node_count=first.node_count,
        edge_count=first.edge_count,
        revision_created=False,
        nodes_created=0,
        edges_created=0,
        node_inputs_merged=0,
        edge_inputs_merged=0,
        audit_intents=(intent, intent),
    )
    receipt = WriteReceipt(
        tenant=_TENANT,
        principal=_PRINCIPAL,
        content_hash=first.content_hash,
        node_count=first.node_count,
        edge_count=first.edge_count,
        revision_number=first.revision_number,
        committed_at=graph_revision_at,
        revision_created=False,
    )
    request = MutationExecutionRequest(
        tenant=_TENANT,
        principal=_PRINCIPAL,
        idempotency_key="batch-key",
        operation="entity.batch",
        command_fingerprint="b" * 64,
        fingerprint_version=1,
        command_schema_version=1,
    )
    transactions = ContextBoundTransactionProvider(_SchemaConnections(settings))
    atomic = PostgresAtomicMutationExecution(transactions)
    atomic.execute(
        request,
        lambda: CommittedMutation(result=result, receipt=receipt),
    )

    with (
        _SchemaConnections(settings).acquire() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT resource.ordinal, resource.resource_type, "
            "resource.resource_id, resource.action "
            "FROM mutation_ledger_resource resource "
            "JOIN mutation_ledger ledger ON ledger.mutation_id = resource.mutation_id "
            "WHERE ledger.idempotency_key = 'batch-key' ORDER BY resource.ordinal"
        )
        assert cursor.fetchall() == [
            (0, "knowledge-graph.entity", "entity-1", "update"),
            (1, "knowledge-graph.entity", "entity-1", "update"),
        ]
