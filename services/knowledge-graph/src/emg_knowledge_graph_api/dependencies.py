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
from emg_knowledge_graph import KnowledgeGraphApplication
from emg_policy_engine import LocalPolicyEnforcementPoint, load_policy_config
from fastapi import Depends

from .config import Settings, get_settings
from .store import GraphStoreDep


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
