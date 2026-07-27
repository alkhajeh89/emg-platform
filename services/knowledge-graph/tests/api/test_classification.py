"""Tests for the Group D8 HTTP-layer classification-enforcement module
(ADR-026 Revision 2 §8.2, §8.5, §8.6).

Every test here exercises `emg_knowledge_graph_api.classification` against a
real `LocalPolicyEnforcementPoint`/`PolicyEngine` (never a mock or a
hand-rolled fake `Decision`), per this repository's established convention
(`test_authorization.py`, `test_authz_scenarios.py`) of proving
authorization behavior against the real evaluator. `required_resource_attributes`
is the *same* mechanism ADR-026 Revision 2 Amendment 1 added to the shared
Policy Engine — this module introduces no comparator of its own, so these
tests are as much a check that `classification.py` builds the right
`AuthorizationRequest` as they are a check of any local logic.

This module is not yet wired into any route (that is Group D9 / Batch 2),
so these are direct unit tests of the pure functions, not HTTP tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from emg_common_types import Classification
from emg_knowledge_graph.results import (
    EdgeDetails,
    EntityDetails,
    EntityHistoryResult,
    EntitySummary,
    NeighborResult,
    PathResult,
    QueryRevisionContext,
)
from emg_knowledge_graph_api.authn import ServicePrincipal
from emg_knowledge_graph_api.classification import (
    filter_edges,
    filter_entities,
    filter_neighbors,
    gate_edge,
    gate_entity,
    gate_history_fact,
    gate_path,
)
from emg_memory_graph import (
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    Metadata,
    TemporalFact,
    TemporalValidity,
)
from emg_policy_engine import LocalPolicyEnforcementPoint
from emg_policy_engine.rules import PolicyConfig, PolicyRule

_RESOURCE_TYPE = "knowledge-graph.entity"
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

# A caller cleared for UNCLASSIFIED/INTERNAL only -- CONFIDENTIAL/SECRET are
# denied by the real Policy Engine's default-deny (no matching allow rule),
# never by a local ordinal comparison.
_CLEARED_ROLE = "clearance-internal"


def _pep(*, cleared: tuple[str, ...] = ("UNCLASSIFIED", "INTERNAL")) -> LocalPolicyEnforcementPoint:
    config = PolicyConfig(
        rules=[
            PolicyRule(
                rule_id="internal-clearance",
                resource_type=_RESOURCE_TYPE,
                action="read",
                effect="allow",
                required_roles=[_CLEARED_ROLE],
                required_resource_attributes={"classification": list(cleared)},
            )
        ]
    )
    return LocalPolicyEnforcementPoint(config)


def _empty_pep() -> LocalPolicyEnforcementPoint:
    return LocalPolicyEnforcementPoint(PolicyConfig(rules=[]))


def _cleared_principal() -> ServicePrincipal:
    return ServicePrincipal(client_id="svc-cleared", roles=(_CLEARED_ROLE,))


def _uncleared_principal() -> ServicePrincipal:
    return ServicePrincipal(client_id="svc-uncleared", roles=("some-other-role",))


def _entity(node_id: str, classification: Classification) -> EntitySummary:
    return EntitySummary(
        node_id=node_id,
        node_type="person",
        label=node_id,
        confidence=0.9,
        classification=classification,
        created_at=_T0,
        updated_at=_T0,
    )


def _edge(edge_id: str, classification: Classification) -> EdgeDetails:
    return EdgeDetails(
        edge_id=edge_id,
        edge_type="owns",
        source_id="a",
        target_id="b",
        direction=EdgeDirection.DIRECTED,
        confidence=0.9,
        classification=classification,
        validity=TemporalValidity(valid_from=_T0, valid_until=None),
        created_at=_T0,
        updated_at=_T0,
        evidence=(
            EvidenceRef.create(
                source=EvidenceSource.MANUAL_ENTRY,
                locator=edge_id,
                source_principal="tester",
                captured_at=_T0,
            ),
        ),
    )


def _neighbor(
    entity_classification: Classification, edge_classification: Classification
) -> NeighborResult:
    return NeighborResult(
        entity=_entity("neighbor-1", entity_classification),
        via_edge_id="rel-1",
        edge_type="owns",
        confidence=0.9,
        direction=EdgeDirection.DIRECTED,
        edge_classification=edge_classification,
    )


def _revision_context() -> QueryRevisionContext:
    return QueryRevisionContext(revision_number=1, committed_at=_T0, is_current_head=True)


def _entity_details(node_id: str, classification: Classification) -> EntityDetails:
    return EntityDetails(
        summary=_entity(node_id, classification),
        source="tester",
        aliases=(),
        evidence=(),
        histories=(),
        metadata=Metadata(),
    )


# --- filter_entities ------------------------------------------------------


def test_filter_entities_prunes_over_clearance_items() -> None:
    items = (
        _entity("e-internal", Classification.INTERNAL),
        _entity("e-secret", Classification.SECRET),
        _entity("e-unclassified", Classification.UNCLASSIFIED),
    )
    result = filter_entities(_pep(), _cleared_principal(), _RESOURCE_TYPE, items)
    assert [item.node_id for item in result] == ["e-internal", "e-unclassified"]


def test_filter_entities_preserves_order() -> None:
    items = (
        _entity("e-1", Classification.UNCLASSIFIED),
        _entity("e-2", Classification.UNCLASSIFIED),
        _entity("e-3", Classification.UNCLASSIFIED),
    )
    result = filter_entities(_pep(), _cleared_principal(), _RESOURCE_TYPE, items)
    assert [item.node_id for item in result] == ["e-1", "e-2", "e-3"]


def test_filter_entities_empty_policy_denies_everything() -> None:
    items = (_entity("e-1", Classification.UNCLASSIFIED),)
    result = filter_entities(_empty_pep(), _cleared_principal(), _RESOURCE_TYPE, items)
    assert result == ()


def test_filter_entities_uncleared_principal_gets_nothing() -> None:
    items = (_entity("e-1", Classification.UNCLASSIFIED),)
    result = filter_entities(_pep(), _uncleared_principal(), _RESOURCE_TYPE, items)
    assert result == ()


# --- filter_edges ----------------------------------------------------------


def test_filter_edges_prunes_over_clearance_items() -> None:
    items = (
        _edge("edge-internal", Classification.INTERNAL),
        _edge("edge-confidential", Classification.CONFIDENTIAL),
    )
    result = filter_edges(_pep(), _cleared_principal(), _RESOURCE_TYPE, items)
    assert [item.edge_id for item in result] == ["edge-internal"]


# --- filter_neighbors -------------------------------------------------------


def test_filter_neighbors_requires_both_entity_and_edge_cleared() -> None:
    allowed = _neighbor(Classification.INTERNAL, Classification.UNCLASSIFIED)
    entity_denied = _neighbor(Classification.SECRET, Classification.UNCLASSIFIED)
    edge_denied = _neighbor(Classification.INTERNAL, Classification.CONFIDENTIAL)

    result = filter_neighbors(
        _pep(), _cleared_principal(), _RESOURCE_TYPE, (allowed, entity_denied, edge_denied)
    )

    assert result == (allowed,)


# --- gate_entity / gate_edge (single-object gates) --------------------------


def test_gate_entity_returns_item_when_cleared() -> None:
    item = _entity_details("e-1", Classification.INTERNAL)
    assert gate_entity(_pep(), _cleared_principal(), _RESOURCE_TYPE, item) is item


def test_gate_entity_returns_none_when_not_cleared() -> None:
    item = _entity_details("e-1", Classification.SECRET)
    assert gate_entity(_pep(), _cleared_principal(), _RESOURCE_TYPE, item) is None


def test_gate_edge_returns_item_when_cleared() -> None:
    item = _edge("edge-1", Classification.UNCLASSIFIED)
    assert gate_edge(_pep(), _cleared_principal(), _RESOURCE_TYPE, item) is item


def test_gate_edge_returns_none_when_not_cleared() -> None:
    item = _edge("edge-1", Classification.CONFIDENTIAL)
    assert gate_edge(_pep(), _cleared_principal(), _RESOURCE_TYPE, item) is None


# --- gate_path (ADR-026 Revision 2 §8.6: no alternate-path recomputation) ---


def test_gate_path_returns_unchanged_when_every_node_and_edge_cleared() -> None:
    path = PathResult(
        node_ids=("n1", "n2"),
        edge_ids=("e1",),
        length=1,
        found=True,
        node_classifications=(Classification.UNCLASSIFIED, Classification.INTERNAL),
        edge_classifications=(Classification.INTERNAL,),
    )
    assert gate_path(_pep(), _cleared_principal(), _RESOURCE_TYPE, path) is path


def test_gate_path_becomes_not_found_when_one_node_exceeds_clearance() -> None:
    path = PathResult(
        node_ids=("n1", "n2"),
        edge_ids=("e1",),
        length=1,
        found=True,
        node_classifications=(Classification.UNCLASSIFIED, Classification.SECRET),
        edge_classifications=(Classification.INTERNAL,),
    )
    result = gate_path(_pep(), _cleared_principal(), _RESOURCE_TYPE, path)
    assert result.found is False
    assert result.node_ids == ()
    assert result.edge_ids == ()
    assert result.node_classifications == ()
    assert result.edge_classifications == ()


def test_gate_path_becomes_not_found_when_one_edge_exceeds_clearance() -> None:
    path = PathResult(
        node_ids=("n1", "n2"),
        edge_ids=("e1",),
        length=1,
        found=True,
        node_classifications=(Classification.UNCLASSIFIED, Classification.INTERNAL),
        edge_classifications=(Classification.SECRET,),
    )
    result = gate_path(_pep(), _cleared_principal(), _RESOURCE_TYPE, path)
    assert result.found is False


def test_gate_path_already_not_found_is_returned_unchanged() -> None:
    path = PathResult(
        node_ids=(),
        edge_ids=(),
        length=0,
        found=False,
        node_classifications=(),
        edge_classifications=(),
    )
    assert gate_path(_pep(), _cleared_principal(), _RESOURCE_TYPE, path) is path


# --- gate_history_fact (ADR-026 Revision 2 §8.5: uniform denial) ------------


def test_gate_history_fact_returns_unchanged_when_cleared() -> None:
    fact = TemporalFact(
        value="alice",
        validity=TemporalValidity(valid_from=_T0, valid_until=None),
        evidence=(
            EvidenceRef.create(
                source=EvidenceSource.MANUAL_ENTRY,
                locator="owner-alice",
                source_principal="tester",
                captured_at=_T0,
            ),
        ),
        recorded_at=_T0,
    )
    result = EntityHistoryResult(
        item=fact, revision_context=_revision_context(), classification=Classification.INTERNAL
    )
    gated = gate_history_fact(_pep(), _cleared_principal(), _RESOURCE_TYPE, result)
    assert gated is result


def test_gate_history_fact_replaces_item_with_none_when_not_cleared() -> None:
    result = EntityHistoryResult(
        item=None, revision_context=_revision_context(), classification=Classification.SECRET
    )
    gated = gate_history_fact(_pep(), _cleared_principal(), _RESOURCE_TYPE, result)
    assert gated.item is None
    assert gated.revision_context == result.revision_context
    # Batch 2 remediation: the true classification must not survive past the
    # authorization decision -- it is never preserved on a denied result.
    assert gated.classification is None


def test_gate_history_fact_redacts_classification_when_not_cleared() -> None:
    """The denied branch must not merely hide `item` -- it must also never
    hand back the real classification value it used to make that decision
    (the audited leak this remediation fixes)."""
    fact = TemporalFact(
        value="alice",
        validity=TemporalValidity(valid_from=_T0, valid_until=None),
        evidence=(
            EvidenceRef.create(
                source=EvidenceSource.MANUAL_ENTRY,
                locator="owner-alice",
                source_principal="tester",
                captured_at=_T0,
            ),
        ),
        recorded_at=_T0,
    )
    result = EntityHistoryResult(
        item=fact, revision_context=_revision_context(), classification=Classification.SECRET
    )
    gated = gate_history_fact(_pep(), _cleared_principal(), _RESOURCE_TYPE, result)
    assert gated.item is None
    assert gated.classification is None


def test_gate_history_fact_is_idempotent_on_an_already_redacted_result() -> None:
    """Re-gating an already-denied (classification=None) result is a safe
    no-op -- it must never attempt to re-derive or re-expose a value."""
    already_denied = EntityHistoryResult(
        item=None, revision_context=_revision_context(), classification=None
    )
    gated = gate_history_fact(_pep(), _cleared_principal(), _RESOURCE_TYPE, already_denied)
    assert gated is already_denied


def test_gate_history_fact_denied_preserves_revision_context() -> None:
    fact = TemporalFact(
        value="alice",
        validity=TemporalValidity(valid_from=_T0, valid_until=None),
        evidence=(
            EvidenceRef.create(
                source=EvidenceSource.MANUAL_ENTRY,
                locator="owner-alice",
                source_principal="tester",
                captured_at=_T0,
            ),
        ),
        recorded_at=_T0,
    )
    context = _revision_context()
    result = EntityHistoryResult(
        item=fact, revision_context=context, classification=Classification.CONFIDENTIAL
    )
    gated = gate_history_fact(_pep(), _cleared_principal(), _RESOURCE_TYPE, result)
    assert gated.item is None
    assert gated.revision_context is context


# --- default action reuse ---------------------------------------------------


def test_default_action_is_read_matching_authorization_module() -> None:
    from emg_knowledge_graph_api import authorization, classification

    # classification.py imports (not redeclares) authorization.py's constant.
    assert classification.DEFAULT_ACTION is authorization.DEFAULT_ACTION
    assert authorization.DEFAULT_ACTION == "read"
