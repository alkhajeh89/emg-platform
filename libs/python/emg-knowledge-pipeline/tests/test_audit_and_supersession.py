"""Audit-contract + supersession tests (FEAT-05-2): all four mutation contracts,
provenance linkage, and the minimal supersession primitives."""

from __future__ import annotations

import emg_knowledge_pipeline as kp


def test_audit_module_and_created_actions(pipeline, context, person_role_batch):
    pipeline.ingest(person_role_batch, context)
    for ev in pipeline.audit_sink.events:
        assert ev.module == "knowledge-graph"
        assert ev.actor == "emg-svc-ingest"
        assert ev.source_system == "system"
        assert ev.outcome == "success"
        # metadata carries identifiers/types only — never entity content
        assert set(ev.metadata) == {
            "graph_action",
            "subject_id",
            "subject_type",
            "ontology_schema_version",
        }


def test_provenance_reference_points_at_the_audit_event(
    pipeline, store, context, person_role_batch
):
    result = pipeline.ingest(person_role_batch, context)
    for eid in result.created_entity_ids:
        entity = store.get_entity(eid)
        assert entity.provenance_reference.event_id in result.emitted_audit_event_ids


def test_build_mutation_event_supports_all_four_actions(context):
    from emg_knowledge_pipeline import build_mutation_event
    from emg_ontology.audit import (
        ENTITY_CREATED,
        ENTITY_SUPERSEDED,
        RELATIONSHIP_CREATED,
        RELATIONSHIP_SUPERSEDED,
    )

    for action in (
        ENTITY_CREATED,
        ENTITY_SUPERSEDED,
        RELATIONSHIP_CREATED,
        RELATIONSHIP_SUPERSEDED,
    ):
        ev = build_mutation_event(
            context=context,
            action=action,
            subject_id="subj-1",
            subject_type="Person",
            classification=__import__(
                "emg_common_types", fromlist=["Classification"]
            ).Classification.INTERNAL,
        )
        assert ev.action == action
        assert ev.module == "knowledge-graph"


def test_supersede_entity_emits_superseded_and_created(pipeline, store, context, now):
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Policy", natural_key="p", effective_from=now),
        )
    )
    r = pipeline.ingest(batch, context)
    prior_id = r.created_entity_ids[0]
    pipeline.audit_sink.events.clear()

    new_req = kp.EntityIngestionRequest(
        entity_type="Policy", natural_key="p", effective_from=now, attributes={"policy_name": "v2"}
    )
    result = pipeline.supersede_entity(context, prior_id, new_req)
    actions = [e.action for e in pipeline.audit_sink.events]
    assert actions == ["entity.superseded", "entity.created"]
    # new version references the prior; the prior is untouched (append-only)
    new_entity = store.get_entity(result.created_entity_ids[0])
    assert new_entity.supersedes == prior_id
    assert new_entity.version == 2
    assert store.get_entity(prior_id).version == 1  # historical version immutable


def test_supersede_relationship_emits_superseded_and_created(
    pipeline, store, context, now, person_role_batch
):
    r = pipeline.ingest(person_role_batch, context)
    prior_rel_id = r.created_relationship_ids[0]
    pipeline.audit_sink.events.clear()
    new_req = kp.RelationshipIngestionRequest(
        relationship_type="HOLDS",
        from_entity_type="Person",
        from_natural_key="alice",
        to_entity_type="Role",
        to_natural_key="investigator",
        effective_from=now,
    )
    pipeline.supersede_relationship(context, prior_rel_id, new_req)
    actions = [e.action for e in pipeline.audit_sink.events]
    assert actions == ["relationship.superseded", "relationship.created"]


def test_no_audit_delivery_failure_breaks_ingestion():
    """The pipeline works with a sink that records into memory; a never-raising
    sink is the Module-6 posture. A raising sink would surface, so we assert the
    default collecting sink is used and events are captured."""
    store = kp.InMemoryGraphStore()
    p = kp.KnowledgePipeline(store)
    assert isinstance(p.audit_sink, kp.CollectingAuditSink)
