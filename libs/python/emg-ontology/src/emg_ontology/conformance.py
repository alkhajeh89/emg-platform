"""Ontology conformance validation (FEAT-05-1, TASK-05-3).

A **pure, storage-independent** validator that answers US-05's requirement: "an
ontology conformance test rejects a non-conforming write." It accepts a
candidate entity or relationship — as a constructed model *or* a raw dict (the
shape a future ingestion write would carry) — and returns a typed,
machine-readable `ConformanceReport`. It performs no I/O and touches no store.

Cross-cutting context that a pure validator cannot know on its own (the
classifications of an edge's endpoints, whether the endpoints exist, sibling
edges for cardinality) is passed in by the caller, so the function stays pure
and storage-independent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from emg_common_types import Classification
from emg_errors import ValidationError
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from .core import Cardinality, Entity, Relationship, dominates
from .registry import ENTITY_REGISTRY
from .relationships import RELATIONSHIP_CATALOG

# --- machine-readable error codes ------------------------------------------

CODE_UNKNOWN_ENTITY_TYPE = "ONTOLOGY_UNKNOWN_ENTITY_TYPE"
CODE_UNKNOWN_RELATIONSHIP_TYPE = "ONTOLOGY_UNKNOWN_RELATIONSHIP_TYPE"
CODE_MISSING_CLASSIFICATION = "ONTOLOGY_MISSING_CLASSIFICATION"
CODE_MISSING_TRUST_SCORE = "ONTOLOGY_MISSING_TRUST_SCORE"
CODE_TRUST_SCORE_OUT_OF_RANGE = "ONTOLOGY_TRUST_SCORE_OUT_OF_RANGE"
CODE_MISSING_PROVENANCE = "ONTOLOGY_MISSING_PROVENANCE"
CODE_INVALID_LIFECYCLE_STATE = "ONTOLOGY_INVALID_LIFECYCLE_STATE"
CODE_INVALID_SOURCE_TYPE = "ONTOLOGY_INVALID_SOURCE_TYPE"
CODE_INVALID_TARGET_TYPE = "ONTOLOGY_INVALID_TARGET_TYPE"
CODE_CARDINALITY_VIOLATION = "ONTOLOGY_CARDINALITY_VIOLATION"
CODE_CLASSIFICATION_DOMINANCE = "ONTOLOGY_CLASSIFICATION_DOMINANCE"
CODE_DANGLING_ENDPOINT = "ONTOLOGY_DANGLING_ENDPOINT"
CODE_SELF_LOOP_PROHIBITED = "ONTOLOGY_SELF_LOOP_PROHIBITED"
CODE_INVALID_EFFECTIVE_DATES = "ONTOLOGY_INVALID_EFFECTIVE_DATES"
CODE_SELF_SUPERSESSION = "ONTOLOGY_SELF_SUPERSESSION"
CODE_EXTRA_FIELD = "ONTOLOGY_EXTRA_FIELD"
CODE_SCHEMA_VIOLATION = "ONTOLOGY_SCHEMA_VIOLATION"


class ConformanceError(BaseModel):
    """One typed conformance failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    location: str | None = None


class ConformanceReport(BaseModel):
    """The result of a conformance check. `ok` is True iff `errors` is empty."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    errors: tuple[ConformanceError, ...] = ()


class OntologyConformanceError(ValidationError):
    """Raised by the `assert_*` helpers when a candidate is non-conforming.
    Carries the typed `errors` for machine consumption; `error_code` is the
    first failure's code (falls back to a generic ontology code)."""

    def __init__(self, errors: tuple[ConformanceError, ...]) -> None:
        code = errors[0].code if errors else "ONTOLOGY_NONCONFORMANT"
        message = "; ".join(f"{e.code}: {e.message}" for e in errors) or "non-conforming"
        super().__init__(message, error_code=code)
        self.errors = errors


def _report(errors: list[ConformanceError]) -> ConformanceReport:
    return ConformanceReport(ok=not errors, errors=tuple(errors))


def _map_pydantic_error(err: Mapping[str, Any]) -> ConformanceError:
    """Translate one pydantic error into a typed ConformanceError with a stable
    ontology code."""
    etype = str(err.get("type", ""))
    loc = err.get("loc", ())
    field = str(loc[0]) if loc else ""
    location = ".".join(str(part) for part in loc) if loc else None
    msg = str(err.get("msg", "invalid"))

    if etype == "missing":
        if field == "classification":
            return ConformanceError(
                code=CODE_MISSING_CLASSIFICATION, message=msg, location=location
            )
        if field == "trust_score":
            return ConformanceError(code=CODE_MISSING_TRUST_SCORE, message=msg, location=location)
        if field == "provenance_reference":
            return ConformanceError(code=CODE_MISSING_PROVENANCE, message=msg, location=location)
        return ConformanceError(code=CODE_SCHEMA_VIOLATION, message=msg, location=location)
    if etype == "extra_forbidden":
        return ConformanceError(code=CODE_EXTRA_FIELD, message=msg, location=location)
    if etype in ("greater_than_equal", "less_than_equal") and field == "trust_score":
        return ConformanceError(code=CODE_TRUST_SCORE_OUT_OF_RANGE, message=msg, location=location)
    if field == "lifecycle_status":
        return ConformanceError(code=CODE_INVALID_LIFECYCLE_STATE, message=msg, location=location)
    if etype == "value_error":
        lowered = msg.lower()
        if "supersede" in lowered:
            return ConformanceError(code=CODE_SELF_SUPERSESSION, message=msg, location=location)
        if "effective" in lowered:
            return ConformanceError(
                code=CODE_INVALID_EFFECTIVE_DATES, message=msg, location=location
            )
    return ConformanceError(code=CODE_SCHEMA_VIOLATION, message=msg, location=location)


# --- entity conformance ----------------------------------------------------


def validate_entity(candidate: Entity | Mapping[str, Any]) -> ConformanceReport:
    """Validate a candidate entity (model or raw dict) against the ontology."""
    if isinstance(candidate, Entity):
        # Already constructed => envelope already enforced by the model.
        return _report([])

    entity_type = candidate.get("entity_type")
    if not entity_type or entity_type not in ENTITY_REGISTRY:
        return _report(
            [
                ConformanceError(
                    code=CODE_UNKNOWN_ENTITY_TYPE,
                    message=f"unknown entity_type {entity_type!r}",
                    location="entity_type",
                )
            ]
        )
    model_cls = ENTITY_REGISTRY[entity_type]
    try:
        model_cls.model_validate(dict(candidate))
    except PydanticValidationError as exc:
        return _report([_map_pydantic_error(e) for e in exc.errors()])
    return _report([])


# --- relationship conformance ----------------------------------------------


def validate_relationship(
    candidate: Relationship | Mapping[str, Any],
    *,
    from_classification: Classification | None = None,
    to_classification: Classification | None = None,
    known_entity_ids: Iterable[str] | None = None,
    existing_edges: Iterable[tuple[str, str]] | None = None,
) -> ConformanceReport:
    """Validate a candidate relationship (model or raw dict) against the
    ontology catalog and the supplied cross-cutting context.

    - `from_classification`/`to_classification`: endpoint classifications; when
      given, the edge must be at least as classified as both (dominance).
    - `known_entity_ids`: when given, both endpoints must be present (else the
      edge is dangling).
    - `existing_edges`: sibling `(from_id, to_id)` pairs of the *same*
      relationship type, used to check cardinality.
    """
    errors: list[ConformanceError] = []

    # Build a model to enforce the envelope (or accept an already-built one).
    if isinstance(candidate, Relationship):
        rel = candidate
        payload: dict[str, Any] = candidate.model_dump()
    else:
        payload = dict(candidate)
        rtype_raw = payload.get("relationship_type")
        if not rtype_raw or rtype_raw not in RELATIONSHIP_CATALOG:
            return _report(
                [
                    ConformanceError(
                        code=CODE_UNKNOWN_RELATIONSHIP_TYPE,
                        message=f"unknown relationship_type {rtype_raw!r}",
                        location="relationship_type",
                    )
                ]
            )
        try:
            rel = Relationship.model_validate(payload)
        except PydanticValidationError as exc:
            return _report([_map_pydantic_error(e) for e in exc.errors()])

    rule = RELATIONSHIP_CATALOG.get(rel.relationship_type)
    if rule is None:
        return _report(
            [
                ConformanceError(
                    code=CODE_UNKNOWN_RELATIONSHIP_TYPE,
                    message=f"unknown relationship_type {rel.relationship_type!r}",
                    location="relationship_type",
                )
            ]
        )

    # Endpoint type legality.
    if rel.from_entity_type not in rule.source_types:
        errors.append(
            ConformanceError(
                code=CODE_INVALID_SOURCE_TYPE,
                message=(
                    f"{rel.relationship_type} source must be one of "
                    f"{sorted(rule.source_types)}, got {rel.from_entity_type!r}"
                ),
                location="from_entity_type",
            )
        )
    if rel.to_entity_type not in rule.target_types:
        errors.append(
            ConformanceError(
                code=CODE_INVALID_TARGET_TYPE,
                message=(
                    f"{rel.relationship_type} target must be one of "
                    f"{sorted(rule.target_types)}, got {rel.to_entity_type!r}"
                ),
                location="to_entity_type",
            )
        )

    # Self-loop rule.
    if rel.from_entity_id == rel.to_entity_id and not rule.self_loop_allowed:
        errors.append(
            ConformanceError(
                code=CODE_SELF_LOOP_PROHIBITED,
                message=f"{rel.relationship_type} may not connect an entity to itself",
                location="to_entity_id",
            )
        )

    # Dangling endpoints (only when the caller supplies the known-id universe).
    if known_entity_ids is not None:
        known = set(known_entity_ids)
        if rel.from_entity_id not in known:
            errors.append(
                ConformanceError(
                    code=CODE_DANGLING_ENDPOINT,
                    message=f"source entity {rel.from_entity_id!r} does not exist",
                    location="from_entity_id",
                )
            )
        if rel.to_entity_id not in known:
            errors.append(
                ConformanceError(
                    code=CODE_DANGLING_ENDPOINT,
                    message=f"target entity {rel.to_entity_id!r} does not exist",
                    location="to_entity_id",
                )
            )

    # Classification dominance (edge >= both endpoints).
    for label, endpoint_cls in (("source", from_classification), ("target", to_classification)):
        if endpoint_cls is not None and not dominates(rel.classification, endpoint_cls):
            errors.append(
                ConformanceError(
                    code=CODE_CLASSIFICATION_DOMINANCE,
                    message=(
                        f"edge classification {rel.classification.value} is below its "
                        f"{label} endpoint classification {endpoint_cls.value}"
                    ),
                    location="classification",
                )
            )

    # Cardinality (only when the caller supplies sibling edges).
    if existing_edges is not None:
        errors.extend(_check_cardinality(rel, rule.cardinality, list(existing_edges)))

    return _report(errors)


def _check_cardinality(
    rel: Relationship, cardinality: Cardinality, existing: list[tuple[str, str]]
) -> list[ConformanceError]:
    """Cardinality check against sibling edges of the same relationship type.
    `existing` is the set of already-present `(from_id, to_id)` pairs (not
    including this candidate)."""
    errors: list[ConformanceError] = []
    source_limited = cardinality in (Cardinality.ONE_TO_ONE, Cardinality.MANY_TO_ONE)
    target_limited = cardinality in (Cardinality.ONE_TO_ONE, Cardinality.ONE_TO_MANY)

    if source_limited:
        targets_for_source = {t for (f, t) in existing if f == rel.from_entity_id}
        targets_for_source.discard(rel.to_entity_id)
        if targets_for_source:
            errors.append(
                ConformanceError(
                    code=CODE_CARDINALITY_VIOLATION,
                    message=(
                        f"{rel.relationship_type} is {cardinality.value}: source "
                        f"{rel.from_entity_id!r} already links to a different target"
                    ),
                    location="from_entity_id",
                )
            )
    if target_limited:
        sources_for_target = {f for (f, t) in existing if t == rel.to_entity_id}
        sources_for_target.discard(rel.from_entity_id)
        if sources_for_target:
            errors.append(
                ConformanceError(
                    code=CODE_CARDINALITY_VIOLATION,
                    message=(
                        f"{rel.relationship_type} is {cardinality.value}: target "
                        f"{rel.to_entity_id!r} already linked from a different source"
                    ),
                    location="to_entity_id",
                )
            )
    return errors


# --- raising helpers --------------------------------------------------------


def assert_entity_conformant(candidate: Entity | Mapping[str, Any]) -> None:
    report = validate_entity(candidate)
    if not report.ok:
        raise OntologyConformanceError(report.errors)


def assert_relationship_conformant(
    candidate: Relationship | Mapping[str, Any], **context: Any
) -> None:
    report = validate_relationship(candidate, **context)
    if not report.ok:
        raise OntologyConformanceError(report.errors)
