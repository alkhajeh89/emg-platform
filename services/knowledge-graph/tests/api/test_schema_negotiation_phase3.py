"""ADR-033 Phase 3 production-catalog and runtime-composition tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    MergeEntitiesCommand,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
    SchemaNegotiationError,
    SchemaNegotiationRequest,
)
from emg_knowledge_graph_api import dependencies
from emg_knowledge_graph_api.main import create_app
from emg_knowledge_graph_api.mutation_mapping import MutationRequest
from emg_knowledge_graph_api.mutation_preparation import MutationRequestPreparer
from emg_knowledge_graph_api.mutation_schemas import (
    CloseRelationshipRequest,
    CreateEntityRequest,
    MergeEntitiesRequest,
    ReplaceEntityRequest,
    ReplaceRelationshipRequest,
)
from emg_knowledge_graph_api.store import graph_store_dependency
from emg_knowledge_graph_infrastructure import (
    RegistryBackedCompatibilityAdapterRegistry,
    SchemaCompatibility,
    SchemaLifecycleState,
    load_schema_catalog,
    schema_registry,
)
from emg_platform_core import InMemoryGraphStore, PrincipalRef, TenantId
from fastapi.testclient import TestClient

CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "schema-catalog.json"
CANONICAL_VERSION = "2.1.0"
CATALOG_GENERATION = "catalog-v2.1.0-gen1"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
TENANT = TenantId.of("schema-phase3")
PRINCIPAL = PrincipalRef.service("schema-phase3-writer")


def _evidence() -> dict[str, object]:
    return {
        "evidence_id": "evidence-1",
        "source": "manual_entry",
        "locator": "case-1",
        "source_principal": "schema-phase3-writer",
        "captured_at": NOW,
    }


def _node() -> dict[str, object]:
    return {
        "node_id": "entity-1",
        "node_type": "person",
        "label": "Entity One",
        "created_at": NOW,
        "updated_at": NOW,
        "source": "schema-phase3-writer",
        "confidence": 0.9,
        "classification": "INTERNAL",
        "owner": "schema-phase3-writer",
        "evidence": [_evidence()],
    }


def _edge() -> dict[str, object]:
    return {
        "edge_id": "relationship-1",
        "edge_type": "owns",
        "source_id": "entity-1",
        "target_id": "entity-2",
        "evidence": [_evidence()],
        "confidence": 0.9,
        "validity": {"valid_from": NOW},
        "created_at": NOW,
        "updated_at": NOW,
        "classification": "INTERNAL",
    }


def _requests() -> tuple[tuple[MutationRequest, type[object]], ...]:
    return (
        (
            CreateEntityRequest.model_validate(
                {
                    "entity": {
                        "entity_id": "entity-1",
                        "entity_type": "person",
                        "classification": "INTERNAL",
                        "trust_score": 0.9,
                        "provenance_reference": {
                            "source_principal": "schema-phase3-writer",
                            "event_id": "event-1",
                        },
                        "effective_from": NOW,
                    },
                    "as_of": NOW,
                }
            ),
            CreateEntityCommand,
        ),
        (
            ReplaceEntityRequest.model_validate(
                {
                    "replacement": _node(),
                    "action": "update",
                    "as_of": NOW,
                }
            ),
            ReplaceEntityCommand,
        ),
        (
            ReplaceRelationshipRequest.model_validate(
                {
                    "replacement": _edge(),
                    "as_of": NOW,
                }
            ),
            ReplaceRelationshipCommand,
        ),
        (
            CloseRelationshipRequest(
                edge_id="relationship-1",
                as_of=NOW,
                reason="relationship ended",
            ),
            CloseRelationshipCommand,
        ),
        (
            MergeEntitiesRequest(
                survivor_id="entity-1",
                source_ids=("entity-2",),
                as_of=NOW,
                reason="duplicate record",
            ),
            MergeEntitiesCommand,
        ),
    )


def _production_components() -> tuple[
    MutationRequestPreparer,
    RegistryBackedCompatibilityAdapterRegistry,
]:
    negotiator, adapters = dependencies._schema_components_singleton(
        str(CATALOG_PATH),
        False,
        "production",
    )
    assert isinstance(adapters, RegistryBackedCompatibilityAdapterRegistry)
    return MutationRequestPreparer(negotiator, adapters), adapters


class _LogSpy:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *, extra: dict[str, str]) -> None:
        self.messages.append(message)


def test_production_catalog_is_the_approved_canonical_only_artifact() -> None:
    catalog = load_schema_catalog(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))

    assert catalog.generation == CATALOG_GENERATION
    assert catalog.canonical_version == CANONICAL_VERSION
    assert len(catalog.versions) == 1
    canonical = catalog.versions[0]
    assert canonical.version == CANONICAL_VERSION
    assert canonical.state is SchemaLifecycleState.PUBLISHED
    assert canonical.compatibility is SchemaCompatibility.STRICT
    assert canonical.normalization_required is False
    assert canonical.normalizer_ids == ()
    assert canonical.deprecated_at is None
    assert canonical.retirement_at is None


@pytest.mark.parametrize(("transport_dto", "command_type"), _requests())
def test_all_mutation_families_negotiate_through_the_production_catalog(
    transport_dto: MutationRequest,
    command_type: type[object],
) -> None:
    dependencies._schema_components_singleton.cache_clear()
    preparer, adapters = _production_components()

    prepared = preparer.prepare(
        transport_dto,
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key=f"phase3-{command_type.__name__}",
        preferred_schema_version=CANONICAL_VERSION,
    )

    assert prepared.effective_schema_version == CANONICAL_VERSION
    assert isinstance(prepared.command, command_type)
    assert adapters.registrations == ()


def test_unknown_version_remains_fail_closed_before_command_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies._schema_components_singleton.cache_clear()
    preparer, _ = _production_components()
    construction_calls = 0

    def observe_construction(*args: object, **kwargs: object) -> object:
        nonlocal construction_calls
        construction_calls += 1
        raise AssertionError("command construction must not run")

    monkeypatch.setattr(
        "emg_knowledge_graph_api.mutation_preparation.map_mutation_request",
        observe_construction,
    )

    with pytest.raises(SchemaNegotiationError) as caught:
        preparer.prepare(
            _requests()[0][0],
            tenant=TENANT,
            principal=PRINCIPAL,
            idempotency_key="phase3-unknown",
            preferred_schema_version="9.9.9",
        )

    assert caught.value.failure_code == "UNKNOWN_SCHEMA"
    assert construction_calls == 0


def test_production_composition_exposes_safe_readiness_metrics_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _LogSpy()
    monkeypatch.setattr(schema_registry, "_log", log)
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH",
        "services/knowledge-graph/config/schema-catalog.json",
    )
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_STORE_BACKEND", "postgres")
    monkeypatch.delenv(
        "EMG_KNOWLEDGE_GRAPH_API_ALLOW_UNCONFIGURED_SCHEMA_NEGOTIATION",
        raising=False,
    )
    dependencies._settings_singleton.cache_clear()
    dependencies._schema_components_singleton.cache_clear()

    try:
        app = create_app()
        app.dependency_overrides[graph_store_dependency] = InMemoryGraphStore
        with TestClient(app) as client:
            negotiated = dependencies.schema_negotiator_dependency().negotiate(
                SchemaNegotiationRequest(preferred_version=CANONICAL_VERSION)
            )
            response = client.get("/readyz")
    finally:
        dependencies._settings_singleton.cache_clear()
        dependencies._schema_components_singleton.cache_clear()

    assert negotiated.effective_version == CANONICAL_VERSION
    assert response.status_code == 200
    assert response.json()["schema_runtime_configured"] is True
    assert response.json()["schema_placeholder_active"] is False
    assert response.json()["canonical_schema_version"] == CANONICAL_VERSION
    assert response.json()["schema_catalog_generation"] == CATALOG_GENERATION

    events = [json.loads(message) for message in log.messages]
    assert any(
        event.get("metric_name") == "schema_catalog_generation_info"
        and event["canonical_version"] == CANONICAL_VERSION
        and event["catalog_generation"] == CATALOG_GENERATION
        for event in events
    )
    assert any(
        event["event"] == "schema_negotiation"
        and event["effective_version"] == CANONICAL_VERSION
        and event["catalog_generation"] == CATALOG_GENERATION
        for event in events
    )
    serialized = "\n".join(log.messages)
    assert str(CATALOG_PATH) not in serialized
    assert str(TENANT) not in serialized
    assert str(PRINCIPAL) not in serialized
