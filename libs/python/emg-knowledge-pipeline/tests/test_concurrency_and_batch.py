"""Concurrency + batch-ordering tests (FEAT-05-2)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import emg_knowledge_pipeline as kp


def test_concurrent_identical_ingestion_collapses_to_one(store, context, person_role_batch):
    """Many threads ingesting the same batch against one store must yield exactly
    one graph (idempotent), never a forked/duplicated graph or an unhandled
    error."""
    pipeline = kp.KnowledgePipeline(store)

    def _ingest(_: int) -> int:
        return pipeline.ingest(person_role_batch, context).created_count

    with ThreadPoolExecutor(max_workers=16) as pool:
        created_counts = list(pool.map(_ingest, range(16)))

    # Exactly one thread's ingestion created the 3 records; the rest were
    # idempotent no-ops. No duplication.
    assert sum(created_counts) == 3
    assert store.entity_count() == 2 and store.relationship_count() == 1


def test_batch_dependency_ordering_entities_before_relationships(store, context, now):
    """A relationship whose endpoints are defined in the SAME batch resolves —
    entities are persisted before relationships."""
    pipeline = kp.KnowledgePipeline(store)
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Risk", natural_key="r1", effective_from=now),
            kp.EntityIngestionRequest(entity_type="Control", natural_key="c1", effective_from=now),
        ),
        relationships=(
            kp.RelationshipIngestionRequest(
                relationship_type="MITIGATED_BY",
                from_entity_type="Risk",
                from_natural_key="r1",
                to_entity_type="Control",
                to_natural_key="c1",
                effective_from=now,
            ),
        ),
    )
    result = pipeline.ingest(batch, context)
    assert result.created_count == 3
    assert store.relationship_count() == 1


def test_partial_batch_failure_is_atomic(store, context, now):
    """If any item in the batch is invalid, the WHOLE batch is rejected and
    nothing is persisted (no partial graph)."""
    pipeline = kp.KnowledgePipeline(store)
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Person", natural_key="ok", effective_from=now),
            kp.EntityIngestionRequest(entity_type="Dragon", natural_key="bad", effective_from=now),
        )
    )
    import pytest

    with pytest.raises(kp.IngestionValidationError):
        pipeline.ingest(batch, context)
    assert store.entity_count() == 0


def test_concurrent_different_content_same_id_one_wins_no_corruption(store, now):
    """Sprint 10 review E3: many threads ingest DIFFERENT content for the SAME
    deterministic id concurrently. Invariants (timing-independent):
    exactly one entity persists with one consistent content, the graph is never
    corrupted or partial, and every non-winning attempt returns a typed error
    (a validation conflict or a persistence conflict) — never a duplicate node."""
    from emg_errors import EMGError

    pipeline = kp.KnowledgePipeline(store)
    ctx = kp.IngestionContext(source_principal="svc", source_type="system", owner="bu")

    def _batch(classification: str) -> kp.IngestionBatch:
        # Same (entity_type, natural_key) => same deterministic id; different
        # classification => different content.
        return kp.IngestionBatch(
            entities=(
                kp.EntityIngestionRequest(
                    entity_type="Person",
                    natural_key="shared",
                    classification=classification,
                    effective_from=now,
                ),
            )
        )

    batches = [_batch("INTERNAL"), _batch("SECRET")] * 12  # 24 racing attempts

    def _run(b: kp.IngestionBatch):
        try:
            return ("ok", pipeline.ingest(b, ctx))
        except EMGError as e:  # typed conflict (validation or persistence)
            return ("err", e)

    with ThreadPoolExecutor(max_workers=24) as pool:
        outcomes = list(pool.map(_run, batches))

    # Exactly one entity persists, with a single consistent (uncorrupted) content.
    assert store.entity_count() == 1
    persisted = next(iter(store._entities.values()))  # type: ignore[attr-defined]
    assert persisted.classification.value in {"INTERNAL", "SECRET"}
    # Every failure is a typed EMGError (never an unhandled/RecursionError/etc.).
    assert all(isinstance(v, EMGError) for kind, v in outcomes if kind == "err")
    # At least one attempt succeeded (the winner + same-content idempotent skips).
    assert any(kind == "ok" for kind, _ in outcomes)
