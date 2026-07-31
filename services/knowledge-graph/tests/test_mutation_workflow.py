from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest
from emg_common_types import Classification
from emg_errors import ConflictError, PermissionDeniedError
from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    EntityReplacementAction,
    InvalidMutationCommandError,
    KnowledgeGraphApplication,
    MergeEntitiesCommand,
    MutationAuthorizationConflictError,
    MutationAuthorizationPreflight,
    MutationBuildError,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
    ResourceMetadata,
)
from emg_knowledge_lifecycle import InvalidTransitionError, VersionState
from emg_memory_graph import (
    MemoryEdge,
    MemoryGraph,
    MemoryGraphBuilder,
    MemoryNode,
    MergeConflictError,
)
from emg_ontology import Entity, ProvenanceReference, Relationship
from emg_platform_core import InMemoryGraphStore, PrincipalRef, TenantId

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=30)
TENANT = TenantId.of("tenant-mutations")
PRINCIPAL = PrincipalRef.service("mutation-writer")


def provenance(subject_id: str) -> ProvenanceReference:
    return ProvenanceReference(source_principal="connector-a", event_id=f"event-{subject_id}")


def entity(entity_id: str, *, classification: Classification = Classification.INTERNAL) -> Entity:
    return Entity(
        entity_id=entity_id,
        entity_type="person",
        classification=classification,
        trust_score=0.9,
        provenance_reference=provenance(entity_id),
        owner="owner-a",
        effective_from=T0,
    )


def relationship(relationship_id: str, source_id: str, target_id: str) -> Relationship:
    return Relationship(
        relationship_id=relationship_id,
        relationship_type="reports-to",
        from_entity_id=source_id,
        from_entity_type="person",
        to_entity_id=target_id,
        to_entity_type="person",
        classification=Classification.INTERNAL,
        provenance_reference=provenance(relationship_id),
        effective_from=T0,
    )


def seed(
    store: InMemoryGraphStore,
    *,
    entities: tuple[Entity, ...],
    relationships: tuple[Relationship, ...] = (),
) -> MemoryGraph:
    graph = (
        MemoryGraphBuilder()
        .from_ontology(
            entities=entities,
            relationships=relationships,
            as_of=T0,
        )
        .graph
    )
    store.write(TENANT, graph, principal=PRINCIPAL)
    return graph


def create_command(**overrides: object) -> CreateEntityCommand:
    values: dict[str, object] = {
        "tenant": TENANT,
        "principal": PRINCIPAL,
        "entity": entity("entity-1"),
        "idempotency_key": "mutation-1",
        "as_of": T1,
    }
    values.update(overrides)
    return CreateEntityCommand(**values)  # type: ignore[arg-type]


def test_create_entity_commits_immutable_revision_and_generates_audit_intent() -> None:
    store = InMemoryGraphStore()
    result = KnowledgeGraphApplication(store).create_entity(create_command())

    persisted = store.read(TENANT)
    assert persisted.node("entity-1") is not None
    assert result.content_hash == persisted.content_hash()
    assert result.revision_number == 1
    assert result.nodes_created == 1
    assert result.audit_intents[0].action == "create"
    assert result.audit_intents[0].resource_id == "entity-1"
    assert result.audit_intents[0].classification is Classification.INTERNAL
    assert result.audit_intents[0].content_hash == result.content_hash


def test_create_command_is_frozen_and_validates_before_authorization() -> None:
    command = create_command()
    with pytest.raises(FrozenInstanceError):
        command.idempotency_key = "changed"  # type: ignore[misc]

    seen: list[CreateEntityCommand] = []
    app = KnowledgeGraphApplication(
        InMemoryGraphStore(), mutation_authorization_hook=lambda item: seen.append(item)
    )
    bad = create_command(as_of=datetime(2026, 1, 1))

    with pytest.raises(InvalidMutationCommandError, match="timezone-aware"):
        app.create_entity(bad)

    assert seen == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant": "tenant"}, "TenantId"),
        ({"principal": "principal"}, "PrincipalRef"),
        ({"entity": object()}, "ontology Entity"),
        ({"idempotency_key": ""}, "idempotency_key"),
        ({"idempotency_key": "x" * 257}, "max length"),
        ({"as_of": "now"}, "datetime"),
    ],
)
def test_create_command_validation(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidMutationCommandError, match=message):
        create_command(**overrides).validate()


def test_authorization_hook_runs_once_before_transaction_and_can_fail_closed() -> None:
    class Denied(RuntimeError):
        pass

    seen: list[CreateEntityCommand] = []

    def deny(command: object) -> None:
        assert isinstance(command, CreateEntityCommand)
        seen.append(command)
        raise Denied("denied")

    store = InMemoryGraphStore()
    with pytest.raises(Denied):
        KnowledgeGraphApplication(store, mutation_authorization_hook=deny).create_entity(
            create_command()
        )

    assert seen == [create_command()]
    assert store.tenants() == ()


class _MetadataReader:
    def __init__(self, metadata: ResourceMetadata | None = None) -> None:
        self.metadata = metadata

    def read_entity(self, tenant: TenantId, entity_id: str) -> ResourceMetadata | None:
        return self.metadata

    def read_relationship(self, tenant: TenantId, relationship_id: str) -> ResourceMetadata | None:
        return self.metadata


class _ToggleEvaluator:
    def __init__(self) -> None:
        self.allowed = True

    def authorize(self, command: object, context: object) -> None:
        if not self.allowed:
            raise PermissionDeniedError("permission was revoked")


def test_stale_authorization_metadata_cannot_commit() -> None:
    store = InMemoryGraphStore()
    seed(
        store,
        entities=(entity("entity-1", classification=Classification.CONFIDENTIAL),),
    )
    current = store.read(TENANT).node("entity-1")
    assert current is not None
    replacement = MemoryNode.model_validate({**current.model_dump(), "updated_at": T1})
    preflight = MutationAuthorizationPreflight(
        _MetadataReader(
            ResourceMetadata(
                resource_type="knowledge-graph.entity",
                resource_id="entity-1",
                classification=Classification.INTERNAL,
                owner="owner-a",
            )
        ),
        _ToggleEvaluator(),
    )
    app = KnowledgeGraphApplication(store, mutation_authorization_hook=preflight)

    with pytest.raises(MutationAuthorizationConflictError):
        app.replace_entity(
            ReplaceEntityCommand(
                tenant=TENANT,
                principal=PRINCIPAL,
                replacement=replacement,
                action=EntityReplacementAction.UPDATE,
                idempotency_key="stale-auth",
                as_of=T1,
            )
        )

    assert (
        store.read(TENANT).content_hash()
        == seed(
            InMemoryGraphStore(),
            entities=(entity("entity-1", classification=Classification.CONFIDENTIAL),),
        ).content_hash()
    )


def test_replay_is_denied_after_current_permission_is_revoked() -> None:
    evaluator = _ToggleEvaluator()
    preflight = MutationAuthorizationPreflight(_MetadataReader(), evaluator)
    app = KnowledgeGraphApplication(
        InMemoryGraphStore(),
        mutation_authorization_hook=preflight,
    )
    command = create_command(idempotency_key="reauthorize-replay")
    first = app.create_entity(command)
    assert first.replayed is False

    evaluator.allowed = False
    with pytest.raises(PermissionDeniedError, match="revoked"):
        app.create_entity(command)


def test_replace_entity_reuses_lifecycle_validation_and_preserves_base() -> None:
    store = InMemoryGraphStore()
    base = seed(store, entities=(entity("entity-1"),))
    current = base.node("entity-1")
    assert current is not None
    replacement = MemoryNode.model_validate(
        {
            **current.model_dump(),
            "lifecycle_status": VersionState.SUPERSEDED,
            "updated_at": T1,
        }
    )

    result = KnowledgeGraphApplication(store).replace_entity(
        ReplaceEntityCommand(
            tenant=TENANT,
            principal=PRINCIPAL,
            replacement=replacement,
            action=EntityReplacementAction.RETIRE,
            idempotency_key="mutation-retire",
            as_of=T1,
            reason="duplicate record",
        )
    )

    assert base.node("entity-1") is current
    assert current.lifecycle_status is VersionState.ACTIVE
    assert store.read(TENANT).node("entity-1") == replacement
    assert result.audit_intents[0].reason == "duplicate record"
    assert result.audit_intents[0].action == "retire"


def test_invalid_lifecycle_transition_surfaces_from_adr029_and_rolls_back() -> None:
    store = InMemoryGraphStore()
    base = seed(store, entities=(entity("entity-1"),))
    current = base.node("entity-1")
    assert current is not None
    invalid = MemoryNode.model_validate(
        {
            **current.model_dump(),
            "lifecycle_status": VersionState.ARCHIVED,
            "updated_at": T1,
        }
    )

    with pytest.raises(InvalidTransitionError):
        KnowledgeGraphApplication(store).replace_entity(
            ReplaceEntityCommand(
                tenant=TENANT,
                principal=PRINCIPAL,
                replacement=invalid,
                action=EntityReplacementAction.RETIRE,
                idempotency_key="mutation-invalid-transition",
                as_of=T1,
                reason="retire",
            )
        )

    assert store.read(TENANT) == base


def test_replace_entity_reason_requirements_are_command_owned() -> None:
    node = (
        MemoryGraphBuilder()
        .from_ontology(entities=(entity("entity-1"),), as_of=T0)
        .graph.node("entity-1")
    )
    assert node is not None
    command = ReplaceEntityCommand(
        tenant=TENANT,
        principal=PRINCIPAL,
        replacement=node,
        action=EntityReplacementAction.RETIRE,
        idempotency_key="mutation-retire",
        as_of=T1,
        reason=" ",
    )

    with pytest.raises(InvalidMutationCommandError, match="reason"):
        command.validate()


def test_replace_relationship_preserves_endpoints_and_wraps_domain_conflict() -> None:
    store = InMemoryGraphStore()
    base = seed(
        store,
        entities=(entity("entity-1"), entity("entity-2"), entity("entity-3")),
        relationships=(relationship("rel-1", "entity-1", "entity-2"),),
    )
    current = base.edge("rel-1")
    assert current is not None
    replacement = MemoryEdge.model_validate(
        {
            **current.model_dump(),
            "classification": Classification.CONFIDENTIAL,
            "updated_at": T1,
        }
    )
    result = KnowledgeGraphApplication(store).replace_relationship(
        ReplaceRelationshipCommand(
            tenant=TENANT,
            principal=PRINCIPAL,
            replacement=replacement,
            idempotency_key="mutation-rel-update",
            as_of=T1,
        )
    )
    assert store.read(TENANT).edge("rel-1") == replacement
    assert result.audit_intents[0].related_resource_ids == ("entity-1", "entity-2")

    changed_endpoint = MemoryEdge.model_validate(
        {**replacement.model_dump(), "target_id": "entity-3"}
    )
    with pytest.raises(MutationBuildError) as caught:
        KnowledgeGraphApplication(store).replace_relationship(
            ReplaceRelationshipCommand(
                tenant=TENANT,
                principal=PRINCIPAL,
                replacement=changed_endpoint,
                idempotency_key="mutation-rel-conflict",
                as_of=T1,
            )
        )
    assert isinstance(caught.value.__cause__, MergeConflictError)


def test_close_relationship_uses_adr029_validity_closure() -> None:
    store = InMemoryGraphStore()
    seed(
        store,
        entities=(entity("entity-1"), entity("entity-2")),
        relationships=(relationship("rel-1", "entity-1", "entity-2"),),
    )

    result = KnowledgeGraphApplication(store).close_relationship(
        CloseRelationshipCommand(
            tenant=TENANT,
            principal=PRINCIPAL,
            edge_id="rel-1",
            idempotency_key="mutation-rel-close",
            as_of=T1,
            reason="relationship ended",
        )
    )

    closed = store.read(TENANT).edge("rel-1")
    assert closed is not None
    assert closed.validity.valid_until == T1
    assert result.audit_intents[0].action == "retire"
    assert result.audit_intents[0].reason == "relationship ended"


def test_merge_entities_delegates_complete_merge_to_adr029() -> None:
    store = InMemoryGraphStore()
    base = seed(
        store,
        entities=(entity("survivor"), entity("source"), entity("other")),
        relationships=(relationship("rel-1", "source", "other"),),
    )

    result = KnowledgeGraphApplication(store).merge_entities(
        MergeEntitiesCommand(
            tenant=TENANT,
            principal=PRINCIPAL,
            survivor_id="survivor",
            source_ids=("source",),
            idempotency_key="mutation-merge",
            as_of=T1,
            reason="same real-world person",
        )
    )

    persisted = store.read(TENANT)
    survivor = persisted.node("survivor")
    source = persisted.node("source")
    assert survivor is not None and survivor.supersedes == ("source",)
    assert source is not None and source.lifecycle_status is VersionState.SUPERSEDED
    assert base.node("source").lifecycle_status is VersionState.ACTIVE  # type: ignore[union-attr]
    assert result.edges_created == 1
    assert result.audit_intents[0].related_resource_ids == ("source",)


def test_merge_command_rejects_invalid_shape_before_domain_execution() -> None:
    command = MergeEntitiesCommand(
        tenant=TENANT,
        principal=PRINCIPAL,
        survivor_id="survivor",
        source_ids=("source", "source"),
        idempotency_key="mutation-merge",
        as_of=T1,
        reason="duplicate",
    )
    with pytest.raises(InvalidMutationCommandError, match="unique"):
        command.validate()


def test_merge_command_maps_non_string_source_to_command_error() -> None:
    command = MergeEntitiesCommand(
        tenant=TENANT,
        principal=PRINCIPAL,
        survivor_id="survivor",
        source_ids=(object(),),  # type: ignore[arg-type]
        idempotency_key="mutation-merge",
        as_of=T1,
        reason="invalid source",
    )
    with pytest.raises(InvalidMutationCommandError, match="source_id"):
        command.validate()


def test_optimistic_conflict_surfaces_without_retry_or_audit_result() -> None:
    class ConflictingStore:
        def __init__(self, graph: MemoryGraph) -> None:
            self.graph = graph
            self.transaction_calls = 0

        def transaction(self, tenant: TenantId, principal: PrincipalRef):
            self.transaction_calls += 1
            inner = InMemoryGraphStore()
            inner.write(tenant, self.graph, principal=principal)
            context = inner.transaction(tenant, principal)

            class ConflictContext:
                def __enter__(self):
                    return context.__enter__()

                def __exit__(self, exc_type, exc, traceback):
                    context.__exit__(exc_type, exc, traceback)
                    raise ConflictError("concurrent revision")

            return ConflictContext()

    store = ConflictingStore(MemoryGraph())
    with pytest.raises(ConflictError, match="concurrent revision"):
        KnowledgeGraphApplication(store).create_entity(create_command())  # type: ignore[arg-type]

    assert store.transaction_calls == 1
