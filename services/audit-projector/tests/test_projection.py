from __future__ import annotations

from dataclasses import replace

import pytest
from audit_projector_helpers import ledger
from emg_audit_projector.errors import ProjectionError
from emg_audit_projector.projection import project_audit_events


def test_projection_is_exact_deterministic_and_excludes_idempotency_key() -> None:
    record = ledger(intent_count=2)

    first = project_audit_events(record)
    second = project_audit_events(record)

    assert first == second
    assert [event.event_id for event in first] == [
        f"kg-mutation:{record.mutation_id}:0",
        f"kg-mutation:{record.mutation_id}:1",
    ]
    event = first[0]
    assert event.actor == "service-principal"
    assert event.actor_type == "service"
    assert event.module == event.source_system == "knowledge-graph"
    assert event.outcome == "success"
    assert event.correlation_id is None
    assert event.provenance is None
    assert event.metadata == {
        "revision_number": "7",
        "content_hash": "a" * 64,
        "related_resource_ids": '["related-b","related-a"]',
        "ledger_status": "succeeded",
    }
    assert "must-not-project" not in event.model_dump_json()


def test_projection_preserves_no_op_as_success_with_ledger_status() -> None:
    record = replace(ledger(), status="no_op")
    event = project_audit_events(record)[0]
    assert event.outcome == "success"
    assert event.metadata["ledger_status"] == "no_op"


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 2, "intents": [{}]},
        {"schema_version": 1, "intents": []},
        {"schema_version": 1, "intents": [{"tenant_id": "tenant-a"}]},
    ],
)
def test_poison_ledger_is_rejected_without_fabrication(document: dict[str, object]) -> None:
    with pytest.raises(ProjectionError):
        project_audit_events(replace(ledger(), audit_intents=document))


def test_cross_tenant_intent_is_rejected() -> None:
    record = ledger()
    document = dict(record.audit_intents)
    intents = [dict(record.audit_intents["intents"][0])]  # type: ignore[index]
    intents[0]["tenant_id"] = "tenant-b"
    document["intents"] = intents
    with pytest.raises(ProjectionError, match="tenant"):
        project_audit_events(replace(record, audit_intents=document))
