"""HTTP-layer classification enforcement for the Knowledge Graph Query API
(ADR-026 Revision 2, Group D8).

This module contains only pure functions. It holds no FastAPI dependency, no
route, and is not wired into `routers/knowledge_graph.py` yet — that wiring
is Group D9 (Batch 2), a deliberately separate change so this batch stays a
single, reviewable unit.

**Mechanism (ADR-026 Revision 2 §8.2):** every function here re-evaluates
the *exact same* `PolicyEnforcementPoint.authorize()` -> `PolicyEngine.evaluate()`
-> `Decision` pipeline `authorization.py`'s `require_permission` already uses
for operation-level authorization (ADR-025 Group C5, C6) — called once more
per returned object, with `resource_attributes={"classification": <value>}`
added to the request. There is no second authorization engine, no
standalone comparator, and no classification ranking/dominance table
anywhere in this module: "is this classification within the caller's
clearance" is answered exclusively by asking the Policy Engine, exactly as
ADR-026 Revision 2 Appendix A's governing principles require.

`resource_type`/`action` are supplied by the caller (the future D9 router
wiring) rather than owned by this module, mirroring `require_permission`'s
own factory-parameter style and its `DEFAULT_ACTION` reuse — see
`authorization.py`. This also keeps the import direction one-way: this
module depends on `authorization.py` and `emg_auth_client`/
`emg_knowledge_graph.results` only, never on `routers/knowledge_graph.py`,
so D9 can import *this* module without creating a cycle.

**Uniform denial (ADR-026 Revision 2 §8.5):** a classification-denied
object must be indistinguishable from a non-existent one. This module never
introduces a new error type or HTTP status code — it only prunes items from
collections (`filter_*`) or replaces a single object with `None` /
"not found" (`gate_*`), so each endpoint's *existing* not-found/empty/no-value
shape (D9's job to apply) is what the caller ultimately sees.

**Traversal semantics (ADR-026 Revision 2 §8.6):**
- `filter_entities`/`filter_edges`/`list_neighbors`-style listings prune.
- A neighbor is hidden if *either* the neighboring entity's classification
  *or* the connecting edge's classification exceeds clearance
  (`filter_neighbors` checks both).
- `find_shortest_path` never recomputes an alternate path: if any node or
  edge on the single already-computed path exceeds clearance, the whole
  path becomes `found=False` (`gate_path`).
- `get_entity_history` gates on the subject node's own classification,
  becoming `item=None` if not cleared (`gate_history_fact`), which (Batch 2
  remediation) also clears `classification` itself to `None` in that case —
  the true value is used only to make the decision, never left on the
  object returned once that decision is "deny".
"""

from __future__ import annotations

from collections.abc import Iterable

from emg_auth_client import AuthorizationRequest, AuthorizedIdentity, PolicyEnforcementPoint
from emg_common_types import Classification
from emg_knowledge_graph.results import (
    EdgeDetails,
    EntityDetails,
    EntityHistoryResult,
    EntitySummary,
    NeighborResult,
    PathResult,
)

from .authorization import DEFAULT_ACTION

_NOT_FOUND_PATH = PathResult(
    node_ids=(),
    edge_ids=(),
    length=0,
    found=False,
    node_classifications=(),
    edge_classifications=(),
)


def _classification_allowed(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    action: str,
    classification: Classification,
    decision_cache: dict[Classification, bool] | None = None,
) -> bool:
    """The single point every function in this module calls to ask "is
    `classification` within `principal`'s clearance" — always via the
    shared `PolicyEnforcementPoint`/`PolicyEngine`, never a local
    comparison."""
    if decision_cache is not None and classification in decision_cache:
        return decision_cache[classification]
    request = AuthorizationRequest(
        principal=principal,
        resource_type=resource_type,
        action=action,
        resource_attributes={"classification": classification.value},
    )
    decision = pep.authorize(request)
    if decision_cache is not None:
        decision_cache[classification] = decision.allowed
    return decision.allowed


def filter_entities(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    items: Iterable[EntitySummary],
    action: str = DEFAULT_ACTION,
    decision_cache: dict[Classification, bool] | None = None,
) -> tuple[EntitySummary, ...]:
    """Prune `items` to those whose own classification is within
    `principal`'s clearance, preserving order."""
    return tuple(
        item
        for item in items
        if _classification_allowed(
            pep, principal, resource_type, action, item.classification, decision_cache
        )
    )


def filter_edges(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    items: Iterable[EdgeDetails],
    action: str = DEFAULT_ACTION,
    decision_cache: dict[Classification, bool] | None = None,
) -> tuple[EdgeDetails, ...]:
    """Prune `items` to those whose own classification is within
    `principal`'s clearance, preserving order."""
    return tuple(
        item
        for item in items
        if _classification_allowed(
            pep, principal, resource_type, action, item.classification, decision_cache
        )
    )


def filter_neighbors(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    items: Iterable[NeighborResult],
    action: str = DEFAULT_ACTION,
) -> tuple[NeighborResult, ...]:
    """Prune `items` to those where *both* the neighboring entity's
    classification and the traversed edge's classification are within
    `principal`'s clearance (ADR-026 Revision 2 §8.6 — either one exceeding
    clearance hides the neighbor), preserving order."""
    return tuple(
        item
        for item in items
        if _classification_allowed(
            pep, principal, resource_type, action, item.entity.classification
        )
        and _classification_allowed(pep, principal, resource_type, action, item.edge_classification)
    )


def gate_entity(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    item: EntityDetails,
    action: str = DEFAULT_ACTION,
) -> EntityDetails | None:
    """Return `item` unchanged if its classification is within
    `principal`'s clearance, else `None` (the caller applies its own
    existing not-found shape, e.g. raising `EntityNotFoundError`)."""
    if _classification_allowed(pep, principal, resource_type, action, item.summary.classification):
        return item
    return None


def gate_edge(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    item: EdgeDetails,
    action: str = DEFAULT_ACTION,
) -> EdgeDetails | None:
    """Return `item` unchanged if its classification is within
    `principal`'s clearance, else `None` (the caller applies its own
    existing not-found shape, e.g. raising `EntityNotFoundError`)."""
    if _classification_allowed(pep, principal, resource_type, action, item.classification):
        return item
    return None


def gate_path(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    path: PathResult,
    action: str = DEFAULT_ACTION,
) -> PathResult:
    """Return `path` unchanged if every node and edge on it is within
    `principal`'s clearance; otherwise return the same `found=False` /
    empty-tuple shape `find_shortest_path` already returns for an
    unreachable pair (ADR-026 Revision 2 §8.6: never recompute an alternate
    path — the whole result becomes "not found").

    A `path` that is already `found=False` is returned unchanged: there is
    nothing to gate on an empty path.
    """
    if not path.found:
        return path

    classifications = path.node_classifications + path.edge_classifications
    if all(
        _classification_allowed(pep, principal, resource_type, action, classification)
        for classification in classifications
    ):
        return path
    return _NOT_FOUND_PATH


def gate_history_fact(
    pep: PolicyEnforcementPoint,
    principal: AuthorizedIdentity,
    resource_type: str,
    result: EntityHistoryResult,
    action: str = DEFAULT_ACTION,
) -> EntityHistoryResult:
    """Return `result` unchanged if the subject node's classification is
    within `principal`'s clearance; otherwise return a copy with both `item`
    and `classification` replaced by `None` — the same shape
    `get_entity_history` already returns when the attribute had no value at
    the requested moment (ADR-026 Revision 2 §8.5's uniform denial
    principle).

    **Batch 2 remediation:** the denied branch used to preserve the real
    `classification` value on the returned object even though `item` was
    redacted — an audited finding, since "may remain available internally
    only for authorization" cannot hold for a value still sitting in a
    field on the object handed back to the router. The true value is used
    here, internally, to make the one decision it exists for, and is never
    placed in the object this function returns once that decision is
    "deny". `result.classification is None` on entry means an already-denied
    result is being gated again (e.g. a caller re-applying this function) —
    treated as a safe no-op rather than re-deriving or re-exposing anything.
    """
    if result.classification is None:
        return result
    if _classification_allowed(pep, principal, resource_type, action, result.classification):
        return result
    return EntityHistoryResult(
        item=None,
        revision_context=result.revision_context,
        classification=None,
    )
