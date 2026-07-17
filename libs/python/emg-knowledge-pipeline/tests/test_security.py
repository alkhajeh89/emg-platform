"""Security tests (FEAT-05-2): server-side assignment, mass-assignment
rejection, and oversized-payload DoS prevention."""

from __future__ import annotations

import emg_knowledge_pipeline as kp
import pytest
from pydantic import ValidationError


def test_request_has_no_server_assigned_fields():
    """A producer literally cannot supply entity_id/owner/provenance/trust — they
    are not fields on the request models (structural, not just validated)."""
    fields = set(kp.EntityIngestionRequest.model_fields)
    for forbidden in ("entity_id", "owner", "provenance_reference", "trust_score", "version"):
        assert forbidden not in fields
    rfields = set(kp.RelationshipIngestionRequest.model_fields)
    for forbidden in ("relationship_id", "owner", "provenance_reference", "version"):
        assert forbidden not in fields | rfields


def test_request_rejects_mass_assignment_extra_fields(now):
    with pytest.raises(ValidationError):
        kp.EntityIngestionRequest(
            entity_type="Person",
            natural_key="a",
            effective_from=now,
            owner="attacker-bu",  # not a field -> extra_forbidden
        )


def test_attributes_cannot_set_server_fields(pipeline, store, context, now):
    """Trying to smuggle a server-assigned field through `attributes` is rejected
    (not silently applied)."""
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(
                entity_type="Person",
                natural_key="a",
                effective_from=now,
                attributes={"owner": "attacker-bu", "trust_score": "1.0"},
            ),
        )
    )
    with pytest.raises(kp.IngestionValidationError):
        pipeline.ingest(batch, context)
    assert store.entity_count() == 0


def test_caller_trust_owner_provenance_never_taken_from_request(pipeline, store, context, now):
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(entity_type="Person", natural_key="a", effective_from=now),
        )
    )
    result = pipeline.ingest(batch, context)
    entity = store.get_entity(result.created_entity_ids[0])
    # All three come from the server-side context, deterministically.
    assert entity.owner == context.owner
    assert entity.trust_score == context.assigned_trust_score()
    assert entity.provenance_reference.source_principal == context.source_principal


def test_natural_key_length_bounded(now):
    with pytest.raises(ValidationError):
        kp.EntityIngestionRequest(
            entity_type="Person",
            natural_key="k" * (kp.MAX_NATURAL_KEY_LEN + 1),
            effective_from=now,
        )


def test_too_many_attributes_rejected(pipeline, context, now):
    attrs = {f"k{i}": "v" for i in range(kp.MAX_ATTRIBUTES + 1)}
    batch = kp.IngestionBatch(
        entities=(
            kp.EntityIngestionRequest(
                entity_type="Person", natural_key="a", effective_from=now, attributes=attrs
            ),
        )
    )
    with pytest.raises(kp.IngestionValidationError):
        pipeline.ingest(batch, context)
