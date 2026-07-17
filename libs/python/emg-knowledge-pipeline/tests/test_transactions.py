"""Transaction + rollback tests (FEAT-05-2): a failed persistence leaves no
partial graph; the transaction abstraction is atomic and append-only."""

from __future__ import annotations

import emg_knowledge_pipeline as kp
import pytest


def test_rollback_on_persistence_failure_leaves_no_partial_graph(store, context, now):
    """If persisting the second entity fails, the first must not remain."""

    class FailingStore(kp.InMemoryGraphStore):
        def _apply(self, entities, relationships):  # type: ignore[override]
            raise RuntimeError("simulated storage outage")

    failing = FailingStore()
    pipeline = kp.KnowledgePipeline(failing)
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Person", natural_key="a", effective_from=now),
            kp.EntityIngestionRequest(entity_type="Role", natural_key="r", effective_from=now),
        )
    )
    with pytest.raises(kp.GraphPersistenceError):
        pipeline.ingest(batch, context)
    assert failing.entity_count() == 0  # nothing partially written
    # no audit events emitted for a failed (rolled-back) commit
    assert pipeline.audit_sink.events == []


def test_explicit_transaction_rollback_discards_staged(store, now):
    from datetime import datetime, timezone

    from emg_ontology import Person, ProvenanceReference

    tx = store.begin()
    entity = Person(
        entity_id="ent-x",
        classification="INTERNAL",
        trust_score=0.5,
        provenance_reference=ProvenanceReference(source_principal="s", event_id="e"),
        owner="bu",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    tx.add_entity(entity)
    tx.rollback()
    assert store.entity_count() == 0


def test_transaction_context_manager_rolls_back_on_exception(store, now):
    from datetime import datetime, timezone

    from emg_ontology import Person, ProvenanceReference

    entity = Person(
        entity_id="ent-y",
        classification="INTERNAL",
        trust_score=0.5,
        provenance_reference=ProvenanceReference(source_principal="s", event_id="e"),
        owner="bu",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(RuntimeError), store.begin() as tx:
        tx.add_entity(entity)
        raise RuntimeError("boom before commit")
    assert store.entity_count() == 0  # never committed


def test_graph_store_has_no_delete_or_update(store):
    # Append-only: neither the store nor the transaction exposes mutation.
    for attr in ("delete_entity", "update_entity", "remove_entity", "delete_relationship"):
        assert not hasattr(store, attr)
    tx = store.begin()
    for attr in ("delete", "update", "remove"):
        assert not hasattr(tx, attr)


def _person(entity_id: str, trust: float):
    from datetime import datetime, timezone

    from emg_ontology import Person, ProvenanceReference

    return Person(
        entity_id=entity_id,
        classification="INTERNAL",
        trust_score=trust,
        provenance_reference=ProvenanceReference(source_principal="s", event_id="e"),
        owner="bu",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_store_rejects_same_id_different_content_conflict(store):
    """Sprint 10 review E2 (store level): committing a different-content record
    for an existing id is a typed conflict (GRAPH_ENTITY_CONFLICT); the original
    is not overwritten."""
    tx1 = store.begin()
    tx1.add_entity(_person("ent-dup", 0.5))
    tx1.commit()

    tx2 = store.begin()
    tx2.add_entity(_person("ent-dup", 0.9))  # same id, different content
    with pytest.raises(kp.IngestionConflictError) as exc:
        tx2.commit()
    assert exc.value.error_code == "GRAPH_ENTITY_CONFLICT"
    assert store.get_entity("ent-dup").trust_score == 0.5  # original unchanged


def test_store_same_id_identical_content_is_idempotent(store):
    """Re-committing byte-identical content for an existing id is a no-op, not a
    conflict (idempotency)."""
    tx1 = store.begin()
    tx1.add_entity(_person("ent-same", 0.5))
    tx1.commit()
    tx2 = store.begin()
    tx2.add_entity(_person("ent-same", 0.5))
    tx2.commit()  # identical -> idempotent, no raise
    assert store.entity_count() == 1


def test_pipeline_rejects_same_key_different_content(pipeline, store, context, now):
    """Sprint 10 review E2 (pipeline level): re-ingesting the same natural key
    with different content is caught at validation (supersession is FEAT-05-5),
    and the existing record is not overwritten."""
    b1 = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(
                entity_type="Person", natural_key="a", classification="INTERNAL", effective_from=now
            ),
        )
    )
    first = pipeline.ingest(b1, context)
    entity_id = first.created_entity_ids[0]
    assert store.get_entity(entity_id).classification.value == "INTERNAL"

    b2 = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(
                entity_type="Person", natural_key="a", classification="SECRET", effective_from=now
            ),
        )
    )
    with pytest.raises(kp.IngestionValidationError):
        pipeline.ingest(b2, context)
    # existing record is unchanged (not overwritten to SECRET)
    assert store.get_entity(entity_id).classification.value == "INTERNAL"
    assert store.entity_count() == 1
