"""The managed lifecycle state machine (FEAT-05-5).

`VersionState` is the *managed* lifecycle state that FEAT-05-5 owns — the state
machine the ontology deliberately deferred (``emg_ontology.LifecycleStatus``
carries a coarse state as a field and notes "the managed proposed→active→retired
state machine is FEAT-05-5"). This library is the authority for **which
transitions are legal** and adds the operational states the managed lifecycle
needs (`DEPRECATED`, `ARCHIVED`) on top of the ontology's
proposed/active/superseded/retired vocabulary.

The transition relation is a **fixed, deterministic** directed graph — a closed
table, never a caller-supplied rule — so a transition is either in the table or
it is rejected. There is no arbitrary code and no configurable escape hatch.

Alignment with `emg_ontology.LifecycleStatus` (which this library does NOT import,
to keep the dependency direction clean and the library reusable):

    ontology PROPOSED  == VersionState.PROPOSED
    ontology ACTIVE    == VersionState.ACTIVE
    ontology SUPERSEDED== VersionState.SUPERSEDED
    ontology RETIRED   == VersionState.RETIRED
    (DEPRECATED, ARCHIVED are managed-lifecycle refinements with no ontology field)
"""

from __future__ import annotations

from enum import Enum


class VersionState(str, Enum):
    """A managed lifecycle state for a knowledge version."""

    PROPOSED = "proposed"  # created, not yet the authoritative/active version
    ACTIVE = "active"  # the single current authoritative version in its chain
    DEPRECATED = "deprecated"  # still readable, discouraged; end-of-life announced
    SUPERSEDED = "superseded"  # a newer version replaced it; retained history
    ARCHIVED = "archived"  # moved to cold storage; restorable
    RETIRED = "retired"  # withdrawn; end of managed life (may still be archived)


# The fixed, deterministic transition table. A transition (from -> to) is legal
# iff `to` is in `_TRANSITIONS[from]`. Self-transitions are never legal.
_TRANSITIONS: dict[VersionState, frozenset[VersionState]] = {
    VersionState.PROPOSED: frozenset({VersionState.ACTIVE, VersionState.RETIRED}),
    VersionState.ACTIVE: frozenset({VersionState.DEPRECATED, VersionState.SUPERSEDED}),
    VersionState.DEPRECATED: frozenset({VersionState.SUPERSEDED, VersionState.RETIRED}),
    VersionState.SUPERSEDED: frozenset({VersionState.ARCHIVED, VersionState.RETIRED}),
    VersionState.RETIRED: frozenset({VersionState.ARCHIVED}),
    VersionState.ARCHIVED: frozenset({VersionState.SUPERSEDED}),  # restore
}

# Canonical ordering for deterministic iteration / reporting.
ALL_STATES: tuple[VersionState, ...] = (
    VersionState.PROPOSED,
    VersionState.ACTIVE,
    VersionState.DEPRECATED,
    VersionState.SUPERSEDED,
    VersionState.ARCHIVED,
    VersionState.RETIRED,
)

# States in which a version is considered "live" (a readable, non-archived,
# non-retired member of the chain).
LIVE_STATES: frozenset[VersionState] = frozenset(
    {VersionState.PROPOSED, VersionState.ACTIVE, VersionState.DEPRECATED}
)


def is_valid_transition(from_state: VersionState, to_state: VersionState) -> bool:
    """True iff `from_state -> to_state` is a legal managed transition. Pure and
    deterministic; self-transitions return False."""
    return to_state in _TRANSITIONS[from_state]


def allowed_transitions(from_state: VersionState) -> frozenset[VersionState]:
    """The set of states reachable from `from_state` in one legal transition."""
    return _TRANSITIONS[from_state]


def is_restore_transition(from_state: VersionState, to_state: VersionState) -> bool:
    """True iff the transition is the archive->restore transition."""
    return from_state is VersionState.ARCHIVED and to_state is VersionState.SUPERSEDED
