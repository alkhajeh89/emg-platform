"""Identifier and value-type primitives for the Core Ontology (FEAT-05-1).

Kept tiny and storage-agnostic. The canonical identifiers are opaque, immutable
strings assigned once (UUIDv4 by default); domain natural keys, when they exist,
live as ordinary attributes on the entity — never as the identity.
"""

from __future__ import annotations

import uuid

# The ontology schema version is pinned here and surfaced through the descriptor
# (see descriptor.py). A backward-incompatible change to the ontology shape
# bumps this; the golden descriptor test guards against an accidental change.
ONTOLOGY_SCHEMA_VERSION = 1

# Trust score is a required *stored value* on every entity (US-05: "every entity
# instance carries ... trust score ... by construction"). The *calculation* of a
# trust score is FEAT-05-3 and is deliberately NOT implemented here; Sprint 9
# only enforces presence and range.
TRUST_SCORE_MIN = 0.0
TRUST_SCORE_MAX = 1.0


def new_entity_id() -> str:
    """Generate a new opaque, canonical entity identifier (UUIDv4)."""
    return f"ent-{uuid.uuid4()}"


def new_relationship_id() -> str:
    """Generate a new opaque, canonical relationship identifier (UUIDv4)."""
    return f"rel-{uuid.uuid4()}"
