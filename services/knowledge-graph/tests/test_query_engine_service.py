"""Sprint 7.3 Phase 2: KnowledgeGraphApplication query-engine service tests.

Exercises the seven orchestration methods (``get_entity``, ``list_entities``,
``get_edge``, ``list_edges``, ``list_neighbors``, ``find_shortest_path``,
``get_entity_history``) against ``InMemoryGraphStore``/its
``GraphRevisionReader`` implementation. Test graphs are built directly from
``MemoryNode``/``MemoryEdge`` and committed via ``store.write(...)`` rather
than through ``BuildRevisionCommand``/ontology objects — this gives full,
direct control over metadata, temporal histories, edge validity, and
classification, none of which the ontology-to-node mapping (``from_ontology``)
currently threads through.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from emg_common_types import Classification
from emg_knowledge_graph import (
    EdgeNotFoundError,
    EntityAttributeHistoryQuery,
    EntityNotFoundError,
    GetEdgeQuery,
    GetEntityQuery,
    GraphQueryScope,
    InvalidQueryError,
    InvalidTemporalFilterError,
    KnowledgeGraphApplication,
    ListEdgesQuery,
    ListEntitiesQuery,
    ListNeighborsQuery,
    MetadataPredicate,
    NeighborDirection,
    PathDepthExceededError,
    RevisionNotFoundError,
    ShortestPathQuery,
    UnsupportedHistoryCapabilityError,
)
from emg_memory_graph import (
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    MemoryEdge,
    MemoryGraph,
    MemoryNode,
    Metadata,
    TemporalFact,
    TemporalHistory,
    TemporalValidity,
)
from emg_platform_core import InMemoryGraphStore, PrincipalRef, TenantId

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=30)
T2 = T1 + timedelta(days=30)
TENANT_A = TenantId.of("tenant-a")
TENANT_B = TenantId.of("tenant-b")
PRINCIPAL = PrincipalRef.service("kg-query-tests")


# --- graph-construction helpers (bypassing the ontology/builder layer for
# direct control over metadata/histories/temporal validity) -----------------


def _evidence(locator: str, *, captured_at: datetime = T0) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef.create(
            source=EvidenceSource.MANUAL_ENTRY,
            locator=locator,
            source_principal="tester",
            captured_at=captured_at,
        ),
    )


def make_node(
    node_id: str,
    node_type: str = "person",
    *,
    label: str | None = None,
    confidence: float = 0.9,
    classification: Classification = Classification.INTERNAL,
    source: str = "tester",
    created_at: datetime = T0,
    updated_at: datetime = T0,
    metadata: Metadata | None = None,
    histories: tuple[TemporalHistory, ...] = (),
) -> MemoryNode:
    return MemoryNode(
        node_id=node_id,
        node_type=node_type,
        label=label or node_id,
        created_at=created_at,
        updated_at=updated_at,
        source=source,
        confidence=confidence,
        classification=classification,
        evidence=_evidence(node_id, captured_at=created_at),
        metadata=metadata or Metadata(),
        histories=histories,
    )


def make_edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    *,
    edge_type: str = "owns",
    direction: EdgeDirection = EdgeDirection.DIRECTED,
    confidence: float = 0.9,
    valid_from: datetime = T0,
    valid_until: datetime | None = None,
    created_at: datetime = T0,
    updated_at: datetime = T0,
) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        direction=direction,
        evidence=_evidence(edge_id, captured_at=created_at),
        confidence=confidence,
        validity=TemporalValidity(valid_from=valid_from, valid_until=valid_until),
        created_at=created_at,
        updated_at=updated_at,
    )


def _owner_history() -> TemporalHistory:
    return TemporalHistory(
        attribute="owner",
        facts=(
            TemporalFact(
                value="alice",
                validity=TemporalValidity(valid_from=T0, valid_until=T1),
                evidence=_evidence("owner-alice", captured_at=T0),
                recorded_at=T0,
            ),
            TemporalFact(
                value="bob",
                validity=TemporalValidity(valid_from=T1, valid_until=None),
                evidence=_evidence("owner-bob", captured_at=T1),
                recorded_at=T1,
            ),
        ),
    )


def _seed(store: InMemoryGraphStore, tenant: TenantId, graph: MemoryGraph) -> None:
    store.write(tenant, graph, principal=PRINCIPAL)


def _app(
    store: InMemoryGraphStore | None = None,
) -> tuple[KnowledgeGraphApplication, InMemoryGraphStore]:
    store = store or InMemoryGraphStore()
    return KnowledgeGraphApplication(store, revision_reader=store), store


def _base_graph() -> MemoryGraph:
    """person-1 --owns--> project-1 (open-ended); person-2 --owns--> project-1
    (closed at T1, so inactive from T1 onward); person-3 unconnected."""
    person1 = make_node(
        "person-1",
        "person",
        confidence=0.9,
        classification=Classification.INTERNAL,
        metadata=Metadata.from_mapping({"team": "alpha"}),
        histories=(_owner_history(),),
    )
    person2 = make_node(
        "person-2", "person", confidence=0.4, classification=Classification.CONFIDENTIAL
    )
    project1 = make_node("project-1", "project", confidence=0.9)
    rel1 = make_edge("rel-1", "person-1", "project-1", edge_type="owns", valid_from=T0)
    rel2 = make_edge(
        "rel-2", "person-2", "project-1", edge_type="owns", valid_from=T0, valid_until=T1
    )
    return MemoryGraph(nodes=(person1, person2, project1), edges=(rel1, rel2))


def _seeded_app() -> tuple[KnowledgeGraphApplication, InMemoryGraphStore]:
    app, store = _app()
    _seed(store, TENANT_A, _base_graph())
    return app, store


# --- get_entity ---------------------------------------------------------


def test_get_entity_current_head_found() -> None:
    app, store = _seeded_app()
    result = app.get_entity(
        GetEntityQuery(scope=GraphQueryScope(tenant=TENANT_A), node_id="person-1")
    )

    assert result.item.summary.node_id == "person-1"
    assert result.item.summary.node_type == "person"
    assert result.item.summary.confidence == 0.9
    assert result.item.summary.classification == Classification.INTERNAL
    assert result.item.metadata.get("team") == "alpha"
    assert result.item.histories[0].attribute == "owner"
    assert result.revision_context.is_current_head is True
    assert result.revision_context.revision_number == 1


def test_get_entity_mapping_correctness_full_fields() -> None:
    app, _ = _seeded_app()
    details = app.get_entity(
        GetEntityQuery(scope=GraphQueryScope(tenant=TENANT_A), node_id="person-1")
    ).item

    assert details.source == "tester"
    assert details.aliases == ()
    assert len(details.evidence) == 1
    assert details.evidence[0].locator == "person-1"


def test_get_entity_not_found() -> None:
    app, _ = _seeded_app()
    with pytest.raises(EntityNotFoundError):
        app.get_entity(GetEntityQuery(scope=GraphQueryScope(tenant=TENANT_A), node_id="ghost"))


def test_get_entity_historical_revision() -> None:
    app, store = _app()
    _seed(store, TENANT_A, MemoryGraph(nodes=(make_node("person-1"),)))
    _seed(
        store,
        TENANT_A,
        MemoryGraph(nodes=(make_node("person-1"), make_node("person-2"))),
    )

    # person-2 did not exist at revision 1.
    with pytest.raises(EntityNotFoundError):
        app.get_entity(
            GetEntityQuery(
                scope=GraphQueryScope(tenant=TENANT_A, revision_number=1), node_id="person-2"
            )
        )

    result = app.get_entity(
        GetEntityQuery(
            scope=GraphQueryScope(tenant=TENANT_A, revision_number=1), node_id="person-1"
        )
    )
    assert result.revision_context.revision_number == 1
    assert result.revision_context.is_current_head is False


def test_get_entity_unknown_revision_number_is_typed() -> None:
    app, _ = _seeded_app()
    with pytest.raises(RevisionNotFoundError):
        app.get_entity(
            GetEntityQuery(
                scope=GraphQueryScope(tenant=TENANT_A, revision_number=999), node_id="person-1"
            )
        )


def test_get_entity_requires_revision_reader() -> None:
    store = InMemoryGraphStore()
    _seed(store, TENANT_A, _base_graph())
    app = KnowledgeGraphApplication(store)  # no revision_reader

    with pytest.raises(UnsupportedHistoryCapabilityError):
        app.get_entity(GetEntityQuery(scope=GraphQueryScope(tenant=TENANT_A), node_id="person-1"))


def test_get_entity_rejects_wrong_query_type() -> None:
    app, _ = _seeded_app()
    with pytest.raises(InvalidQueryError, match="GetEntityQuery"):
        app.get_entity(object())  # type: ignore[arg-type]


def test_get_entity_current_head_with_no_committed_revision_is_typed() -> None:
    app, _ = _app()
    with pytest.raises(RevisionNotFoundError):
        app.get_entity(GetEntityQuery(scope=GraphQueryScope(tenant=TENANT_A), node_id="person-1"))


def test_get_entity_cross_tenant_lookup_not_found() -> None:
    app, store = _seeded_app()
    _seed(store, TENANT_B, MemoryGraph(nodes=(make_node("person-9"),)))

    with pytest.raises(EntityNotFoundError):
        app.get_entity(GetEntityQuery(scope=GraphQueryScope(tenant=TENANT_A), node_id="person-9"))


# --- list_entities --------------------------------------------------------


def test_list_entities_filters_by_type() -> None:
    app, _ = _seeded_app()
    result = app.list_entities(
        ListEntitiesQuery(scope=GraphQueryScope(tenant=TENANT_A), node_type="project")
    )
    assert [item.node_id for item in result.items] == ["project-1"]


def test_list_entities_filters_by_classification() -> None:
    app, _ = _seeded_app()
    result = app.list_entities(
        ListEntitiesQuery(
            scope=GraphQueryScope(tenant=TENANT_A), classification=Classification.CONFIDENTIAL
        )
    )
    assert [item.node_id for item in result.items] == ["person-2"]


def test_list_entities_filters_by_exact_confidence() -> None:
    app, _ = _seeded_app()
    result = app.list_entities(
        ListEntitiesQuery(scope=GraphQueryScope(tenant=TENANT_A), confidence=0.4)
    )
    assert [item.node_id for item in result.items] == ["person-2"]


def test_list_entities_filters_by_metadata_predicate() -> None:
    app, _ = _seeded_app()
    result = app.list_entities(
        ListEntitiesQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            metadata_predicates=(MetadataPredicate(key="team", value="alpha"),),
        )
    )
    assert [item.node_id for item in result.items] == ["person-1"]


def test_list_entities_combined_filters_are_additive() -> None:
    app, _ = _seeded_app()
    result = app.list_entities(
        ListEntitiesQuery(
            scope=GraphQueryScope(tenant=TENANT_A), node_type="person", confidence=0.4
        )
    )
    assert [item.node_id for item in result.items] == ["person-2"]


def test_list_entities_pagination_forward_progress() -> None:
    app, store = _app()
    _seed(
        store,
        TENANT_A,
        MemoryGraph(nodes=tuple(make_node(f"n-{i}") for i in range(5))),
    )

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        page = app.list_entities(
            ListEntitiesQuery(
                scope=GraphQueryScope(tenant=TENANT_A), limit=2, before_node_id=cursor
            )
        )
        seen.extend(item.node_id for item in page.items)
        if not page.page_info.has_more:
            break
        cursor = page.page_info.next_cursor

    assert seen == [f"n-{i}" for i in range(5)]


def test_list_entities_page_info_shape() -> None:
    app, store = _app()
    _seed(store, TENANT_A, MemoryGraph(nodes=tuple(make_node(f"n-{i}") for i in range(3))))

    page = app.list_entities(ListEntitiesQuery(scope=GraphQueryScope(tenant=TENANT_A), limit=2))
    assert page.page_info.limit == 2
    assert page.page_info.returned_count == 2
    assert page.page_info.has_more is True
    assert page.page_info.next_cursor == "n-1"

    last_page = app.list_entities(
        ListEntitiesQuery(scope=GraphQueryScope(tenant=TENANT_A), limit=2, before_node_id="n-1")
    )
    assert last_page.page_info.has_more is False
    assert last_page.page_info.next_cursor is None


def test_list_entities_tenant_isolation() -> None:
    app, store = _seeded_app()
    _seed(store, TENANT_B, MemoryGraph(nodes=(make_node("person-only-in-b"),)))

    result = app.list_entities(ListEntitiesQuery(scope=GraphQueryScope(tenant=TENANT_A)))
    assert "person-only-in-b" not in {item.node_id for item in result.items}


def test_list_entities_empty_tenant_returns_empty_page_not_error() -> None:
    app, store = _app()
    _seed(store, TENANT_A, MemoryGraph())  # committed, but empty

    result = app.list_entities(ListEntitiesQuery(scope=GraphQueryScope(tenant=TENANT_A)))
    assert result.items == ()
    assert result.page_info.has_more is False


# --- get_edge / list_edges ------------------------------------------------


def test_get_edge_found_and_mapped() -> None:
    app, _ = _seeded_app()
    result = app.get_edge(GetEdgeQuery(scope=GraphQueryScope(tenant=TENANT_A), edge_id="rel-1"))
    assert result.item.edge_id == "rel-1"
    assert result.item.source_id == "person-1"
    assert result.item.target_id == "project-1"
    assert result.item.direction == EdgeDirection.DIRECTED
    assert result.item.validity.valid_from == T0


def test_get_edge_not_found() -> None:
    app, _ = _seeded_app()
    with pytest.raises(EdgeNotFoundError):
        app.get_edge(GetEdgeQuery(scope=GraphQueryScope(tenant=TENANT_A), edge_id="ghost-edge"))


def test_list_edges_filters_by_type() -> None:
    app, store = _app()
    _seed(
        store,
        TENANT_A,
        MemoryGraph(
            nodes=(make_node("a"), make_node("b"), make_node("c")),
            edges=(
                make_edge("e-owns", "a", "b", edge_type="owns"),
                make_edge("e-approves", "b", "c", edge_type="approved"),
            ),
        ),
    )
    result = app.list_edges(
        ListEdgesQuery(scope=GraphQueryScope(tenant=TENANT_A), edge_type="approved")
    )
    assert [item.edge_id for item in result.items] == ["e-approves"]


def test_list_edges_filters_by_direction() -> None:
    app, store = _app()
    _seed(
        store,
        TENANT_A,
        MemoryGraph(
            nodes=(make_node("a"), make_node("b")),
            edges=(make_edge("e-undirected", "a", "b", direction=EdgeDirection.UNDIRECTED),),
        ),
    )
    result = app.list_edges(
        ListEdgesQuery(scope=GraphQueryScope(tenant=TENANT_A), direction=EdgeDirection.DIRECTED)
    )
    assert result.items == ()

    result = app.list_edges(
        ListEdgesQuery(scope=GraphQueryScope(tenant=TENANT_A), direction=EdgeDirection.UNDIRECTED)
    )
    assert [item.edge_id for item in result.items] == ["e-undirected"]


def test_list_edges_valid_at_excludes_closed_interval() -> None:
    app, _ = _seeded_app()
    # rel-2 (person-2 -> project-1) closes at T1; rel-1 stays open.
    result = app.list_edges(ListEdgesQuery(scope=GraphQueryScope(tenant=TENANT_A), valid_at=T2))
    assert [item.edge_id for item in result.items] == ["rel-1"]

    result_before_close = app.list_edges(
        ListEdgesQuery(scope=GraphQueryScope(tenant=TENANT_A), valid_at=T0)
    )
    assert {item.edge_id for item in result_before_close.items} == {"rel-1", "rel-2"}


def test_list_edges_naive_valid_at_rejected() -> None:
    app, _ = _seeded_app()
    query = ListEdgesQuery(scope=GraphQueryScope(tenant=TENANT_A), valid_at=datetime(2026, 1, 1))
    with pytest.raises(InvalidTemporalFilterError):
        app.list_edges(query)


# --- list_neighbors --------------------------------------------------------


def test_list_neighbors_outgoing() -> None:
    app, _ = _seeded_app()
    result = app.list_neighbors(
        ListNeighborsQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="person-1",
            direction=NeighborDirection.OUTGOING,
        )
    )
    assert [n.entity.node_id for n in result.items] == ["project-1"]
    assert result.items[0].via_edge_id == "rel-1"
    assert result.items[0].edge_type == "owns"


def test_list_neighbors_incoming() -> None:
    app, _ = _seeded_app()
    result = app.list_neighbors(
        ListNeighborsQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="project-1",
            direction=NeighborDirection.INCOMING,
        )
    )
    assert {n.entity.node_id for n in result.items} == {"person-1", "person-2"}


def test_list_neighbors_both() -> None:
    app, _ = _seeded_app()
    result = app.list_neighbors(
        ListNeighborsQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="project-1",
            direction=NeighborDirection.BOTH,
        )
    )
    assert {n.entity.node_id for n in result.items} == {"person-1", "person-2"}


def test_list_neighbors_valid_at_excludes_inactive_edge() -> None:
    app, _ = _seeded_app()
    result = app.list_neighbors(
        ListNeighborsQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="project-1",
            direction=NeighborDirection.INCOMING,
            valid_at=T2,
        )
    )
    assert {n.entity.node_id for n in result.items} == {"person-1"}


def test_list_neighbors_subject_not_found() -> None:
    app, _ = _seeded_app()
    with pytest.raises(EntityNotFoundError):
        app.list_neighbors(
            ListNeighborsQuery(
                scope=GraphQueryScope(tenant=TENANT_A),
                node_id="ghost",
                direction=NeighborDirection.BOTH,
            )
        )


def test_list_neighbors_pagination() -> None:
    app, store = _app()
    hub = make_node("hub")
    leaves = tuple(make_node(f"leaf-{i}") for i in range(4))
    edges = tuple(make_edge(f"e-{i}", "hub", f"leaf-{i}", edge_type="relates_to") for i in range(4))
    _seed(store, TENANT_A, MemoryGraph(nodes=(hub, *leaves), edges=edges))

    page = app.list_neighbors(
        ListNeighborsQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="hub",
            direction=NeighborDirection.OUTGOING,
            limit=2,
        )
    )
    assert page.page_info.has_more is True
    assert len(page.items) == 2

    next_page = app.list_neighbors(
        ListNeighborsQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="hub",
            direction=NeighborDirection.OUTGOING,
            limit=2,
            before_edge_id=page.page_info.next_cursor,
        )
    )
    assert next_page.page_info.has_more is False
    first_ids = {n.via_edge_id for n in page.items}
    second_ids = {n.via_edge_id for n in next_page.items}
    assert not first_ids & second_ids


# --- find_shortest_path ----------------------------------------------------


def test_find_shortest_path_found() -> None:
    app, _ = _seeded_app()
    result = app.find_shortest_path(
        ShortestPathQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            from_node_id="person-1",
            to_node_id="person-2",
        )
    )
    assert result.item.found is True
    assert result.item.node_ids[0] == "person-1"
    assert result.item.node_ids[-1] == "person-2"
    assert result.item.length == 2


def test_find_shortest_path_unreachable() -> None:
    app, store = _app()
    _seed(
        store,
        TENANT_A,
        MemoryGraph(nodes=(make_node("island-a"), make_node("island-b"))),
    )
    result = app.find_shortest_path(
        ShortestPathQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            from_node_id="island-a",
            to_node_id="island-b",
        )
    )
    assert result.item.found is False
    assert result.item.node_ids == ()
    assert result.item.edge_ids == ()


def test_find_shortest_path_endpoint_not_found() -> None:
    app, _ = _seeded_app()
    with pytest.raises(EntityNotFoundError):
        app.find_shortest_path(
            ShortestPathQuery(
                scope=GraphQueryScope(tenant=TENANT_A),
                from_node_id="person-1",
                to_node_id="ghost",
            )
        )


def test_find_shortest_path_exceeding_maximum_depth_reports_not_found() -> None:
    app, _ = _seeded_app()
    # person-1 -> project-1 -> person-2 is 2 hops; cap at 1 to force the
    # over-depth path.
    result = app.find_shortest_path(
        ShortestPathQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            from_node_id="person-1",
            to_node_id="person-2",
            maximum_depth=1,
        )
    )
    assert result.item.found is False


def test_find_shortest_path_rejects_depth_above_ceiling() -> None:
    """Distinct from ``test_find_shortest_path_exceeding_maximum_depth_reports_not_found``:
    that test covers an actual BFS-found path exceeding a *valid* (<=
    ``MAX_TRAVERSAL_DEPTH``) requested ``maximum_depth``, reported as
    ``found=False`` (ADR-024 §15). This test covers requesting a
    ``maximum_depth`` above ``MAX_TRAVERSAL_DEPTH`` itself, rejected by
    command validation (``ShortestPathQuery.validate()``) before any graph
    snapshot is acquired, per ADR-024 §15/§17."""
    app, _ = _seeded_app()
    with pytest.raises(PathDepthExceededError):
        app.find_shortest_path(
            ShortestPathQuery(
                scope=GraphQueryScope(tenant=TENANT_A),
                from_node_id="person-1",
                to_node_id="person-2",
                maximum_depth=65,
            )
        )


def test_find_shortest_path_same_node() -> None:
    app, _ = _seeded_app()
    result = app.find_shortest_path(
        ShortestPathQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            from_node_id="person-1",
            to_node_id="person-1",
        )
    )
    assert result.item.found is True
    assert result.item.length == 0


# --- get_entity_history ----------------------------------------------------


def test_get_entity_history_returns_fact_at_moment() -> None:
    app, _ = _seeded_app()
    result = app.get_entity_history(
        EntityAttributeHistoryQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="person-1",
            attribute="owner",
            valid_at=T0 + timedelta(days=1),
        )
    )
    assert result.item is not None
    assert result.item.value == "alice"


def test_get_entity_history_reflects_change_after_transition() -> None:
    app, _ = _seeded_app()
    result = app.get_entity_history(
        EntityAttributeHistoryQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="person-1",
            attribute="owner",
            valid_at=T1 + timedelta(days=1),
        )
    )
    assert result.item is not None
    assert result.item.value == "bob"


def test_get_entity_history_no_value_before_first_interval() -> None:
    app, _ = _seeded_app()
    result = app.get_entity_history(
        EntityAttributeHistoryQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="person-1",
            attribute="owner",
            valid_at=T0 - timedelta(days=1),
        )
    )
    assert result.item is None


def test_get_entity_history_unknown_attribute_returns_none() -> None:
    app, _ = _seeded_app()
    result = app.get_entity_history(
        EntityAttributeHistoryQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="person-1",
            attribute="does-not-exist",
            valid_at=T0,
        )
    )
    assert result.item is None


def test_get_entity_history_entity_not_found() -> None:
    app, _ = _seeded_app()
    with pytest.raises(EntityNotFoundError):
        app.get_entity_history(
            EntityAttributeHistoryQuery(
                scope=GraphQueryScope(tenant=TENANT_A),
                node_id="ghost",
                attribute="owner",
                valid_at=T0,
            )
        )


def test_get_entity_history_naive_valid_at_rejected() -> None:
    app, _ = _seeded_app()
    query = EntityAttributeHistoryQuery(
        scope=GraphQueryScope(tenant=TENANT_A),
        node_id="person-1",
        attribute="owner",
        valid_at=datetime(2026, 1, 2),
    )
    with pytest.raises(InvalidTemporalFilterError):
        app.get_entity_history(query)


def test_get_entity_history_historical_revision() -> None:
    app, store = _app()
    _seed(store, TENANT_A, MemoryGraph(nodes=(make_node("p", histories=(_owner_history(),)),)))
    _seed(store, TENANT_A, MemoryGraph(nodes=(make_node("p"),)))  # rev 2: history dropped

    historical = app.get_entity_history(
        EntityAttributeHistoryQuery(
            scope=GraphQueryScope(tenant=TENANT_A, revision_number=1),
            node_id="p",
            attribute="owner",
            valid_at=T0,
        )
    )
    assert historical.item is not None
    assert historical.item.value == "alice"

    current = app.get_entity_history(
        EntityAttributeHistoryQuery(
            scope=GraphQueryScope(tenant=TENANT_A),
            node_id="p",
            attribute="owner",
            valid_at=T0,
        )
    )
    assert current.item is None
