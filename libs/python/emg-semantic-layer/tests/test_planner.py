"""Planner tests (FEAT-05-4): canonical order, determinism, conditional steps,
and deterministic-execution-model semantics. The planner executes nothing."""

from __future__ import annotations

from emg_semantic_layer import (
    NodeSelector,
    Pagination,
    PlanStepKind,
    SemanticFilter,
    SemanticOrdering,
    SemanticProjection,
    SemanticQuery,
    SemanticTraversal,
    SortKey,
    TraversalStep,
    plan,
)


def test_minimal_plan_is_select_then_paginate() -> None:
    q = SemanticQuery(selector=NodeSelector(type="Person"))
    assert plan(q).kinds() == (PlanStepKind.SELECT, PlanStepKind.PAGINATE)


def test_full_plan_canonical_order(full_query: SemanticQuery) -> None:
    assert plan(full_query).kinds() == (
        PlanStepKind.SELECT,
        PlanStepKind.TRAVERSE,
        PlanStepKind.FILTER,
        PlanStepKind.ORDER,
        PlanStepKind.PAGINATE,
        PlanStepKind.PROJECT,
    )


def test_plan_is_deterministic(full_query: SemanticQuery) -> None:
    assert plan(full_query).model_dump() == plan(full_query).model_dump()


def test_plan_step_indices_are_sequential(full_query: SemanticQuery) -> None:
    steps = plan(full_query).steps
    assert [s.index for s in steps] == list(range(len(steps)))


def test_traversal_emits_one_step_per_hop() -> None:
    q = SemanticQuery(
        selector=NodeSelector(type="Person"),
        traversal=SemanticTraversal(
            steps=(
                TraversalStep(relationship_types=("A",)),
                TraversalStep(relationship_types=("B",)),
            )
        ),
    )
    kinds = plan(q).kinds()
    assert kinds.count(PlanStepKind.TRAVERSE) == 2


def test_match_all_filter_is_not_planned() -> None:
    q = SemanticQuery(selector=NodeSelector(type="Person"), filter=SemanticFilter())
    assert PlanStepKind.FILTER not in plan(q).kinds()


def test_projection_all_is_not_planned() -> None:
    q = SemanticQuery(selector=NodeSelector(type="Person"), projection=SemanticProjection())
    assert PlanStepKind.PROJECT not in plan(q).kinds()


def test_paginate_always_present() -> None:
    q = SemanticQuery(selector=NodeSelector(type="Person"), pagination=Pagination(limit=10))
    paginate = [s for s in plan(q).steps if s.kind is PlanStepKind.PAGINATE]
    assert len(paginate) == 1
    assert "limit 10" in paginate[0].detail


def test_ordering_detail_preserves_key_order() -> None:
    q = SemanticQuery(
        selector=NodeSelector(type="Person"),
        ordering=SemanticOrdering(keys=(SortKey(field="a"), SortKey(field="b"))),
    )
    order = [s for s in plan(q).steps if s.kind is PlanStepKind.ORDER][0]
    assert order.detail.index("a") < order.detail.index("b")


def test_plan_is_immutable(full_query: SemanticQuery) -> None:
    import pytest
    from pydantic import ValidationError

    p = plan(full_query)
    with pytest.raises(ValidationError):
        p.steps = ()
