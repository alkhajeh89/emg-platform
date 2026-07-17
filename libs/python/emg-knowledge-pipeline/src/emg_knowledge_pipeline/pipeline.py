"""The Knowledge Ingestion Pipeline orchestrator (FEAT-05-2).

`KnowledgePipeline.ingest(batch, context)` is the end-to-end path:

1. **Validate + build** (`validation.validate_and_build`) — server-assigns
   `owner`/`provenance_reference`/`trust_score`/ids, runs ontology conformance,
   duplicate/dangling/cycle checks. **No persistence before validation
   succeeds**; a failure raises a typed `IngestionValidationError`.
2. **Persist atomically** — stage every new entity then every new relationship
   in a single `GraphTransaction` and `commit()`. Entities before relationships
   is the dependency order. If persistence fails, the transaction rolls back —
   **no partial graph**.
3. **Emit audit contracts** — only after a successful commit, emit one
   `SubmittedAuditEvent` per created mutation to the injected `AuditSink`
   (`entity.created` / `relationship.created`). The sink owns durability and
   never raises merely because Module 6 is briefly unavailable (Sprint 6
   posture). Idempotently-skipped items emit nothing.

`supersede_entity` / `supersede_relationship` are the minimal supersession
primitives that emit the `entity.superseded` / `relationship.superseded` (paired
with the new version's `*.created`) contracts. Full lifecycle management
(proposed→active→retired, current-version resolution) is FEAT-05-5 and is
deliberately not implemented here.
"""

from __future__ import annotations

from emg_audit_client import SubmittedAuditEvent
from emg_ontology import ENTITY_REGISTRY, Entity, LifecycleStatus, Relationship
from emg_ontology.audit import (
    ENTITY_CREATED,
    ENTITY_SUPERSEDED,
    RELATIONSHIP_CREATED,
    RELATIONSHIP_SUPERSEDED,
)

from .audit import build_mutation_event, provenance_reference_for
from .context import IngestionContext
from .errors import GraphPersistenceError, IngestionProblem, IngestionValidationError
from .graph_store import GraphStore
from .requests import EntityIngestionRequest, IngestionBatch, RelationshipIngestionRequest
from .resolver import resolve_relationship_endpoints
from .result import IngestionResult
from .validation import RESERVED_ENTITY_KEYS, validate_and_build


class CollectingAuditSink:
    """A durable-enough, never-raising sink for tests and local development:
    collects emitted events in memory. Satisfies `emg_audit_client.AuditSink`."""

    def __init__(self) -> None:
        self.events: list[SubmittedAuditEvent] = []

    def record(self, event: SubmittedAuditEvent) -> None:
        self.events.append(event)


class KnowledgePipeline:
    """Storage-independent ingestion orchestrator."""

    def __init__(self, store: GraphStore, audit_sink: object | None = None) -> None:
        self._store = store
        # Default to a collecting sink so the pipeline is usable without wiring a
        # live audit service; a real deployment injects a durable AuditSink.
        self._sink = audit_sink if audit_sink is not None else CollectingAuditSink()

    @property
    def audit_sink(self) -> object:
        return self._sink

    def ingest(self, batch: IngestionBatch, context: IngestionContext) -> IngestionResult:
        validated = validate_and_build(batch, context, self._store)

        # Persist atomically; roll back on any failure (no partial graph).
        try:
            with self._store.begin() as tx:
                for entity in validated.new_entities:
                    tx.add_entity(entity)
                for rel in validated.new_relationships:
                    tx.add_relationship(rel)
                tx.commit()
        except Exception as exc:  # noqa: BLE001 - surface as a typed persistence error
            raise GraphPersistenceError(
                f"graph persistence failed and was rolled back: {exc}",
                error_code="GRAPH_PERSISTENCE_ERROR",
            ) from exc

        # Emit audit contracts only after a durable commit.
        emitted: list[str] = []
        for entity in validated.new_entities:
            emitted.append(
                self._emit(context, ENTITY_CREATED, entity.entity_id, entity.entity_type, entity)
            )
        for rel in validated.new_relationships:
            emitted.append(
                self._emit(
                    context, RELATIONSHIP_CREATED, rel.relationship_id, rel.relationship_type, rel
                )
            )

        return IngestionResult(
            correlation_id=context.correlation_id,
            created_entity_ids=tuple(e.entity_id for e in validated.new_entities),
            created_relationship_ids=tuple(r.relationship_id for r in validated.new_relationships),
            skipped_entity_ids=tuple(validated.skipped_entity_ids),
            skipped_relationship_ids=tuple(validated.skipped_relationship_ids),
            emitted_audit_event_ids=tuple(emitted),
        )

    # --- minimal supersession primitives (emit the *.superseded contracts) ---

    def supersede_entity(
        self,
        context: IngestionContext,
        prior_entity_id: str,
        new_request: EntityIngestionRequest,
    ) -> IngestionResult:
        prior = self._store.get_entity(prior_entity_id)
        if prior is None:
            raise IngestionValidationError(
                (
                    IngestionProblem(
                        code="INGESTION_UNKNOWN_ENTITY",
                        message=f"cannot supersede unknown entity {prior_entity_id!r}",
                    ),
                )
            )
        model_cls = ENTITY_REGISTRY[new_request.entity_type]
        new_version = prior.version + 1
        new_id = f"{prior_entity_id}#v{new_version}"
        new_entity: Entity = model_cls(
            entity_id=new_id,
            classification=new_request.classification,
            trust_score=context.assigned_trust_score(),
            provenance_reference=provenance_reference_for(context, ENTITY_CREATED, new_id),
            owner=context.owner,
            lifecycle_status=LifecycleStatus.ACTIVE,
            version=new_version,
            effective_from=new_request.effective_from,
            effective_to=new_request.effective_to,
            supersedes=prior_entity_id,
            **{k: v for k, v in new_request.attributes.items() if k not in RESERVED_ENTITY_KEYS},
        )
        try:
            with self._store.begin() as tx:
                tx.add_entity(new_entity)
                tx.commit()
        except Exception as exc:  # noqa: BLE001
            raise GraphPersistenceError(
                f"supersession persistence failed and was rolled back: {exc}",
                error_code="GRAPH_PERSISTENCE_ERROR",
            ) from exc

        emitted = [
            self._emit(context, ENTITY_SUPERSEDED, prior_entity_id, prior.entity_type, prior),
            self._emit(context, ENTITY_CREATED, new_id, new_entity.entity_type, new_entity),
        ]
        return IngestionResult(
            correlation_id=context.correlation_id,
            created_entity_ids=(new_id,),
            emitted_audit_event_ids=tuple(emitted),
        )

    def supersede_relationship(
        self,
        context: IngestionContext,
        prior_relationship_id: str,
        new_request: RelationshipIngestionRequest,
    ) -> IngestionResult:
        prior = self._store.get_relationship(prior_relationship_id)
        if prior is None:
            raise IngestionValidationError(
                (
                    IngestionProblem(
                        code="INGESTION_UNKNOWN_RELATIONSHIP",
                        message=f"cannot supersede unknown relationship {prior_relationship_id!r}",
                    ),
                )
            )
        from_id, to_id = resolve_relationship_endpoints(context, new_request)
        new_version = prior.version + 1
        new_id = f"{prior_relationship_id}#v{new_version}"
        new_rel = Relationship(
            relationship_id=new_id,
            relationship_type=new_request.relationship_type,
            from_entity_id=from_id,
            from_entity_type=new_request.from_entity_type,
            to_entity_id=to_id,
            to_entity_type=new_request.to_entity_type,
            classification=new_request.classification,
            provenance_reference=provenance_reference_for(context, RELATIONSHIP_CREATED, new_id),
            version=new_version,
            effective_from=new_request.effective_from,
            effective_to=new_request.effective_to,
            supersedes=prior_relationship_id,
        )
        try:
            with self._store.begin() as tx:
                tx.add_relationship(new_rel)
                tx.commit()
        except Exception as exc:  # noqa: BLE001
            raise GraphPersistenceError(
                f"supersession persistence failed and was rolled back: {exc}",
                error_code="GRAPH_PERSISTENCE_ERROR",
            ) from exc

        emitted = [
            self._emit(
                context,
                RELATIONSHIP_SUPERSEDED,
                prior_relationship_id,
                prior.relationship_type,
                prior,
            ),
            self._emit(context, RELATIONSHIP_CREATED, new_id, new_rel.relationship_type, new_rel),
        ]
        return IngestionResult(
            correlation_id=context.correlation_id,
            created_relationship_ids=(new_id,),
            emitted_audit_event_ids=tuple(emitted),
        )

    # --- internals ---

    def _emit(
        self,
        context: IngestionContext,
        action: str,
        subject_id: str,
        subject_type: str,
        subject: Entity | Relationship,
    ) -> str:
        event = build_mutation_event(
            context=context,
            action=action,  # type: ignore[arg-type]
            subject_id=subject_id,
            subject_type=subject_type,
            classification=subject.classification,
        )
        self._sink.record(event)  # type: ignore[attr-defined]
        return event.event_id
