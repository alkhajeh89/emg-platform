from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from emg_common_types import Classification
from emg_errors import ConflictError
from emg_knowledge_graph import (
    BuildRevisionCommand,
    InvalidRevisionCommandError,
    KnowledgeGraphApplication,
    RevisionBuildError,
)
from emg_memory_graph import EMPTY_GRAPH, MergeConflictError
from emg_ontology import Entity, ProvenanceReference, Relationship
from emg_platform_core import (
    GraphStore,
    GraphTransaction,
    InMemoryGraphStore,
    PrincipalRef,
    TenantId,
    TransactionStateError,
    WriteReceipt,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=30)
T2 = T1 + timedelta(days=30)
TENANT_A = TenantId.of("tenant-a")
TENANT_B = TenantId.of("tenant-b")
PRINCIPAL = PrincipalRef.service("knowledge-builder")


def provenance(subject_id: str) -> ProvenanceReference:
    return ProvenanceReference(source_principal="connector-a", event_id=f"event-{subject_id}")


def entity(entity_id: str, entity_type: str = "person") -> Entity:
    return Entity(
        entity_id=entity_id,
        entity_type=entity_type,
        classification=Classification.INTERNAL,
        trust_score=0.9,
        provenance_reference=provenance(entity_id),
        owner="owner-a",
        effective_from=T0,
    )


def relationship(
    relationship_id: str,
    *,
    valid_from: datetime = T0,
    valid_until: datetime | None = None,
    classification: Classification = Classification.INTERNAL,
    supersedes: str | None = None,
) -> Relationship:
    return Relationship(
        relationship_id=relationship_id,
        relationship_type="owns",
        from_entity_id="person-1",
        from_entity_type="person",
        to_entity_id="project-1",
        to_entity_type="project",
        classification=classification,
        provenance_reference=provenance(relationship_id),
        effective_from=valid_from,
        effective_to=valid_until,
        supersedes=supersedes,
    )


def command(
    *,
    tenant: TenantId = TENANT_A,
    principal: PrincipalRef = PRINCIPAL,
    entities: tuple[Entity, ...] = (),
    relationships: tuple[Relationship, ...] = (),
    as_of: datetime = T2,
) -> BuildRevisionCommand:
    return BuildRevisionCommand(
        tenant=tenant,
        principal=principal,
        entities=entities,
        relationships=relationships,
        as_of=as_of,
    )


def test_creates_first_revision_and_maps_actual_receipt_to_result_dto() -> None:
    store = InMemoryGraphStore()
    result = KnowledgeGraphApplication(store).build_revision(
        command(entities=(entity("person-1"),))
    )

    persisted = store.read(TENANT_A)
    assert persisted.node_count == 1
    assert result.tenant == TENANT_A
    assert result.principal is PRINCIPAL
    assert result.content_hash == persisted.content_hash()
    assert result.node_count == 1
    assert result.edge_count == 0
    assert result.nodes_created == 1
    assert not hasattr(result, "receipt")


def test_extends_existing_revision_without_losing_prior_content() -> None:
    store = InMemoryGraphStore()
    app = KnowledgeGraphApplication(store)
    app.build_revision(
        command(
            entities=(entity("person-1"), entity("project-1", "project")),
            relationships=(relationship("rel-1"),),
        )
    )

    result = app.build_revision(command(entities=(entity("person-2"),)))

    persisted = store.read(TENANT_A)
    assert {node.node_id for node in persisted.nodes} == {
        "person-1",
        "person-2",
        "project-1",
    }
    assert {edge.edge_id for edge in persisted.edges} == {"rel-1"}
    assert result.nodes_created == 1


def test_preserves_tenant_isolation() -> None:
    store = InMemoryGraphStore()
    app = KnowledgeGraphApplication(store)
    app.build_revision(command(tenant=TENANT_A, entities=(entity("person-1"),)))
    app.build_revision(command(tenant=TENANT_B, entities=(entity("project-1", "project"),)))

    assert {node.node_id for node in store.read(TENANT_A).nodes} == {"person-1"}
    assert {node.node_id for node in store.read(TENANT_B).nodes} == {"project-1"}


class RecordingStore:
    def __init__(self) -> None:
        self.inner = InMemoryGraphStore()
        self.calls: list[tuple[TenantId, PrincipalRef]] = []

    def read(self, tenant: TenantId):
        return self.inner.read(tenant)

    def write(self, tenant: TenantId, graph, *, principal: PrincipalRef):
        return self.inner.write(tenant, graph, principal=principal)

    def tenants(self) -> tuple[TenantId, ...]:
        return self.inner.tenants()

    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef) -> Iterator[GraphTransaction]:
        self.calls.append((tenant, principal))
        with self.inner.transaction(tenant, principal) as transaction:
            yield transaction


def test_passes_exact_principal_and_tenant_to_transaction() -> None:
    store = RecordingStore()
    principal = PrincipalRef.connector("connector-principal")
    tenant = TenantId.of("tenant-recorded")

    KnowledgeGraphApplication(store).build_revision(
        command(tenant=tenant, principal=principal, entities=(entity("person-1"),))
    )

    assert len(store.calls) == 1
    assert store.calls[0][0] is tenant
    assert store.calls[0][1] is principal


def test_uses_supplied_as_of_for_builder_evidence() -> None:
    store = InMemoryGraphStore()
    supplied = datetime(2030, 5, 6, 7, 8, tzinfo=timezone.utc)

    KnowledgeGraphApplication(store).build_revision(
        command(entities=(entity("person-1"),), as_of=supplied)
    )

    persisted = store.read(TENANT_A)
    assert persisted.node("person-1").updated_at == supplied  # type: ignore[union-attr]
    assert persisted.node("person-1").evidence[0].captured_at == supplied  # type: ignore[union-attr]


def test_deterministic_replay_preserves_hash_and_reports_no_new_objects() -> None:
    store = InMemoryGraphStore()
    app = KnowledgeGraphApplication(store)
    first_command = command(
        entities=(entity("person-1"), entity("project-1", "project")),
        relationships=(relationship("rel-1"),),
    )
    first = app.build_revision(first_command)

    replay = app.build_revision(
        command(
            entities=tuple(reversed(first_command.entities)),
            relationships=first_command.relationships,
        )
    )

    assert replay.content_hash == first.content_hash
    assert replay.nodes_created == 0
    assert replay.edges_created == 0


def test_build_conflict_is_mapped_and_transaction_rolls_back() -> None:
    store = InMemoryGraphStore()
    first = relationship("rel-conflict")
    conflicting = relationship(
        "rel-conflict",
        classification=Classification.CONFIDENTIAL,
    )

    with pytest.raises(RevisionBuildError) as caught:
        KnowledgeGraphApplication(store).build_revision(
            command(
                entities=(entity("person-1"), entity("project-1", "project")),
                relationships=(first, conflicting),
            )
        )

    assert isinstance(caught.value.__cause__, MergeConflictError)
    assert store.read(TENANT_A) == EMPTY_GRAPH


class StageFailure(RuntimeError):
    pass


class StagingTransaction:
    tenant = TENANT_A
    principal = PRINCIPAL

    @property
    def receipt(self) -> WriteReceipt:
        raise TransactionStateError("transaction did not commit")

    def read(self):
        return EMPTY_GRAPH

    def stage(self, graph) -> None:
        raise StageFailure("stage failed")


class StagingFailureStore:
    def __init__(self) -> None:
        self.inner = InMemoryGraphStore()
        self.aborted = False
        self.opened = 0

    def read(self, tenant: TenantId):
        return self.inner.read(tenant)

    def write(self, tenant: TenantId, graph, *, principal: PrincipalRef):
        return self.inner.write(tenant, graph, principal=principal)

    def tenants(self) -> tuple[TenantId, ...]:
        return self.inner.tenants()

    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef):
        self.opened += 1
        try:
            yield StagingTransaction()
        except BaseException:
            self.aborted = True
            raise


def test_staging_failure_rolls_back_and_surfaces_original_error() -> None:
    store = StagingFailureStore()
    assert isinstance(store, GraphStore)

    with pytest.raises(StageFailure, match="stage failed"):
        KnowledgeGraphApplication(store).build_revision(command(entities=(entity("person-1"),)))

    assert store.opened == 1
    assert store.aborted


class SimulatedConflict(ConflictError):
    pass


class ConflictStore(StagingFailureStore):
    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef):
        self.opened += 1
        yield _StagingTransactionThatAccepts()
        raise SimulatedConflict("authoritative head changed")


class _StagingTransactionThatAccepts(StagingTransaction):
    def stage(self, graph) -> None:
        self.staged = graph


def test_optimistic_conflict_surfaces_without_suppression() -> None:
    store = ConflictStore()

    with pytest.raises(SimulatedConflict, match="authoritative head changed"):
        KnowledgeGraphApplication(store).build_revision(command(entities=(entity("person-1"),)))


def test_temporal_relationship_versions_remain_distinct() -> None:
    store = InMemoryGraphStore()
    first = relationship("rel-1", valid_until=T1)
    second = relationship("rel-1#v2", valid_from=T1, supersedes="rel-1")

    KnowledgeGraphApplication(store).build_revision(
        command(
            entities=(entity("person-1"), entity("project-1", "project")),
            relationships=(first, second),
        )
    )

    persisted = store.read(TENANT_A)
    assert {edge.edge_id for edge in persisted.edges} == {"rel-1", "rel-1#v2"}
    assert {item.locator for item in persisted.edge("rel-1").evidence} == {"rel-1"}  # type: ignore[union-attr]
    assert {item.locator for item in persisted.edge("rel-1#v2").evidence} == {  # type: ignore[union-attr]
        "rel-1#v2"
    }


@pytest.mark.parametrize(
    "invalid",
    [
        command(),
        command(entities=(entity("person-1"),), as_of=datetime(2026, 1, 1)),
    ],
)
def test_invalid_command_is_rejected_before_transaction(
    invalid: BuildRevisionCommand,
) -> None:
    store = StagingFailureStore()

    with pytest.raises(InvalidRevisionCommandError):
        KnowledgeGraphApplication(store).build_revision(invalid)

    assert store.opened == 0


def test_command_validate_accepts_valid_command() -> None:
    valid = command(entities=(entity("person-1"),))
    assert valid.validate() is None


@pytest.mark.parametrize(
    "invalid",
    [
        BuildRevisionCommand(
            tenant="tenant-a",  # type: ignore[arg-type]
            principal=PRINCIPAL,
            entities=(entity("person-1"),),
            relationships=(),
            as_of=T2,
        ),
        BuildRevisionCommand(
            tenant=TENANT_A,
            principal="principal",  # type: ignore[arg-type]
            entities=(entity("person-1"),),
            relationships=(),
            as_of=T2,
        ),
        BuildRevisionCommand(
            tenant=TENANT_A,
            principal=PRINCIPAL,
            entities=[entity("person-1")],  # type: ignore[arg-type]
            relationships=(),
            as_of=T2,
        ),
        BuildRevisionCommand(
            tenant=TENANT_A,
            principal=PRINCIPAL,
            entities=("not-an-entity",),  # type: ignore[arg-type]
            relationships=(),
            as_of=T2,
        ),
        BuildRevisionCommand(
            tenant=TENANT_A,
            principal=PRINCIPAL,
            entities=(entity("person-1"),),
            relationships=[],  # type: ignore[arg-type]
            as_of=T2,
        ),
        BuildRevisionCommand(
            tenant=TENANT_A,
            principal=PRINCIPAL,
            entities=(),
            relationships=("not-a-relationship",),  # type: ignore[arg-type]
            as_of=T2,
        ),
        command(),
        BuildRevisionCommand(
            tenant=TENANT_A,
            principal=PRINCIPAL,
            entities=(entity("person-1"),),
            relationships=(),
            as_of="not-a-datetime",  # type: ignore[arg-type]
        ),
        command(entities=(entity("person-1"),), as_of=datetime(2026, 1, 1)),
    ],
)
def test_command_validate_rejects_invalid_fields(
    invalid: BuildRevisionCommand,
) -> None:
    with pytest.raises(InvalidRevisionCommandError):
        invalid.validate()


def test_service_retains_only_command_type_guard() -> None:
    store = StagingFailureStore()

    with pytest.raises(InvalidRevisionCommandError, match="BuildRevisionCommand"):
        KnowledgeGraphApplication(store).build_revision(object())  # type: ignore[arg-type]

    assert store.opened == 0
    assert not hasattr(KnowledgeGraphApplication, "_validate")
