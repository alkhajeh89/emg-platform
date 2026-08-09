"""Authoritative mutation-to-audit proof across both PostgreSQL boundaries."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_audit_projector.config import Settings as ProjectorSettings
from emg_audit_projector.delivery import AuditDeliveryClient
from emg_audit_projector.projection import project_audit_events
from emg_audit_projector.worker import AuditProjectorWorker
from emg_audit_service.authn import (
    ServiceTokenValidator,
    service_token_validator_dependency,
)
from emg_audit_service.config import Settings as AuditSettings
from emg_audit_service.main import create_app
from emg_common_types import Classification
from emg_knowledge_graph import CreateEntityCommand, KnowledgeGraphApplication
from emg_knowledge_graph_infrastructure import PostgresAtomicMutationExecution
from emg_ontology import Entity, ProvenanceReference
from emg_persistence import PersistenceSettings, PostgresNeo4jGraphStore
from emg_persistence.postgres import (
    ContextBoundTransactionProvider,
    DirectConnectionProvider,
    PostgresMigrationExecutor,
    PostgresMutationRepository,
)
from emg_persistence.provisioning import run_knowledge_graph_migrations
from emg_platform_core import PrincipalRef, TenantId
from fastapi.testclient import TestClient
from psycopg import sql

ROOT = Path(__file__).resolve().parents[4]
_BASE_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
_TENANT = TenantId.of("rc1e-authoritative-tenant")
_PRINCIPAL = PrincipalRef.service("rc1e-knowledge-graph-writer")
_PROJECTOR_CLIENT_ID = "emg-svc-audit-projector-rc1e"
_NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)
_AUDIT_SCHEMA_SCRIPTS = (
    "001_audit_events.sql",
    "002_audit_provenance.sql",
    "003_evidence_custody.sql",
    "004_audit_reporting_indexes.sql",
    "006_audit_tenant.sql",
)

pytestmark = pytest.mark.skipif(
    not _BASE_DSN,
    reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN",
)


def _database_dsn(base_dsn: str, database: str) -> str:
    parsed = urlsplit(base_dsn)
    return urlunsplit(parsed._replace(path=f"/{database}"))


def _initialize_database(postgres_dsn: str) -> None:
    settings = PersistenceSettings(postgres_dsn=postgres_dsn)
    connection = psycopg.connect(postgres_dsn)
    try:
        run_knowledge_graph_migrations(PostgresMigrationExecutor(connection))
        seed_root = ROOT / "tools/seed-data/postgres"
        with connection.cursor() as cursor:
            for script_name in _AUDIT_SCHEMA_SCRIPTS:
                cursor.execute((seed_root / script_name).read_text(), prepare=False)
        connection.commit()
    finally:
        connection.close()
    assert settings.is_persistence_configured


@pytest.fixture
def postgres_dsn() -> Iterator[str]:
    assert _BASE_DSN is not None
    database = f"rc1e_audit_e2e_{uuid4().hex}"
    admin = psycopg.connect(_BASE_DSN, autocommit=True)
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    finally:
        admin.close()

    test_dsn = _database_dsn(_BASE_DSN, database)
    try:
        _initialize_database(test_dsn)
        yield test_dsn
    finally:
        admin = psycopg.connect(_BASE_DSN, autocommit=True)
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
                )
        finally:
            admin.close()


class _AuthenticatedAuditBridge:
    """Serve a signed integration token and forward delivery to the real API."""

    def __init__(
        self,
        audit: TestClient,
        *,
        token: str,
        token_endpoint: str,
        postgres_dsn: str,
    ) -> None:
        self._audit = audit
        self._token = token
        self._token_endpoint = token_endpoint
        self._postgres_dsn = postgres_dsn
        self.persisted_before_response: set[str] = set()

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        if url == self._token_endpoint:
            return httpx.Response(200, json={"access_token": self._token})

        response = self._audit.post("/audit/events", **kwargs)
        if response.status_code == 200:
            event_id = str(kwargs["json"]["event_id"])
            with (
                psycopg.connect(self._postgres_dsn) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT count(*) FROM audit_events WHERE event_id = %s",
                    (event_id,),
                )
                if cursor.fetchone() == (1,):
                    self.persisted_before_response.add(event_id)
        return httpx.Response(response.status_code, json=response.json())

    def close(self) -> None:
        return None


def _application(
    postgres_dsn: str,
) -> tuple[KnowledgeGraphApplication, ContextBoundTransactionProvider]:
    persistence = PersistenceSettings(postgres_dsn=postgres_dsn)
    transactions = ContextBoundTransactionProvider(DirectConnectionProvider(persistence))
    graph_store = PostgresNeo4jGraphStore(transactions)
    return (
        KnowledgeGraphApplication(
            graph_store,
            atomic_mutation_execution=PostgresAtomicMutationExecution(transactions),
        ),
        transactions,
    )


def _command() -> CreateEntityCommand:
    return CreateEntityCommand(
        tenant=_TENANT,
        principal=_PRINCIPAL,
        entity=Entity(
            entity_id="rc1e-entity-1",
            entity_type="person",
            classification=Classification.INTERNAL,
            trust_score=0.9,
            provenance_reference=ProvenanceReference(
                source_principal="rc1e-source",
                event_id="rc1e-source-event-1",
            ),
            owner="rc1e-owner",
            effective_from=_NOW,
        ),
        idempotency_key="rc1e-authoritative-mutation",
        as_of=_NOW,
    )


def _signed_projector_token(private_key: Any, settings: AuditSettings) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": settings.service_token_audience,
            "azp": _PROJECTOR_CLIENT_ID,
            "tenant_id": _TENANT.value,
            "realm_access": {
                "roles": ["service-account", "svc-audit-projector"],
            },
        },
        private_key,
        algorithm="RS256",
    )


def test_mutation_reconciles_through_projector_into_postgres_audit_ledger(
    postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, transactions = _application(postgres_dsn)
    mutation = application.create_entity(_command())
    expected_event_id = f"kg-mutation:{mutation.mutation_id}:0"

    with psycopg.connect(postgres_dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT tenant_id, principal_id, status, graph_revision, "
            "graph_content_hash, audit_intents FROM mutation_ledger "
            "WHERE mutation_id = %s",
            (mutation.mutation_id,),
        )
        ledger_row = cursor.fetchone()
        assert ledger_row is not None
        assert ledger_row[:5] == (
            _TENANT.value,
            str(_PRINCIPAL.principal_id),
            "succeeded",
            mutation.revision_number,
            mutation.content_hash,
        )
        assert ledger_row[5]["intents"][0]["tenant_id"] == _TENANT.value
        cursor.execute(
            "SELECT tenant_id, available_at, attempt_count, delivered_at, claim_owner, "
            "available_at <= clock_timestamp() FROM mutation_dispatch "
            "WHERE mutation_id = %s AND channel = 'audit'",
            (mutation.mutation_id,),
        )
        initial_dispatch = cursor.fetchone()
        assert initial_dispatch is not None
        assert initial_dispatch[0] == _TENANT.value
        assert initial_dispatch[2:] == (0, None, None, True)

    monkeypatch.setenv("EMG_AUDIT_STORE_BACKEND", "postgres")
    monkeypatch.setenv("EMG_AUDIT_DEPLOYMENT_ENVIRONMENT", "test")
    monkeypatch.setenv("EMG_AUDIT_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("EMG_AUDIT_KEYCLOAK_BASE_URL", "http://keycloak.test")
    monkeypatch.setenv("EMG_AUDIT_KEYCLOAK_REALM", "emg-test")
    monkeypatch.setenv(
        "EMG_AUDIT_PROJECTOR_CLIENT_IDS",
        json.dumps([_PROJECTOR_CLIENT_ID]),
    )
    monkeypatch.setenv(
        "EMG_AUDIT_POLICY_CONFIG_PATH",
        str(ROOT / "services/audit/config/policy.example.yaml"),
    )
    audit_settings = AuditSettings()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _signed_projector_token(private_key, audit_settings)

    projector_settings = ProjectorSettings(
        deployment_environment="test",
        postgres_dsn=postgres_dsn,
        keycloak_base_url="http://keycloak.test",
        keycloak_realm="emg-test",
        audit_service_base_url="http://audit.test",
        tenant_credentials_json=json.dumps(
            [
                {
                    "tenant_id": _TENANT.value,
                    "client_id": _PROJECTOR_CLIENT_ID,
                    "client_secret": "rc1e-integration-secret",
                }
            ]
        ),
        worker_id="rc1e-authoritative-worker",
        batch_size=1,
        poll_interval_seconds=0.01,
        telemetry_interval_seconds=30,
    )
    credential = projector_settings.tenant_credentials[0]
    assert credential.tenant_id == _TENANT.value
    audit_app = create_app()
    audit_app.dependency_overrides[service_token_validator_dependency] = lambda: (
        ServiceTokenValidator(
            audit_settings,
            signing_key_resolver=lambda supplied: private_key.public_key(),
        )
    )

    with TestClient(audit_app) as audit_client:
        bridge = _AuthenticatedAuditBridge(
            audit_client,
            token=token,
            token_endpoint=projector_settings.token_endpoint,
            postgres_dsn=postgres_dsn,
        )
        delivery = AuditDeliveryClient(projector_settings, client=cast(Any, bridge))
        worker = AuditProjectorWorker(projector_settings, transactions, delivery)

        assert worker.run_cycle() is True
        assert bridge.persisted_before_response == {expected_event_id}

        with transactions.transaction() as connection:
            ledger = PostgresMutationRepository(connection).get_ledger(
                tenant_id=_TENANT.value,
                mutation_id=mutation.mutation_id,
            )
        assert ledger is not None
        projected = project_audit_events(ledger)
        assert [event.event_id for event in projected] == [expected_event_id]

        delivery.deliver(
            projected,
            credential=credential,
            shutdown_requested=lambda: False,
        )

    with psycopg.connect(postgres_dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT event_id, source_principal, tenant_id, actor, action, "
            "correlation_id, resource_type, resource_id, classification, "
            "source_system, metadata FROM audit_events WHERE event_id = %s",
            (expected_event_id,),
        )
        audit_rows = cursor.fetchall()
        assert len(audit_rows) == 1
        audit_row = audit_rows[0]
        assert audit_row[:10] == (
            expected_event_id,
            _PROJECTOR_CLIENT_ID,
            _TENANT.value,
            str(_PRINCIPAL.principal_id),
            "create",
            None,
            "knowledge-graph.entity",
            "rc1e-entity-1",
            Classification.INTERNAL.value,
            "knowledge-graph",
        )
        assert audit_row[10]["revision_number"] == str(mutation.revision_number)
        assert audit_row[10]["content_hash"] == mutation.content_hash
        cursor.execute(
            "SELECT available_at, attempt_count, delivered_at, claim_owner, "
            "claim_expires_at FROM mutation_dispatch "
            "WHERE mutation_id = %s AND channel = 'audit'",
            (mutation.mutation_id,),
        )
        completed_dispatch = cursor.fetchone()
        assert completed_dispatch is not None
        assert completed_dispatch[0] == initial_dispatch[1]
        assert completed_dispatch[1] == 1
        assert completed_dispatch[2] is not None
        assert completed_dispatch[3:] == (None, None)
