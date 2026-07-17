"""Validation tests (FEAT-05-2): no persistence before validation; typed
problems for every rejection category."""

from __future__ import annotations

import emg_knowledge_pipeline as kp
import pytest
from emg_knowledge_pipeline.errors import (
    CODE_BATCH_TOO_LARGE,
    CODE_CYCLIC_DEPENDENCY,
    CODE_DANGLING_ENDPOINT,
    CODE_DUPLICATE_ENTITY_IN_BATCH,
    CODE_DUPLICATE_RELATIONSHIP_IN_BATCH,
    CODE_FIELD_TOO_LONG,
    CODE_ONTOLOGY_NONCONFORMANT,
    CODE_RELATIONSHIP_NONCONFORMANT,
    CODE_UNKNOWN_ENTITY_TYPE,
)
from emg_knowledge_pipeline.validation import _detect_cycle


def _codes(exc: kp.IngestionValidationError) -> set[str]:
    return {p.code for p in exc.problems}


def test_unknown_entity_type_rejected_and_nothing_persisted(pipeline, store, context, now):
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Dragon", natural_key="d", effective_from=now),
        )
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(batch, context)
    assert CODE_UNKNOWN_ENTITY_TYPE in _codes(exc.value)
    assert store.entity_count() == 0  # no persistence before validation succeeds


def test_invalid_relationship_endpoint_type_rejected(pipeline, store, context, now):
    # System HOLDS Role is not a legal HOLDS (source must be Person).
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="System", natural_key="s", effective_from=now),
            kp.EntityIngestionRequest(entity_type="Role", natural_key="r", effective_from=now),
        ),
        relationships=(
            kp.RelationshipIngestionRequest(
                relationship_type="HOLDS",
                from_entity_type="System",
                from_natural_key="s",
                to_entity_type="Role",
                to_natural_key="r",
                effective_from=now,
            ),
        ),
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(batch, context)
    assert CODE_RELATIONSHIP_NONCONFORMANT in _codes(exc.value)
    assert store.entity_count() == 0 and store.relationship_count() == 0


def test_dangling_relationship_endpoint_rejected(pipeline, store, context, now):
    batch = kp.IngestionBatch(
        relationships=(
            kp.RelationshipIngestionRequest(
                relationship_type="HOLDS",
                from_entity_type="Person",
                from_natural_key="ghost",
                to_entity_type="Role",
                to_natural_key="phantom",
                effective_from=now,
            ),
        )
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(batch, context)
    assert CODE_DANGLING_ENDPOINT in _codes(exc.value)


def test_duplicate_entity_in_batch_rejected(pipeline, context, now):
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Person", natural_key="a", effective_from=now),
            kp.EntityIngestionRequest(entity_type="Person", natural_key="a", effective_from=now),
        )
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(batch, context)
    assert CODE_DUPLICATE_ENTITY_IN_BATCH in _codes(exc.value)


def test_cyclic_derived_from_rejected(pipeline, context, now):
    # Evidence e1 DERIVED_FROM e2 and e2 DERIVED_FROM e1 — a prohibited cycle.
    ents = tuple(
        kp.EntityIngestionRequest(entity_type="Evidence", natural_key=k, effective_from=now)
        for k in ("e1", "e2")
    )
    rels = (
        kp.RelationshipIngestionRequest(
            relationship_type="DERIVED_FROM",
            from_entity_type="Evidence",
            from_natural_key="e1",
            to_entity_type="Evidence",
            to_natural_key="e2",
            effective_from=now,
        ),
        kp.RelationshipIngestionRequest(
            relationship_type="DERIVED_FROM",
            from_entity_type="Evidence",
            from_natural_key="e2",
            to_entity_type="Evidence",
            to_natural_key="e1",
            effective_from=now,
        ),
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(kp.IngestionBatch(entities=ents, relationships=rels), context)
    assert CODE_CYCLIC_DEPENDENCY in _codes(exc.value)


def test_self_loop_derived_from_rejected(pipeline, context, now):
    ents = (kp.EntityIngestionRequest(entity_type="Evidence", natural_key="e", effective_from=now),)
    rels = (
        kp.RelationshipIngestionRequest(
            relationship_type="DERIVED_FROM",
            from_entity_type="Evidence",
            from_natural_key="e",
            to_entity_type="Evidence",
            to_natural_key="e",
            effective_from=now,
        ),
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(kp.IngestionBatch(entities=ents, relationships=rels), context)
    # a self-loop is caught either by the ontology self-loop rule or the cycle check
    assert _codes(exc.value) & {CODE_RELATIONSHIP_NONCONFORMANT, CODE_CYCLIC_DEPENDENCY}


def test_effective_dates_validated(pipeline, context, now):
    from datetime import timedelta

    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(
                entity_type="Person",
                natural_key="a",
                effective_from=now,
                effective_to=now - timedelta(days=1),
            ),
        )
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(batch, context)
    assert CODE_ONTOLOGY_NONCONFORMANT in _codes(exc.value)


def test_unknown_domain_attribute_rejected(pipeline, context, now):
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(
                entity_type="Person",
                natural_key="a",
                effective_from=now,
                attributes={"totally_unknown_field": "x"},
            ),
        )
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(batch, context)
    assert CODE_ONTOLOGY_NONCONFORMANT in _codes(exc.value)


def test_batch_too_large_rejected(pipeline, context, now):
    ents = tuple(
        kp.EntityIngestionRequest(entity_type="Person", natural_key=f"p{i}", effective_from=now)
        for i in range(kp.MAX_BATCH_ENTITIES + 1)
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(kp.IngestionBatch(entities=ents), context)
    assert CODE_BATCH_TOO_LARGE in _codes(exc.value)


def test_oversized_attribute_value_rejected(pipeline, context, now):
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(
                entity_type="Person",
                natural_key="a",
                effective_from=now,
                attributes={"display_name": "A" * (kp.MAX_ATTRIBUTE_VALUE_LEN + 1)},
            ),
        )
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(batch, context)
    assert CODE_FIELD_TOO_LONG in _codes(exc.value)


def test_duplicate_relationship_in_batch_rejected(pipeline, context, now):
    """Sprint 10 review E1: two identical relationships in one batch are a typed
    rejection (CODE_DUPLICATE_RELATIONSHIP_IN_BATCH)."""
    ents = (
        kp.EntityIngestionRequest(entity_type="Person", natural_key="p", effective_from=now),
        kp.EntityIngestionRequest(entity_type="Role", natural_key="r", effective_from=now),
    )
    edge = kp.RelationshipIngestionRequest(
        relationship_type="HOLDS",
        from_entity_type="Person",
        from_natural_key="p",
        to_entity_type="Role",
        to_natural_key="r",
        effective_from=now,
    )
    with pytest.raises(kp.IngestionValidationError) as exc:
        pipeline.ingest(kp.IngestionBatch(entities=ents, relationships=(edge, edge)), context)
    assert CODE_DUPLICATE_RELATIONSHIP_IN_BATCH in _codes(exc.value)


# --- C1 regression: cycle detector must not recurse (RecursionError DoS) ----


def test_detect_cycle_deep_chain_no_recursion() -> None:
    """Sprint 10 review C1 (unit level): a linear chain far deeper than Python's
    recursion limit must not raise RecursionError; adding a closing edge must
    still be detected as a cycle. Preserves the prior return semantics."""
    depth = 5000  # >> sys.getrecursionlimit() (default 1000)
    chain = [(f"n{i}", f"n{i + 1}") for i in range(depth)]
    assert _detect_cycle(chain) is None  # acyclic, no RecursionError
    cyclic = chain + [(f"n{depth}", "n0")]
    cycle = _detect_cycle(cyclic)
    assert cycle is not None and cycle[0] == cycle[-1]  # a real cycle path
    # Semantics unchanged for the small cases.
    assert _detect_cycle([("a", "b"), ("b", "a")]) == ["a", "b", "a"]
    assert _detect_cycle([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]) is None


def test_pipeline_accepts_deep_acyclic_chain_and_rejects_cycle(
    pipeline, store, context, now
) -> None:
    """Sprint 10 review C1 (end-to-end): a DERIVED_FROM chain deeper than the
    recursion limit but within Sprint 10 batch limits ingests without
    RecursionError and is accepted; the same chain plus a closing edge is
    rejected with the typed cycle code."""
    depth = 1100  # > recursion limit (1000); chain edges <= MAX_BATCH_RELATIONSHIPS (2000)
    assert depth + 1 <= kp.MAX_BATCH_ENTITIES * 2  # created across <=2 entity batches
    keys = [f"ev{i}" for i in range(depth + 1)]

    # Pre-create the evidence nodes across entity-only batches (<= MAX_BATCH_ENTITIES each).
    for i in range(0, len(keys), kp.MAX_BATCH_ENTITIES):
        chunk = keys[i : i + kp.MAX_BATCH_ENTITIES]
        pipeline.ingest(
            kp.IngestionBatch(
                entities=tuple(
                    kp.EntityIngestionRequest(
                        entity_type="Evidence", natural_key=k, effective_from=now
                    )
                    for k in chunk
                )
            ),
            context,
        )
    assert store.entity_count() == depth + 1

    def _edge(a: str, b: str) -> kp.RelationshipIngestionRequest:
        return kp.RelationshipIngestionRequest(
            relationship_type="DERIVED_FROM",
            from_entity_type="Evidence",
            from_natural_key=a,
            to_entity_type="Evidence",
            to_natural_key=b,
            effective_from=now,
        )

    acyclic = tuple(_edge(keys[i], keys[i + 1]) for i in range(depth))
    # Accepted — no RecursionError even though the chain is 1100 deep.
    result = pipeline.ingest(kp.IngestionBatch(relationships=acyclic), context)
    assert result.created_relationship_ids  # persisted
    assert store.relationship_count() == depth

    # The same chain plus a closing edge (in a fresh store) is a rejected cycle.
    store2 = kp.InMemoryGraphStore()
    p2 = kp.KnowledgePipeline(store2)
    for i in range(0, len(keys), kp.MAX_BATCH_ENTITIES):
        chunk = keys[i : i + kp.MAX_BATCH_ENTITIES]
        p2.ingest(
            kp.IngestionBatch(
                entities=tuple(
                    kp.EntityIngestionRequest(
                        entity_type="Evidence", natural_key=k, effective_from=now
                    )
                    for k in chunk
                )
            ),
            context,
        )
    cyclic = acyclic + (_edge(keys[depth], keys[0]),)
    with pytest.raises(kp.IngestionValidationError) as exc:
        p2.ingest(kp.IngestionBatch(relationships=cyclic), context)
    assert CODE_CYCLIC_DEPENDENCY in _codes(exc.value)
    assert store2.relationship_count() == 0  # nothing persisted on rejection
