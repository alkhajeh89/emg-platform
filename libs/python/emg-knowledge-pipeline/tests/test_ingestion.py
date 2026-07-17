"""End-to-end ingestion tests (FEAT-05-2): success, idempotency, server-side
assignment, provenance linkage, audit emission, and result shape."""

from __future__ import annotations

import emg_knowledge_pipeline as kp


def test_successful_ingestion_persists_and_emits_audit(pipeline, store, context, person_role_batch):
    result = pipeline.ingest(person_role_batch, context)
    assert result.ok
    assert result.created_count == 3  # 2 entities + 1 relationship
    assert result.skipped_count == 0
    assert store.entity_count() == 2 and store.relationship_count() == 1
    # one audit event per created mutation
    assert len(result.emitted_audit_event_ids) == 3
    actions = sorted(e.action for e in pipeline.audit_sink.events)
    assert actions == ["entity.created", "entity.created", "relationship.created"]


def test_idempotent_reingestion_creates_nothing(pipeline, store, context, person_role_batch):
    pipeline.ingest(person_role_batch, context)
    before = pipeline.audit_sink.events.copy()
    result = pipeline.ingest(person_role_batch, context)
    assert result.created_count == 0
    assert result.skipped_count == 3
    assert store.entity_count() == 2 and store.relationship_count() == 1
    # no new audit events for an idempotent no-op
    assert pipeline.audit_sink.events == before


def test_deterministic_ids_are_stable_across_pipelines(store, context, person_role_batch):
    p1 = kp.KnowledgePipeline(store)
    r1 = p1.ingest(person_role_batch, context)
    # a fresh pipeline over the same store re-ingests idempotently.
    p2 = kp.KnowledgePipeline(store)
    r2 = p2.ingest(person_role_batch, context)
    assert set(r1.created_entity_ids) and r2.created_count == 0


def test_server_assigns_owner_trust_provenance(pipeline, store, context, person_role_batch):
    result = pipeline.ingest(person_role_batch, context)
    entity_id = result.created_entity_ids[0]
    entity = store.get_entity(entity_id)
    assert entity.owner == "business-unit-1"  # from context, not the request
    assert entity.trust_score == 0.7  # system-source default (interim)
    # provenance references the audit event emitted for this entity's creation
    assert entity.provenance_reference.source_principal == "emg-svc-ingest"
    assert entity.provenance_reference.event_id in result.emitted_audit_event_ids
    # no audit content copied — only the reference
    assert set(entity.provenance_reference.model_dump()) == {
        "source_principal",
        "event_id",
        "correlation_id",
        "provenance_record_id",
        "custody_event_id",
    }


def test_correlation_id_preserved_on_audit_events(pipeline, context, person_role_batch):
    result = pipeline.ingest(person_role_batch, context)
    assert result.correlation_id == "corr-1"
    assert all(e.correlation_id == "corr-1" for e in pipeline.audit_sink.events)


def test_trust_default_varies_by_source_type(store, now):
    for source_type, expected in [("system", 0.7), ("ai", 0.3), ("document", 0.5)]:
        s = kp.InMemoryGraphStore()
        p = kp.KnowledgePipeline(s)
        ctx = kp.IngestionContext(source_principal="svc", source_type=source_type, owner="bu")
        p.ingest(
            kp.IngestionBatch(
                entities=(
                    kp.EntityIngestionRequest(
                        entity_type="System", natural_key="sys-1", effective_from=now
                    ),
                )
            ),
            ctx,
        )
        entity = next(iter(s._entities.values()))
        assert entity.trust_score == expected


def test_different_principals_do_not_collide(store, now):
    """Two producers using the same natural key create distinct entities."""
    p = kp.KnowledgePipeline(store)
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Person", natural_key="x", effective_from=now),
        )
    )
    r1 = p.ingest(
        batch, kp.IngestionContext(source_principal="svc-a", source_type="system", owner="bu")
    )
    r2 = p.ingest(
        batch, kp.IngestionContext(source_principal="svc-b", source_type="system", owner="bu")
    )
    assert r1.created_entity_ids != r2.created_entity_ids
    assert store.entity_count() == 2
