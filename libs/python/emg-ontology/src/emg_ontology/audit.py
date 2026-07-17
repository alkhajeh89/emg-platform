"""Graph-mutation audit contract (FEAT-05-1 — definition only).

Sprint 9 has **no write service**, so nothing here emits an audit event. This
module only *defines the contract* the future ingestion/write path (FEAT-05-2)
will use when it records graph mutations into the completed Module 6 Audit
Platform: the mutation action names, the target module tag, and a small helper
that shapes the metadata a producer would attach. Live delivery, the
`emg-audit-client` wiring, correlation propagation at the HTTP boundary, and any
"fail-closed on degraded audit" decision belong to FEAT-05-2.

No Module 6 code or record is touched by importing or using this module.
"""

from __future__ import annotations

from typing import Literal

# The module tag a knowledge-graph audit event would carry (Module 6 `module`
# field). Kept as a constant so the future write path and its tests agree.
AUDIT_MODULE = "knowledge-graph"

# The graph-mutation actions that MUST produce an audit event once a write path
# exists. Reads are not audited (consistent with the Module 6 posture).
GraphMutationAction = Literal[
    "entity.created",
    "entity.superseded",
    "relationship.created",
    "relationship.superseded",
]

ENTITY_CREATED: GraphMutationAction = "entity.created"
ENTITY_SUPERSEDED: GraphMutationAction = "entity.superseded"
RELATIONSHIP_CREATED: GraphMutationAction = "relationship.created"
RELATIONSHIP_SUPERSEDED: GraphMutationAction = "relationship.superseded"

GRAPH_MUTATION_ACTIONS: tuple[GraphMutationAction, ...] = (
    ENTITY_CREATED,
    ENTITY_SUPERSEDED,
    RELATIONSHIP_CREATED,
    RELATIONSHIP_SUPERSEDED,
)


def mutation_audit_metadata(
    *,
    action: GraphMutationAction,
    subject_id: str,
    subject_type: str,
    schema_version: int,
) -> dict[str, str]:
    """Shape the (non-sensitive) metadata a future graph write would attach to
    its audit event. Deliberately carries identifiers and types only — never
    entity attribute *content* — so no classified payload is smuggled into the
    audit metadata. Pure; performs no I/O and emits nothing."""
    return {
        "graph_action": action,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "ontology_schema_version": str(schema_version),
    }
