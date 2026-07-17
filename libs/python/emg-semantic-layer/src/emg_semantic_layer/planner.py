"""Deterministic canonical step-order planner (FEAT-05-4).

`plan()` compiles a `SemanticQuery` into an immutable `SemanticPlan`: the
**canonical order** in which the query's logical stages apply, in a fixed
sequence. It is a *step-order* plan, **not** a complete executable representation
— a `PlanStep` carries a `kind` (the logical stage) and a human-readable `detail`
string; the `detail` is descriptive text, and **no executor can or should execute
from it**. A conforming storage binding reads the structured `SemanticQuery`
itself for the operational parameters (which relationship types, which filter
tree, which limit/offset) and uses this plan only to know the canonical order to
apply those stages in, so results are reproducible across backends.

The canonical order is fixed:

    SELECT -> TRAVERSE (one step per hop) -> FILTER -> ORDER -> PAGINATE -> PROJECT

`plan()` also gives a single typed rejection path: a query that is field-valid but
semantically malformed (e.g. names a traversal deeper than the governed maximum)
raises `SemanticQueryError`. Because the individual models already validate
themselves at construction, `plan()` is total for every normally-constructed
query; the explicit re-checks here guard the cross-model invariants (and catch a
query assembled via `model_construct`, which bypasses validation).

This module executes nothing: no store, no driver, no I/O, no randomness, no
wall-clock. Identical queries always produce an identical plan.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from .errors import SemanticQueryError
from .limits import MAX_TRAVERSAL_DEPTH
from .query import NodeSelector, SemanticQuery


class PlanStepKind(str, Enum):
    """The logical stage a plan step represents (the machine-consumable part of a
    step; a binding switches on this, not on `detail`)."""

    SELECT = "select"
    TRAVERSE = "traverse"
    FILTER = "filter"
    ORDER = "order"
    PAGINATE = "paginate"
    PROJECT = "project"


class PlanStep(BaseModel):
    """One ordered step of the canonical step-order plan.

    `kind` is the machine-consumable logical stage. `detail` is a stable,
    **human-readable description only** — it is not code, is never executed, and
    is deliberately not a substitute for the structured `SemanticQuery`: an
    executor must read the query for operational parameters, not parse `detail`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    kind: PlanStepKind
    detail: str


class SemanticPlan(BaseModel):
    """The immutable, deterministic **canonical step-order** for a query: an
    ordered tuple of steps. It states the order stages apply in, not a complete
    executable representation. Identical queries always produce an identical
    plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: tuple[PlanStep, ...]

    def kinds(self) -> tuple[PlanStepKind, ...]:
        return tuple(s.kind for s in self.steps)


def plan(query: SemanticQuery) -> SemanticPlan:
    """Compile `query` into its canonical `SemanticPlan`. Pure and deterministic;
    executes nothing. Raises `SemanticQueryError` on a semantic violation."""
    # Cross-model invariant re-check (defensive; the models enforce these too).
    if query.traversal is not None and query.traversal.depth > MAX_TRAVERSAL_DEPTH:
        raise SemanticQueryError(
            f"traversal depth {query.traversal.depth} exceeds maximum {MAX_TRAVERSAL_DEPTH}"
        )

    steps: list[PlanStep] = []
    idx = 0

    sel = query.selector
    select_detail = _selector_detail(sel)
    steps.append(PlanStep(index=idx, kind=PlanStepKind.SELECT, detail=select_detail))
    idx += 1

    if query.traversal is not None:
        for hop, step in enumerate(query.traversal.steps, start=1):
            rels = ",".join(step.relationship_types) if step.relationship_types else "*"
            detail = f"hop {hop} {step.direction.value} via [{rels}]"
            if step.target_type is not None:
                detail += f" -> :{step.target_type}"
            steps.append(PlanStep(index=idx, kind=PlanStepKind.TRAVERSE, detail=detail))
            idx += 1

    if query.filter is not None and not query.filter.is_match_all():
        steps.append(
            PlanStep(
                index=idx,
                kind=PlanStepKind.FILTER,
                detail=f"filter {query.filter.operator.value} " f"(depth {query.filter.depth})",
            )
        )
        idx += 1

    if query.ordering is not None:
        order_detail = ", ".join(f"{k.field} {k.direction.value}" for k in query.ordering.keys)
        steps.append(PlanStep(index=idx, kind=PlanStepKind.ORDER, detail=order_detail))
        idx += 1

    steps.append(
        PlanStep(
            index=idx,
            kind=PlanStepKind.PAGINATE,
            detail=f"limit {query.pagination.limit} offset {query.pagination.offset}",
        )
    )
    idx += 1

    if query.projection is not None and not query.projection.projects_all():
        fields = ",".join(query.projection.fields)
        steps.append(PlanStep(index=idx, kind=PlanStepKind.PROJECT, detail=f"fields [{fields}]"))
        idx += 1

    return SemanticPlan(steps=tuple(steps))


def _selector_detail(selector: NodeSelector) -> str:
    parts: list[str] = []
    if selector.ids:
        parts.append(f"ids[{len(selector.ids)}]")
    if selector.type is not None:
        parts.append(f":{selector.type}")
    if selector.filter is not None:
        parts.append("filter")
    return "select " + " ".join(parts)
