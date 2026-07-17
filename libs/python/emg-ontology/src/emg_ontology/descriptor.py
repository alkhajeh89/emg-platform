"""The deterministic, machine-readable ontology descriptor (FEAT-05-1).

The **code models are authoritative**; this descriptor is *generated from them*
(never hand-authored, no RDF/OWL/SHACL/YAML authority). It is a stable,
sorted-key snapshot of the ontology — entity types with their required/optional
attributes, the relationship catalog, the lifecycle states, classification
levels, and the trust-score range — stamped with `ontology_schema_version`.

Determinism is a hard requirement: `build_descriptor()` sorts every collection
and `descriptor_json()` serializes with sorted keys, so the same code always
yields byte-identical output. A **golden descriptor test** pins a hash of that
output; an unintended change to the ontology shape breaks the golden test (the
same merge-blocking-gate pattern as the Module 6 golden hash).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from emg_common_types import Classification

from .core import Entity, LifecycleStatus
from .identifiers import ONTOLOGY_SCHEMA_VERSION, TRUST_SCORE_MAX, TRUST_SCORE_MIN
from .registry import ENTITY_DOMAINS, ENTITY_REGISTRY
from .relationships import RELATIONSHIP_CATALOG

# The governance-envelope field names shared by every entity, in a fixed order.
_ENVELOPE_FIELDS = (
    "entity_id",
    "entity_type",
    "classification",
    "trust_score",
    "provenance_reference",
    "owner",
    "lifecycle_status",
    "version",
    "effective_from",
    "effective_to",
    "supersedes",
    "superseded_by",
    "correlation_id",
)


def _entity_descriptor(name: str, model_cls: type[Entity]) -> dict[str, Any]:
    fields = model_cls.model_fields
    required = sorted(fname for fname, f in fields.items() if f.is_required())
    optional = sorted(fname for fname, f in fields.items() if not f.is_required())
    return {
        "entity_type": name,
        "archetype": model_cls.archetype,
        "domain": ENTITY_DOMAINS.get(name, "unknown"),
        "required_attributes": required,
        "optional_attributes": optional,
        "requires_classification": "classification" in required,
        "requires_trust_score": "trust_score" in required,
        "requires_provenance_reference": "provenance_reference" in required,
    }


def _relationship_descriptor(name: str) -> dict[str, Any]:
    rule = RELATIONSHIP_CATALOG[name]
    return {
        "relationship_type": name,
        "source_types": sorted(rule.source_types),
        "target_types": sorted(rule.target_types),
        "cardinality": rule.cardinality.value,
        "mutability": rule.mutability.value,
        "direction": rule.direction.value,
        "self_loop_allowed": rule.self_loop_allowed,
        "description": rule.description,
    }


def build_descriptor() -> dict[str, Any]:
    """Build the deterministic ontology descriptor from the code models."""
    return {
        "ontology_schema_version": ONTOLOGY_SCHEMA_VERSION,
        "classification_levels": [c.value for c in Classification],
        "lifecycle_states": [s.value for s in LifecycleStatus],
        "trust_score_range": {"min": TRUST_SCORE_MIN, "max": TRUST_SCORE_MAX},
        "envelope_fields": list(_ENVELOPE_FIELDS),
        "entities": [
            _entity_descriptor(name, ENTITY_REGISTRY[name]) for name in sorted(ENTITY_REGISTRY)
        ],
        "relationships": [_relationship_descriptor(name) for name in sorted(RELATIONSHIP_CATALOG)],
    }


def descriptor_json() -> str:
    """Canonical JSON serialization of the descriptor (sorted keys, stable
    separators) — byte-identical across runs."""
    return json.dumps(build_descriptor(), sort_keys=True, separators=(",", ":"))


def descriptor_hash() -> str:
    """SHA-256 of the canonical descriptor JSON — the value the golden test
    pins."""
    return hashlib.sha256(descriptor_json().encode("utf-8")).hexdigest()
