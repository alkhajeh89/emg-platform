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

from functools import lru_cache
from typing import Annotated

from emg_auth_client import PolicyEnforcementPoint
from emg_knowledge_graph import (
    IResourceMetadataReader,
    KnowledgeGraphApplication,
    MutationAuthorizationPreflight,
    SchemaNegotiationError,
    SchemaNegotiationRequest,
    SchemaNegotiationResult,
    SchemaNegotiator,
)
from emg_knowledge_graph_infrastructure import GraphResourceMetadataReader
from emg_platform_core import PrincipalRef
from emg_policy_engine import LocalPolicyEnforcementPoint, load_policy_config
from fastapi import Depends

from .authn import TenantContextDep
from .config import Settings, get_settings
from .mutation_authorization import PepMutationAuthorizationEvaluator
from .mutation_preparation import MutationRequestPreparer
from .store import AtomicMutationExecutionDep, GraphStoreDep


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
    config = load_policy_config(settings.policy_config_path)
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


@lru_cache
def _schema_negotiator_singleton() -> SchemaNegotiator:
    return _UnconfiguredSchemaNegotiator()


def schema_negotiator_dependency() -> SchemaNegotiator:
    return _schema_negotiator_singleton()


SchemaNegotiatorDep = Annotated[SchemaNegotiator, Depends(schema_negotiator_dependency)]


def mutation_request_preparer_dependency(
    schema_negotiator: SchemaNegotiatorDep,
) -> MutationRequestPreparer:
    return MutationRequestPreparer(schema_negotiator)


MutationRequestPreparerDep = Annotated[
    MutationRequestPreparer, Depends(mutation_request_preparer_dependency)
]


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
