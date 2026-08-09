"""Live PostgreSQL coverage for bounded ADR-030 dispatch claims."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from _persistence_integration_helpers import truncate_persistence_tables
from emg_audit_projector.config import Settings as ProjectorSettings
from emg_audit_projector.worker import AuditProjectorWorker
from emg_memory_graph import EvidenceRef, EvidenceSource, MemoryGraph, MemoryNode
from emg_persistence import PersistenceSettings, PostgresNeo4jGraphStore
from emg_persistence.migrate import run_migrations
from emg_persistence.mutations import DispatchWorkItem, LedgerAppend, LedgerResource
from emg_persistence.postgres import (
    DirectConnectionProvider,
    PostgresMigrationExecutor,
    PostgresMutationRepository,
    PostgresTransactionProvider,
    connect,
)
from emg_platform_core import PrincipalRef, TenantId

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)

_PRINCIPAL = PrincipalRef.service("dispatch-test-writer")
_CAPTURED_AT = datetime(2026, 8, 2, tzinfo=timezone.utc)
_LEASE = timedelta(minutes=5)


@pytest.fixture
def settings() -> PersistenceSettings:  # pragma: no cover - live DB only
    return PersistenceSettings(postgres_dsn=_PG_DSN)


@pytest.fixture(autouse=True)
def clean_database(settings: PersistenceSettings) -> Iterator[None]:  # pragma: no cover
    connection = connect(settings)
    run_migrations(PostgresMigrationExecutor(connection))
    truncate_persistence_tables(connection)
    connection.commit()
    connection.close()
    try:
        yield
    finally:
        connection = connect(settings)
        truncate_persistence_tables(connection)
        connection.commit()
        connection.close()


def _graph(node_id: str) -> MemoryGraph:
    evidence = EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator=f"document-{node_id}",
        source_principal="dispatch-test-source",
        captured_at=_CAPTURED_AT,
    )
    return MemoryGraph(
        nodes=(
            MemoryNode(
                node_id=node_id,
                node_type="person",
                label=f"Node {node_id}",
                created_at=_CAPTURED_AT,
                updated_at=_CAPTURED_AT,
                source="dispatch-test-source",
                confidence=0.9,
                evidence=(evidence,),
            ),
        )
    )


def _seed_dispatch(
    settings: PersistenceSettings,
    *,
    tenant_id: str,
    idempotency_key: str,
) -> UUID:
    tenant = TenantId.of(tenant_id)
    graph = _graph(f"node-{tenant_id}")
    store = PostgresNeo4jGraphStore(PostgresTransactionProvider(DirectConnectionProvider(settings)))
    receipt = store.write(tenant, graph, principal=_PRINCIPAL)
    mutation_id = uuid4()
    resource = LedgerResource(
        ordinal=0,
        resource_type="entity",
        resource_id=graph.nodes[0].node_id,
        action="create_entity",
        classification="INTERNAL",
        reason=None,
    )
    intent: dict[str, object] = {
        "tenant_id": tenant.value,
        "principal": _PRINCIPAL.model_dump(mode="json"),
        "idempotency_key": idempotency_key,
        "action": resource.action,
        "resource_type": resource.resource_type,
        "resource_id": resource.resource_id,
        "related_resource_ids": [],
        "classification": resource.classification,
        "reason": resource.reason,
        "revision_number": receipt.revision_number,
        "content_hash": receipt.content_hash,
    }
    result: dict[str, object] = {
        "schema_version": 1,
        "result": {
            "tenant_id": tenant.value,
            "principal": _PRINCIPAL.model_dump(mode="json"),
            "revision_number": receipt.revision_number,
            "content_hash": receipt.content_hash,
            "node_count": receipt.node_count,
            "edge_count": receipt.edge_count,
            "revision_created": receipt.revision_created,
            "nodes_created": 1,
            "edges_created": 0,
            "node_inputs_merged": 0,
            "edge_inputs_merged": 0,
            "audit_intents": [intent],
        },
    }
    audit: dict[str, object] = {"schema_version": 1, "intents": [intent]}
    fingerprint = mutation_id.hex * 2
    connection = connect(settings)
    try:
        with connection.transaction():
            repository = PostgresMutationRepository(connection)
            claim = repository.acquire_claim(
                tenant_id=tenant.value,
                principal_id=str(_PRINCIPAL.principal_id),
                idempotency_key=idempotency_key,
                operation="create_entity",
                command_fingerprint=fingerprint,
                fingerprint_version=1,
                command_schema_version=1,
                claim_ttl=timedelta(minutes=2),
                wait_timeout_seconds=1.0,
            )
            repository.append_success(
                claim=claim,
                ledger=LedgerAppend(
                    mutation_id=mutation_id,
                    tenant_id=tenant.value,
                    principal_id=str(_PRINCIPAL.principal_id),
                    principal_kind=_PRINCIPAL.kind.value,
                    idempotency_key=idempotency_key,
                    command_fingerprint=fingerprint,
                    fingerprint_version=1,
                    command_schema_version=1,
                    operation="create_entity",
                    status="succeeded",
                    graph_revision=receipt.revision_number,
                    graph_content_hash=receipt.content_hash,
                    graph_revision_at=receipt.committed_at,
                    write_receipt={
                        "schema_version": 1,
                        "receipt": receipt.model_dump(mode="json"),
                    },
                    mutation_result=result,
                    audit_intents=audit,
                    resources=(resource,),
                ),
                replay_retention=timedelta(hours=1),
            )
    finally:
        connection.close()
    return mutation_id


def _claim(
    settings: PersistenceSettings,
    *,
    tenant_id: str,
    channel: str,
    worker: str,
    max_attempts: int,
) -> tuple[DispatchWorkItem, ...]:
    connection = connect(settings)
    try:
        with connection.transaction():
            return PostgresMutationRepository(connection).claim_dispatch(
                tenant_id=tenant_id,
                channel=channel,
                worker=worker,
                limit=10,
                max_attempts=max_attempts,
                lease=_LEASE,
            )
    finally:
        connection.close()


def _set_dispatch_state(
    settings: PersistenceSettings,
    *,
    mutation_id: UUID,
    channel: str,
    attempt_count: int,
    expired_claim: bool = False,
) -> None:
    connection = connect(settings)
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE mutation_dispatch SET attempt_count = %(attempts)s, "
                "claim_owner = CASE WHEN %(expired)s THEN 'expired-worker' ELSE NULL END, "
                "claim_expires_at = CASE WHEN %(expired)s "
                "THEN clock_timestamp() - interval '1 second' ELSE NULL END "
                "WHERE mutation_id = %(mutation_id)s AND channel = %(channel)s",
                {
                    "attempts": attempt_count,
                    "expired": expired_claim,
                    "mutation_id": mutation_id,
                    "channel": channel,
                },
            )
    finally:
        connection.close()


@requires_postgres
def test_below_bound_row_is_claimed_and_incremented_once(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB
    mutation_id = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-a", idempotency_key="dispatch-key-a"
    )

    claimed = _claim(
        settings,
        tenant_id="dispatch-tenant-a",
        channel="audit",
        worker="worker-a",
        max_attempts=2,
    )

    assert len(claimed) == 1
    item = claimed[0]
    assert item.mutation_id == mutation_id
    assert item.attempt_count == 1
    assert item.claim_owner == "worker-a"


@requires_postgres
def test_row_at_bound_is_not_claimed(settings: PersistenceSettings) -> None:
    mutation_id = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-a", idempotency_key="dispatch-key-a"
    )
    _set_dispatch_state(settings, mutation_id=mutation_id, channel="audit", attempt_count=2)

    assert (
        _claim(
            settings,
            tenant_id="dispatch-tenant-a",
            channel="audit",
            worker="worker-a",
            max_attempts=2,
        )
        == ()
    )


@requires_postgres
def test_expired_row_at_bound_is_not_reclaimed(settings: PersistenceSettings) -> None:
    mutation_id = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-a", idempotency_key="dispatch-key-a"
    )
    _set_dispatch_state(
        settings,
        mutation_id=mutation_id,
        channel="audit",
        attempt_count=2,
        expired_claim=True,
    )

    assert (
        _claim(
            settings,
            tenant_id="dispatch-tenant-a",
            channel="audit",
            worker="worker-a",
            max_attempts=2,
        )
        == ()
    )


@requires_postgres
def test_claim_preserves_tenant_and_channel_isolation(
    settings: PersistenceSettings,
) -> None:
    mutation_a = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-a", idempotency_key="dispatch-key-a"
    )
    mutation_b = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-b", idempotency_key="dispatch-key-b"
    )

    claimed = _claim(
        settings,
        tenant_id="dispatch-tenant-a",
        channel="audit",
        worker="worker-a",
        max_attempts=2,
    )

    assert [item.mutation_id for item in claimed] == [mutation_a]
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT mutation_id, channel, attempt_count FROM mutation_dispatch "
                "ORDER BY mutation_id, channel"
            )
            attempts = {(row[0], row[1]): row[2] for row in cursor.fetchall()}
    finally:
        connection.close()
    assert attempts[(mutation_a, "audit")] == 1
    assert attempts[(mutation_a, "event")] == 0
    assert attempts[(mutation_b, "audit")] == 0
    assert attempts[(mutation_b, "event")] == 0


@requires_postgres
def test_concurrent_claimers_cannot_exceed_bound(settings: PersistenceSettings) -> None:
    mutation_id = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-a", idempotency_key="dispatch-key-a"
    )
    _set_dispatch_state(
        settings,
        mutation_id=mutation_id,
        channel="audit",
        attempt_count=1,
        expired_claim=True,
    )
    barrier = threading.Barrier(8)
    claimed_counts: list[int] = []
    failures: list[BaseException] = []
    result_lock = threading.Lock()

    def claim(worker_number: int) -> None:
        try:
            barrier.wait()
            count = len(
                _claim(
                    settings,
                    tenant_id="dispatch-tenant-a",
                    channel="audit",
                    worker=f"worker-{worker_number}",
                    max_attempts=2,
                )
            )
            with result_lock:
                claimed_counts.append(count)
        except BaseException as exc:
            with result_lock:
                failures.append(exc)

    threads = [threading.Thread(target=claim, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert sum(claimed_counts) == 1
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT attempt_count FROM mutation_dispatch "
                "WHERE mutation_id = %s AND channel = 'audit'",
                (mutation_id,),
            )
            assert cursor.fetchone() == (2,)
    finally:
        connection.close()


@requires_postgres
def test_complete_dispatch_behavior_is_unchanged(settings: PersistenceSettings) -> None:
    mutation_id = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-a", idempotency_key="dispatch-key-a"
    )
    assert (
        len(
            _claim(
                settings,
                tenant_id="dispatch-tenant-a",
                channel="audit",
                worker="worker-a",
                max_attempts=2,
            )
        )
        == 1
    )

    connection = connect(settings)
    try:
        with (
            pytest.raises(RuntimeError, match="mutation dispatch claim was lost"),
            connection.transaction(),
        ):
            PostgresMutationRepository(connection).complete_dispatch(
                tenant_id="dispatch-tenant-a",
                mutation_id=mutation_id,
                channel="audit",
                worker="wrong-worker",
            )
        with connection.transaction():
            PostgresMutationRepository(connection).complete_dispatch(
                tenant_id="dispatch-tenant-a",
                mutation_id=mutation_id,
                channel="audit",
                worker="worker-a",
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT delivered_at IS NOT NULL, claim_owner, claim_expires_at, attempt_count "
                "FROM mutation_dispatch WHERE mutation_id = %s AND channel = 'audit'",
                (mutation_id,),
            )
            assert cursor.fetchone() == (True, None, None, 1)
    finally:
        connection.close()

    assert (
        _claim(
            settings,
            tenant_id="dispatch-tenant-a",
            channel="audit",
            worker="worker-b",
            max_attempts=2,
        )
        == ()
    )


class _AcceptingAuditDelivery:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    def deliver(self, events, **kwargs) -> None:
        del kwargs
        self.event_ids.extend(event.event_id for event in events)


@requires_postgres
def test_live_projector_claims_projects_delivers_and_acknowledges(
    settings: PersistenceSettings,
) -> None:
    mutation_id = _seed_dispatch(
        settings, tenant_id="dispatch-tenant-a", idempotency_key="projector-live"
    )
    delivery = _AcceptingAuditDelivery()
    projector_settings = ProjectorSettings(
        deployment_environment="test",
        postgres_dsn=settings.postgres_dsn,
        tenant_credentials_json=json.dumps(
            [
                {
                    "tenant_id": "dispatch-tenant-a",
                    "client_id": "emg-svc-audit-projector-dispatch-tenant-a",
                    "client_secret": "integration-only",
                }
            ]
        ),
        worker_id="live-projector",
        telemetry_interval_seconds=300,
    )
    worker = AuditProjectorWorker(
        projector_settings,
        PostgresTransactionProvider(DirectConnectionProvider(settings)),
        delivery,  # type: ignore[arg-type]
    )

    assert worker.run_cycle() is True

    assert delivery.event_ids == [f"kg-mutation:{mutation_id}:0"]
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT delivered_at IS NOT NULL, claim_owner, claim_expires_at, "
                "attempt_count FROM mutation_dispatch "
                "WHERE mutation_id = %s AND channel = 'audit'",
                (mutation_id,),
            )
            assert cursor.fetchone() == (True, None, None, 1)
    finally:
        connection.close()
