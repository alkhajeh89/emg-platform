"""Deterministic lifecycle validation (FEAT-05-5).

`LifecycleValidator` provides the validation surfaces:

  * `validate_chain(...)` — a **non-raising** pass that enumerates *every* problem
    in a set of versions as a typed `ChainValidationReport` (useful for a caller
    that wants to report all issues at once), and
  * `assert_valid_chain(...)` — constructs a `VersionChain`, raising the typed
    `InvalidChainError` on the first structural problem.

It also validates transitions and events against the fixed state machine and an
optional `LifecyclePolicy`.

There is exactly **one** chain-analysis implementation, `find_chain_issues`, used
by both `validate_chain` and the `VersionChain` constructor — there is no
duplicate cycle algorithm. It is **O(N)**: cycle detection is a single
three-colour DFS over the parent "functional graph" (each version has at most one
parent), so every node is entered a bounded number of times regardless of chain
depth. Everything is pure and deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from .errors import InvalidTransitionError, MissingReasonError
from .events import LifecycleEvent
from .limits import MAX_CHAIN_SIZE
from .policy import DEFAULT_LIFECYCLE_POLICY, LifecyclePolicy
from .states import ALL_STATES, VersionState, is_valid_transition
from .version import KnowledgeVersion

if TYPE_CHECKING:
    from .chain import VersionChain


class ChainIssueKind(str, Enum):
    """The kind of problem found in a version chain."""

    EMPTY = "empty"
    TOO_LARGE = "too_large"
    MIXED_ENTITY = "mixed_entity"
    DUPLICATE_IDENTIFIER = "duplicate_identifier"
    ORPHANED_PARENT = "orphaned_parent"
    SELF_PARENT = "self_parent"
    CROSS_ENTITY_PARENT = "cross_entity_parent"
    NON_DECREASING_PARENT = "non_decreasing_parent"
    DUPLICATE_ACTIVE = "duplicate_active"
    CYCLE = "cycle"
    INVALID_STATE = "invalid_state"
    INVALID_EFFECTIVE_WINDOW = "invalid_effective_window"


class ChainIssue(BaseModel):
    """One typed problem found during validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ChainIssueKind
    detail: str


class ChainValidationReport(BaseModel):
    """The immutable result of validating a set of versions. `valid` is True iff
    no issues were found."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    issues: tuple[ChainIssue, ...]

    def issues_of(self, kind: ChainIssueKind) -> tuple[ChainIssue, ...]:
        return tuple(i for i in self.issues if i.kind is kind)


# Three-colour DFS states for cycle detection.
_GREY = "grey"  # on the current DFS path
_BLACK = "black"  # fully explored, known acyclic


def find_chain_issues(versions: Sequence[KnowledgeVersion]) -> list[ChainIssue]:
    """The single authoritative chain analysis. Enumerates every structural
    problem in `versions` in a deterministic order, without raising. **O(N)** in
    the number of versions (cycle detection is a single three-colour DFS over the
    parent graph; each node is coloured at most once). Used by both
    `LifecycleValidator.validate_chain` and the `VersionChain` constructor."""
    issues: list[ChainIssue] = []

    def add(kind: ChainIssueKind, detail: str) -> None:
        issues.append(ChainIssue(kind=kind, detail=detail))

    n = len(versions)
    if n == 0:
        add(ChainIssueKind.EMPTY, "a version chain must contain at least one version")
        return issues
    if n > MAX_CHAIN_SIZE:
        add(ChainIssueKind.TOO_LARGE, f"{n} versions exceeds maximum {MAX_CHAIN_SIZE}")

    entity_ids = {v.entity_id for v in versions}
    if len(entity_ids) != 1:
        add(ChainIssueKind.MIXED_ENTITY, f"multiple entity_ids: {sorted(entity_ids)}")

    seen_keys: set[str] = set()
    for v in versions:
        key = v.identifier.key
        if key in seen_keys:
            add(ChainIssueKind.DUPLICATE_IDENTIFIER, f"duplicate identifier {key}")
        seen_keys.add(key)

    by_id: dict[str, KnowledgeVersion] = {v.identifier.key: v for v in versions}

    for v in versions:
        if v.state not in ALL_STATES:
            add(ChainIssueKind.INVALID_STATE, f"{v.identifier.key}: invalid state {v.state!r}")
        if v.effective_to is not None and v.effective_to <= v.effective_from:
            add(
                ChainIssueKind.INVALID_EFFECTIVE_WINDOW,
                f"{v.identifier.key}: effective_to not after effective_from",
            )
        parent = v.parent
        if parent is not None:
            if parent == v.identifier:
                add(ChainIssueKind.SELF_PARENT, f"{v.identifier.key} is its own parent")
            if parent.entity_id != v.identifier.entity_id:
                add(
                    ChainIssueKind.CROSS_ENTITY_PARENT,
                    f"{v.identifier.key}: parent {parent.key} is a different entity",
                )
            if parent.version >= v.identifier.version:
                add(
                    ChainIssueKind.NON_DECREASING_PARENT,
                    f"{v.identifier.key}: parent version not lower than child",
                )
            if parent.key not in by_id:
                add(
                    ChainIssueKind.ORPHANED_PARENT,
                    f"{v.identifier.key}: parent {parent.key} not in chain",
                )

    actives = [v.identifier.key for v in versions if v.state is VersionState.ACTIVE]
    if len(actives) > 1:
        add(ChainIssueKind.DUPLICATE_ACTIVE, f"multiple ACTIVE versions: {sorted(actives)}")

    issues.extend(_detect_cycles(versions, by_id))
    return issues


def _detect_cycles(
    versions: Sequence[KnowledgeVersion], by_id: dict[str, KnowledgeVersion]
) -> list[ChainIssue]:
    # Single three-colour DFS over the parent functional graph. Each node is
    # coloured GREY when entered on the current path and BLACK once its (single)
    # ancestor path is known acyclic, so the total work is O(N) regardless of
    # chain depth. A GREY node re-encountered on the same path is a back-edge = a
    # cycle. Orphan/self/etc. are reported elsewhere; here a missing parent simply
    # ends the walk (an acyclic boundary).
    found: list[ChainIssue] = []
    color: dict[str, str] = {}
    for start in versions:
        if color.get(start.identifier.key) is not None:
            continue  # already GREY/BLACK from an earlier walk
        path: list[str] = []
        current: KnowledgeVersion | None = start
        while current is not None:
            key = current.identifier.key
            state = color.get(key)
            if state == _BLACK:
                break  # joins a known-acyclic path
            if state == _GREY:
                found.append(
                    ChainIssue(
                        kind=ChainIssueKind.CYCLE, detail=f"cycle detected in lineage of {key}"
                    )
                )
                break
            color[key] = _GREY
            path.append(key)
            parent = current.parent
            current = by_id.get(parent.key) if parent is not None else None
        for key in path:
            color[key] = _BLACK
    return found


class LifecycleValidator:
    """Stateless, deterministic validation of version graphs, transitions, and
    events."""

    @staticmethod
    def validate_chain(versions: Sequence[KnowledgeVersion]) -> ChainValidationReport:
        """Enumerate every structural problem in `versions` without raising (O(N))."""
        issues = find_chain_issues(versions)
        return ChainValidationReport(valid=not issues, issues=tuple(issues))

    @staticmethod
    def assert_valid_chain(versions: Sequence[KnowledgeVersion]) -> VersionChain:
        """Construct a `VersionChain` (raising `InvalidChainError` on the first
        structural problem)."""
        from .chain import VersionChain

        return VersionChain(versions=tuple(versions))

    @staticmethod
    def validate_transition(
        from_state: VersionState,
        to_state: VersionState,
        policy: LifecyclePolicy = DEFAULT_LIFECYCLE_POLICY,
    ) -> bool:
        """True iff the transition is permitted by the state machine and policy."""
        return policy.permits_transition(from_state, to_state)

    @staticmethod
    def assert_transition(
        from_state: VersionState,
        to_state: VersionState,
        policy: LifecyclePolicy = DEFAULT_LIFECYCLE_POLICY,
    ) -> None:
        """Raise `InvalidTransitionError` if the transition is not permitted."""
        if not policy.permits_transition(from_state, to_state):
            legal = is_valid_transition(from_state, to_state)
            why = "disabled by policy" if legal else "not a legal transition"
            raise InvalidTransitionError(
                f"transition {from_state.value} -> {to_state.value} is not permitted ({why})"
            )

    @staticmethod
    def validate_event(
        event: LifecycleEvent, policy: LifecyclePolicy = DEFAULT_LIFECYCLE_POLICY
    ) -> bool:
        """True iff `event` is permitted under `policy`: its transition is
        permitted, and — when `policy.require_reason` is set — it carries a reason.
        (A whitespace-only reason cannot exist: it is rejected at event
        construction by the safe-text validator.)"""
        if not policy.permits_transition(event.from_state, event.to_state):
            return False
        return not (policy.require_reason and event.reason is None)

    @staticmethod
    def assert_event(
        event: LifecycleEvent, policy: LifecyclePolicy = DEFAULT_LIFECYCLE_POLICY
    ) -> None:
        """Raise if `event` is not permitted under `policy`: `InvalidTransitionError`
        if the transition is disallowed, or `MissingReasonError` if a reason is
        required but absent."""
        LifecycleValidator.assert_transition(event.from_state, event.to_state, policy)
        if policy.require_reason and event.reason is None:
            raise MissingReasonError(
                f"policy requires a reason for the {event.from_state.value} -> "
                f"{event.to_state.value} transition"
            )
