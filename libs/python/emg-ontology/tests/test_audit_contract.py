"""Graph-mutation audit contract tests (FEAT-05-1 — definition only).

Sprint 9 has no write service, so nothing is emitted; these tests pin the
*contract* the FEAT-05-2 write path will honor, and prove the metadata helper
carries identifiers/types only (never entity attribute content)."""

from __future__ import annotations

from emg_ontology import (
    AUDIT_MODULE,
    ENTITY_CREATED,
    ENTITY_SUPERSEDED,
    GRAPH_MUTATION_ACTIONS,
    RELATIONSHIP_CREATED,
    RELATIONSHIP_SUPERSEDED,
    mutation_audit_metadata,
)


def test_mutation_action_names_are_pinned() -> None:
    assert ENTITY_CREATED == "entity.created"
    assert ENTITY_SUPERSEDED == "entity.superseded"
    assert RELATIONSHIP_CREATED == "relationship.created"
    assert RELATIONSHIP_SUPERSEDED == "relationship.superseded"
    assert set(GRAPH_MUTATION_ACTIONS) == {
        "entity.created",
        "entity.superseded",
        "relationship.created",
        "relationship.superseded",
    }


def test_audit_module_tag() -> None:
    assert AUDIT_MODULE == "knowledge-graph"


def test_metadata_carries_identifiers_only_not_content() -> None:
    meta = mutation_audit_metadata(
        action=ENTITY_CREATED,
        subject_id="ent-123",
        subject_type="Person",
        schema_version=1,
    )
    assert meta == {
        "graph_action": "entity.created",
        "subject_id": "ent-123",
        "subject_type": "Person",
        "ontology_schema_version": "1",
    }
    # No free-form entity attribute content is present — identifiers/types only.
    assert "classification" not in meta
    assert all(isinstance(v, str) for v in meta.values())
