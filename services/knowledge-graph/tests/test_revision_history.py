from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from emg_common_types import Classification
from emg_errors import ConflictError
from emg_knowledge_graph import (
    BuildRevisionCommand,
    CompareRevisionsQuery,
    GetRevisionQuery,
    InvalidHistoryQueryError,
    InvalidRevisionCommandError,
    KnowledgeGraphApplication,
    ListRevisionsQuery,
    RestoreRevisionCommand,
    RevisionNotFoundError,
    UnsupportedHistoryCapabilityError,
)
from emg_ontology import Entity, ProvenanceReference, Relationship
from emg_platform_core import (
    InMemoryGraphStore,
    PrincipalRef,
    TenantId,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=30)
TENANT_A = TenantId.of("tenant-a")
TENANT_B = TenantId.of("tenant-b")
PRINCIPAL = PrincipalRef.service("knowledge-builder")
RESTORER = PrincipalRef.service("restorer")


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
    supersedes: str | None = None,
) -> Relationship:
    return Relationship(
        relationship_id=relationship_id,
        relationship_type="owns",
        from_entity_id="person-1",
        from_entity_type="person",
        to_entity_id="project-1",
        to_entity_type="project",
        classification=Classification.INTERNAL,
        provenance_reference=provenance(relationship_id),
        effective_from=valid_from,
        effective_to=valid_until,
        supersedes=supersedes,
    )


def build_command(
    *,
    tenant: TenantId = TENANT_A,
    entities: tuple[Entity, ...] = (),
    relationships: tuple[Relationship, ...] = (),
    as_of: datetime = T0,
) -> BuildRevisionCommand:
    return BuildRevisionCommand(
        tenant=tenant,
        principal=PRINCIPAL,
        entities=entities,
        relationships=relationships,
        as_of=as_of,
    )


def _app(
    store: InMemoryGraphStore | None = None,
) -> tuple[KnowledgeGraphApplication, InMemoryGraphStore]:
    store = store or InMemoryGraphStore()
    return KnowledgeGraphApplication(store, revision_reader=store), store


# --- list_revisions ------------------------------------------------------


def test_list_revisions_empty_history() -> None:
    app, _ = _app()
    assert app.list_revisions(ListRevisionsQuery(tenant=TENANT_A)) == ()


def test_list_revisions_first_revision() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))

    summaries = app.list_revisions(ListRevisionsQuery(tenant=TENANT_A))
    assert len(summaries) == 1
    assert summaries[0].revision_number == 1
    assert summaries[0].parent_hash is None
    assert summaries[0].principal == PRINCIPAL


def test_list_revisions_multiple_revision_ordering() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))
    app.build_revision(build_command(entities=(entity("person-3"),)))

    summaries = app.list_revisions(ListRevisionsQuery(tenant=TENANT_A))
    assert [s.revision_number for s in summaries] == [3, 2, 1]


def test_list_revisions_pagination() -> None:
    app, _ = _app()
    for suffix in ("1", "2", "3"):
        app.build_revision(build_command(entities=(entity(f"person-{suffix}"),)))

    page = app.list_revisions(ListRevisionsQuery(tenant=TENANT_A, limit=2))
    assert [s.revision_number for s in page] == [3, 2]

    next_page = app.list_revisions(
        ListRevisionsQuery(tenant=TENANT_A, limit=2, before_revision_number=2)
    )
    assert [s.revision_number for s in next_page] == [1]


def test_list_revisions_does_not_load_graphs() -> None:
    app, store = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    summaries = app.list_revisions(ListRevisionsQuery(tenant=TENANT_A))
    assert not hasattr(summaries[0], "graph")


# --- invalid queries rejected before store interaction -------------------


class _CountingStore:
    def __init__(self, inner: InMemoryGraphStore) -> None:
        self.inner = inner
        self.list_calls = 0
        self.read_calls = 0

    def read(self, tenant: TenantId):
        return self.inner.read(tenant)

    def write(self, tenant, graph, *, principal):
        return self.inner.write(tenant, graph, principal=principal)

    def tenants(self):
        return self.inner.tenants()

    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef) -> Iterator[object]:
        with self.inner.transaction(tenant, principal) as txn:
            yield txn

    def list_revisions(self, tenant, *, limit=50, before_revision_number=None):
        self.list_calls += 1
        return self.inner.list_revisions(
            tenant, limit=limit, before_revision_number=before_revision_number
        )

    def read_revision(self, tenant, revision_number):
        self.read_calls += 1
        return self.inner.read_revision(tenant, revision_number)


@pytest.mark.parametrize(
    "query",
    [
        ListRevisionsQuery(tenant=TENANT_A, limit=0),
        ListRevisionsQuery(tenant=TENANT_A, limit=10_000),
        ListRevisionsQuery(tenant=TENANT_A, before_revision_number=0),
        GetRevisionQuery(tenant=TENANT_A, revision_number=0),
        CompareRevisionsQuery(tenant=TENANT_A, from_revision_number=0, to_revision_number=1),
    ],
)
def test_invalid_queries_rejected_before_reader_interaction(query: object) -> None:
    inner = InMemoryGraphStore()
    counting = _CountingStore(inner)
    app = KnowledgeGraphApplication(counting, revision_reader=counting)  # type: ignore[arg-type]

    with pytest.raises(InvalidHistoryQueryError):
        if isinstance(query, ListRevisionsQuery):
            app.list_revisions(query)
        elif isinstance(query, GetRevisionQuery):
            app.get_revision(query)
        else:
            app.compare_revisions(query)  # type: ignore[arg-type]

    assert counting.list_calls == 0
    assert counting.read_calls == 0


def test_restore_command_rejected_before_store_interaction() -> None:
    inner = InMemoryGraphStore()
    counting = _CountingStore(inner)
    app = KnowledgeGraphApplication(counting, revision_reader=counting)  # type: ignore[arg-type]

    with pytest.raises(InvalidRevisionCommandError):
        app.restore_revision(
            RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=0)
        )
    assert counting.read_calls == 0


def test_history_methods_require_revision_reader() -> None:
    store = InMemoryGraphStore()
    app = KnowledgeGraphApplication(store)  # no revision_reader supplied

    with pytest.raises(UnsupportedHistoryCapabilityError):
        app.list_revisions(ListRevisionsQuery(tenant=TENANT_A))


# --- get_revision ---------------------------------------------------------


def test_get_revision_historical_non_head() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))

    details = app.get_revision(GetRevisionQuery(tenant=TENANT_A, revision_number=1))
    assert details.summary.revision_number == 1
    assert {n.node_id for n in details.graph.nodes} == {"person-1"}


def test_get_revision_not_found_is_typed() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))

    with pytest.raises(RevisionNotFoundError):
        app.get_revision(GetRevisionQuery(tenant=TENANT_A, revision_number=999))


def test_get_revision_cross_tenant_lookup_not_found() -> None:
    app, _ = _app()
    app.build_revision(build_command(tenant=TENANT_A, entities=(entity("person-1"),)))
    app.build_revision(build_command(tenant=TENANT_B, entities=(entity("person-2"),)))
    app.build_revision(build_command(tenant=TENANT_B, entities=(entity("person-3"),)))

    # revision 2 exists for TENANT_B (two builds) but TENANT_A only has
    # revision 1 -- the lookup for A must not leak B's data or existence.
    with pytest.raises(RevisionNotFoundError):
        app.get_revision(GetRevisionQuery(tenant=TENANT_A, revision_number=2))
    # sanity: it does exist for TENANT_B
    assert app.get_revision(GetRevisionQuery(tenant=TENANT_B, revision_number=2)) is not None


# --- compare_revisions ------------------------------------------------------


def test_compare_revisions_self_comparison_returns_empty_diff() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))

    diff = app.compare_revisions(
        CompareRevisionsQuery(tenant=TENANT_A, from_revision_number=1, to_revision_number=1)
    )
    assert diff.diff.is_empty


def test_compare_revisions_forward_reports_additions() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))

    diff = app.compare_revisions(
        CompareRevisionsQuery(tenant=TENANT_A, from_revision_number=1, to_revision_number=2)
    )
    assert diff.diff.added_nodes == ("person-2",)
    assert diff.diff.removed_nodes == ()


def test_compare_revisions_reverse_reports_removals() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))

    diff = app.compare_revisions(
        CompareRevisionsQuery(tenant=TENANT_A, from_revision_number=2, to_revision_number=1)
    )
    assert diff.diff.removed_nodes == ("person-2",)
    assert diff.diff.added_nodes == ()


def test_compare_revisions_node_and_edge_changes() -> None:
    app, _ = _app()
    app.build_revision(
        build_command(
            entities=(entity("person-1"), entity("project-1", "project")),
            relationships=(relationship("rel-1"),),
        )
    )
    app.build_revision(
        build_command(
            entities=(entity("person-2"),),
        )
    )

    diff = app.compare_revisions(
        CompareRevisionsQuery(tenant=TENANT_A, from_revision_number=1, to_revision_number=2)
    )
    assert diff.diff.added_nodes == ("person-2",)
    assert diff.diff.added_edges == ()
    assert diff.diff.removed_edges == ()


def test_compare_revisions_temporal_edge_identity() -> None:
    app, _ = _app()
    first = relationship("rel-1", valid_until=T1)
    second = relationship("rel-1#v2", valid_from=T1, supersedes="rel-1")
    app.build_revision(
        build_command(
            entities=(entity("person-1"), entity("project-1", "project")),
            relationships=(first,),
            as_of=T0,
        )
    )
    app.build_revision(
        build_command(
            entities=(entity("person-1"), entity("project-1", "project")),
            relationships=(first, second),
            as_of=T1,
        )
    )

    diff = app.compare_revisions(
        CompareRevisionsQuery(tenant=TENANT_A, from_revision_number=1, to_revision_number=2)
    )
    assert diff.diff.added_edges == ("rel-1#v2",)
    assert "rel-1" not in diff.diff.removed_edges


def test_compare_revisions_not_found() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    with pytest.raises(RevisionNotFoundError):
        app.compare_revisions(
            CompareRevisionsQuery(tenant=TENANT_A, from_revision_number=1, to_revision_number=99)
        )


# --- restore_revision --------------------------------------------------------


def test_restore_creates_a_new_revision() -> None:
    app, store = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))

    result = app.restore_revision(
        RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
    )

    assert result.revision_created is True
    assert result.revision_number == 3
    assert result.source_revision_number == 1
    current = store.read(TENANT_A)
    assert {n.node_id for n in current.nodes} == {"person-1"}


def test_restore_source_revision_remains_unchanged() -> None:
    app, store = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))

    before = store.read_revision(TENANT_A, 1)
    app.restore_revision(
        RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
    )
    after = store.read_revision(TENANT_A, 1)

    assert before.graph.content_hash() == after.graph.content_hash()
    assert before.metadata == after.metadata


def test_restore_principal_attribution() -> None:
    app, store = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))

    app.restore_revision(
        RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
    )

    new_head = store.read_revision(TENANT_A, 3)
    assert new_head.metadata.principal == RESTORER
    # the historical source revision's own principal is untouched.
    source = store.read_revision(TENANT_A, 1)
    assert source.metadata.principal == PRINCIPAL


def test_restore_preserves_temporal_fields_exactly() -> None:
    app, store = _app()
    app.build_revision(
        build_command(
            entities=(entity("person-1"), entity("project-1", "project")),
            relationships=(relationship("rel-1", valid_until=T1),),
            as_of=T0,
        )
    )
    app.build_revision(build_command(entities=(entity("person-2"),)))

    before = store.read_revision(TENANT_A, 1).graph.edge("rel-1")
    app.restore_revision(
        RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
    )
    restored_edge = store.read(TENANT_A).edge("rel-1")

    assert restored_edge is not None
    assert before is not None
    assert restored_edge.validity.valid_from == before.validity.valid_from
    assert restored_edge.validity.valid_until == before.validity.valid_until


def test_restore_current_revision_is_no_op() -> None:
    app, store = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))

    result = app.restore_revision(
        RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
    )

    assert result.revision_created is False
    assert result.revision_number == 1
    assert result.source_revision_number == 1


def test_restore_no_op_returns_current_head_revision_number() -> None:
    app, store = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    app.build_revision(build_command(entities=(entity("person-2"),)))

    result = app.restore_revision(
        RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=2)
    )
    assert result.revision_number == 2
    assert result.revision_created is False


def test_restore_no_op_committed_at_is_head_committed_at() -> None:
    app, store = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    head_before = store.list_revisions(TENANT_A)[0]

    result = app.restore_revision(
        RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
    )
    assert result.committed_at == head_before.created_at


def test_restore_not_found() -> None:
    app, _ = _app()
    app.build_revision(build_command(entities=(entity("person-1"),)))
    with pytest.raises(RevisionNotFoundError):
        app.restore_revision(
            RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=99)
        )


class _StagingFailureStore:
    """A GraphStore double whose transaction always yields a transaction
    object whose `stage()` raises — used to verify restore rolls back and
    surfaces the failure without suppression."""

    def __init__(self, source_graph: object) -> None:
        self._source_graph = source_graph
        self.opened = 0
        self.aborted = False

    def read(self, tenant: TenantId):
        raise NotImplementedError

    def write(self, tenant, graph, *, principal):
        raise NotImplementedError

    def tenants(self):
        return ()

    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef) -> Iterator[object]:
        self.opened += 1

        class _Txn:
            tenant_ = tenant
            principal_ = principal

            def stage(self, graph: object) -> None:
                raise RuntimeError("stage failed")

        try:
            yield _Txn()
        except BaseException:
            self.aborted = True
            raise


def test_restore_rollback_on_staging_failure() -> None:
    inner = InMemoryGraphStore()
    reader_app, reader_store = _app(inner)
    reader_app.build_revision(build_command(entities=(entity("person-1"),)))

    failing_store = _StagingFailureStore(None)
    app = KnowledgeGraphApplication(failing_store, revision_reader=reader_store)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="stage failed"):
        app.restore_revision(
            RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
        )
    assert failing_store.opened == 1
    assert failing_store.aborted


class SimulatedConflict(ConflictError):
    pass


class _ConflictStore:
    def __init__(self, reader: InMemoryGraphStore) -> None:
        self._reader = reader
        self.opened = 0

    def read(self, tenant: TenantId):
        return self._reader.read(tenant)

    def write(self, tenant, graph, *, principal):
        raise NotImplementedError

    def tenants(self):
        return ()

    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef) -> Iterator[object]:
        self.opened += 1

        class _Txn:
            def stage(self, graph: object) -> None:
                return None

        yield _Txn()
        raise SimulatedConflict("authoritative head changed")


def test_restore_optimistic_conflict_passes_through_unsuppressed() -> None:
    inner = InMemoryGraphStore()
    reader_app, reader_store = _app(inner)
    reader_app.build_revision(build_command(entities=(entity("person-1"),)))

    conflict_store = _ConflictStore(reader_store)
    app = KnowledgeGraphApplication(conflict_store, revision_reader=reader_store)  # type: ignore[arg-type]

    with pytest.raises(SimulatedConflict, match="authoritative head changed"):
        app.restore_revision(
            RestoreRevisionCommand(tenant=TENANT_A, principal=RESTORER, source_revision_number=1)
        )
