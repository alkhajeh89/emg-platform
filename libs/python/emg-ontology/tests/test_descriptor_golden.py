"""Deterministic + golden ontology descriptor tests (FEAT-05-1).

The descriptor is generated from the authoritative code models and must be
byte-stable. `_GOLDEN_DESCRIPTOR_HASH` is the merge-blocking pin: if the
ontology shape changes without an intended, reviewed bump, this test fails —
the same gate pattern as the Module 6 golden audit hash."""

from __future__ import annotations

import json

from emg_ontology import build_descriptor, descriptor_hash, descriptor_json

# Pinned SHA-256 of the canonical descriptor JSON (ontology_schema_version 1).
_GOLDEN_DESCRIPTOR_HASH = "5cbc5baa1ebadb52c65377b653b1d054d8aa2edae4a7e193f477b25585adf3b2"


def test_descriptor_is_deterministic() -> None:
    assert descriptor_json() == descriptor_json()
    assert descriptor_hash() == descriptor_hash()


def test_golden_descriptor_hash_is_unchanged() -> None:
    assert descriptor_hash() == _GOLDEN_DESCRIPTOR_HASH


def test_descriptor_json_is_canonical_sorted() -> None:
    text = descriptor_json()
    reparsed = json.loads(text)
    # Re-serializing with sorted keys yields the identical string.
    assert json.dumps(reparsed, sort_keys=True, separators=(",", ":")) == text


def test_descriptor_structure() -> None:
    d = build_descriptor()
    assert d["ontology_schema_version"] == 1
    assert d["classification_levels"] == ["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"]
    assert d["lifecycle_states"] == ["proposed", "active", "superseded", "retired"]
    assert d["trust_score_range"] == {"min": 0.0, "max": 1.0}
    # Entities are sorted by name and each declares the required envelope.
    names = [e["entity_type"] for e in d["entities"]]
    assert names == sorted(names)
    for e in d["entities"]:
        assert e["requires_classification"] is True
        assert e["requires_trust_score"] is True
        assert e["requires_provenance_reference"] is True
    rel_names = [r["relationship_type"] for r in d["relationships"]]
    assert rel_names == sorted(rel_names)
    assert len(d["relationships"]) == 8
