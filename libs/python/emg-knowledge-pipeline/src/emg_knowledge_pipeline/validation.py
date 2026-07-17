"""Ingestion validation + server-side construction (FEAT-05-2).

This is the gate: **no persistence happens before validation succeeds.** It
builds the fully server-assigned `Entity`/`Relationship` objects (assigning
`entity_id`, `owner`, `provenance_reference`, `trust_score`, `version` from the
context — never from the request) and validates the whole batch:

- payload/field/metadata bounds (oversized-payload DoS prevention),
- attempted override of a server-assigned field (mass-assignment rejection),
- unknown entity type, ontology conformance of each built entity,
- relationship validity (endpoint types, self-loop, classification dominance,
  intra-batch cardinality) via the ontology validator,
- identifier/duplicate detection (same resolved id twice in a batch),
- dangling relationship endpoints (endpoint neither in the batch nor the store),
- cyclic dependency for acyclic relationship types (e.g. DERIVED_FROM lineage),
- effective dating (enforced by the model on construction).

All failures are aggregated into typed `IngestionProblem`s and raised as one
`IngestionValidationError`. On success it returns a `ValidatedBatch` of built
objects partitioned into *new* (to persist) and *idempotent-skipped* (already
present, byte-identical).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from emg_common_types import Classification
from emg_ontology import (
    ENTITY_REGISTRY,
    Entity,
    LifecycleStatus,
    Relationship,
    validate_relationship,
)
from emg_ontology.audit import ENTITY_CREATED, RELATIONSHIP_CREATED
from pydantic import ValidationError as PydanticValidationError

from .audit import provenance_reference_for
from .context import IngestionContext
from .errors import (
    CODE_BATCH_TOO_LARGE,
    CODE_CYCLIC_DEPENDENCY,
    CODE_DANGLING_ENDPOINT,
    CODE_DUPLICATE_ENTITY_IN_BATCH,
    CODE_DUPLICATE_RELATIONSHIP_IN_BATCH,
    CODE_FIELD_TOO_LONG,
    CODE_METADATA_TOO_LARGE,
    CODE_ONTOLOGY_NONCONFORMANT,
    CODE_RELATIONSHIP_NONCONFORMANT,
    CODE_UNKNOWN_ENTITY_TYPE,
    IngestionProblem,
    IngestionValidationError,
)
from .graph_store import GraphStore
from .requests import (
    MAX_ATTRIBUTE_VALUE_LEN,
    MAX_ATTRIBUTES,
    MAX_BATCH_ENTITIES,
    MAX_BATCH_RELATIONSHIPS,
    EntityIngestionRequest,
    IngestionBatch,
    RelationshipIngestionRequest,
)
from .resolver import (
    resolve_entity_id,
    resolve_relationship_endpoints,
    resolve_relationship_id,
)

# Envelope + server-assigned fields a producer may never set via `attributes`.
RESERVED_ENTITY_KEYS = frozenset(
    {
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
        "archetype",
    }
)

# Relationship types whose lineage must remain acyclic within a batch.
ACYCLIC_RELATIONSHIP_TYPES = frozenset({"DERIVED_FROM"})


@dataclass
class ValidatedBatch:
    """The build+validate output: objects to persist, and idempotent skips."""

    new_entities: list[Entity] = field(default_factory=list)
    new_relationships: list[Relationship] = field(default_factory=list)
    skipped_entity_ids: list[str] = field(default_factory=list)
    skipped_relationship_ids: list[str] = field(default_factory=list)


def _build_entity(
    context: IngestionContext, request: EntityIngestionRequest, entity_id: str
) -> Entity:
    """Construct a fully server-assigned entity. Raises pydantic ValidationError
    on a conformance failure (mapped to problems by the caller)."""
    model_cls = ENTITY_REGISTRY[request.entity_type]
    domain_attrs = {k: v for k, v in request.attributes.items() if k not in RESERVED_ENTITY_KEYS}
    return model_cls(
        entity_id=entity_id,
        classification=request.classification,
        trust_score=context.assigned_trust_score(),
        provenance_reference=provenance_reference_for(context, ENTITY_CREATED, entity_id),
        owner=context.owner,
        lifecycle_status=LifecycleStatus.ACTIVE,
        version=1,
        effective_from=request.effective_from,
        effective_to=request.effective_to,
        **domain_attrs,
    )


def _build_relationship(
    context: IngestionContext,
    request: RelationshipIngestionRequest,
    rel_id: str,
    from_id: str,
    to_id: str,
) -> Relationship:
    return Relationship(
        relationship_id=rel_id,
        relationship_type=request.relationship_type,
        from_entity_id=from_id,
        from_entity_type=request.from_entity_type,
        to_entity_id=to_id,
        to_entity_type=request.to_entity_type,
        classification=request.classification,
        provenance_reference=provenance_reference_for(context, RELATIONSHIP_CREATED, rel_id),
        version=1,
        effective_from=request.effective_from,
        effective_to=request.effective_to,
    )


def validate_and_build(
    batch: IngestionBatch, context: IngestionContext, store: GraphStore
) -> ValidatedBatch:
    """Validate and build a batch. Raises `IngestionValidationError` (nothing is
    persisted) or returns a `ValidatedBatch`."""
    problems: list[IngestionProblem] = []

    if (
        len(batch.entities) > MAX_BATCH_ENTITIES
        or len(batch.relationships) > MAX_BATCH_RELATIONSHIPS
    ):
        problems.append(
            IngestionProblem(
                code=CODE_BATCH_TOO_LARGE,
                message=(
                    f"batch has {len(batch.entities)} entities / "
                    f"{len(batch.relationships)} relationships; maxima are "
                    f"{MAX_BATCH_ENTITIES}/{MAX_BATCH_RELATIONSHIPS}"
                ),
            )
        )
        raise IngestionValidationError(tuple(problems))

    result = ValidatedBatch()
    # entity_id -> classification, for relationship dominance + dangling checks.
    entity_classification: dict[str, Classification] = {}
    seen_entity_ids: set[str] = set()

    # --- entities ---
    for index, req in enumerate(batch.entities):
        loc = f"entities[{index}]"
        if req.entity_type not in ENTITY_REGISTRY:
            problems.append(
                IngestionProblem(
                    code=CODE_UNKNOWN_ENTITY_TYPE,
                    message=f"unknown entity_type {req.entity_type!r}",
                    location=loc,
                )
            )
            continue
        if len(req.attributes) > MAX_ATTRIBUTES:
            problems.append(
                IngestionProblem(
                    code=CODE_METADATA_TOO_LARGE,
                    message=f"{len(req.attributes)} attributes; maximum is {MAX_ATTRIBUTES}",
                    location=loc,
                )
            )
            continue
        oversized = [k for k, v in req.attributes.items() if len(v) > MAX_ATTRIBUTE_VALUE_LEN]
        if oversized:
            problems.append(
                IngestionProblem(
                    code=CODE_FIELD_TOO_LONG,
                    message=(
                        f"attribute value(s) exceed {MAX_ATTRIBUTE_VALUE_LEN} chars: {oversized}"
                    ),
                    location=loc,
                )
            )
            continue
        # Reject any attempt to set a server-assigned / envelope field via
        # `attributes` (mass-assignment of owner/trust/provenance/etc.).
        reserved = sorted(k for k in req.attributes if k in RESERVED_ENTITY_KEYS)
        if reserved:
            problems.append(
                IngestionProblem(
                    code=CODE_ONTOLOGY_NONCONFORMANT,
                    message=f"attributes may not set server-assigned fields: {reserved}",
                    location=loc,
                )
            )
            continue

        entity_id = resolve_entity_id(context, req)
        if entity_id in seen_entity_ids:
            problems.append(
                IngestionProblem(
                    code=CODE_DUPLICATE_ENTITY_IN_BATCH,
                    message=(
                        f"entity {req.entity_type}:{req.natural_key} appears twice in the batch"
                    ),
                    location=loc,
                )
            )
            continue
        seen_entity_ids.add(entity_id)

        try:
            built = _build_entity(context, req, entity_id)
        except PydanticValidationError as exc:
            for e in exc.errors():
                problems.append(
                    IngestionProblem(
                        code=CODE_ONTOLOGY_NONCONFORMANT,
                        message=str(e.get("msg", "invalid")),
                        location=f"{loc}.{'.'.join(str(p) for p in e.get('loc', ()))}",
                    )
                )
            continue

        entity_classification[entity_id] = built.classification
        existing = store.get_entity(entity_id)
        if existing is not None:
            if existing.model_dump() == built.model_dump():
                result.skipped_entity_ids.append(entity_id)  # idempotent no-op
            else:
                problems.append(
                    IngestionProblem(
                        code=CODE_ONTOLOGY_NONCONFORMANT,
                        message=(
                            f"entity {entity_id!r} already exists with different content "
                            "(supersession is FEAT-05-5, not an ingest overwrite)"
                        ),
                        location=loc,
                    )
                )
        else:
            result.new_entities.append(built)

    # --- relationships ---
    seen_rel_ids: set[str] = set()
    acyclic_edges: dict[str, list[tuple[str, str]]] = {}
    same_type_edges: dict[str, list[tuple[str, str]]] = {}

    for index, rreq in enumerate(batch.relationships):
        loc = f"relationships[{index}]"
        from_id, to_id = resolve_relationship_endpoints(context, rreq)
        rel_id = resolve_relationship_id(context, rreq, from_id, to_id)

        if rel_id in seen_rel_ids:
            problems.append(
                IngestionProblem(
                    code=CODE_DUPLICATE_RELATIONSHIP_IN_BATCH,
                    message=f"relationship {rreq.relationship_type} appears twice in the batch",
                    location=loc,
                )
            )
            continue
        seen_rel_ids.add(rel_id)

        # Dangling: each endpoint must be in this batch or already in the store.
        from_cls = entity_classification.get(from_id) or _store_classification(store, from_id)
        to_cls = entity_classification.get(to_id) or _store_classification(store, to_id)
        if from_cls is None or to_cls is None:
            problems.append(
                IngestionProblem(
                    code=CODE_DANGLING_ENDPOINT,
                    message="relationship endpoint is not present in the batch or the graph",
                    location=loc,
                )
            )
            continue

        try:
            built_rel = _build_relationship(context, rreq, rel_id, from_id, to_id)
        except PydanticValidationError as exc:
            for e in exc.errors():
                problems.append(
                    IngestionProblem(
                        code=CODE_RELATIONSHIP_NONCONFORMANT,
                        message=str(e.get("msg", "invalid")),
                        location=loc,
                    )
                )
            continue

        report = validate_relationship(
            built_rel,
            from_classification=from_cls,
            to_classification=to_cls,
            known_entity_ids={from_id, to_id},
            existing_edges=same_type_edges.get(rreq.relationship_type, []),
        )
        if not report.ok:
            for ce in report.errors:
                problems.append(
                    IngestionProblem(
                        code=CODE_RELATIONSHIP_NONCONFORMANT,
                        message=f"{ce.code}: {ce.message}",
                        location=loc,
                    )
                )
            continue

        same_type_edges.setdefault(rreq.relationship_type, []).append((from_id, to_id))
        if rreq.relationship_type in ACYCLIC_RELATIONSHIP_TYPES:
            acyclic_edges.setdefault(rreq.relationship_type, []).append((from_id, to_id))

        existing_rel = store.get_relationship(rel_id)
        if existing_rel is not None:
            if existing_rel.model_dump() == built_rel.model_dump():
                result.skipped_relationship_ids.append(rel_id)
            else:
                problems.append(
                    IngestionProblem(
                        code=CODE_RELATIONSHIP_NONCONFORMANT,
                        message=f"relationship {rel_id!r} already exists with different content",
                        location=loc,
                    )
                )
        else:
            result.new_relationships.append(built_rel)

    # --- cyclic dependency for acyclic relationship types ---
    for rtype, edges in acyclic_edges.items():
        cycle = _detect_cycle(edges)
        if cycle:
            problems.append(
                IngestionProblem(
                    code=CODE_CYCLIC_DEPENDENCY,
                    message=f"{rtype} edges form a prohibited cycle: {cycle}",
                    location="relationships",
                )
            )

    if problems:
        raise IngestionValidationError(tuple(problems))
    return result


def _store_classification(store: GraphStore, entity_id: str) -> Classification | None:
    entity = store.get_entity(entity_id)
    return None if entity is None else entity.classification


def _detect_cycle(edges: list[tuple[str, str]]) -> list[str] | None:
    """Return a cycle (as a node list) in the directed graph of `edges`, or None.
    Used to reject cyclic lineage for acyclic relationship types.

    Implemented as an **iterative** depth-first search with an explicit stack —
    never recursive — so a long acyclic chain up to `MAX_BATCH_RELATIONSHIPS`
    cannot exhaust Python's recursion limit (Sprint 10 review fix C1). Semantics
    are preserved: standard white/grey/black colouring detects a back edge to a
    node still on the active DFS path, and the returned cycle is the active-path
    slice from the revisited node, matching the previous recursive behaviour.
    """
    adjacency: dict[str, list[str]] = {}
    for src, dst in edges:
        adjacency.setdefault(src, []).append(dst)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    for start in list(adjacency):
        if color.get(start, WHITE) != WHITE:
            continue
        # `path` is the active DFS path (all GREY); `work` holds, per path node,
        # an iterator over its not-yet-visited neighbours. Pushing/popping the
        # two together keeps them in lockstep — the explicit-stack equivalent of
        # the recursive call stack.
        color[start] = GREY
        path: list[str] = [start]
        work: list[Iterator[str]] = [iter(adjacency.get(start, ()))]
        while work:
            advanced = False
            for nxt in work[-1]:
                c = color.get(nxt, WHITE)
                if c == GREY:
                    # Back edge to a node on the active path -> cycle.
                    idx = path.index(nxt)
                    return path[idx:] + [nxt]
                if c == WHITE:
                    color[nxt] = GREY
                    path.append(nxt)
                    work.append(iter(adjacency.get(nxt, ())))
                    advanced = True
                    break
                # BLACK: fully explored, no cycle through it — skip.
            if not advanced:
                # Node exhausted: finish it and backtrack.
                color[path[-1]] = BLACK
                path.pop()
                work.pop()
    return None
