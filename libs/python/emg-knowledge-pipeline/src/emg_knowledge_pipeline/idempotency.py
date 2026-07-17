"""Deterministic idempotency keys (FEAT-05-2).

Re-ingesting the same payload must not create duplicates. The canonical id of an
entity/relationship is therefore a **deterministic function of its identity
inputs**, not a random UUID: the same `(source_principal, source_type,
entity_type, natural_key)` always yields the same `entity_id`, so a repeated
ingestion resolves to the existing node and is skipped (idempotent). Likewise a
relationship's id is derived from `(source_principal, relationship_type,
from_entity_id, to_entity_id)`.

Ids are namespaced (`ent-…` / `rel-…`) SHA-256 digests so they are opaque,
collision-resistant, and stable across processes. `source_principal` is part of
every key so two different producers using the same `natural_key` create
distinct nodes — one producer can never overwrite or suppress another's
(mirrors the Sprint 6 P5 per-principal idempotency posture).

The idempotency of the *audit* event emitted for a mutation reuses the same
determinism: the mutation event id is derived from the subject id and action, so
a replayed ingestion that is skipped emits no new audit event, and a genuinely
retried create maps to the same audit `event_id` (which Module 6 already treats
idempotently).
"""

from __future__ import annotations

import hashlib


def _digest(*parts: str) -> str:
    # Join with a delimiter that cannot appear ambiguously; NUL is never present
    # in the validated inputs (they are bounded printable strings).
    joined = "\x00".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def entity_id_for(
    source_principal: str, source_type: str, entity_type: str, natural_key: str
) -> str:
    """Deterministic canonical id for an ingested entity."""
    return "ent-" + _digest("entity", source_principal, source_type, entity_type, natural_key)


def relationship_id_for(
    source_principal: str, relationship_type: str, from_entity_id: str, to_entity_id: str
) -> str:
    """Deterministic canonical id for an ingested relationship."""
    return "rel-" + _digest(
        "relationship", source_principal, relationship_type, from_entity_id, to_entity_id
    )


def mutation_event_id_for(source_principal: str, action: str, subject_id: str) -> str:
    """Deterministic Module-6 audit event id for a graph mutation, so a replayed
    ingestion does not create a second audit record for the same mutation."""
    return "kg-" + _digest("mutation", source_principal, action, subject_id)
