"""Transport-contract tests for ADR-027 Stage 4 Phase 2."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from emg_knowledge_graph_api.mutation_schemas import (
    CloseRelationshipRequest,
    CreateEntityRequest,
    MergeEntitiesRequest,
    MutationResponse,
    ReplaceEntityRequest,
    ReplaceRelationshipRequest,
)
from pydantic import ValidationError

NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def _evidence() -> dict[str, object]:
    return {
        "evidence_id": "evidence-1",
        "source": "manual_entry",
        "locator": "case-1",
        "source_principal": "analyst-1",
        "captured_at": NOW,
    }


def _node() -> dict[str, object]:
    return {
        "node_id": "entity-1",
        "node_type": "person",
        "label": "Entity One",
        "created_at": NOW,
        "updated_at": NOW,
        "source": "analyst-1",
        "confidence": 0.9,
        "classification": "INTERNAL",
        "owner": "analyst-1",
        "evidence": [_evidence()],
    }


def _edge() -> dict[str, object]:
    return {
        "edge_id": "relationship-1",
        "edge_type": "owns",
        "source_id": "entity-1",
        "target_id": "entity-2",
        "evidence": [_evidence()],
        "confidence": 0.9,
        "validity": {"valid_from": NOW},
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_create_entity_request_is_closed_and_owner_is_not_caller_supplied() -> None:
    payload: dict[str, object] = {
        "entity": {
            "entity_id": "entity-1",
            "entity_type": "person",
            "classification": "INTERNAL",
            "trust_score": 0.9,
            "provenance_reference": {
                "source_principal": "analyst-1",
                "event_id": "event-1",
            },
            "effective_from": NOW,
        },
        "as_of": NOW,
    }

    request = CreateEntityRequest.model_validate(payload)
    assert request.entity.lifecycle_status == "proposed"
    assert request.entity.version == 1
    entity_fields = type(request.entity).model_fields
    assert "owner" not in entity_fields
    assert "superseded_by" not in entity_fields

    entity = payload["entity"]
    assert isinstance(entity, dict)
    entity["owner"] = "caller-controlled"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreateEntityRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            ReplaceEntityRequest,
            {
                "replacement": _node(),
                "action": "update",
                "as_of": NOW,
            },
        ),
        (
            ReplaceRelationshipRequest,
            {
                "replacement": _edge(),
                "as_of": NOW,
            },
        ),
        (
            CloseRelationshipRequest,
            {
                "edge_id": "relationship-1",
                "as_of": NOW,
                "reason": "relationship ended",
            },
        ),
        (
            MergeEntitiesRequest,
            {
                "survivor_id": "entity-1",
                "source_ids": ["entity-2", "entity-3"],
                "as_of": NOW,
                "reason": "duplicate records",
            },
        ),
    ],
)
def test_existing_mutation_operations_have_typed_transport_requests(
    model: type[object], payload: dict[str, object]
) -> None:
    validated = model.model_validate(payload)  # type: ignore[attr-defined]
    assert validated is not None


def test_transport_requests_require_timezone_aware_datetimes() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        CloseRelationshipRequest(
            edge_id="relationship-1",
            as_of=datetime(2026, 7, 28),
            reason="relationship ended",
        )


def test_mutation_response_exactly_matches_adr_030_revision_4() -> None:
    expected_fields = {
        "tenant_id",
        "revision_number",
        "content_hash",
        "node_count",
        "edge_count",
        "revision_created",
        "nodes_created",
        "edges_created",
        "node_inputs_merged",
        "edge_inputs_merged",
        "mutation_id",
        "audit_reference",
        "replayed",
        "timestamp",
    }
    assert set(MutationResponse.model_fields) == expected_fields

    response = MutationResponse(
        tenant_id="tenant-a",
        revision_number=7,
        content_hash="sha256:abc",
        node_count=4,
        edge_count=2,
        revision_created=True,
        nodes_created=1,
        edges_created=0,
        node_inputs_merged=0,
        edge_inputs_merged=0,
        mutation_id=UUID("11111111-1111-4111-8111-111111111111"),
        audit_reference="audit:11111111-1111-4111-8111-111111111111",
        replayed=False,
        timestamp=NOW,
    )
    assert response.model_dump()["replayed"] is False


def test_mutation_response_rejects_internal_ledger_fields() -> None:
    payload = {
        "tenant_id": "tenant-a",
        "revision_number": 7,
        "content_hash": "sha256:abc",
        "node_count": 4,
        "edge_count": 2,
        "revision_created": True,
        "nodes_created": 1,
        "edges_created": 0,
        "node_inputs_merged": 0,
        "edge_inputs_merged": 0,
        "mutation_id": "11111111-1111-4111-8111-111111111111",
        "audit_reference": "audit:11111111-1111-4111-8111-111111111111",
        "replayed": True,
        "timestamp": NOW,
        "command_fingerprint": "not-public",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MutationResponse.model_validate(payload)
