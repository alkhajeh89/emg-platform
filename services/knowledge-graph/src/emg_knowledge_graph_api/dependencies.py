"""`KnowledgeGraphApplication` wiring for the Query API, plus (ADR-025 Group
C3) the Policy Enforcement Point dependency used for authorization.

Routes never instantiate `KnowledgeGraphApplication` or a `GraphStore`
themselves — they depend on `KnowledgeGraphApplicationDep`, which composes
the already-wired `GraphStoreDep` (see `store.py`). Both constructor
arguments (`graph_store`, `revision_reader`) receive the same object, since
every backend this service supports implements both Protocols (exactly the
existing `emg_knowledge_graph` test convention — see
`test_query_engine_service.py`'s `_app()` helper).

`PolicyEnforcementPointDep` mirrors `services/identity/src/emg_identity/
dependencies.py`'s `policy_enforcement_point_dependency`/`PolicyEnforcementPointDep`
field-for-field: same `lru_cache`d singleton shape, same
`emg_policy_engine.load_policy_config` + `LocalPolicyEnforcementPoint`
construction, same safe-default behavior (a missing policy file yields an
empty, default-deny `PolicyConfig` — see `config.py`'s `policy_config_path`
docstring). No new authorization framework is introduced; this is the same
Policy Enforcement Point contract (`emg_auth_client.PolicyEnforcementPoint`)
and the same evaluator (`emg_policy_engine.LocalPolicyEnforcementPoint`)
`services/identity` already uses — this service is simply the first to
enforce the resulting `Decision` rather than only introspect it (see
`authorization.py`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, TypeVar

from emg_auth_client import PolicyEnforcementPoint
from emg_knowledge_graph import (
    CompatibilityAdapterRegistry,
    IResourceMetadataReader,
    KnowledgeGraphApplication,
    MutationAuthorizationPreflight,
    SchemaNegotiationError,
    SchemaNegotiationRequest,
    SchemaNegotiationResult,
    SchemaNegotiator,
)
from emg_knowledge_graph_infrastructure import (
    CompatibilityNormalizerRegistration,
    GraphResourceMetadataReader,
    RegistryBackedCompatibilityAdapterRegistry,
    RegistryBackedSchemaNegotiator,
    SchemaCatalogValidationError,
    load_schema_catalog,
    validate_schema_boot_gate,
)
from emg_platform_core import PrincipalRef
from emg_policy_engine import LocalPolicyEnforcementPoint, load_validated_policy_config
from fastapi import Depends

from .authn import TenantContextDep
from .config import Settings, get_settings, validate_secure_transport
from .mutation_authorization import PepMutationAuthorizationEvaluator
from .mutation_preparation import MutationRequestPreparer
from .store import AtomicMutationExecutionDep, GraphStoreDep

_RequestT = TypeVar("_RequestT")
_NON_PRODUCTION_ENVIRONMENTS = frozenset({"development", "test"})

# ADR-033 registrations are a static, reviewable composition artifact. Phase 2
# ships no production normalizer. A future reviewed source change adds concrete
# registrations here; runtime discovery and environment-selected code are absent.
_SCHEMA_NORMALIZER_REGISTRATIONS: tuple[CompatibilityNormalizerRegistration, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemaRuntimeHealth:
    configured: bool
    placeholder_active: bool
    canonical_version: str | None
    catalog_generation: str | None


def knowledge_graph_application_dependency(
    graph_store: GraphStoreDep,
) -> KnowledgeGraphApplication:
    return KnowledgeGraphApplication(graph_store=graph_store, revision_reader=graph_store)


KnowledgeGraphApplicationDep = Annotated[
    KnowledgeGraphApplication, Depends(knowledge_graph_application_dependency)
]


@lru_cache
def _settings_singleton() -> Settings:
    return get_settings()


@lru_cache
def _policy_enforcement_point_singleton() -> PolicyEnforcementPoint:
    settings = _settings_singleton()
    config = load_validated_policy_config(settings.policy_config_path)
    return LocalPolicyEnforcementPoint(config)


def policy_enforcement_point_dependency() -> PolicyEnforcementPoint:
    return _policy_enforcement_point_singleton()


PolicyEnforcementPointDep = Annotated[
    PolicyEnforcementPoint, Depends(policy_enforcement_point_dependency)
]


class _UnconfiguredSchemaNegotiator:
    """Fail closed until the authoritative ADR-032 registry adapter is injected."""

    def negotiate(self, request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        raise SchemaNegotiationError(
            f"no authoritative schema registry is configured for {request.preferred_version!r}",
            failure_code="NEGOTIATION_UNCONFIGURED",
        )

    def normalize(
        self,
        request: _RequestT,
        *,
        source_version: str,
        target_version: str | None = None,
    ) -> _RequestT:
        raise SchemaNegotiationError(
            f"no authoritative schema registry is configured for {source_version!r}",
            failure_code="NEGOTIATION_UNCONFIGURED",
        )


@lru_cache
def _schema_components_singleton(
    catalog_path: str | None,
    allow_unconfigured: bool,
    deployment_environment: str | None,
) -> tuple[SchemaNegotiator, CompatibilityAdapterRegistry]:
    if allow_unconfigured and deployment_environment not in _NON_PRODUCTION_ENVIRONMENTS:
        environment = deployment_environment or "missing"
        raise SchemaCatalogValidationError(
            "unconfigured schema negotiation requires an explicit recognized "
            f"non-production environment; received {environment!r}"
        )
    if catalog_path is None:
        if allow_unconfigured:
            placeholder = _UnconfiguredSchemaNegotiator()
            return placeholder, placeholder
        raise SchemaCatalogValidationError("schema catalog path is not configured")

    catalog = load_schema_catalog(_read_schema_catalog(Path(catalog_path)))
    adapters = RegistryBackedCompatibilityAdapterRegistry(
        catalog,
        _SCHEMA_NORMALIZER_REGISTRATIONS,
    )
    validate_schema_boot_gate(catalog, adapters)
    return RegistryBackedSchemaNegotiator(catalog), adapters


def _read_schema_catalog(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SchemaCatalogValidationError(f"failed to read schema catalog {path}: {exc}") from exc


def _schema_components() -> tuple[SchemaNegotiator, CompatibilityAdapterRegistry]:
    settings = _settings_singleton()
    return _schema_components_singleton(
        None if settings.schema_catalog_path is None else str(settings.schema_catalog_path),
        settings.allow_unconfigured_schema_negotiation,
        settings.deployment_environment,
    )


def schema_negotiator_dependency() -> SchemaNegotiator:
    return _schema_components()[0]


SchemaNegotiatorDep = Annotated[SchemaNegotiator, Depends(schema_negotiator_dependency)]


def compatibility_adapter_registry_dependency() -> CompatibilityAdapterRegistry:
    return _schema_components()[1]


CompatibilityAdapterRegistryDep = Annotated[
    CompatibilityAdapterRegistry,
    Depends(compatibility_adapter_registry_dependency),
]


def schema_runtime_health_dependency() -> SchemaRuntimeHealth:
    negotiator, adapters = _schema_components()
    if isinstance(adapters, RegistryBackedCompatibilityAdapterRegistry):
        return SchemaRuntimeHealth(
            configured=True,
            placeholder_active=False,
            canonical_version=adapters.catalog.canonical_version,
            catalog_generation=adapters.catalog.generation,
        )
    assert isinstance(negotiator, _UnconfiguredSchemaNegotiator)
    return SchemaRuntimeHealth(
        configured=False,
        placeholder_active=True,
        canonical_version=None,
        catalog_generation=None,
    )


SchemaRuntimeHealthDep = Annotated[
    SchemaRuntimeHealth,
    Depends(schema_runtime_health_dependency),
]


def mutation_request_preparer_dependency(
    schema_negotiator: SchemaNegotiatorDep,
    compatibility_adapters: CompatibilityAdapterRegistryDep,
) -> MutationRequestPreparer:
    return MutationRequestPreparer(schema_negotiator, compatibility_adapters)


MutationRequestPreparerDep = Annotated[
    MutationRequestPreparer, Depends(mutation_request_preparer_dependency)
]


def validate_schema_runtime_configuration() -> None:
    """Enforce production safety, policy validation, and the schema boot gate."""

    settings = _settings_singleton()
    if settings.deployment_environment == "production" and settings.store_backend == "memory":
        raise RuntimeError(
            "knowledge-graph cannot start in production with the in-memory store backend"
        )
    if (
        settings.deployment_environment == "production"
        and settings.store_backend == "postgres"
        and settings.postgres_dsn == settings.migration_postgres_dsn
    ):
        raise RuntimeError(
            "knowledge-graph production runtime and migration database credentials "
            "must be distinct"
        )
    validate_secure_transport(settings)
    _policy_enforcement_point_singleton()
    _schema_components()


def mutation_principal_ref_dependency(caller: TenantContextDep) -> PrincipalRef:
    """Adapt the authenticated transport identity to the application contract."""

    return PrincipalRef.service(caller.principal.client_id)


MutationPrincipalRefDep = Annotated[PrincipalRef, Depends(mutation_principal_ref_dependency)]


def resource_metadata_reader_dependency(
    graph_store: GraphStoreDep,
) -> IResourceMetadataReader:
    return GraphResourceMetadataReader(graph_store)


ResourceMetadataReaderDep = Annotated[
    IResourceMetadataReader, Depends(resource_metadata_reader_dependency)
]


def mutation_authorization_preflight_dependency(
    metadata_reader: ResourceMetadataReaderDep,
    pep: PolicyEnforcementPointDep,
    caller: TenantContextDep,
) -> MutationAuthorizationPreflight:
    return MutationAuthorizationPreflight(
        metadata_reader,
        PepMutationAuthorizationEvaluator(pep, caller.principal),
    )


MutationAuthorizationPreflightDep = Annotated[
    MutationAuthorizationPreflight,
    Depends(mutation_authorization_preflight_dependency),
]


def mutation_knowledge_graph_application_dependency(
    graph_store: GraphStoreDep,
    atomic_mutations: AtomicMutationExecutionDep,
    preflight: MutationAuthorizationPreflightDep,
) -> KnowledgeGraphApplication:
    return KnowledgeGraphApplication(
        graph_store=graph_store,
        revision_reader=graph_store,
        mutation_authorization_hook=preflight,
        atomic_mutation_execution=atomic_mutations,
    )


MutationKnowledgeGraphApplicationDep = Annotated[
    KnowledgeGraphApplication,
    Depends(mutation_knowledge_graph_application_dependency),
]
