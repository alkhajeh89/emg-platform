"""Shared fixtures for the emg-ontology test suite (FEAT-05-1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_ontology import ProvenanceReference, new_entity_id, new_relationship_id


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def prov() -> ProvenanceReference:
    return ProvenanceReference(source_principal="emg-svc-identity", event_id="evt-1")


@pytest.fixture
def prov_dict() -> dict:
    return {"source_principal": "emg-svc-identity", "event_id": "evt-1"}


@pytest.fixture
def entity_payload(prov_dict):
    """Factory returning a conforming raw entity dict; override any field."""

    def _make(entity_type: str = "Person", **overrides) -> dict:
        payload = {
            "entity_type": entity_type,
            "entity_id": new_entity_id(),
            "classification": "INTERNAL",
            "trust_score": 0.75,
            "provenance_reference": dict(prov_dict),
            "owner": "business-unit-1",
            "lifecycle_status": "active",
            "version": 1,
            "effective_from": "2026-01-01T00:00:00Z",
        }
        payload.update(overrides)
        return payload

    return _make


@pytest.fixture
def relationship_payload(prov_dict):
    """Factory returning a conforming raw relationship dict; override any field."""

    def _make(relationship_type: str = "HOLDS", **overrides) -> dict:
        payload = {
            "relationship_id": new_relationship_id(),
            "relationship_type": relationship_type,
            "from_entity_id": "p-1",
            "from_entity_type": "Person",
            "to_entity_id": "ro-1",
            "to_entity_type": "Role",
            "classification": "INTERNAL",
            "provenance_reference": dict(prov_dict),
            "version": 1,
            "effective_from": "2026-01-01T00:00:00Z",
        }
        payload.update(overrides)
        return payload

    return _make
