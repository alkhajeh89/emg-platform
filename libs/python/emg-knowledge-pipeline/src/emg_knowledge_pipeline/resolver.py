"""Entity + relationship resolution (FEAT-05-2).

Turns producer-supplied `(entity_type, natural_key)` identity inputs into the
pipeline's deterministic canonical ids, resolves relationship endpoints to those
ids, and detects duplicates *within a batch* (the same resolved id appearing
twice). Pure functions — no store access, no persistence.
"""

from __future__ import annotations

from .context import IngestionContext
from .idempotency import entity_id_for, relationship_id_for
from .requests import EntityIngestionRequest, RelationshipIngestionRequest


def resolve_entity_id(context: IngestionContext, request: EntityIngestionRequest) -> str:
    """The deterministic canonical id for an entity request under this context."""
    return entity_id_for(
        context.source_principal, context.source_type, request.entity_type, request.natural_key
    )


def resolve_endpoint_id(context: IngestionContext, entity_type: str, natural_key: str) -> str:
    """The deterministic canonical id of a relationship endpoint, referenced by
    its `(entity_type, natural_key)`."""
    return entity_id_for(context.source_principal, context.source_type, entity_type, natural_key)


def resolve_relationship_endpoints(
    context: IngestionContext, request: RelationshipIngestionRequest
) -> tuple[str, str]:
    """`(from_entity_id, to_entity_id)` for a relationship request."""
    from_id = resolve_endpoint_id(context, request.from_entity_type, request.from_natural_key)
    to_id = resolve_endpoint_id(context, request.to_entity_type, request.to_natural_key)
    return from_id, to_id


def resolve_relationship_id(
    context: IngestionContext,
    request: RelationshipIngestionRequest,
    from_id: str,
    to_id: str,
) -> str:
    """The deterministic canonical id for a relationship request."""
    return relationship_id_for(context.source_principal, request.relationship_type, from_id, to_id)


def find_duplicate_entity_ids(
    context: IngestionContext, requests: tuple[EntityIngestionRequest, ...]
) -> set[str]:
    """Resolved entity ids that appear more than once in the batch."""
    seen: set[str] = set()
    dupes: set[str] = set()
    for req in requests:
        eid = resolve_entity_id(context, req)
        if eid in seen:
            dupes.add(eid)
        seen.add(eid)
    return dupes


def find_duplicate_relationship_ids(
    context: IngestionContext, requests: tuple[RelationshipIngestionRequest, ...]
) -> set[str]:
    """Resolved relationship ids that appear more than once in the batch."""
    seen: set[str] = set()
    dupes: set[str] = set()
    for req in requests:
        from_id, to_id = resolve_relationship_endpoints(context, req)
        rid = resolve_relationship_id(context, req, from_id, to_id)
        if rid in seen:
            dupes.add(rid)
        seen.add(rid)
    return dupes
