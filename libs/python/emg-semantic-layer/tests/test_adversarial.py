"""Adversarial tests for the Sprint 12 review fixes (FEAT-05-4).

Covers genuine nested immutability, input-dict aliasing, the new collection/offset
bounds, control/NUL/CR-LF/bidi identifier rejection, extreme integers, filter
nesting/width at and above the limit, deterministic planning, the documented
result-forgery trust boundary, and executor-protocol misuse.
"""

from __future__ import annotations

import emg_semantic_layer as sl
import pytest
from emg_semantic_layer import (
    FilterCondition,
    FilterOperator,
    NodeSelector,
    PageInfo,
    Pagination,
    SemanticFilter,
    SemanticGraph,
    SemanticNode,
    SemanticOrdering,
    SemanticProjection,
    SemanticQuery,
    SemanticQueryError,
    SemanticQueryExecutor,
    SemanticRelationship,
    SemanticResult,
    SortKey,
    TraversalStep,
    plan,
)
from emg_semantic_layer.limits import (
    MAX_FILTER_CONDITIONS,
    MAX_FILTER_DEPTH,
    MAX_FILTER_GROUPS,
    MAX_ORDERING_KEYS,
    MAX_PAGE_OFFSET,
    MAX_PROJECTION_FIELDS,
    MAX_SELECTOR_IDS,
)
from pydantic import ValidationError

# --- FIX 1: genuine nested immutability -------------------------------------


def test_node_properties_reject_item_assignment() -> None:
    n = SemanticNode(node_id="p1", type="Person", properties={"a": 1})
    with pytest.raises(TypeError):
        n.properties["a"] = 999  # type: ignore[index]


def test_node_properties_reject_key_addition() -> None:
    n = SemanticNode(node_id="p1", type="Person", properties={"a": 1})
    with pytest.raises(TypeError):
        n.properties["b"] = 2  # type: ignore[index]


def test_node_properties_reject_deletion() -> None:
    n = SemanticNode(node_id="p1", type="Person", properties={"a": 1})
    with pytest.raises(TypeError):
        del n.properties["a"]  # type: ignore[attr-defined]


def test_relationship_properties_are_immutable() -> None:
    r = SemanticRelationship(
        relationship_id="r1", type="X", source_id="a", target_id="b", properties={"k": 1}
    )
    with pytest.raises(TypeError):
        r.properties["k"] = 2  # type: ignore[index]


def test_caller_input_dict_cannot_mutate_model_afterward() -> None:
    src: dict[str, object] = {"a": 1}
    n = SemanticNode(node_id="p1", type="Person", properties=src)  # type: ignore[arg-type]
    src["a"] = 999
    src["b"] = 2
    assert n.properties["a"] == 1  # not aliased to the caller's dict
    assert "b" not in n.properties


def test_mutation_through_graph_returned_node_fails() -> None:
    g = SemanticGraph(nodes=(SemanticNode(node_id="p1", type="Person", properties={"a": 1}),))
    got = g.node("p1")
    assert got is not None
    with pytest.raises(TypeError):
        got.properties["a"] = 2  # type: ignore[index]


def test_field_reassignment_still_fails() -> None:
    n = SemanticNode(node_id="p1", type="Person")
    with pytest.raises(ValidationError):
        n.node_id = "p2"


def test_immutable_properties_preserve_dump_and_equality() -> None:
    a = SemanticNode(node_id="p1", type="Person", properties={"b": 1, "a": 2})
    b = SemanticNode(node_id="p1", type="Person", properties={"a": 2, "b": 1})
    assert a == b
    assert a.model_dump() == b.model_dump()
    assert a.model_dump()["properties"] == {"a": 2, "b": 1}  # sorted, plain dict


# --- FIX 2: bounded collections + pagination --------------------------------


def test_offset_at_limit_ok_above_limit_fails() -> None:
    assert Pagination(limit=1, offset=MAX_PAGE_OFFSET).offset == MAX_PAGE_OFFSET
    with pytest.raises(ValidationError):
        Pagination(limit=1, offset=MAX_PAGE_OFFSET + 1)


def test_extreme_offset_fails_cleanly() -> None:
    with pytest.raises(ValidationError):
        Pagination(limit=1, offset=10**18)


def test_selector_ids_at_and_above_limit() -> None:
    ok = NodeSelector(ids=tuple(f"n{i}" for i in range(MAX_SELECTOR_IDS)))
    assert len(ok.ids) == MAX_SELECTOR_IDS
    with pytest.raises(ValidationError):
        NodeSelector(ids=tuple(f"n{i}" for i in range(MAX_SELECTOR_IDS + 1)))


def test_filter_conditions_width_at_and_above_limit() -> None:
    conds = tuple(
        FilterCondition(field=f"f{i}", operator=FilterOperator.EQ, value=i)
        for i in range(MAX_FILTER_CONDITIONS)
    )
    assert len(SemanticFilter(conditions=conds).conditions) == MAX_FILTER_CONDITIONS
    over = conds + (FilterCondition(field="x", operator=FilterOperator.EQ, value=0),)
    with pytest.raises(ValidationError):
        SemanticFilter(conditions=over)


def test_filter_groups_width_at_and_above_limit() -> None:
    leaf = SemanticFilter(
        conditions=(FilterCondition(field="a", operator=FilterOperator.EQ, value=1),)
    )
    groups = tuple(leaf for _ in range(MAX_FILTER_GROUPS))
    assert len(SemanticFilter(groups=groups).groups) == MAX_FILTER_GROUPS
    with pytest.raises(ValidationError):
        SemanticFilter(groups=groups + (leaf,))


def test_projection_fields_at_and_above_limit() -> None:
    fields = tuple(f"f{i}" for i in range(MAX_PROJECTION_FIELDS))
    assert len(SemanticProjection(fields=fields).fields) == MAX_PROJECTION_FIELDS
    with pytest.raises(ValidationError):
        SemanticProjection(fields=fields + ("extra",))


def test_ordering_keys_at_and_above_limit() -> None:
    keys = tuple(SortKey(field=f"f{i}") for i in range(MAX_ORDERING_KEYS))
    assert len(SemanticOrdering(keys=keys).keys) == MAX_ORDERING_KEYS
    with pytest.raises(ValidationError):
        SemanticOrdering(keys=keys + (SortKey(field="extra"),))


def test_zero_and_negative_pagination_still_rejected() -> None:
    with pytest.raises(ValidationError):
        Pagination(limit=0)
    with pytest.raises(ValidationError):
        Pagination(offset=-1)


# --- FIX 3: string / identifier validation ----------------------------------

_UNSAFE = {
    "NUL": "a\x00b",
    "control": "a\x01b",
    "newline": "a\nb",
    "carriage-return": "a\rb",
    "tab": "a\tb",
    "bidi-RLO": "a‮b",
    "bidi-LRI": "a⁦b",
    "zero-width-RLM": "a‏b",
    "whitespace-only": "   ",
    "empty": "",
}


@pytest.mark.parametrize("label", list(_UNSAFE.values()), ids=list(_UNSAFE))
def test_node_id_rejects_unsafe_strings(label: str) -> None:
    with pytest.raises(ValidationError):
        SemanticNode(node_id=label, type="Person")


@pytest.mark.parametrize("label", list(_UNSAFE.values()), ids=list(_UNSAFE))
def test_node_type_rejects_unsafe_strings(label: str) -> None:
    with pytest.raises(ValidationError):
        SemanticNode(node_id="p1", type=label)


@pytest.mark.parametrize("label", list(_UNSAFE.values()), ids=list(_UNSAFE))
def test_filter_field_rejects_unsafe_strings(label: str) -> None:
    with pytest.raises(ValidationError):
        FilterCondition(field=label, operator=FilterOperator.EQ, value=1)


def test_relationship_type_and_endpoints_reject_unsafe() -> None:
    with pytest.raises(ValidationError):
        SemanticRelationship(relationship_id="r1", type="A\nB", source_id="a", target_id="b")
    with pytest.raises(ValidationError):
        SemanticRelationship(relationship_id="r1", type="X", source_id="a\x00", target_id="b")


def test_traversal_projection_ordering_fields_reject_unsafe() -> None:
    with pytest.raises(ValidationError):
        TraversalStep(relationship_types=("OK", "BAD‮"))
    with pytest.raises(ValidationError):
        SemanticProjection(fields=("ok", "bad\x00"))
    with pytest.raises(ValidationError):
        SortKey(field="bad\r")


def test_property_keys_reject_unsafe() -> None:
    with pytest.raises(ValidationError):
        SemanticNode(node_id="p1", type="Person", properties={"bad\x00key": 1})


def test_legitimate_unicode_labels_are_preserved() -> None:
    # Non-control, non-bidi Unicode (Arabic, accented Latin, CJK) is allowed.
    for label in ("مؤسسة", "Café", "组织", "Zürich_Hub-1"):
        n = SemanticNode(node_id=label, type="Person")
        assert n.node_id == label


def test_ensure_safe_label_is_exported_and_pure() -> None:
    assert sl.ensure_safe_label("Valid_Label-1") == "Valid_Label-1"
    with pytest.raises(ValueError):
        sl.ensure_safe_label("bad\x00")


# --- FIX 4/6: filter nesting exactly at and above the depth limit ------------


def test_filter_nesting_at_and_above_depth_limit() -> None:
    node = SemanticFilter(
        conditions=(FilterCondition(field="a", operator=FilterOperator.EQ, value=1),)
    )
    for _ in range(MAX_FILTER_DEPTH - 1):
        node = SemanticFilter(groups=(node,))
    assert node.depth == MAX_FILTER_DEPTH
    with pytest.raises(ValidationError):
        SemanticFilter(groups=(node,))


# --- FIX 5: deterministic planning ------------------------------------------


def test_repeated_planning_is_identical(full_query: SemanticQuery) -> None:
    p1, p2 = plan(full_query), plan(full_query)
    assert p1 == p2
    assert p1.model_dump() == p2.model_dump()


def test_plan_step_detail_is_descriptive_not_executable() -> None:
    """Option B contract: detail is human-readable text, not an executable form.
    The machine-consumable part is `kind`; parameters live on the query."""
    q = SemanticQuery(
        selector=NodeSelector(type="Person"), pagination=Pagination(limit=10, offset=5)
    )
    for step in plan(q).steps:
        assert isinstance(step.detail, str)


# --- FIX 5: result-forgery trust boundary (documented, intentionally possible)


def test_result_model_can_be_constructed_but_is_consistency_checked() -> None:
    """`SemanticResult`/`PageInfo` are output DTOs: constructable in Python (the
    documented trust boundary — a consumer must obtain them from an executor, not
    fabricate them), but still internally consistency-checked."""
    graph = SemanticGraph(nodes=(SemanticNode(node_id="x", type="T"),))
    ok = SemanticResult(graph=graph, page=PageInfo(limit=10, offset=0, returned_count=1))
    assert ok.page.returned_count == len(ok.graph.nodes)
    # A forged page whose count contradicts the graph is rejected.
    with pytest.raises(ValidationError):
        SemanticResult(graph=graph, page=PageInfo(limit=10, offset=0, returned_count=5))


# --- FIX 5: executor protocol misuse ----------------------------------------


def test_executor_protocol_rejects_missing_method() -> None:
    class NoExecute:
        pass

    assert not isinstance(NoExecute(), SemanticQueryExecutor)


def test_executor_protocol_accepts_conforming_double() -> None:
    class Conforming:
        def execute(self, query: SemanticQuery) -> SemanticResult:
            return SemanticResult(
                graph=SemanticGraph(),
                page=PageInfo(
                    limit=query.pagination.limit, offset=query.pagination.offset, returned_count=0
                ),
            )

    assert isinstance(Conforming(), SemanticQueryExecutor)


def test_over_deep_traversal_via_model_construct_raises_semantic_error() -> None:
    from emg_semantic_layer import SemanticTraversal
    from emg_semantic_layer.limits import MAX_TRAVERSAL_DEPTH

    over = SemanticTraversal.model_construct(
        steps=tuple(TraversalStep() for _ in range(MAX_TRAVERSAL_DEPTH + 1))
    )
    q = SemanticQuery.model_construct(
        selector=NodeSelector(type="Person"),
        traversal=over,
        filter=None,
        projection=None,
        ordering=None,
        pagination=Pagination(),
    )
    with pytest.raises(SemanticQueryError):
        plan(q)
