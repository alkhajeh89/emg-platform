"""Contract-focused tests for the Sprint 7.3 query engine (ADR-024, Phase 1).

Phase 1 is application-contracts only: command validation, result DTO shape,
error taxonomy, and package exports. Nothing here reads a graph, opens a
``GraphStore``/``GraphRevisionReader`` transaction, or exercises query
orchestration — those belong to a later implementation phase.
"""

from __future__ import annotations

import dataclasses
import importlib
from datetime import datetime, timezone

import pytest
from emg_common_types import Classification
from emg_knowledge_graph import (
    MAX_QUERY_PAGE_SIZE,
    MAX_QUERY_PROPERTY_PREDICATES,
    MAX_TRAVERSAL_DEPTH,
    EdgeDetails,
    EdgeNotFoundError,
    EdgeQueryResult,
    EntityAttributeHistoryQuery,
    EntityDetails,
    EntityNotFoundError,
    EntityQueryResult,
    EntitySummary,
    GetEdgeQuery,
    GetEntityQuery,
    GraphQueryScope,
    InvalidQueryError,
    InvalidTemporalFilterError,
    KnowledgeGraphApplicationError,
    ListEdgesQuery,
    ListEntitiesQuery,
    ListNeighborsQuery,
    MetadataPredicate,
    NeighborDirection,
    NeighborResult,
    PagedEdgeResult,
    PagedEntityResult,
    PagedNeighborResult,
    PageInfo,
    PathDepthExceededError,
    PathQueryResult,
    PathResult,
    QueryLimitExceededError,
    QueryRevisionContext,
    RevisionNotFoundError,
    ShortestPathQuery,
    UnsupportedHistoryCapabilityError,
)
from emg_memory_graph import EdgeDirection
from emg_platform_core import TenantId

TENANT = TenantId.of("tenant-a")
T_AWARE = datetime(2026, 1, 1, tzinfo=timezone.utc)
T_NAIVE = datetime(2026, 1, 1)


def scope(revision_number: int | None = None) -> GraphQueryScope:
    return GraphQueryScope(tenant=TENANT, revision_number=revision_number)


# --- DTO immutability ---------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        GraphQueryScope(tenant=TENANT),
        EntitySummary(
            node_id="n1",
            node_type="person",
            label="Alice",
            confidence=0.9,
            classification=Classification.INTERNAL,
            created_at=T_AWARE,
            updated_at=T_AWARE,
        ),
        PageInfo(limit=50, returned_count=0, next_cursor=None, has_more=False),
        PathResult(
            node_ids=(),
            edge_ids=(),
            length=0,
            found=False,
            node_classifications=(),
            edge_classifications=(),
        ),
        QueryRevisionContext(revision_number=1, committed_at=T_AWARE, is_current_head=True),
        MetadataPredicate(key="k", value="v"),
    ],
)
def test_dto_instances_are_frozen(instance: object) -> None:
    field_name = dataclasses.fields(instance)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, field_name, getattr(instance, field_name))


# --- Exact DTO field shapes ----------------------------------------------------


def _field_names(cls: type) -> tuple[str, ...]:
    return tuple(f.name for f in dataclasses.fields(cls))


def test_graph_query_scope_has_only_tenant_and_revision_number() -> None:
    assert _field_names(GraphQueryScope) == ("tenant", "revision_number")


def test_query_revision_context_field_shape() -> None:
    assert _field_names(QueryRevisionContext) == (
        "revision_number",
        "committed_at",
        "is_current_head",
    )


def test_entity_summary_field_shape() -> None:
    assert _field_names(EntitySummary) == (
        "node_id",
        "node_type",
        "label",
        "confidence",
        "classification",
        "created_at",
        "updated_at",
    )


def test_entity_details_field_shape() -> None:
    assert _field_names(EntityDetails) == (
        "summary",
        "source",
        "aliases",
        "evidence",
        "histories",
        "metadata",
    )


def test_edge_details_field_shape() -> None:
    # ADR-026 Revision 2, Group D7: `classification` added (projection only).
    assert _field_names(EdgeDetails) == (
        "edge_id",
        "edge_type",
        "source_id",
        "target_id",
        "direction",
        "confidence",
        "classification",
        "validity",
        "created_at",
        "updated_at",
        "evidence",
    )


def test_neighbor_result_field_shape() -> None:
    # ADR-026 Revision 2, Group D7: `edge_classification` added (the
    # traversed edge's own classification, distinct from `entity.classification`).
    assert _field_names(NeighborResult) == (
        "entity",
        "via_edge_id",
        "edge_type",
        "confidence",
        "direction",
        "edge_classification",
    )


def test_path_result_field_shape() -> None:
    # ADR-026 Revision 2, Group D7: `node_classifications`/`edge_classifications`
    # added, index-aligned with node_ids/edge_ids.
    assert _field_names(PathResult) == (
        "node_ids",
        "edge_ids",
        "length",
        "found",
        "node_classifications",
        "edge_classifications",
    )


def test_page_info_field_shape() -> None:
    assert _field_names(PageInfo) == ("limit", "returned_count", "next_cursor", "has_more")


@pytest.mark.parametrize("cls", [PagedEntityResult, PagedEdgeResult, PagedNeighborResult])
def test_paged_result_shapes_carry_exactly_items_page_info_revision_context(
    cls: type,
) -> None:
    assert _field_names(cls) == ("items", "page_info", "revision_context")


@pytest.mark.parametrize("cls", [EntityQueryResult, EdgeQueryResult, PathQueryResult])
def test_single_item_result_shapes_carry_exactly_item_revision_context(cls: type) -> None:
    assert _field_names(cls) == ("item", "revision_context")


# --- GraphQueryScope: current-head / historical forms + revision validation ---


def test_scope_current_head_form_validates() -> None:
    assert scope(revision_number=None).validate() is None


def test_scope_historical_revision_form_validates() -> None:
    assert scope(revision_number=7).validate() is None


@pytest.mark.parametrize("bad_revision", [0, -1, True, "5", 1.5])
def test_scope_rejects_invalid_revision_number(bad_revision: object) -> None:
    with pytest.raises(InvalidQueryError):
        GraphQueryScope(tenant=TENANT, revision_number=bad_revision).validate()  # type: ignore[arg-type]


def test_scope_rejects_non_tenant_id() -> None:
    with pytest.raises(InvalidQueryError):
        GraphQueryScope(tenant="tenant-a", revision_number=None).validate()  # type: ignore[arg-type]


# --- Page-size bounds -----------------------------------------------------------


def test_page_size_lower_bound_accepted() -> None:
    ListEntitiesQuery(scope=scope(), limit=1).validate()


def test_page_size_upper_bound_accepted() -> None:
    assert MAX_QUERY_PAGE_SIZE == 200
    ListEntitiesQuery(scope=scope(), limit=200).validate()


def test_page_size_over_limit_rejected() -> None:
    with pytest.raises(QueryLimitExceededError):
        ListEntitiesQuery(scope=scope(), limit=201).validate()


def test_page_size_below_lower_bound_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ListEntitiesQuery(scope=scope(), limit=0).validate()


# --- Path depth bounds -----------------------------------------------------------


def test_path_depth_lower_bound_accepted() -> None:
    ShortestPathQuery(scope=scope(), from_node_id="a", to_node_id="b", maximum_depth=1).validate()


def test_path_depth_upper_bound_accepted() -> None:
    assert MAX_TRAVERSAL_DEPTH == 64
    ShortestPathQuery(scope=scope(), from_node_id="a", to_node_id="b", maximum_depth=64).validate()


def test_path_depth_over_limit_rejected() -> None:
    with pytest.raises(PathDepthExceededError):
        ShortestPathQuery(
            scope=scope(), from_node_id="a", to_node_id="b", maximum_depth=65
        ).validate()


def test_path_depth_below_lower_bound_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ShortestPathQuery(
            scope=scope(), from_node_id="a", to_node_id="b", maximum_depth=0
        ).validate()


# --- valid_at timezone enforcement -----------------------------------------------


def test_timezone_aware_valid_at_accepted() -> None:
    EntityAttributeHistoryQuery(
        scope=scope(), node_id="n1", attribute="owner", valid_at=T_AWARE
    ).validate()


def test_timezone_naive_valid_at_rejected() -> None:
    with pytest.raises(InvalidTemporalFilterError):
        EntityAttributeHistoryQuery(
            scope=scope(), node_id="n1", attribute="owner", valid_at=T_NAIVE
        ).validate()


def test_list_edges_naive_valid_at_rejected() -> None:
    with pytest.raises(InvalidTemporalFilterError):
        ListEdgesQuery(scope=scope(), valid_at=T_NAIVE).validate()


def test_list_neighbors_naive_valid_at_rejected() -> None:
    with pytest.raises(InvalidTemporalFilterError):
        ListNeighborsQuery(
            scope=scope(), node_id="n1", direction=NeighborDirection.BOTH, valid_at=T_NAIVE
        ).validate()


# --- Exact scalar property predicate validation ----------------------------------


def test_scalar_predicates_accepted() -> None:
    ListEntitiesQuery(
        scope=scope(),
        node_type="person",
        source="connector-a",
        confidence=0.5,
        classification=Classification.INTERNAL,
    ).validate()


def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ListEntitiesQuery(scope=scope(), confidence=1.5).validate()


def test_classification_wrong_type_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ListEntitiesQuery(scope=scope(), classification="INTERNAL").validate()  # type: ignore[arg-type]


def test_node_type_wrong_type_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ListEntitiesQuery(scope=scope(), node_type=123).validate()  # type: ignore[arg-type]


# --- Metadata predicate validation ------------------------------------------------


def test_metadata_predicate_accepted() -> None:
    MetadataPredicate(key="team", value="platform").validate()


def test_metadata_predicate_rejects_empty_key() -> None:
    with pytest.raises(InvalidQueryError):
        MetadataPredicate(key="", value="platform").validate()


def test_metadata_predicate_rejects_non_string_value() -> None:
    with pytest.raises(InvalidQueryError):
        MetadataPredicate(key="team", value=123).validate()  # type: ignore[arg-type]


# --- Maximum of 8 predicates ------------------------------------------------------


def test_maximum_of_eight_predicates_accepted() -> None:
    assert MAX_QUERY_PROPERTY_PREDICATES == 8
    predicates = tuple(MetadataPredicate(key=f"k{i}", value=f"v{i}") for i in range(5))
    ListEntitiesQuery(
        scope=scope(),
        node_type="person",
        source="connector-a",
        confidence=0.5,
        metadata_predicates=predicates,
    ).validate()  # 3 scalar + 5 metadata = 8


def test_more_than_eight_predicates_rejected() -> None:
    predicates = tuple(MetadataPredicate(key=f"k{i}", value=f"v{i}") for i in range(6))
    with pytest.raises(QueryLimitExceededError):
        ListEntitiesQuery(
            scope=scope(),
            node_type="person",
            source="connector-a",
            confidence=0.5,
            metadata_predicates=predicates,
        ).validate()  # 3 scalar + 6 metadata = 9


# --- Cursor validation -------------------------------------------------------------


def test_empty_before_node_id_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ListEntitiesQuery(scope=scope(), before_node_id="").validate()


def test_empty_before_edge_id_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ListEdgesQuery(scope=scope(), before_edge_id="").validate()


def test_control_character_cursor_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        ListEntitiesQuery(scope=scope(), before_node_id="node\x00-1").validate()


def test_get_entity_rejects_empty_node_id() -> None:
    with pytest.raises(InvalidQueryError):
        GetEntityQuery(scope=scope(), node_id="").validate()


def test_get_edge_rejects_empty_edge_id() -> None:
    with pytest.raises(InvalidQueryError):
        GetEdgeQuery(scope=scope(), edge_id="").validate()


# --- Direction filter reuses the existing domain EdgeDirection enum ----------------


def test_list_edges_direction_accepts_domain_edge_direction() -> None:
    ListEdgesQuery(scope=scope(), direction=EdgeDirection.DIRECTED).validate()


def test_list_edges_direction_rejects_foreign_type() -> None:
    with pytest.raises(InvalidQueryError):
        ListEdgesQuery(scope=scope(), direction="directed").validate()  # type: ignore[arg-type]


def test_list_neighbors_requires_neighbor_direction_enum() -> None:
    with pytest.raises(InvalidQueryError):
        ListNeighborsQuery(
            scope=scope(), node_id="n1", direction="both"  # type: ignore[arg-type]
        ).validate()


# --- Deferred capabilities remain absent -------------------------------------------

_ALL_NEW_COMMAND_CLASSES: tuple[type, ...] = (
    GraphQueryScope,
    GetEntityQuery,
    ListEntitiesQuery,
    GetEdgeQuery,
    ListEdgesQuery,
    ListNeighborsQuery,
    ShortestPathQuery,
    EntityAttributeHistoryQuery,
    MetadataPredicate,
)

_FORBIDDEN_FIELD_SUBSTRINGS = (
    "text",
    "fuzzy",
    "tokenized",
    "dsl",
    "expression",
    "operator",
    "cypher",
    "as_of",
    "offset",
    "page_number",
    "all_paths",
    "k_shortest",
    "max_paths",
    "weighted",
)


@pytest.mark.parametrize("cls", _ALL_NEW_COMMAND_CLASSES)
def test_free_text_and_dsl_and_all_path_and_offset_fields_are_absent(cls: type) -> None:
    names = " ".join(_field_names(cls)).lower()
    for forbidden in _FORBIDDEN_FIELD_SUBSTRINGS:
        assert forbidden not in names, f"{cls.__name__} unexpectedly declares {forbidden!r}"


def test_graph_query_scope_has_no_as_of_or_timestamp_selector() -> None:
    field_types = {f.name: f.type for f in dataclasses.fields(GraphQueryScope)}
    assert "as_of" not in field_types
    assert "datetime" not in str(field_types["revision_number"])


def test_shortest_path_query_exposes_no_multi_path_option() -> None:
    names = set(_field_names(ShortestPathQuery))
    assert names == {"scope", "from_node_id", "to_node_id", "maximum_depth"}


def test_no_generic_dict_any_typed_predicate_field() -> None:
    for cls in _ALL_NEW_COMMAND_CLASSES:
        for f in dataclasses.fields(cls):
            type_str = str(f.type)
            assert "dict" not in type_str.lower(), f"{cls.__name__}.{f.name} is dict-typed"
            assert "Any" not in type_str, f"{cls.__name__}.{f.name} is Any-typed"


# --- Error inheritance --------------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls",
    [
        InvalidQueryError,
        EntityNotFoundError,
        EdgeNotFoundError,
        QueryLimitExceededError,
        InvalidTemporalFilterError,
        PathDepthExceededError,
    ],
)
def test_new_query_errors_inherit_from_application_error(error_cls: type) -> None:
    assert issubclass(error_cls, KnowledgeGraphApplicationError)


def test_reused_errors_still_inherit_from_application_error() -> None:
    assert issubclass(RevisionNotFoundError, KnowledgeGraphApplicationError)
    assert issubclass(UnsupportedHistoryCapabilityError, KnowledgeGraphApplicationError)


def test_no_cross_tenant_access_error_is_defined() -> None:
    errors_module = importlib.import_module("emg_knowledge_graph.errors")
    assert not hasattr(errors_module, "CrossTenantAccessError")


# --- Package exports ------------------------------------------------------------------


def test_new_contract_types_are_exported_from_package_root() -> None:
    pkg = importlib.import_module("emg_knowledge_graph")
    for name in (
        "GraphQueryScope",
        "NeighborDirection",
        "MetadataPredicate",
        "GetEntityQuery",
        "ListEntitiesQuery",
        "GetEdgeQuery",
        "ListEdgesQuery",
        "ListNeighborsQuery",
        "ShortestPathQuery",
        "EntityAttributeHistoryQuery",
        "QueryRevisionContext",
        "EntitySummary",
        "EntityDetails",
        "EdgeDetails",
        "NeighborResult",
        "PathResult",
        "PageInfo",
        "PagedEntityResult",
        "PagedEdgeResult",
        "PagedNeighborResult",
        "EntityQueryResult",
        "EdgeQueryResult",
        "PathQueryResult",
        "InvalidQueryError",
        "EntityNotFoundError",
        "EdgeNotFoundError",
        "QueryLimitExceededError",
        "InvalidTemporalFilterError",
        "PathDepthExceededError",
        "MAX_QUERY_PAGE_SIZE",
        "MAX_QUERY_PROPERTY_PREDICATES",
        "MAX_TRAVERSAL_DEPTH",
    ):
        assert hasattr(pkg, name), f"emg_knowledge_graph is missing export {name!r}"
        assert name in pkg.__all__, f"{name!r} missing from emg_knowledge_graph.__all__"


def test_max_traversal_depth_matches_domain_constant() -> None:
    from emg_memory_graph import MAX_TRAVERSAL_DEPTH as domain_max_depth

    assert MAX_TRAVERSAL_DEPTH == domain_max_depth == 64
