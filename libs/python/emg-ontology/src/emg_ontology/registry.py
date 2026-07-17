"""The entity-type registry (FEAT-05-1).

A single, deterministic mapping from `entity_type` string to its model class,
assembled from the approved Sprint 9 domains. Used by the conformance validator
and the descriptor. Building it here (importing the domain modules) keeps
`core.py` free of domain imports and avoids import cycles.
"""

from __future__ import annotations

from .core import Entity
from .organizational import ORGANIZATIONAL_ENTITY_TYPES
from .references import REFERENCE_ENTITY_TYPES
from .risk_safety import RISK_SAFETY_ENTITY_TYPES

# Deterministic insertion order: Organizational, then Risk & Safety, then the
# Module-6 reference types. `descriptor.py` sorts by name for stable output.
ENTITY_REGISTRY: dict[str, type[Entity]] = {
    **ORGANIZATIONAL_ENTITY_TYPES,
    **RISK_SAFETY_ENTITY_TYPES,
    **REFERENCE_ENTITY_TYPES,
}

# Which domain each entity type belongs to (for the descriptor + docs).
ENTITY_DOMAINS: dict[str, str] = {
    **{name: "organizational" for name in ORGANIZATIONAL_ENTITY_TYPES},
    **{name: "risk_safety" for name in RISK_SAFETY_ENTITY_TYPES},
    **{name: "module6_reference" for name in REFERENCE_ENTITY_TYPES},
}


def is_known_entity_type(entity_type: str) -> bool:
    return entity_type in ENTITY_REGISTRY
