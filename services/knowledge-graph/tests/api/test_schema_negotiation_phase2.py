"""Focused ADR-033 Revision 2 Phase 2 pipeline and composition tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from emg_knowledge_graph import SchemaNegotiationError, SchemaNegotiationRequest
from emg_knowledge_graph_api import dependencies
from emg_knowledge_graph_api.main import create_app
from emg_knowledge_graph_api.mutation_mapping import MutationRequest
from emg_knowledge_graph_api.mutation_preparation import MutationRequestPreparer
from emg_knowledge_graph_api.mutation_schemas import ReplaceEntityRequest
from emg_knowledge_graph_infrastructure import (
    CompatibilityNormalizerRegistration,
    RegistryBackedCompatibilityAdapterRegistry,
    RegistryBackedSchemaNegotiator,
    SchemaBootGateError,
    SchemaCatalog,
    SchemaCatalogEntry,
    SchemaCompatibility,
    SchemaLifecycleState,
    validate_schema_boot_gate,
)
from emg_platform_core import PrincipalRef, TenantId
from fastapi.testclient import TestClient

NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)
LATER = datetime(2027, 1, 30, tzinfo=timezone.utc)
TENANT = TenantId.of("schema-phase2")
PRINCIPAL = PrincipalRef.service("schema-phase2-writer")


def _request(label: str = "Legacy Label") -> ReplaceEntityRequest:
    return ReplaceEntityRequest.model_validate(
        {
            "replacement": {
                "node_id": "entity-1",
                "node_type": "person",
                "label": label,
                "created_at": NOW,
                "updated_at": NOW,
                "source": "schema-phase2-writer",
                "confidence": 0.9,
                "classification": "INTERNAL",
                "owner": "schema-phase2-writer",
                "evidence": [
                    {
                        "evidence_id": "evidence-1",
                        "source": "manual_entry",
                        "locator": "case-1",
                        "source_principal": "schema-phase2-writer",
                        "captured_at": NOW,
                    }
                ],
            },
            "action": "update",
            "as_of": NOW,
        }
    )


def _catalog(
    version: str,
    compatibility: SchemaCompatibility,
    *,
    state: SchemaLifecycleState = SchemaLifecycleState.PUBLISHED,
    normalization_required: bool = False,
    normalizer_ids: tuple[str, ...] = (),
) -> SchemaCatalog:
    lifecycle = (
        {"deprecated_at": NOW, "retirement_at": LATER}
        if state is not SchemaLifecycleState.PUBLISHED
        else {}
    )
    return SchemaCatalog(
        generation="phase2-tests",
        canonical_version="2.1.0",
        versions=(
            SchemaCatalogEntry(
                version="2.1.0",
                state=SchemaLifecycleState.PUBLISHED,
                compatibility=SchemaCompatibility.STRICT,
            ),
            SchemaCatalogEntry(
                version=version,
                state=state,
                compatibility=compatibility,
                normalization_required=normalization_required,
                normalizer_ids=normalizer_ids,
                **lifecycle,
            ),
        ),
    )


class _CompatibilityAdapterSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[MutationRequest, str, str | None]] = []

    def normalize(
        self,
        request: MutationRequest,
        *,
        source_version: str,
        target_version: str | None = None,
    ) -> MutationRequest:
        self.calls.append((request, source_version, target_version))
        return request


@pytest.mark.parametrize(
    ("version", "compatibility"),
    [
        ("2.1.0", SchemaCompatibility.STRICT),
        ("2.0.0", SchemaCompatibility.BACKWARD),
    ],
)
def test_strict_and_backward_requests_use_identity_normalization(
    version: str,
    compatibility: SchemaCompatibility,
) -> None:
    catalog = (
        SchemaCatalog(
            generation="phase2-tests",
            canonical_version="2.1.0",
            versions=(
                SchemaCatalogEntry(
                    version="2.1.0",
                    state=SchemaLifecycleState.PUBLISHED,
                    compatibility=SchemaCompatibility.STRICT,
                ),
            ),
        )
        if version == "2.1.0"
        else _catalog(version, compatibility)
    )
    adapters = _CompatibilityAdapterSpy()
    preparer = MutationRequestPreparer(
        RegistryBackedSchemaNegotiator(catalog),
        adapters,
    )
    request = _request()

    prepared = preparer.prepare(
        request,
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key=f"phase2-{version}",
        preferred_schema_version=version,
    )

    assert adapters.calls == [(request, version, None)]
    assert prepared.command.replacement.label == "Legacy Label"
    assert prepared.effective_schema_version == version


def test_normalization_runs_once_and_only_canonical_dto_reaches_command_builder() -> None:
    calls: list[ReplaceEntityRequest] = []

    def normalize(value: object) -> object:
        assert isinstance(value, ReplaceEntityRequest)
        calls.append(value)
        return value.model_copy(
            update={
                "replacement": value.replacement.model_copy(update={"label": "Canonical Label"})
            }
        )

    catalog = _catalog(
        "1.2.0",
        SchemaCompatibility.NORMALIZATION_REQUIRED,
        normalization_required=True,
        normalizer_ids=("normalize-1.2-to-2.1",),
    )
    adapters = RegistryBackedCompatibilityAdapterRegistry(
        catalog,
        (
            CompatibilityNormalizerRegistration(
                normalizer_id="normalize-1.2-to-2.1",
                source_version="1.2.0",
                target_version="2.1.0",
                written_fields=("replacement.label",),
                normalizer=normalize,
            ),
        ),
    )
    validate_schema_boot_gate(catalog, adapters)
    preparer = MutationRequestPreparer(
        RegistryBackedSchemaNegotiator(catalog),
        adapters,
    )
    legacy_request = _request()

    prepared = preparer.prepare(
        legacy_request,
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="test",
        preferred_schema_version="1.2.0",
    )

    assert calls == [legacy_request]
    assert legacy_request.replacement.label == "Legacy Label"
    assert prepared.command.replacement.label == "Canonical Label"
    assert prepared.effective_schema_version == "1.2.0"
    assert not hasattr(prepared.command, "preferred_schema_version")
    assert not hasattr(prepared.command, "compatibility")
    assert not hasattr(prepared.command, "source_schema")


@pytest.mark.parametrize(
    ("version", "compatibility", "state", "expected_code"),
    [
        (
            "1.0.0",
            SchemaCompatibility.MIGRATION_REQUIRED,
            SchemaLifecycleState.PUBLISHED,
            "INCOMPATIBLE_SCHEMA",
        ),
        (
            "0.8.0",
            SchemaCompatibility.INCOMPATIBLE,
            SchemaLifecycleState.PUBLISHED,
            "INCOMPATIBLE_SCHEMA",
        ),
        (
            "0.7.0",
            SchemaCompatibility.INCOMPATIBLE,
            SchemaLifecycleState.RETIRED,
            "RETIRED_SCHEMA",
        ),
    ],
)
def test_rejected_versions_fail_before_normalization_or_command_construction(
    version: str,
    compatibility: SchemaCompatibility,
    state: SchemaLifecycleState,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = _CompatibilityAdapterSpy()
    preparer = MutationRequestPreparer(
        RegistryBackedSchemaNegotiator(_catalog(version, compatibility, state=state)),
        adapters,
    )
    command_construction_calls = 0

    def reject_command_construction(*args: object, **kwargs: object) -> object:
        nonlocal command_construction_calls
        command_construction_calls += 1
        raise AssertionError("command construction must not run")

    monkeypatch.setattr(
        "emg_knowledge_graph_api.mutation_preparation.map_mutation_request",
        reject_command_construction,
    )

    with pytest.raises(SchemaNegotiationError) as caught:
        preparer.prepare(
            _request(),
            tenant=TENANT,
            principal=PRINCIPAL,
            idempotency_key=f"phase2-rejected-{version}",
            preferred_schema_version=version,
        )

    assert caught.value.failure_code == expected_code
    assert adapters.calls == []
    assert command_construction_calls == 0


def test_runtime_composition_loads_external_catalog_and_passes_boot_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path = tmp_path / "schema-catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "generation": "phase2-composition",
                "canonical_version": "2.1.0",
                "versions": [
                    {
                        "version": "2.1.0",
                        "state": "published",
                        "compatibility": "strict",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH",
        str(catalog_path),
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_DEPLOYMENT_ENVIRONMENT",
        "test",
    )
    dependencies._settings_singleton.cache_clear()
    dependencies._schema_components_singleton.cache_clear()

    try:
        with TestClient(create_app()) as client:
            negotiated = dependencies.schema_negotiator_dependency().negotiate(
                SchemaNegotiationRequest(preferred_version="2.1.0")
            )
            readiness = client.get("/readyz")
    finally:
        dependencies._settings_singleton.cache_clear()
        dependencies._schema_components_singleton.cache_clear()

    assert negotiated.effective_version == "2.1.0"
    assert negotiated.adapter_required is False
    assert readiness.status_code == 200
    assert readiness.json() == {
        "status": "ready",
        "store_backend": "memory",
        "store_available": True,
        "detail": "store reachable",
        "schema_runtime_configured": True,
        "schema_placeholder_active": False,
        "canonical_schema_version": "2.1.0",
        "schema_catalog_generation": "phase2-composition",
    }


def test_normalization_required_catalog_uses_static_real_composition_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path = tmp_path / "normalizing-schema-catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "generation": "phase2-normalizing-composition",
                "canonical_version": "2.1.0",
                "versions": [
                    {
                        "version": "2.1.0",
                        "state": "published",
                        "compatibility": "strict",
                    },
                    {
                        "version": "1.2.0",
                        "state": "published",
                        "compatibility": "normalization_required",
                        "normalization_required": True,
                        "normalizer_ids": ["normalize-1.2-to-2.1"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    calls = 0

    def normalize(value: object) -> object:
        nonlocal calls
        calls += 1
        assert isinstance(value, ReplaceEntityRequest)
        return value.model_copy(
            update={
                "replacement": value.replacement.model_copy(
                    update={"label": "Composition Canonical"}
                )
            }
        )

    monkeypatch.setattr(
        dependencies,
        "_SCHEMA_NORMALIZER_REGISTRATIONS",
        (
            CompatibilityNormalizerRegistration(
                normalizer_id="normalize-1.2-to-2.1",
                source_version="1.2.0",
                target_version="2.1.0",
                written_fields=("replacement.label",),
                normalizer=normalize,
            ),
        ),
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH",
        str(catalog_path),
    )
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_DEPLOYMENT_ENVIRONMENT", "test")
    dependencies._settings_singleton.cache_clear()
    dependencies._schema_components_singleton.cache_clear()

    try:
        preparer = dependencies.mutation_request_preparer_dependency(
            dependencies.schema_negotiator_dependency(),
            dependencies.compatibility_adapter_registry_dependency(),
        )
        prepared = preparer.prepare(
            _request(),
            tenant=TENANT,
            principal=PRINCIPAL,
            idempotency_key="phase2-real-composition-normalization",
            preferred_schema_version="1.2.0",
        )
    finally:
        dependencies._settings_singleton.cache_clear()
        dependencies._schema_components_singleton.cache_clear()

    assert calls == 1
    assert prepared.command.replacement.label == "Composition Canonical"


def test_missing_composition_normalizer_fails_boot_gate(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "missing-normalizer-catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "generation": "phase2-missing-normalizer",
                "canonical_version": "2.1.0",
                "versions": [
                    {
                        "version": "2.1.0",
                        "state": "published",
                        "compatibility": "strict",
                    },
                    {
                        "version": "1.2.0",
                        "state": "published",
                        "compatibility": "normalization_required",
                        "normalization_required": True,
                        "normalizer_ids": ["missing"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    dependencies._schema_components_singleton.cache_clear()

    with pytest.raises(SchemaBootGateError, match="exactly one"):
        dependencies._schema_components_singleton(
            str(catalog_path),
            False,
            "test",
        )


def test_placeholder_health_is_visible_and_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH", raising=False)
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_ALLOW_UNCONFIGURED_SCHEMA_NEGOTIATION",
        "true",
    )
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_DEPLOYMENT_ENVIRONMENT", "test")
    dependencies._settings_singleton.cache_clear()
    dependencies._schema_components_singleton.cache_clear()

    try:
        with TestClient(create_app()) as client:
            response = client.get("/readyz")
    finally:
        dependencies._settings_singleton.cache_clear()
        dependencies._schema_components_singleton.cache_clear()

    assert response.status_code == 200
    assert response.json()["schema_runtime_configured"] is False
    assert response.json()["schema_placeholder_active"] is True
    assert response.json()["canonical_schema_version"] is None
    assert response.json()["schema_catalog_generation"] is None


def test_production_rejects_in_memory_store_before_serving_traffic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path = tmp_path / "production-schema-catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "generation": "production-safety",
                "canonical_version": "2.1.0",
                "versions": [
                    {
                        "version": "2.1.0",
                        "state": "published",
                        "compatibility": "strict",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_STORE_BACKEND", "memory")
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH", str(catalog_path))
    dependencies._settings_singleton.cache_clear()
    dependencies._schema_components_singleton.cache_clear()

    try:
        with (
            pytest.raises(RuntimeError, match="cannot start in production"),
            TestClient(create_app()),
        ):
            pass
    finally:
        dependencies._settings_singleton.cache_clear()
        dependencies._schema_components_singleton.cache_clear()
